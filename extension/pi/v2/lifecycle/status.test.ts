// The read-only status open (docs/design/pi-durable-v2-foundations.md §10 status) and H7: a status
// open never schedules work. Through a call-recording Harness it makes no forbidden call — no
// commit (not even a probe), resume, conversation creation, retry, abort or wait — on the normal
// path and on a failed one, where a storage failure in its first read is `uncertain`. Pending work
// stays ready across repeated status opens; the run control shows the recorder sees the calls.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { CATALOG_KIND } from "../durable/documents.ts";
import { readStatus, runHost } from "../host.ts";
import { C1B, FAKE_ASSIGNMENT_NAME, T1 } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, failingFind } from "../testing/durable.ts";
import {
  expectIncompatible,
  expectQuiescent,
  expectStatus,
  FORBIDDEN_STATUS_CALLS,
  fakeProgram,
  harnessSpy,
  hostOptions,
  observed,
  ownerEpochs,
  phaseLog,
  seedStartedStore,
  storeIn,
} from "../testing/host.ts";

function forbidden(calls: readonly string[]): string[] {
  const banned: readonly string[] = FORBIDDEN_STATUS_CALLS;
  return calls.filter((call) => banned.includes(call));
}

test("H7: a status open never schedules work", { timeout: CASE_TIMEOUT_MS }, async (t) => {
  const store = await storeIn(t);
  await seedStartedStore(t, store);
  const phases = phaseLog();
  for (const [index, epoch] of [1, 2].entries()) {
    const spy = harnessSpy();
    const status = expectStatus(
      await readStatus(
        hostOptions(store, fakeProgram({ hooks: phases.hooks }), { openHarness: spy.openHarness }),
      ),
    );
    const open = `status open ${index + 1}`;
    assert.equal(status.epoch, epoch, open);
    assert.equal(status.view.waitReason, null, `${open}: running work, no wait reason`);
    assert.equal(status.view.wake.active, true, open);
    assert.equal(status.view.inspection.scheduling, "paused", open);
    assert.deepEqual(
      status.view.inspection.tasks
        .filter((task) => task.record.kind === FAKE_ASSIGNMENT_NAME)
        .map((task) => task.state.kind),
      ["ready", "ready"],
      open,
    );
    assert.equal(phases.count(), 0, `${open}: no phase ran`);
    assert.ok(spy.calls().includes("inspect"), `${open}: the recorder sees calls`);
    assert.deepEqual(forbidden(spy.calls()), [], `${open}: no forbidden call`);
  }

  // Vacuity: a run through the same recorder runs the phases, and the recorder sees its calls.
  const spy = harnessSpy();
  expectQuiescent(
    await runHost(
      hostOptions(store, fakeProgram({ hooks: phases.hooks }), { openHarness: spy.openHarness }),
      { type: "run", observe: observed(T1, C1B) },
    ),
  );
  assert.equal(phases.count(), 2);
  assert.ok(spy.calls().includes("commit"), "the recorder sees a commit");
  assert.ok(spy.calls().includes("resume"), "the recorder sees a resume");
});

test("a status read on a failed Harness is uncertain, with no commit call", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await seedStartedStore(t, store);
  const boom = new Error("catalog read failed");
  const spy = harnessSpy();
  const outcome = await readStatus(
    hostOptions(store, fakeProgram(), {
      openHarness: spy.openHarness,
      openStorage: async (path) => {
        const failing = failingFind(await openNodeSqliteStorage(path), CATALOG_KIND);
        failing.arm(boom);
        return failing.storage;
      },
    }),
  );
  assert.equal(outcome.kind, "uncertain", JSON.stringify(outcome));
  assert.ok(outcome.kind === "uncertain");
  assert.equal(outcome.error, boom);
  assert.equal(outcome.epoch, 1);
  assert.deepEqual(forbidden(spy.calls()), [], "no forbidden call, no probe commit");
  assert.deepEqual(
    (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released]),
    [[1, true]],
  );
  assert.equal(expectStatus(await readStatus(hostOptions(store))).epoch, 2);
});

test("status on a quiescent store reports its wait reason; a mismatched program is refused", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  expectQuiescent(await runHost(hostOptions(store), { type: "start", observe: observed() }));
  const status = expectStatus(await readStatus(hostOptions(store)));
  assert.equal(status.view.waitReason, "pending_decision");
  assert.equal(status.view.wake.active, false);
  expectIncompatible(
    await readStatus(hostOptions(store, fakeProgram({ policyVersion: 2 }))),
    "policyVersion",
  );
});
