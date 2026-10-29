// The store owner lock's proofs H1, H2, H3 and H5 (docs/design/pi-durable-v2-foundations.md §10
// store owner lock protocol) over a real temp filesystem, with injected identities and liveness:
// a second live owner is refused; two acquirers racing inside the check-then-act window after a
// dead owner yield exactly one new epoch; epochs are unique and strictly increasing; liveness fails
// closed. Plus the lost-round bound and release's nonce check.

import assert from "node:assert/strict";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { CASE_TIMEOUT_MS, deferred } from "../testing/durable.ts";
import {
  fakeLiveness,
  GHOST,
  LIVE_A,
  LIVE_B,
  liveAB,
  ownerEntries,
  ownerEpochs,
  storeIn,
  THIS_HOST,
} from "../testing/host.ts";
import type { HolderIdentity, Liveness } from "./liveness.ts";
import {
  ACQUIRE_ROUNDS,
  acquireOwnerLock,
  META_FILE,
  OWNER_DIR,
  type OwnerLockResult,
  RELEASED_FILE,
} from "./ownerLock.ts";

function expectAcquired(
  result: OwnerLockResult,
  epoch: number,
): Extract<OwnerLockResult, { kind: "acquired" }> {
  assert.equal(result.kind, "acquired", `expected acquired ${epoch}: ${JSON.stringify(result)}`);
  assert.ok(result.kind === "acquired");
  assert.equal(result.epoch, epoch);
  return result;
}

function expectBusy(result: OwnerLockResult, epoch: number): void {
  assert.deepEqual(
    { kind: result.kind, epoch: result.epoch },
    { kind: "owner_busy", epoch },
    `expected owner_busy ${epoch}`,
  );
}

/** Leave `owner/1` held by `holder` and unreleased (an owner that never released). */
async function heldBy(store: string, holder: HolderIdentity, liveness: Liveness): Promise<void> {
  expectAcquired(await acquireOwnerLock(store, { self: holder, liveness }), 1);
}

test("H1 (lock): a second owner is refused while the first holds the epoch", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = { self: LIVE_A, liveness: liveAB() };
  const first = expectAcquired(await acquireOwnerLock(store, options), 1);
  expectBusy(await acquireOwnerLock(store, options), 1);
  expectBusy(await acquireOwnerLock(store, { self: LIVE_B, liveness: liveAB() }), 1);
  await first.release();
  expectAcquired(await acquireOwnerLock(store, options), 2);
});

test("H2: two concurrent acquirers after a dead owner — exactly one creates the next epoch", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await heldBy(store, GHOST, fakeLiveness({ [GHOST.pid]: GHOST.startedAt }));

  // Both contenders classify epoch 1 as dead, then meet at a barrier right before the rename.
  let hookCalls = 0;
  let arrived = 0;
  const barrier = deferred();
  const hooks = {
    beforeRename: async (): Promise<void> => {
      hookCalls++;
      arrived++;
      if (arrived === 2) barrier.resolve();
      await barrier.promise;
    },
  };
  const results = await Promise.all([
    acquireOwnerLock(store, { self: LIVE_A, liveness: liveAB(), hooks }),
    acquireOwnerLock(store, { self: LIVE_B, liveness: liveAB(), hooks }),
  ]);
  assert.equal(hookCalls, 2, "both contenders reached the rename: the race really interleaved");
  const acquired = results.filter((result) => result.kind === "acquired");
  const busy = results.filter((result) => result.kind === "owner_busy");
  assert.equal(acquired.length, 1, "exactly one acquires");
  assert.equal(busy.length, 1, "the other is busy");
  assert.equal(acquired[0]?.epoch, 2);
  assert.equal(busy[0]?.epoch, 2, "the loser sees the winner's live epoch");
  assert.deepEqual(await ownerEntries(store), ["1", "2"], "no temp directory is left behind");
  const winner = results[0]?.kind === "acquired" ? LIVE_A : LIVE_B;
  const meta = (await ownerEpochs(store)).find((entry) => entry.epoch === 2)?.meta;
  assert.equal(meta?.pid, winner.pid, "owner/2/meta.json names the winner");
});

