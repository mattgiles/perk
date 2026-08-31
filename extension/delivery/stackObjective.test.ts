// The stack command vocabulary: the objective-argument parse. The refusal message's exact
// wording is pinned by the door/adapter suites that emit it (stackStatus.test.ts,
// objectiveStack.test.ts); here the parser's token discipline is pinned directly.

import assert from "node:assert/strict";
import { test } from "node:test";

import { parseStackObjectiveArg } from "./stackObjective.ts";

test("parseStackObjectiveArg: first token wins, leading # stripped, whitespace tolerated", () => {
  assert.equal(parseStackObjectiveArg("2083"), "2083");
  assert.equal(parseStackObjectiveArg("  #2083  trailing words "), "2083");
  assert.equal(parseStackObjectiveArg("abc-id"), "abc-id");
});

test("parseStackObjectiveArg: empty/blank args parse to null", () => {
  assert.equal(parseStackObjectiveArg(""), null);
  assert.equal(parseStackObjectiveArg("   "), null);
  assert.equal(parseStackObjectiveArg("#"), null);
});
