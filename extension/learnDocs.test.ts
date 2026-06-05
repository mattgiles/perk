// hop-2 — unit tests for the pure `learnDocsGuidance` (the warm `/learn-docs` factory seed). The
// command's delegation to `perk learn-docs --gather` is exercised offline elsewhere; here we pin
// the guidance shape (inbox path, consumed numbers). The skill pointer is no longer in the pure
// guidance — Node 2.3 delivers it via the skill-binding suffix (command:learn-docs).

import assert from "node:assert/strict";
import { test } from "node:test";
import { learnDocsGuidance } from "./learnDocs.ts";

test("learnDocsGuidance names the inbox path", () => {
  const text = learnDocsGuidance(".pi/workflow/scratch/learn-docs-inbox.md", [45, 50]);
  assert.match(text, /\.pi\/workflow\/scratch\/learn-docs-inbox\.md/);
});

test("learnDocsGuidance carries the consumed learn numbers", () => {
  const text = learnDocsGuidance("inbox.md", [45, 50]);
  assert.match(text, /consumed_learn: \[45, 50\]/);
});

test("learnDocsGuidance no longer hardcodes the perk-learn-docs skill pointer (Node 2.3)", () => {
  const text = learnDocsGuidance("inbox.md", [45]);
  assert.doesNotMatch(text, /Follow the perk-learn-docs skill/);
});
