// Durable characterization — P8 (ownership before open; compatibility before resume; residence is
// policy), docs/design/pi-durable-v2-foundations.md §3 P8 and §10 (the host lifecycle). Opening a
// Harness schedules nothing until `resume()`, so the host can gate work between open and resume; a
// task cut off by crashes is parked at the restart limit where `inspect()` and `wake()` show it;
// and a clean close counts no restart.
//
// Upstream evidence (packages/durable at the mirrored 1.4.0 pin):
// src/harness/scheduler.ts::TaskScheduler.open/resume/wake/inspect/retry;
// test/harness-inspect.test.ts::"derives every live task's state without running task code";
// test/harness-blocked.test.ts::"parks a task cut off restartLimit times in a row, shows why, and
// runs it again on retryTask()" and ::"counts no restart for a task a close stopped".

import assert from "node:assert/strict";
import { test } from "node:test";
import { defineTask, type TaskId } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  aborted,
  CASE_TIMEOUT_MS,
  completed,
  context,
  crashable,
  fauxSetup,
  flush,
  installTasks,
  type Opened,
  open,
  sqlitePath,
  waitFor,
} from "../testing/durable.ts";

/** A task that counts its runs and completes at once. */
function probe(state: { runs: number }) {
  return defineTask<null, { phase: "run" }, null>({
    name: "perk.characterization.probe",
    version: 1,
    initial: () => ({ phase: "run" }),
    phases: {
      run: async (_task, runtime, phaseContext) => {
        state.runs++;
        await runtime.commit(() => completed(null), phaseContext);
      },
    },
    abort: async () => {},
  });
}

/** A task that blocks in its phase while `crashing` — as one killed every time would — and completes otherwise. */
function crashLoop(state: { crashing: boolean; started: number }) {
  return defineTask<null, { phase: "run" }, null>({
    name: "test.crash-loop",
    version: 1,
    initial: () => ({ phase: "run" }),
    phases: {
      run: async (_task, runtime, phaseContext) => {
        state.started++;
        if (state.crashing) await aborted(runtime.signal).catch(() => {});
        else await runtime.commit(() => completed(null), phaseContext);
      },
    },
    abort: async () => {},
  });
}

/** The scheduler's view of one task in `inspect()`. */
async function inspected(opened: Opened, id: TaskId) {
  const inspection = await opened.harness.inspect(context);
  return {
    scheduling: inspection.scheduling,
    state: inspection.tasks.find((task) => task.record.id === id)?.state,
  };
}

test("D1 (P8): opening does not schedule work until resume()", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const state = { runs: 0 };
  const Probe = probe(state);
  const setup = fauxSetup();
  installTasks(setup, "probe", [Probe]);

  const first = await open(t, await openNodeSqliteStorage(path), setup);
  const id = await first.root.commit(
    (tx) => tx.createTask(Probe, null, { ownership: { kind: "conversation" } }),
    context,
  );
  for (let turn = 0; turn < 3; turn++) await flush();
  assert.equal(state.runs, 0, "a committed task does not run on a Harness never resumed");
  const before = await inspected(first, id);
  assert.equal(before.scheduling, "paused");
  assert.equal(before.state?.kind, "ready", "the task is ready: only scheduling holds it");
  await first.dispose();

  // Reopened over the same store: still nothing runs until resume().
  const second = await open(t, await openNodeSqliteStorage(path), setup);
  assert.equal((await second.harness.getTask(id, context))?.state.status, "pending");
  for (let turn = 0; turn < 3; turn++) await flush();
  assert.equal(state.runs, 0, "opening over a store with pending work runs none of it");
  assert.equal((await inspected(second, id)).scheduling, "paused");

  // The positive control: the same task runs once scheduling is enabled.
  second.harness.resume();
  const settled = await second.harness.waitForTask(id, context);
  assert.equal(settled.state.outcome.status, "completed");
  assert.equal(state.runs, 1);
});

test("D10 (P8): restart-limit parking shows in inspect() and wake()", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const state = { crashing: true, started: 0 };
  const Loop = crashLoop(state);
  const setup = fauxSetup();
  installTasks(setup, "loop", [Loop]);
  const settings = { restartLimit: 2 };

  const openCrashable = async () => {
    const store = crashable(t, await openNodeSqliteStorage(path));
    return { store, opened: await open(t, store.storage, setup, { settings }) };
  };
  let current = await openCrashable();
  const root = current.opened.root;
  const id = await root.commit(
    (tx) => tx.createTask(Loop, null, { ownership: { kind: "conversation" } }),
    context,
  );

  // Each cycle runs the phase and crashes the process under it (a close would not count).
  for (let run = 1; run <= 2; run++) {
    current.opened.harness.resume();
    await waitFor(() => state.started === run);
    current.store.crash();
    current.opened.abandon();
    current = await openCrashable();
    const { harness } = current.opened;
    if (run === 1) {
      // One below the limit: counted, not parked.
      assert.equal((await harness.getTask(id, context))?.restarts, 1);
      assert.deepEqual((await inspected(current.opened, id)).state, {
        kind: "ready",
        migrates: false,
      });
      assert.deepEqual(
        setup.infos.filter((info) => info.type === "task_parked"),
        [],
      );
    }
  }

  const { harness } = current.opened;
  assert.equal((await harness.getTask(id, context))?.restarts, 2);
  assert.deepEqual(
    setup.infos.filter((info) => info.type === "task_parked"),
    [
      {
        type: "task_parked",
        task: { id, kind: "test.crash-loop", conversationId: root.id },
        extension: "loop",
      },
    ],
  );
  assert.deepEqual((await inspected(current.opened, id)).state, {
    kind: "blocked",
    reason: "restart_limit",
  });
  // Parked work needs no process: nothing is active.
  await waitFor(() => !harness.wake().active);
  assert.deepEqual(harness.wake(), { active: false });
  harness.resume();
  for (let turn = 0; turn < 5; turn++) await flush();
  assert.equal(state.started, 2, "a scheduling pass leaves the parked task out");

  state.crashing = false;
  await harness.retryTask(id, context);
  assert.equal((await harness.waitForTask(id, context)).state.outcome.status, "completed");
  assert.equal(state.started, 3);
});

test("D10c (P8): a clean close() counts no restart", { timeout: CASE_TIMEOUT_MS }, async (t) => {
  const path = await sqlitePath(t);
  const state = { crashing: true, started: 0 };
  const Loop = crashLoop(state);
  const setup = fauxSetup();
  installTasks(setup, "loop", [Loop]);
  const settings = { restartLimit: 1 };

  const first = await open(t, await openNodeSqliteStorage(path), setup, { settings });
  const id = await first.root.commit(
    (tx) => tx.createTask(Loop, null, { ownership: { kind: "conversation" } }),
    context,
  );
  first.harness.resume();
  await waitFor(() => state.started === 1);
  await first.dispose();

  const second = await open(t, await openNodeSqliteStorage(path), setup, { settings });
  const record = await second.harness.getTask(id, context);
  assert.equal(record?.state.status, "pending");
  assert.equal(record?.restarts, undefined, "the close stopped the task without counting it");
  assert.notEqual((await inspected(second, id)).state?.kind, "blocked");
  state.crashing = false;
  assert.equal((await second.harness.waitForTask(id, context)).state.outcome.status, "completed");
});
