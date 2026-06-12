// Rich-UI call-site regression guard — Objective #251, node 4.1 (`docs/design/tui-charter.md` §7).
// Production extension code may reach the rich UI only inside the surfaces module
// (surfaces/surfaces.ts + surfaces/report.ts); everything else goes through the seams (`report()`,
// `createPerkStatus`, `setStandingWidget`, `installPerkFooter`). `setWorkingIndicator` is never
// called anywhere (charter D5 rescinded). This source-scan test fails CI on drift.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// The surfaces module: the only files allowed to make rich-UI calls (see the surfaces.ts header —
// "the surfaces module" is surfaces.ts + report.ts for this node-4.1 guard).
const SURFACES_MODULE = ["surfaces/report.ts", "surfaces/surfaces.ts"];

// pattern → allowlist of relative paths. The `.`-prefixed patterns intentionally match
// call/member sites only — structural-type DECLARATIONS like `setStatus(slot: string, …): void;`
// (which modules may legitimately carry in a `ui: { … }` interface) have no leading dot and don't
// match. `ui.notify(` matches both `ctx.ui.notify(` and `target.ui.notify(`.
const RULES: { pattern: RegExp; allowlist: string[] }[] = [
  { pattern: /\bui\.notify\(/, allowlist: SURFACES_MODULE },
  { pattern: /\.setStatus\(/, allowlist: SURFACES_MODULE },
  { pattern: /\.setWidget\(/, allowlist: SURFACES_MODULE },
  { pattern: /\.setFooter\(/, allowlist: SURFACES_MODULE },
];

// Banned everywhere — D5 rescinded: perk keeps pi's default working indicator.
const BANNED_EVERYWHERE: RegExp = /\.setWorkingIndicator\(/;

/**
 * Discover production sources under extension/: every `.ts` file (recursively, so future
 * subdirectories are scanned by default) except test files and the testing/ fakes — test fakes
 * legitimately IMPLEMENT setStatus/setWidget/setFooter.
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
 * matching and none of the banned tokens plausibly appears in a perk string/URL.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

/** Collect `«relative-path»:«1-based line»: «matched text»` violations of one rule. */
function violationsOf(files: string[], pattern: RegExp, allowlist: string[]): string[] {
  const violations: string[] = [];
  for (const file of files) {
    if (allowlist.includes(file)) continue;
    const stripped = stripComments(readFileSync(path.join(import.meta.dirname, file), "utf8"));
    const lines = stripped.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line === undefined) continue;
      const match = pattern.exec(line);
      if (match) violations.push(`${file}:${i + 1}: ${match[0]}`);
    }
  }
  return violations;
}

test("rich-UI calls live only in the surfaces module (surfaces/surfaces.ts + surfaces/report.ts)", () => {
  const files = productionFiles();
  // Self-check: a future path/layout change that silently empties the scan must fail loudly
  // instead of passing vacuously.
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");
  assert.ok(
    files.includes("surfaces/surfaces.ts"),
    "scan missed surfaces/surfaces.ts — guard is misaimed",
  );
  assert.ok(files.includes("index.ts"), "scan missed index.ts — guard is misaimed");

  const violations = RULES.flatMap(({ pattern, allowlist }) =>
    violationsOf(files, pattern, allowlist),
  );
  assert.deepEqual(
    violations,
    [],
    `rich-UI calls outside the surfaces module:\n${violations.join("\n")}\n` +
      "Route notifies through report() (extension/surfaces/report.ts) and standing surfaces through " +
      "createPerkStatus/setStandingWidget/installPerkFooter (extension/surfaces/surfaces.ts), per " +
      "docs/design/tui-charter.md and the contracts surfaces-discipline passage.",
  );
});

test("setWorkingIndicator is never called (charter D5 rescinded)", () => {
  const files = productionFiles();
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");

  const violations = violationsOf(files, BANNED_EVERYWHERE, []);
  assert.deepEqual(
    violations,
    [],
    `setWorkingIndicator is banned everywhere (D5 rescinded):\n${violations.join("\n")}\n` +
      "perk keeps pi's default working indicator — remove the call.",
  );
});
