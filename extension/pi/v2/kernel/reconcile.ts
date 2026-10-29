// The fixture-review rules and the pure operation pipeline (docs/design/pi-durable-v2-foundations.md
// §4 replay rule, §7 write contract and kernel properties, §12 rules and their precisions).
//
// Invariants:
// - `reconcile(records, policy)` is a pure function of the record SET (order never matters) and
//   runs its rules to a fixpoint, so applying its actions and reconciling again yields nothing.
// - Terminal states dominate: once a cancellation is recorded or any continuation exists,
//   reconcile emits no action of any kind.
// - Every rule reads the current subject (the latest observation's tree); a new tree starts a
//   fresh round, and records over earlier trees stay inert.
// - `evaluateOperation` decides one operation completely: receipt lookup first (§4), then
//   identity, freshness, cancellation, supersession and last report content. A refused or
//   replayed operation records nothing, not even its observation.
// - `nextRecords` is the reference applier: a binding persists `recorded` and then exactly the
//   action records, in order.

import { asJsonValue, isWellFormedText, type JsonValue, jsonEquals } from "./canonical.ts";
import { normalizeCapabilitySet } from "./capability.ts";
import {
  coverageOf,
  FIXTURE_ACTIONS,
  FIXTURE_ACTOR,
  FIXTURE_ASSIGNMENT_KIND,
  FIXTURE_DECISION_KIND,
  type FixturePolicy,
} from "./fixture.ts";
import {
  acceptReportOpId,
  admitOpId,
  aggregateOpId,
  cancelOpId,
  continuationOpId,
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
  type OperationRecord,
  observationProblem,
  type RecordIndex,
  type ReplyRecord,
  type ReportOutcomeRecord,
} from "./records.ts";
import type { Refusal, RefusalReason } from "./refusal.ts";
import { validateReport } from "./report.ts";
import { gitTreeSubject } from "./subject.ts";

/**
 * One reconcile action; each carries exactly the one kernel record it writes. The binding's
 * obligations, applied in the same commit:
 * - `admit`, `aggregate`, `open-decision`: write the record;
 * - `start-attempt`: write the attempt record and launch the attempt's work;
 * - `continue`: create the conversation-owned background continuation task plus its durable-map
 *   row, which the binding presents back as the continuation record.
 */
export type Action =
  | { readonly type: "admit"; readonly record: AssignmentRecord }
  | { readonly type: "start-attempt"; readonly record: AttemptRecord }
  | { readonly type: "aggregate"; readonly record: AggregateOutcomeRecord }
  | { readonly type: "open-decision"; readonly record: DecisionRecord }
  | { readonly type: "continue"; readonly record: ContinuationRecord };

export type Operation =
  | {
      readonly type: "start";
      readonly manifest: ExecutionManifest;
      readonly observation: ObservationFacts;
    }
  | { readonly type: "run"; readonly observation: ObservationFacts }
  | { readonly type: "step" }
  | {
      readonly type: "accept-report";
      readonly attemptId: string;
      readonly report: unknown;
      readonly verifiedDigest: string;
    }
  | {
      readonly type: "reply";
      readonly decisionId: string;
      readonly action: string;
      readonly actor: string;
      readonly observation: ObservationFacts;
    }
  | { readonly type: "cancel"; readonly reason: string };

/** The recorded operation record, plus a reply's continuation (null for every other kind). */
export type Receipt = {
  readonly opId: string;
  readonly record: OperationRecord;
  readonly continuation: ContinuationRecord | null;
};

export type OperationResult =
  | { readonly kind: "replayed"; readonly receipt: Receipt }
  | { readonly kind: "refused"; readonly refusal: Refusal }
  | {
      readonly kind: "applied";
      readonly recorded: readonly KernelRecord[];
      readonly actions: readonly Action[];
      readonly receipt: Receipt | null;
    };

/** The rounds after which a non-converging reconcile is an integrity violation. */
export const MAX_ROUNDS = 8;

type InputRecord = ReportOutcomeRecord | ReplyRecord | CancellationRecord;

/** The §4 duplicate-compared payload of a caller-input record. */
export function inputPayload(record: InputRecord): JsonValue {
  switch (record.type) {
    case "report-outcome":
      return { report: record.report, verifiedDigest: record.verifiedDigest };
    case "reply":
      return { decisionId: record.decisionId, action: record.action, actor: record.actor };
    case "cancellation":
      return { reason: record.reason };
  }
}

