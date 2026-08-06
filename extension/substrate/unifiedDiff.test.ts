// Strictness + generator-parity coverage for the vendored unified-diff applier
// (`unifiedDiff.ts`). The hand-written half pins the strict-apply semantics (multi-hunk,
// insert/delete-only, EOF-no-newline on either side, and null on every anomaly class); the
// parity half round-trips (base, edited) pairs through the EXACT generator plannotator uses —
// jsdiff `createTwoFilesPatch(..., { context: 3 })`, a DEV-only dependency here — including
// the `patch.trimEnd()` embedding (`buildDirectEditsSection` trims the patch before fencing),
// so the trailing-whitespace-context reconstruction arm is exercised for real.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createTwoFilesPatch } from "diff";
import { applyUnifiedDiff } from "./unifiedDiff.ts";

/** The exact patch bytes plannotator embeds in the Direct Edits fence (generator + trimEnd). */
function plannotatorPatch(base: string, edited: string): string {
  return createTwoFilesPatch(
    "plan.md (original)",
    "plan.md (edited)",
    base,
    edited,
    undefined,
    undefined,
    { context: 3 },
  ).trimEnd();
}

// -------------------------------------------------------------------- hand-written fixtures

const BASE = ["# Title", "", "one", "two", "three", "four", "five", "six", "seven", ""].join("\n");

test("single hunk: a mid-file line replacement applies cleanly", () => {
  const diff = [
    "--- plan.md (original)",
    "+++ plan.md (edited)",
    "@@ -2,7 +2,7 @@",
    " ",
    " one",
    " two",
    "-three",
    "+THREE",
    " four",
    " five",
    " six",
  ].join("\n");
  assert.equal(applyUnifiedDiff(BASE, diff), BASE.replace("three", "THREE"));
});

test("multi-hunk: two separated edits apply in order", () => {
  const base = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", ""].join("\n");
  const diff = [
    "@@ -1,4 +1,4 @@",
    "-a",
    "+A",
    " b",
    " c",
    " d",
    "@@ -9,4 +9,4 @@",
    " i",
    " j",
    "-k",
    "+K",
    " l",
  ].join("\n");
  assert.equal(
    applyUnifiedDiff(base, diff),
    ["A", "b", "c", "d", "e", "f", "g", "h", "i", "j", "K", "l", ""].join("\n"),
  );
});

test("insert-only hunk splices new lines without consuming base lines", () => {
  const base = "a\nb\nc\n";
  const diff = ["@@ -1,3 +1,4 @@", " a", " b", "+b2", " c"].join("\n");
  assert.equal(applyUnifiedDiff(base, diff), "a\nb\nb2\nc\n");
});

test("delete-only hunk removes lines", () => {
  const base = "a\nb\nc\n";
  const diff = ["@@ -1,3 +1,2 @@", " a", "-b", " c"].join("\n");
  assert.equal(applyUnifiedDiff(base, diff), "a\nc\n");
});

test("delete-to-empty: removing every line yields the empty string", () => {
  const diff = ["@@ -1,1 +0,0 @@", "-only"].join("\n");
  assert.equal(applyUnifiedDiff("only\n", diff), "");
});

test("insert-into-empty: a zero-length old range at the start", () => {
  const diff = ["@@ -0,0 +1,1 @@", "+first"].join("\n");
  assert.equal(applyUnifiedDiff("", diff), "first\n");
});

test("EOF no-newline on the OLD side: the marker must match a newline-less base tail", () => {
  const base = "a\nb"; // no trailing newline
  const diff = ["@@ -1,2 +1,2 @@", " a", "-b", "\\ No newline at end of file", "+B"].join("\n");
  assert.equal(applyUnifiedDiff(base, diff), "a\nB\n");
});

test("EOF no-newline on the NEW side: the result ends without a newline", () => {
  const base = "a\nb\n";
  const diff = ["@@ -1,2 +1,2 @@", " a", "-b", "+B", "\\ No newline at end of file"].join("\n");
  assert.equal(applyUnifiedDiff(base, diff), "a\nB");
});

test("EOF no-newline on a context line flags both sides", () => {
  const base = "a\nb"; // no trailing newline
  const diff = ["@@ -1,2 +1,2 @@", "-a", "+A", " b", "\\ No newline at end of file"].join("\n");
  assert.equal(applyUnifiedDiff(base, diff), "A\nb");
});

// ----------------------------------------------------------------------- the null anomalies

test("null: a context line that does not byte-match the base", () => {
  const diff = ["@@ -1,2 +1,2 @@", " NOT IN BASE", "-b", "+B"].join("\n");
  assert.equal(applyUnifiedDiff("a\nb\n", diff), null);
});

test("null: a delete line that does not byte-match the base", () => {
  const diff = ["@@ -1,2 +1,2 @@", " a", "-NOT b", "+B"].join("\n");
  assert.equal(applyUnifiedDiff("a\nb\n", diff), null);
});

test("null: a malformed hunk header", () => {
  const diff = ["@@ -x,2 +1,2 @@", " a", "-b", "+B"].join("\n");
  assert.equal(applyUnifiedDiff("a\nb\n", diff), null);
});

test("null: an unknown body prefix", () => {
  const diff = ["@@ -1,2 +1,2 @@", " a", "*b", "+B"].join("\n");
  assert.equal(applyUnifiedDiff("a\nb\n", diff), null);
});

