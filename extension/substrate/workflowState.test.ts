import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { type PlanRef, writePlanRef } from "./cache.ts";
import {
  activePlanRef,
  appendWorkflowState,
  appendWorkflowStateClassified,
  type BranchEntry,
  branchCarries,
  branchOf,
  conflictResolutionAttempts,
  type EntrySink,
  nodeClaimsEqual,
  planRefsEqual,
  readNodeClaim,
  rebuildWorkflowState,
  resolveStackObjective,
  setConflictAttempts,
  WORKFLOW_STATE_TYPE,
} from "./workflowState.ts";

/** A live fake: appends land in `entries`, which also backs the BranchSource + ReportTarget. */
function fakeWorld() {
  const entries: BranchEntry[] = [];
  const notifications: string[] = [];
  const sink: EntrySink = {
    appendEntry: (customType, data) =>
      entries.push({ type: "custom", customType, data: data as Record<string, unknown> }),
  };
  const source = {
    sessionManager: { getBranch: () => entries },
    hasUI: true,
    ui: { notify: (message: string) => notifications.push(message) },
  };
  return { entries, notifications, sink, source };
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

test("branchCarries: finds the needle in a custom entry's data", () => {
  const branch = [
    ws({ mode: "read-only" }),
    {
      type: "custom",
      customType: "perk:mode-context",
      data: { content: "[READ-ONLY MODE]\nyou are read-only" },
    },
  ];
  assert.equal(branchCarries(branch, "[READ-ONLY MODE]"), true);
});

test("branchCarries: finds the needle in a message entry's text", () => {
  const branch = [
    {
      type: "message",
      message: { role: "user", content: [{ type: "text", text: "seed [PLAN AUTHORING] seed" }] },
    } as unknown as BranchEntry,
  ];
  assert.equal(branchCarries(branch, "[PLAN AUTHORING]"), true);
});

test("branchCarries: false on a clean branch", () => {
  const branch = [ws({ mode: "read-only" }), ws({ stage: "plan" })];
  assert.equal(branchCarries(branch, "[READ-ONLY MODE]"), false);
  assert.equal(branchCarries([], "[READ-ONLY MODE]"), false);
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

test("rebuild: session_artifacts participates in per-field LWW like any field", () => {
  const v1 = { run_id: "A", name: "draft.md", path: "p", digest: "sha256:1", at: "t1" };
  const v2 = { run_id: "A", name: "draft.md", path: "p", digest: "sha256:2", at: "t2" };
  const state = rebuildWorkflowState([
    ws({ session_artifacts: { "draft.md": v1 } }),
    ws({ session_artifacts: { "draft.md": v2 } }),
  ]);
  assert.deepEqual(state.session_artifacts, { "draft.md": v2 });
});

test("rebuild: /tree re-scan reflects a newly added entry", () => {
  const branch: BranchEntry[] = [ws({ run_id: "A", mode: "read-only" })];
  assert.equal(rebuildWorkflowState(branch).mode, "read-only");
  branch.push(ws({ mode: "read-write" }));
  assert.equal(rebuildWorkflowState(branch).mode, "read-write");
});

test("appendWorkflowState: success — appends, reads back, no report", () => {
  const { notifications, sink, source } = fakeWorld();
  const ok = appendWorkflowState(sink, source, {
    data: { active_objective: "42" },
    field: "active_objective",
    expected: "42",
    scope: "objective-save",
    failure: "active_objective read-back failed for #42",
  });
  assert.equal(ok, true);
  assert.deepEqual(notifications, []);
});

test("appendWorkflowState: dropped write — false + one prefixed report", () => {
  const { notifications, source } = fakeWorld();
  const droppingSink: EntrySink = { appendEntry: () => {} };
  const ok = appendWorkflowState(droppingSink, source, {
    data: { active_objective: "42" },
    field: "active_objective",
    expected: "42",
    scope: "objective-save",
    failure: "active_objective read-back failed for #42",
  });
  assert.equal(ok, false);
  assert.equal(notifications.length, 1);
  assert.ok(notifications[0]?.startsWith("perk: objective-save — "));
  assert.ok(notifications[0]?.includes("active_objective read-back failed for #42"));
});

test("appendWorkflowState: custom equals — planRefsEqual ignores non-identity drift", () => {
  const { entries, notifications, source } = fakeWorld();
  const expected: PlanRef = {
    provider: "github",
    pr_id: "7",
    url: "https://a",
    labels: [],
    objective_id: null,
  };
  // The sink writes a ref differing only in `url` — identity (provider, pr_id) still matches.
  const driftingSink: EntrySink = {
    appendEntry: (customType) =>
      entries.push({
        type: "custom",
        customType,
        data: { active_plan_ref: { provider: "github", pr_id: "7", url: "https://b" } },
      }),
  };
  const ok = appendWorkflowState(driftingSink, source, {
    data: { active_plan_ref: expected },
    field: "active_plan_ref",
    expected,
    scope: "plan-save",
    failure: "plan-ref read-back failed for github:7",
    equals: planRefsEqual,
  });
  assert.equal(ok, true);
  assert.deepEqual(notifications, []);
});

test("appendWorkflowState: never throws — a throwing sink reports and returns false", () => {
  const { notifications, source } = fakeWorld();
  const throwingSink: EntrySink = {
    appendEntry: () => {
      throw new Error("disk full");
    },
  };
  const ok = appendWorkflowState(throwingSink, source, {
    data: { run_id: "01RID" },
    field: "run_id",
    expected: "01RID",
    scope: "workflow-state linkage error",
    failure: "read-back failed for run 01RID",
  });
  assert.equal(ok, false);
  assert.equal(notifications.length, 1);
  assert.ok(notifications[0]?.includes("run_id append threw"));
  assert.ok(notifications[0]?.includes("disk full"));
});

test("appendWorkflowStateClassified: a throwing sink whose field never changed is rejected", () => {
  const { notifications, source } = fakeWorld();
  const throwingSink: EntrySink = {
    appendEntry: () => {
      throw new Error("append refused");
    },
  };
  const result = appendWorkflowStateClassified(throwingSink, source, {
    data: { run_id: "01RID" },
    field: "run_id",
    expected: "01RID",
    scope: "workflow-state linkage error",
    failure: "read-back failed for run 01RID",
  });
  // Proven refusal-before-effect: the entry never landed (the rebuilt field is unchanged).
  assert.equal(result.status, "rejected");
  assert.ok(result.status === "rejected" && /run_id append threw/.test(result.problem));
  assert.equal(notifications.length, 1, "the failure arm still reports loudly");
});

test("appendWorkflowStateClassified: a throw AFTER the entry landed classifies applied", () => {
  const { entries, notifications, source } = fakeWorld();
  const landsThenThrows: EntrySink = {
    appendEntry: (customType, data) => {
      entries.push({ type: "custom", customType, data: data as Record<string, unknown> });
      throw new Error("late explosion");
    },
  };
  const result = appendWorkflowStateClassified(landsThenThrows, source, {
    data: { run_id: "01RID" },
    field: "run_id",
    expected: "01RID",
    scope: "workflow-state linkage error",
    failure: "read-back failed for run 01RID",
  });
  // The read-back is the proof authority: the rebuilt field matches, so the change landed.
  assert.equal(result.status, "applied");
  assert.equal(notifications.length, 1, "the throw is still reported (loud, non-fatal)");
});

test("appendWorkflowStateClassified: a dropped write (read-back miss) stays unverified", () => {
  const { notifications, source } = fakeWorld();
  const droppingSink: EntrySink = { appendEntry: () => {} };
  const result = appendWorkflowStateClassified(droppingSink, source, {
    data: { run_id: "01RID" },
    field: "run_id",
    expected: "01RID",
    scope: "workflow-state linkage error",
    failure: "read-back failed for run 01RID",
  });
  assert.equal(result.status, "unverified");
  assert.ok(result.status === "unverified" && /read-back failed/.test(result.problem));
  assert.equal(notifications.length, 1);
});

test("appendWorkflowState: multi-field data verifies only the named field", () => {
  const { notifications, sink, source } = fakeWorld();
  const ok = appendWorkflowState(sink, source, {
    data: { run_id: "01RID", pi_session_id: "s1", mode: "read-only", stage: "plan" },
    field: "run_id",
    expected: "01RID",
    scope: "workflow-state linkage error",
    failure: "read-back failed for run 01RID",
  });
  assert.equal(ok, true);
  assert.deepEqual(notifications, []);
});

// --- nodeClaimsEqual / readNodeClaim (pure units) -------------------------------------------

test("nodeClaimsEqual: structural objective+node identity; absent equals only absent", () => {
  const a = { objective: "7", node: "1.2" };
  assert.equal(nodeClaimsEqual(a, { objective: "7", node: "1.2" }), true);
  assert.equal(nodeClaimsEqual(a, { objective: "7", node: "1.3" }), false);
  assert.equal(nodeClaimsEqual(a, { objective: "8", node: "1.2" }), false);
  assert.equal(nodeClaimsEqual(a, null), false);
  assert.equal(nodeClaimsEqual(null, null), true);
  assert.equal(nodeClaimsEqual(undefined, null), true);
});

test("readNodeClaim: rebuilt claim, fail-open on malformed/missing", () => {
  const src = (data: unknown): { sessionManager: { getBranch(): unknown[] } } => ({
    sessionManager: {
      getBranch: () => [{ type: "custom", customType: "perk:workflow-state", data }],
    },
  });
  assert.deepEqual(readNodeClaim(src({ objective_node_claim: { objective: "7", node: "1.2" } })), {
    objective: "7",
    node: "1.2",
  });
  assert.equal(readNodeClaim(src({})), null);
  assert.equal(readNodeClaim(src({ objective_node_claim: null })), null);
  assert.equal(readNodeClaim(src({ objective_node_claim: { objective: 7, node: "1.2" } })), null);
  assert.equal(readNodeClaim(src({ objective_node_claim: { objective: "7", node: "" } })), null);
  assert.equal(
    readNodeClaim({
      sessionManager: {
        getBranch: () => {
          throw new Error("boom");
        },
      },
    }),
    null,
  );
});

// --- activePlanRef (the shared worktree-first plan-ref resolution) ------------------------------

const WORKTREE_REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};

const BRANCH_REF: PlanRef = { ...WORKTREE_REF, pr_id: "7", url: "https://gh/o/r/issues/7" };

test("activePlanRef: the worktree plan-ref wins over a branch-carried one", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-apr-"));
  writePlanRef(cwd, WORKTREE_REF);
  const source = {
    cwd,
    sessionManager: { getBranch: () => [ws({ active_plan_ref: BRANCH_REF })] },
  };
  assert.deepEqual(activePlanRef(source), WORKTREE_REF);
});

test("activePlanRef: no worktree file → the rebuilt branch active_plan_ref", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-apr-"));
  const source = {
    cwd,
    sessionManager: { getBranch: () => [ws({ active_plan_ref: BRANCH_REF })] },
  };
  assert.deepEqual(activePlanRef(source), BRANCH_REF);
  // A branch that carries no linkage resolves null (not undefined).
  assert.equal(activePlanRef({ cwd, sessionManager: { getBranch: () => [] } }), null);
});

