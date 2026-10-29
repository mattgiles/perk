// The persisted human decision and its reply at the host (docs/design/pi-durable-v2-foundations.md
// §7 the reply, §10 the host), over real temp git repos and SQLite stores. R1: reconcile opens one
// decision bound to the aggregate's subject, allowed actions and actor; nothing waits on it; a reply
// after the requesting task is terminal is accepted, creates exactly one conversation-owned
// continuation and returns its receipt at once, and the receipt is found later by the reply op id —
// over the fake program and over the native assignment. R2: a duplicate reply returns the same
// continuation, even after a later subject change or a cancellation; another payload is
// `duplicate_conflict` and records nothing.

import assert from "node:assert/strict";
import { test } from "node:test";
import { ROOT_CONVERSATION_ID } from "@earendil-works/pi-durable";
import { FIXTURE_REPORT_TASK_NAME } from "../durable/assignment.ts";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import { type BindingReceipt, lookupReceipt, operate } from "../durable/operate.ts";
import { readStatus, runHost } from "../host.ts";
import { FIXTURE_ACTIONS, FIXTURE_ACTOR, FIXTURE_DECISION_KIND } from "../kernel/fixture.ts";
import {
  aggregateOpId,
  cancelOpId,
  continuationOpId,
  observeOpId,
  openDecisionOpId,
  replyOpId,
} from "../kernel/identity.ts";
import type { KernelRecord } from "../kernel/records.ts";
import {
  assertSameRecords,
  cancelOp,
  decisionIdOf,
  E,
  expectApplied,
  ofType,
} from "../testing/binding.ts";
import {
  assertCompleted,
  assertNothingRecorded,
  belowHost,
  launchedTasks,
  recorded,
  recordsOf,
  replyVerb,
  storeTasks,
} from "../testing/decision.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectHostRefused,
  expectQuiescent,
  expectStatus,
  hostOptions,
  ownerEpochs,
  spyObserve,
} from "../testing/host.ts";
import { commitAll, treeOf, writeFiles } from "../testing/subject.ts";
import {
  assertScript,
  fixtureAttemptId,
  fixtureSubject,
  ROLES,
  reportCall,
  reportTypes,
  startNative,
} from "../testing/worker.ts";

function opIds(records: readonly KernelRecord[]): Set<string> {
  return new Set(records.map((record) => (record.type === "manifest" ? "manifest" : record.opId)));
}

/** The receipt's one continuation task id. */
function continuationTaskOf(receipt: BindingReceipt | null): number {
  assert.ok(receipt !== null, "the reply has a receipt");
  assert.equal(receipt.durable.length, 1, "one durable row");
  const [row] = receipt.durable;
  assert.ok(row !== undefined);
  return row.durableId;
}

/** The store holds exactly the continuation task `id`, completed. */
async function assertOnlyContinuation(store: string, id: number, message: string): Promise<void> {
  const tasks = await storeTasks(store, CONTINUATION_TASK_NAME);
  assert.deepEqual(
    tasks.map((task) => task.id),
    [id],
    `${message}: exactly one continuation task`,
  );
  assertCompleted(tasks[0], message);
}

test("R1: the decision is bound to the aggregate; a reply with no waiter after the requesting task is terminal creates one continuation", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { tree, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store);
  const started = expectQuiescent(await runHost(options, { type: "start", observe }));
  assert.equal(started.view.waitReason, "pending_decision");
  assert.equal(started.receipt, null, "start carries no receipt");

  // The pending decision is one record bound to the aggregate's subject, actions and actor.
  const d = decisionIdOf(tree);
  const records = started.view.records.records;
  assert.deepEqual(ofType(records, "decision"), [
    {
      type: "decision",
      opId: openDecisionOpId(d),
      decisionId: d,
      subjectDigest: tree,
      decisionKind: FIXTURE_DECISION_KIND,
      aggregateId: aggregateOpId(E, tree),
      allowedActions: [...FIXTURE_ACTIONS],
      actor: FIXTURE_ACTOR,
    },
  ]);
  const aggregates = ofType(records, "aggregate-outcome");
  assert.equal(aggregates.length, 1);
  assert.equal(aggregates[0]?.opId, aggregateOpId(E, tree));
  assert.equal(aggregates[0]?.subjectDigest, tree);
  assert.equal(aggregates[0]?.outcomeIds.length, 2);

  // Nothing waits on the decision: no owner, no live task, the requesting work terminal.
  assert.ok(
    (await ownerEpochs(store)).every((entry) => entry.released),
    "every epoch released",
  );
  const status = expectStatus(await readStatus(options));
  assert.deepEqual(status.view.inspection.tasks, [], "no live task");
  assert.equal(status.view.wake.active, false);
  assert.equal(status.view.waitReason, "pending_decision");
  const launched = await launchedTasks(store, status.view.records.durableMap);
  assert.equal(launched.length, 2, "both attempts launched");
  for (const task of launched) assertCompleted(task, `launched task ${task.id}`);

  // The reply: quiescent `completed` at a fresh epoch, its receipt returned at once.
  const priorEpochs = (await ownerEpochs(store)).length;
  const replied = expectQuiescent(await runHost(options, replyVerb(observe, d)));
  assert.equal(replied.epoch, priorEpochs + 1, "a fresh epoch");
  assert.equal(replied.view.waitReason, "completed");
  const continuationTask = continuationTaskOf(replied.receipt);
  assert.deepEqual(replied.receipt, {
    opId: replyOpId(d),
    record: {
      type: "reply",
      opId: replyOpId(d),
      decisionId: d,
      action: "approve",
      actor: FIXTURE_ACTOR,
    },
    continuation: { type: "continuation", opId: continuationOpId(d), decisionId: d },
    durable: [{ perkId: continuationOpId(d), durableKind: "task", durableId: continuationTask }],
  });

  // It recorded exactly its observation (seq 2, the same tree), the reply and the continuation.
  const before = opIds(records);
  const added = [...opIds(replied.view.records.records)].filter((id) => !before.has(id)).sort();
  assert.deepEqual(added, [observeOpId(E, 2), replyOpId(d), continuationOpId(d)].sort());
  const observation = ofType(replied.view.records.records, "observation").find(
    (record) => record.seq === 2,
  );
  assert.equal(observation?.tree, tree);

  // The continuation is conversation-owned on the execution conversation, background, and ran.
  const continuations = await storeTasks(store, CONTINUATION_TASK_NAME);
  assert.deepEqual(
    continuations.map((task) => task.id),
    [continuationTask],
  );
  const [continuation] = continuations;
  assert.ok(continuation !== undefined);
  assert.equal(continuation.owner, undefined, "owned by its conversation, never a task");
  assert.equal(continuation.conversationId, ROOT_CONVERSATION_ID);
  assert.equal(continuation.background, true);
  assertCompleted(continuation, "the continuation");

  // The receipt is found later by the reply op id.
  const later = await belowHost(t, options, ({ harness }) => lookupReceipt(harness, replyOpId(d)));
  assert.deepEqual(later, replied.receipt);
});

