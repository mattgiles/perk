// Tests for the shared learn-factory door module (learnFactory.ts): the strict `decodeGather`
// reject branches (once — the decode is kind-independent) plus the pure `learnFactoryGuidance`
// seed per kind. The skill pointer is no longer in the pure guidance — the skill-binding suffix
// delivers it (command:learn-docs / command:learn-code). Door-level harness tests live in
// learnDocs.test.ts / learnCode.test.ts (per-file process parallelism).

import assert from "node:assert/strict";
import { test } from "node:test";
import { CODE_DOOR, DOCS_DOOR, decodeGather, learnFactoryGuidance } from "./learnFactory.ts";

// --- decodeGather reject branches (the strict decode returns null) ------------------------------

test("decodeGather: missing inbox_path rejects", () => {
  assert.equal(decodeGather({ learn_numbers: ["45"] }), null);
});

test("decodeGather: non-array learn_numbers rejects", () => {
  assert.equal(decodeGather({ inbox_path: "inbox.md", learn_numbers: "45" }), null);
});

test("decodeGather: bad element types in learn_numbers reject", () => {
  assert.equal(decodeGather({ inbox_path: "inbox.md", learn_numbers: [{}, true] }), null);
});

test("decodeGather: valid payload coerces numbers to string ids", () => {
  assert.deepEqual(decodeGather({ inbox_path: "inbox.md", learn_numbers: [45, "50"] }), {
    inbox_path: "inbox.md",
    learn_numbers: ["45", "50"],
  });
});

// --- learnFactoryGuidance (pure, per kind) ------------------------------------------------------

for (const kind of [DOCS_DOOR, CODE_DOOR]) {
  test(`learnFactoryGuidance (${kind.name}) names the inbox path`, () => {
    const inbox = `.perk/workflow/scratch/${kind.name}-inbox.md`;
    const text = learnFactoryGuidance(kind, inbox, ["45", "50"]);
    assert.ok(text.includes(inbox), "the guidance names the inbox path");
  });

  test(`learnFactoryGuidance (${kind.name}) carries the consumed learn numbers`, () => {
    const text = learnFactoryGuidance(kind, "inbox.md", ["45", "50"]);
    assert.match(text, /consumed_learn: \[45, 50\]/);
  });

  test(`learnFactoryGuidance (${kind.name}) does not hardcode the perk-${kind.name} skill pointer`, () => {
    const text = learnFactoryGuidance(kind, "inbox.md", ["45"]);
    assert.doesNotMatch(text, new RegExp(`Follow the perk-${kind.name} skill`));
  });
}