test("control (H2): sequential acquirers — the second is busy at classification", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await heldBy(store, GHOST, fakeLiveness({ [GHOST.pid]: GHOST.startedAt }));
  let hookCalls = 0;
  const hooks = {
    beforeRename: async (): Promise<void> => {
      hookCalls++;
    },
  };
  expectAcquired(await acquireOwnerLock(store, { self: LIVE_A, liveness: liveAB(), hooks }), 2);
  expectBusy(await acquireOwnerLock(store, { self: LIVE_B, liveness: liveAB(), hooks }), 2);
  assert.equal(hookCalls, 1, "the second contender never reached the rename");
});

test("H3 (lock): epochs are unique and strictly increasing; decoys are ignored", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await mkdir(join(store, OWNER_DIR), { recursive: true });
  for (const decoy of ["007", "abc", ".tmp.x"]) await mkdir(join(store, OWNER_DIR, decoy));
  const options = { self: LIVE_A, liveness: liveAB() };
  for (let epoch = 1; epoch <= 5; epoch++) {
    await expectAcquired(await acquireOwnerLock(store, options), epoch).release();
  }
  const cycles = await ownerEpochs(store);
  assert.deepEqual(
    cycles.map((entry) => entry.epoch),
    [1, 2, 3, 4, 5],
  );
  for (const entry of cycles) {
    assert.equal(entry.meta.epoch, entry.epoch, "meta.epoch equals its directory name");
    assert.ok(entry.released, `epoch ${entry.epoch} is released`);
  }
  assert.equal(new Set(cycles.map((entry) => entry.meta.nonce)).size, 5, "nonces are distinct");

  // A dead, unreleased epoch 6: the next acquisition is 7, never 6 again.
  expectAcquired(await acquireOwnerLock(store, { self: GHOST, liveness: liveAB() }), 6);
  expectAcquired(await acquireOwnerLock(store, options), 7);
  assert.deepEqual(
    (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released]),
    [
      [1, true],
      [2, true],
      [3, true],
      [4, true],
      [5, true],
      [6, false],
      [7, false],
    ],
  );
  assert.deepEqual(
    (await ownerEntries(store)).filter((name) => !/^[1-9][0-9]*$/.test(name)),
    [".tmp.x", "007", "abc"],
    "the decoys are left as they were",
  );
});

