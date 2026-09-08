// The vendored parser closure must stay byte-identical to the pinned upstream package: a local
// edit would silently fork a third-party TOML implementation, and a stray extra file (the
// serializer, the CJS bundle, an entry point) would widen what the bare clone ships and loads.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const here = import.meta.dirname;
const repoRoot = join(here, "..", "..");
const vendored = join(here, "smol-toml");
const upstream = join(repoRoot, "node_modules", "smol-toml");
const PIN = "1.8.0";
const RUNTIME = [
  "parse.js",
  "struct.js",
  "extract.js",
  "primitive.js",
  "date.js",
  "error.js",
  "util.js",
] as const;
const TYPES = ["parse.d.ts", "date.d.ts", "error.d.ts", "util.d.ts"] as const;

test("package.json pins smol-toml exactly as a devDependency only (never a runtime dependency)", () => {
  const pkg = JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8"));
  assert.equal(pkg.devDependencies["smol-toml"], PIN);
  assert.equal(pkg.dependencies, undefined);
  const installed = JSON.parse(readFileSync(join(upstream, "package.json"), "utf8"));
  assert.equal(installed.version, PIN, "node_modules must carry the pinned version");
});

test("the vendored directory is exactly the parser closure + license + provenance README", () => {
  const files = readdirSync(vendored).sort();
  assert.deepEqual(files, [...RUNTIME, ...TYPES, "LICENSE", "README.md"].sort());
  const readme = readFileSync(join(vendored, "README.md"), "utf8");
  assert.match(readme, new RegExp(`\`${PIN.replaceAll(".", "\\.")}\``));
  assert.match(readme, /BSD-3-Clause/);
  for (const forbidden of ["stringify.js", "stringify.d.ts", "index.js", "index.cjs", "index.d.ts"])
    assert.ok(!files.includes(forbidden), `${forbidden} must not be vendored`);
});

test("every vendored module and the license are byte-identical to the pinned upstream package", () => {
  for (const name of [...RUNTIME, ...TYPES]) {
    const ours = readFileSync(join(vendored, name));
    const theirs = readFileSync(join(upstream, "dist", name));
    assert.ok(ours.equals(theirs), `${name} drifted from smol-toml@${PIN}`);
    // Upstream keeps its copyright/license notice on every module; a rewrite would lose it.
    assert.match(ours.toString("utf8"), /Copyright \(c\) Squirrel Chat et al\./);
    assert.match(ours.toString("utf8"), /SPDX-License-Identifier: BSD-3-Clause/);
  }
  assert.ok(
    readFileSync(join(vendored, "LICENSE")).equals(readFileSync(join(upstream, "LICENSE"))),
    "LICENSE drifted from upstream",
  );
});

test("the vendored parser loads directly and honors integersAsBigInt for huge unrelated integers", async () => {
  const { parse } = await import("./smol-toml/parse.js");
  const doc = parse('[compaction]\nreserve_tokens = 99999999999999999999\n[issues]\nbackend = "x"\n', {
    integersAsBigInt: true,
  });
  assert.deepEqual(doc, {
    compaction: { reserve_tokens: 99999999999999999999n },
    issues: { backend: "x" },
  });
});
