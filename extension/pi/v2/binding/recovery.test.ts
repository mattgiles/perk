// The binding's recovery proof B3 and receipt-first lookup (docs/design/pi-durable-v2-foundations.md
// §4 replay rule, §6 receipt lookup, §7 receipts, §9 uncertain). Over SQLite: a reply whose storage
// commit landed but whose acknowledgement was lost is `uncertain`; reopening finds its receipt by op
// id before anything resumes, with exactly one continuation, and the retry replays it. Receipt
// lookup precedes every freshness, cancellation and supersession check, immediately and after a
// reopen.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import { opKindOf } from "../durable/documents.ts";
import { lookupReceipt, operate } from "../durable/operate.ts";
import { readRecords } from "../durable/records.ts";
import { acceptReportOpId, cancelOpId, continuationOpId, replyOpId } from "../kernel/identity.ts";
import {
  acceptOp,
  attemptIdOf,
  C2,
  cancelOp,
  decisionIdOf,
  E,
  expectApplied,
  expectRefused,
  expectReplayed,
  expectUncertain,
  facts,
  installBinding,
  ofType,
  openBinding,
  policyA,
  quiesce,
  replyOp,
  startOp,
  T1,
  T2,
  tasksOfKind,
} from "../testing/binding.ts";
import { acknowledgementLost, CASE_TIMEOUT_MS, fauxSetup, sqlitePath } from "../testing/durable.ts";

const DECISION = decisionIdOf(T1);
const REPLY = replyOpId(DECISION);
const CONTINUATION = continuationOpId(DECISION);

test("B3: after storage success and a lost acknowledgement, reopening finds the receipt with one continuation", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = acknowledgementLost(await openNodeSqliteStorage(path));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  expectApplied(await operate(target, startOp()));
  await quiesce(opened.harness);

  // The reply's batch lands, then its acknowledgement is lost: uncertain, and the Harness fails.
  const lost = new Error("acknowledgement lost");
  store.armNextCommit(lost);
  assert.equal(
    expectUncertain(await operate(target, replyOp(T1))),
    lost,
    "the armed commit was the reply's",
  );
  assert.deepEqual(await opened.harness.closed, { reason: "failed", error: lost });

  // Reopen; before resuming, the receipt is found by op id with its one continuation row.
  const reopened = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  const { harness } = reopened.opened;
  const receipt = await lookupReceipt(harness, REPLY);
  assert.ok(receipt !== null, "the reply's receipt is recorded");
  assert.deepEqual(receipt.record, {
    type: "reply",
    opId: REPLY,
    decisionId: DECISION,
    action: "approve",
    actor: "human:cli",
  });
  assert.deepEqual(receipt.continuation, {
    type: "continuation",
    opId: CONTINUATION,
    decisionId: DECISION,
  });
  assert.equal(receipt.durable.length, 1);
  const [row] = receipt.durable;
  assert.ok(row !== undefined);
  assert.equal(row.perkId, CONTINUATION);
  assert.equal(row.durableKind, "task");
  const continuationTask = row.durableId;
  assert.deepEqual(
    (await tasksOfKind(harness, CONTINUATION_TASK_NAME)).map((task) => task.id),
    [continuationTask],
    "exactly the mapped continuation task exists",
  );
  const { durableMap } = await readRecords(harness);
  assert.deepEqual(
    [...durableMap.keys()].filter((key) => opKindOf(key) === "continuation"),
    [CONTINUATION],
    "exactly one continuation row",
  );

  // The retry replays the same continuation; another payload conflicts.
  const replay = expectReplayed(await operate(reopened.target, replyOp(T1)));
  assert.deepEqual(replay.receipt.durable, [
    { perkId: CONTINUATION, durableKind: "task", durableId: continuationTask },
  ]);
  expectRefused(
    await operate(reopened.target, replyOp(T1, { action: "reject" })),
    "duplicate_conflict",
  );

  // Resuming completes that continuation and creates no other; a step finds nothing to do.
  await quiesce(harness);
  const continuations = await tasksOfKind(harness, CONTINUATION_TASK_NAME);
  assert.deepEqual(
    continuations.map((task) => task.id),
    [continuationTask],
  );
  assert.equal(continuations[0]?.state.status, "terminal");
  assert.equal(continuations[0]?.state.outcome?.status, "completed");
  const step = expectApplied(await operate(reopened.target));
  assert.deepEqual(step.recorded, []);
  assert.deepEqual(step.actions, []);
});

test("receipt lookup precedes every other check, immediately and after a reopen", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const { opened, target } = await openBinding(
    t,
    await openNodeSqliteStorage(path),
    setup,
    installed,
  );
  expectApplied(await operate(target, startOp()));
  await quiesce(opened.harness);
  const reply = expectApplied(await operate(target, replyOp(T1)));
  const cancel = expectApplied(await operate(target, cancelOp()));
  await quiesce(opened.harness);
  const observations = ofType((await readRecords(opened.harness)).records, "observation").length;

  // A re-reply replays — not `cancelled`, not `superseded`, and not stale over a moved ref.
  const again = expectReplayed(await operate(target, replyOp(T1)));
  assert.deepEqual(again.receipt, reply.receipt);
  const moved = expectReplayed(await operate(target, replyOp(T1, { observation: facts(T2, C2) })));
  assert.deepEqual(moved.receipt, reply.receipt);
  assert.equal(
    ofType((await readRecords(opened.harness)).records, "observation").length,
    observations,
    "a replay records no observation",
  );
  const accepted = expectReplayed(await operate(target, acceptOp("a", T1)));
  assert.equal(accepted.receipt.opId, acceptReportOpId(attemptIdOf("a", T1)));

  // After a reopen, lookup returns the same receipts.
  await opened.dispose();
  const reopened = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  const { harness } = reopened.opened;
  assert.deepEqual(await lookupReceipt(harness, REPLY), reply.receipt);
  assert.deepEqual(await lookupReceipt(harness, cancelOpId(E)), cancel.receipt);
  assert.deepEqual(
    await lookupReceipt(harness, acceptReportOpId(attemptIdOf("a", T1))),
    accepted.receipt,
  );
  assert.equal(await lookupReceipt(harness, `${REPLY}-garbage`), null, "a garbage id misses");
});
