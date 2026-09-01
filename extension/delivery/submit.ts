// The change-publication feature (the submit half of the delivery pair), Pi-free.
//
// One entry point — `submitChange` — owns the ordering and failure semantics of publishing the
// active plan's change: external publish first, session-side updates ONLY on verified success
// (the implementation pointer, the reset-on-clean), then the bounded conflict follow-up
// decision. The composable internals (`publishVerified`, `decideConflictFollowUp`) are exported
// for the sibling address feature, whose conflict-decision timing is deliberately DIFFERENT
// (structural, not stylistic): `/submit` decides immediately after publish; `finalizeAddress`
// decides only after full corroborated resolve success — a resolve failure never burns an
// attempt.
//
// Ports are action-specific (never a DeliveryBackend/Git facade): `PublishChange` has exactly
// ONE production adapter — the `perk pr submit --json` cold-door composition in
// `pi/v1/delivery/submit.ts`, which also owns the `operation.notes` warning reports at
// publish-success time. Refusals (`planning_session`, `bad_input`) are adapter shapes — they
// never enter the outcome union.

/** The published-change facts — the structured `details` surface doubles as branch-safe
 * persisted state. `issue` is the opaque string id the Python boundary sends (contracts §8.21). */
export interface PublishedChange {
  pr: { number: number; url: string; is_draft: boolean; existed: boolean };
  branch?: string;
  issue?: string;
  plan_embedded?: boolean;
  /** The target branch the PR merges into (the conflict-resolver rebases onto it). */
  base?: string;
  /** Tri-state mergeability from the Python `git merge-tree` probe: true/false/null/absent. */
  mergeable?: boolean | null;
  /** The conflicted paths when `mergeable === false`; `[]` otherwise (advisory). */
  conflicts?: string[];
  /** `"stacked"` when the submit routed through the delivery publish operation (§8.47). */
  delivery?: string;
  /** The native-stack facts of a stacked submit (absent for the bottom layer). */
  stack?: { number: number; size: number; position: number };
  /** Lenient summary of an automatic suffix synchronization. */
  operation?: {
    kind: string;
    operation_id: string | null;
    no_op: boolean;
    affected_count: number;
    notes: string[];
  };
}

/** One external publish attempt: the verified facts, or the adapter's soft failure. */
export type PublishAttempt =
  | { ok: true; change: PublishedChange }
  | { ok: false; message: string; errorType: string };

/** The publish port — ONE production adapter (`createChangePublisher`). */
export type PublishChange = (opts: { runId: string | null }) => Promise<PublishAttempt>;

/**
 * The bounded conflict-attempt capability. `write` returns the persistence result (strict
 * read-back / equal-value short-circuit true) — callers decide whether the boolean gates.
 */
export interface ConflictAttempts {
  read(): number;
  write(next: number): boolean;
}

/**
 * The bounded conflict-resolution re-drive cap: drive the resolver at most this many times.
 * The counter behind it (`conflict_resolution_attempts`) is SHARED with `/objective-sync`'s
 * retained-continuation conflict drive (doors/objectiveStack.ts) — submit- and sync-episode
 * attempts deliberately share one bound, reset on any clean completion of either surface.
 */
export const CONFLICT_RESOLUTION_ATTEMPT_CAP = 2;

/** The bounded conflict follow-up decision (surface translation stays adapter-side). */
export type ConflictFollowUp =
  | { kind: "none" }
  | { kind: "drive"; base: string; attempt: number; cap: number }
  | { kind: "exhausted"; base: string; attempts: number };

export interface PublishDeps {
  publish: PublishChange;
  /** The adapter's DIRECT run-id read, invoked at publish time — AFTER any pre-effect refusal
   * (the finalize empty-batch check) but BEFORE the external call, so a throwing branch read
   * still fails before publication (today's parity); `""` ⇒ `null` is the adapter's job. */
  readRunId: () => string | null;
  /** CONTRACT: never throws; owns its own failure reporting (production:
   * `captureSessionPointer` — best-effort + non-fatal, a successful publish must stand).
   * Receives the run id `readRunId` returned for this publish. */
  recordImplementationPointer: (runId: string) => void;
  attempts: ConflictAttempts;
}

export type SubmitChangeOutcome =
  | { kind: "publish_failed"; message: string; errorType: string }
  | { kind: "published"; change: PublishedChange; conflict: ConflictFollowUp };

/**
 * Publish the change, then apply the verified-success session updates. A failed publish returns
 * as-is with NO session-side activity (no pointer, no counter read/write). On success: the
 * implementation pointer is recorded iff the run id exists (no catch — the capability contract
 * is never-throws), and the shared conflict counter resets on a clean (or undetermined) submit
 * so a later independent conflict starts fresh. The reset's persistence result is deliberately
 * unchecked — today's posture; the seam warns loudly on a read-back miss.
 */
export async function publishVerified(deps: PublishDeps): Promise<PublishAttempt> {
  const runId = deps.readRunId();
  const attempt = await deps.publish({ runId });
  if (!attempt.ok) return attempt;
  if (runId !== null) deps.recordImplementationPointer(runId);
  if (attempt.change.mergeable !== false && deps.attempts.read() !== 0) {
    deps.attempts.write(0);
  }
  return attempt;
}

/**
 * The bounded conflict follow-up decision for a published change: mergeable (or undetermined) ⇒
 * `none`; definitively unmergeable under the cap ⇒ `drive` (the increment is written first —
 * its boolean is deliberately NOT gating: today's submit surface proceeds on an unverified
 * increment with the seam's loud warning as the mitigation; the sync path's
 * withhold-and-release stays the stricter posture, both pinned); at the cap ⇒ `exhausted`
 * (no write).
 */
export function decideConflictFollowUp(
  change: PublishedChange,
  attempts: ConflictAttempts,
): ConflictFollowUp {
  if (change.mergeable !== false) return { kind: "none" };
  const base = change.base ?? "";
  const n = attempts.read();
  if (n >= CONFLICT_RESOLUTION_ATTEMPT_CAP) return { kind: "exhausted", base, attempts: n };
  attempts.write(n + 1);
  return { kind: "drive", base, attempt: n + 1, cap: CONFLICT_RESOLUTION_ATTEMPT_CAP };
}

/**
 * The one standalone-submit operation: external publish → verified-success session updates →
 * the bounded conflict decision, taken immediately after publish (the standalone surface's
 * structural timing; the address finalizer defers it until corroborated resolve success).
 */
export async function submitChange(deps: PublishDeps): Promise<SubmitChangeOutcome> {
  const attempt = await publishVerified(deps);
  if (!attempt.ok) {
    return { kind: "publish_failed", message: attempt.message, errorType: attempt.errorType };
  }
  return {
    kind: "published",
    change: attempt.change,
    conflict: decideConflictFollowUp(attempt.change, deps.attempts),
  };
}
