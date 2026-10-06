// The node:test tier wiring: the slow list names real suite files, the two tiers partition the
// full suite exactly, the recipes run what they claim, and the in-session gate's JS row is the
// fast tier while every full entrypoint keeps the whole suite.

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

/** The quoted glob arguments of a recipe's `node --test` line — read from the justfile itself. */
function recipeGlobs(name: string): string[] {
  const line = recipeBody(name)
    .split("\n")
    .find((l) => l.startsWith("node --test "));
  assert.ok(line, `\`${name}\` runs node --test`);
  return [...line.matchAll(/"([^"]+)"/g)].map((m) => m[1] ?? "").sort();
}

/** The full suite as the `test-js` recipe defines it: its own globs, expanded independently. */
function recipeSuite(): string[] {
  const files = new Set<string>();
  for (const pattern of recipeGlobs("test-js")) {
    for (const file of globSync(pattern, { cwd: ROOT })) {
      const normalized = file.split("\\").join("/");
      if (!normalized.split("/").includes("node_modules")) files.add(normalized);
    }
  }
  return [...files].sort();
}

test("the slow list is sorted, unique and names only real suite files", () => {
  assert.deepEqual([...SLOW_JS_TEST_FILES], [...new Set(SLOW_JS_TEST_FILES)].sort());
  const all = new Set(allJsTestFiles(ROOT));
  const stale = SLOW_JS_TEST_FILES.filter((file) => !all.has(file));
  assert.deepEqual(stale, [], "a slow-tier entry that the full suite does not run");
});

test("the tiers partition the full suite: disjoint, and their union is every file", () => {
  // The oracle is the `test-js` recipe's own globs, not the selector's: a cohort dropped from
  // `JS_TEST_GLOBS` (or added to the recipe only) fails here.
  const all = recipeSuite();
  assert.ok(all.length > 0, "the recipe's globs select files");
  assert.deepEqual(allJsTestFiles(ROOT), all, "the selector's corpus is the recipe's suite");
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

test("the selector's globs are exactly the full recipes' globs, both ways", () => {
  for (const recipe of ["test-js", "test"]) {
    assert.deepEqual(recipeGlobs(recipe), [...JS_TEST_GLOBS].sort(), `\`${recipe}\`'s globs`);
  }
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
