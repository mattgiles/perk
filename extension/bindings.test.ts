// #75 — loadDefaultBindings against the REAL bundled bindings.yaml. The shipped default set
// is the 8 perk skills (all nudge); spot-check the trigger parse for one stage: and one
// command: trigger. The Python plane (tests/test_bindings.py) is the authoritative validator;
// this is the thin TS-side structural parse.

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadDefaultBindings } from "./bindings.ts";

const EXPECTED: ReadonlyArray<readonly [string, string, string]> = [
  ["stage:plan", "perk-plan", "nudge"],
  ["stage:objective-author", "perk-objective-author", "nudge"],
  ["stage:objective-plan", "perk-objective-plan", "nudge"],
  ["stage:implement", "perk-implement", "nudge"],
  ["stage:address", "perk-address", "nudge"],
  ["stage:learn", "perk-learn", "nudge"],
  ["command:objective-reconcile", "perk-objective-reconcile", "nudge"],
  ["command:learn-docs", "perk-learn-docs", "nudge"],
];

test("loadDefaultBindings: returns the 8 shipped default bindings", () => {
  const bindings = loadDefaultBindings();
  assert.deepEqual(
    bindings.map((b) => [b.trigger, b.skill, b.mode]),
    EXPECTED.map((e) => [...e]),
  );
});

test("loadDefaultBindings: splits a stage: trigger into kind/targetId", () => {
  const plan = loadDefaultBindings().find((b) => b.trigger === "stage:plan");
  assert.deepEqual(plan, {
    trigger: "stage:plan",
    kind: "stage",
    targetId: "plan",
    skill: "perk-plan",
    mode: "nudge",
  });
});

test("loadDefaultBindings: splits a command: trigger into kind/targetId", () => {
  const learnDocs = loadDefaultBindings().find((b) => b.trigger === "command:learn-docs");
  assert.deepEqual(learnDocs, {
    trigger: "command:learn-docs",
    kind: "command",
    targetId: "learn-docs",
    skill: "perk-learn-docs",
    mode: "nudge",
  });
});
