// perk-owned checkpoints: pure step/`[DONE:n]` helpers + the scan-after-marker rebuild
// (the live session round-trip lives in checkpointsRoundTrip.test.ts). Fully offline.
// See checkpoints.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CHECKPOINT_TYPE,
  type CheckpointStep,
  computeCurrent,
  extractDoneSteps,
  extractSteps,
  extractWipSteps,
  isInert,
  markCompletedSteps,
  rebuildCheckpoint,
} from "./checkpoints.ts";

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

test("extractWipSteps: parses `[WIP:n]` case-insensitive", () => {
  assert.deepEqual(extractWipSteps("start [WIP:2] then [wip:3]"), [2, 3]);
  assert.deepEqual(extractWipSteps("no markers"), []);
});

test("computeCurrent: preferred-if-incomplete, else lowest incomplete, else null", () => {
  const steps: CheckpointStep[] = [
    { step: 1, text: "one", completed: true },
    { step: 2, text: "two", completed: false },
    { step: 3, text: "three", completed: false },
  ];
  assert.equal(computeCurrent(steps, 3), 3, "preferred incomplete step honored");
  assert.equal(computeCurrent(steps, 1), 2, "preferred completed -> lowest incomplete");
  assert.equal(computeCurrent(steps, null), 2, "no preference -> lowest incomplete");
  const allDone = steps.map((s) => ({ ...s, completed: true }));
  assert.equal(computeCurrent(allDone, null), null, "all complete -> null");
});

test("rebuildCheckpoint: inert with no checkpoint entry", () => {
  const built = rebuildCheckpoint([]);
  assert.ok(isInert(built));
  assert.equal(built.current, null);
});

test("rebuildCheckpoint: derives `current` from WIP/completion (scan-after-marker)", () => {
  const seed = () =>
    ({
      type: "custom",
      customType: CHECKPOINT_TYPE,
      data: {
        steps: [
          { step: 1, text: "one", completed: false },
          { step: 2, text: "two", completed: false },
          { step: 3, text: "three", completed: false },
        ],
      },
    }) as never;
  const assistant = (content: string) =>
    ({ type: "message", message: { role: "assistant", content } }) as never;

  // explicit `[WIP:2]` after the marker -> current === 2
  assert.equal(rebuildCheckpoint([seed(), assistant("start [WIP:2]")]).current, 2);
  // no WIP -> lowest incomplete (1)
  assert.equal(rebuildCheckpoint([seed(), assistant("working")]).current, 1);
  // WIP pointing at a completed step -> falls back to lowest incomplete (2)
  assert.equal(rebuildCheckpoint([seed(), assistant("done [DONE:1] then [WIP:1]")]).current, 2);
  // all complete -> current === null
  assert.equal(rebuildCheckpoint([seed(), assistant("[DONE:1] [DONE:2] [DONE:3]")]).current, null);
  // a `[WIP:3]` BEFORE the marker is ignored; lowest incomplete wins (1)
  assert.equal(rebuildCheckpoint([assistant("stale [WIP:3]"), seed(), assistant("go")]).current, 1);
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
