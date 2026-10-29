// The consistent-view quiescence loop (docs/design/pi-durable-v2-foundations.md §10 step 7–8): a
// view is accepted only when no commit landed while it was collected and `wake()` is still
// inactive after it. A sleeping deadline that passes during collection, and a commit published
// during collection, each send the driver back to resuming and polling; the controls show a single
// collection when nothing moves.

import assert from "node:assert/strict";
import { test } from "node:test";
import { defineDoc, type JsonObject } from "@earendil-works/pi-durable";
import { runHost } from "../host.ts";
import { ofType } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, context } from "../testing/durable.ts";
import {
  expectQuiescent,
  fakeProgram,
  HOST_NOW,
  harnessSpy,
  hostOptions,
  observed,
  sleepyProgram,
  storeIn,
} from "../testing/host.ts";

/** A non-v2 session document: a commit the v2 records never see. */
const MarkerDoc = defineDoc<JsonObject>({
  kind: "test.marker",
  version: 1,
  scope: "session",
  initial: () => ({ marked: true }),
  checkpointWhen: () => true,
});

function inspects(calls: readonly string[]): number {
  return calls.filter((call) => call === "inspect").length;
}

/**
 * Run `start` under the sleepy program, with the Harness clock frozen and timers that never fire.
 * The timers are accepted and then simply never run — Durable arms a declined foreground timer with
 * `setTimeout` instead — so only the driver's own `resume()` can wake a due sleeper.
 */
async function sleepyStart(t: Parameters<typeof storeIn>[0], advance: boolean) {
  const until = HOST_NOW + 1000;
  let clock = HOST_NOW;
  const spy = harnessSpy({
    harness: { now: () => clock, setTimer: () => () => {} },
    onInspect: (call) => {
      // The deadline passes between the driver's last inactive poll and its view collection.
      if (advance && call === 1) clock = until;
    },
  });
  const store = await storeIn(t);
  const outcome = expectQuiescent(
    await runHost(hostOptions(store, sleepyProgram(until), { openHarness: spy.openHarness }), {
      type: "start",
      observe: observed(),
    }),
  );
  return { outcome, calls: spy.calls(), until };
}

test("a sleeping deadline that passes during view collection returns the driver to polling", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { outcome, calls } = await sleepyStart(t, true);
  assert.equal(outcome.view.waitReason, "pending_decision");
  assert.equal(ofType(outcome.view.records.records, "report-outcome").length, 2);
  assert.ok(inspects(calls) >= 2, `the first view was rejected: ${inspects(calls)} inspections`);
});

test("control: with the clock still, the run quiesces sleeping after one collection", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { outcome, calls, until } = await sleepyStart(t, false);
  assert.equal(outcome.view.waitReason, "sleeping");
  assert.equal(outcome.view.wake.active, false);
  assert.equal(outcome.view.wake.at, until);
  assert.equal(ofType(outcome.view.records.records, "report-outcome").length, 0);
  assert.equal(inspects(calls), 1);
});

test("a commit published during view collection returns the driver to polling", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  for (const marker of [true, false]) {
    const spy = harnessSpy({
      onInspect: async (call, harness) => {
        if (!marker || call !== 1) return;
        await harness.commit(async (tx) => {
          await tx.doc(MarkerDoc);
        }, context);
      },
    });
    const store = await storeIn(t);
    const outcome = expectQuiescent(
      await runHost(hostOptions(store, fakeProgram(), { openHarness: spy.openHarness }), {
        type: "start",
        observe: observed(),
      }),
    );
    assert.equal(outcome.view.waitReason, "pending_decision");
    if (marker) {
      assert.ok(inspects(spy.calls()) >= 2, "the view collected around the commit was rejected");
    } else {
      assert.equal(inspects(spy.calls()), 1, "control: one collection");
    }
  }
});
