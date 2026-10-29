// Harness failure at the host (docs/design/pi-durable-v2-foundations.md §9 uncertain, §10): a
// storage failure in the verb's own commit, one during quiescence, and a storage open that
// rejects are each `uncertain`; a non-storage throw (an `observe` bug) is rethrown as itself. In
// every case the Harness closes before the epoch is released, and the next run recovers under the
// following epoch without repeating accepted work.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionFailed, type Storage } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { type HostRunOutcome, runHost } from "../host.ts";
import { observeOpId } from "../kernel/identity.ts";
import { C1B, E, ofType, T1 } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, failing } from "../testing/durable.ts";
import {
  expectQuiescent,
  fakeProgram,
  hostOptions,
  observed,
  ownerEpochs,
  storeIn,
} from "../testing/host.ts";

function expectUncertain(outcome: HostRunOutcome): unknown {
  assert.equal(outcome.kind, "uncertain", JSON.stringify(outcome));
  assert.ok(outcome.kind === "uncertain");
  return outcome.error;
}

/** Every epoch so far is released. */
async function allReleased(store: string, count: number): Promise<void> {
  assert.deepEqual(
    (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released]),
    Array.from({ length: count }, (_, i) => [i + 1, true]),
  );
}

/** An `openStorage` seam over SQLite whose last opened store can be armed to fail its next commit. */
function armable(): { open(path: string): Promise<Storage>; armNextCommit(error: Error): void } {
  let arm: ((error: Error) => void) | undefined;
  return {
    open: async (path) => {
      const store = failing(await openNodeSqliteStorage(path));
      arm = store.armNextCommit;
      return store.storage;
    },
    armNextCommit: (error) => {
      assert.ok(arm !== undefined, "a store is open");
      arm(error);
    },
  };
}

test("a storage failure in the verb's commit is uncertain, and nothing of it lands", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const storage = armable();
  const options = hostOptions(store, fakeProgram(), { openStorage: storage.open });
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  const boom = new Error("commit failed");
  const error = expectUncertain(
    await runHost(options, {
      type: "run",
      observe: async (tracked) => {
        storage.armNextCommit(boom);
        return await observed(T1, C1B)(tracked);
      },
    }),
  );
  assert.equal(error, boom);
  await allReleased(store, 2);

  const recovered = expectQuiescent(
    await runHost(options, { type: "run", observe: observed(T1, C1B) }),
  );
  assert.equal(recovered.epoch, 3);
  assert.deepEqual(
    ofType(recovered.view.records.records, "observation").map((record) => record.opId),
    [observeOpId(E, 1), observeOpId(E, 2)],
    "the failed observation never landed",
  );
});

test("a storage failure during quiescence is uncertain, and the next run recovers", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const storage = armable();
  let armed = false;
  const failingOnce = fakeProgram({
    hooks: {
      before: () => {
        if (armed) return;
        armed = true;
        storage.armNextCommit(new Error("phase commit failed"));
      },
    },
  });
  const error = expectUncertain(
    await runHost(hostOptions(store, failingOnce, { openStorage: storage.open }), {
      type: "start",
      observe: observed(),
    }),
  );
  assert.ok(error instanceof SessionFailed, `SessionFailed, not ${String(error)}`);
  await allReleased(store, 1);

  const recovered = expectQuiescent(
    await runHost(hostOptions(store), { type: "run", observe: observed(T1, C1B) }),
  );
  assert.equal(recovered.epoch, 2);
  assert.equal(recovered.view.waitReason, "pending_decision");
  assert.equal(ofType(recovered.view.records.records, "report-outcome").length, 2);
});

test("a storage open that rejects is uncertain; the next start runs", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const boom = new Error("cannot open");
  const error = expectUncertain(
    await runHost(hostOptions(store, fakeProgram(), { openStorage: () => Promise.reject(boom) }), {
      type: "start",
      observe: observed(),
    }),
  );
  assert.equal(error, boom);
  await allReleased(store, 1);
  assert.equal(
    expectQuiescent(await runHost(hostOptions(store), { type: "start", observe: observed() }))
      .epoch,
    2,
  );
});

test("an observe that throws is rethrown as itself, after close and release", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const bug = new TypeError("observe bug");
  await assert.rejects(
    runHost(hostOptions(store), { type: "start", observe: () => Promise.reject(bug) }),
    (error) => error === bug,
  );
  await allReleased(store, 1);
  assert.equal(
    expectQuiescent(await runHost(hostOptions(store), { type: "start", observe: observed() }))
      .epoch,
    2,
  );
});
