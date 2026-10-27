// Durable characterization — P1 (one advancement owner) and P5 (three tiers, one writer each),
// docs/design/pi-durable-v2-foundations.md §3 P1/P5, §6 (record tiers, its binding constraint) and
// §7 (the write contract). One `Tx` writes conversation-owned tasks and session doc-family records
// in a single atomic storage batch; a family member is get-or-create by key (no enumeration, the
// seed of an existing member is ignored); and a task created from a task's commit runs only after
// that commit has landed.
//
// Upstream evidence (packages/durable at the mirrored 1.4.0 pin): src/types.ts::Tx (`createTask`,
// `doc(token, key, seed)`), src/documents.ts::defineDocFamily, src/types.ts::TaskRuntime.commit;
// test/harness-tasks.test.ts::"commits results with entries atomically";
// test/session-documents.test.ts::"uses the first family seed and ignores seeds for existing
// members"; test/examples/24-child-tasks.ts (no upstream test isolates the D5 ordering).

import assert from "node:assert/strict";
import { test } from "node:test";
import { defineDocFamily, defineTask } from "@earendil-works/pi-durable";
import {
  CASE_TIMEOUT_MS,
  CountingStorage,
  completed,
  context,
  fauxSetup,
  installTasks,
  open,
  waitFor,
} from "../testing/durable.ts";

const Records = defineDocFamily<{ value: string }, { value: string }>({
  kind: "perk.record",
  version: 1,
  scope: "session",
  family: true,
  initial: (seed) => ({ value: seed.value }),
  checkpointWhen: () => true,
});

const Idle = defineTask<null, { phase: "run" }, null>({
  name: "perk.characterization.idle",
  version: 1,
  initial: () => ({ phase: "run" }),
  phases: {
    run: async (_task, runtime, phaseContext) => {
      await runtime.commit(() => completed(null), phaseContext);
    },
  },
  abort: async () => {},
});

test("D4 (P1, P5): Tx creates conversation-owned tasks and session doc-family records atomically", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const storage = new CountingStorage();
  const setup = fauxSetup();
  installTasks(setup, "idle", [Idle]);
  const { harness, root } = await open(t, storage, setup);
  const before = storage.commits.length;

  const id = await root.commit(async (tx) => {
    (await tx.doc(Records, "op-1", { value: "a" })).value = "recorded";
    return tx.createTask(Idle, null, { ownership: { kind: "conversation" } });
  }, context);

  const batches = storage.commits.slice(before);
  assert.equal(batches.length, 1, "one commit is one storage batch");
  const types = (batches[0] ?? []).map((write) => write.type);
  assert.ok(types.includes("task"), "the batch carries the task");
  assert.ok(types.includes("document.create"), "the same batch carries the family member");
  assert.deepEqual(await harness.snapshot(Records, "op-1", context), { value: "recorded" });
  const tasks = await harness.commit(
    (tx) => tx.scanTasks({ conversationId: root.id }, 20),
    context,
  );
  assert.equal(tasks.items.length, 1);
  const [task] = tasks.items;
  assert.equal(task?.id, id);
  assert.equal(task?.state.status, "pending");
  assert.equal(task?.conversationId, root.id);
  assert.equal(task?.owner, undefined, "no owner task: the conversation owns it");
});

test("D4c (P5): a session doc-family member is get-or-create by key", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const setup = fauxSetup();
  const { harness, root } = await open(t, new CountingStorage(), setup);

  await root.commit(async (tx) => {
    await tx.doc(Records, "k1", { value: "first" });
  }, context);
  const seen = await root.commit(
    async (tx) => (await tx.doc(Records, "k1", { value: "second" })).value,
    context,
  );
  assert.equal(seen, "first", "an existing member ignores the new seed");
  assert.deepEqual(await harness.snapshot(Records, "k1", context), { value: "first" });
  assert.equal(
    await harness.snapshot(Records, "k2", context),
    undefined,
    "another key is absent until it is created",
  );
  await root.commit(async (tx) => {
    await tx.doc(Records, "k2", { value: "third" });
  }, context);
  assert.deepEqual(await harness.snapshot(Records, "k2", context), { value: "third" });
});

test("D5 (P1): tasks created from a task's commit run after that commit", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const log: string[] = [];
  const storage = new CountingStorage();
  storage.onCommitted = () => log.push("storage:committed");
  const Child = defineTask<null, { phase: "run" }, null>({
    name: "perk.characterization.child",
    version: 1,
    initial: () => ({ phase: "run" }),
    phases: {
      run: async (_task, runtime, phaseContext) => {
        log.push("child:start");
        await runtime.commit(() => completed(null), phaseContext);
      },
    },
    abort: async () => {},
  });
  const Parent = defineTask<null, { phase: "run" }, null>({
    name: "perk.characterization.parent",
    version: 1,
    initial: () => ({ phase: "run" }),
    phases: {
      run: async (_task, runtime, phaseContext) => {
        await runtime.commit(async (tx) => {
          log.push("callback:createTask");
          await tx.createTask(Child, null, { ownership: { kind: "conversation" } });
          log.push("callback:end");
          return completed(null);
        }, phaseContext);
      },
    },
    abort: async () => {},
  });
  const setup = fauxSetup();
  installTasks(setup, "family", [Parent, Child]);
  const { harness, root } = await open(t, storage, setup);
  await root.commit(
    (tx) => tx.createTask(Parent, null, { ownership: { kind: "conversation" } }),
    context,
  );
  harness.resume();
  await waitFor(async () => {
    const tasks = await harness.commit(
      (tx) => tx.scanTasks({ conversationId: root.id }, 20),
      context,
    );
    return (
      tasks.items.length === 2 && tasks.items.every((task) => task.state.status === "terminal")
    );
  });

  const end = log.indexOf("callback:end");
  assert.notEqual(end, -1, "the parent's commit callback ran");
  const landed = log.indexOf("storage:committed", end);
  assert.notEqual(landed, -1, "the parent's commit reached storage");
  const start = log.indexOf("child:start");
  assert.ok(start > end, `the child started after the callback ended: ${log.join(" → ")}`);
  assert.ok(start > landed, `the child started after the commit landed: ${log.join(" → ")}`);
  assert.equal(log.filter((event) => event === "child:start").length, 1);
});
