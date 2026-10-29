// The fixture worker policy (docs/design/pi-durable-v2-foundations.md §12 the native assignment):
// `fixturePolicy()` is already normalized and binds the digest of the one instructions text and
// every enabled tool, the report tool included; the per-attempt prompt is deterministic and
// validates its parts; and `manifestDigestFor` reads the highest-`seq` observation of a tree.

import assert from "node:assert/strict";
import { test } from "node:test";
import { isWellFormedText, sha256Hex } from "./canonical.ts";
import { normalizeCapabilitySet } from "./capability.ts";
import {
  FIXTURE_MODEL,
  FIXTURE_POLICY_VERSION,
  FIXTURE_REPORT_TOOL,
  FIXTURE_WORKER_EXTENSION,
  FIXTURE_WORKER_TOOLS,
  fixturePolicy,
  fixtureWorkerPrompt,
  renderFixtureInstructions,
} from "./fixture.ts";
import { observeOpId } from "./identity.ts";
import {
  type ExecutionManifest,
  indexRecords,
  type KernelRecord,
  manifestDigestFor,
  type ObservationRecord,
} from "./records.ts";

const E = "01HZY3V8Q2M5N7P9R1T3V5X7Z9";
const T1 = "1111111111111111111111111111111111111111";
const T2 = "2222222222222222222222222222222222222222";
const T3 = "3333333333333333333333333333333333333333";
const M1 = "a1".repeat(32);
const M2 = "a2".repeat(32);

const MANIFEST: ExecutionManifest = {
  type: "manifest",
  recordVersion: 1,
  definitions: { "perk.v2.assignment": 1 },
  policyVersion: 1,
  durableVersion: "1.4.0",
  chordVersion: "1.4.0",
  workspace: { repoIdentity: "/repo/.git", executionId: E },
  executionKind: "fixture-review",
  createdAt: 1_700_000_000_000,
};

function observation(seq: number, tree: string, manifestDigest: string): ObservationRecord {
  return {
    type: "observation",
    opId: observeOpId(E, seq),
    seq,
    repo: "/repo/.git",
    ref: "refs/heads/main",
    commit: "c1".repeat(20),
    tree,
    manifestDigest,
    observedAt: 1000,
  };
}

test("fixturePolicy() is normalized and binds the instructions digest and every tool", () => {
  const policy = fixturePolicy();
  assert.deepEqual(normalizeCapabilitySet(policy.capabilitySet), policy.capabilitySet);
  assert.deepEqual(policy.capabilitySet, {
    model: { provider: "faux", modelId: "faux-1" },
    extensions: ["perk.v2.report"],
    tools: ["find", "grep", "ls", "read", "report"],
    instructionsDigest: sha256Hex(renderFixtureInstructions()),
    posture: "read-only",
    workspaceRoot: "subject-snapshot",
  });
  assert.deepEqual(policy.capabilitySet.model, FIXTURE_MODEL);
  assert.deepEqual(policy.capabilitySet.extensions, [FIXTURE_WORKER_EXTENSION]);
  assert.deepEqual(policy.capabilitySet.tools, [...FIXTURE_WORKER_TOOLS]);
  assert.ok(FIXTURE_WORKER_TOOLS.includes(FIXTURE_REPORT_TOOL), "the report tool is bound (P7)");
  assert.equal(FIXTURE_POLICY_VERSION, 1);
  assert.deepEqual(fixturePolicy(), policy, "a pure function");
});

test("the instructions are fixed, non-empty, well-formed text naming every tool", () => {
  const text = renderFixtureInstructions();
  assert.equal(text, renderFixtureInstructions());
  assert.ok(text.length > 0);
  assert.ok(isWellFormedText(text));
  for (const tool of FIXTURE_WORKER_TOOLS) assert.ok(text.includes(`\`${tool}\``), tool);
});

test("the worker prompt is deterministic and validates its parts", () => {
  assert.equal(fixtureWorkerPrompt("a", T1), `Review subject ${T1} as reviewer a.`);
  assert.equal(fixtureWorkerPrompt("a", T1), fixtureWorkerPrompt("a", T1));
  assert.notEqual(fixtureWorkerPrompt("a", T1), fixtureWorkerPrompt("b", T1));
  assert.throws(() => fixtureWorkerPrompt("A", T1), RangeError);
  assert.throws(() => fixtureWorkerPrompt("a", "not-a-tree"), RangeError);
});

test("manifestDigestFor reads the highest-seq observation of the tree, and null otherwise", () => {
  const records: KernelRecord[] = [
    MANIFEST,
    observation(1, T1, M1),
    observation(2, T2, M2),
    observation(3, T1, M1),
  ];
  const index = indexRecords(records);
  assert.equal(manifestDigestFor(index, T1), M1);
  assert.equal(manifestDigestFor(index, T2), M2);
  assert.equal(manifestDigestFor(index, T3), null);
  assert.equal(manifestDigestFor(indexRecords([]), T1), null);
  // The latest observation wins even if (impossibly) the digests disagreed.
  const disagreeing = indexRecords([MANIFEST, observation(1, T1, M1), observation(2, T1, M2)]);
  assert.equal(manifestDigestFor(disagreeing, T1), M2);
});
