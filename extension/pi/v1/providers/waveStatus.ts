// The `perk:wave` status marker's texts — the code-owned words the browser doors show where the
// reviewer findings will land, shared by the two launch/collect tool pairs (`draftReviewWaveTools`
// and `codeReview/reviewWave`). Review waves are completion-only, so the marker is the human's
// only in-browser signal that findings are still coming: running at launch, failed when zero
// lanes launched, incomplete (naming the uncovered lanes) or cleared at collection. One more arm
// belongs to the browser-operation owner alone (never the tool pairs): the DETACHED marker, which
// replaces whatever the tab last showed once perk's wait on that review is over — replaced by a
// newer open, interrupted by a turn abort, or orphaned by a session reload/replacement. Pure text
// composition; the push mechanics live in `annotations.ts::replaceWaveStatus`.

/** The running marker: the lane census plus the decide-after-they-arrive nudge. */
export function waveRunningStatus(keys: readonly string[]): string {
  return (
    `Reviewer wave running — ${keys.length} lane(s): ${keys.join(", ")}. ` +
    "Findings land here as annotations when the wave completes; decide after they arrive."
  );
}

/** The launch soft-fail marker (zero runnable lanes): no findings will ever arrive. */
export function waveFailedStatus(reason: string): string {
  return `Reviewer wave failed to launch (${reason}) — no reviewer findings will arrive.`;
}

/** The incomplete-collect marker: the uncovered lanes; the covered lanes' findings follow. */
export function waveIncompleteStatus(uncovered: readonly string[]): string {
  return (
    `Reviewer wave incomplete — uncovered: ${uncovered.join(", ")}; ` +
    "findings from the covered lanes follow."
  );
}

/** Why perk's wait on a browser review ended while its tab stays open (the detached marker). */
export type ReviewDetachCause = "replaced" | "interrupted" | "session-ended";

/** The cause clause of each detached marker (what happened to perk's wait). */
const DETACH_CAUSE_TEXT: Readonly<Record<ReviewDetachCause, string>> = {
  replaced: "a newer browser review replaced it.",
  interrupted: "its wait was interrupted (the turn was aborted).",
  "session-ended": "the session reloaded or was replaced.",
};

/** The closing cue of each detached marker (where the human goes next). */
const DETACH_CUE_TEXT: Readonly<Record<ReviewDetachCause, string>> = {
  replaced: "decide in the newer review.",
  interrupted: "re-run the door to review again.",
  "session-ended": "re-run the door from the current session.",
};

/**
 * The detached marker: the tab stays open but perk no longer listens — findings will not arrive
 * and a decision made here will not reach the session. Same two facts for every cause; only the
 * cause clause and the cue differ.
 */
export function reviewDetachedStatus(cause: ReviewDetachCause): string {
  return (
    `Perk detached this review — ${DETACH_CAUSE_TEXT[cause]} ` +
    "Reviewer findings will not arrive here and a decision here will not reach the session; " +
    DETACH_CUE_TEXT[cause]
  );
}

/**
 * The door-open TUI notice suffix (the three browser doors): review waves are completion-only,
 * so the human is told at open that annotations arrive when the wave completes and that an
 * early decision — authoritative by contract — forgoes them.
 */
export const WAVE_ARRIVAL_NOTICE =
  " — reviewer findings land as annotations when the wave completes; decide after they arrive";
