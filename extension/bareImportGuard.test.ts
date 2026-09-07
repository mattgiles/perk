// Bare-clone / zero-runtime-dependency invariant guard.
//
// pi loads the perk extension from a git-package clone whose imports resolve through a FIXED
// host-alias set (`@earendil-works/pi-*`, `typebox`) plus native `node_modules` walking — and perk
// pre-materializes that clone with a plain `git clone` and NO `npm install`. So every production
// source file the runtime can reach (the import graph rooted at `extension/index.ts`) must import
// ONLY Node builtins (`node:*`), relative paths, or the host/peer packages — never a bare npm
// dependency. This source-scan test fails CI on any drift (e.g. re-introducing `nunjucks`/`yaml`).
// It covers static `import … from`, bare side-effect `import "…"`, and the string-literal form of
// dynamic `import(…)` / `require(…)` (a computed specifier has no literal to scan, but the bundled
// extension uses none, except the confined source-bound optional preflight loader described below).
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
  // The old global pi-ai API (`complete`, `getModel`, …) moved to /compat in pi-ai 0.80; pi's
  // extension loader carries an explicit alias for it alongside the root.
  "@earendil-works/pi-ai/compat",
  "@earendil-works/pi-coding-agent",
  "@earendil-works/pi-tui",
  "typebox",
  // The host aliases this peer subpath too; compatibility recovery validates original schemas.
  "typebox/compile",
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
 * `import … from "spec"` / `export … from "spec"` (the `from "…"` clause, multiline-safe), bare
 * side-effect `import "spec"`, and the string-literal form of dynamic `import("spec")` /
 * `require("spec")` (a non-literal dynamic specifier has no string to scan and is not flagged).
 */
function specifiersOf(strippedSource: string): string[] {
  const specs: string[] = [];
  for (const m of strippedSource.matchAll(/\bfrom\s*["']([^"']+)["']/g)) {
    if (m[1] !== undefined) specs.push(m[1]);
  }
  for (const m of strippedSource.matchAll(/\bimport\s*["']([^"']+)["']/g)) {
    if (m[1] !== undefined) specs.push(m[1]);
  }
  for (const m of strippedSource.matchAll(/\b(?:import|require)\s*\(\s*["']([^"']+)["']/g)) {
    if (m[1] !== undefined) specs.push(m[1]);
  }
  return specs;
}

// This one optional loader resolves jiti from the REGISTERED engine's manifest, not perk's
// package/dependencies. It cannot generalize to another caller or import; compatibility tests
// exercise the real public export and unavailable/escaping cases.
const PUBLIC_PREFLIGHT_LOADER = "pi/v1/delivery/conflictResolverEngine.ts";
function allowedAt(file: string, spec: string): boolean {
  return isAllowed(spec) || (file === PUBLIC_PREFLIGHT_LOADER && spec === "jiti");
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
      if (!allowedAt(file, spec)) violations.push(`${file}: import "${spec}"`);
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

test("source-bound public loader exception is exact, live, and cannot widen other imports", () => {
  const source = stripComments(
    readFileSync(path.join(import.meta.dirname, PUBLIC_PREFLIGHT_LOADER), "utf8"),
  );
  assert.ok(specifiersOf(source).includes("jiti"));
  assert.match(source, /createRequire\(manifestPath\)/);
  assert.match(source, /manifest\?\.name === "pi-subagents"/);
  assert.match(source, /realpathSync\(resolve\(root, target\)\)/);
  assert.equal(allowedAt("delivery/rogue.ts", "jiti"), false);
  assert.equal(allowedAt(PUBLIC_PREFLIGHT_LOADER, "pi-subagents/private"), false);
});

test("synthetic positive: fabricated bare imports (static, side-effect, dynamic, require) are flagged", () => {
  // Proves the extractor+classifier actually catches a real bare npm import (not vacuously green),
  // across every scanned form — including dynamic import()/require() with a string-literal specifier.
  const fabricated = [
    'import nunjucks from "nunjucks";',
    'import { parse } from "yaml";',
    'import "side-effect-pkg";',
    'const x = await import("dynamic-pkg");',
    'const y = require("require-pkg");',
  ].join("\n");
  const flagged = specifiersOf(stripComments(fabricated)).filter((s) => !isAllowed(s));
  assert.deepEqual(flagged, ["nunjucks", "yaml", "side-effect-pkg", "dynamic-pkg", "require-pkg"]);
});
