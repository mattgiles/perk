// perk reaches pi-subagents only through public surfaces (the v1 RPC envelope, the delegation
// events, agent-def frontmatter), never its installed private tree; the two sanctioned install-root
// spellings are Ponytail's manifest-declared skill preflight and the host-SDK bridge's consumer
// install root (`NATIVE_CONSUMER_INSTALL_ROOT` — the bridge verifies consumer roots by manifest
// identity + whole-path prefix and reads only their `package.json`; every other file imports the
// constant). A scan over every extension source (tests, testing/, vendor/ alike) pins SPELLINGS —
// the two forms a human writes when building such a path: a `.pi/npm/node_modules/` literal or
// `"npm", "node_modules"` segments (imports: bareImportGuard).

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Whole path tokens: the exception matches exactly (not by prefix); its presence keeps the scan live.
const INSTALL_ROOT_SPELLING =
  /\.pi\/npm\/node_modules\/[^"'`\s]*|["']npm["']\s*,\s*["']node_modules["']/g;
const SANCTIONED_ROOT = ".pi/npm/node_modules/@dietrichgebert/ponytail";
// file → the exact spellings it may carry (deepEqual-pinned, so a second literal in either fails).
const SANCTIONED: Record<string, string[]> = {
  "waves/ponytail.ts": [SANCTIONED_ROOT],
  "substrate/nativeSdkBridge.ts": [".pi/npm/node_modules/"],
};
const VIOLATION_MESSAGE =
  "perk consumes installed packages only through public surfaces — resolve nothing into .pi/npm/node_modules/ (see docs/developers/pi-subagents-reverify.md); the two exceptions are Ponytail's manifest-declared preflight in waves/ponytail.ts and the host-SDK bridge's NATIVE_CONSUMER_INSTALL_ROOT in substrate/nativeSdkBridge.ts (import the constant, never respell the path)";

/** The ONE classifier (the scan and the controls): every spelling in comment-stripped source. */
function installRootSpellings(source: string): string[] {
  const stripped = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  return [...stripped.matchAll(INSTALL_ROOT_SPELLING)].map((m) => m[0]);
}

test("no extension source spells a path into .pi/npm/node_modules/ except the two sanctioned roots", () => {
  const files = (readdirSync(import.meta.dirname, { recursive: true }) as string[])
    .map((f) => f.split(path.sep).join("/"))
    .filter((f) => /\.(ts|mjs|js)$/.test(f) && f !== path.basename(import.meta.filename))
    .sort();
  assert.ok(
    files.includes("index.ts") && Object.keys(SANCTIONED).every((f) => files.includes(f)),
    "scan misaimed",
  );
  const violations: string[] = [];
  for (const file of files) {
    const spellings = installRootSpellings(readFileSync(`${import.meta.dirname}/${file}`, "utf8"));
    const sanctioned = SANCTIONED[file];
    if (sanctioned !== undefined) assert.deepEqual(spellings, sanctioned, file);
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
