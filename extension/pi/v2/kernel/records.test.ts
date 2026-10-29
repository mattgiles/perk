// The record integrity rules (docs/design/pi-durable-v2-foundations.md §5, §6): one valid set,
// built by hand through the derivation functions, holds every record type and is accepted; each
// malformed-set row changes exactly one thing (re-deriving any op id the change would otherwise
// break, and dropping the dependents of a removed record except the one under test) and must
// throw `KernelInvariantError` naming its rule. The observation and manifest checks get per-field
// tables.

import assert from "node:assert/strict";
import { test } from "node:test";
import { type CapabilitySet, capabilitySetDigest } from "./capability.ts";
import {
  acceptReportOpId,
  admitOpId,
  aggregateOpId,
  cancelOpId,
  continuationOpId,
  deriveAssignmentId,
  deriveAttemptId,
  deriveDecisionId,
  observeOpId,
  openDecisionOpId,
  replyOpId,
  submitOpId,
} from "./identity.ts";
import {
  type AggregateOutcomeRecord,
  type AssignmentRecord,
  type AttemptRecord,
  type CancellationRecord,
  type ContinuationRecord,
  type DecisionRecord,
  type ExecutionManifest,
  indexRecords,
  KernelInvariantError,
  type KernelRecord,
  manifestProblem,
  type ObservationFacts,
  type ObservationRecord,
  observationProblem,
  type ReplyRecord,
  type ReportOutcomeRecord,
} from "./records.ts";

// ── builders ────────────────────────────────────────────────────────────────────────────────────

const E = "01HZY3V8Q2M5N7P9R1T3V5X7Z9";
const T1 = "1111111111111111111111111111111111111111";
const T2 = "2222222222222222222222222222222222222222";
const C1 = "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1";
const C2 = "c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2";
const M1 = "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
const M2 = "a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2";

const CAPSET: CapabilitySet = {
  model: { provider: "faux", modelId: "faux-1" },
  extensions: ["perk.v2.report"],
  tools: ["find", "grep", "ls", "read"],
  instructionsDigest: "1".repeat(64),
  posture: "read-only",
  workspaceRoot: "subject-snapshot",
};

const MANIFEST: ExecutionManifest = {
  type: "manifest",
  recordVersion: 1,
  definitions: { "perk.v2.assignment": 1, "perk.v2.reply": 1 },
  policyVersion: 1,
  durableVersion: "1.4.0",
  chordVersion: "1.4.0",
  workspace: { repoIdentity: "/repo/.git", executionId: E },
  executionKind: "fixture-review",
  createdAt: 1_700_000_000_000,
};

function observation(seq: number, tree: string, commit: string, manifestDigest: string) {
  const record: ObservationRecord = {
    type: "observation",
    opId: observeOpId(E, seq),
    seq,
    repo: "/repo/.git",
    ref: "refs/heads/main",
    commit,
    tree,
    manifestDigest,
    observedAt: 1000 * seq,
  };
  return record;
}

function assignment(role: string, tree: string, capabilitySet: CapabilitySet = CAPSET) {
  const assignmentId = deriveAssignmentId({
    executionId: E,
    kind: "fixture-report",
    role,
    subjectDigest: tree,
    capabilitySetDigest: capabilitySetDigest(capabilitySet),
  });
  const record: AssignmentRecord = {
    type: "assignment",
    opId: admitOpId(assignmentId),
    assignmentId,
    kind: "fixture-report",
    role,
    subject: { kind: "git-tree", digest: tree },
    capabilitySet,
  };
  return record;
}

function attempt(of: AssignmentRecord) {
  const attemptId = deriveAttemptId(of.assignmentId, 1);
  const record: AttemptRecord = {
    type: "attempt",
    opId: submitOpId(attemptId),
    attemptId,
    assignmentId: of.assignmentId,
    ordinal: 1,
  };
  return record;
}

function outcome(of: AttemptRecord, tree: string) {
  const record: ReportOutcomeRecord = {
    type: "report-outcome",
    opId: acceptReportOpId(of.attemptId),
    attemptId: of.attemptId,
    assignmentId: of.assignmentId,
    subjectDigest: tree,
    verifiedDigest: M1,
    report: {
      subjectDigest: tree,
      summary: "looks fine",
      findings: [{ path: "a.ts", note: "ok" }],
    },
  };
  return record;
}

