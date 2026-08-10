import { strict as assert } from "node:assert";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { perkVersion, promptsDir, sharedDir, versionStamp } from "./resources.ts";

test("promptsDir resolves in the dev tree and contains README.md", () => {
  const dir = promptsDir();
  assert.ok(existsSync(dir));
  assert.ok(existsSync(join(dir, "README.md")));
});

test("sharedDir still resolves (regression guard)", () => {
  assert.ok(existsSync(sharedDir()));
});

test("versionStamp filters the 0.0.0 failure sentinel to undefined", () => {
  assert.equal(versionStamp("0.0.0"), undefined);
});

test("versionStamp passes a real version through", () => {
  assert.equal(versionStamp("2.3.0"), "2.3.0");
});

test("versionStamp(perkVersion()) is a defined strict-X.Y.Z string in the dev tree", () => {
  // Proves the dev tree never carries the sentinel, so the session-lifecycle stamp
  // assertions are deterministic.
  const stamp = versionStamp(perkVersion());
  assert.ok(stamp !== undefined);
  assert.match(stamp, /^\d+\.\d+\.\d+$/);
});
