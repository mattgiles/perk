// The exact-match gate's comparison (docs/design/pi-durable-v2-foundations.md §10 step 4): equal
// manifests match whatever their `createdAt` or `definitions` key order; each gate field is caught
// alone, with the whole expected and found values; several differences report the earliest field;
// a stored manifest missing a field reads `found: null`; and every manifest field is classified.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { JsonValue } from "./canonical.ts";
import {
  MANIFEST_FIELD_POLICY,
  MANIFEST_GATE_FIELDS,
  type ManifestGateField,
  manifestMismatch,
} from "./compatibility.ts";
import type { ExecutionManifest } from "./records.ts";

function sample(): ExecutionManifest {
  return {
    type: "manifest",
    recordVersion: 1,
    definitions: { "perk.v2.catalog": 1, "perk.v2.step": 1, "perk.v2.fake-assignment": 1 },
    policyVersion: 1,
    durableVersion: "1.4.0",
    chordVersion: "1.4.0",
    workspace: { repoIdentity: "/repo/.git", executionId: "01HZY3V8Q2M5N7P9R1T3V5X7Z9" },
    executionKind: "fixture-review",
    createdAt: 1_700_000_000_000,
  };
}

/** One changed value per gate field. */
const CHANGED: { readonly [K in ManifestGateField]: ExecutionManifest[K] } = {
  recordVersion: 2,
  definitions: { "perk.v2.catalog": 1, "perk.v2.step": 2, "perk.v2.fake-assignment": 1 },
  policyVersion: 2,
  durableVersion: "1.5.0",
  chordVersion: "1.5.0",
  workspace: { repoIdentity: "/other/.git", executionId: "01HZY3V8Q2M5N7P9R1T3V5X7Z9" },
  executionKind: "other-review",
};

test("equal manifests match, whatever their createdAt and definitions key order", () => {
  assert.equal(manifestMismatch(sample(), sample()), null);
  const reordered: ExecutionManifest = {
    ...sample(),
    definitions: { "perk.v2.fake-assignment": 1, "perk.v2.step": 1, "perk.v2.catalog": 1 },
    createdAt: 42,
  };
  assert.equal(manifestMismatch(sample(), reordered), null);
});

test("each gate field changed alone is named, with the whole expected and found values", () => {
  for (const field of MANIFEST_GATE_FIELDS) {
    const found: ExecutionManifest = { ...sample(), [field]: CHANGED[field] };
    assert.deepEqual(
      manifestMismatch(sample(), found),
      {
        field,
        expected: sample()[field] as JsonValue,
        found: CHANGED[field] as JsonValue,
      },
      field,
    );
  }
});

test("several differences report the earliest field in gate order", () => {
  const found: ExecutionManifest = {
    ...sample(),
    executionKind: CHANGED.executionKind,
    chordVersion: CHANGED.chordVersion,
    policyVersion: CHANGED.policyVersion,
  };
  assert.equal(manifestMismatch(sample(), found)?.field, "policyVersion");
  const later: ExecutionManifest = { ...found, policyVersion: 1 };
  assert.equal(manifestMismatch(sample(), later)?.field, "chordVersion");
});

test("a stored manifest missing a field reads found: null", () => {
  const { durableVersion: _omitted, ...rest } = sample();
  // A malformed store: the field is absent from the stored value.
  const found = rest as ExecutionManifest;
  assert.deepEqual(manifestMismatch(sample(), found), {
    field: "durableVersion",
    expected: "1.4.0",
    found: null,
  });
});

test("census: every manifest field is classified, and the compared ones are the gate fields", () => {
  const policy: Readonly<Record<string, string>> = MANIFEST_FIELD_POLICY;
  assert.deepEqual(Object.keys(policy).sort(), Object.keys(sample()).sort());
  assert.deepEqual(
    Object.keys(policy)
      .filter((field) => policy[field] === "compared")
      .sort(),
    [...MANIFEST_GATE_FIELDS].sort(),
  );
  assert.deepEqual(
    Object.keys(policy).filter((field) => policy[field] === "excluded"),
    ["type", "createdAt"],
  );
});
