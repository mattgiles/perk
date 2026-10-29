// Wait-reason derivation (docs/design/pi-durable-v2-foundations.md §10 step 8): why a quiescent
// execution is not progressing, derived from the presented records plus the Harness's live task
// diagnostics (`inspect()`). Never stored; the kernel only names the vocabulary.
//
// Invariants:
// - A pure function of its arguments. Whether work is still runnable (`wake().active`) is the
//   caller's question: a reason is only meaningful once nothing can run.
// - Precedence is `DERIVED_WAIT_REASONS` order: terminal states first, then a human wait, then the
//   live diagnostics from most to least severe, then incomplete coverage.
// - Only a decision over the CURRENT subject is a human wait; decisions over earlier trees are
//   stale by derivation.

import type { TaskInspection } from "@earendil-works/pi-durable";
import { coverageOf, FIXTURE_DECISION_KIND, type FixturePolicy } from "../kernel/fixture.ts";
import { deriveDecisionId } from "../kernel/identity.ts";
import { indexRecords, type KernelRecord } from "../kernel/records.ts";
import type { WaitReason } from "../kernel/waitReason.ts";

/** The wait reasons this derivation can produce, in precedence order. */
export const DERIVED_WAIT_REASONS = [
  "completed",
  "cancelled",
  "pending_decision",
  "blocked",
  "parked",
  "sleeping",
  "assignment_incomplete",
] as const satisfies readonly WaitReason[];

/**
 * The vocabulary's remaining reasons: no fixture state produces them yet. The native assignment
 * derives `repair_required`.
 */
export const UNDERIVED_WAIT_REASONS = [
  "unmet_prerequisite",
  "repair_required",
] as const satisfies readonly WaitReason[];

/** One live task's diagnostic state, as `inspect()` reports it. */
export type LiveTaskState = TaskInspection["state"];

/**
 * The wait reason over `records` (validated by `indexRecords`) and the live task states, or `null`
 * when none applies — not started, or every assignment covered with no decision, sleep or block to
 * explain the wait.
 */
export function deriveWaitReason(
  records: readonly KernelRecord[],
  policy: FixturePolicy,
  live: readonly LiveTaskState[],
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
  if (!coverageOf(index, policy).complete) return "assignment_incomplete";
  return null;
}
