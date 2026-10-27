// The node:test tier wiring: the slow list names real suite files, the two tiers partition the
// full suite exactly, the selector's corpus is its globs minus exactly the two carve-outs
// (`node_modules`, the v2 workspace), the recipes run what they claim, and the in-session gate's
// JS row is the fast tier while every full entrypoint keeps the whole suite.

import assert from "node:assert/strict";
import { globSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import {
  allJsTestFiles,
  JS_TEST_GLOBS,
  jsTestTierFiles,
  SLOW_JS_TEST_FILES,
} from "./jsTestTiers.ts";

const ROOT = resolve(import.meta.dirname, "..", "..");

/** The suite's three cohorts, transcribed independently of `JS_TEST_GLOBS` (sorted). */
const SUITE_GLOBS = [
  "docs/site/src/**/*.test.mjs",
  "extension/**/*.test.ts",
  "packages/perk-dev/**/*.test.mjs",
];

/** One justfile recipe's body (the indented lines after `name…:`). */
function recipeBody(name: string): string {
  const lines = readFileSync(resolve(ROOT, "justfile"), "utf8").split("\n");
  const start = lines.findIndex((line) => new RegExp(`^${name}( [^:]*)?:`).test(line));
  assert.ok(start !== -1, `the justfile defines a \`${name}\` recipe`);
  const body: string[] = [];
  for (const line of lines.slice(start + 1)) {
    if (!line.startsWith(" ")) break;
    body.push(line.trim());
  }
  return body.join("\n");
}

/** The raw expansion of one glob, with NO filtering (repo-relative, posix separators). */
function rawExpansion(pattern: string): string[] {
  return globSync(pattern, { cwd: ROOT }).map((file) => file.split("\\").join("/"));
}

test("the slow list is sorted, unique and names only real suite files", () => {
  assert.deepEqual([...SLOW_JS_TEST_FILES], [...new Set(SLOW_JS_TEST_FILES)].sort());
  const all = new Set(allJsTestFiles(ROOT));
  const stale = SLOW_JS_TEST_FILES.filter((file) => !all.has(file));
  assert.deepEqual(stale, [], "a slow-tier entry that the full suite does not run");
});

test("the selector's globs are exactly the three suite cohorts", () => {
  // An independent transcription: a cohort dropped from (or added to) `JS_TEST_GLOBS` fails here.
  assert.deepEqual([...JS_TEST_GLOBS].sort(), SUITE_GLOBS);
});

test("the selector's corpus is the raw glob expansion minus node_modules and the v2 workspace", () => {
  const raw = new Set<string>();
  for (const pattern of SUITE_GLOBS) {
    for (const file of rawExpansion(pattern)) raw.add(file);
  }
  // The carve is non-vacuous: the unfiltered globs DO reach the v2 workspace.
  assert.ok(raw.has("extension/pi/v2/host.test.ts"), "the raw globs reach extension/pi/v2/");
  const expected = [...raw]
    .filter((file) => !file.split("/").includes("node_modules"))
    .filter((file) => !file.startsWith("extension/pi/v2/"))
    .sort();
  assert.ok(expected.length > 0, "the globs select files");
  assert.deepEqual(allJsTestFiles(ROOT), expected);
});

test("the tiers partition the full suite: disjoint, and their union is every file", () => {
  const all = allJsTestFiles(ROOT);
  const fast = jsTestTierFiles("fast", ROOT);
  const slow = jsTestTierFiles("slow", ROOT);
  assert.ok(fast.length > 0 && slow.length > 0, "both tiers select files");
  assert.deepEqual(
    fast.filter((file) => slow.includes(file)),
    [],
  );
  assert.deepEqual([...fast, ...slow].sort(), all);
  assert.ok(fast.includes("extension/testing/jsTestTiers.test.ts"), "this guard runs in the gate");
});

test("the full recipes run the whole v1 suite through the selector — never a raw glob", () => {
  const full = "node extension/testing/runJsTestTier.ts all";
  assert.equal(recipeBody("test-js"), full);
  const test = recipeBody("test").split("\n");
  assert.ok(test.includes(full), "`test` runs the whole v1 suite through the selector");
  assert.deepEqual(
    test.filter((line) => line.startsWith("node --test ")),
    [],
    "`test` carries no raw `node --test` glob line",
  );
});

test("the tier recipes run the tier runner", () => {
  assert.equal(recipeBody("test-js-fast"), "node extension/testing/runJsTestTier.ts fast {{args}}");
  assert.equal(recipeBody("test-js-slow"), "node extension/testing/runJsTestTier.ts slow {{args}}");
});

test("the in-session gate's JS row is the fast tier", () => {
  const config = readFileSync(resolve(ROOT, ".perk", "config.toml"), "utf8");
  const rows = config.split("[[ci.checks]]").slice(1);
  const commands = rows.map((row) => /^command = "([^"]*)"/m.exec(row)?.[1]);
  assert.ok(commands.includes("just test-js-fast"), "a run_ci row runs `just test-js-fast`");
  for (const full of ["just test-js", "just test", "just test-js-slow", "just ci"]) {
    assert.ok(!commands.includes(full), `no run_ci row runs \`${full}\``);
  }
});
