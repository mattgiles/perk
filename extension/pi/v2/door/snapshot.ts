// The status snapshot (docs/design/pi-durable-v2-foundations.md §11, contracts.md §8.77): the derived
// view a door envelope carries, projected from the retained records plus the live diagnostics a
// host call collected. Never stored.
//
// Invariants:
// - A pure function of its input and the wall clock `now`, which only ages the latest observation.
// - Every list is in record-index order (by op id), never insertion order, and every object is
//   built field by field, so equal inputs serialize to equal JSON.
// - Every assignment record is listed, each flagged `current` against the latest observation's
//   tree, so earlier rounds stay visible; only the current subject's decision is shown, and none
//   once the execution is cancelled or continued.
// - `waitReason` is non-null exactly for `waiting`; `completed` and `cancelled` are states of their
//   own.

import type { AttemptEnding } from "../durable/ending.ts";
import type { LiveTaskState } from "../durable/waitReason.ts";
import { FIXTURE_DECISION_KIND } from "../kernel/fixture.ts";
import { deriveDecisionId } from "../kernel/identity.ts";
import { indexRecords, type KernelRecord, type RecordIndex } from "../kernel/records.ts";
import type { WaitReason } from "../kernel/waitReason.ts";

/** What a snapshot is projected from: one host call's records and live diagnostics. */
export type SnapshotInput = {
  readonly records: readonly KernelRecord[];
  readonly live: readonly LiveTaskState[];
  /** Whether work was runnable (`wake().active`). */
  readonly runnable: boolean;
  /** The launched attempt tasks' typed endings, by attempt id. */
  readonly endings: ReadonlyMap<string, AttemptEnding>;
  /** `null` only while work is runnable. */
  readonly waitReason: WaitReason | null;
};

export type ObservationView = {
  readonly seq: number;
  readonly repo: string;
  readonly ref: string;
  readonly commit: string;
  readonly tree: string;
  readonly manifestDigest: string;
  readonly observedAt: number;
  readonly ageMs: number;
};

export type AttemptView = {
  readonly attemptId: string;
  readonly ordinal: number;
  readonly outcomeId: string | null;
  readonly ending: AttemptEnding | null;
};

export type AssignmentView = {
  readonly assignmentId: string;
  readonly role: string;
  readonly subjectDigest: string;
  /** Whether the assignment is over the latest observation's tree. */
  readonly current: boolean;
  readonly acceptedOutcomeId: string | null;
  readonly attempts: readonly AttemptView[];
};

export type DecisionView = {
  readonly decisionId: string;
  readonly subjectDigest: string;
  readonly allowedActions: readonly string[];
  readonly actor: string;
};

export type Diagnostics = {
  readonly runnable: boolean;
  /** Live tasks blocked for any reason but the restart limit. */
  readonly blocked: number;
  /** Live tasks parked by the restart limit. */
  readonly parked: number;
  readonly sleeping: number;
};

/** The wait reasons a `waiting` snapshot can carry: every reason but the two terminal states. */
export type WaitingReason = Exclude<WaitReason, "completed" | "cancelled">;

export type ViewSnapshot = {
  readonly state: "running" | "waiting" | "completed" | "cancelled";
  readonly waitReason: WaitingReason | null;
  readonly observation: ObservationView | null;
  readonly assignments: readonly AssignmentView[];
  readonly decision: DecisionView | null;
  readonly cancellation: { readonly reason: string } | null;
  readonly diagnostics: Diagnostics;
};

/** The snapshot of an outcome that saw no consistent view. */
export type MarkerSnapshot = { readonly state: "incompatible" | "uncertain" };

export type Snapshot = ViewSnapshot | MarkerSnapshot;

function endingView(ending: AttemptEnding): AttemptEnding {
  switch (ending.end) {
    case "accepted":
      return { end: "accepted", outcomeId: ending.outcomeId };
    case "incomplete":
      return {
        end: "incomplete",
        submission: ending.submission,
        reason: ending.reason,
        refusal: ending.refusal,
      };
    case "repair":
      return { end: "repair", cause: ending.cause, detail: ending.detail };
  }
}

function stateOf(waitReason: WaitReason | null): Pick<ViewSnapshot, "state" | "waitReason"> {
  if (waitReason === null) return { state: "running", waitReason: null };
  if (waitReason === "completed" || waitReason === "cancelled") {
    return { state: waitReason, waitReason: null };
  }
  return { state: "waiting", waitReason };
}

function assignmentViews(
  index: RecordIndex,
  endings: ReadonlyMap<string, AttemptEnding>,
): AssignmentView[] {
  const current = index.latest?.tree ?? null;
  return [...index.assignments.values()].map((assignment): AssignmentView => {
    const attempts = (index.attemptsByAssignment.get(assignment.assignmentId) ?? []).map(
      (attempt): AttemptView => {
        const ending = endings.get(attempt.attemptId);
        return {
          attemptId: attempt.attemptId,
          ordinal: attempt.ordinal,
          outcomeId: index.outcomesByAttempt.get(attempt.attemptId)?.opId ?? null,
          ending: ending === undefined ? null : endingView(ending),
        };
      },
    );
    return {
      assignmentId: assignment.assignmentId,
      role: assignment.role,
      subjectDigest: assignment.subject.digest,
      current: assignment.subject.digest === current,
      acceptedOutcomeId: attempts.find((attempt) => attempt.outcomeId !== null)?.outcomeId ?? null,
      attempts,
    };
  });
}

function decisionView(index: RecordIndex): DecisionView | null {
  if (index.cancellation !== null || index.continuations.size > 0) return null;
  const { manifest, latest } = index;
  if (manifest === null || latest === null) return null;
  const decisionId = deriveDecisionId({
    executionId: manifest.workspace.executionId,
    subjectDigest: latest.tree,
    decisionKind: FIXTURE_DECISION_KIND,
  });
  const decision = index.decisions.get(decisionId);
  if (decision === undefined) return null;
  return {
    decisionId: decision.decisionId,
    subjectDigest: decision.subjectDigest,
    allowedActions: [...decision.allowedActions],
    actor: decision.actor,
  };
}

function diagnostics(input: SnapshotInput): Diagnostics {
  let blocked = 0;
  let parked = 0;
  let sleeping = 0;
  for (const state of input.live) {
    if (state.kind === "blocked") {
      if (state.reason === "restart_limit") parked++;
      else blocked++;
    } else if (state.kind === "sleeping") {
      sleeping++;
    }
  }
  return { runnable: input.runnable, blocked, parked, sleeping };
}

/** The status snapshot of `input` at wall-clock `now` (ms); pure. */
export function statusSnapshot(input: SnapshotInput, now: number): ViewSnapshot {
  const index = indexRecords(input.records);
  const latest = index.latest;
  return {
    ...stateOf(input.waitReason),
    observation:
      latest === null
        ? null
        : {
            seq: latest.seq,
            repo: latest.repo,
            ref: latest.ref,
            commit: latest.commit,
            tree: latest.tree,
            manifestDigest: latest.manifestDigest,
            observedAt: latest.observedAt,
            ageMs: Math.max(0, now - latest.observedAt),
          },
    assignments: assignmentViews(index, input.endings),
    decision: decisionView(index),
    cancellation: index.cancellation === null ? null : { reason: index.cancellation.reason },
    diagnostics: diagnostics(input),
  };
}
