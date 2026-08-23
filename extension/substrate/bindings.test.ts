// loadDefaultBindings against the REAL bundled bindings.yaml. The shipped default set
// is the 22 perk skill bindings (all nudge); spot-check the trigger parse for one stage: and one
// command: trigger. (Kept in lockstep with tests/test_bindings.py EXPECTED_DEFAULTS.) The Python plane (tests/test_bindings.py) is the authoritative validator;
// this is the thin TS-side structural parse.

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadDefaultBindings, resolveBindings, type SkillBinding } from "./bindings.ts";

const EXPECTED: ReadonlyArray<readonly [string, string, string]> = [
  ["stage:plan", "perk-plan", "nudge"],
  ["stage:gist-author", "perk-gist-author", "nudge"],
  ["stage:objective-author", "perk-objective-author", "nudge"],
  ["stage:objective-plan", "perk-objective-plan", "nudge"],
  ["stage:implement", "perk-implement", "nudge"],
  ["stage:address", "perk-address", "nudge"],
  ["stage:learn", "perk-learn", "nudge"],
  ["command:objective-reconcile", "perk-objective-reconcile", "nudge"],
  ["command:objective-replan", "perk-objective-replan", "nudge"],
  ["command:replan", "perk-replan", "nudge"],
  ["command:learn-docs", "perk-learn-docs", "nudge"],
  ["command:learn-code", "perk-learn-code", "nudge"],
  ["command:learn-harvest", "perk-learn-harvest", "nudge"],
  ["command:learn-dream", "perk-learn-dream", "nudge"],
  ["command:pr-review", "perk-pr-review", "nudge"],
  ["command:pr-review-dynamic", "perk-pr-review-dynamic", "nudge"],
  ["command:pr-review-terminal", "perk-pr-review-terminal", "nudge"],
  ["command:pr-review-browser", "perk-pr-review-browser", "nudge"],
  ["command:stack-review-browser", "perk-pr-review-browser", "nudge"],
  ["command:plan-review-browser", "perk-plan-review-browser", "nudge"],
  ["command:objective-review-browser", "perk-objective-review-browser", "nudge"],
  ["command:skills-create", "perk-skill-author", "nudge"],
  ["command:skills-refine", "perk-skill-author", "nudge"],
];

test("loadDefaultBindings: returns the shipped default bindings", () => {
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

// --- resolveBindings — mirror of tests/test_bindings.py resolver cases ---

function b(trigger: string, skill: string, mode: string): SkillBinding {
  const idx = trigger.indexOf(":");
  const [kind, targetId] = idx === -1 ? ["", ""] : [trigger.slice(0, idx), trigger.slice(idx + 1)];
  return { trigger, kind, targetId, skill, mode };
}

const DEFAULTS: SkillBinding[] = [
  b("stage:plan", "perk-plan", "nudge"),
  b("stage:implement", "perk-implement", "nudge"),
];

test("resolveBindings: empty user overlay returns defaults unchanged", () => {
  const resolved = resolveBindings([], DEFAULTS);
  assert.deepEqual(resolved.bindings, DEFAULTS);
  assert.deepEqual(resolved.issues, []);
});

test("resolveBindings: override mode in place preserves position and count", () => {
  const resolved = resolveBindings([b("stage:plan", "perk-plan", "transclude")], DEFAULTS);
  assert.deepEqual(resolved.issues, []);
  assert.deepEqual(
    resolved.bindings.map((x) => [x.trigger, x.skill, x.mode]),
    [
      ["stage:plan", "perk-plan", "transclude"],
      ["stage:implement", "perk-implement", "nudge"],
    ],
  );
});

test("resolveBindings: replace skill at an existing trigger", () => {
  const resolved = resolveBindings([b("stage:plan", "house-style", "nudge")], DEFAULTS);
  assert.deepEqual(resolved.bindings[0], b("stage:plan", "house-style", "nudge"));
});

test("resolveBindings: a new trigger is appended", () => {
  const resolved = resolveBindings([b("stage:address", "house-style", "nudge")], DEFAULTS);
  assert.deepEqual(resolved.issues, []);
  assert.deepEqual(
    resolved.bindings.map((x) => x.trigger),
    ["stage:plan", "stage:implement", "stage:address"],
  );
});

test("resolveBindings: drops invalid bindings and reports each class", () => {
  const invalid = [
    b("stage:plan", "", "nudge"), // missing skill
    b("stage:implement", "s", "shout"), // bad mode
    b("noColon", "s", "nudge"), // malformed trigger
    b("phase:x", "s", "nudge"), // unknown kind
    b("stage:", "s", "nudge"), // empty target id
  ];
  const resolved = resolveBindings(invalid, DEFAULTS);
  assert.deepEqual(resolved.bindings, DEFAULTS);
  const messages = resolved.issues.map((i) => i.message).join(" | ");
  for (const fragment of ["skill", "mode", "<kind>:<id>", "kind", "empty"]) {
    assert.ok(messages.includes(fragment), `expected issue mentioning ${fragment}`);
  }
});

test("resolveBindings: duplicate user trigger applies first, reports second, stays unique", () => {
  const resolved = resolveBindings(
    [b("stage:plan", "first", "nudge"), b("stage:plan", "second", "nudge")],
    DEFAULTS,
  );
  assert.equal(resolved.bindings[0]?.skill, "first");
  assert.deepEqual(
    resolved.issues.map((i) => i.message),
    ["duplicate `trigger`"],
  );
  const triggers = resolved.bindings.map((x) => x.trigger);
  assert.equal(triggers.length, new Set(triggers).size);
});

test("resolveBindings: defaults to the shipped set when omitted", () => {
  const resolved = resolveBindings([]);
  assert.deepEqual(
    resolved.bindings.map((x) => [x.trigger, x.skill, x.mode]),
    loadDefaultBindings().map((x) => [x.trigger, x.skill, x.mode]),
  );
  assert.deepEqual(resolved.issues, []);
});
