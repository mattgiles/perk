import assert from "node:assert/strict";
import test from "node:test";
import {
  NEWLINE_STYLES,
  parseSourceFile,
  parseSourceView,
  parseUnitSource,
  READ_ONLY_PRESENTATION,
  READ_ONLY_REASONS,
  type SourceFile,
  type SourceView,
  sourceCurrentText,
  type UnitSource,
} from "./src/source.ts";

const HASH = "0123456789abcdef".repeat(4);
const FILE: SourceFile = {
  path: "AGENTS.md",
  mode: 0o6751,
  newline_style: "mixed",
  load_hash: HASH,
};
const EDITABLE: SourceView = {
  unit: "managed:repo-agents",
  fragment: { id: "section:agents/developing-perk", label: "Developing perk" },
  kind: "managed-prose",
  before: "# AGENTS\r\n",
  focus: "Focused 😀 prose\r",
  after: "# Next\n",
  editable: true,
  read_only_reason: null,
};
const WHOLE: SourceView = {
  unit: "managed:repo-agents",
  fragment: null,
  kind: "managed-prose",
  before: "",
  focus: "# AGENTS\n",
  after: "",
  editable: false,
  read_only_reason: "whole-unit",
};
const LOAD: UnitSource = { file: FILE, view: EDITABLE };

test("nested source parsers accept metadata, Unicode, empty focus, and additive fields", () => {
  assert.deepEqual(parseSourceFile(FILE), FILE);
  assert.deepEqual(parseSourceView(EDITABLE), EDITABLE);
  assert.deepEqual(parseUnitSource(LOAD), LOAD);
  const empty = { ...EDITABLE, before: "\ufeff😀", focus: "", after: "tail" };
  assert.deepEqual(parseSourceView(empty), empty);
  assert.deepEqual(
    parseUnitSource({
      future_top_level: true,
      file: { ...FILE, future_file_field: "kept additive" },
      view: { ...EDITABLE, future_view_field: 1 },
    }),
    LOAD,
  );
});

test("sourceCurrentText reconstructs Unicode and every transported newline exactly", () => {
  assert.equal(sourceCurrentText(EDITABLE), "# AGENTS\r\nFocused 😀 prose\r# Next\n");
  assert.equal(
    sourceCurrentText({ ...EDITABLE, before: "\ufeffα", focus: "😀", after: "omega" }),
    "\ufeffα😀omega",
  );
  assert.equal(
    sourceCurrentText({ ...WHOLE, focus: "no terminal newline" }),
    "no terminal newline",
  );
});

for (const style of NEWLINE_STYLES) {
  test(`parseSourceFile accepts ${style} newline metadata`, () => {
    assert.deepEqual(parseSourceFile({ ...FILE, newline_style: style }), {
      ...FILE,
      newline_style: style,
    });
  });
}

for (const key of ["path", "mode", "newline_style", "load_hash"] as const) {
  test(`parseSourceFile rejects a missing ${key}`, () => {
    const { [key]: _omitted, ...rest } = FILE;
    assert.equal(parseSourceFile(rest), null);
  });
}

for (const key of [
  "unit",
  "fragment",
  "kind",
  "before",
  "focus",
  "after",
  "editable",
  "read_only_reason",
] as const) {
  test(`parseSourceView rejects a missing ${key}`, () => {
    const { [key]: _omitted, ...rest } = EDITABLE;
    assert.equal(parseSourceView(rest), null);
  });
}

test("parseSourceFile enforces mode, newline, and lowercase SHA-256 vocabularies", () => {
  for (const mode of [-1, 0.5, 0o10000, "0644", null]) {
    assert.equal(parseSourceFile({ ...FILE, mode }), null);
  }
  assert.equal(parseSourceFile({ ...FILE, newline_style: "native" }), null);
  assert.equal(parseSourceFile({ ...FILE, load_hash: HASH.toUpperCase() }), null);
  assert.equal(parseSourceFile({ ...FILE, load_hash: "a".repeat(63) }), null);
  assert.equal(parseSourceFile({ ...FILE, path: null }), null);
});

test("parseSourceView rejects ill-typed fields and malformed fragments", () => {
  assert.equal(parseSourceView({ ...EDITABLE, unit: 7 }), null);
  assert.equal(parseSourceView({ ...EDITABLE, kind: "latin" }), null);
  assert.equal(parseSourceView({ ...EDITABLE, before: 1 }), null);
  assert.equal(parseSourceView({ ...EDITABLE, focus: 1 }), null);
  assert.equal(parseSourceView({ ...EDITABLE, after: 1 }), null);
  assert.equal(parseSourceView({ ...EDITABLE, editable: "yes" }), null);
  assert.equal(parseSourceView({ ...EDITABLE, fragment: { id: "body" } }), null);
  assert.equal(parseSourceView({ ...EDITABLE, fragment: undefined }), null);
});

test("parseSourceView enforces exact editable and read-only invariants", () => {
  assert.equal(parseSourceView({ ...EDITABLE, fragment: null }), null);
  assert.equal(parseSourceView({ ...EDITABLE, read_only_reason: "selector-not-found" }), null);
  assert.equal(parseSourceView({ ...WHOLE, read_only_reason: null }), null);
  assert.equal(parseSourceView({ ...WHOLE, editable: true }), null);
  const unresolved = {
    ...WHOLE,
    fragment: EDITABLE.fragment,
    read_only_reason: "selector-not-found" as const,
  };
  assert.deepEqual(parseSourceView(unresolved), unresolved);
});

test("parseSourceView accepts every closed reason and rejects unknown reasons", () => {
  for (const reason of READ_ONLY_REASONS) {
    assert.notEqual(parseSourceView({ ...WHOLE, read_only_reason: reason }), null);
  }
  assert.equal(parseSourceView({ ...WHOLE, read_only_reason: "permission-denied" }), null);
});

test("parseUnitSource requires both nested objects", () => {
  assert.equal(parseUnitSource(null), null);
  assert.equal(parseUnitSource({ file: FILE }), null);
  assert.equal(parseUnitSource({ view: EDITABLE }), null);
  assert.equal(parseUnitSource({ file: FILE, view: { unit: "only" } }), null);
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
