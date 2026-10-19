// The shared approval-gate invariant behind the three approval→save orchestrations
// (`gistApprovalSave`/`planApprovalSave`/`objectiveApprovalSave` — contracts §8.23/§8.41):
// the gate transition and its structural type unify HERE; draft resolution, save unions, and
// result field names stay feature-owned. Pi-free and storage-free (the pi/v1 adapters build the
// gate slice over ToolGating). The no-save siblings — `reviewPlanDraft`'s implement-here arm and
// `pi/v1/planReview.ts`'s `implementHereExit` — keep their own gate handling on purpose (the
// sanctioned §8.23 no-save exits, not save flows).
//
// `gateExited` is earned, never assumed: it is true only when the one release this seam makes
// reports an applied read-write transition (contracts.md §8.40). A held release (the runner
// restriction floor, a failed persist/install) leaves it false — and the save outcome always
// returns: the slice never throws, and reporting the held release is the adapter's best-effort job.

import type { GateTransition } from "../../substrate/toolPolicy.ts";

/** The structural gate slice the approval→save flows release (pi/v1 adapters build it over ToolGating). */
export interface ApprovalGate {
  isActive(): boolean;
  /** Release the gate; the transition result says what is actually in force. Never throws. */
  exit(): GateTransition;
}

/**
 * The approval-gate invariant (contracts §8.23/§8.41 — the D1a pattern): snapshot the gate
 * BEFORE the save; exit ONLY after a successful save while read-only; report gateExited — true
 * only for an applied read-write release. Success is the fixed shared discriminant
 * (status === "saved") — not caller policy. A failed save leaves the gate untouched; a thrown
 * save propagates with the gate untouched.
 */
export async function saveThroughApprovalGate<T extends { status: "saved" } | { status: "failed" }>(
  gate: ApprovalGate,
  save: () => Promise<T>,
): Promise<{ outcome: T; gateExited: boolean }> {
  const wasReadOnly = gate.isActive();
  const outcome = await save();
  if (outcome.status !== "saved") return { outcome, gateExited: false };
  if (!wasReadOnly) return { outcome, gateExited: false };
  const release = gate.exit();
  return { outcome, gateExited: release.status === "applied" && release.access === "read-write" };
}