test("null: zero hunks (headers only, or plain prose)", () => {
  assert.equal(applyUnifiedDiff("a\n", "--- plan.md (original)\n+++ plan.md (edited)"), null);
  assert.equal(applyUnifiedDiff("a\n", "just some prose, not a diff"), null);
  assert.equal(applyUnifiedDiff("a\n", ""), null);
});

test("null: out-of-order (descending) hunks", () => {
  const base = "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n";
  const diff = ["@@ -9,1 +9,1 @@", "-i", "+I", "@@ -1,1 +1,1 @@", "-a", "+A"].join("\n");
  assert.equal(applyUnifiedDiff(base, diff), null);
});

test("null: trailing garbage after the last hunk", () => {
  const diff = ["@@ -1,1 +1,1 @@", "-a", "+A", "some trailing prose"].join("\n");
  assert.equal(applyUnifiedDiff("a\n", diff), null);
});

test("null: a hunk whose stated old range runs past the end of the base", () => {
  const diff = ["@@ -5,1 +5,1 @@", "-e", "+E"].join("\n");
  assert.equal(applyUnifiedDiff("a\nb\n", diff), null);
});

test("null: an old-side no-newline marker contradicting a newline-terminated base", () => {
  const diff = ["@@ -1,1 +1,1 @@", "-a", "\\ No newline at end of file", "+A"].join("\n");
  assert.equal(applyUnifiedDiff("a\n", diff), null);
});

test("null: a truncated final hunk whose missing context is NOT whitespace-only", () => {
  // Declares 3 old/new lines but carries 2 — the missing context line in the base is "c",
  // which trimEnd() could never have eaten.
  const diff = ["@@ -1,3 +1,3 @@", "-a", "+A", " b"].join("\n");
  assert.equal(applyUnifiedDiff("a\nb\nc\n", diff), null);
});

// -------------------------------------------------- generator parity (jsdiff, dev-only here)

const PARITY_CASES: { name: string; base: string; edited: string }[] = [
  {
    name: "simple replacement",
    base: "# Plan\n\nStep one.\nStep two.\nStep three.\n",
    edited: "# Plan\n\nStep one.\nStep 2 (edited).\nStep three.\n",
  },
  {
    name: "adjacent hunks merge into one (context 3)",
    base: Array.from({ length: 20 }, (_, i) => `line ${i + 1}`)
      .join("\n")
      .concat("\n"),
    edited: Array.from({ length: 20 }, (_, i) =>
      i === 4 ? "LINE 5" : i === 9 ? "LINE 10" : `line ${i + 1}`,
    )
      .join("\n")
      .concat("\n"),
  },
  {
    name: "distant hunks stay separate",
    base: Array.from({ length: 30 }, (_, i) => `row ${i + 1}`)
      .join("\n")
      .concat("\n"),
    edited: Array.from({ length: 30 }, (_, i) =>
      i === 1 ? "ROW 2" : i === 27 ? "ROW 28" : `row ${i + 1}`,
    )
      .join("\n")
      .concat("\n"),
  },
  {
    name: "unicode content",
    base: "## Résumé\n\n- naïve café ☕\n- emoji ✅ done\n",
    edited: "## Résumé\n\n- naïve café ☕ (updated)\n- emoji ✅ done\n- 中文行\n",
  },
  {
    name: "base without trailing newline",
    base: "a\nb\nc",
    edited: "a\nB\nc",
  },
  {
    name: "edited without trailing newline",
    base: "a\nb\nc\n",
    edited: "a\nb\nc changed",
  },
  {
    name: "both without trailing newline",
    base: "alpha\nbeta",
    edited: "alpha\nbeta!",
  },
  {
    name: "insertion at the very start",
    base: "middle\nend\n",
    edited: "start\nmiddle\nend\n",
  },
  {
    name: "append at the very end",
    base: "one\ntwo\n",
    edited: "one\ntwo\nthree\n",
  },
  {
    name: "trailing blank lines inside context (the trimEnd() reconstruction arm)",
    // The change sits within context distance of trailing blank lines, so the patch's final
    // context lines are whitespace-only and trimEnd() eats them out of the fence body.
    base: "# T\n\nbody\n\n\n",
    edited: "# T\n\nbody edited\n\n\n",
  },
  {
    name: "whitespace-only line adjacent to the change",
    base: "a\n \nb\n",
    edited: "a\n \nB\n",
  },
  {
    name: "full rewrite",
    base: "old one\nold two\n",
    edited: "completely\nnew\ncontent\n",
  },
  {
    name: "delete everything",
    base: "gone\nall gone\n",
    edited: "",
  },
  {
    name: "insert into empty",
    base: "",
    edited: "fresh\ncontent\n",
  },
];

for (const { name, base, edited } of PARITY_CASES) {
  test(`generator parity: ${name}`, () => {
    assert.equal(applyUnifiedDiff(base, plannotatorPatch(base, edited)), edited);
  });
}

test("generator parity: identical inputs produce a no-hunk patch -> null (nothing to apply)", () => {
  // plannotator never emits a Direct Edits section for an unchanged document
  // (`normalizeEditedMarkdown` returns null), so a hunkless patch maps to the null arm.
  const base = "same\nbytes\n";
  assert.equal(applyUnifiedDiff(base, plannotatorPatch(base, base)), null);
});
