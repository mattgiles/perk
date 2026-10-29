// The binding's acceptance proof B1 and its identity mappings (docs/design/pi-durable-v2-foundations.md
// §6 record keys, identity mappings and receipt lookup; §7 the binding and task ownership). Over
// SQLite with the fake assignment task: `start` admits two assignments and launches their attempts,
// each fake accepts once, the aggregate and the decision follow, host-level duplicates replay or
// conflict without reaching storage, and a reopen finds the same records. Every Durable object the
// binding creates is mapped to its Perk id in the very storage batch that creates it.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { StorageWrite } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import { lookupReceipt, operate } from "../durable/operate.ts";
import { readRecords } from "../durable/records.ts";
import { acceptReportOpId, continuationOpId, launchOpId, submitOpId } from "../kernel/identity.ts";
import {
  acceptOp,
  assertSameRecords,
  attemptIdOf,
  decisionIdOf,
  expectApplied,
  expectRefused,
  expectReplayed,
  FAKE_ASSIGNMENT_NAME,
  fakeReport,
  installBinding,
  modelChain,
  ofType,
  openBinding,
  policyA,
  quiesce,
  replyOp,
  startOp,
  T1,
  tasksOfKind,
} from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, fauxSetup, recording, sqlitePath } from "../testing/durable.ts";

const ATTEMPTS = [attemptIdOf("a", T1), attemptIdOf("b", T1)];

/** The task records a batch writes. */
function taskWrites(batch: readonly StorageWrite[]) {
  return batch.flatMap((write) => (write.type === "task" ? [write.value] : []));
}

/** The durable-map rows a batch creates, by key. */
function rowWrites(batch: readonly StorageWrite[]): Map<string | undefined, unknown> {
  return new Map(
    batch.flatMap((write) =>
      write.type === "document.create" && write.record.kind === "perk.v2.durable-map"
        ? [[write.record.key, write.content.value] as const]
        : [],
    ),
  );
}

test("B1: two assignments, each accepted exactly once", { timeout: CASE_TIMEOUT_MS }, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = recording(await openNodeSqliteStorage(path));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  const { harness } = opened;

  // start: two admissions and their attempts, launched in the same commit.
  const start = expectApplied(await operate(target, startOp()));
  assert.deepEqual(
    start.actions.map((action) => action.type),
    ["admit", "admit", "start-attempt", "start-attempt"],
  );
  assertSameRecords((await readRecords(harness)).records, modelChain([startOp()]), "after start");

  // Each attempt's launch row names a fake task: on the root conversation, background, unowned.
  const { durableMap } = await readRecords(harness);
  const launched = ATTEMPTS.map((attempt) => {
    const row = durableMap.get(launchOpId(attempt));
    assert.ok(row !== undefined, `${attempt} has a launch row`);
    assert.equal(row.durableKind, "task");
    return row.durableId;
  });
  const fakes = await tasksOfKind(harness, FAKE_ASSIGNMENT_NAME);
  assert.deepEqual(fakes.map((task) => task.id).sort(), [...launched].sort());
  for (const task of fakes) {
    assert.equal(task.conversationId, opened.root.id, "on the execution conversation");
    assert.equal(task.background, true, "background");
    assert.equal(task.owner, undefined, "conversation-owned, no owner task");
  }

  // Run to quiescence: each fake accepts once; the aggregate and the decision follow.
  await quiesce(harness);
  const { records } = await readRecords(harness);
  const assignments = ofType(records, "assignment");
  assert.deepEqual(assignments.map((record) => record.role).sort(), ["a", "b"]);
  assert.ok(
    assignments.every((record) => record.subject.digest === T1),
    "both over T1",
  );
  assert.deepEqual(
    ofType(records, "attempt")
      .map((record) => record.attemptId)
      .sort(),
    [...ATTEMPTS].sort(),
  );
  const outcomes = ofType(records, "report-outcome");
  assert.deepEqual(
    outcomes.map((record) => record.attemptId).sort(),
    [...ATTEMPTS].sort(),
    "one outcome per attempt",
  );
  const aggregates = ofType(records, "aggregate-outcome");
  assert.equal(aggregates.length, 1);
  assert.deepEqual(
    [...(aggregates[0]?.outcomeIds ?? [])].sort(),
    ATTEMPTS.map(acceptReportOpId).sort(),
    "the aggregate names both outcomes",
  );
  assert.equal(ofType(records, "decision").length, 1);
  assertSameRecords(
    records,
    modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1)]),
    "the a-first model chain",
  );
  assertSameRecords(
    records,
    modelChain([startOp(), acceptOp("b", T1), acceptOp("a", T1)]),
    "the b-first model chain",
  );
  for (const task of await tasksOfKind(harness, FAKE_ASSIGNMENT_NAME)) {
    assert.equal(task.state.status, "terminal");
    assert.equal(task.state.outcome?.status, "completed");
  }

  // Host-level duplicates: an equal payload replays, another conflicts; neither reaches storage.
  const before = store.batches.length;
  const replay = expectReplayed(await operate(target, acceptOp("a", T1)));
  assert.deepEqual(
    replay.receipt.record,
    outcomes.find((record) => record.attemptId === ATTEMPTS[0]),
  );
  expectRefused(
    await operate(
      target,
      acceptOp("a", T1, { report: { ...fakeReport(T1), summary: "another summary" } }),
    ),
    "duplicate_conflict",
  );
  assert.equal(store.batches.length, before, "neither duplicate reached storage");
  assertSameRecords((await readRecords(harness)).records, records, "duplicates record nothing");

  // Close and reopen: the same records; resuming re-runs nothing.
  await opened.dispose();
  const reopened = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  const again = reopened.opened.harness;
  assertSameRecords((await readRecords(again)).records, records, "after reopen");
  await quiesce(again);
  assertSameRecords((await readRecords(again)).records, records, "after reopen and resume");
  assert.equal(ofType((await readRecords(again)).records, "report-outcome").length, 2);
  for (const task of await tasksOfKind(again, FAKE_ASSIGNMENT_NAME)) {
    assert.equal(task.state.status, "terminal");
    assert.equal(task.state.outcome?.status, "completed");
  }
});

