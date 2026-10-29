// The kernel purity guard (docs/design/pi-durable-v2-foundations.md P2 — reconcile never performs
// I/O and reads no ambient state). Two structural checks over every production file under
// `kernel/`: its only non-relative import is `node:crypto` (hashing), and its code names no
// clock, randomness, timer, `process`, `fetch`, `globalThis`, dynamic evaluation or
// asynchrony. Confining the kernel's relative imports to `kernel/` is `layeringGuard.test.ts`'s
// job. Comment stripping is naive on purpose: no kernel string holds `//`, and a banned word
// inside a kernel string literal is reported too — fail-closed; rephrase the string rather than
// add an allowlist. Each live check is paired with synthetic controls fed to the SAME functions.

import assert from "node:assert/strict";
import { test } from "node:test";
import { extractSpecifiers } from "../../testing/importGraph.ts";
import { readExtensionFile, v2Files } from "./testing/corpus.ts";

const KERNEL_PREFIX = "pi/v2/kernel/";
const ALLOWED_BUILTIN = "node:crypto";

const BANNED_WORDS = [
  "Date",
  "Math.random",
  "performance",
  "process",
  "globalThis",
  "setTimeout",
  "setInterval",
  "setImmediate",
  "queueMicrotask",
  "fetch",
  "require",
  "eval",
  "async",
  "await",
  "Promise",
  "randomUUID",
  "randomBytes",
  "randomInt",
  "getRandomValues",
];

const BANNED = new RegExp(
  `\\b(?:${BANNED_WORDS.map((word) => word.replace(".", "\\.")).join("|")})\\b`,
  "g",
);

/** Every specifier that is neither relative nor exactly `node:crypto`. */
function foreignImports(source: string): string[] {
  return extractSpecifiers(source).filter(
    (spec) => !spec.startsWith(".") && spec !== ALLOWED_BUILTIN,
  );
}

/** Every banned word in `source` once its block and line comments are stripped. */
function impureTokens(source: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  return [...code.matchAll(BANNED)].map((match) => match[0]);
}

function kernelCorpus(): string[] {
  return v2Files().filter((file) => file.startsWith(KERNEL_PREFIX) && !file.endsWith(".test.ts"));
}

// ── live ────────────────────────────────────────────────────────────────────────────────────────

test("the kernel corpus is live and holds its anchors", () => {
  const corpus = kernelCorpus();
  assert.ok(corpus.length > 0, "the kernel corpus is non-empty");
  for (const anchor of ["canonical.ts", "records.ts", "reconcile.ts"]) {
    assert.ok(corpus.includes(`${KERNEL_PREFIX}${anchor}`), `the corpus holds ${anchor}`);
  }
  assert.deepEqual(
    corpus.filter((file) => file.endsWith(".test.ts")),
    [],
    "no test file in the production corpus",
  );
});

test("every production kernel file imports only kernel files and node:crypto", () => {
  for (const file of kernelCorpus()) {
    assert.deepEqual(foreignImports(readExtensionFile(file)), [], file);
  }
  // Positive floor: the check sees a real specifier.
  assert.ok(
    extractSpecifiers(readExtensionFile(`${KERNEL_PREFIX}canonical.ts`)).includes(ALLOWED_BUILTIN),
    "canonical.ts imports node:crypto",
  );
});

test("no production kernel file names a clock, randomness, a timer or asynchrony", () => {
  for (const file of kernelCorpus()) {
    assert.deepEqual(impureTokens(readExtensionFile(file)), [], file);
  }
});

// ── controls ────────────────────────────────────────────────────────────────────────────────────

test("control: foreignImports reports every non-crypto builtin form and spares the allowed ones", () => {
  assert.deepEqual(foreignImports('import { readFileSync } from "node:fs";\n'), ["node:fs"]);
  assert.deepEqual(foreignImports('export * from "node:os";\n'), ["node:os"]);
  assert.deepEqual(foreignImports('import "node:process";\n'), ["node:process"]);
  assert.deepEqual(foreignImports('const m = await import("node:fs");\n'), ["node:fs"]);
  assert.deepEqual(foreignImports('import { createHash } from "node:crypto";\n'), []);
  assert.deepEqual(foreignImports('import type { X } from "./records.ts";\n'), []);
});

test("control: impureTokens reports each banned word in code, not in comments or longer identifiers", () => {
  for (const word of BANNED_WORDS) {
    assert.deepEqual(impureTokens(`const x = ${word};\n`), [word], `in code: ${word}`);
    assert.deepEqual(impureTokens(`const x = 1; // ${word}\n`), [], `in a line comment: ${word}`);
    assert.deepEqual(
      impureTokens(`/* ${word}\n  ${word} */ const x = 1;\n`),
      [],
      `in a block comment: ${word}`,
    );
  }
  assert.deepEqual(impureTokens("const t = Date.now();\n"), ["Date"]);
  assert.deepEqual(impureTokens("async function f() { await g(); }\n"), ["async", "await"]);
  assert.deepEqual(
    impureTokens("const updatedAt = requireRecord(processed);\n"),
    [],
    "identifiers that merely contain a banned word",
  );
});
