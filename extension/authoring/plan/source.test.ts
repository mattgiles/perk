// Direct feature tests for the plan-source resolution law (artifact → param → save-only
// transcript) and the fail-open transcript scrape. The adversarial extractPlanMarkdown cases
// pin the hardened narrowing: UNTRUSTED session history never throws, it fails open to null.

import assert from "node:assert/strict";
import { test } from "node:test";
import { extractPlanMarkdown, resolvePlanSource } from "./source.ts";

// ------------------------------------------------------------------------- resolvePlanSource

test("resolvePlanSource: a non-blank draft wins over every other tier", () => {
  const result = resolvePlanSource(
    { draft: "# Draft plan\n", explicit: "# Param plan", transcript: () => "# Scraped" },
    "save",
  );
  assert.deepEqual(result, { plan: "# Draft plan\n", source: "plan-draft", paramMismatch: true });
});

test("resolvePlanSource: paramMismatch is trimmed-compare — an equal param is not flagged", () => {
  const result = resolvePlanSource({ draft: "# Same plan\n", explicit: "  # Same plan  " }, "save");
  assert.deepEqual(result, { plan: "# Same plan\n", source: "plan-draft", paramMismatch: false });
});

test("resolvePlanSource: a blank param never flags a mismatch", () => {
  const result = resolvePlanSource({ draft: "# Draft\n", explicit: "   " }, "save");
  assert.deepEqual(result, { plan: "# Draft\n", source: "plan-draft", paramMismatch: false });
});

test("resolvePlanSource: a blank/absent draft falls back to the explicit param", () => {
  for (const draft of [null, "", "   \n"]) {
    const result = resolvePlanSource({ draft, explicit: "# Param plan" }, "review");
    assert.deepEqual(result, { plan: "# Param plan", source: "param", paramMismatch: false });
  }
});

test("resolvePlanSource: save mode reaches the transcript last resort", () => {
  const result = resolvePlanSource(
    { draft: null, explicit: "  ", transcript: () => "# Scraped plan" },
    "save",
  );
  assert.deepEqual(result, { plan: "# Scraped plan", source: "transcript", paramMismatch: false });
});

test("resolvePlanSource: review mode NEVER consults a transcript tier (the review-surface law)", () => {
  let scraped = 0;
  const result = resolvePlanSource(
    {
      draft: null,
      transcript: () => {
        scraped += 1;
        return "# Scraped plan";
      },
    },
    "review",
  );
  assert.equal(result, null);
  assert.equal(scraped, 0, "the thunk was never invoked in review mode");
});

test("resolvePlanSource: nothing resolvable → null (a null scrape too)", () => {
  assert.equal(resolvePlanSource({ draft: null }, "save"), null);
  assert.equal(resolvePlanSource({ draft: null, transcript: () => null }, "save"), null);
});

// ---------------------------------------------------------------------- extractPlanMarkdown

const msg = (role: string, content: unknown): unknown => ({
  type: "message",
  message: { role, content },
});

test("extractPlanMarkdown: the LATEST non-blank assistant message wins", () => {
  const entries = [
    msg("assistant", "# Old plan"),
    msg("user", "revise it"),
    msg("assistant", "# New plan\n\nSteps."),
  ];
  assert.equal(extractPlanMarkdown(entries), "# New plan\n\nSteps.");
});

test("extractPlanMarkdown: content-block arrays join text blocks; blank text is skipped", () => {
  const entries = [
    msg("assistant", "# Fallback"),
    msg("assistant", [
      { type: "text", text: "# Block plan" },
      { type: "thinking", thinking: "never surfaced" },
      { type: "text", text: "second block" },
    ]),
    msg("assistant", [{ type: "text", text: "   " }]),
  ];
  assert.equal(extractPlanMarkdown(entries), "# Block plan\nsecond block");
});

test("extractPlanMarkdown: no assistant text anywhere → null", () => {
  assert.equal(extractPlanMarkdown([]), null);
  assert.equal(extractPlanMarkdown([msg("user", "hello"), { type: "toolResult" }]), null);
});

test("extractPlanMarkdown: adversarial entries fail open to null, never throw", () => {
  // The delta-5 hardening: null/sparse/primitive entries and malformed shapes are UNTRUSTED
  // session history — each is skipped (or contributes nothing), never dereferenced blindly.
  const adversarial: readonly unknown[] = [
    null,
    undefined,
    42,
    "a bare string entry",
    [],
    { type: "message" }, // no message field
    { type: "message", message: null },
    { type: "message", message: "not a record" },
    { type: "message", message: { role: "assistant" } }, // no content
    { type: "message", message: { role: "assistant", content: null } },
    { type: "message", message: { role: "assistant", content: 7 } },
  ];
  assert.equal(extractPlanMarkdown(adversarial), null);
});

test("extractPlanMarkdown: malformed content blocks contribute nothing (fail-open per block)", () => {
  const entries = [
    msg("assistant", [
      null,
      "a bare string block",
      { type: "text" }, // no text field
      { type: "text", text: 9 },
      { type: "text", text: "# Survivor plan" },
    ]),
  ];
  assert.equal(extractPlanMarkdown(entries), "# Survivor plan");
});

test("extractPlanMarkdown: a malformed latest entry falls through to an earlier good one", () => {
  const entries = [msg("assistant", "# Good plan"), null, { type: "message", message: null }];
  assert.equal(extractPlanMarkdown(entries), "# Good plan");
});
