// The v2 record types and the integrity rules between them (docs/design/pi-durable-v2-foundations.md
// §5 observation records, §6 families and key shapes, §10 the execution manifest).
//
// Invariants:
// - Every operation record carries its op id plus the identity fields derivable from it, beside
//   its §4 payload; all record types are `type` aliases so they assign to `JsonValue`.
// - Records only ever come from kernel output, so a correct binding presents a set `indexRecords`
//   accepts by construction. A set that fails a shape, identity or reference rule is a binding
//   fault — `KernelInvariantError`, never a refusal.
// - Insertion order never leaks: every list and map in the index is ordered by op id or seq.
// - Limit: an omitted record that nothing references (an attempt with no outcome yet, the latest
//   observation, the cancellation) is undetectable here; presenting the complete set is the
//   binding's obligation.

import { asJsonValue, isWellFormedText, jsonEquals } from "./canonical.ts";
import { type CapabilitySet, capabilitySetDigest, normalizeCapabilitySet } from "./capability.ts";
import {
  acceptReportOpId,
  admitOpId,
  aggregateOpId,
  cancelOpId,
  continuationOpId,
  deriveAssignmentId,
  deriveAttemptId,
  deriveDecisionId,
  isExecutionId,
  isGitOid,
  isSha256Hex,
  isSlug,
  observeOpId,
  openDecisionOpId,
  replyOpId,
  submitOpId,
} from "./identity.ts";
import { type Subject, subjectDigest } from "./subject.ts";

export const RECORD_VERSION = 1;

/** The `perk.v2.manifest` singleton (§10); it has no op id. */
export type ExecutionManifest = {
  readonly type: "manifest";
  readonly recordVersion: number;
  readonly definitions: { readonly [name: string]: number };
  readonly policyVersion: number;
  readonly durableVersion: string;
  readonly chordVersion: string;
  readonly workspace: { readonly repoIdentity: string; readonly executionId: string };
  readonly executionKind: string;
  readonly createdAt: number;
};

/** The observing verb's pre-commit read of the tracked ref; `observedAt` is display-only. */
export type ObservationFacts = {
  readonly repo: string;
  readonly ref: string;
  readonly commit: string;
  readonly tree: string;
  readonly manifestDigest: string;
  readonly observedAt: number;
};

export type ObservationRecord = {
  readonly type: "observation";
  readonly opId: string;
  readonly seq: number;
  readonly repo: string;
  readonly ref: string;
  readonly commit: string;
  readonly tree: string;
  readonly manifestDigest: string;
  readonly observedAt: number;
};

export type AssignmentRecord = {
  readonly type: "assignment";
  readonly opId: string;
  readonly assignmentId: string;
  readonly kind: string;
  readonly role: string;
  readonly subject: Subject;
  readonly capabilitySet: CapabilitySet;
};

export type AttemptRecord = {
  readonly type: "attempt";
  readonly opId: string;
  readonly attemptId: string;
  readonly assignmentId: string;
  readonly ordinal: number;
};

/** The fixture report schema `{subjectDigest, summary, findings: [{path, note}]}` (§12). */
export type FixtureReport = {
  readonly subjectDigest: string;
  readonly summary: string;
  readonly findings: readonly { readonly path: string; readonly note: string }[];
};

export type ReportOutcomeRecord = {
  readonly type: "report-outcome";
  readonly opId: string;
  readonly attemptId: string;
  readonly assignmentId: string;
  readonly subjectDigest: string;
  readonly verifiedDigest: string;
  readonly report: FixtureReport;
};

export type AggregateOutcomeRecord = {
  readonly type: "aggregate-outcome";
  readonly opId: string;
  readonly subjectDigest: string;
  readonly outcomeIds: readonly string[];
};

export type DecisionRecord = {
  readonly type: "decision";
  readonly opId: string;
  readonly decisionId: string;
  readonly subjectDigest: string;
  readonly decisionKind: string;
  readonly aggregateId: string;
  readonly allowedActions: readonly string[];
  readonly actor: string;
};

