// Store ownership at the host (docs/design/pi-durable-v2-foundations.md §10 store owner lock
// protocol): H1 — while a run holds the store mid-quiescence, another run and a status open are
// refused `owner_busy` with the holder's epoch, and the next epoch opens once it releases; H4 — a
// host that died between acquiring and its first commit leaves an unreleased epoch the next host
// treats as free, over a store that presents as `manifest_missing`, so `start` may run again.

import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { type HostRunOutcome, readStatus, runHost, STORE_DATABASE } from "../host.ts";
import { acquireOwnerLock } from "../store/ownerLock.ts";
import { CASE_TIMEOUT_MS, defer, deferred, fauxSetup, open } from "../testing/durable.ts";
import {
  expectIncompatible,
  expectQuiescent,
  expectStatus,
  fakeProgram,
  GHOST,
  hostOptions,
  LIVE_A,
  liveAB,
  observed,
  ownerEpochs,
  roleOf,
  storeIn,
} from "../testing/host.ts";

test("H1 (host): a second owner is refused while a run holds the store", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const entered = deferred();
  const gate = deferred();
  const blocking = fakeProgram({
    hooks: {
      before: async (input) => {
        if (roleOf(input.attemptId) !== "a") return;
        entered.resolve();
        await gate.promise;
      },
    },
  });
  const first = runHost(hostOptions(store, blocking), { type: "start", observe: observed() });
  defer(t, async () => {
    gate.resolve();
    await first.catch(() => {});
  });
  await entered.promise;

  // The run holds epoch 1 and is mid-quiescence.
  assert.deepEqual(await runHost(hostOptions(store), { type: "run", observe: observed() }), {
    kind: "owner_busy",
    epoch: 1,
  });
  assert.deepEqual(await readStatus(hostOptions(store)), { kind: "owner_busy", epoch: 1 });

  gate.resolve();
  const settled: HostRunOutcome = await first;
  assert.equal(expectQuiescent(settled).epoch, 1);
  assert.equal(expectStatus(await readStatus(hostOptions(store))).epoch, 2);
});

test("H4: a crash between acquisition and the first commit leaves a free epoch and a manifest_missing store", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await mkdir(store);
  // The dead host: it acquired epoch 1 and opened the store, then died before any v2 commit.
  const ghost = await acquireOwnerLock(store, { self: GHOST, liveness: liveAB() });
  assert.equal(ghost.kind, "acquired");
  const opened = await open(
    t,
    await openNodeSqliteStorage(join(store, STORE_DATABASE)),
    fauxSetup(),
  );
  await opened.dispose();

  const lock = { self: LIVE_A, liveness: liveAB() };
  const missing = expectIncompatible(
    await runHost(hostOptions(store, fakeProgram(), { lock }), {
      type: "run",
      observe: observed(),
    }),
    "manifest_missing",
  );
  assert.equal(missing.epoch, 2);
  const started = expectQuiescent(
    await runHost(hostOptions(store, fakeProgram(), { lock }), {
      type: "start",
      observe: observed(),
    }),
  );
  assert.equal(started.epoch, 3);
  assert.deepEqual(
    (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released, entry.meta.pid]),
    [
      [1, false, GHOST.pid],
      [2, true, LIVE_A.pid],
      [3, true, LIVE_A.pid],
    ],
  );
});
