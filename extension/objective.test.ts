// P2.T9 — objective substrate: pure budget/threshold helpers + the live `/objective` round-trip
// (set/clear active_objective + seed the budget marker). Fully offline. See objective.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import type { PlanRef } from "./cache.ts";
import {
  DEFAULT_COMPACT_THRESHOLD,
  findBudgetMarker,
  OBJECTIVE_BUDGET_TYPE,
  rebuildBudget,
  shouldCompact,
  sumAssistantTokens,
} from "./objective.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
import { type BranchEntry, branchOf, type WorkflowState } from "./workflowState.ts";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};
const ACTIVE: Partial<WorkflowState> = {
  run_id: "01RID",
  mode: "read-write",
  active_plan_ref: REF,
};

const asst = (input: number, output: number) =>
  ({ type: "message", message: { role: "assistant", usage: { input, output } } }) as never;
const marker = (objective_id: string, activated_at: string) =>
  ({
    type: "custom",
    customType: OBJECTIVE_BUDGET_TYPE,
    data: { objective_id, activated_at },
  }) as never;

// --- pure helpers -----------------------------------------------------------------------

test("sumAssistantTokens: only after-marker assistant messages; clamps negatives", () => {
  const branch = [
    asst(100, 50), // before marker — ignored
    marker("obj-1", new Date().toISOString()),
    asst(10, 5),
    { type: "message", message: { role: "user", usage: { input: 999, output: 999 } } } as never,
    asst(-3, 7), // negative input clamped to 0
  ];
  // marker at index 1 -> sum entries after it: (10+5) + (0+7) = 22
  assert.equal(sumAssistantTokens(branch, 1), 22);
});

test("findBudgetMarker: returns the latest marker", () => {
  const branch = [
    marker("obj-1", "2020-01-01T00:00:00Z"),
    asst(1, 1),
    marker("obj-2", "2020-02-01T00:00:00Z"),
  ];
  const m = findBudgetMarker(branch);
  assert.equal(m?.objectiveId, "obj-2");
  assert.equal(m?.index, 2);
});

test("findBudgetMarker: null when none present", () => {
  assert.equal(findBudgetMarker([asst(1, 1)]), null);
});

test("rebuildBudget: tokens after marker + elapsed", () => {
  const activated = new Date(Date.now() - 60_000).toISOString();
  const branch = [marker("obj-1", activated), asst(40, 60)];
  const state = rebuildBudget(branch, Date.now());
  assert.equal(state.objectiveId, "obj-1");
  assert.equal(state.tokens, 100);
  assert.ok(state.elapsedMs >= 60_000 - 2000 && state.elapsedMs <= 60_000 + 2000);
});

test("rebuildBudget: inert with no marker", () => {
  assert.deepEqual(rebuildBudget([asst(1, 1)], Date.now()), {
    objectiveId: null,
    tokens: 0,
    elapsedMs: 0,
  });
});

test("shouldCompact: threshold boundaries", () => {
  assert.equal(shouldCompact({ percent: 79, tokens: 1 }, 0.8), false);
  assert.equal(shouldCompact({ percent: 80, tokens: 1 }, 0.8), true);
  assert.equal(shouldCompact({ percent: 95, tokens: 1 }, 0.8), true);
  assert.equal(shouldCompact({ percent: null, tokens: null }, 0.8), false);
  assert.equal(shouldCompact(undefined, 0.8), false);
  assert.equal(DEFAULT_COMPACT_THRESHOLD, 0.8);
});

// --- live round-trip --------------------------------------------------------------------

function budgetMarkers(branch: readonly BranchEntry[]): BranchEntry[] {
  return branch.filter(
    (e) => e.type === "custom" && (e as BranchEntry).customType === OBJECTIVE_BUDGET_TYPE,
  );
}

test("/objective <id> sets active_objective + seeds the budget marker", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    await h.runCommandHandler("objective", "obj-7");
    assert.equal(h.workflowState().active_objective, "obj-7");
    const branch = branchOf(h.session);
    const markers = budgetMarkers(branch);
    assert.equal(markers.length, 1);
    assert.equal((markers[0] as { data?: { objective_id?: string } }).data?.objective_id, "obj-7");
  } finally {
    h.dispose();
  }
});

test("/objective clear nulls active_objective", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ ...ACTIVE, active_objective: "obj-7" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().active_objective, "obj-7");
    await h.runCommandHandler("objective", "clear");
    assert.equal(h.workflowState().active_objective, null);
  } finally {
    h.dispose();
  }
});

test("activation renders the 🎯 segment in the composed `perk` status; no objective widget", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    await h.invokeCommand("objective", "251");
    // The objective segment renders under the single composed `perk` status slot (node 2.3).
    const last = h.statuses.filter((s) => s.slot === "perk").at(-1);
    assert.ok(last?.value?.includes("🎯 251"), `composed status carries 🎯 251: ${last?.value}`);
    // The `perk-objective` widget is retired — nothing is EVER set under that slot.
    assert.equal(
      h.widgets.filter((w) => w.slot === "perk-objective").length,
      0,
      "no perk-objective widget set (retired in node 2.3)",
    );
  } finally {
    h.dispose();
  }
});

test("session_tree rebuild preserves the budget marker", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    await h.runCommandHandler("objective", "obj-9");
    const ids = h.entryIds();
    // navigate to the last entry — rebuild must not throw and the marker survives.
    await h.navigateTo(ids[ids.length - 1] as string);
    const branch = branchOf(h.session);
    assert.ok(findBudgetMarker(branch as never));
    assert.equal(h.workflowState().active_objective, "obj-9");
  } finally {
    h.dispose();
  }
});
