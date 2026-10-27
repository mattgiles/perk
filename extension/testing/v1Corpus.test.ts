// The shared v1 walker prunes the v2 workspace and every `node_modules` directory, fails closed on
// an empty walk, and — over the live tree — the exclusion is live, never vacuous.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, sep } from "node:path";
import { test } from "node:test";
import { EXTENSION_ROOT, v1ExtensionFiles } from "./v1Corpus.ts";

function tree(files: readonly string[]): string {
  const root = mkdtempSync(join(tmpdir(), "perk-v1-corpus-"));
  for (const file of files) {
    const path = join(root, file);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "export {};\n");
  }
  return root;
}

test("the walk prunes pi/v2 and every node_modules directory", () => {
  const root = tree([
    "a.ts",
    "pi/v2/host.ts",
    "node_modules/x/y.ts",
    "sub/node_modules/z.ts",
    "sub/b.ts",
  ]);
  try {
    assert.deepEqual(v1ExtensionFiles(root), ["a.ts", "sub/b.ts"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("a walk that yields nothing fails closed", () => {
  const root = tree(["pi/v2/x.ts"]);
  try {
    assert.throws(() => v1ExtensionFiles(root), /found no files/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("the live corpus holds v1 and excludes the (present) v2 workspace", () => {
  const files = v1ExtensionFiles();
  for (const anchor of ["index.ts", "pi/v1/gist.ts", "testing/v1Corpus.ts"]) {
    assert.ok(files.includes(anchor), `the v1 corpus contains ${anchor}`);
  }
  assert.deepEqual(
    files.filter((file) => file.startsWith("pi/v2/")),
    [],
    "nothing under pi/v2/",
  );
  assert.deepEqual(
    files.filter((file) => file.split("/").includes("node_modules")),
    [],
    "no node_modules segment",
  );
  // The exclusion bites: an unpruned walk of the same tree DOES see the v2 workspace.
  const raw = (readdirSync(EXTENSION_ROOT, { recursive: true }) as string[]).map((entry) =>
    entry.split(sep).join("/"),
  );
  assert.ok(raw.includes("pi/v2/host.ts"), "the raw walk sees pi/v2/host.ts");
});