test("activePlanRef: a throwing getBranch is fail-open → null", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-apr-"));
  const source = {
    cwd,
    sessionManager: {
      getBranch: (): unknown[] => {
        throw new Error("boom");
      },
    },
  };
  assert.equal(activePlanRef(source), null);
});

// --- resolveStackObjective (the shared three-tier stack-objective resolution) --------------------

const STACK_REF: PlanRef = { ...WORKTREE_REF, objective_id: "137" };

test("resolveStackObjective: explicit wins over active_objective and the plan-ref", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-rso-"));
  writePlanRef(cwd, STACK_REF);
  const source = {
    cwd,
    sessionManager: { getBranch: () => [ws({ active_objective: "9" })] },
  };
  assert.equal(resolveStackObjective("42", source), "42");
  // An empty explicit never wins — it falls through to the branch tier.
  assert.equal(resolveStackObjective("", source), "9");
});

test("resolveStackObjective: active_objective beats the plan-ref; the plan-ref is last", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-rso-"));
  writePlanRef(cwd, STACK_REF);
  const withActive = {
    cwd,
    sessionManager: { getBranch: () => [ws({ active_objective: "9" })] },
  };
  assert.equal(resolveStackObjective(undefined, withActive), "9");
  const withoutActive = { cwd, sessionManager: { getBranch: () => [] } };
  assert.equal(resolveStackObjective(undefined, withoutActive), "137");
});