export type ReplyRecord = {
  readonly type: "reply";
  readonly opId: string;
  readonly decisionId: string;
  readonly action: string;
  readonly actor: string;
};

/** The binding's projection of the durable-map row keyed `<decision-id>/continuation` (§6). */
export type ContinuationRecord = {
  readonly type: "continuation";
  readonly opId: string;
  readonly decisionId: string;
};

export type CancellationRecord = {
  readonly type: "cancellation";
  readonly opId: string;
  readonly reason: string;
};

export type OperationRecord =
  | ObservationRecord
  | AssignmentRecord
  | AttemptRecord
  | ReportOutcomeRecord
  | AggregateOutcomeRecord
  | DecisionRecord
  | ReplyRecord
  | ContinuationRecord
  | CancellationRecord;

export type KernelRecord = ExecutionManifest | OperationRecord;

/** A malformed record set: a binding fault, never a caller error. */
export class KernelInvariantError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "KernelInvariantError";
  }
}

function isText(value: unknown): value is string {
  return typeof value === "string" && value !== "" && isWellFormedText(value);
}

/** The first problem with an observation's facts, or `null` when they are valid. */
export function observationProblem(facts: ObservationFacts): string | null {
  if (typeof facts !== "object" || facts === null) return "observation is not an object";
  if (!isText(facts.repo)) return "repo is not a non-empty well-formed string";
  if (!isText(facts.ref)) return "ref is not a non-empty well-formed string";
  if (!isGitOid(facts.commit)) return "commit is not a lowercase git oid";
  if (!isGitOid(facts.tree)) return "tree is not a lowercase git oid";
  if (!isSha256Hex(facts.manifestDigest)) return "manifestDigest is not 64 lowercase hex";
  if (!Number.isSafeInteger(facts.observedAt) || facts.observedAt < 0) {
    return "observedAt is not a non-negative safe integer";
  }
  return null;
}

/** The first problem with an execution manifest `start` would record, or `null`. */
export function manifestProblem(manifest: ExecutionManifest): string | null {
  if (typeof manifest !== "object" || manifest === null || asJsonValue(manifest) === null) {
    return "manifest is not JSON-compatible";
  }
  if (manifest.type !== "manifest") return 'type is not "manifest"';
  if (manifest.recordVersion !== RECORD_VERSION) return `recordVersion is not ${RECORD_VERSION}`;
  if (!isSlug(manifest.executionKind)) return "executionKind is not a slug";
  if (
    typeof manifest.workspace !== "object" ||
    manifest.workspace === null ||
    !isExecutionId(manifest.workspace.executionId)
  ) {
    return "workspace.executionId is not a ULID";
  }
  return null;
}

/** The validated record set, with its lookups. Every list is ordered by op id or seq. */
export type RecordIndex = {
  readonly manifest: ExecutionManifest | null;
  /** Ascending `seq`. */
  readonly observations: readonly ObservationRecord[];
  /** The observation with the highest `seq`. */
  readonly latest: ObservationRecord | null;
  readonly byOpId: ReadonlyMap<string, OperationRecord>;
  /** By assignment id. */
  readonly assignments: ReadonlyMap<string, AssignmentRecord>;
  /** By attempt id. */
  readonly attempts: ReadonlyMap<string, AttemptRecord>;
  /** By assignment id; each list ordered by op id. */
  readonly attemptsByAssignment: ReadonlyMap<string, readonly AttemptRecord[]>;
  /** By attempt id. */
  readonly outcomesByAttempt: ReadonlyMap<string, ReportOutcomeRecord>;
  /** By subject digest. */
  readonly aggregatesBySubject: ReadonlyMap<string, AggregateOutcomeRecord>;
  /** By decision id. */
  readonly decisions: ReadonlyMap<string, DecisionRecord>;
  /** Ordered by op id. */
  readonly replies: readonly ReplyRecord[];
  /** By decision id. */
  readonly continuations: ReadonlyMap<string, ContinuationRecord>;
  readonly cancellation: CancellationRecord | null;
};

