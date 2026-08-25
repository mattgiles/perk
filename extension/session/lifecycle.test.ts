// The session identity lifecycle's pure decision units (`decideClaim` / `deriveForkRunId` /
// `resolveRunStage`) — moved with the definitions from `substrate/workflowState.test.ts` — and
// (below) the two-store `establishSessionIdentity` suite. Each establishment arm has a live
// wiring twin in `extension/sessionLifecycle.test.ts` (the harness suite proving the
// extraction preserved behavior end-to-end); here we prove the operation itself over fakes.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { handoffPath, workflowDir } from "../substrate/cache.ts";
import { decideClaim, deriveForkRunId, resolveRunStage } from "./lifecycle.ts";

/** Plant a handoff blob (optionally carrying `stage`/`consumed`/claim fields) for claim tests. */
function plantHandoff(
  runId: string,
  stage?: string,
  opts: { consumed?: boolean; piSessionId?: string; mode?: string } = {},
): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-stage-"));
  mkdirSync(join(workflowDir(cwd), "handoff"), { recursive: true });
  writeFileSync(
    handoffPath(cwd, runId),
    `${JSON.stringify(
      {
        run_id: runId,
        consumed: opts.consumed ?? false,
        stage,
        mode: opts.mode,
        pi_session_id: opts.piSessionId,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
  return cwd;
}

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

test("decideClaim: a consumed handoff claimed by a DIFFERENT session adopts a child identity", () => {
  const cwd = plantHandoff("01RID", "implement", {
    consumed: true,
    piSessionId: "parent.jsonl",
    mode: "read-write",
  });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", cwd });
  assert.deepEqual(d, {
    action: "adopt",
    source: "env-child",
    childRunId: "01RID.1",
    parentRunId: "01RID",
    mode: "read-write",
  });
});

test("decideClaim: a consumed handoff with NO recorded pi_session_id adopts (unrecorded claimer)", () => {
  const cwd = plantHandoff("01RID", "implement", { consumed: true, mode: "read-only" });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", cwd });
  assert.equal(d.action, "adopt");
  if (d.action === "adopt") {
    assert.equal(d.childRunId, "01RID.1");
    assert.equal(d.mode, "read-only");
  }
});

test("decideClaim: a consumed handoff claimed by the CURRENT session re-claims (idempotent)", () => {
  const cwd = plantHandoff("01RID", "implement", { consumed: true, piSessionId: "me.jsonl" });
  const d = decideClaim({ state: {}, currentSessionId: "me.jsonl", envRunId: "01RID", cwd });
  assert.deepEqual(d, { action: "claim", source: "env", runId: "01RID" });
});

test("decideClaim: an unconsumed handoff stays the normal cold claim", () => {
  const cwd = plantHandoff("01RID", "implement", { consumed: false });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", cwd });
  assert.deepEqual(d, { action: "claim", source: "env", runId: "01RID" });
});

test("decideClaim: adopt derives past existing siblings", () => {
  const cwd = plantHandoff("01RID", "implement", { consumed: true, piSessionId: "parent.jsonl" });
  mkdirSync(join(cwd, ".perk", "workflow", "scratch", "runs", "01RID.1"), { recursive: true });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", cwd });
  assert.equal(d.action, "adopt");
  if (d.action === "adopt") assert.equal(d.childRunId, "01RID.2");
});

test("resolveRunStage: adopt carries no launched stage", () => {
  const cwd = plantHandoff("01RID", "implement", { consumed: true, piSessionId: "parent.jsonl" });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", cwd });
  assert.equal(d.action, "adopt");
  assert.equal(resolveRunStage(d, cwd), null);
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
  const runs = join(dir, ".perk", "workflow", "scratch", "runs");
  mkdirSync(join(runs, "01RID.1"), { recursive: true });
  mkdirSync(join(runs, "01RID.2"), { recursive: true });
  assert.equal(deriveForkRunId("01RID", dir), "01RID.3");
  assert.equal(deriveForkRunId("01OTHER", dir), "01OTHER.1");
});
