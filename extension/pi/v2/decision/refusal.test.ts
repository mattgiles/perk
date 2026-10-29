// R3 — a reply to a changed-subject, superseded or cancelled decision is refused with its typed
// reason, and so is one to a decision that does not exist (docs/design/pi-durable-v2-foundations.md
// §7 the reply, §8): over real temp git repos and SQLite stores, the refusal comes from the reply's
// one commit after its observation, and rolls that observation back with everything else — nothing
// is recorded and no continuation is created. A same-tree commit is not a changed subject.

import assert from "node:assert/strict";
import { test } from "node:test";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import { operate } from "../durable/operate.ts";
import { type HostOptions, type Observe, readStatus, runHost } from "../host.ts";
import type { RefusalReason } from "../kernel/refusal.ts";
import { cancelOp, decisionIdOf, expectApplied, ofType } from "../testing/binding.ts";
import {
  assertNothingRecorded,
  belowHost,
  recorded,
  replyVerb,
  storeTasks,
} from "../testing/decision.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectHostRefused,
  expectQuiescent,
  expectStatus,
  fakeProgram,
  hostOptions,
  ownerEpochs,
  spyObserve,
} from "../testing/host.ts";
import { commitAll, commitIndex, treeOf, writeFiles } from "../testing/subject.ts";
import { fixtureSubject, SUBJECT_FILES } from "../testing/worker.ts";

/**
 * Reply to `decisionId` and assert it is refused with `reason` at the run's own epoch, after
 * observing exactly once, recording nothing; the refusal's detail.
 */
async function refusedReply(
  options: HostOptions,
  observe: Observe,
  decisionId: string,
  reason: RefusalReason,
): Promise<string> {
  const before = await recorded(options);
  const spy = spyObserve(observe);
  const outcome = await runHost(options, replyVerb(spy.observe, decisionId));
  const detail = expectHostRefused(outcome, reason);
  assert.equal(spy.calls(), 1, `${reason}: refused by the commit, after observing once`);
  const latest = (await ownerEpochs(options.storeDir)).at(-1);
  assert.ok(outcome.kind === "refused" && outcome.epoch === latest?.epoch, "the run's own epoch");
  await assertNothingRecorded(options, before, `${reason}: nothing recorded`);
  return detail;
}

async function continuationIds(store: string): Promise<number[]> {
  return (await storeTasks(store, CONTINUATION_TASK_NAME)).map((task) => task.id);
}

test("R3 (stale_subject): a reply to a decision over a changed subject is refused and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { repo, tree: t1, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe }));
  writeFiles(repo, { "a.txt": "changed\n" });
  assert.notEqual(treeOf(repo, commitAll(repo, "c2")), t1);

  const detail = await refusedReply(options, observe, decisionIdOf(t1), "stale_subject");
  assert.match(detail, /not the observed subject/);
  assert.deepEqual(await continuationIds(store), []);
  // Status never observes: the latest recorded observation is still over `t1`.
  assert.equal(expectStatus(await readStatus(options)).view.waitReason, "pending_decision");
});

test("R3 (same tree): a reply after a commit that keeps the tree is applied", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { repo, tree: t1, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe }));
  assert.equal(treeOf(repo, commitIndex(repo, "c2, same tree")), t1);

  const replied = expectQuiescent(await runHost(options, replyVerb(observe, decisionIdOf(t1))));
  assert.equal(replied.view.waitReason, "completed");
  assert.notEqual(replied.receipt, null);
  assert.equal((await continuationIds(store)).length, 1);
});

test("R3 (superseded): a fresh, uncancelled decision is refused once the execution consumed another", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { repo, tree: t1, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe }));

  writeFiles(repo, { "a.txt": "changed\n" });
  const t2 = treeOf(repo, commitAll(repo, "c2"));
  assert.notEqual(t2, t1);
  const ran = expectQuiescent(await runHost(options, { type: "run", observe }));
  assert.equal(ran.view.waitReason, "pending_decision");
  assert.ok(
    ofType(ran.view.records.records, "decision").some((d) => d.decisionId === decisionIdOf(t2)),
    "a pending decision over t2",
  );
  const consumed = expectQuiescent(await runHost(options, replyVerb(observe, decisionIdOf(t2))));
  assert.equal(consumed.view.waitReason, "completed");
  const continuations = await continuationIds(store);
  assert.equal(continuations.length, 1);

  writeFiles(repo, SUBJECT_FILES);
  assert.equal(treeOf(repo, commitAll(repo, "c3, t1 again")), t1);
  const detail = await refusedReply(options, observe, decisionIdOf(t1), "superseded");
  assert.match(detail, /already consumed a decision/);
  assert.deepEqual(await continuationIds(store), continuations, "only t2's continuation");
});

test("R3 (cancelled): a reply after a cancellation is refused and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { tree: t1, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe }));
  expectApplied(await belowHost(t, options, (target) => operate(target, cancelOp())));

  await refusedReply(options, observe, decisionIdOf(t1), "cancelled");
  assert.deepEqual(await continuationIds(store), []);
  assert.equal(expectStatus(await readStatus(options)).view.waitReason, "cancelled");
});

test("R3 (unknown_decision): a reply naming no recorded decision is refused and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { tree: t1, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store, fakeProgram({ accept: false }));
  const started = expectQuiescent(await runHost(options, { type: "start", observe }));
  assert.equal(started.view.waitReason, "assignment_incomplete");
  assert.deepEqual(ofType(started.view.records.records, "aggregate-outcome"), []);
  assert.deepEqual(ofType(started.view.records.records, "decision"), []);

  await refusedReply(options, observe, decisionIdOf(t1), "unknown_decision");
  assert.deepEqual(await continuationIds(store), []);
});
