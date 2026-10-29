// Wait-reason derivation (docs/design/pi-durable-v2-foundations.md §10 step 8): why a quiescent
// execution is not progressing, derived from the presented records, the Harness's live task
// diagnostics (`inspect()`) and the launched attempt tasks' typed endings (`getTask`). Never
// stored; the kernel only names the vocabulary.
//
// Invariants:
// - A pure function of its arguments. Whether work is still runnable (`wake().active`) is the
//   caller's question: a reason is only meaningful once nothing can run.
// - Precedence is `DERIVED_WAIT_REASONS` order: terminal states first, then a human wait, then the
//   live diagnostics from most to least severe, then an attempt needing repair, then incomplete
//   coverage.
// - Only a decision over the CURRENT subject is a human wait; decisions over earlier trees are
//   stale by derivation.
// - `repair_required` is derived, never recorded: a current-subject role with no accepted outcome
//   whose attempt ended `repair`. The ending explains the wait and authorizes nothing (P6).

import type { TaskInspection } from "@earendil-works/pi-durable";
import { coverageOf, FIXTURE_DECISION_KIND, type FixturePolicy } from "../kernel/fixture.ts";
import { deriveDecisionId } from "../kernel/identity.ts";
import { indexRecords, type KernelRecord, type RecordIndex } from "../kernel/records.ts";
import type { WaitReason } from "../kernel/waitReason.ts";
import type { AttemptEnding } from "./ending.ts";

/** The wait reasons this derivation can produce, in precedence order. */
export const DERIVED_WAIT_REASONS = [
  "completed",
  "cancelled",
  "pending_decision",
  "blocked",
  "parked",
  "sleeping",
  "repair_required",
  "assignment_incomplete",
] as const satisfies readonly WaitReason[];

/** The vocabulary's remaining reason: no fixture state produces it. */
export const UNDERIVED_WAIT_REASONS = [
  "unmet_prerequisite",
] as const satisfies readonly WaitReason[];

/** One live task's diagnostic state, as `inspect()` reports it. */
export type LiveTaskState = TaskInspection["state"];

/** Whether some current-subject role lacks an accepted outcome and one of its attempts ended `repair`. */
function repairRequired(
  index: RecordIndex,
  policy: FixturePolicy,
  endings: ReadonlyMap<string, AttemptEnding>,
): boolean {
  return coverageOf(index, policy).roles.some(
    (role) =>
      role.acceptedOutcomeId === null &&
      (index.attemptsByAssignment.get(role.assignmentId) ?? []).some(
        (attempt) => endings.get(attempt.attemptId)?.end === "repair",
      ),
  );
}

/**
 * The wait reason over `records` (validated by `indexRecords`), the live task states and the
 * attempt endings by attempt id, or `null` when none applies — not started, or every assignment
 * covered with no decision, sleep or block to explain the wait.
 */
export function deriveWaitReason(
  records: readonly KernelRecord[],
  policy: FixturePolicy,
  live: readonly LiveTaskState[],
  endings: ReadonlyMap<string, AttemptEnding>,
): WaitReason | null {
  const index = indexRecords(records);
  if (index.continuations.size > 0) return "completed";
  if (index.cancellation !== null) return "cancelled";
  const { manifest, latest } = index;
  if (manifest === null || latest === null) return null;
  const decisionId = deriveDecisionId({
    executionId: manifest.workspace.executionId,
    subjectDigest: latest.tree,
    decisionKind: FIXTURE_DECISION_KIND,
  });
  if (index.decisions.has(decisionId)) return "pending_decision";
  if (live.some((state) => state.kind === "blocked" && state.reason !== "restart_limit")) {
    return "blocked";
  }
  if (live.some((state) => state.kind === "blocked" && state.reason === "restart_limit")) {
    return "parked";
  }
  if (live.some((state) => state.kind === "sleeping")) return "sleeping";
  if (repairRequired(index, policy, endings)) return "repair_required";
  if (!coverageOf(index, policy).complete) return "assignment_incomplete";
  return null;
}
