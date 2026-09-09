// The current-review record — the ONE in-memory record of the review a Perk activation is showing
// a human right now (a Plannotator browser door or the blocking `plan_review` arm). Pi-free and
// storage-free: nothing is persisted, so a crash loses the browser decision and the human re-runs
// the door (contracts.md §8.23).
//
// The record is a FENCE, not a copy of the review: the record OBJECT is the identity (a newer
// open supersedes the previous record; a decision for a superseded record is ignored loudly), it
// carries the artifact baseline the approve gate re-reads against (`source`), and the
// save-destination snapshot taken at open. Every door/arm keeps its displayed draft in a local
// and passes it to the completion seam itself — `source.raw` is the only content the fence needs.

/**
 * The three readings that select WHERE a save goes. Absence is a VALUE — a repo without remotes
 * or without an `[issues]` table reviews normally; only a failed git reading (`remotes: null`)
 * is UNREADABLE, and the approve gate refuses on it at either end of the review.
 */
export interface ReviewDestination {
  /** Main-checkout committed `[issues] backend`; null = key/table/file absent (or malformed → absent, loudly). */
  backend: string | null;
  /** Main-checkout committed `[issues] team`; same absence rule. */
  team: string | null;
  /** Sorted `git config --get-regexp ^remote\..*\.url$` lines; [] = no remotes; null = UNREADABLE. */
  remotes: readonly string[] | null;
}

/**
 * The record handed back by `openCurrentReview`. Its identity is the object reference — decisions
 * are checked against the record the caller holds, never against Plannotator's `reviewId`.
 */
export interface CurrentReview {
  /**
   * The artifact re-read baseline; null when the subject's save seam owns the compare (refinement
   * compares the reviewed (draft, context) pair itself) or there is no artifact (a param-tier plan).
   */
  readonly source: { name: string; raw: string } | null;
  /** The save-destination snapshot taken at open. */
  readonly destination: ReviewDestination;
}

export interface CurrentReviewState {
  current: CurrentReview | null;
  /** Whether `current` already attempted its save — the per-activation dedupe. */
  saved: boolean;
}

export type StaleReason =
  | "superseded"
  | "already-saved"
  | "source-changed"
  | "destination-unreadable"
  | "destination-changed";

export type ApproveGate = { ok: true } | { ok: false; reason: StaleReason };

export function createCurrentReviewState(): CurrentReviewState {
  return { current: null, saved: false };
}

/** Open a review: a fresh record SUPERSEDES the previous current review and resets `saved`. */
export function openCurrentReview(state: CurrentReviewState, input: CurrentReview): CurrentReview {
  const review: CurrentReview = { source: input.source, destination: input.destination };
  state.current = review;
  state.saved = false;
  return review;
}

export function isCurrentReview(state: CurrentReviewState, review: CurrentReview): boolean {
  return state.current === review;
}

/**
 * The approve-time gate. Order: `superseded` (defensive — callers check `isCurrentReview` first) →
 * `already-saved` → `source-changed` (only when the record carries a source; a `null` current
 * reading — artifact absent or invalid — never equals) → `destination-unreadable` (either end) →
 * `destination-changed`. On `ok` the record is marked saved BEFORE returning, so a repeated
 * decision for the same record refuses `already-saved` even while the save is still running. The
 * check-to-save window is the accepted residual.
 */
export function gateApprovedSave(
  state: CurrentReviewState,
  review: CurrentReview,
  now: { source: string | null; destination: ReviewDestination },
): ApproveGate {
  if (!isCurrentReview(state, review)) return { ok: false, reason: "superseded" };
  if (state.saved) return { ok: false, reason: "already-saved" };
  if (review.source !== null && now.source !== review.source.raw) {
    return { ok: false, reason: "source-changed" };
  }
  if (review.destination.remotes === null || now.destination.remotes === null) {
    return { ok: false, reason: "destination-unreadable" };
  }
  if (!sameDestination(review.destination, now.destination)) {
    return { ok: false, reason: "destination-changed" };
  }
  state.saved = true;
  return { ok: true };
}

/** Clears `current` only if it is `review` — a superseding open is never undone by the older close. */
export function closeCurrentReview(state: CurrentReviewState, review: CurrentReview): void {
  if (isCurrentReview(state, review)) state.current = null;
}

/** Field-wise equality; `null === null` is equal because absence is a value; remote order is irrelevant. */
function sameDestination(a: ReviewDestination, b: ReviewDestination): boolean {
  if (a.backend !== b.backend || a.team !== b.team) return false;
  const left = [...(a.remotes ?? [])].sort();
  const right = [...(b.remotes ?? [])].sort();
  return left.length === right.length && left.every((url, i) => url === right[i]);
}
