// The golden stage×tool matrix (`shared/fixtures/tool-matrix.json`): derived from the catalog +
// the posture rows by `toolMatrix()`, committed, and drift-guarded here byte-for-byte. Both
// planes' prompt guards read it (the Python half reads only the file). Regenerate with
//   PERK_UPDATE_TOOL_MATRIX=1 node --test extension/substrate/toolMatrix.test.ts

import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { before, test } from "node:test";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { sharedDir } from "./resources.ts";
import {
  BUILTIN_TOOL_POLICY,
  gatedToolsFor,
  PACKAGE_TOOL_POLICY,
  perkToolNames,
  REGISTRY_STAGE_IDS,
  SYNTHETIC_PATH_TOOL_POLICY,
  stageToolsFor,
  toolMatrix,
  UNSCOPED_MATRIX_KEY,
} from "./toolPolicy.ts";

const FIXTURE = join(sharedDir(), "fixtures", "tool-matrix.json");

before(ensureToolCatalog);

/** Keys sorted at every depth, 2-space indent, trailing newline (arrays keep their order). */
function canonicalJson(value: unknown): string {
  const sortKeys = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sortKeys);
    if (v !== null && typeof v === "object") {
      return Object.fromEntries(
        Object.keys(v)
          .sort()
          .map((key) => [key, sortKeys((v as Record<string, unknown>)[key])]),
      );
    }
    return v;
  };
  return `${JSON.stringify(sortKeys(value), null, 2)}\n`;
}

test("the committed matrix equals the derived one byte-for-byte (regenerate on purpose)", () => {
  const derived = canonicalJson(toolMatrix());
  if (process.env.PERK_UPDATE_TOOL_MATRIX === "1") writeFileSync(FIXTURE, derived, "utf8");
  assert.equal(
    readFileSync(FIXTURE, "utf8"),
    derived,
    "shared/fixtures/tool-matrix.json drifted — regenerate with PERK_UPDATE_TOOL_MATRIX=1",
  );
});

test("toolMatrix() is the derived views: perk + builtin rows, the posture table, eligibility = the views", () => {
  const matrix = toolMatrix();
  const builtins = Object.keys(BUILTIN_TOOL_POLICY);
  assert.deepEqual(Object.keys(matrix.tools).sort(), [...builtins, ...perkToolNames()].sort());
  for (const name of perkToolNames()) assert.equal(matrix.tools[name]?.owner, "perk", name);
  assert.deepEqual(
    Object.keys(matrix.postures.packages).sort(),
    Object.keys(PACKAGE_TOOL_POLICY).sort(),
  );
  assert.deepEqual(Object.keys(matrix.postures.paths), Object.keys(SYNTHETIC_PATH_TOOL_POLICY));
  const gatedBuiltins = builtins.filter((n) => BUILTIN_TOOL_POLICY[n]?.gated !== "blocked");
  for (const stage of REGISTRY_STAGE_IDS) {
    const row = matrix.eligible[stage];
    assert.ok(row !== undefined, stage);
    assert.deepEqual(
      row["read-only"],
      [...gatedToolsFor(stage), ...gatedBuiltins].sort(),
      `${stage} read-only`,
    );
    assert.deepEqual(
      row["read-write"],
      [...(stageToolsFor(stage) ?? []), ...builtins].sort(),
      `${stage} read-write`,
    );
  }
  const unscoped = matrix.eligible[UNSCOPED_MATRIX_KEY];
  assert.deepEqual(unscoped?.["read-only"], [...gatedToolsFor(null), ...gatedBuiltins].sort());
  assert.deepEqual(unscoped?.["read-write"], Object.keys(matrix.tools).sort());
});