/** Equal canonical payloads; an incoming value outside the JSON domain is simply unequal. */
export function payloadMatches(stored: JsonValue, incoming: unknown): boolean {
  const json = asJsonValue(incoming);
  return json !== null && jsonEquals(stored, json);
}

function rulesOnce(index: RecordIndex, policy: FixturePolicy): Action[] {
  const { manifest, latest } = index;
  if (manifest === null || latest === null) return [];
  if (index.cancellation !== null || index.continuations.size > 0) return [];
  const executionId = manifest.workspace.executionId;
  const current = latest.tree;
  const cov = coverageOf(index, policy);
  const actions: Action[] = [];
  for (const role of cov.roles) {
    if (role.admitted) continue;
    actions.push({
      type: "admit",
      record: {
        type: "assignment",
        opId: admitOpId(role.assignmentId),
        assignmentId: role.assignmentId,
        kind: FIXTURE_ASSIGNMENT_KIND,
        role: role.role,
        subject: gitTreeSubject(current),
        capabilitySet: normalizeCapabilitySet(policy.capabilitySet),
      },
    });
  }
  for (const role of cov.roles) {
    if (!role.admitted || role.attempts !== 0) continue;
    const attemptId = deriveAttemptId(role.assignmentId, 1);
    actions.push({
      type: "start-attempt",
      record: {
        type: "attempt",
        opId: submitOpId(attemptId),
        attemptId,
        assignmentId: role.assignmentId,
        ordinal: 1,
      },
    });
  }
  const aggregate = index.aggregatesBySubject.get(current);
  if (cov.complete && aggregate === undefined) {
    actions.push({
      type: "aggregate",
      record: {
        type: "aggregate-outcome",
        opId: aggregateOpId(executionId, current),
        subjectDigest: current,
        outcomeIds: cov.roles.flatMap((role) =>
          role.acceptedOutcomeId === null ? [] : [role.acceptedOutcomeId],
        ),
      },
    });
  }
  if (aggregate !== undefined) {
    const decisionId = deriveDecisionId({
      executionId,
      subjectDigest: current,
      decisionKind: FIXTURE_DECISION_KIND,
    });
    if (!index.decisions.has(decisionId)) {
      actions.push({
        type: "open-decision",
        record: {
          type: "decision",
          opId: openDecisionOpId(decisionId),
          decisionId,
          subjectDigest: current,
          decisionKind: FIXTURE_DECISION_KIND,
          aggregateId: aggregate.opId,
          allowedActions: [...FIXTURE_ACTIONS],
          actor: FIXTURE_ACTOR,
        },
      });
    }
  }
  for (const reply of index.replies) {
    if (index.continuations.has(reply.decisionId)) continue;
    actions.push({
      type: "continue",
      record: {
        type: "continuation",
        opId: continuationOpId(reply.decisionId),
        decisionId: reply.decisionId,
      },
    });
  }
  return actions;
}

/** The actions the fixture rules take over `records`, run to a fixpoint (round order). */
export function reconcile(records: readonly KernelRecord[], policy: FixturePolicy): Action[] {
  let working: readonly KernelRecord[] = records;
  let index = indexRecords(working);
  const all: Action[] = [];
  for (let round = 0; round < MAX_ROUNDS; round++) {
    const actions = rulesOnce(index, policy);
    if (actions.length === 0) return all;
    all.push(...actions);
    working = applyActions(working, actions);
    index = indexRecords(working);
  }
  throw new KernelInvariantError(`reconcile did not converge within ${MAX_ROUNDS} rounds`);
}

/** `records` plus each action's record, in order: the reference applier. */
export function applyActions(
  records: readonly KernelRecord[],
  actions: readonly Action[],
): KernelRecord[] {
  return [...records, ...actions.map((action) => action.record)];
}

/** The record set after a result: `recorded` plus the action records when applied, else unchanged. */
export function nextRecords(
  records: readonly KernelRecord[],
  result: OperationResult,
): readonly KernelRecord[] {
  if (result.kind !== "applied") return records;
  return applyActions([...records, ...result.recorded], result.actions);
}