const OPERATION_TYPES: readonly string[] = [
  "observation",
  "assignment",
  "attempt",
  "report-outcome",
  "aggregate-outcome",
  "decision",
  "reply",
  "continuation",
  "cancellation",
];

function violation(subject: string, rule: string): KernelInvariantError {
  return new KernelInvariantError(`${subject}: ${rule}`);
}

function compareOpIds(a: OperationRecord, b: OperationRecord): number {
  return a.opId < b.opId ? -1 : a.opId > b.opId ? 1 : 0;
}

/** Run a derivation over stored fields; a malformed field is an integrity violation. */
function derived(opId: string, rule: string, derive: () => string): string {
  try {
    return derive();
  } catch (error) {
    if (error instanceof RangeError) throw violation(opId, `${rule} (${error.message})`);
    throw error;
  }
}

function expectDerived(opId: string, actual: string, rule: string, derive: () => string): void {
  if (actual !== derived(opId, rule, derive)) throw violation(opId, rule);
}

/** The identity rule: a record's ids equal their derivation from its own fields. */
function checkIdentity(executionId: string, record: OperationRecord): void {
  const { opId } = record;
  switch (record.type) {
    case "observation": {
      const problem = observationProblem(record);
      if (problem !== null) throw violation(opId, `malformed observation: ${problem}`);
      expectDerived(opId, opId, "op id does not derive from its seq", () =>
        observeOpId(executionId, record.seq),
      );
      return;
    }
    case "assignment":
      if (record.subject?.kind !== "git-tree") throw violation(opId, "unknown subject kind");
      expectDerived(
        opId,
        record.assignmentId,
        "assignment id does not derive from its kind, role, subject and capability set",
        () =>
          deriveAssignmentId({
            executionId,
            kind: record.kind,
            role: record.role,
            subjectDigest: subjectDigest(record.subject),
            capabilitySetDigest: capabilitySetDigest(record.capabilitySet),
          }),
      );
      expectDerived(opId, opId, "op id does not derive from its assignment id", () =>
        admitOpId(record.assignmentId),
      );
      return;
    case "attempt":
      expectDerived(
        opId,
        record.attemptId,
        "attempt id does not derive from its assignment id and ordinal",
        () => deriveAttemptId(record.assignmentId, record.ordinal),
      );
      expectDerived(opId, opId, "op id does not derive from its attempt id", () =>
        submitOpId(record.attemptId),
      );
      return;
    case "report-outcome":
      expectDerived(opId, opId, "op id does not derive from its attempt id", () =>
        acceptReportOpId(record.attemptId),
      );
      return;
    case "aggregate-outcome":
      expectDerived(opId, opId, "op id does not derive from its subject", () =>
        aggregateOpId(executionId, record.subjectDigest),
      );
      return;
    case "decision":
      expectDerived(
        opId,
        record.decisionId,
        "decision id does not derive from its subject and decision kind",
        () =>
          deriveDecisionId({
            executionId,
            subjectDigest: record.subjectDigest,
            decisionKind: record.decisionKind,
          }),
      );
      expectDerived(opId, opId, "op id does not derive from its decision id", () =>
        openDecisionOpId(record.decisionId),
      );
      return;
    case "reply":
      expectDerived(opId, opId, "op id does not derive from its decision id", () =>
        replyOpId(record.decisionId),
      );
      return;
    case "continuation":
      expectDerived(opId, opId, "op id does not derive from its decision id", () =>
        continuationOpId(record.decisionId),
      );
      return;
    case "cancellation":
      expectDerived(opId, opId, "op id does not derive from the execution", () =>
        cancelOpId(executionId),
      );
      return;
  }
}