test("H5: an unsupported or foreign-host liveness seam never frees an unreleased epoch", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const deadToEveryone = fakeLiveness({});
  const cases: {
    name: string;
    holder?: HolderIdentity;
    tamper?: (meta: Record<string, unknown>) => unknown;
    liveness: Liveness;
  }[] = [
    {
      name: "a foreign host, while liveness says dead",
      holder: { ...GHOST, host: `${THIS_HOST}.elsewhere` },
      liveness: deadToEveryone,
    },
    { name: "liveness unsupported", holder: GHOST, liveness: fakeLiveness({}, "unsupported") },
    {
      name: "a null startedAt, while liveness says dead",
      holder: { ...GHOST, startedAt: null },
      liveness: deadToEveryone,
    },
    { name: "a malformed meta.json", tamper: () => "{not json", liveness: deadToEveryone },
    {
      name: "a meta.epoch mismatch",
      tamper: (meta) => JSON.stringify({ ...meta, epoch: 9 }),
      liveness: deadToEveryone,
    },
  ];
  for (const row of cases) {
    const store = await storeIn(t);
    await heldBy(store, row.holder ?? GHOST, deadToEveryone);
    if (row.tamper !== undefined) {
      const path = join(store, OWNER_DIR, "1", META_FILE);
      const meta: Record<string, unknown> = JSON.parse(await readFile(path, "utf8"));
      const tampered = row.tamper(meta);
      assert.equal(typeof tampered, "string");
      await writeFile(path, String(tampered));
    }
    expectBusy(await acquireOwnerLock(store, { self: LIVE_A, liveness: row.liveness }), 1);
  }

  // Controls: a same-host dead holder, or a reused pid, frees the epoch.
  const dead = await storeIn(t);
  await heldBy(dead, GHOST, deadToEveryone);
  expectAcquired(await acquireOwnerLock(dead, { self: LIVE_A, liveness: deadToEveryone }), 2);
  const reused = await storeIn(t);
  await heldBy(reused, GHOST, deadToEveryone);
  const otherProcess = fakeLiveness({ [GHOST.pid]: "9999" });
  expectAcquired(await acquireOwnerLock(reused, { self: LIVE_A, liveness: otherProcess }), 2);

  // A released marker frees even a foreign or unsupported holder.
  for (const [holder, liveness] of [
    [{ ...GHOST, host: `${THIS_HOST}.elsewhere` }, deadToEveryone],
    [GHOST, fakeLiveness({}, "unsupported")],
  ] as const) {
    const store = await storeIn(t);
    const held = expectAcquired(await acquireOwnerLock(store, { self: holder, liveness }), 1);
    await held.release();
    expectAcquired(await acquireOwnerLock(store, { self: LIVE_A, liveness }), 2);
  }
});

test("three lost renames end in owner_busy and leave no temp directory", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  let hookCalls = 0;
  const hooks = {
    // Another contender wins each epoch first: a complete, released directory appears.
    beforeRename: async (epoch: number): Promise<void> => {
      hookCalls++;
      const dir = join(store, OWNER_DIR, String(epoch));
      await mkdir(dir);
      const meta = { epoch, pid: LIVE_B.pid, host: THIS_HOST, startedAt: "1003", nonce: "x" };
      await writeFile(join(dir, META_FILE), JSON.stringify(meta));
      await writeFile(join(dir, RELEASED_FILE), "{}");
    },
  };
  expectBusy(
    await acquireOwnerLock(store, { self: LIVE_A, liveness: liveAB(), hooks }),
    ACQUIRE_ROUNDS,
  );
  assert.equal(hookCalls, ACQUIRE_ROUNDS);
  assert.deepEqual(await ownerEntries(store), ["1", "2", "3"], "no temp directory is left behind");
});

test("release writes the marker once, and refuses an epoch whose nonce changed", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = { self: LIVE_A, liveness: liveAB() };
  const held = expectAcquired(await acquireOwnerLock(store, options), 1);
  const marker = join(store, OWNER_DIR, "1", RELEASED_FILE);
  await held.release();
  const written = await readFile(marker, "utf8");
  const meta = (await ownerEpochs(store))[0]?.meta;
  assert.deepEqual(JSON.parse(written), { epoch: 1, nonce: meta?.nonce });
  await writeFile(marker, "kept");
  await held.release();
  assert.equal(await readFile(marker, "utf8"), "kept", "a second release writes nothing");
  assert.deepEqual(await ownerEntries(store), ["1"]);
  assert.deepEqual(
    (await readdir(join(store, OWNER_DIR, "1"))).sort(),
    [META_FILE, RELEASED_FILE],
    "release leaves no temp file",
  );

  const tampered = expectAcquired(await acquireOwnerLock(store, options), 2);
  const path = join(store, OWNER_DIR, "2", META_FILE);
  const stored: Record<string, unknown> = JSON.parse(await readFile(path, "utf8"));
  await writeFile(path, JSON.stringify({ ...stored, nonce: "someone-else" }));
  await assert.rejects(tampered.release(), /owner epoch 2/);
  assert.equal(
    (await ownerEpochs(store)).find((entry) => entry.epoch === 2)?.released,
    false,
    "no marker",
  );
});
