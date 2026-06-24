import { strict as assert } from "node:assert";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { promptsDir, sharedDir } from "./resources.ts";

test("promptsDir resolves in the dev tree and contains README.md", () => {
  const dir = promptsDir();
  assert.ok(existsSync(dir));
  assert.ok(existsSync(join(dir, "README.md")));
});

test("sharedDir still resolves (regression guard)", () => {
  assert.ok(existsSync(sharedDir()));
});
