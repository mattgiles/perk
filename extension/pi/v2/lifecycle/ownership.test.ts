// Store ownership at the host (docs/design/pi-durable-v2-foundations.md §10 store owner lock
// protocol): H1 — while a run holds the store mid-quiescence, another run and a status open are
// refused `owner_busy` with the holder's epoch, and the next epoch opens once it releases; H4 — a
// host that died between acquiring and its first commit leaves an unreleased epoch the next host
// treats as free, over a store that presents as `manifest_missing`, so `start` may run again. And
// close before release: while the Harness's shutdown is held — after a quiescent run, a failed
// Harness, or a failed open — the epoch stays unreleased and a competing host is `owner_busy`.

import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import type { Storage } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  type HostOptions,
  type HostRunOutcome,
  readStatus,
  runHost,
  STORE_DATABASE,
} from "../host.ts";
import { acquireOwnerLock } from "../store/ownerLock.ts";
import {
  CASE_TIMEOUT_MS,
  defer,
  deferred,
  failing,
  fauxSetup,
  gatedClose,
  open,
} from "../testing/durable.ts";
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

/**
 * How long a run whose close is held gets to (wrongly) settle and release. A correct host never
 * settles while its close is held, so the window cannot fail it; it only bounds how long a host
 * that releases before closing has to show itself (its release takes a few file operations).
 */
const SHUTDOWN_GRACE_MS = 100;

/** Whether `promise` settles, either way, within `ms` of real time. */
function settlesWithin(promise: Promise<unknown>, ms: number): Promise<boolean> {
  return Promise.race([
    promise.then(
      () => true,
      () => true,
    ),
    sleep(ms).then(() => false),
  ]);
}

type ShutdownRow = {
  readonly name: string;
  readonly expected: HostRunOutcome["kind"];
  /** The run's options over `store`, given the storage seam that gates its close. */
  options(store: string, openStorage: (path: string) => Promise<Storage>): HostOptions;
  /** Wrap the SQLite storage before the close gate (a failure injector). */
  wrap?(inner: Storage): Storage;
};

/** A program whose first fake phase fails the next storage commit, through `arm`. */
function failingOnce(arm: () => void) {
  let armed = false;
  return fakeProgram({
    hooks: {
      before: () => {
        if (armed) return;
        armed = true;
        arm();
      },
    },
  });
}

test("close before release: the epoch stays held while the Harness is shutting down", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  let armNextCommit: ((error: Error) => void) | undefined;
  const rows: readonly ShutdownRow[] = [
    {
      name: "a quiescent run",
      expected: "quiescent",
      options: (store, openStorage) => hostOptions(store, fakeProgram(), { openStorage }),
    },
    {
      name: "a failed Harness, closing itself",
      expected: "uncertain",
      wrap: (inner) => {
        const store = failing(inner);
        armNextCommit = store.armNextCommit;
        return store.storage;
      },
      options: (store, openStorage) =>
        hostOptions(
          store,
          failingOnce(() => armNextCommit?.(new Error("phase commit failed"))),
          { openStorage },
        ),
    },
    {
      name: "a failed Harness.open, its storage closed by the host",
      expected: "uncertain",
      options: (store, openStorage) =>
        hostOptions(store, fakeProgram(), {
          openStorage,
          openHarness: () => Promise.reject(new Error("open failed")),
        }),
    },
  ];
  for (const row of rows) {
    const store = await storeIn(t);
    const gated = deferred<ReturnType<typeof gatedClose>>();
    const openStorage = async (path: string): Promise<Storage> => {
      const inner = await openNodeSqliteStorage(path);
      const gate = gatedClose(row.wrap?.(inner) ?? inner);
      gated.resolve(gate);
      return gate.storage;
    };
    const run = runHost(row.options(store, openStorage), {
      type: "start",
      observe: observed(),
    });
    defer(t, async () => {
      (await gated.promise).release();
      await run.catch(() => {});
    });

    // The Harness is in its shutdown, its storage close held.
    const gate = await gated.promise;
    await gate.closing;
    assert.equal(await settlesWithin(run, SHUTDOWN_GRACE_MS), false, `${row.name}: the run waits`);
    assert.deepEqual(
      await readStatus(hostOptions(store)),
      { kind: "owner_busy", epoch: 1 },
      `${row.name}: a competing host is refused`,
    );
    assert.deepEqual(
      (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released]),
      [[1, false]],
      `${row.name}: the epoch is still held`,
    );

    gate.release();
    assert.equal((await run).kind, row.expected, row.name);
    assert.deepEqual(
      (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released]),
      [[1, true]],
      `${row.name}: released once closed`,
    );
    const next = await readStatus(hostOptions(store));
    assert.notEqual(next.kind, "owner_busy", row.name);
    assert.equal(next.epoch, 2, `${row.name}: the next host acquires`);
  }
});
