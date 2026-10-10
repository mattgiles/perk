// loadHostFloor against the REAL bundled host-floor.yaml, plus the structural refusals. The
// pinned literals match tests/test_host_floor.py's — the cross-plane drift alarm. The Python
// plane is the authoritative content validator; this is the thin TS-side structural parse.

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadHostFloor, parseHostFloor } from "./hostFloor.ts";

test("loadHostFloor: returns the shipped floors", () => {
  assert.deepEqual(loadHostFloor(), {
    schemaVersion: 1,
    piMinVersion: "1.1.0",
    nodeMinVersion: "22.19.0",
  });
});

const GOOD = 'schema_version: 1\npi:\n  min_version: "1.0.0"\nnode:\n  min_version: "22.19.0"\n';

test("parseHostFloor: a good declaration parses", () => {
  assert.deepEqual(parseHostFloor(GOOD, "good.yaml"), {
    schemaVersion: 1,
    piMinVersion: "1.0.0",
    nodeMinVersion: "22.19.0",
  });
});

test("parseHostFloor: a non-mapping top level throws", () => {
  assert.throws(() => parseHostFloor("- 1.0.0\n", "list.yaml"), /list\.yaml is not a mapping/);
});

test("parseHostFloor: a missing pi entry throws", () => {
  const text = GOOD.replace('pi:\n  min_version: "1.0.0"\n', "");
  assert.throws(() => parseHostFloor(text, "x.yaml"), /x\.yaml has no pi\.min_version/);
});

test("parseHostFloor: a non-string min_version throws", () => {
  const text = GOOD.replace('min_version: "22.19.0"', "min_version: 22");
  assert.throws(() => parseHostFloor(text, "x.yaml"), /x\.yaml has no node\.min_version/);
});