test("every Durable object is mapped in the commit that creates it", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = recording(await openNodeSqliteStorage(path));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  const { harness } = opened;

  // The start batch carries both fake tasks and each attempt's launch row naming its own task.
  const before = store.batches.length;
  expectApplied(await operate(target, startOp()));
  assert.equal(store.batches.length, before + 1, "start is one storage batch");
  const startBatch = store.batches[before] ?? [];
  const fakes = taskWrites(startBatch);
  assert.deepEqual(
    fakes.map((task) => task.kind),
    [FAKE_ASSIGNMENT_NAME, FAKE_ASSIGNMENT_NAME],
  );
  const launchRows = rowWrites(startBatch);
  assert.deepEqual([...launchRows.keys()].sort(), ATTEMPTS.map(launchOpId).sort());
  for (const task of fakes) {
    const attemptId: unknown = Reflect.get(Object(task.input), "attemptId");
    assert.equal(typeof attemptId, "string");
    assert.deepEqual(
      launchRows.get(launchOpId(String(attemptId))),
      { durableKind: "task", durableId: task.id },
      `the launch row of ${String(attemptId)} names its own task`,
    );
  }
  const attemptReceipt = await lookupReceipt(harness, submitOpId(ATTEMPTS[0] ?? ""));
  assert.deepEqual(attemptReceipt?.durable, [
    {
      perkId: launchOpId(ATTEMPTS[0] ?? ""),
      durableKind: "task",
      durableId: fakes.find((task) => Reflect.get(Object(task.input), "attemptId") === ATTEMPTS[0])
        ?.id,
    },
  ]);

  // The reply batch carries the continuation task and its row; the receipt names it.
  await quiesce(harness);
  const replyAt = store.batches.length;
  const reply = expectApplied(await operate(target, replyOp(T1)));
  const replyBatch = store.batches[replyAt] ?? [];
  const continuations = taskWrites(replyBatch).filter(
    (task) => task.kind === CONTINUATION_TASK_NAME,
  );
  assert.equal(continuations.length, 1, "one continuation task in the reply batch");
  const [continuation] = continuations;
  assert.ok(continuation !== undefined);
  assert.equal(continuation.conversationId, opened.root.id, "on the execution conversation");
  assert.equal(continuation.background, true, "background");
  assert.equal(continuation.owner, undefined, "conversation-owned, no owner task");
  const key = continuationOpId(decisionIdOf(T1));
  assert.deepEqual(rowWrites(replyBatch).get(key), {
    durableKind: "task",
    durableId: continuation.id,
  });
  assert.deepEqual(reply.receipt?.durable, [
    { perkId: key, durableKind: "task", durableId: continuation.id },
  ]);
});