test("resolveStackObjective: a throwing branch read fails open to the plan-ref tier", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-rso-"));
  writePlanRef(cwd, STACK_REF);
  const source = {
    cwd,
    sessionManager: {
      getBranch: (): unknown[] => {
        throw new Error("boom");
      },
    },
  };
  assert.equal(resolveStackObjective(undefined, source), "137");
});

test("resolveStackObjective: nothing resolves → null", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-rso-"));
  assert.equal(
    resolveStackObjective(undefined, { cwd, sessionManager: { getBranch: () => [] } }),
    null,
  );
});

// --- conflictResolutionAttempts / setConflictAttempts (the checked counter seam) ------------------

test("conflictResolutionAttempts: a non-negative integer passes through", () => {
  for (const value of [0, 1, 2, 7]) {
    const source = {
      sessionManager: { getBranch: () => [ws({ conflict_resolution_attempts: value })] },
    };
    assert.equal(conflictResolutionAttempts(source), value);
  }
});

test("conflictResolutionAttempts: a readable but malformed value narrows to 0", () => {
  for (const malformed of [undefined, null, "2", 1.5, -1, { n: 2 }, [2], true]) {
    const source = {
      sessionManager: { getBranch: () => [ws({ conflict_resolution_attempts: malformed })] },
    };
    assert.equal(conflictResolutionAttempts(source), 0, JSON.stringify(malformed) ?? "undefined");
  }
  assert.equal(conflictResolutionAttempts({ sessionManager: { getBranch: () => [] } }), 0);
});

