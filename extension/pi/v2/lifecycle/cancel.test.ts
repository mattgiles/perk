// V3 — the host's `cancel` verb (docs/design/pi-durable-v2-foundations.md §8, §10 the host,
// contracts.md §8.77) over real SQLite stores and the fake program: it follows `run`'s path without
// observing — a missing store is `incompatible` with `epoch: null` and creates nothing, a mismatched
// manifest is `incompatible`; an applied cancel records exactly the cancellation and quiesces
// `cancelled` with the cancellation receipt; an equal cancel replays that receipt, another reason is
// `duplicate_conflict` and records nothing; a later run over a new tree admits nothing; and a cancel
// after completion quiesces `completed`.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { test } from "node:test";
import { type HostVerb, runHost } from "../host.ts";
import { cancelOpId } from "../kernel/identity.ts";
import {
  assertSameRecords,
  C2,
  cancelOp,
  decisionIdOf,
  E,
  modelAfter,
  ofType,
  T1,
  T2,
} from "../testing/binding.ts";
import { assertNothingRecorded, recorded, recordsOf, replyVerb } from "../testing/decision.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectHostRefused,
  expectIncompatible,
  expectQuiescent,
  fakeProgram,
  hostOptions,
  observed,
  ownerEpochs,
  storeIn,
} from "../testing/host.ts";

function cancel(reason = "operator stop"): HostVerb {
  return { type: "cancel", reason };
}

test("V3: cancel on a missing store is incompatible with no epoch and creates nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  assert.deepEqual(await runHost(hostOptions(store), cancel()), {
    kind: "incompatible",
    epoch: null,
    mismatch: { field: "manifest_missing", expected: null, found: null },
  });
  assert.equal(existsSync(store), false, "the store directory is not created");
});

test("V3: cancel on a mismatched manifest is incompatible and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  const before = await recorded(options);
  const mismatched = hostOptions(store, fakeProgram({ policyVersion: 2 }));
  const outcome = expectIncompatible(await runHost(mismatched, cancel()), "policyVersion");
  assert.equal(typeof outcome.epoch, "number", "the gate runs under the lock");
  await assertNothingRecorded(options, before, "an incompatible cancel");
});

test("V3: an applied cancel records only the cancellation, never observes, and quiesces cancelled with its receipt; an equal cancel replays it", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store, fakeProgram({ accept: false }));
  const started = expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  assert.equal(started.view.waitReason, "assignment_incomplete");
  const before = started.view.records.records;

  const cancelled = expectQuiescent(await runHost(options, cancel()));
  assert.equal(cancelled.epoch, 2);
  assert.equal(cancelled.view.waitReason, "cancelled");
  const receipt = {
    opId: cancelOpId(E),
    record: { type: "cancellation", opId: cancelOpId(E), reason: "operator stop" },
    continuation: null,
    durable: [],
  };
  assert.deepEqual(cancelled.receipt, receipt);
  // Exactly the kernel model's cancellation: no observation was taken or recorded.
  assertSameRecords(
    cancelled.view.records.records,
    modelAfter(before, cancelOp()),
    "the cancel's records",
  );
  assert.equal(ofType(cancelled.view.records.records, "observation").length, 1);
  assert.ok(
    (await ownerEpochs(store)).every((entry) => entry.released),
    "every epoch released",
  );

  const after = await recorded(options);
  const replayed = expectQuiescent(await runHost(options, cancel()));
  assert.equal(replayed.view.waitReason, "cancelled");
  assert.deepEqual(replayed.receipt, receipt, "the same receipt");
  await assertNothingRecorded(options, after, "a replayed cancel");
});

test("V3: a cancel with another reason is duplicate_conflict and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store, fakeProgram({ accept: false }));
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  expectQuiescent(await runHost(options, cancel("first reason")));
  const before = await recorded(options);
  expectHostRefused(await runHost(options, cancel("second reason")), "duplicate_conflict");
  await assertNothingRecorded(options, before, "a conflicting cancel");
});

test("V3: after a cancel, a run over a new tree admits nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store, fakeProgram({ accept: false }));
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  expectQuiescent(await runHost(options, cancel()));
  const ran = expectQuiescent(await runHost(options, { type: "run", observe: observed(T2, C2) }));
  assert.equal(ran.view.waitReason, "cancelled");
  const assignments = ofType(ran.view.records.records, "assignment");
  assert.deepEqual(
    assignments.filter((assignment) => assignment.subject.digest === T2),
    [],
    "no assignment over the new tree",
  );
  assert.equal(ofType((await recordsOf(options)).records, "observation").length, 2);
});

test("V3: a cancel after completion quiesces completed with its own receipt", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  const replied = expectQuiescent(await runHost(options, replyVerb(observed(), decisionIdOf(T1))));
  assert.equal(replied.view.waitReason, "completed");
  const cancelled = expectQuiescent(await runHost(options, cancel()));
  assert.equal(cancelled.view.waitReason, "completed", "completion dominates");
  assert.equal(cancelled.receipt?.record.type, "cancellation");
  assert.equal(cancelled.receipt?.opId, cancelOpId(E));
});