const OBS1 = observation(1, T1, C1, M1);
const ASSIGN_A = assignment("a", T1);
const ASSIGN_B = assignment("b", T1);
const ATTEMPT_A = attempt(ASSIGN_A);
const ATTEMPT_B = attempt(ASSIGN_B);
const OUTCOME_A = outcome(ATTEMPT_A, T1);
const OUTCOME_B = outcome(ATTEMPT_B, T1);
const AGGREGATE: AggregateOutcomeRecord = {
  type: "aggregate-outcome",
  opId: aggregateOpId(E, T1),
  subjectDigest: T1,
  outcomeIds: [OUTCOME_A.opId, OUTCOME_B.opId],
};
const D1 = deriveDecisionId({
  executionId: E,
  subjectDigest: T1,
  decisionKind: "fixture-approval",
});
const DECISION: DecisionRecord = {
  type: "decision",
  opId: openDecisionOpId(D1),
  decisionId: D1,
  subjectDigest: T1,
  decisionKind: "fixture-approval",
  aggregateId: AGGREGATE.opId,
  allowedActions: ["approve", "reject"],
  actor: "human:cli",
};
const REPLY: ReplyRecord = {
  type: "reply",
  opId: replyOpId(D1),
  decisionId: D1,
  action: "approve",
  actor: "human:cli",
};
const CONTINUATION: ContinuationRecord = {
  type: "continuation",
  opId: continuationOpId(D1),
  decisionId: D1,
};
const OBS2 = observation(2, T2, C2, M2);
const CANCELLATION: CancellationRecord = {
  type: "cancellation",
  opId: cancelOpId(E),
  reason: "operator stop",
};

/** A completed happy path, plus a T2 observation and a cancellation: every record type. */
const VALID: readonly KernelRecord[] = [
  MANIFEST,
  OBS1,
  ASSIGN_A,
  ASSIGN_B,
  ATTEMPT_A,
  ATTEMPT_B,
  OUTCOME_A,
  OUTCOME_B,
  AGGREGATE,
  DECISION,
  REPLY,
  CONTINUATION,
  OBS2,
  CANCELLATION,
];

function replace(target: KernelRecord, replacement: KernelRecord): KernelRecord[] {
  assert.ok(VALID.includes(target), "the replaced record is in the valid set");
  return VALID.map((record) => (record === target ? replacement : record));
}

function without(...targets: KernelRecord[]): KernelRecord[] {
  for (const target of targets) assert.ok(VALID.includes(target), "removed from the valid set");
  return VALID.filter((record) => !targets.includes(record));
}

// ── the valid set ───────────────────────────────────────────────────────────────────────────────

test("the valid set holds every record type and is accepted", () => {
  assert.deepEqual([...new Set(VALID.map((record) => record.type))].sort(), [
    "aggregate-outcome",
    "assignment",
    "attempt",
    "cancellation",
    "continuation",
    "decision",
    "manifest",
    "observation",
    "reply",
    "report-outcome",
  ]);
  const index = indexRecords(VALID);
  assert.equal(index.manifest, MANIFEST);
  assert.deepEqual(index.observations, [OBS1, OBS2]);
  assert.equal(index.latest, OBS2);
  assert.equal(index.byOpId.size, VALID.length - 1);
  assert.equal(index.assignments.get(ASSIGN_A.assignmentId), ASSIGN_A);
  assert.equal(index.attempts.get(ATTEMPT_B.attemptId), ATTEMPT_B);
  assert.deepEqual(index.attemptsByAssignment.get(ASSIGN_A.assignmentId), [ATTEMPT_A]);
  assert.equal(index.outcomesByAttempt.get(ATTEMPT_A.attemptId), OUTCOME_A);
  assert.equal(index.aggregatesBySubject.get(T1), AGGREGATE);
  assert.equal(index.decisions.get(D1), DECISION);
  assert.deepEqual(index.replies, [REPLY]);
  assert.equal(index.continuations.get(D1), CONTINUATION);
  assert.equal(index.cancellation, CANCELLATION);
});

