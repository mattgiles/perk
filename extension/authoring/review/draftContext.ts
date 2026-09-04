// The door-primed draft-review context + per-activation state for the draft-review doors
// (/plan-review-browser + /objective-review-browser). THE TRUST POSTURE (the difference from
// the PR pair): the wave's inputs — the draft under review, its type, and the optional
// human-supplied custom-angle definition — are REGISTRATION-OWNED STATE primed by the door
// (the `primeAnnotationSurface` discipline), never tool params: one `DraftReviewWaveState`
// instance per activation, created in `index.ts` and threaded to the two browser doors and the
// `pi/v1/draftReviewWaveTools.ts` tool pair. `start_draft_review_wave` takes ONLY `{angles}`
// and refuses unprimed, so the model can never substitute a transcript/arbitrary draft or
// invent a custom lane: reviewed bytes == browsed bytes == wave bytes by construction. A prime
// supersedes everything (context AND pending ref); a clear drops only the primed inputs — a
// launched wave stays collectable.

import type { ReportWaveRef } from "../../waves/reportWave.ts";

/** The door-primed draft-review inputs (registration-owned state — never tool params). */
export interface DraftReviewContext {
  /** The draft kind under review (the wave lane tasks are parameterized on it). */
  draftType: "plan" | "objective";
  /** The rendered draft bytes the door surfaced in the browser — the wave reviews exactly these. */
  draft: string;
  /** The human-supplied custom-angle definition from the door arg — adds the `custom` lane. */
  custom?: string;
}

/**
 * The draft pair's per-activation state: the ONE opaque ref of the pending (launched,
 * uncollected) draft-review wave (the `pi/v1/codeReview/reviewWave.ts` pending-slot mirror —
 * `start_draft_review_wave` refuses while it is set, and `collect_draft_review_wave` drains it;
 * the wave's settled keys include the `custom` lane when one was primed — the covered
 * computation needs it) PLUS the door-primed context slot (same defect class, same lifetime —
 * one browser session's inputs, superseded by the next prime). Which wave is *current* is flow
 * policy (this slot); every race/grace/drain mechanic below it is wave-owned.
 */
export interface DraftReviewWaveState {
  pending: ReportWaveRef | null;
  context: DraftReviewContext | null;
}

/** Create a fresh draft-review state (plain object — no Pi calls; safe anywhere in activation). */
export function createDraftReviewWaveState(): DraftReviewWaveState {
  return { pending: null, context: null };
}

/**
 * Prime the draft-review context for a new browser session (door-owned; called beside
 * `primeAnnotationSurface` the moment the browser open picks the port). Resets the pending-wave
 * slot too — a new browser session supersedes everything (the `primeAnnotationSurface`
 * discipline).
 */
export function primeDraftReviewContext(
  state: DraftReviewWaveState,
  next: DraftReviewContext,
): void {
  state.context = {
    draftType: next.draftType,
    draft: next.draft,
    ...(next.custom !== undefined ? { custom: next.custom } : {}),
  };
  state.pending = null;
}

/**
 * Drop the context (door-owned; called when the bridge settles AND on the degrade arm). A
 * launched wave stays collectable — only the primed inputs die with the browser session.
 */
export function clearDraftReviewContext(state: DraftReviewWaveState): void {
  state.context = null;
}
