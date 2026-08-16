import assert from "node:assert/strict";
import test from "node:test";
import {
  parseUnitSource,
  READ_ONLY_PRESENTATION,
  READ_ONLY_REASONS,
  type UnitSource,
} from "./src/source.ts";

const EDITABLE: UnitSource = {
  unit: "managed:repo-agents",
  fragment: { id: "section:agents/developing-perk", label: "Developing perk" },
  path: "AGENTS.md",
  kind: "managed-prose",
  before: "# AGENTS\n",
  focus: "Focused 😀 prose\n",
  after: "# Next\n",
  editable: true,
  read_only_reason: null,
};

const WHOLE: UnitSource = {
  unit: "managed:repo-agents",
  fragment: null,
  path: "AGENTS.md",
  kind: "managed-prose",
  before: "",
  focus: "# AGENTS\n",
  after: "",
  editable: false,
  read_only_reason: "whole-unit",
};

test("parseUnitSource accepts editable, whole-unit, empty, and non-BMP segments", () => {
  assert.deepEqual(parseUnitSource(EDITABLE), EDITABLE);
  assert.deepEqual(parseUnitSource(WHOLE), WHOLE);
  const empty = { ...EDITABLE, before: "😀", focus: "", after: "tail" };
  assert.deepEqual(parseUnitSource(empty), empty);
});

const KEYS = [
  "unit",
  "fragment",
  "path",
  "kind",
  "before",
  "focus",
  "after",
  "editable",
  "read_only_reason",
] as const;

for (const key of KEYS) {
  test(`parseUnitSource rejects a missing ${key}`, () => {
    const { [key]: _omitted, ...rest } = EDITABLE;
    assert.equal(parseUnitSource(rest), null);
  });
}

test("parseUnitSource rejects ill-typed fields and malformed fragments", () => {
  assert.equal(parseUnitSource({ ...EDITABLE, unit: 7 }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, path: null }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, kind: "latin" }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, before: 1 }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, focus: 1 }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, after: 1 }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, editable: "yes" }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, fragment: { id: "body" } }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, fragment: undefined }), null);
});

test("parseUnitSource enforces exact editable and read-only invariants", () => {
  assert.equal(parseUnitSource({ ...EDITABLE, fragment: null }), null);
  assert.equal(parseUnitSource({ ...EDITABLE, read_only_reason: "selector-not-found" }), null);
  assert.equal(parseUnitSource({ ...WHOLE, read_only_reason: null }), null);
  assert.equal(parseUnitSource({ ...WHOLE, editable: true }), null);
  const unresolved = {
    ...WHOLE,
    fragment: EDITABLE.fragment,
    read_only_reason: "selector-not-found" as const,
  };
  assert.deepEqual(parseUnitSource(unresolved), unresolved);
});

test("parseUnitSource accepts every closed reason and rejects unknown reasons", () => {
  for (const reason of READ_ONLY_REASONS) {
    assert.notEqual(parseUnitSource({ ...WHOLE, read_only_reason: reason }), null);
  }
  assert.equal(parseUnitSource({ ...WHOLE, read_only_reason: "permission-denied" }), null);
});

test("read-only presentation copy is exact and exhaustive", () => {
  assert.deepEqual(READ_ONLY_PRESENTATION, {
    "whole-unit": {
      badge: "Read-only whole file",
      heading: "Whole-file view",
      explanation:
        "Select a logical fragment to view its focused range. Whole-unit browsing is read-only.",
    },
    "unsupported-family": {
      badge: "Read-only source",
      heading: "Adapter not available",
      explanation: "This source family is readable, but its focused adapter has not landed yet.",
    },
    "adapter-unavailable": {
      badge: "Read-only source",
      heading: "Adapter unavailable",
      explanation: "The source is readable, but its focused adapter could not run safely.",
    },
    "unsupported-selector": {
      badge: "Read-only source",
      heading: "Unsupported selector",
      explanation: "This fragment uses a selector shape the workbench does not edit.",
    },
    "unsupported-source-shape": {
      badge: "Read-only source",
      heading: "Unsupported source shape",
      explanation:
        "The fragment is readable, but its current source shape cannot be focused safely.",
    },
    "selector-not-found": {
      badge: "Read-only source",
      heading: "Fragment not found",
      explanation: "The catalog fragment no longer resolves in the current source file.",
    },
    "selector-ambiguous": {
      badge: "Read-only source",
      heading: "Fragment is ambiguous",
      explanation: "The catalog fragment resolves more than once in the current source file.",
    },
    "invalid-source": {
      badge: "Read-only source",
      heading: "Invalid source",
      explanation: "The current source cannot be parsed safely enough to resolve this fragment.",
    },
  });
});

test("parseUnitSource rejects non-object input", () => {
  assert.equal(parseUnitSource(null), null);
  assert.equal(parseUnitSource(undefined), null);
  assert.equal(parseUnitSource("source"), null);
  assert.equal(parseUnitSource([EDITABLE]), null);
});
