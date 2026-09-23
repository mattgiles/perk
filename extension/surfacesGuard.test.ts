// Rich-UI call-site regression guard (`docs/design/tui-charter.md` §7).
// Production extension code may reach the rich UI only inside the surfaces module
// (surfaces/surfaces.ts + surfaces/report.ts); everything else goes through the seams (`report()`,
// `createPerkStatus`, `installPerkFooter`, `registerTranscriptRenderer`).
// pi-tui imports are likewise confined to the surfaces module (vocabulary re-exports — e.g. `Key`)
// plus the named vendor/btw `ctx.ui.custom` exception, and the raw `.registerEntryRenderer(` call
// lives only inside the `registerTranscriptRenderer` seam. `setWorkingIndicator` is never called
// anywhere (charter D5 rescinded). This source-scan test fails CI on drift.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { extractSpecifiers } from "./testing/importGraph.ts";

// The surfaces module: the only files allowed to make rich-UI calls (see the surfaces.ts header —
// "the surfaces module" is surfaces.ts + report.ts for this node-4.1 guard).
const SURFACES_MODULE = ["surfaces/report.ts", "surfaces/surfaces.ts"];

// Named so the pattern-matches-the-seam self-check below exercises the SAME regex the rule uses.
const PI_TUI_IMPORT = /["']@earendil-works\/pi-tui["']/;
const PI_TUI_SPECIFIER = "@earendil-works/pi-tui";

// Files exempt from the pi-tui LINE regex because they carry the specifier as data (the host-SDK
// bridge's census + captured-namespace key). Each is held to an import-aware rule instead: the
// bridge imports node builtins only, and hostSdk.ts reaches pi-tui only through surfaces.ts.
const DATA_ONLY_PI_TUI_FILES = ["substrate/nativeSdkBridge.ts", "substrate/hostSdk.ts"];

// pattern → allowlist of relative paths. The `.`-prefixed patterns intentionally match
// call/member sites only — structural-type DECLARATIONS like `setStatus(slot: string, …): void;`
// (which modules may legitimately carry in a `ui: { … }` interface) have no leading dot and don't
// match. `ui.notify(` matches both `ctx.ui.notify(` and `target.ui.notify(`.
const RULES: { pattern: RegExp; allowlist: string[] }[] = [
  { pattern: /\bui\.notify\(/, allowlist: SURFACES_MODULE },
  { pattern: /\.setStatus\(/, allowlist: SURFACES_MODULE },
  { pattern: /\.setWidget\(/, allowlist: SURFACES_MODULE },
  { pattern: /\.setFooter\(/, allowlist: SURFACES_MODULE },
  // The vendored `whimsical` working-message label routes through the `setWorkingMessage` surfaces
  // seam (charter §6: text-only, permitted, headless-no-op — distinct from the banned
  // `setWorkingIndicator` below).
  { pattern: /\.setWorkingMessage\(/, allowlist: SURFACES_MODULE },
  // Transcript renderers (audit §2.3): the raw pi call lives only inside the
  // `registerTranscriptRenderer` seam — feature modules register through the seam, which carries
  // the one typeof feature-detect. The seam's own structural DECLARATION
  // (`registerEntryRenderer?(…): void` in `TranscriptRendererHost`) has no leading dot and is
  // correctly not matched.
  { pattern: /\.registerEntryRenderer\(/, allowlist: SURFACES_MODULE },
  // pi-tui imports (static, side-effect, or dynamic — the specifier always sits on one line) are
  // confined to the surfaces module, which re-exports the vocabulary other modules need (`Key`,
  // renderer helpers). The two vendor/btw files are the charter's named D6 `ctx.ui.custom`
  // exception (§6): real pi-tui components for the sanctioned human-only overlay. The two
  // host-SDK bridge files (`DATA_ONLY_PI_TUI_FILES`) name the pi-tui specifier as DATA — the
  // redirected census entry and its captured-namespace key — never as an import; the line regex
  // cannot tell the two apart, so the import-aware test below lexes their real specifiers.
  {
    pattern: PI_TUI_IMPORT,
    allowlist: [
      ...SURFACES_MODULE,
      "vendor/btw/btw.ts",
      "vendor/btw/core.ts",
      ...DATA_ONLY_PI_TUI_FILES,
    ],
  },
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

  // Pattern-matches-the-seam self-check (docs/learned/workflow/source-scan-guards.md): the
  // surfaces module itself must still match the pi-tui import pattern — a seam refactor that
  // rots the pattern must fail loudly here instead of the rule passing vacuously.
  const surfacesSource = stripComments(
    readFileSync(path.join(import.meta.dirname, "surfaces/surfaces.ts"), "utf8"),
  );
  assert.ok(
    PI_TUI_IMPORT.test(surfacesSource),
    "surfaces/surfaces.ts no longer matches the pi-tui import pattern — the guard rule rotted",
  );

  const violations = RULES.flatMap(({ pattern, allowlist }) =>
    violationsOf(files, pattern, allowlist),
  );
  assert.deepEqual(
    violations,
    [],
    `rich-UI calls outside the surfaces module:\n${violations.join("\n")}\n` +
      "Route notifies through report() (extension/surfaces/report.ts), standing surfaces through " +
      "createPerkStatus/installPerkFooter, transcript renderers through the " +
      "registerTranscriptRenderer seam, and pi-tui vocabulary through the surfaces re-exports " +
      "(extension/surfaces/surfaces.ts), per docs/design/tui-charter.md §7 and AGENTS.md.",
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

test("the data-only pi-tui allowlist entries carry no pi-tui import (import-aware, lexed specifiers)", () => {
  const read = (file: string) => readFileSync(path.join(import.meta.dirname, file), "utf8");
  for (const file of DATA_ONLY_PI_TUI_FILES) {
    // The regex exemption is only meaningful while the literal is really there as data.
    assert.ok(PI_TUI_IMPORT.test(stripComments(read(file))), `${file} no longer names pi-tui`);
    const specifiers = extractSpecifiers(read(file));
    assert.ok(specifiers.length > 0, `${file}: the lexer saw no imports — the check is vacuous`);
    assert.ok(!specifiers.includes(PI_TUI_SPECIFIER), `${file} imports pi-tui directly`);
  }
  // The bridge is the loader hook: node builtins only (the fixture processes import it SDK-free).
  const bridge = extractSpecifiers(read("substrate/nativeSdkBridge.ts"));
  assert.deepEqual(
    bridge.filter((spec) => !spec.startsWith("node:")),
    [],
    "substrate/nativeSdkBridge.ts must import node builtins only",
  );
  // hostSdk.ts captures pi-tui through the surfaces module's re-export, never the package.
  const hostSdk = extractSpecifiers(read("substrate/hostSdk.ts"));
  assert.ok(
    hostSdk.includes("../surfaces/surfaces.ts"),
    "hostSdk.ts must take pi-tui from surfaces.ts",
  );
  // Non-vacuity: the lexer reports a direct import when one exists.
  assert.ok(
    extractSpecifiers(`import { Key } from "${PI_TUI_SPECIFIER}";`).includes(PI_TUI_SPECIFIER),
  );
});
