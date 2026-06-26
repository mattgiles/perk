// perk-owned checkpoints: pure step/`[DONE:n]` helpers + the scan-after-marker rebuild +
// the live session round-trip (seed from `## Steps`, advance on turn_end, inert on prose plans,
// headless-safe). Fully offline. See checkpoints.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type PlanRef, planBodyPath } from "../substrate/cache.ts";
import type { WorkflowState } from "../substrate/workflowState.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "../testing/harness.ts";
import {
  CHECKPOINT_TYPE,
  type CheckpointStep,
  computeCurrent,
  extractDoneSteps,
  extractSteps,
  extractWipSteps,
  isInert,
  isPerkCheckpointsReferenceSelected,
  markCompletedSteps,
  rebuildCheckpoint,
  resolvedTodoProviderId,
} from "./checkpoints.ts";

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

// --- todo-provider deferral --------------------------------------------------

/** Write a `[providers]` selection into `cwd`'s `.perk/config.toml`. */
function writeProvidersSelection(cwd: string, body: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), body, "utf8");
}

test("resolvedTodoProviderId / isPerkCheckpointsReferenceSelected: default + foreign + unknown", () => {
  // No config -> the reference todo provider is selected.
  const bare = scaffoldRepo();
  assert.equal(resolvedTodoProviderId(bare), "perk-checkpoints");
  assert.equal(isPerkCheckpointsReferenceSelected(bare), true);

  // A foreign `[providers] todo` selection -> NOT the reference.
  const foreign = scaffoldRepo();
  writeProvidersSelection(foreign, '[providers]\ntodo = "juicesharp-todo"\n');
  assert.equal(resolvedTodoProviderId(foreign), "juicesharp-todo");
  assert.equal(isPerkCheckpointsReferenceSelected(foreign), false);

  // An unknown id falls back to the reference (the resolver's loud-but-non-fatal default).
  const unknown = scaffoldRepo();
  writeProvidersSelection(unknown, '[providers]\ntodo = "no-such-provider"\n');
  assert.equal(resolvedTodoProviderId(unknown), "perk-checkpoints");
  assert.equal(isPerkCheckpointsReferenceSelected(unknown), true);
});

test("deferral: a foreign [providers] todo steps the progress surface aside", async () => {
  const cwd = scaffoldRepo();
  writeProvidersSelection(cwd, '[providers]\ntodo = "juicesharp-todo"\n');
  writeFileSync(planBodyPath(cwd), PLAN_WITH_STEPS, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    // session_start defers silently: NO `perk:checkpoint` entry seeded despite a `## Steps` body.
    const branch = h.session.sessionManager.getBranch() as never as { customType?: string }[];
    assert.equal(
      branch.some((e) => e.customType === CHECKPOINT_TYPE),
      false,
      "no checkpoint entry seeded under a foreign todo selection",
    );
    // ...and no progress status/widget rendered. (The objective controller may clear its own
    // absent segment — composing `perk` to undefined — so assert no *text* ever rendered.)
    assert.equal(
      h.statuses.filter((s) => s.slot === "perk" && s.value !== undefined).length,
      0,
      "no status text rendered while deferred",
    );

    // /checkpoints ANNOUNCES the deferral (the surface-facing mirror of the silent handlers).
    await h.invokeCommand("checkpoints");
    assert.ok(
      h.notifies.some((m) => m.includes("deferred") && m.includes("juicesharp-todo")),
      `\`/checkpoints\` announced the deferral: ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});
