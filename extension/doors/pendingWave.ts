// The per-registration pending-wave state the launch/collect door pairs share
// (`pi/v1/codeReview/reviewWave.ts` + `draftReviewWaveTools.ts`): plain state objects owned by registration
// closures and threaded as explicit parameters — deliberately NO interface/factory protocol and
// no controller abstraction. One shared collect function races the pending result against the
// bounded grace; everything else (error prose, aggregate shaping, warnings) stays with each
// door's execute core.
//
// The identity-guarded clear is the module's one subtle invariant: `collectPending` captures
// the pending record at entry and, after the race, clears the slot ONLY if it still holds that
// same record. A supersede during the await (the draft door's re-prime + new launch) therefore
// never erases the new pending wave — the stale collect still returns its settled result, and a
// following collect drains the new wave. Safe under the tools' `executionMode: "sequential"`;
// the guard additionally makes stale settles harmless.

import type { WaveResult } from "../waves/reportWave.ts";

/**
 * The grace a collect core allows a not-yet-settled wave before soft-failing `wave_running`:
 * long enough to absorb the completion-event-vs-`subagent_wait` wake race, short enough that an
 * early call never stalls the relay loop. Overridable for tests via PERK_WAVE_COLLECT_GRACE_MS.
 */
const WAVE_COLLECT_GRACE_MS = 15_000;

/** One knob, shared by the review-wave AND draft-review-wave collect cores (one env override). */
export function collectGraceMs(): number {
  const raw = Number(process.env.PERK_WAVE_COLLECT_GRACE_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : WAVE_COLLECT_GRACE_MS;
}

/**
 * One pending (launched, uncollected) wave: the pre-launch key manifest plus the
 * never-rejecting result promise. Deliberately NO run handle — collect never reads it (the
 * start tools' ok-details echo reads the launch handle at response-build time).
 */
export interface PendingWave<K extends string> {
  /** The launched keys (copied on store; caller-immutable). */
  keys: readonly K[];
  result: Promise<WaveResult>;
}

/** The one-slot pending-wave state a registration closure owns. */
export interface PendingWaveState<K extends string> {
  pending: PendingWave<K> | null;
}

const STILL_RUNNING = Symbol("wave-still-running");

/**
 * Race the pending wave against the grace: `"none"` when nothing is pending; `"running"` when
 * unsettled after the grace (the pending wave is RETAINED — its bound is the wave module's
 * timeout, and a later collect drains whatever it settles into); settled ⇒ the keys + result are
 * returned and the slot is cleared ONLY if it still holds the SAME record (the identity-guarded
 * clear — a supersede during the await never erases the new pending wave).
 */
export async function collectPending<K extends string>(
  state: PendingWaveState<K>,
  graceMs: number,
): Promise<
  | { kind: "none" }
  | { kind: "running" }
  | { kind: "settled"; keys: readonly K[]; result: WaveResult }
> {
  const wave = state.pending;
  if (wave === null) return { kind: "none" };
  let timer: ReturnType<typeof setTimeout> | undefined;
  const raced = await Promise.race([
    wave.result,
    new Promise<typeof STILL_RUNNING>((resolve) => {
      timer = setTimeout(() => resolve(STILL_RUNNING), graceMs);
    }),
  ]);
  clearTimeout(timer);
  if (raced === STILL_RUNNING) return { kind: "running" };
  if (state.pending === wave) state.pending = null;
  return { kind: "settled", keys: wave.keys, result: raced };
}
