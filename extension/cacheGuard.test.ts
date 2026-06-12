// Scratch-path construction regression guard (Objective #339 Node 1.2, contracts.md §8.1).
// Production extension code may build the `scratch`/`runs` path segments only inside the
// cache seam (cache.ts); everything else goes through its helpers (`scratchDir`,
// `runScratchDir`, `sessionDataDir`, `ensureRunScratch`, `listRunIds`) or the ctx-level
// session-data seam (sessionData.ts). This source-scan test fails CI on drift. The Python twin
// is tests/test_cache_guard.py.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// The path-primitive seam: the only file allowed to carry the segment literals.
// sessionData.ts composes via cache.ts helpers, so it needs no literal and no allowlisting.
const ALLOWLIST = ["cache.ts"];

// The banned path-segment string literals.
const PATTERN = /["'](scratch|runs)["']/;

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
 * `scratch`/`runs` segment on the same line.
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
      const match = PATTERN.exec(line);
      if (match) violations.push(`${file}:${i + 1}: ${match[0]}`);
    }
  }
  return violations;
}

test("scratch/runs path segments are built only inside the cache seam (cache.ts)", () => {
  const files = productionFiles();
  // Self-checks: a future path/layout change that silently empties the scan must fail loudly
  // instead of passing vacuously.
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");
  assert.ok(files.includes("cache.ts"), "scan missed cache.ts — guard is misaimed");
  assert.ok(files.includes("index.ts"), "scan missed index.ts — guard is misaimed");

  // Non-vacuous pattern check: the seam itself DOES carry the literals the guard bans.
  const cacheSource = stripComments(
    readFileSync(path.join(import.meta.dirname, "cache.ts"), "utf8"),
  );
  assert.ok(
    PATTERN.test(cacheSource),
    "cache.ts no longer matches the banned pattern — guard is vacuous",
  );

  const violations = violationsOf(files);
  assert.deepEqual(
    violations,
    [],
    "manual scratch/runs path construction outside cache.ts — go through the cache seam " +
      "(scratchDir/runScratchDir/sessionDataDir) or the sessionData.ts ctx seam:\n" +
      violations.join("\n"),
  );
});
