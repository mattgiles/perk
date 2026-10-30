// The v2 tier wiring: fast ∪ slow is every v2 test and the two are disjoint, the fast tier holds
// its anchors, the filename rule partitions a synthetic tree (pruning node_modules), the slow tier
// runs under a reporter that prints diagnostics, and the recipes plus the `[[ci.checks]]` rows run
// what they claim.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { allV2TestFiles, SLOW_SUFFIX, v2TierFiles } from "./tiers.ts";

const ROOT = resolve(import.meta.dirname, "..", "..", "..", "..");

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

/** One recipe's header line (`name …: dependencies`). */
function recipeHeader(name: string): string {
  const line = readFileSync(resolve(ROOT, "justfile"), "utf8")
    .split("\n")
    .find((l) => new RegExp(`^${name}( [^:]*)?:`).test(l));
  assert.ok(line, `the justfile defines a \`${name}\` recipe`);
  return line;
}

/** The `[[ci.checks]]` rows of `.perk/config.toml`, by name. */
function ciRows(): Map<string, { command: string; glob: string[] }> {
  const config = readFileSync(resolve(ROOT, ".perk", "config.toml"), "utf8");
  const rows = new Map<string, { command: string; glob: string[] }>();
  for (const row of config.split("[[ci.checks]]").slice(1)) {
    const name = /^name = "([^"]*)"/m.exec(row)?.[1];
    const command = /^command = "([^"]*)"/m.exec(row)?.[1];
    const glob = /^glob = "([^"]*)"/m.exec(row)?.[1];
    if (name !== undefined && command !== undefined) {
      rows.set(name, { command, glob: glob === undefined ? [] : glob.split(",") });
    }
  }
  return rows;
}

test("the tiers partition the v2 suite: disjoint, and their union is every v2 test", () => {
  const all = allV2TestFiles(ROOT);
  const fast = v2TierFiles("fast", ROOT);
  const slow = v2TierFiles("slow", ROOT);
  assert.deepEqual(
    fast.filter((file) => slow.includes(file)),
    [],
  );
  assert.deepEqual([...fast, ...slow].sort(), all);
  for (const anchor of [
    "extension/pi/v2/host.test.ts",
    "extension/pi/v2/layeringGuard.test.ts",
    "extension/pi/v2/testing/tiers.test.ts",
  ]) {
    assert.ok(fast.includes(anchor), `the fast tier holds ${anchor}`);
  }
  assert.deepEqual(
    slow,
    all.filter((file) => file.endsWith(SLOW_SUFFIX)),
  );
});

test("the filename rule partitions a synthetic tree and prunes node_modules", () => {
  const root = mkdtempSync(join(tmpdir(), "perk-v2-tiers-"));
  try {
    for (const file of ["a.test.ts", "b.slow.test.ts", "node_modules/c.test.ts"]) {
      const path = join(root, "extension", "pi", "v2", file);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, "");
    }
    assert.deepEqual(v2TierFiles("fast", root), ["extension/pi/v2/a.test.ts"]);
    assert.deepEqual(v2TierFiles("slow", root), ["extension/pi/v2/b.slow.test.ts"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("the v2 recipes run the v2 runner and the aggregates reach them", () => {
  assert.equal(recipeBody("test-v2"), "node extension/pi/v2/testing/runTier.ts fast {{args}}");
  assert.equal(recipeBody("test-v2-slow"), "node extension/pi/v2/testing/runTier.ts slow {{args}}");
  assert.equal(recipeBody("typecheck-v2"), "npm run v2:typecheck");
  assert.ok(
    recipeHeader("typecheck").split(/\s+/).includes("typecheck-v2"),
    "`typecheck` depends on `typecheck-v2`",
  );
  const testBody = recipeBody("test").split("\n");
  for (const line of [
    "node extension/pi/v2/testing/runTier.ts fast",
    "node extension/pi/v2/testing/runTier.ts slow",
  ]) {
    assert.ok(testBody.includes(line), `\`test\` runs \`${line}\``);
  }
});

test("the slow tier prints its diagnostics: spec reporter for slow, dot for fast", () => {
  const runner = readFileSync(resolve(import.meta.dirname, "runTier.ts"), "utf8");
  assert.ok(
    runner.includes('const reporter = tier === "slow" ? "spec" : "dot";'),
    "runTier.ts picks the reporter per tier",
  );
  // Assembled from parts so the expected source text is not itself read as a template string.
  assert.ok(
    runner.includes(["`--test-reporter=$", "{reporter}`"].join("")),
    "runTier.ts passes the per-tier reporter to node --test",
  );
});

test("the three v2 rows run their recipes over globs that reach their inputs", () => {
  const rows = ciRows();
  for (const name of ["typecheck-v2", "test-v2", "test-v2-slow"]) {
    const row = rows.get(name);
    assert.ok(row, `a \`${name}\` row exists`);
    assert.equal(row.command, `just ${name}`);
    for (const pattern of ["package.json", "package-lock.json"]) {
      assert.ok(row.glob.includes(pattern), `\`${name}\`'s glob lists ${pattern}`);
    }
  }
  const typecheck = rows.get("typecheck-v2")?.glob ?? [];
  for (const pattern of [
    "extension/pi/v2/**",
    "extension/testing/importGraph.ts",
    "tsconfig.json",
  ]) {
    assert.ok(typecheck.includes(pattern), `\`typecheck-v2\`'s glob lists ${pattern}`);
  }
  // The cross-import guard reads every v1 file (tests included): a v1-only edit must schedule it.
  assert.ok(
    rows.get("test-v2")?.glob.includes("extension/**"),
    "`test-v2` triggers on extension/**",
  );
  // The capstone drives the Python `perk v2` door end to end: a door-only edit must schedule it.
  for (const pattern of ["extension/pi/v2/**", "src/perk/v2/**", "src/perk/cli/commands/v2/**"]) {
    assert.ok(
      rows.get("test-v2-slow")?.glob.includes(pattern),
      `\`test-v2-slow\` triggers on ${pattern}`,
    );
  }
});
