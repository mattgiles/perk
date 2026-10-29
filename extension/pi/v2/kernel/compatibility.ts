// The exact-match compatibility gate's comparison (docs/design/pi-durable-v2-foundations.md §10
// step 4): the execution manifest a host expects against the one its store holds. Any difference
// in a compared field refuses the resume; migrations are deferred (§14).
//
// Invariants:
// - Fields are compared in `MANIFEST_GATE_FIELDS` order and the first difference is reported, with
//   the whole expected and found top-level values.
// - Every manifest field is classified as compared or excluded (`MANIFEST_FIELD_POLICY`, checked
//   by the type), so a new manifest field cannot silently escape the gate. `createdAt` and the
//   constant `type` are excluded.
// - A stored field that is missing or not JSON reads as `null`, so a malformed manifest mismatches
//   rather than throws. Comparison is canonical: key order inside `definitions` is irrelevant.

import { asJsonValue, type JsonValue, jsonEquals } from "./canonical.ts";
import type { ExecutionManifest } from "./records.ts";

export const MANIFEST_GATE_FIELDS = [
  "recordVersion",
  "definitions",
  "policyVersion",
  "durableVersion",
  "chordVersion",
  "workspace",
  "executionKind",
] as const;

export type ManifestGateField = (typeof MANIFEST_GATE_FIELDS)[number];

/** Every execution-manifest field, classified for the gate. */
export const MANIFEST_FIELD_POLICY: {
  readonly [K in keyof ExecutionManifest]-?: "compared" | "excluded";
} = {
  type: "excluded",
  recordVersion: "compared",
  definitions: "compared",
  policyVersion: "compared",
  durableVersion: "compared",
  chordVersion: "compared",
  workspace: "compared",
  executionKind: "compared",
  createdAt: "excluded",
};

/** The first differing gate field, with the whole expected and found values. */
export type ManifestMismatch = {
  readonly field: ManifestGateField;
  readonly expected: JsonValue;
  readonly found: JsonValue;
};

/** The first gate field where `found` differs from `expected`, or `null` when they match. */
export function manifestMismatch(
  expected: ExecutionManifest,
  found: ExecutionManifest,
): ManifestMismatch | null {
  for (const field of MANIFEST_GATE_FIELDS) {
    const expectedValue = asJsonValue(expected[field]);
    const foundValue = asJsonValue(found[field]);
    if (!jsonEquals(expectedValue, foundValue)) {
      return { field, expected: expectedValue, found: foundValue };
    }
  }
  return null;
}
