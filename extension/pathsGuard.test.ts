// perk-owned dot-path construction regression guard (contracts.md §8.1).
// Production extension code may construct the perk-owned config family (`config.toml`/`local.toml`,
// now under `.perk/`) and the workflow family only inside their seams: substrate/paths.ts (config)
// and substrate/cache.ts (workflow). Everything else goes through their helpers (`configFile`/
// `localConfigFile`/`workflowDir`). The skills family is Python-only, so it is not mirrored here.
// This source-scan test fails CI on drift. The Python twin is tests/test_paths_guard.py.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// The path-primitive seams: the only files allowed to carry the perk-owned family literals.
const ALLOWLIST = ["substrate/paths.ts", "substrate/cache.ts"];

// A `".pi"` segment in `join(...)` path construction (adjacent to a `,`) followed by a still-`.pi`
// perk-owned follow-segment: the `"workflow"` literal plus the legacy config filename literals
// (legacy config construction is banned everywhere on this plane — TS reads the `.perk/` target
// only). Pi-native `.pi` + `npm`/`agents`/`settings.json`/`APPEND_SYSTEM.md` therefore never match.
const PI_PATTERN = /"\.pi"\s*,\s*("workflow"|"perk\.toml"|"perk\.local\.toml")/;

// A `".perk"` segment followed by a config follow-segment: the new filename literals or the
// imported constants (the config family now lives under `.perk/`).
const PERK_PATTERN =
  /"\.perk"\s*,\s*("config\.toml"|"local\.toml"|CONFIG_FILENAME|LOCAL_CONFIG_FILENAME)/;

function matches(line: string): boolean {
  return PI_PATTERN.test(line) || PERK_PATTERN.test(line);
}

/**
 * Discover production sources under extension/: every `.ts` file (recursively, so future
 * subdirectories are scanned by default) except test files and the testing/ fakes.
 */
function productionFiles(): string[] {
  const entries = readdirSync(import.meta.dirname, { recursive: true }) as string[];
  return entries
    .map((entry) => entry.split(path.sep).join("/"))
    .filter(
      (entry) =>
        entry.endsWith(".ts") && !entry.endsWith(".test.ts") && !entry.startsWith("testing/"),
    )
    .sort();
}

/**
 * Strip block comments then line comments before matching. Deliberately naive — this would also
 * eat `//` inside string literals — acceptable because the stripped text is only consumed for
 * matching and a perk string/URL plausibly containing `//` would not also carry a quoted
 * `.pi`+family construction on the same line.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

/** Collect `«relative-path»:«1-based line»: «matched text»` violations. */
function violationsOf(files: string[]): string[] {
  const violations: string[] = [];
  for (const file of files) {
    if (ALLOWLIST.includes(file)) continue;
    const stripped = stripComments(readFileSync(path.join(import.meta.dirname, file), "utf8"));
    const lines = stripped.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line === undefined) continue;
      const match = PI_PATTERN.exec(line) ?? PERK_PATTERN.exec(line);
      if (match) violations.push(`${file}:${i + 1}: ${match[0]}`);
    }
  }
  return violations;
}

test("perk-owned config/workflow dot-paths are built only inside their seams", () => {
  const files = productionFiles();
  // Self-checks: a future path/layout change that silently empties the scan must fail loudly
  // instead of passing vacuously.
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");
  assert.ok(
    files.includes("substrate/cache.ts"),
    "scan missed substrate/cache.ts — guard is misaimed",
  );
  assert.ok(files.includes("index.ts"), "scan missed index.ts — guard is misaimed");

  // Non-vacuous pattern check: the workflow seam itself DOES carry the literal the guard bans.
  const cacheSource = stripComments(
    readFileSync(path.join(import.meta.dirname, "substrate", "cache.ts"), "utf8"),
  );
  assert.ok(
    PI_PATTERN.test(cacheSource),
    "substrate/cache.ts no longer matches the banned pattern — guard is vacuous",
  );

  // Per-arm positive asserts on synthetic strings (keeps the config arms honest even though the
  // seam derives them from `configDir`).
  assert.ok(PI_PATTERN.test('join(cwd, ".pi", "workflow")'));
  assert.ok(PI_PATTERN.test('join(cwd, ".pi", "perk.toml")'));
  assert.ok(PI_PATTERN.test('join(cwd, ".pi", "perk.local.toml")'));
  assert.ok(PERK_PATTERN.test('join(cwd, ".perk", CONFIG_FILENAME)'));
  assert.ok(PERK_PATTERN.test('join(cwd, ".perk", LOCAL_CONFIG_FILENAME)'));
  assert.ok(PERK_PATTERN.test('join(cwd, ".perk", "config.toml")'));
  assert.ok(PERK_PATTERN.test('join(cwd, ".perk", "local.toml")'));

  // Pi-native `.pi/...` construction is out of scope and must not false-positive; a config
  // filename is no longer `.pi`-adjacent (it moved to `.perk`).
  assert.ok(!matches('join(cwd, ".pi", "npm")'));
  assert.ok(!matches('join(cwd, ".pi", "agents")'));
  assert.ok(!matches('join(cwd, ".pi", "APPEND_SYSTEM.md")'));
  assert.ok(!PI_PATTERN.test('join(cwd, ".pi", CONFIG_FILENAME)'));
  assert.ok(!PERK_PATTERN.test('join(cwd, ".perk", "workflow")'));

  const violations = violationsOf(files);
  assert.deepEqual(
    violations,
    [],
    "manual perk-owned dot-path construction outside the seams — go through substrate/paths.ts " +
      "(configFile/localConfigFile) or substrate/cache.ts (workflowDir):\n" +
      violations.join("\n"),
  );
});
