import assert from "node:assert/strict";
import test from "node:test";
import { type CatalogSummary, parseSummary } from "./src/summary.ts";

const WIRE: CatalogSummary = {
  units: 1,
  fragments: 2,
  session_shapes: 3,
  assemblies: 4,
  scenarios: 5,
  concerns: 6,
  lineage_rules: 7,
  capabilities: [
    { id: "foundation", label: "Foundation" },
    { id: "extension", label: "Extension & utilities" },
  ],
};

test("parseSummary accepts the exact wire shape", () => {
  assert.deepEqual(parseSummary(WIRE), WIRE);
});

// Every count field is exercised for both defects: dropping any single field's runtime
// check must fail at least one test, never pass silently.
const COUNT_KEYS = [
  "units",
  "fragments",
  "session_shapes",
  "assemblies",
  "scenarios",
  "concerns",
  "lineage_rules",
] as const;

for (const key of COUNT_KEYS) {
  test(`parseSummary rejects a missing ${key}`, () => {
    const { [key]: _omitted, ...missingCount } = WIRE;
    assert.equal(parseSummary(missingCount), null);
  });

  test(`parseSummary rejects a non-numeric ${key}`, () => {
    assert.equal(parseSummary({ ...WIRE, [key]: String(WIRE[key]) }), null);
  });
}

test("parseSummary rejects missing capabilities", () => {
  const { capabilities: _capabilities, ...missingCapabilities } = WIRE;
  assert.equal(parseSummary(missingCapabilities), null);
});

test("parseSummary rejects non-array capabilities", () => {
  assert.equal(parseSummary({ ...WIRE, capabilities: {} }), null);
});

test("parseSummary rejects ill-shaped capability entries", () => {
  assert.equal(parseSummary({ ...WIRE, capabilities: [{ id: "foundation" }] }), null);
  assert.equal(parseSummary({ ...WIRE, capabilities: [{ id: 1, label: "Foundation" }] }), null);
  assert.equal(parseSummary({ ...WIRE, capabilities: ["foundation"] }), null);
});

test("parseSummary rejects non-object input", () => {
  assert.equal(parseSummary(null), null);
  assert.equal(parseSummary(undefined), null);
  assert.equal(parseSummary("catalog"), null);
  assert.equal(parseSummary(7), null);
  assert.equal(parseSummary([WIRE]), null);
});
