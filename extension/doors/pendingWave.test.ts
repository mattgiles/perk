// The shared pending-wave collector's own suite: the none/running/settled arms, drain-once, the
// grace knob's env override, and the module's one subtle invariant — the identity-guarded clear
// (a supersede DURING an in-flight collect's await never erases the new pending wave). Pure
// state + promises: no adapters, no sessions, no timers beyond the grace race itself.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { WaveResult } from "../waves/reportWave.ts";
import { collectGraceMs, collectPending, type PendingWaveState } from "./pendingWave.ts";

function settled(keys: string[]): WaveResult {
  return {
    complete: true,
    reports: keys.map((key) => ({ key, report: { angle: key } })),
    failures: [],
    receipt: { state: "complete", children: [] },
  };
}

/** A pending wave whose result the test settles on demand. */
function deferredWave(keys: string[]): {
  wave: { keys: readonly string[]; result: Promise<WaveResult> };
  settle: () => void;
} {
  let resolve: (result: WaveResult) => void = () => {};
  const result = new Promise<WaveResult>((r) => {
    resolve = r;
  });
  return { wave: { keys, result }, settle: () => resolve(settled(keys)) };
}

test("collectPending: none without a pending wave", async () => {
  const state: PendingWaveState<string> = { pending: null };
  assert.deepEqual(await collectPending(state, 5), { kind: "none" });
});

test("collectPending: running retains the pending wave; the later collect drains it once", async () => {
  const state: PendingWaveState<string> = { pending: null };
  const { wave, settle } = deferredWave(["a", "b"]);
  state.pending = wave;

  const running = await collectPending(state, 10);
  assert.deepEqual(running, { kind: "running" });
  assert.equal(state.pending, wave, "an unsettled wave is RETAINED, never dropped");

  settle();
  const drained = await collectPending(state, 1_000);
  assert.equal(drained.kind, "settled");
  if (drained.kind !== "settled") return;
  assert.deepEqual(drained.keys, ["a", "b"]);
  assert.equal(drained.result.complete, true);
  assert.equal(state.pending, null, "the settled drain clears the slot");

  // Drain-once: the following collect is none.
  assert.deepEqual(await collectPending(state, 5), { kind: "none" });
});

test("collectPending: a supersede during the collect's await never erases the NEW pending wave", async () => {
  // The latent-erasure regression: collect awaits wave 1; meanwhile a re-prime + new launch
  // stores wave 2. The stale collect must return wave 1's settled result WITHOUT clearing
  // wave 2 (the identity-guarded clear), and a following collect drains wave 2.
  const state: PendingWaveState<string> = { pending: null };
  const first = deferredWave(["one"]);
  const second = deferredWave(["two"]);
  state.pending = first.wave;

  const staleCollect = collectPending(state, 5_000);
  // The supersede lands while the stale collect is racing wave 1's result.
  state.pending = second.wave;
  first.settle();

  const stale = await staleCollect;
  assert.equal(stale.kind, "settled");
  if (stale.kind !== "settled") return;
  assert.deepEqual(stale.keys, ["one"], "the stale collect returns wave 1's settled result");
  assert.equal(state.pending, second.wave, "wave 2 SURVIVES the stale collect's clear");

  second.settle();
  const next = await collectPending(state, 1_000);
  assert.equal(next.kind, "settled");
  if (next.kind !== "settled") return;
  assert.deepEqual(next.keys, ["two"], "the following collect drains wave 2");
  assert.equal(state.pending, null);
});

test("collectGraceMs: the module default with the env override (invalid values fall back)", () => {
  const prev = process.env.PERK_WAVE_COLLECT_GRACE_MS;
  try {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
    assert.equal(collectGraceMs(), 15_000, "the module default is the seam's contract");
    process.env.PERK_WAVE_COLLECT_GRACE_MS = "250";
    assert.equal(collectGraceMs(), 250);
    for (const bad of ["0", "-5", "nope", ""]) {
      process.env.PERK_WAVE_COLLECT_GRACE_MS = bad;
      assert.equal(collectGraceMs(), 15_000, `invalid override falls back: ${bad}`);
    }
  } finally {
    if (prev === undefined) delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
    else process.env.PERK_WAVE_COLLECT_GRACE_MS = prev;
  }
});