/**
 * Validate `records` and build the index. Throws `KernelInvariantError`, naming the offending op
 * id and rule, on a shape violation (more than one manifest, an operation record without a
 * manifest, a duplicate op id, observation seqs other than exactly 1..n), an identity violation
 * (an id that does not derive from the record's own fields), or a reference violation (a record
 * naming something missing or inconsistent — see the checks below).
 */
export function indexRecords(records: readonly KernelRecord[]): RecordIndex {
  // ── shape ──
  const manifests: ExecutionManifest[] = [];
  const unsorted: OperationRecord[] = [];
  for (const record of records) {
    if (record.type === "manifest") manifests.push(record);
    else if (OPERATION_TYPES.includes(record.type)) unsorted.push(record);
    else throw violation(String(Reflect.get(record, "opId")), "unknown record type");
  }
  if (manifests.length > 1) throw violation("manifest", "more than one manifest");
  const manifest = manifests[0] ?? null;
  const operations = unsorted.toSorted(compareOpIds);
  const first = operations[0];
  if (manifest === null) {
    if (first !== undefined) throw violation(first.opId, "operation record without a manifest");
    return emptyIndex();
  }
  const byOpId = new Map<string, OperationRecord>();
  for (const record of operations) {
    if (byOpId.has(record.opId)) throw violation(record.opId, "duplicate op id");
    byOpId.set(record.opId, record);
  }
  const observations = operations
    .filter((record): record is ObservationRecord => record.type === "observation")
    .toSorted((a, b) => a.seq - b.seq);
  observations.forEach((observation, i) => {
    if (observation.seq !== i + 1) {
      throw violation(observation.opId, "observation seqs are not exactly 1..n");
    }
  });

  // ── identity ──
  const problem = manifestProblem(manifest);
  if (problem !== null) throw violation("manifest", `malformed manifest: ${problem}`);
  const executionId = manifest.workspace.executionId;
  for (const record of operations) checkIdentity(executionId, record);

  // ── lookups ──
  const assignments = new Map<string, AssignmentRecord>();
  const attempts = new Map<string, AttemptRecord>();
  const attemptsByAssignment = new Map<string, AttemptRecord[]>();
  const outcomesByAttempt = new Map<string, ReportOutcomeRecord>();
  const aggregatesBySubject = new Map<string, AggregateOutcomeRecord>();
  const decisions = new Map<string, DecisionRecord>();
  const replies: ReplyRecord[] = [];
  const continuations = new Map<string, ContinuationRecord>();
  let cancellation: CancellationRecord | null = null;
  for (const record of operations) {
    switch (record.type) {
      case "assignment":
        assignments.set(record.assignmentId, record);
        break;
      case "attempt": {
        attempts.set(record.attemptId, record);
        const list = attemptsByAssignment.get(record.assignmentId) ?? [];
        list.push(record);
        attemptsByAssignment.set(record.assignmentId, list);
        break;
      }
      case "report-outcome":
        outcomesByAttempt.set(record.attemptId, record);
        break;
      case "aggregate-outcome":
        aggregatesBySubject.set(record.subjectDigest, record);
        break;
      case "decision":
        decisions.set(record.decisionId, record);
        break;
      case "reply":
        replies.push(record);
        break;
      case "continuation":
        continuations.set(record.decisionId, record);
        break;
      case "cancellation":
        cancellation = record;
        break;
      case "observation":
        break;
    }
  }

  // ── references and consistency ──
  const tracked = observations[0];
  for (const observation of observations) {
    if (
      tracked !== undefined &&
      (observation.repo !== tracked.repo || observation.ref !== tracked.ref)
    ) {
      throw violation(observation.opId, "observation names another repo or ref than seq 1");
    }
  }
  for (const assignment of assignments.values()) {
    const json = asJsonValue(assignment.capabilitySet);
    if (json === null || !jsonEquals(json, normalizeCapabilitySet(assignment.capabilitySet))) {
      throw violation(assignment.opId, "capability set is not normalized");
    }
  }
  for (const attempt of attempts.values()) {
    if (!assignments.has(attempt.assignmentId)) {
      throw violation(attempt.opId, "attempt names a missing assignment");
    }
  }
  for (const outcome of outcomesByAttempt.values()) {
    const attempt = attempts.get(outcome.attemptId);
    if (attempt === undefined)
      throw violation(outcome.opId, "report outcome names a missing attempt");
    if (outcome.assignmentId !== attempt.assignmentId) {
      throw violation(outcome.opId, "report outcome names another assignment than its attempt");
    }
    if (outcome.subjectDigest !== assignments.get(attempt.assignmentId)?.subject.digest) {
      throw violation(outcome.opId, "report outcome subject differs from its assignment's");
    }
    if (outcome.report?.subjectDigest !== outcome.subjectDigest) {
      throw violation(outcome.opId, "report subject differs from its outcome's");
    }
  }
  for (const aggregate of aggregatesBySubject.values()) {
    const ids = aggregate.outcomeIds;
    if (!Array.isArray(ids) || ids.length === 0) {
      throw violation(aggregate.opId, "aggregate names no outcome");
    }
    if (new Set(ids).size !== ids.length) {
      throw violation(aggregate.opId, "aggregate names an outcome twice");
    }
    for (const id of ids) {
      const outcome = byOpId.get(id);
      if (outcome?.type !== "report-outcome") {
        throw violation(aggregate.opId, `aggregate names a missing report outcome ${id}`);
      }
      if (outcome.subjectDigest !== aggregate.subjectDigest) {
        throw violation(aggregate.opId, `aggregate names an outcome over another subject ${id}`);
      }
    }
  }
  for (const decision of decisions.values()) {
    const aggregate = byOpId.get(decision.aggregateId);
    if (
      aggregate?.type !== "aggregate-outcome" ||
      aggregate.subjectDigest !== decision.subjectDigest
    ) {
      throw violation(decision.opId, "decision names no aggregate over its subject");
    }
  }
  for (const reply of replies) {
    const decision = decisions.get(reply.decisionId);
    if (decision === undefined) throw violation(reply.opId, "reply names a missing decision");
    if (!decision.allowedActions.includes(reply.action)) {
      throw violation(reply.opId, "reply action is not allowed by its decision");
    }
    if (reply.actor !== decision.actor) {
      throw violation(reply.opId, "reply actor differs from its decision's");
    }
  }
  for (const continuation of continuations.values()) {
    if (byOpId.get(replyOpId(continuation.decisionId))?.type !== "reply") {
      throw violation(continuation.opId, "continuation has no reply for its decision");
    }
  }

  return {
    manifest,
    observations,
    latest: observations.at(-1) ?? null,
    byOpId,
    assignments,
    attempts,
    attemptsByAssignment,
    outcomesByAttempt,
    aggregatesBySubject,
    decisions,
    replies,
    continuations,
    cancellation,
  };
}

/**
 * The manifest digest of `tree`: that of the highest-`seq` observation of it, or `null` when no
 * observation names it. A tree's manifest digest is a function of the tree, so every observation of
 * it agrees; the latest is read only to make the choice deterministic.
 */
export function manifestDigestFor(index: RecordIndex, tree: string): string | null {
  return (
    index.observations.findLast((observation) => observation.tree === tree)?.manifestDigest ?? null
  );
}

function emptyIndex(): RecordIndex {
  return {
    manifest: null,
    observations: [],
    latest: null,
    byOpId: new Map(),
    assignments: new Map(),
    attempts: new Map(),
    attemptsByAssignment: new Map(),
    outcomesByAttempt: new Map(),
    aggregatesBySubject: new Map(),
    decisions: new Map(),
    replies: [],
    continuations: new Map(),
    cancellation: null,
  };
}
