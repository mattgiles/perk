// The characterization suite's closed vocabulary floor: the six principle files hold exactly the
// fourteen tagged cases — every listed Durable behavior once, no untagged test, no stray id — each
// bounded by the suite's per-case timeout, and all of them in the fast tier. Adding or renaming a
// case means editing EXPECTED_TOKENS here: the set is the characterization contract of the record's
// §15 (docs/design/pi-durable-v2-foundations.md), not whatever the files happen to contain.

import assert from "node:assert/strict";
import { globSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { v2TierFiles } from "../testing/tiers.ts";

const ROOT = resolve(import.meta.dirname, "..", "..", "..", "..");
const SELF = "census.test.ts";

const EXPECTED_FILES = [
  "commit.test.ts",
  "enforcement.test.ts",
  "failure.test.ts",
  "scheduling.test.ts",
  "submissions.test.ts",
  "termination.test.ts",
];

const EXPECTED_TOKENS = [
  "D1 (P8)",
  "D2 (P9)",
  "D3 (P9)",
  "D4 (P1, P5)",
  "D4c (P5)",
  "D5 (P1)",
  "D6 (P4)",
  "D7 (P6)",
  "D8 (P7)",
  "D8c (P7)",
  "D9 (P7)",
  "D9c (P7)",
  "D10 (P8)",
  "D10c (P8)",
];

/** The literal options argument every tagged case passes (compared whitespace-insensitively). */
const TIMEOUT_OPTIONS = "{ timeout: CASE_TIMEOUT_MS }";

/**
 * One `test(` call: its quoted title, then its second argument — a brace-delimited object literal
 * without nested braces, or else everything up to the next comma.
 */
const TEST_CALL = /\btest\(\s*(["'`])(.*?)\1\s*,\s*(\{[^{}]*\}|[^,]*?)\s*,/gs;

/** An argument's source with whitespace and a trailing comma before its closing brace dropped. */
function normalized(source: string): string {
  return source.replace(/\s+/g, "").replace(/,\}$/, "}");
}

/** A title's leading tag: the behavior id, then the principles it supports. */
const TAG = /^(D\d+c?) \((P\d+(?:, P\d+)*)\): \S/;

/** The characterization files, by name, sorted. */
function characterizationFiles(): string[] {
  return globSync("*.test.ts", { cwd: import.meta.dirname })
    .filter((file) => file !== SELF)
    .sort();
}

/** Every `test(` call across the characterization files: its tag token and options source. */
function cases(): { file: string; token: string; options: string }[] {
  const found: { file: string; token: string; options: string }[] = [];
  for (const file of characterizationFiles()) {
    const source = readFileSync(join(import.meta.dirname, file), "utf8");
    const matches = [...source.matchAll(TEST_CALL)];
    assert.equal(
      matches.length,
      source.match(/\btest\(/g)?.length ?? 0,
      `every test( call in ${file} has a literal title the census can read`,
    );
    for (const [, , title = "", options = ""] of matches) {
      const tag = TAG.exec(title);
      const token = tag === null ? `untagged: ${title}` : `${tag[1]} (${tag[2]})`;
      found.push({ file, token, options });
    }
  }
  return found;
}

test("the characterization suite is the six principle files", () => {
  assert.deepEqual(characterizationFiles(), EXPECTED_FILES);
});

test("every listed Durable behavior is characterized exactly once, and nothing else", () => {
  assert.deepEqual(
    cases()
      .map((found) => found.token)
      .sort(),
    [...EXPECTED_TOKENS].sort(),
  );
});

test("every tagged case is bounded by the per-case timeout", () => {
  const unbounded = cases()
    .filter((found) => normalized(found.options) !== normalized(TIMEOUT_OPTIONS))
    .map((found) => `${found.file}: ${found.token} passes ${found.options}`);
  assert.deepEqual(unbounded, []);
});

test("every characterization file runs in the fast tier", () => {
  const fast = v2TierFiles("fast", ROOT);
  for (const file of EXPECTED_FILES) {
    const path = `extension/pi/v2/characterization/${file}`;
    assert.ok(fast.includes(path), `the fast tier holds ${path}`);
  }
});
