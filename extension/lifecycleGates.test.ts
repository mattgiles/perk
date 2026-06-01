// P1.T4b — lifecycle-gate tests (turn-4 §10). The pure gateDecision matrix as units; the dirty-repo
// gate + the guard-only `/implement` driven through a REAL bound offline session (T1 harness) over a
// REAL git repo (gitInit). No LLM / network. Mirrors spike S-B (turn-4 §3.5).

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import type { PlanRef } from "./cache.ts";
import { gateDecision } from "./lifecycleGates.ts";
import { gitInit, loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
import type { WorkflowState } from "./workflowState.ts";

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

/** Load a session over a planted branch + a real git repo (planted first so it commits clean). */
async function loadOverGit(
  cwd: string,
  states: Partial<WorkflowState>[],
  opts: { dirty: boolean; headful?: boolean },
) {
  const file = plantSession(cwd, states);
  gitInit(cwd, { dirty: opts.dirty });
  return loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    headful: opts.headful ?? true,
  });
}

// --- pure policy ------------------------------------------------------------------------

test("gateDecision: cancels only inside an active workflow with a dirty tree", () => {
  assert.equal(gateDecision({ active: true, dirty: true }).cancel, true);
  assert.equal(gateDecision({ active: true, dirty: false }).cancel, false);
  assert.equal(gateDecision({ active: false, dirty: true }).cancel, false);
  assert.equal(gateDecision({ active: false, dirty: false }).cancel, false);
});

// --- live gate matrix -------------------------------------------------------------------

test("gate: dirty + active workflow -> before_fork AND before_switch cancel", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: true });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    const sw = await h.emitLifecycle({ type: "session_before_switch", reason: "resume" });
    assert.equal(fork?.cancel, true, "dirty fork cancels");
    assert.equal(sw?.cancel, true, "dirty switch cancels");
    assert.ok(
      h.notifies.some((n) => /uncommitted changes/.test(n)),
      "loud notify",
    );
  } finally {
    h.dispose();
  }
});

test("gate: clean + active workflow -> allows", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: false });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    assert.notEqual(fork?.cancel, true, "clean fork is allowed");
  } finally {
    h.dispose();
  }
});

test("gate: dirty but NO active workflow -> allows (perk does not interfere)", async () => {
  // mode set, but no active_plan_ref -> not a perk workflow
  const h = await loadOverGit(scaffoldRepo(), [{ run_id: "01RID", mode: "read-write" }], {
    dirty: true,
  });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    assert.notEqual(fork?.cancel, true, "non-workflow fork is not gated");
  } finally {
    h.dispose();
  }
});

test("gate: headless + dirty + active -> cancels (fail-safe, no notify)", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: true, headful: false });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    assert.equal(fork?.cancel, true, "headless dirty fork still cancels");
    assert.equal(h.notifies.length, 0, "headless: no UI notify (stderr only)");
  } finally {
    h.dispose();
  }
});

// --- the guard-only /implement ----------------------------------------------------------

test("/implement: outside an impl worktree -> refuses, points to the cold door", async () => {
  const h = await loadPerkSession({ cwd: scaffoldRepo() });
  try {
    await h.invokeCommand("implement");
    assert.ok(
      h.notifies.some((n) => /cold-only/.test(n)),
      "warned cold-only",
    );
  } finally {
    h.dispose();
  }
});

test("/implement: inside an impl worktree -> acknowledges continue", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    await h.invokeCommand("implement");
    assert.ok(
      h.notifies.some((n) => /already implementing/.test(n)),
      "acknowledged continue",
    );
  } finally {
    h.dispose();
  }
});
