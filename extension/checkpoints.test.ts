// P2.T2c — perk-owned checkpoints: pure step/`[DONE:n]` helpers + the scan-after-marker rebuild +
// the live session round-trip (seed from `## Steps`, advance on turn_end, inert on prose plans,
// headless-safe). Fully offline. See checkpoints.ts.

import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type PlanRef, planBodyPath } from "./cache.ts";
import {
  CHECKPOINT_TYPE,
  type CheckpointStep,
  extractDoneSteps,
  extractSteps,
  isInert,
  markCompletedSteps,
  rebuildCheckpoint,
} from "./checkpoints.ts";
import { loadPerkSession, plantRawSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
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

const PLAN_WITH_STEPS = `# Add retry

## Summary
Add retry to the gateway.

## Steps
1. Add the retry helper
2. Wire it into the client
3. Add a test

## Test plan
Run the suite.
`;

// --- pure helpers -----------------------------------------------------------------------

test("extractSteps: parses a `## Steps` numbered list; inert without one", () => {
  const steps = extractSteps(PLAN_WITH_STEPS);
  assert.deepEqual(
    steps.map((s) => [s.step, s.text, s.completed]),
    [
      [1, "Add the retry helper", false],
      [2, "Wire it into the client", false],
      [3, "Add a test", false],
    ],
  );
  // A prose plan with no `## Steps` -> inert (empty).
  assert.deepEqual(extractSteps("# Title\n\n## Summary\nProse only.\n"), []);
  assert.deepEqual(extractSteps(null), []);
});

test("extractSteps: stops at the next heading", () => {
  const steps = extractSteps("## Steps\n1. one\n2. two\n## Other\n3. not a step\n");
  assert.equal(steps.length, 2);
});

test("extractDoneSteps + markCompletedSteps", () => {
  assert.deepEqual(extractDoneSteps("did [DONE:1] and [DONE:3]"), [1, 3]);
  const steps: CheckpointStep[] = extractSteps(PLAN_WITH_STEPS);
  assert.equal(markCompletedSteps("finished [DONE:2]", steps), 1);
  assert.equal(steps[1]?.completed, true);
  assert.equal(steps[0]?.completed, false);
});

test("rebuildCheckpoint: inert with no checkpoint entry", () => {
  assert.ok(isInert(rebuildCheckpoint([])));
});

test("rebuildCheckpoint: scan-after-marker ignores stale [DONE:n] before the seed", () => {
  // A stale [DONE:2] BEFORE the seed marker must not count; [DONE:1] AFTER it must.
  const built = rebuildCheckpoint([
    { type: "message", message: { role: "assistant", content: "stale [DONE:2]" } } as never,
    {
      type: "custom",
      customType: CHECKPOINT_TYPE,
      data: {
        steps: [
          { step: 1, text: "one", completed: false },
          { step: 2, text: "two", completed: false },
          { step: 3, text: "three", completed: false },
        ],
      },
    } as never,
    { type: "message", message: { role: "assistant", content: "done [DONE:1]" } } as never,
  ]);
  assert.equal(built.steps[0]?.completed, true, "step 1 (after marker) completed");
  assert.equal(built.steps[1]?.completed, false, "stale step 2 (before marker) NOT completed");
});

// --- live round-trip --------------------------------------------------------------------

test("session_start seeds checkpoints from the plan body's `## Steps`", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), PLAN_WITH_STEPS, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const state = rebuildCheckpoint(h.session.sessionManager.getBranch() as never);
    assert.equal(state.steps.length, 3, "seeded 3 steps from `## Steps`");
    assert.equal(isInert(state), false);
  } finally {
    h.dispose();
  }
});

test("a plan WITHOUT `## Steps` yields an inert checkpoint (no crash)", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), "# T\n\n## Summary\nProse only.\n", "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.ok(isInert(rebuildCheckpoint(h.session.sessionManager.getBranch() as never)));
  } finally {
    h.dispose();
  }
});

test("rebuild restored on session_tree across a seeded checkpoint", async () => {
  const cwd = scaffoldRepo();
  // Seed entry, then an assistant [DONE:1], then a second checkpoint marker — navigation rebuilds.
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: CHECKPOINT_TYPE,
        data: {
          steps: [
            { step: 1, text: "one", completed: false },
            { step: 2, text: "two", completed: false },
          ],
        },
      },
    },
    { assistant: "completed [DONE:1]" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const ids = h.entryIds();
    await h.navigateTo(ids[0] as string); // navigate to the seed marker -> session_tree rebuild
    const atSeed = rebuildCheckpoint(h.session.sessionManager.getBranch() as never);
    // At the seed marker (no assistant msgs after it on this branch) nothing is complete.
    assert.equal(
      atSeed.steps.every((s) => !s.completed),
      true,
    );
  } finally {
    h.dispose();
  }
});

test("/checkpoints headless: uses console (no rich-UI throw)", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), PLAN_WITH_STEPS, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    headful: false,
  });
  try {
    // Must not throw on the headless path (setStatus/setWidget are guarded by hasUI).
    await h.invokeCommand("checkpoints");
    assert.ok(true, "headless /checkpoints did not throw");
  } finally {
    h.dispose();
  }
});
