// Bare-clone / zero-runtime-dependency invariant guard.
//
// pi loads the perk extension from a git-package clone whose imports resolve through a FIXED
// host-alias set (`@earendil-works/pi-*`, `typebox`) plus native `node_modules` walking — and perk
// pre-materializes that clone with a plain `git clone` and NO `npm install`. So every production
// source file the runtime can reach (the import graph rooted at `extension/index.ts`) must import
// ONLY Node builtins (`node:*`), relative paths, or the host/peer packages — never a bare npm
// dependency. This source-scan test fails CI on any drift (e.g. re-introducing `nunjucks`/`yaml`).
//
// Paired with `tests/test_packaging.py::test_no_runtime_dependencies` (package.json has no runtime
// `dependencies`); together they durably pin the invariant the vendored miniYaml/miniJinja readers
// restore. Comments are stripped before scanning so the explanatory `import … from "nunjucks"` /
// `"yaml"` text in those vendored modules' headers is NOT mistaken for a real import.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// The host/peer packages pi resolves via its fixed alias set (package.json `peerDependencies`).
const ALLOWED_PACKAGES = new Set([
  "@earendil-works/pi-ai",
  "@earendil-works/pi-coding-agent",
  "@earendil-works/pi-tui",
  "typebox",
]);

/**
 * Production sources: every `.ts` under extension/ except test files and the dev-only testing/
 * fakes — neither is reachable from the runtime import graph rooted at index.ts (testing/ is
 * imported only by *.test.ts), and the npm tarball ships neither.
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

/** Strip block then line comments before scanning (mirrors surfacesGuard's deliberately-naive strip). */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

/**
 * Extract every imported/re-exported module specifier from already-comment-stripped source:
 * `import … from "spec"` / `export … from "spec"` (the `from "…"` clause, multiline-safe) and bare
 * side-effect `import "spec"`.
 */
function specifiersOf(strippedSource: string): string[] {
  const specs: string[] = [];
  for (const m of strippedSource.matchAll(/\bfrom\s*["']([^"']+)["']/g)) {
    if (m[1] !== undefined) specs.push(m[1]);
  }
  for (const m of strippedSource.matchAll(/\bimport\s*["']([^"']+)["']/g)) {
    if (m[1] !== undefined) specs.push(m[1]);
  }
  return specs;
}

/** A specifier is allowed iff it is a Node builtin, a relative path, or a host/peer package. */
function isAllowed(spec: string): boolean {
  return spec.startsWith("node:") || spec.startsWith(".") || ALLOWED_PACKAGES.has(spec);
}

test("production extension sources import only node:/relative/host specifiers (zero bare npm deps)", () => {
  const files = productionFiles();
  // Self-check: a layout change that silently empties the scan must fail loudly, not pass vacuously.
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");
  assert.ok(files.includes("index.ts"), "scan missed index.ts — guard is misaimed");

  const violations: string[] = [];
  for (const file of files) {
    const stripped = stripComments(readFileSync(path.join(import.meta.dirname, file), "utf8"));
    for (const spec of specifiersOf(stripped)) {
      if (!isAllowed(spec)) violations.push(`${file}: import "${spec}"`);
    }
  }
  assert.deepEqual(
    violations,
    [],
    `bare (non-host) npm imports in shipped extension code break the bare-clone invariant:\n${violations.join("\n")}\n` +
      "Vendor the dependency with Node builtins only (see substrate/miniYaml.ts / substrate/miniJinja.ts) " +
      "or add it to package.json peerDependencies + this guard's ALLOWED_PACKAGES if pi resolves it as a host alias.",
  );
});

test("synthetic positive: a fabricated bare import is flagged", () => {
  // Proves the extractor+classifier actually catches a real bare npm import (not vacuously green).
  const fabricated = 'import nunjucks from "nunjucks";\nimport { parse } from "yaml";\n';
  const flagged = specifiersOf(stripComments(fabricated)).filter((s) => !isAllowed(s));
  assert.deepEqual(flagged, ["nunjucks", "yaml"]);
});