test("insertion order never leaks into the index", () => {
  const forward = indexRecords(VALID);
  const reversed = indexRecords(VALID.toReversed());
  assert.deepEqual([...reversed.byOpId.keys()], [...forward.byOpId.keys()]);
  assert.deepEqual([...reversed.assignments.keys()], [...forward.assignments.keys()]);
  assert.deepEqual(reversed.observations, forward.observations);
  const opIds = [...forward.byOpId.keys()];
  assert.deepEqual(opIds, opIds.toSorted(), "ordered by op id");
});

test("an empty set and a manifest-only set index to nothing", () => {
  assert.equal(indexRecords([]).manifest, null);
  assert.equal(indexRecords([]).latest, null);
  const index = indexRecords([MANIFEST]);
  assert.equal(index.manifest, MANIFEST);
  assert.equal(index.latest, null);
});

// ── malformed sets ──────────────────────────────────────────────────────────────────────────────

const OTHER_DECISION = deriveDecisionId({
  executionId: E,
  subjectDigest: T2,
  decisionKind: "fixture-approval",
});

const MALFORMED: readonly [string, () => KernelRecord[], string][] = [
  // shape
  ["two manifests", () => [...VALID, { ...MANIFEST, createdAt: 2 }], "more than one manifest"],
  [
    "an observation without a manifest",
    () => without(MANIFEST),
    "operation record without a manifest",
  ],
  ["a duplicate op id", () => [...VALID, { ...REPLY }], "duplicate op id"],
  [
    "seqs 1, 3",
    () => replace(OBS2, { ...OBS2, seq: 3, opId: observeOpId(E, 3) }),
    "observation seqs are not exactly 1..n",
  ],
  [
    "a duplicate seq",
    () => replace(OBS2, { ...OBS2, seq: 1 }),
    "observation seqs are not exactly 1..n",
  ],
  // identity
  [
    "an assignment whose role was edited without re-deriving its id",
    () => replace(ASSIGN_A, { ...ASSIGN_A, role: "c" }),
    "assignment id does not derive from its kind, role, subject and capability set",
  ],
  [
    "a reply whose op id names another decision",
    () => replace(REPLY, { ...REPLY, opId: replyOpId(OTHER_DECISION) }),
    "op id does not derive from its decision id",
  ],
  // references
  [
    "the T2 observation on another ref",
    () => replace(OBS2, { ...OBS2, ref: "refs/heads/other" }),
    "observation names another repo or ref than seq 1",
  ],
  [
    "a non-normalized capability set (tools unsorted, id re-derived)",
    () => {
      const unsorted: CapabilitySet = { ...CAPSET, tools: ["read", "find", "grep", "ls"] };
      const rederived = assignment("a", T1, unsorted);
      assert.equal(rederived.assignmentId, ASSIGN_A.assignmentId, "the digest normalizes");
      return replace(ASSIGN_A, rederived);
    },
    "capability set is not normalized",
  ],
  [
    "an attempt whose assignment was removed",
    () => without(ASSIGN_A, OUTCOME_A, AGGREGATE, DECISION, REPLY, CONTINUATION),
    "attempt names a missing assignment",
  ],
  [
    "a report outcome whose attempt was removed",
    () => without(ATTEMPT_A),
    "report outcome names a missing attempt",
  ],
  [
    "a report outcome with another assignment id",
    () => replace(OUTCOME_A, { ...OUTCOME_A, assignmentId: ASSIGN_B.assignmentId }),
    "report outcome names another assignment than its attempt",
  ],
  [
    "a report outcome with another subject digest",
    () => replace(OUTCOME_A, { ...OUTCOME_A, subjectDigest: T2 }),
    "report outcome subject differs from its assignment's",
  ],
  [
    "a report outcome whose report names another subject",
    () => replace(OUTCOME_A, { ...OUTCOME_A, report: { ...OUTCOME_A.report, subjectDigest: T2 } }),
    "report subject differs from its outcome's",
  ],
  [
    "an aggregate naming a missing outcome",
    () => without(OUTCOME_B),
    "aggregate names a missing report outcome",
  ],
  [
    "an aggregate naming an outcome over another subject",
    () => replace(AGGREGATE, { ...AGGREGATE, subjectDigest: T2, opId: aggregateOpId(E, T2) }),
    "aggregate names an outcome over another subject",
  ],
  [
    "an aggregate with duplicated outcome ids",
    () => replace(AGGREGATE, { ...AGGREGATE, outcomeIds: [OUTCOME_A.opId, OUTCOME_A.opId] }),
    "aggregate names an outcome twice",
  ],
  [
    "an aggregate with no outcome ids",
    () => replace(AGGREGATE, { ...AGGREGATE, outcomeIds: [] }),
    "aggregate names no outcome",
  ],
  [
    "a decision whose aggregate was removed",
    () => without(AGGREGATE),
    "decision names no aggregate over its subject",
  ],
  ["a reply whose decision was removed", () => without(DECISION), "reply names a missing decision"],
  [
    "a reply with an action that is not allowed",
    () => replace(REPLY, { ...REPLY, action: "maybe" }),
    "reply action is not allowed by its decision",
  ],
  [
    "a reply with another actor",
    () => replace(REPLY, { ...REPLY, actor: "human:web" }),
    "reply actor differs from its decision's",
  ],
  [
    "a continuation whose reply was removed",
    () => without(REPLY),
    "continuation has no reply for its decision",
  ],
];