test("R1 (native): a reply after the native requesting tasks are terminal creates one continuation", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const native = await startNative(t, (tree) => ({ a: [reportCall(tree)], b: [reportCall(tree)] }));
  const { tree, store, script, reports } = native;
  const started = expectQuiescent(native.outcome);
  assert.equal(started.view.waitReason, "pending_decision");
  for (const role of ROLES) {
    assert.equal(
      started.view.endings.get(fixtureAttemptId(role, tree))?.end,
      "accepted",
      `role ${role}`,
    );
  }
  const requesting = await storeTasks(store, FIXTURE_REPORT_TASK_NAME);
  assert.equal(requesting.length, 2, "both requesting tasks");
  for (const task of requesting) assertCompleted(task, `requesting task ${task.id}`);

  const replied = expectQuiescent(
    await runHost(native.options, replyVerb(native.observe, decisionIdOf(tree))),
  );
  assert.equal(replied.view.waitReason, "completed");
  const continuationTask = continuationTaskOf(replied.receipt);
  await assertOnlyContinuation(store, continuationTask, "native");
  assertScript(script, { a: { leftover: 0 }, b: { leftover: 0 } });
  assert.deepEqual(reportTypes(reports), [], "no task_faulted or extension_error");
});

test("R2: a duplicate reply returns the same continuation, even after a subject change or a cancellation; another payload is duplicate_conflict", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { repo, tree, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store);
  expectQuiescent(await runHost(options, { type: "start", observe }));
  const d = decisionIdOf(tree);
  const first = expectQuiescent(await runHost(options, replyVerb(observe, d)));
  const receipt = first.receipt;
  const continuationTask = continuationTaskOf(receipt);
  const s1 = (await recordsOf(options)).records;
  await assertOnlyContinuation(store, continuationTask, "after the first reply");

  // The same reply again: the same receipt, nothing recorded — its observation included.
  const spy = spyObserve(observe);
  const again = expectQuiescent(await runHost(options, replyVerb(spy.observe, d)));
  assert.equal(spy.calls(), 1, "the duplicate observed once");
  assert.equal(again.view.waitReason, "completed");
  assert.deepEqual(again.receipt, receipt);
  assertSameRecords((await recordsOf(options)).records, s1, "a duplicate records nothing");
  assert.ok(!opIds(again.view.records.records).has(observeOpId(E, 3)), "no third observation");
  await assertOnlyContinuation(store, continuationTask, "after a duplicate");

  // After a subject change: still the same receipt, still nothing recorded.
  writeFiles(repo, { "a.txt": "changed\n" });
  assert.notEqual(treeOf(repo, commitAll(repo, "c2")), tree);
  const changed = expectQuiescent(await runHost(options, replyVerb(observe, d)));
  assert.equal(changed.view.waitReason, "completed");
  assert.deepEqual(changed.receipt, receipt);
  assertSameRecords((await recordsOf(options)).records, s1, "after a subject change");
  await assertOnlyContinuation(store, continuationTask, "after a subject change");

  // After a cancellation another process committed: still the same receipt.
  expectApplied(await belowHost(t, options, (target) => operate(target, cancelOp())));
  const s2 = (await recordsOf(options)).records;
  const cancellations = ofType(s2, "cancellation");
  assert.deepEqual(
    cancellations.map((record) => record.opId),
    [cancelOpId(E)],
  );
  assertSameRecords(s2, [...s1, ...cancellations], "the cancellation is the only addition");
  const cancelled = expectQuiescent(await runHost(options, replyVerb(observe, d)));
  assert.deepEqual(cancelled.receipt, receipt);
  assertSameRecords((await recordsOf(options)).records, s2, "after a cancellation");
  await assertOnlyContinuation(store, continuationTask, "after a cancellation");

  // Another payload under the same reply op id conflicts and records nothing.
  const before = await recorded(options);
  expectHostRefused(
    await runHost(options, replyVerb(observe, d, { action: "reject" })),
    "duplicate_conflict",
  );
  expectHostRefused(
    await runHost(options, replyVerb(observe, d, { actor: "human:other" })),
    "duplicate_conflict",
  );
  await assertNothingRecorded(options, before, "a conflicting payload");
  await assertOnlyContinuation(store, continuationTask, "after the conflicts");
});
