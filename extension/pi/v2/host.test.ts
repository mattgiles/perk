// The v2 host entry opens and closes a Harness, and every dependency the workspace declares
// resolves at exactly its declared pin — the executable half of the workspace's resolution record
// (docs/design/archive/pi-durable-v2-workspace.md holds the measured locations).

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { MemoryStorage } from "@earendil-works/pi-durable";
import { openHost } from "./host.ts";

/** One importable entry per declared dependency (not every package exports `./package.json`). */
const ENTRY_SPECIFIERS: Readonly<Record<string, string>> = {
  "@earendil-works/chord": "@earendil-works/chord/context",
  "@earendil-works/pi-ai": "@earendil-works/pi-ai/models",
  "@earendil-works/pi-durable": "@earendil-works/pi-durable",
  "@earendil-works/pi-env": "@earendil-works/pi-env",
};

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every((v) => typeof v === "string")
  );
}

/** The workspace manifest's `dependencies`, narrowed from the parsed JSON. */
function declaredDependencies(): Record<string, string> {
  const manifest: unknown = JSON.parse(
    readFileSync(resolve(import.meta.dirname, "package.json"), "utf8"),
  );
  assert.ok(typeof manifest === "object" && manifest !== null, "the manifest is an object");
  const dependencies: unknown = Reflect.get(manifest, "dependencies");
  assert.ok(isStringRecord(dependencies), "the manifest declares string-valued dependencies");
  return dependencies;
}

/** The manifest of the package `entrySpecifier` resolves into: the nearest `package.json` named `name`. */
function resolvedManifest(name: string, entrySpecifier: string): { path: string; version: string } {
  let dir = dirname(fileURLToPath(import.meta.resolve(entrySpecifier)));
  for (;;) {
    const candidate = join(dir, "package.json");
    if (existsSync(candidate)) {
      const manifest: unknown = JSON.parse(readFileSync(candidate, "utf8"));
      if (
        typeof manifest === "object" &&
        manifest !== null &&
        Reflect.get(manifest, "name") === name
      ) {
        const version: unknown = Reflect.get(manifest, "version");
        assert.equal(typeof version, "string", `${candidate} carries a version`);
        return { path: candidate, version: String(version) };
      }
    }
    const parent = dirname(dir);
    assert.notEqual(parent, dir, `no package.json named ${name} above ${entrySpecifier}`);
    dir = parent;
  }
}

test("opens a Harness over MemoryStorage and closes it", async () => {
  const host = await openHost(new MemoryStorage());
  assert.ok(host.harness, "the host carries its Harness");
  await host.close();
  await host.harness.closed;
});

test("resolves every declared dependency at its declared pin", () => {
  const declared = declaredDependencies();
  assert.deepEqual(
    Object.keys(declared).sort(),
    Object.keys(ENTRY_SPECIFIERS).sort(),
    "every declared dependency has an entry specifier here (and nothing else does)",
  );
  for (const [name, pin] of Object.entries(declared)) {
    const entry = ENTRY_SPECIFIERS[name];
    assert.ok(entry, `an entry specifier for ${name}`);
    const { path, version } = resolvedManifest(name, entry);
    assert.equal(version, pin, `${name} resolves to ${path} at its declared pin`);
  }
});
