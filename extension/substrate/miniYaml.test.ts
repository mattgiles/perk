// Fidelity + unit coverage for the vendored YAML-subset reader (`miniYaml.ts`).
//
// The reader replaces the lone non-host runtime import (`yaml`) so the extension is self-contained
// in a consumer git clone. `yaml` survives as a DEV-only dependency that powers the fidelity half
// of this test: for each of the three bundled `shared/*.yaml` contracts, the vendored reader must
// produce a value graph deep-equal to the reference parser's. The unit half pins the reader's
// scalar typing, flow collections, comment handling, and loud failure on unsupported constructs.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { parse as referenceParse } from "yaml";
import { parse as miniParse } from "./miniYaml.ts";
import { sharedDir } from "./resources.ts";

test("fidelity: parses all three bundled shared/*.yaml files identically to the reference parser", () => {
  for (const file of ["registry.yaml", "bindings.yaml", "providers.yaml"]) {
    const text = readFileSync(join(sharedDir(), file), "utf8");
    assert.deepStrictEqual(
      miniParse(text),
      referenceParse(text),
      `${file} should parse identically to the reference yaml lib`,
    );
  }
});

test("scalar typing: booleans, integers, null, bare and quoted strings", () => {
  assert.deepStrictEqual(miniParse("a: true\nb: false\nc: null\nd: 1\ne: bare string\nf: -7"), {
    a: true,
    b: false,
    c: null,
    d: 1,
    e: "bare string",
    f: -7,
  });
});

test("double-quoted strings keep colons/at/slash and an inner # is not a comment", () => {
  assert.deepStrictEqual(
    miniParse('trigger: "stage:plan"\npkg: "npm:@tombell/pi-plan"\nh: "a # b"'),
    {
      trigger: "stage:plan",
      pkg: "npm:@tombell/pi-plan",
      h: "a # b",
    },
  );
});

test("flow mappings and flow sequences (incl. empty) parse recursively", () => {
  assert.deepStrictEqual(
    miniParse(
      "doors: { warm: true, cold_local: true, cold_remote: false }\nempty: []\nlist: [a, b]",
    ),
    {
      doors: { warm: true, cold_local: true, cold_remote: false },
      empty: [],
      list: ["a", "b"],
    },
  );
});

test("block sequences of mappings (the `- id: x` map-as-sequence-item shape)", () => {
  const text = "stages:\n  - id: one\n    mode: read-only\n  - id: two\n    mode: read-write\n";
  assert.deepStrictEqual(miniParse(text), {
    stages: [
      { id: "one", mode: "read-only" },
      { id: "two", mode: "read-write" },
    ],
  });
});

test("nested block mapping with block-sequence scalar leaves", () => {
  const text = "state_keys:\n  github:\n    - plan\n    - pr\n  session:\n    - workflow-state\n";
  assert.deepStrictEqual(miniParse(text), {
    state_keys: {
      github: ["plan", "pr"],
      session: ["workflow-state"],
    },
  });
});

test("strips trailing and whole-line comments and blank lines", () => {
  const text = "# header comment\n\nschema_version: 1  # trailing\nname: perk  # another\n";
  assert.deepStrictEqual(miniParse(text), { schema_version: 1, name: "perk" });
});

test("folds the `>` block scalar used by package skill frontmatter", () => {
  assert.deepStrictEqual(
    miniParse("name: ponytail\ndescription: >\n  lazy senior\n  minimal code\nlicense: MIT\n"),
    { name: "ponytail", description: "lazy senior minimal code", license: "MIT" },
  );
});

test("throws loudly on an unsupported block scalar (`|`)", () => {
  assert.throws(() => miniParse("body: |\n  some block\n  text\n"), /not supported|unsupported/i);
});

test("throws loudly on a single-quoted string", () => {
  assert.throws(() => miniParse("name: 'single'"), /single-quoted/i);
});

test("throws loudly on a multi-document stream", () => {
  assert.throws(() => miniParse("a: 1\n---\nb: 2\n"), /multi-document/i);
});
