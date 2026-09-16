// The `perk:wave` status marker's texts — the code-owned words the browser doors show where the
// reviewer findings will land, shared by the two launch/collect tool pairs (`draftReviewWaveTools`
// and `codeReview/reviewWave`). Review waves are completion-only, so the marker is the human's
// only in-browser signal that findings are still coming: running at launch, failed when zero
// lanes launched, incomplete (naming the uncovered lanes) or cleared at collection. Pure text
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

/**
 * The door-open TUI notice suffix (the three browser doors): review waves are completion-only,
 * so the human is told at open that annotations arrive when the wave completes and that an
 * early decision — authoritative by contract — forgoes them.
 */
export const WAVE_ARRIVAL_NOTICE =
  " — reviewer findings land as annotations when the wave completes; decide after they arrive";
