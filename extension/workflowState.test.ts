import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { handoffPath, type PlanRef, workflowDir } from "./cache.ts";
import {
  type BranchEntry,
  branchOf,
  decideClaim,
  deriveForkRunId,
  planRefsEqual,
  rebuildWorkflowState,
  resolveRunStage,
  WORKFLOW_STATE_TYPE,
} from "./workflowState.ts";

/** Plant a handoff blob (optionally carrying `stage`) for resolveRunStage tests. */
function plantHandoff(runId: string, stage?: string): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-stage-"));
  mkdirSync(join(workflowDir(cwd), "handoff"), { recursive: true });
  writeFileSync(
    handoffPath(cwd, runId),
    `${JSON.stringify({ run_id: runId, consumed: false, stage }, null, 2)}\n`,
    "utf8",
  );
  return cwd;
}

function ws(data: Record<string, unknown>): BranchEntry {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}

test("branchOf: typed seam over sessionManager.getBranch", () => {
  const entries = [ws({ run_id: "r1" })];
  const source = { sessionManager: { getBranch: () => entries } };
  assert.deepEqual(branchOf(source), entries);
  // feeds rebuildWorkflowState without further casting:
  assert.equal(rebuildWorkflowState(branchOf(source)).run_id, "r1");
});

test("planRefsEqual: identity by (provider, pr_id); null only equals null", () => {
  const ref = (provider: string, pr_id: string): PlanRef => ({
    provider,
    pr_id,
    url: `x/${pr_id}`,
    labels: [],
    objective_id: null,
  });
  assert.equal(
    planRefsEqual(ref("github", "42"), { ...ref("github", "42"), url: "different" }),
    true,
  );
  assert.equal(planRefsEqual(ref("github", "42"), ref("github", "43")), false);
  assert.equal(planRefsEqual(ref("github", "42"), ref("jira", "42")), false);
  assert.equal(planRefsEqual(null, null), true);
  assert.equal(planRefsEqual(undefined, null), true);
  assert.equal(planRefsEqual(ref("github", "42"), null), false);
});

test("rebuild: per-field last-write-wins, non-perk entries ignored", () => {
  const state = rebuildWorkflowState([
    ws({ run_id: "A", mode: "read-only" }),
    { type: "custom", customType: "other", data: { run_id: "X" } },
    { type: "message" },
    ws({ mode: "read-write" }),
  ]);
  assert.deepEqual(state, { run_id: "A", mode: "read-write" });
});

test("rebuild: undefined does not clobber, explicit null wins", () => {
  const state = rebuildWorkflowState([
    ws({ run_id: "A", active_plan_ref: { pr_id: "1" } }),
    ws({ run_id: undefined, active_plan_ref: null }),
  ]);
  assert.equal(state.run_id, "A");
  assert.equal(state.active_plan_ref, null);
});

test("rebuild: /tree re-scan reflects a newly added entry", () => {
  const branch: BranchEntry[] = [ws({ run_id: "A", mode: "read-only" })];
  assert.equal(rebuildWorkflowState(branch).mode, "read-only");
  branch.push(ws({ mode: "read-write" }));
  assert.equal(rebuildWorkflowState(branch).mode, "read-write");
});

test("decideClaim: cold env claim when no prior state", () => {
  const d = decideClaim({ state: {}, currentSessionId: "s1", envRunId: "01RID", cwd: "/x" });
  assert.deepEqual(d, { action: "claim", source: "env", runId: "01RID" });
});

test("decideClaim: none when no state and no env", () => {
  const d = decideClaim({ state: {}, currentSessionId: "s1", envRunId: null, cwd: "/x" });
  assert.equal(d.action, "none");
});

test("decideClaim: keep (reload) when pi_session_id matches the current session", () => {
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "s1" },
    currentSessionId: "s1",
    envRunId: null,
    cwd: "/x",
  });
  assert.equal(d.action, "keep");
  assert.equal(d.source, "session");
});

test("decideClaim: fork when run_id was inherited from a different session", () => {
  const dir = mkdtempSync(join(tmpdir(), "perk-ws-"));
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "parent" },
    currentSessionId: "child",
    envRunId: null,
    cwd: dir,
  });
  assert.equal(d.action, "fork");
  if (d.action === "fork") {
    assert.equal(d.parentRunId, "01RID");
    assert.equal(d.childRunId, "01RID.1");
  }
});

test("resolveRunStage: claim reads the stage from the run's handoff", () => {
  const cwd = plantHandoff("01RID", "implement");
  const d = decideClaim({ state: {}, currentSessionId: "s1", envRunId: "01RID", cwd });
  assert.equal(resolveRunStage(d, cwd), "implement");
});

test("resolveRunStage: claim with a stage-less handoff is null", () => {
  const cwd = plantHandoff("01RID");
  const d = decideClaim({ state: {}, currentSessionId: "s1", envRunId: "01RID", cwd });
  assert.equal(d.action, "claim");
  assert.equal(resolveRunStage(d, cwd), null);
});

test("resolveRunStage: keep reads the stage from the kept run's handoff", () => {
  const cwd = plantHandoff("01RID", "submit");
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "s1" },
    currentSessionId: "s1",
    envRunId: null,
    cwd,
  });
  assert.equal(d.action, "keep");
  assert.equal(resolveRunStage(d, cwd), "submit");
});

test("resolveRunStage: keep with no handoff file is null", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-stage-"));
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "s1" },
    currentSessionId: "s1",
    envRunId: null,
    cwd,
  });
  assert.equal(d.action, "keep");
  assert.equal(resolveRunStage(d, cwd), null);
});

test("resolveRunStage: fork and none carry no launched stage", () => {
  const cwd = plantHandoff("01RID", "implement");
  const fork = decideClaim({
    state: { run_id: "01RID", pi_session_id: "parent" },
    currentSessionId: "child",
    envRunId: null,
    cwd,
  });
  assert.equal(fork.action, "fork");
  assert.equal(resolveRunStage(fork, cwd), null);
  const none = decideClaim({ state: {}, currentSessionId: "s1", envRunId: null, cwd });
  assert.equal(none.action, "none");
  assert.equal(resolveRunStage(none, cwd), null);
});

test("deriveForkRunId: increments past existing siblings", () => {
  const dir = mkdtempSync(join(tmpdir(), "perk-fork-"));
  const runs = join(dir, ".pi", "workflow", "scratch", "runs");
  mkdirSync(join(runs, "01RID.1"), { recursive: true });
  mkdirSync(join(runs, "01RID.2"), { recursive: true });
  assert.equal(deriveForkRunId("01RID", dir), "01RID.3");
  assert.equal(deriveForkRunId("01OTHER", dir), "01OTHER.1");
});