test("conflictResolutionAttempts: a throwing branch read propagates (no catch)", () => {
  const source = {
    sessionManager: {
      getBranch: (): unknown[] => {
        throw new Error("adversarial branch read");
      },
    },
  };
  assert.throws(() => conflictResolutionAttempts(source), /adversarial branch read/);
});

test("setConflictAttempts: a verified append returns true", () => {
  const { entries, sink, source } = fakeWorld();
  entries.push(ws({ conflict_resolution_attempts: 1 }));
  assert.equal(setConflictAttempts(sink, source, { attempts: 2, scope: "submit" }), true);
  assert.equal(rebuildWorkflowState(entries).conflict_resolution_attempts, 2);
});

test("setConflictAttempts: an equal value short-circuits true and appends nothing", () => {
  const { entries, sink, source } = fakeWorld();
  entries.push(ws({ conflict_resolution_attempts: 1 }));
  const before = entries.length;
  assert.equal(setConflictAttempts(sink, source, { attempts: 1, scope: "submit" }), true);
  assert.equal(entries.length, before, "the short-circuit appends nothing");
  // The absent/0 pair short-circuits too (a reset over a clean branch is a no-op).
  const clean = fakeWorld();
  assert.equal(setConflictAttempts(clean.sink, clean.source, { attempts: 0, scope: "s" }), true);
  assert.equal(clean.entries.length, 0);
});

test("setConflictAttempts: an invalid value is refused loudly — false, NO append", () => {
  // The write seam enforces the reader's invariant: persisting a value the reader narrows to 0
  // would silently reopen the conflict budget — invalid states are unrepresentable through the
  // seam.
  for (const invalid of [-1, 1.5, Number.NaN]) {
    const { entries, notifications, sink, source } = fakeWorld();
    entries.push(ws({ conflict_resolution_attempts: 1 }));
    const before = entries.length;
    assert.equal(setConflictAttempts(sink, source, { attempts: invalid, scope: "submit" }), false);
    assert.equal(entries.length, before, `nothing appended for ${invalid}`);
    assert.deepEqual(notifications, [
      `perk: submit — refused an invalid conflict_resolution_attempts write (${invalid}) — ` +
        "the counter is a non-negative integer",
    ]);
  }
});

test("setConflictAttempts: a failed read-back returns false with the increment failure text", () => {
  const { entries, notifications, source } = fakeWorld();
  entries.push(ws({ conflict_resolution_attempts: 1 }));
  const dropping: EntrySink = { appendEntry: () => {} };
  assert.equal(setConflictAttempts(dropping, source, { attempts: 2, scope: "submit" }), false);
  assert.deepEqual(notifications, [
    "perk: submit — conflict_resolution_attempts read-back failed (expected 2)",
  ]);
});

test("setConflictAttempts: a failed reset read-back uses the reset failure text", () => {
  const { entries, notifications, source } = fakeWorld();
  entries.push(ws({ conflict_resolution_attempts: 1 }));
  const dropping: EntrySink = { appendEntry: () => {} };
  assert.equal(
    setConflictAttempts(dropping, source, { attempts: 0, scope: "objective-sync" }),
    false,
  );
  assert.deepEqual(notifications, [
    "perk: objective-sync — conflict_resolution_attempts reset read-back failed (expected 0)",
  ]);
});
