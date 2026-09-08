// The pure authoring-context eligibility policy (eligibility.ts): the positive-evidence rule,
// the dedicated-stage precedence, the runner suppression, and the literal-true intent read.
// The wired behavior (which installer injects/strips what, over a REAL bound session) lives in
// the plan/provider/session-lifecycle suites; this file pins the policy table itself.

import assert from "node:assert/strict";
import { test } from "node:test";
import { GIST_AUTHOR_STAGE, GIST_SAVE_STAGE } from "../gist/draft.ts";
import { OBJECTIVE_AUTHOR_STAGE, OBJECTIVE_SAVE_STAGE } from "../objective/prose.ts";
import {
  type AuthoringContextInput,
  classifyAuthoringContext,
  DEDICATED_AUTHORING_STAGES,
  hasWarmPlanIntent,
  isDedicatedAuthoringStage,
  isPlanAuthoringEligible,
  PLAN_AUTHORING_STAGES,
  readOnlyModeOf,
} from "./eligibility.ts";

const gated = (state: AuthoringContextInput["state"], runnerChild = false) => ({
  gateActive: true,
  runnerChild,
  state,
});

test("the stage tables are the registry's plan family and the four dedicated authoring stages", () => {
  assert.deepEqual([...PLAN_AUTHORING_STAGES], ["plan", "save", "objective-plan"]);
  assert.deepEqual(
    [...DEDICATED_AUTHORING_STAGES],
    [OBJECTIVE_AUTHOR_STAGE, OBJECTIVE_SAVE_STAGE, GIST_AUTHOR_STAGE, GIST_SAVE_STAGE],
  );
  for (const stage of DEDICATED_AUTHORING_STAGES)
    assert.equal(isDedicatedAuthoringStage(stage), true);
  for (const stage of [...PLAN_AUTHORING_STAGES, "implement", undefined]) {
    assert.equal(isDedicatedAuthoringStage(stage), false, String(stage));
  }
});

test("positive plan evidence: a plan-family stage OR literal warm intent, gated and not a runner", () => {
  for (const stage of PLAN_AUTHORING_STAGES) {
    assert.equal(classifyAuthoringContext(gated({ stage })), "plan", stage);
  }
  // Warm intent alone authorizes plan guidance in an unscoped or non-authoring parent stage
  // WITHOUT rewriting that stage.
  assert.equal(classifyAuthoringContext(gated({ plan_authoring: true })), "plan");
  assert.equal(
    classifyAuthoringContext(gated({ stage: "implement", plan_authoring: true })),
    "plan",
  );
  assert.equal(classifyAuthoringContext(gated({ stage: "audit", plan_authoring: true })), "plan");
  assert.equal(isPlanAuthoringEligible(gated({ stage: "plan" })), true);
});

test("no inference: a bare gate, an unknown stage, a worktree stage, or a non-true intent selects nothing", () => {
  for (const state of [
    {},
    { stage: "implement" },
    { stage: "stack-review" },
    { stage: "audit" },
    { stage: "not-a-stage" },
    { plan_authoring: false },
    { plan_authoring: "true" as unknown as boolean },
    { plan_authoring: 1 as unknown as boolean },
    { plan_authoring: null as unknown as boolean },
    { stage: "implement", plan_authoring: false },
  ]) {
    assert.equal(classifyAuthoringContext(gated(state)), null, JSON.stringify(state));
    assert.equal(isPlanAuthoringEligible(gated(state)), false, JSON.stringify(state));
  }
});

test("the dedicated stages take precedence over plan evidence on the same branch", () => {
  const kinds: Record<string, string> = {
    [OBJECTIVE_AUTHOR_STAGE]: "objective-author",
    [OBJECTIVE_SAVE_STAGE]: "objective-save",
    [GIST_AUTHOR_STAGE]: "gist-author",
    [GIST_SAVE_STAGE]: "gist-save",
  };
  for (const [stage, kind] of Object.entries(kinds)) {
    assert.equal(classifyAuthoringContext(gated({ stage })), kind);
    // A stray warm intent bit never turns a dedicated stage into a plan author.
    assert.equal(classifyAuthoringContext(gated({ stage, plan_authoring: true })), kind);
    assert.equal(isPlanAuthoringEligible(gated({ stage, plan_authoring: true })), false);
  }
});

test("the gate off selects nothing whatever the evidence", () => {
  for (const state of [
    { stage: "plan" },
    { plan_authoring: true },
    { stage: OBJECTIVE_AUTHOR_STAGE },
    { stage: GIST_AUTHOR_STAGE },
  ]) {
    assert.equal(
      classifyAuthoringContext({ gateActive: false, runnerChild: false, state }),
      null,
      JSON.stringify(state),
    );
  }
});

test("a runner child is suppressed even over inherited authoring evidence — every kind, not just plan", () => {
  for (const state of [
    { stage: "plan" },
    { stage: "objective-plan", plan_authoring: true },
    { plan_authoring: true },
    { stage: OBJECTIVE_AUTHOR_STAGE },
    { stage: OBJECTIVE_SAVE_STAGE },
    { stage: GIST_AUTHOR_STAGE },
    { stage: GIST_SAVE_STAGE },
  ]) {
    assert.equal(classifyAuthoringContext(gated(state, true)), null, JSON.stringify(state));
  }
});

test("hasWarmPlanIntent and readOnlyModeOf read literal values only", () => {
  assert.equal(hasWarmPlanIntent({ plan_authoring: true }), true);
  assert.equal(hasWarmPlanIntent({ plan_authoring: false }), false);
  assert.equal(hasWarmPlanIntent({}), false);
  assert.equal(hasWarmPlanIntent({ plan_authoring: "yes" as unknown as boolean }), false);
  assert.equal(readOnlyModeOf({ mode: "read-only" }), true);
  assert.equal(readOnlyModeOf({ mode: "read-write" }), false);
  assert.equal(readOnlyModeOf({}), false);
  assert.equal(readOnlyModeOf({ mode: "READ-ONLY" }), false);
});