/** The receipt under `opId`: its operation record, plus a reply's continuation. */
export function receiptFor(records: readonly KernelRecord[], opId: string): Receipt | null {
  const find = (id: string): OperationRecord | undefined =>
    records.find(
      (record): record is OperationRecord => record.type !== "manifest" && record.opId === id,
    );
  const record = find(opId);
  if (record === undefined) return null;
  if (record.type !== "reply") return { opId, record, continuation: null };
  const continuation = find(continuationOpId(record.decisionId));
  return {
    opId,
    record,
    continuation: continuation?.type === "continuation" ? continuation : null,
  };
}

function refused(reason: RefusalReason, detail: string): OperationResult {
  return { kind: "refused", refusal: { reason, detail } };
}

function applied(
  records: readonly KernelRecord[],
  recorded: readonly KernelRecord[],
  receiptOpId: string | null,
  policy: FixturePolicy,
): OperationResult {
  const withInputs = [...records, ...recorded];
  const actions = reconcile(withInputs, policy);
  const receipt =
    receiptOpId === null ? null : receiptFor(applyActions(withInputs, actions), receiptOpId);
  return { kind: "applied", recorded, actions, receipt };
}

/** §4 lookup: the replayed receipt, `duplicate_conflict`, or `null` when the op id is new. */
function lookup(
  records: readonly KernelRecord[],
  index: RecordIndex,
  opId: string,
  type: InputRecord["type"],
  incoming: unknown,
): OperationResult | null {
  const existing = index.byOpId.get(opId);
  if (existing === undefined) return null;
  const matches =
    (existing.type === "report-outcome" ||
      existing.type === "reply" ||
      existing.type === "cancellation") &&
    existing.type === type &&
    payloadMatches(inputPayload(existing), incoming);
  const receipt = matches ? receiptFor(records, opId) : null;
  if (receipt !== null) return { kind: "replayed", receipt };
  return refused("duplicate_conflict", `${opId} is already recorded with another payload`);
}

function trackedObservationProblem(index: RecordIndex, facts: ObservationFacts): string | null {
  const problem = observationProblem(facts);
  if (problem !== null) return problem;
  const tracked = index.observations[0];
  if (tracked !== undefined && (facts.repo !== tracked.repo || facts.ref !== tracked.ref)) {
    return `repo and ref are not the tracked ${JSON.stringify(tracked.repo)} ${JSON.stringify(tracked.ref)}`;
  }
  return null;
}

function observationRecord(
  executionId: string,
  seq: number,
  facts: ObservationFacts,
): ObservationRecord {
  return {
    type: "observation",
    opId: observeOpId(executionId, seq),
    seq,
    repo: facts.repo,
    ref: facts.ref,
    commit: facts.commit,
    tree: facts.tree,
    manifestDigest: facts.manifestDigest,
    observedAt: facts.observedAt,
  };
}

const NOT_STARTED = "the execution has no manifest (not started)";

function supersededDetail(index: RecordIndex): string {
  const [first] = index.continuations.values();
  return `the execution already consumed a decision (${first?.opId ?? "a continuation"})`;
}

/**
 * Decide one operation over the complete record set of its execution. `refused` → the binding
 * throws `KernelRefusal` inside the commit; `replayed` → it returns the receipt; `applied` → it
 * writes `recorded`, then applies `actions`. A malformed record set throws `KernelInvariantError`.
 */
