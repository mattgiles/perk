// perk reaches pi-subagents only through public surfaces (the v1 RPC envelope, the delegation
// events, agent-def frontmatter), never its installed private tree; the one sanctioned install-root
// read is Ponytail's manifest-declared skill preflight. A scan over every extension source (tests,
// testing/, vendor/ alike) pins SPELLINGS — the two forms a human writes when building such a path:
// a `.pi/npm/node_modules/` literal or `"npm", "node_modules"` segments (imports: bareImportGuard).

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Whole path tokens: the exception matches exactly (not by prefix); its presence keeps the scan live.
const INSTALL_ROOT_SPELLING =
  /\.pi\/npm\/node_modules\/[^"'`\s]*|["']npm["']\s*,\s*["']node_modules["']/g;
const SANCTIONED_FILE = "waves/ponytail.ts";
const SANCTIONED_ROOT = ".pi/npm/node_modules/@dietrichgebert/ponytail";
const VIOLATION_MESSAGE =
  "perk consumes installed packages only through public surfaces — resolve nothing into .pi/npm/node_modules/ (see docs/developers/pi-subagents-reverify.md); Ponytail's manifest-declared preflight in waves/ponytail.ts is the one exception";

/** The ONE classifier (the scan and the controls): every spelling in comment-stripped source. */
function installRootSpellings(source: string): string[] {
  const stripped = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  return [...stripped.matchAll(INSTALL_ROOT_SPELLING)].map((m) => m[0]);
}

test("no extension source spells a path into .pi/npm/node_modules/ except Ponytail's manifest-declared root", () => {
  const files = (readdirSync(import.meta.dirname, { recursive: true }) as string[])
    .map((f) => f.split(path.sep).join("/"))
    .filter((f) => /\.(ts|mjs|js)$/.test(f) && f !== path.basename(import.meta.filename))
    .sort();
  assert.ok(files.includes("index.ts") && files.includes(SANCTIONED_FILE), "scan misaimed");
  const violations: string[] = [];
  for (const file of files) {
    const spellings = installRootSpellings(readFileSync(`${import.meta.dirname}/${file}`, "utf8"));
    if (file === SANCTIONED_FILE) assert.deepEqual(spellings, [SANCTIONED_ROOT]);
    else violations.push(...spellings.map((spelling) => `${file}: ${spelling}`));
  }
  assert.deepEqual(violations, [], VIOLATION_MESSAGE);
  // Same-classifier controls: full literals (a root prefix-match is NOT the root); no false hits.
  for (const [control, expected] of [
    ['"../../.pi/npm/node_modules/pi-subagents"', [".pi/npm/node_modules/pi-subagents"]],
    ['join(cwd, ".pi", "npm", "node_modules", "pi-subagents")', ['"npm", "node_modules"']],
    [`"${SANCTIONED_ROOT}-fork/private"`, [`${SANCTIONED_ROOT}-fork/private`]],
    ["join(cwd, PONYTAIL_ROOT) // .pi/npm/node_modules/x", []],
  ] as const)
    assert.deepEqual(installRootSpellings(control), expected, control);
});
