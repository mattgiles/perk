// The objective planning feature: the roadmap-node → plan-generation policy — the bounded
// node-transition operation (with the completion-audit gate and the warm node-claim carrier
// maintenance). The reconcile/add-node writes carry no feature policy beyond their decoders,
// so they live adapter-tier in pi/v1/objectivePlanning.ts (direct cold-door calls — no port).
//
// The completion-audit gate is a property of the MODEL-FACING boundary only — NOT an invariant
// on the node-`done` state: the canonical `perk objective node --status done` (human/CI cold
// CLI) has no audit gate, and the auto-on-merge node-done deliberately sets `done` without one.
// Both are intentional non-audited paths; the structural refusal protects the model's path
// only. The "are we done?" judgment text lives in the perk-objective-plan skill.
//
// Decode-once-at-the-edge: inputs arrive TYPED (the pi/v1 decoders own the tool-boundary
// shape), so the ops re-validate nothing. Canonical mutations stay in the Python plane — the
// backends delegate; the objective's canonical state is the issue (re-read on demand), and the
// only session state these ops maintain is the warm `objective_node_claim` carrier, THROUGH the
// session seam.

import type { WorkflowChangeResult, WorkflowSession } from "../../session/workflowSession.ts";

/** The valid node statuses (mirrors the Python `objective.NodeStatus` StrEnum). */
export const NODE_STATUSES = [
  "pending",
  "planning",
  "in_progress",
  "done",
  "blocked",
  "skipped",
] as const;
export type NodeStatus = (typeof NODE_STATUSES)[number];

/** The minimum trimmed length of a non-trivial completion `audit` (the pinnable predicate). */
export const MIN_AUDIT_LENGTH = 40;

/** A non-trivial audit iff it is a string whose value after `.trim()` is ≥ MIN_AUDIT_LENGTH. */
export function isNonTrivialAudit(audit: unknown): boolean {
  return typeof audit === "string" && audit.trim().length >= MIN_AUDIT_LENGTH;
}

/** The typed `objective_node` input (`objective` is the opaque §8.21 string id). */
export interface ObjectiveNodeInput {
  objective: string;
  node: string;
  status?: NodeStatus;
  pr?: string;
  description?: string;
  audit?: string;
}

/** The narrow exterior port the node transition writes through (the cold door in pi/v1). */
export interface ObjectiveNodeBackend {
  transition(req: {
    objective: string;
    node: string;
    status?: NodeStatus;
    pr?: string;
    description?: string;
  }): Promise<
    | { status: "ok"; commentUpdated: boolean }
    | { status: "failed"; message: string; errorType: string }
  >;
}

/**
 * The transition outcome. `claimChange` is the session seam's own `WorkflowChangeResult`
 * VERBATIM (`null` = not attempted: a pr/description-only call leaves the carrier untouched);
 * the adapter's rendering ignores it (the seam's report() stays the loudness channel — a failed
 * claim append never fails the tool result).
 */
export type TransitionObjectiveNodeOutcome =
  | { status: "ok"; commentUpdated: boolean; claimChange: WorkflowChangeResult | null }
  | { status: "failed"; message: string; errorType: string };

/**
 * The bounded `objective_node` transition: the completion-audit gate (`status:"done"` requires
 * a non-trivial `audit` — model-path-only) → the no-change refusal (neither status nor pr nor
 * description) → `backend.transition` → on success, maintain the warm node-link carrier
 * THROUGH THE SEAM: `planning` records the claim (the exact moment the warm factory learns the
 * node id; an idempotent re-claim short-circuits `unchanged`); any other explicit status clears
 * it (the seam's both-field match — an unrelated claim is never clobbered); no status change
 * leaves it untouched. Never throws.
 */
export async function transitionObjectiveNode(
  input: ObjectiveNodeInput,
  deps: { backend: ObjectiveNodeBackend; session: WorkflowSession },
): Promise<TransitionObjectiveNodeOutcome> {
  // The completion-audit gate (model-path-only): `status:"done"` requires a non-trivial `audit`.
  if (input.status === "done" && !isNonTrivialAudit(input.audit)) {
    return {
      status: "failed",
      message:
        `setting a node to "done" requires a completion audit (a requirement→evidence mapping of ` +
        `at least ${MIN_AUDIT_LENGTH} characters) — confirm the work actually landed first.`,
      errorType: "audit_required",
    };
  }
  if (input.status === undefined && input.pr === undefined && input.description === undefined) {
    return {
      status: "failed",
      message: "objective_node needs a `status`, a `pr`, or a `description` to change",
      errorType: "bad_input",
    };
  }

  const transitioned = await deps.backend.transition({
    objective: input.objective,
    node: input.node,
    ...(input.status !== undefined ? { status: input.status } : {}),
    ...(input.pr !== undefined ? { pr: input.pr } : {}),
    ...(input.description !== undefined ? { description: input.description } : {}),
  });
  if (transitioned.status === "failed") return transitioned;

  // Maintain the warm node-link carrier off the successful transition (best-effort: a failed
  // append is loud via the seam's report() but never fails the tool result).
  let claimChange: WorkflowChangeResult | null = null;
  if (input.status !== undefined) {
    const claim = { objective: input.objective, node: input.node };
    claimChange =
      input.status === "planning"
        ? deps.session.apply({ kind: "record-node-claim", claim })
        : deps.session.apply({ kind: "clear-node-claim", claim });
  }
  return { status: "ok", commentUpdated: transitioned.commentUpdated, claimChange };
}
