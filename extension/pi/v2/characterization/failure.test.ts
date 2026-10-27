// Durable characterization — P9 (storage failure means uncertainty; application failure means
// refusal), docs/design/pi-durable-v2-foundations.md §3 P9 and §9 (the outcome taxonomy). A
// failed storage commit ends the whole Harness — the caller gets the storage error itself and every
// later call fails with `SessionFailed` — while a commit callback that throws refuses only that
// commit and leaves the Harness serving the next one.
//
// Upstream evidence (packages/durable at the mirrored 1.4.0 pin): src/errors.ts::SessionFailed;
// src/session/session.ts::SessionImpl.#runCommit;
// test/harness-storage-failure.test.ts::"ends everything with the first error…" and ::"rejects the
// Harness's own calls with SessionFailed after a failure";
// test/session-documents.test.ts::"aborts every change when the callback fails".

import assert from "node:assert/strict";
import { test } from "node:test";
import { defineDoc, defineTask, SessionFailed } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  CASE_TIMEOUT_MS,
  CountingStorage,
  completed,
  context,
  failing,
  fauxSetup,
  flush,
  installTasks,
  open,
  sqlitePath,
} from "../testing/durable.ts";

const Probe = defineDoc<{ value: string }>({
  kind: "perk.probe",
  version: 1,
  scope: "session",
  initial: () => ({ value: "" }),
  checkpointWhen: () => true,
});

const Work = defineTask<null, { phase: "run" }, null>({
  name: "perk.characterization.work",
  version: 1,
  initial: () => ({ phase: "run" }),
  phases: {
    run: async (_task, runtime, phaseContext) => {
      await runtime.commit(() => completed(null), phaseContext);
    },
  },
  abort: async () => {},
});

/** Assert that `promise` rejects with a `SessionFailed` carrying `cause`. */
async function rejectsSessionFailed(promise: Promise<unknown>, cause: Error): Promise<void> {
  await assert.rejects(promise, (error: unknown) => {
    assert.ok(error instanceof SessionFailed, "the rejection is a SessionFailed");
    assert.equal(error.cause, cause, "SessionFailed carries the storage error as its cause");
    return true;
  });
}

test("D2 (P9): a storage commit failure closes the Harness, and later calls fail", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const { storage, armNextCommit } = failing(await openNodeSqliteStorage(path));
  // Unarmed while opening: root creation is itself a commit, and it must succeed.
  const { harness, root } = await open(t, storage, setup);

  // Baseline: an ordinary commit lands.
  await root.commit(async (tx) => {
    (await tx.doc(Probe)).value = "baseline";
  }, context);
  assert.deepEqual(await harness.snapshot(Probe, context), { value: "baseline" });

  // The next storage commit fails: the caller gets that very error.
  const thrown = new Error("disk gone");
  armNextCommit(thrown);
  let caught: unknown;
  try {
    await root.commit(async (tx) => {
      (await tx.doc(Probe)).value = "lost";
    }, context);
  } catch (error) {
    caught = error;
  }
  assert.equal(caught, thrown, "the failed commit rejects with the storage error itself");
  assert.deepEqual(await harness.closed, { reason: "failed", error: thrown });
  assert.deepEqual(setup.infos, [{ type: "session_failed" }]);
  assert.equal(setup.reports.length, 1);
  assert.equal(setup.reports[0], thrown);

  // Every later call fails with SessionFailed.
  await rejectsSessionFailed(
    root.commit(() => undefined, context),
    thrown,
  );
  await rejectsSessionFailed(
    harness.createConversation({ ownership: { kind: "ownerless" } }, context),
    thrown,
  );

  // A fresh Harness over the same store sees the baseline: the attempted write never landed.
  const reopened = await open(t, await openNodeSqliteStorage(path), setup);
  assert.deepEqual(await reopened.harness.snapshot(Probe, context), { value: "baseline" });
});

test("D3 (P9): a commit callback that throws rolls back only that commit; the Harness accepts the next", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const storage = new CountingStorage();
  const setup = fauxSetup();
  installTasks(setup, "work", [Work]);
  const { harness, root } = await open(t, storage, setup);
  const before = storage.commits.length;

  const thrown = new Error("callback refused");
  let caught: unknown;
  try {
    await root.commit(async (tx) => {
      (await tx.doc(Probe)).value = "lost";
      await tx.createTask(Work, null, { ownership: { kind: "conversation" } });
      throw thrown;
    }, context);
  } catch (error) {
    caught = error;
  }
  assert.equal(caught, thrown, "the commit rejects with the callback's own error");
  assert.equal(storage.commits.length, before, "nothing reached storage");
  assert.equal(await harness.snapshot(Probe, context), undefined, "the doc edit rolled back");
  const tasks = await harness.commit(
    (tx) => tx.scanTasks({ conversationId: root.id }, 20),
    context,
  );
  assert.deepEqual(tasks.items, [], "the task creation rolled back");
  const state = await Promise.race([
    harness.closed.then(() => "closed"),
    flush().then(() => "open"),
  ]);
  assert.equal(state, "open", "the Harness did not close");

  // The next commit is accepted.
  const accepted = storage.commits.length;
  await root.commit(async (tx) => {
    (await tx.doc(Probe)).value = "kept";
  }, context);
  assert.deepEqual(await harness.snapshot(Probe, context), { value: "kept" });
  assert.equal(storage.commits.length, accepted + 1);
});
