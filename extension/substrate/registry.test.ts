// stageConsumesPlanRef against the REAL bundled registry. The worktree binding stages
// (implement/submit/address/land/learn) list `cache.plan-ref` in requires/reads and so consume
// the selector; the root `worktree: none` stages (plan/objective-plan/save) and unknown ids do
// not. This is the contract that gates session_start plan-ref reconciliation (extension/index.ts).

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadRegistry, PLAN_REF_STATE_KEY, stageConsumesPlanRef } from "./registry.ts";

test("stageConsumesPlanRef: worktree binding stages consume the plan-ref selector", () => {
  const registry = loadRegistry();
  for (const id of ["implement", "submit", "address", "land", "learn"]) {
    assert.equal(
      stageConsumesPlanRef(registry, id),
      true,
      `${id} should consume ${PLAN_REF_STATE_KEY}`,
    );
  }
});

test("stageConsumesPlanRef: root planning stages and unknown ids do not consume it", () => {
  const registry = loadRegistry();
  for (const id of ["plan", "objective-plan", "save", "nonexistent-stage"]) {
    assert.equal(
      stageConsumesPlanRef(registry, id),
      false,
      `${id} should not consume ${PLAN_REF_STATE_KEY}`,
    );
  }
});

test("every stage admits the universal eligible-turn cache.scratch side effect", () => {
  const registry = loadRegistry();
  for (const stage of registry.stages) {
    assert.ok(stage.writes.includes("cache.scratch"), `${stage.id} omits cache.scratch`);
  }
});
