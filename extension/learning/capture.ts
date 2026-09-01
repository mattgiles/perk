// The learn-capture feature operation: the capture/skip state policy over two narrow ports.
// With a summary the learn cycle ends in a capture (a `perk:learn` issue via the backend port);
// without one it ends in a canonically recorded skip (contracts.md §8.36 — the plan-header
// `learn_state: skipped` stamp, never a TS-only marker-clear). The pending-learn marker clears
// ONLY on a verified backend success (both arms); the failure arm never clears — the marker is
// the retry signal, and the cycle is never silently closed on uncertainty.
//
// Pi-free by construction: the production ports (the `perk learn capture/skip` cold doors, the
// substrate cache markers) are composed by the `pi/v1/learning/` adapter; tests drive fakes.

/**
 * The closed CAPTURED-classification set persisted on a `perk:learn` header (contracts.md §8.35) —
 * the reconciliation DECISION set minus `SKIP` (a skip creates no issue). Mirrors
 * `plan.CapturedDecision` (the Python SSOT); the `learn` tool's JSON-schema enum and the analyst
 * report schema's decision enum are both derived from this constant.
 */
export const CAPTURED_DECISIONS = [
  "CAPTURE_LEARN",
  "SHOULD_BE_CODE",
  "UPDATE_EXISTING_DOC",
  "NEW_DOC",
  "STALE_DOC",
] as const;

export type CapturedDecision = (typeof CAPTURED_DECISIONS)[number];

/** Boundary narrowing for the tool-schema enum (out-of-enum strings stay unrepresentable past it). */
export function isCapturedDecision(value: string): value is CapturedDecision {
  return (CAPTURED_DECISIONS as readonly string[]).includes(value);
}

/** The captured learn issue's identity; `id` is the opaque string issue id (§8.21). */
export interface LearnIssue {
  id: string;
  url: string;
  existed: boolean;
}

/** Cross-plane persistence port (production: the perk-learn cold doors). */
export interface LearnBackend {
  capture(input: {
    body: string;
    decision?: CapturedDecision;
    target?: string;
  }): Promise<
    { ok: true; issue: LearnIssue | null } | { ok: false; message: string; errorType: string }
  >;
  skip(): Promise<
    { ok: true; learnState: string | null } | { ok: false; message: string; errorType: string }
  >;
}

/** The pending-learn semaphore role (production: substrate/cache markers, adapter-composed). */
export interface PendingLearnMarker {
  clear(): { wasPending: boolean };
}

export type FinishLearnOutcome =
  | { kind: "skip_recorded"; wasPending: boolean; alreadyCaptured: boolean }
  | { kind: "captured"; wasPending: boolean; issue: LearnIssue | null }
  | { kind: "backend_failed"; message: string; errorType: string };

/**
 * Finish the learn cycle. A blank (or absent) summary routes to the skip arm — the deliberate
 * skip carries no classification, so `decision`/`target` are intentionally ignored there; a
 * non-blank summary routes to the capture arm. Both arms clear the marker ONLY on a verified
 * backend success (the in-session mirror is idempotent — the worker already cleared it on
 * disk); the failure arm returns without touching it. A `null` issue on the captured arm is the
 * undecodable-payload case — still captured: the success envelope is authoritative.
 */
export async function finishLearn(
  input: { summary?: string; decision?: CapturedDecision; target?: string },
  deps: { backend: LearnBackend; marker: PendingLearnMarker },
): Promise<FinishLearnOutcome> {
  const trimmed = (input.summary ?? "").trim();

  if (trimmed.length === 0) {
    const r = await deps.backend.skip();
    if (!r.ok) return { kind: "backend_failed", message: r.message, errorType: r.errorType };
    const { wasPending } = deps.marker.clear();
    return { kind: "skip_recorded", wasPending, alreadyCaptured: r.learnState === "captured" };
  }

  const r = await deps.backend.capture({
    body: trimmed,
    ...(input.decision !== undefined ? { decision: input.decision } : {}),
    ...(input.target !== undefined ? { target: input.target } : {}),
  });
  if (!r.ok) return { kind: "backend_failed", message: r.message, errorType: r.errorType };
  const { wasPending } = deps.marker.clear();
  return { kind: "captured", wasPending, issue: r.issue };
}
