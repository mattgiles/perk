import assert from "node:assert/strict";
import test from "node:test";
import { parseUnitSource, type UnitSource } from "./src/source.ts";

const WIRE: UnitSource = {
  unit: "managed:repo-agents",
  path: "AGENTS.md",
  kind: "managed-prose",
  content: "# AGENTS\n",
};

test("parseUnitSource accepts the exact wire shape", () => {
  assert.deepEqual(parseUnitSource(WIRE), WIRE);
});

const KEYS = ["unit", "path", "kind", "content"] as const;

for (const key of KEYS) {
  test(`parseUnitSource rejects a missing ${key}`, () => {
    const { [key]: _omitted, ...rest } = WIRE;
    assert.equal(parseUnitSource(rest), null);
  });

  test(`parseUnitSource rejects an ill-typed ${key}`, () => {
    assert.equal(parseUnitSource({ ...WIRE, [key]: 7 }), null);
  });
}

test("parseUnitSource rejects an unknown kind string", () => {
  assert.equal(parseUnitSource({ ...WIRE, kind: "latin" }), null);
});

test("parseUnitSource rejects non-object input", () => {
  assert.equal(parseUnitSource(null), null);
  assert.equal(parseUnitSource(undefined), null);
  assert.equal(parseUnitSource("source"), null);
  assert.equal(parseUnitSource([WIRE]), null);
});
