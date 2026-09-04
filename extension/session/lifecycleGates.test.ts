// Pure session-lifecycle policy tests: the implement handoff priming and the planning-stage
// lifecycle-door refusal — no harness, no git, no LLM / network. The registration half (the
// gate:/implement arcs through a real bound session) is covered in
// `pi/v1/lifecycleGates.test.ts`.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { PlanRef } from "../substrate/cache.ts";
import { implementHandoffPrompt, planningStageRefusal } from "./lifecycleGates.ts";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};

test("implementHandoffPrompt: carries the plan forward (read it; never summarize)", () => {
  const prompt = implementHandoffPrompt(REF);
  assert.match(prompt, /implementing perk plan github #42/);
  assert.match(prompt, /gh issue view 42 --comments/);
  assert.match(prompt, /\/submit/);
  // The warm handoff is now unified with the cold/worker primer — it carries the progress tail.
  assert.match(prompt, /Progress tracking:/);
  // …and the validation discipline (run_ci while iterating; a green run-all is terminal).
  assert.match(prompt, /Validation:/);
  // A non-github provider falls back to opening the url.
  const other = implementHandoffPrompt({ ...REF, provider: "gitlab" });
  assert.match(other, /open https:\/\/gh\/o\/r\/issues\/42/);
  // A linear ref renders the pi-mono-linear read recipe.
  const linear = implementHandoffPrompt({ ...REF, provider: "linear" });
  assert.match(linear, /linear_get_issue/);
  assert.match(linear, /linear_list_comments/);
});

test("planningStageRefusal: planning stages refuse; other/absent stages pass", () => {
  const ctxFor = (stage?: string) => ({
    sessionManager: {
      getBranch: () => [
        {
          type: "custom",
          customType: "perk:workflow-state",
          data: { run_id: "01RID", ...(stage !== undefined ? { stage } : {}) },
        },
      ],
    },
  });
  for (const stage of ["plan", "objective-plan"]) {
    const message = planningStageRefusal(ctxFor(stage), "submit");
    assert.ok(message !== null, `${stage} refuses`);
    assert.match(message, /planning session/);
    assert.match(message, /perk impl <N>/);
    assert.match(message, new RegExp(stage));
  }
  for (const stage of ["implement", "address", "learn", undefined]) {
    assert.equal(planningStageRefusal(ctxFor(stage), "submit"), null, `${stage} passes`);
  }
});

test("planningStageRefusal: an unreadable branch refuses (fail-closed)", () => {
  // Without the state the guard cannot prove the session is not a positioned planning session
  // (whose cwd binding is the PREDECESSOR), so an unreadable branch refuses, never allows.
  const throwing = {
    sessionManager: {
      getBranch: () => {
        throw new Error("branch unavailable");
      },
    },
  };
  const message = planningStageRefusal(throwing, "land");
  assert.ok(message !== null, "unreadable state refuses");
  assert.match(message, /could not be read/);
  assert.match(message, /branch unavailable/);
});
