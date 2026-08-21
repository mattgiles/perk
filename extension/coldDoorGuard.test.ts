// Mandatory cold-door delegation guard. Production extension code shells the perk CLI only
// through substrate/coldDoor.ts (`runColdDoor`): PERK_BIN resolution, the scratch stdin channel,
// the envelope-aware exit check, the JSON boundary, and the validated decode all live in that
// one seam — a hand-rolled exec/parse is a regression
// (docs/learned/workflow/cold-door-client.md). This is a textual backstop, not a completeness
// proof (docs/learned/workflow/source-scan-guards.md): variable indirection (`pi.exec(perkBin,
// …)` where `perkBin` was resolved elsewhere) and multi-line exec calls evade the per-line
// patterns — the guard catches the honest regression, not the adversarial one.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// The one cold-door delegation seam: the only file allowed to resolve PERK_BIN or exec perk.
const ALLOWLIST = ["substrate/coldDoor.ts"];

// The bin-resolution seam is coldDoor-only: any other `PERK_BIN` reference means a second
// resolution site is growing outside the seam.
const PERK_BIN_PATTERN = /\bPERK_BIN\b/;

// A direct `.exec("perk", …)` / `.exec('perk', …)` call — shelling the CLI without the seam.
const PERK_EXEC_PATTERN = /\.exec\(\s*["']perk["']/;

function matches(line: string): boolean {
  return PERK_BIN_PATTERN.test(line) || PERK_EXEC_PATTERN.test(line);
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
 * matching and a perk string/URL plausibly containing `//` would not also carry a PERK_BIN
 * reference or a quoted perk exec on the same line.
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
      const match = PERK_BIN_PATTERN.exec(line) ?? PERK_EXEC_PATTERN.exec(line);
      if (match) violations.push(`${file}:${i + 1}: ${match[0]}`);
    }
  }
  return violations;
}

test("perk CLI exec goes only through substrate/coldDoor.ts (runColdDoor)", () => {
  const files = productionFiles();
  // Self-checks: a future path/layout change that silently empties the scan must fail loudly
  // instead of passing vacuously.
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");
  assert.ok(
    files.includes("substrate/coldDoor.ts"),
    "scan missed substrate/coldDoor.ts — guard is misaimed",
  );
  assert.ok(files.includes("index.ts"), "scan missed index.ts — guard is misaimed");

  // Non-vacuous pattern check: the seam itself DOES carry the reference the guard bans.
  const coldDoorSource = stripComments(
    readFileSync(path.join(import.meta.dirname, "substrate", "coldDoor.ts"), "utf8"),
  );
  assert.ok(
    PERK_BIN_PATTERN.test(coldDoorSource),
    "substrate/coldDoor.ts no longer matches the banned pattern — guard is vacuous",
  );

  // Synthetic positives: the shapes a hand-rolled door would write.
  assert.ok(PERK_EXEC_PATTERN.test('pi.exec("perk", ["plan", "save", "--json"])'));
  assert.ok(PERK_EXEC_PATTERN.test("await host.exec('perk', argv)"));
  assert.ok(PERK_BIN_PATTERN.test('process.env.PERK_BIN ?? "perk"'));

  // Synthetic negatives: other execs and plain "perk" labels must not false-positive.
  // `pi.exec(perkBin, …)` is the documented variable-indirection evasion — out of scope.
  assert.ok(!matches('pi.exec("git", ["status"])'));
  assert.ok(!matches('pi.exec("bash", ["-c", script])'));
  assert.ok(!matches("pi.exec(perkBin, fullArgv)"));
  assert.ok(!matches('const label = "perk pr submit";'));

  const violations = violationsOf(files);
  assert.deepEqual(
    violations,
    [],
    "perk CLI exec outside substrate/coldDoor.ts — delegate through runColdDoor instead:\n" +
      violations.join("\n"),
  );
});
