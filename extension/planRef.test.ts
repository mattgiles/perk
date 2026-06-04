// P1.T2b — live plan-ref linkage tests (turn-2b §9). These drive a REAL bound AgentSession via
// the T1 harness and prove the cache.plan-ref -> active_plan_ref reconciliation end-to-end,
// OFFLINE (no LLM, no network, no gh). The pure dedup twin is planRefsEqual in
// workflowState.test.ts; here we prove the wiring on session_start / reload / session_tree / fork.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type PlanRef, writePlanRef } from "./cache.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://github.com/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};

/** Count workflow-state entries on the branch that carry an active_plan_ref (the dedup proof). */
function countPlanRefLinks(branch: readonly unknown[]): number {
  return branch.filter((entry) => {
    const e = entry as { type?: string; customType?: string; data?: Record<string, unknown> };
    return (
      e.type === "custom" &&
      e.customType === WORKFLOW_STATE_TYPE &&
      e.data?.active_plan_ref !== undefined
    );
  }).length;
}

test("link: a cached plan-ref is reconciled into active_plan_ref on session_start", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writePlanRef(cwd, REF);
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(h.workflowState().active_plan_ref, REF);
    assert.deepEqual(h.sentinel()?.active_plan_ref, REF);
  } finally {
    h.dispose();
  }
});

test("no-dup reload: a second session_start does not re-append the same ref", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writePlanRef(cwd, REF);
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const countLinks = () => countPlanRefLinks(h.session.sessionManager.getBranch());
    assert.equal(
      countLinks(),
      1,
      "expected exactly one active_plan_ref entry after the first link",
    );
    await h.reload({ PERK_RUN_ID: undefined });
    assert.equal(countLinks(), 1, "reload must not duplicate the active_plan_ref entry");
    assert.deepEqual(h.workflowState().active_plan_ref, REF);
  } finally {
    h.dispose();
  }
});

test("session_tree: branch navigation preserves active_plan_ref via the LWW rebuild", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writePlanRef(cwd, REF);
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    // The link entry is the leaf (appended last), so the only navigations that fire the tree
    // handler land before or back at it. Hop to a pre-link entry then back to the leaf:
    const branch = h.session.sessionManager.getBranch();
    const preLink = branch[0]?.id as string;
    const leaf = h.session.sessionManager.getLeafId() as string;
    await h.navigateTo(preLink);
    assert.equal(h.sentinel()?.source, "tree");
    // Pre-link branch point: active_plan_ref is correctly absent (LWW, not a bug).
    assert.equal(h.sentinel()?.active_plan_ref, null);
    await h.navigateTo(leaf);
    assert.equal(h.sentinel()?.source, "tree");
    // Back at the leaf: the rebuild restored the ref without re-reading the cache file.
    assert.deepEqual(h.sentinel()?.active_plan_ref, REF);
  } finally {
    h.dispose();
  }
});

// Regression (#43): the root `cache.plan-ref` *selector* must NOT leak into a fresh planning
// session. The root `worktree: none` stages (plan/objective-plan/save) do not consume the ref
// (registry `requires`/`reads`), so session_start must not reconcile it into active_plan_ref.
for (const stage of ["plan", "objective-plan", "save"]) {
  test(`gate: a ${stage} session does not inherit the root plan-ref selector`, async () => {
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage } });
    writePlanRef(cwd, REF);
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
    try {
      // The run is still claimed (run_id linkage is independent of plan-ref reconciliation)…
      assert.equal(h.workflowState().run_id, "01RID");
      // …but the stale root selector never becomes active_plan_ref.
      assert.equal(h.workflowState().active_plan_ref ?? null, null);
      assert.equal(countPlanRefLinks(h.session.sessionManager.getBranch()), 0);
    } finally {
      h.dispose();
    }
  });
}

test("gate: a bare session (no handoff, no PERK_RUN_ID) never reads the plan-ref file", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, REF);
  const h = await loadPerkSession({ cwd });
  try {
    assert.equal(h.workflowState().active_plan_ref ?? null, null);
    assert.equal(countPlanRefLinks(h.session.sessionManager.getBranch()), 0);
  } finally {
    h.dispose();
  }
});

test("fork: a child keeps the inherited ref without re-appending", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, REF);
  // Planted state carries the same ref + a pi_session_id that won't match -> fork.
  const file = plantSession(cwd, [
    { run_id: "01RID", pi_session_id: "OTHER-SESSION", mode: "read-write", active_plan_ref: REF },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.sentinel()?.source, "fork");
    assert.deepEqual(h.workflowState().active_plan_ref, REF);
    // The inherited ref is kept, not re-appended: still exactly one link entry (D4 fork path).
    assert.equal(
      countPlanRefLinks(h.session.sessionManager.getBranch()),
      1,
      "fork must not re-append an already-inherited ref",
    );
  } finally {
    h.dispose();
  }
});