for (const [label, build, rule] of MALFORMED) {
  test(`malformed set — ${label}: KernelInvariantError names the rule`, () => {
    assert.throws(
      () => indexRecords(build()),
      (error: unknown) =>
        error instanceof KernelInvariantError &&
        error.name === "KernelInvariantError" &&
        error.message.includes(rule),
    );
  });
}

// ── per-field tables ────────────────────────────────────────────────────────────────────────────

const FACTS: ObservationFacts = {
  repo: "/repo/.git",
  ref: "refs/heads/main",
  commit: C1,
  tree: T1,
  manifestDigest: M1,
  observedAt: 0,
};

test("observationProblem names the first malformed field", () => {
  assert.equal(observationProblem(FACTS), null);
  const cases: [Partial<Record<keyof ObservationFacts, unknown>>, string][] = [
    [{ repo: "" }, "repo"],
    [{ repo: "/r\uDC00" }, "repo"],
    [{ ref: "" }, "ref"],
    [{ ref: "refs/heads/\uD800" }, "ref"],
    [{ commit: C1.toUpperCase() }, "commit"],
    [{ tree: T1.slice(1) }, "tree"],
    [{ tree: 42 }, "tree"],
    [{ manifestDigest: T1 }, "manifestDigest"],
    [{ observedAt: -1 }, "observedAt"],
    [{ observedAt: 1.5 }, "observedAt"],
    [{ observedAt: Number.NaN }, "observedAt"],
  ];
  for (const [overrides, field] of cases) {
    const problem = observationProblem({ ...FACTS, ...overrides } as ObservationFacts);
    assert.ok(problem?.startsWith(field), `${field}: ${problem}`);
  }
});

test("manifestProblem names a non-JSON manifest and each start check", () => {
  assert.equal(manifestProblem(MANIFEST), null);
  const cases: [string, unknown, string][] = [
    ["lone-surrogate durableVersion", { ...MANIFEST, durableVersion: "1.4\uD800" }, "JSON"],
    ["lone-surrogate definitions key", { ...MANIFEST, definitions: { "\uDC00": 1 } }, "JSON"],
    ["non-finite createdAt", { ...MANIFEST, createdAt: Number.NaN }, "JSON"],
    ["wrong type", { ...MANIFEST, type: "observation" }, "type"],
    ["recordVersion 2", { ...MANIFEST, recordVersion: 2 }, "recordVersion"],
    ["non-slug executionKind", { ...MANIFEST, executionKind: "Fixture Review" }, "executionKind"],
    [
      "lowercase executionId",
      { ...MANIFEST, workspace: { repoIdentity: "/repo/.git", executionId: E.toLowerCase() } },
      "workspace.executionId",
    ],
  ];
  for (const [label, manifest, needle] of cases) {
    const problem = manifestProblem(manifest as ExecutionManifest);
    assert.ok(problem?.includes(needle), `${label}: ${problem}`);
  }
});
