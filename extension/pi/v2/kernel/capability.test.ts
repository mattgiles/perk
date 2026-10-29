// The capability set (docs/design/pi-durable-v2-foundations.md §4, P7): the canonical-JSON golden
// of the normalized set, its digest as an independent hash of that literal, permutation
// invariance, and the RangeError on every malformed field.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import { canonicalJson } from "./canonical.ts";
import { type CapabilitySet, capabilitySetDigest, normalizeCapabilitySet } from "./capability.ts";

const DIGEST_1 = "1".repeat(64);

const SET: CapabilitySet = {
  model: { provider: "faux", modelId: "faux-1" },
  extensions: ["perk.v2.report"],
  tools: ["read", "ls", "grep", "find"],
  instructionsDigest: DIGEST_1,
  posture: "read-only",
  workspaceRoot: "subject-snapshot",
};

const GOLDEN =
  '{"extensions":["perk.v2.report"],"instructionsDigest":"1111111111111111111111111111111111111111111111111111111111111111","model":{"modelId":"faux-1","provider":"faux"},"posture":"read-only","tools":["find","grep","ls","read"],"workspaceRoot":"subject-snapshot"}';

test("the normalized set's canonical JSON is the golden; the digest hashes it", () => {
  assert.equal(canonicalJson(normalizeCapabilitySet(SET)), GOLDEN);
  assert.equal(capabilitySetDigest(SET), createHash("sha256").update(GOLDEN, "utf8").digest("hex"));
});

test("a permuted input gives the same digest, and normalization is a fresh value", () => {
  const permuted: CapabilitySet = {
    workspaceRoot: "subject-snapshot",
    posture: "read-only",
    tools: ["find", "read", "grep", "ls"],
    instructionsDigest: DIGEST_1,
    extensions: ["perk.v2.report"],
    model: { modelId: "faux-1", provider: "faux" },
  };
  assert.equal(capabilitySetDigest(permuted), capabilitySetDigest(SET));
  const normalized = normalizeCapabilitySet(SET);
  assert.notEqual(normalized.tools, SET.tools);
  assert.deepEqual(SET.tools, ["read", "ls", "grep", "find"], "the input is not mutated");
});

test("a malformed set throws RangeError", () => {
  const cases: [string, unknown][] = [
    ["duplicate tool", { ...SET, tools: ["read", "ls", "read"] }],
    ["duplicate extension", { ...SET, extensions: ["x", "x"] }],
    ["empty tool name", { ...SET, tools: ["read", ""] }],
    ["empty extension name", { ...SET, extensions: [""] }],
    ["lone-surrogate tool name", { ...SET, tools: ["re\uD800ad"] }],
    ["empty provider", { ...SET, model: { provider: "", modelId: "faux-1" } }],
    ["lone-surrogate modelId", { ...SET, model: { provider: "faux", modelId: "\uDC00" } }],
    ["short instructionsDigest", { ...SET, instructionsDigest: "1111" }],
    ["uppercase instructionsDigest", { ...SET, instructionsDigest: "A".repeat(64) }],
    ["wrong posture", { ...SET, posture: "read-write" }],
    ["wrong workspace root", { ...SET, workspaceRoot: "/abs/path" }],
  ];
  for (const [label, set] of cases) {
    assert.throws(() => capabilitySetDigest(set as CapabilitySet), RangeError, label);
  }
});
