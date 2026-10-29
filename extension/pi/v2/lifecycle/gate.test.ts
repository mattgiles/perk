// The exact-match manifest gate (docs/design/pi-durable-v2-foundations.md §10 step 4, §9) and H6:
// an incompatible manifest is refused before any task phase runs and before observing — the
// pending work stays ready, and the compatible control runs it. Each gate field is reached from a
// real host program; `start` on a started store is `already_started`; a store directory without a
// manifest, or no store directory at all, is `manifest_missing` — the latter with no lock taken and
// nothing created.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { test } from "node:test";
import { defineTask } from "@earendil-works/pi-durable";
import { readStatus, runHost } from "../host.ts";
import { C1B, FAKE_ASSIGNMENT_NAME, T1 } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectIncompatible,
  expectQuiescent,
  expectStatus,
  fakeProgram,
  hostOptions,
  observed,
  phaseLog,
  seedStartedStore,
  spyObserve,
  storeIn,
} from "../testing/host.ts";

const extraTask = defineTask<null, { phase: "run" }, null>({
  name: "perk.v2.extra",
  version: 1,
  initial: () => ({ phase: "run" }),
  phases: { run: async () => {} },
  abort: async () => {},
});

test("H6: an incompatible manifest is refused with no task phase executed", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await seedStartedStore(t, store);
  const phases = phaseLog();
  const spy = spyObserve(observed(T1, C1B));
  const refused = expectIncompatible(
    await runHost(hostOptions(store, fakeProgram({ policyVersion: 2, hooks: phases.hooks })), {
      type: "run",
      observe: spy.observe,
    }),
    "policyVersion",
  );
  assert.deepEqual(refused, {
    kind: "incompatible",
    epoch: 1,
    mismatch: { field: "policyVersion", expected: 2, found: 1 },
  });
  assert.equal(phases.count(), 0, "no task phase ran");
  assert.equal(spy.calls(), 0, "the verb never observed");

  // The pending work is untouched: both fakes are still ready.
  const status = expectStatus(await readStatus(hostOptions(store)));
  assert.deepEqual(
    status.view.inspection.tasks
      .filter((task) => task.record.kind === FAKE_ASSIGNMENT_NAME)
      .map((task) => task.state.kind),
    ["ready", "ready"],
  );

  // Vacuity: the compatible program runs both phases.
  const ran = expectQuiescent(
    await runHost(hostOptions(store, fakeProgram({ hooks: phases.hooks })), {
      type: "run",
      observe: observed(T1, C1B),
    }),
  );
  assert.equal(phases.count(), 2);
  assert.equal(ran.view.waitReason, "pending_decision");
});

test("an extra task or another execution id is named by its gate field", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await seedStartedStore(t, store);
  const extra = expectIncompatible(
    await runHost(hostOptions(store, fakeProgram({ extraTasks: [extraTask] })), {
      type: "run",
      observe: observed(T1, C1B),
    }),
    "definitions",
  );
  assert.equal(Reflect.get(Object(extra.mismatch.expected), "perk.v2.extra"), 1);
  assert.equal(Reflect.get(Object(extra.mismatch.found), "perk.v2.extra"), undefined);
  const elsewhere = hostOptions(store, fakeProgram(), {
    workspace: { repoIdentity: "/repo/.git", executionId: "01HZY3V8Q2M5N7P9R1T3V5X7ZA" },
  });
  expectIncompatible(
    await runHost(elsewhere, { type: "run", observe: observed(T1, C1B) }),
    "workspace",
  );
  expectIncompatible(await readStatus(elsewhere), "workspace");
});

test("start on a started store is refused already_started without observing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await seedStartedStore(t, store);
  const spy = spyObserve(observed());
  const outcome = await runHost(hostOptions(store), { type: "start", observe: spy.observe });
  assert.equal(outcome.kind, "refused");
  assert.ok(outcome.kind === "refused");
  assert.equal(outcome.epoch, 1);
  assert.equal(outcome.refusal.reason, "already_started");
  assert.equal(spy.calls(), 0);
});

test("a store directory without a manifest is manifest_missing for run and status", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  await mkdir(store);
  const spy = spyObserve(observed());
  const ran = expectIncompatible(
    await runHost(hostOptions(store), { type: "run", observe: spy.observe }),
    "manifest_missing",
  );
  assert.deepEqual(ran.mismatch, { field: "manifest_missing", expected: null, found: null });
  assert.equal(ran.epoch, 1);
  assert.equal(
    expectIncompatible(await readStatus(hostOptions(store)), "manifest_missing").epoch,
    2,
  );
  assert.equal(spy.calls(), 0);
});

test("a missing store directory is manifest_missing with no lock taken and nothing created", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const spy = spyObserve(observed());
  for (const outcome of [
    await runHost(hostOptions(store), { type: "run", observe: spy.observe }),
    await readStatus(hostOptions(store)),
  ]) {
    assert.deepEqual(outcome, {
      kind: "incompatible",
      epoch: null,
      mismatch: { field: "manifest_missing", expected: null, found: null },
    });
  }
  assert.equal(existsSync(store), false, "the store directory still does not exist");
  assert.equal(spy.calls(), 0);
});
