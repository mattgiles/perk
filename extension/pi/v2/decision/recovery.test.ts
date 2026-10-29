// R5 — a reply whose storage commit landed but whose acknowledgement was lost
// (docs/design/pi-durable-v2-foundations.md §7 the reply, §9 uncertain): the host reports
// `uncertain` and releases its epoch; reopening finds the receipt by the reply op id before anything
// resumes, with exactly one continuation task that has not run; the retry replays that receipt and
// resumes, so exactly that one continuation runs. The loss is injected at the reply's own batch,
// never "the next commit" — `root()` commits too — and the found receipt proves the targeting.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import { lookupReceipt } from "../durable/operate.ts";
import { runHost } from "../host.ts";
import { continuationOpId, observeOpId, replyOpId } from "../kernel/identity.ts";
import { decisionIdOf, E, ofType } from "../testing/binding.ts";
import {
  assertCompleted,
  belowHost,
  replyLands,
  replyVerb,
  storeTasks,
} from "../testing/decision.ts";
import { acknowledgementLostWhen, CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectHostRefused,
  expectQuiescent,
  fakeProgram,
  hostOptions,
  ownerEpochs,
} from "../testing/host.ts";
import { fixtureSubject } from "../testing/worker.ts";

test("R5: after storage success and a lost acknowledgement, reopening finds the receipt and exactly one continuation runs", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { tree, store, observe } = await fixtureSubject(t);
  const options = hostOptions(store);
  const started = expectQuiescent(await runHost(options, { type: "start", observe }));
  assert.equal(started.view.waitReason, "pending_decision");
  const d = decisionIdOf(tree);

  // The reply's own batch lands, then its acknowledgement is lost.
  const lost = new Error("acknowledgement lost");
  const proxies: { fired(): boolean }[] = [];
  const lossy = hostOptions(store, fakeProgram(), {
    openStorage: async (path) => {
      const proxy = acknowledgementLostWhen(await openNodeSqliteStorage(path), replyLands(d), lost);
      proxies.push(proxy);
      return proxy.storage;
    },
  });
  const outcome = await runHost(lossy, replyVerb(observe, d));
  assert.ok(outcome.kind === "uncertain", `uncertain, not ${outcome.kind}`);
  assert.equal(outcome.error, lost);
  assert.deepEqual(
    proxies.map((proxy) => proxy.fired()),
    [true],
    "the reply's batch landed",
  );
  assert.ok(
    (await ownerEpochs(store)).every((entry) => entry.released),
    "every epoch released",
  );

  // Reopened below the host, before any resume: the receipt by reply op id, one unrun continuation.
  const found = await belowHost(t, options, ({ harness }) => lookupReceipt(harness, replyOpId(d)));
  assert.ok(found !== null, "the reply's receipt is recorded");
  assert.equal(found.record.type, "reply");
  assert.equal(found.record.opId, replyOpId(d));
  assert.equal(found.continuation?.opId, continuationOpId(d));
  assert.equal(found.durable.length, 1);
  const [row] = found.durable;
  assert.ok(row !== undefined);
  assert.deepEqual(row, {
    perkId: continuationOpId(d),
    durableKind: "task",
    durableId: row.durableId,
  });
  const continuationTask = row.durableId;
  const unrun = await storeTasks(store, CONTINUATION_TASK_NAME);
  assert.deepEqual(
    unrun.map((task) => task.id),
    [continuationTask],
  );
  assert.notEqual(unrun[0]?.state.status, "terminal", "the continuation has not run");

  // The retry replays the receipt and resumes: the one continuation runs, nothing is re-recorded.
  const retried = expectQuiescent(await runHost(options, replyVerb(observe, d)));
  assert.equal(retried.view.waitReason, "completed");
  assert.deepEqual(retried.receipt, found);
  const records = retried.view.records.records;
  assert.deepEqual(
    ofType(records, "observation").map((record) => record.opId),
    [observeOpId(E, 1), observeOpId(E, 2)],
    "the lost commit's observation, once; no third",
  );
  assert.equal(ofType(records, "reply").length, 1);
  assert.deepEqual(
    ofType(records, "continuation").map((record) => record.opId),
    [continuationOpId(d)],
  );
  const ran = await storeTasks(store, CONTINUATION_TASK_NAME);
  assert.deepEqual(
    ran.map((task) => task.id),
    [continuationTask],
  );
  assertCompleted(ran[0], "the continuation");

  expectHostRefused(
    await runHost(options, replyVerb(observe, d, { action: "reject" })),
    "duplicate_conflict",
  );
  const final = expectQuiescent(await runHost(options, { type: "run", observe }));
  assert.equal(final.view.waitReason, "completed");
  assert.deepEqual(
    (await storeTasks(store, CONTINUATION_TASK_NAME)).map((task) => task.id),
    [continuationTask],
  );
});
