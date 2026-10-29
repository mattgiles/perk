// R4 — a reply whose observation fails is `observation_failed` and records nothing, and the gate
// runs before a reply observes (docs/design/pi-durable-v2-foundations.md §7 the reply, §8, §10).
// Over a real temp git repo whose tracked ref is deleted and restored: the failed reply records no
// observation and no continuation; once the ref resolves again the reply is applied. Observation
// precedes receipt lookup, so a duplicate reply whose observation fails is `observation_failed` too
// — its receipt stays findable below the host, and an equal reply that observes replays it.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { test } from "node:test";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import { lookupReceipt } from "../durable/operate.ts";
import { readStatus, runHost } from "../host.ts";
import { replyOpId } from "../kernel/identity.ts";
import { gitObserver } from "../subject/observe.ts";
import { decisionIdOf, REF, T1 } from "../testing/binding.ts";
import {
  assertNothingRecorded,
  belowHost,
  recorded,
  replyVerb,
  storeTasks,
} from "../testing/decision.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectIncompatible,
  expectObservationFailed,
  expectQuiescent,
  expectStatus,
  fakeProgram,
  hostOptions,
  observed,
  ownerEpochs,
  spyObserve,
  storeIn,
} from "../testing/host.ts";
import {
  commitAll,
  fixtureGit,
  gitRepo,
  subjectStore,
  treeOf,
  writeFiles,
} from "../testing/subject.ts";
import { SUBJECT_FILES } from "../testing/worker.ts";

test("R4: a reply whose observation fails is observation_failed and records nothing; observation precedes receipt lookup", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const repo = await gitRepo(t);
  writeFiles(repo, SUBJECT_FILES);
  const c1 = commitAll(repo, "c1");
  const tree = treeOf(repo, c1);
  const store = await subjectStore(t);
  const options = hostOptions(store);
  const observe = gitObserver({ storeDir: store, repo, ref: REF });
  const d = decisionIdOf(tree);
  const started = expectQuiescent(await runHost(options, { type: "start", observe }));
  assert.equal(started.view.waitReason, "pending_decision");

  // The tracked ref is gone: the reply fails before its commit, at the run's own epoch.
  const before = await recorded(options);
  fixtureGit(repo, ["update-ref", "-d", REF]);
  const failed = await runHost(options, replyVerb(observe, d));
  assert.match(expectObservationFailed(failed), /does not resolve to a commit/);
  const latest = (await ownerEpochs(store)).at(-1);
  assert.ok(failed.kind === "observation_failed" && failed.epoch === latest?.epoch);
  await assertNothingRecorded(options, before, "a failed observation");
  assert.deepEqual(before.continuations, [], "no continuation task");
  assert.equal(expectStatus(await readStatus(options)).view.waitReason, "pending_decision");

  // Restored, the same reply is applied.
  fixtureGit(repo, ["update-ref", REF, c1]);
  const applied = expectQuiescent(await runHost(options, replyVerb(observe, d)));
  assert.equal(applied.view.waitReason, "completed");
  const receipt = applied.receipt;
  assert.ok(receipt !== null);

  // Deleted again, the duplicate observes first and fails; its receipt is still findable.
  const recordedOnce = await recorded(options);
  assert.equal(recordedOnce.continuations.length, 1);
  fixtureGit(repo, ["update-ref", "-d", REF]);
  assert.match(
    expectObservationFailed(await runHost(options, replyVerb(observe, d))),
    /does not resolve to a commit/,
  );
  await assertNothingRecorded(options, recordedOnce, "a duplicate whose observation failed");
  assert.deepEqual(
    await belowHost(t, options, ({ harness }) => lookupReceipt(harness, replyOpId(d))),
    receipt,
  );

  // Restored again, an equal reply replays it.
  fixtureGit(repo, ["update-ref", REF, c1]);
  const replayed = expectQuiescent(await runHost(options, replyVerb(observe, d)));
  assert.deepEqual(replayed.receipt, receipt);
  await assertNothingRecorded(options, recordedOnce, "the replay");
  assert.equal((await storeTasks(store, CONTINUATION_TASK_NAME)).length, 1);
});

test("the gate runs before a reply observes: a missing store directory", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const spy = spyObserve(observed());
  assert.deepEqual(await runHost(hostOptions(store), replyVerb(spy.observe, decisionIdOf(T1))), {
    kind: "incompatible",
    epoch: null,
    mismatch: { field: "manifest_missing", expected: null, found: null },
  });
  assert.equal(spy.calls(), 0, "never observed");
  assert.equal(existsSync(store), false, "the store directory is not created");
});

test("the gate runs before a reply observes: a mismatched manifest", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  expectQuiescent(await runHost(hostOptions(store), { type: "start", observe: observed() }));
  const spy = spyObserve(observed());
  expectIncompatible(
    await runHost(
      hostOptions(store, fakeProgram({ policyVersion: 2 })),
      replyVerb(spy.observe, decisionIdOf(T1)),
    ),
    "policyVersion",
  );
  assert.equal(spy.calls(), 0, "never observed");
});
