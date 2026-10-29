// The run-to-quiescence driver (docs/design/pi-durable-v2-foundations.md §10 steps 3–9) over real
// SQLite stores: `start` and `run` reach quiescence with exactly the kernel model's records; the
// host closes only once every fake phase has run; an observation failure or a refusal records
// nothing; and H3 at the host: epochs are unique, strictly increasing and released across verbs.

import assert from "node:assert/strict";
import { join } from "node:path";
import { test } from "node:test";
import type { ReportInfo } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { readStatus, runHost, STORE_DATABASE } from "../host.ts";
import {
  acceptOp,
  assertSameRecords,
  C1,
  C1B,
  FAKE_ASSIGNMENT_NAME,
  facts,
  installBinding,
  modelAfter,
  modelChain,
  ofType,
  openBinding,
  policyA,
  runOp,
  startOp,
  T1,
  tasksOfKind,
} from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, fauxSetup } from "../testing/durable.ts";
import {
  expectIncompatible,
  expectQuiescent,
  expectStatus,
  failedObservation,
  fakeProgram,
  hostOptions,
  observed,
  ownerEpochs,
  spyObserve,
  storeIn,
} from "../testing/host.ts";

const START_RECORDS = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1)]);

test("start and then run reach quiescence with exactly the model's records", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store);
  const started = expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  assert.equal(started.epoch, 1);
  assert.equal(started.view.waitReason, "pending_decision");
  assert.equal(started.view.wake.active, false);
  assertSameRecords(started.view.records.records, START_RECORDS, "start's records");
  assert.deepEqual(
    (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released]),
    [[1, true]],
  );

  // A same-tree observation: a new observation, no new admission.
  const ran = expectQuiescent(await runHost(options, { type: "run", observe: observed(T1, C1B) }));
  assert.equal(ran.epoch, 2);
  assert.equal(ran.view.waitReason, "pending_decision");
  assertSameRecords(
    ran.view.records.records,
    modelAfter(START_RECORDS, runOp(T1, C1B)),
    "run's records: the previous set plus observe/2",
  );
});

test("a fake that never accepts quiesces as assignment_incomplete", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store, fakeProgram({ accept: false }));
  const outcome = expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  assert.equal(outcome.view.waitReason, "assignment_incomplete");
  assert.equal(ofType(outcome.view.records.records, "report-outcome").length, 0);
});

test("the host closes only after quiescence: every fake phase ran on an open Harness", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const infos: ReportInfo[] = [];
  const options = hostOptions(store, fakeProgram(), {
    onReport: (_error, info) => infos.push(info),
  });
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  assert.deepEqual(
    infos.filter((info) => info.type === "task_faulted"),
    [],
    "no task faulted against a closed Harness",
  );

  // Reopen below the host, never resumed: both fakes are terminal and completed.
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const { opened } = await openBinding(
    t,
    await openNodeSqliteStorage(join(store, STORE_DATABASE)),
    setup,
    installed,
  );
  const fakes = await tasksOfKind(opened.harness, FAKE_ASSIGNMENT_NAME);
  assert.equal(fakes.length, 2);
  for (const task of fakes) {
    assert.equal(task.state.status, "terminal");
    assert.equal(task.state.outcome?.status, "completed");
  }
});

test("an observation failure records nothing, and start may run again", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store);
  assert.deepEqual(
    await runHost(options, { type: "start", observe: failedObservation("no such ref") }),
    { kind: "observation_failed", epoch: 1, detail: "no such ref" },
  );
  expectIncompatible(await readStatus(options), "manifest_missing");
  const outcome = expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  assert.equal(outcome.epoch, 3);
  assertSameRecords(outcome.view.records.records, START_RECORDS, "the re-run start");
});

test("a run naming another repo is refused and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  const spy = spyObserve(() =>
    Promise.resolve({ kind: "observed", facts: { ...facts(T1, C1B), repo: "/other/.git" } }),
  );
  const refused = await runHost(options, { type: "run", observe: spy.observe });
  assert.equal(refused.kind, "refused");
  assert.ok(refused.kind === "refused");
  assert.equal(refused.epoch, 2);
  assert.equal(refused.refusal.reason, "invalid_input");
  assert.equal(spy.calls(), 1);
  const status = expectStatus(await readStatus(options));
  assert.equal(ofType(status.view.records.records, "observation").length, 1);
  assertSameRecords(status.view.records.records, START_RECORDS, "nothing recorded");
});

test("H3 (host): start, status, run, status hold epochs 1–4, each released", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store);
  const epochs = [
    expectQuiescent(await runHost(options, { type: "start", observe: observed() })).epoch,
    expectStatus(await readStatus(options)).epoch,
    expectQuiescent(await runHost(options, { type: "run", observe: observed(T1, C1) })).epoch,
    expectStatus(await readStatus(options)).epoch,
  ];
  assert.deepEqual(epochs, [1, 2, 3, 4]);
  const owned = await ownerEpochs(store);
  assert.deepEqual(
    owned.map((entry) => [entry.epoch, entry.released, entry.meta.epoch]),
    [
      [1, true, 1],
      [2, true, 2],
      [3, true, 3],
      [4, true, 4],
    ],
  );
  assert.equal(new Set(owned.map((entry) => entry.meta.nonce)).size, 4);
  assert.equal(owned[0]?.meta.pid, process.pid);
});