export function evaluateOperation(
  records: readonly KernelRecord[],
  operation: Operation,
  policy: FixturePolicy,
): OperationResult {
  const index = indexRecords(records);
  const { manifest, latest } = index;
  if (operation.type === "start") {
    if (manifest !== null) {
      return refused("already_started", `${manifest.workspace.executionId} already has a manifest`);
    }
    const problem = manifestProblem(operation.manifest);
    if (problem !== null) return refused("invalid_input", `manifest: ${problem}`);
    const observed = observationProblem(operation.observation);
    if (observed !== null) return refused("invalid_input", `observation: ${observed}`);
    const executionId = operation.manifest.workspace.executionId;
    const first = observationRecord(executionId, 1, operation.observation);
    return applied(records, [operation.manifest, first], null, policy);
  }
  if (manifest === null || latest === null) return refused("invalid_input", NOT_STARTED);
  const executionId = manifest.workspace.executionId;
  const nextSeq = index.observations.length + 1;

  switch (operation.type) {
    case "run": {
      const problem = trackedObservationProblem(index, operation.observation);
      if (problem !== null) return refused("invalid_input", `observation: ${problem}`);
      const observation = observationRecord(executionId, nextSeq, operation.observation);
      return applied(records, [observation], null, policy);
    }
    case "step":
      return applied(records, [], null, policy);
    case "accept-report": {
      const { attemptId, report, verifiedDigest } = operation;
      if (typeof attemptId !== "string")
        return refused("invalid_input", "attemptId is not a string");
      const opId = acceptReportOpId(attemptId);
      const replay = lookup(records, index, opId, "report-outcome", { report, verifiedDigest });
      if (replay !== null) return replay;
      const attempt = index.attempts.get(attemptId);
      if (attempt === undefined) {
        return refused("invalid_input", `unknown attempt ${JSON.stringify(attemptId)}`);
      }
      const assignment = index.assignments.get(attempt.assignmentId);
      if (assignment === undefined) {
        throw new KernelInvariantError(`${attempt.opId}: attempt names a missing assignment`);
      }
      if (assignment.subject.digest !== latest.tree) {
        return refused(
          "stale_subject",
          `${attemptId} is over ${assignment.subject.digest}, not the current subject ${latest.tree}`,
        );
      }
      if (index.cancellation !== null) {
        return refused("cancelled", `the execution is cancelled (${index.cancellation.opId})`);
      }
      if (index.continuations.size > 0) return refused("superseded", supersededDetail(index));
      const validation = validateReport({ assignment, latest, report, verifiedDigest });
      if (!validation.ok) return { kind: "refused", refusal: validation.refusal };
      const outcome: ReportOutcomeRecord = {
        type: "report-outcome",
        opId,
        attemptId,
        assignmentId: attempt.assignmentId,
        subjectDigest: assignment.subject.digest,
        verifiedDigest,
        report: validation.report,
      };
      return applied(records, [outcome], opId, policy);
    }
    case "reply": {
      const { decisionId, action, actor } = operation;
      // Only the decision id names the operation; action and actor are payload, compared by the
      // lookup first (an ill-typed payload against a receipt is `duplicate_conflict`).
      if (typeof decisionId !== "string")
        return refused("invalid_input", "decisionId is not a string");
      const opId = replyOpId(decisionId);
      const replay = lookup(records, index, opId, "reply", { decisionId, action, actor });
      if (replay !== null) return replay;
      const problem = trackedObservationProblem(index, operation.observation);
      if (problem !== null) return refused("invalid_input", `observation: ${problem}`);
      const observation = observationRecord(executionId, nextSeq, operation.observation);
      const decision = index.decisions.get(decisionId);
      if (decision === undefined) {
        return refused("unknown_decision", `no decision ${JSON.stringify(decisionId)}`);
      }
      if (typeof action !== "string") return refused("invalid_input", "action is not a string");
      if (!decision.allowedActions.includes(action)) {
        return refused(
          "invalid_input",
          `action ${JSON.stringify(action)} is not allowed by ${decisionId}`,
        );
      }
      if (typeof actor !== "string") return refused("invalid_input", "actor is not a string");
      if (actor !== decision.actor) {
        return refused("invalid_input", `actor ${JSON.stringify(actor)} is not ${decision.actor}`);
      }
      if (decision.subjectDigest !== observation.tree) {
        return refused(
          "stale_subject",
          `${decisionId} is over ${decision.subjectDigest}, not the observed subject ${observation.tree}`,
        );
      }
      if (index.cancellation !== null) {
        return refused("cancelled", `the execution is cancelled (${index.cancellation.opId})`);
      }
      if (index.continuations.size > 0) return refused("superseded", supersededDetail(index));
      const reply: ReplyRecord = { type: "reply", opId, decisionId, action, actor };
      return applied(records, [observation, reply], opId, policy);
    }
    case "cancel": {
      const { reason } = operation;
      const opId = cancelOpId(executionId);
      const replay = lookup(records, index, opId, "cancellation", { reason });
      if (replay !== null) return replay;
      if (typeof reason !== "string" || reason === "" || !isWellFormedText(reason)) {
        return refused("invalid_input", "reason is not a non-empty well-formed string");
      }
      const cancellation: CancellationRecord = { type: "cancellation", opId, reason };
      return applied(records, [cancellation], opId, policy);
    }
    default:
      return refused("invalid_input", "unknown operation type");
  }
}
