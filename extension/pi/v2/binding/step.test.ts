// The step task (docs/design/pi-durable-v2-foundations.md §7 the step task and task ownership, §9).
// Over SQLite: `perk.v2.step` is `operate()` with no input, committed from the task's own commit —
// on settled records it writes nothing but its own completion. Under a policy the records were not
// reconciled under, a step admits the new round exactly once beside concurrent host steps (2.3's
// gate refuses such a policy change in production; here it makes the step's work observable). On
// an unstarted store the step's refusal faults the task and records nothing.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { StorageWrite } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { CatalogDoc } from "../durable/documents.ts";
import { operate } from "../durable/operate.ts";
import { readRecords } from "../durable/records.ts";
import { createStepTask, STEP_TASK_NAME } from "../durable/tasks.ts";
import { capabilitySetDigest } from "../kernel/capability.ts";
import { launchOpId } from "../kernel/identity.ts";
import type { KernelRecord } from "../kernel/records.ts";
import {
  assertSameRecords,
  attemptIdOf,
  expectApplied,
  installBinding,
  ofType,
  openBinding,
  policyA,
  policyB,
  quiesce,
  startOp,
  T1,
  tasksOfKind,
} from "../testing/binding.ts";
import {
  CASE_TIMEOUT_MS,
  context,
  fauxSetup,
  recording,
  sqlitePath,
  waitFor,
} from "../testing/durable.ts";

function keyOf(record: KernelRecord): string {
  return record.type === "manifest" ? "manifest" : record.opId;
}

function isDocumentWrite(write: StorageWrite): boolean {
  return write.type.startsWith("document.");
}

test("the step task is operate() with no input", { timeout: CASE_TIMEOUT_MS }, async (t) => {
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = recording(await openNodeSqliteStorage(await sqlitePath(t)));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  const { harness } = opened;
  expectApplied(await operate(target, startOp()));
  await quiesce(harness);
  const records = (await readRecords(harness)).records;

  // On settled records the step writes nothing but its own task state.
  const before = store.batches.length;
  const id = await harness.commit(
    (tx) => createStepTask(tx, installed.step, opened.root.id),
    context,
  );
  await quiesce(harness);
  const [step] = await tasksOfKind(harness, STEP_TASK_NAME);
  assert.equal(step?.id, id);
  assert.equal(step?.conversationId, opened.root.id, "on the execution conversation");
  assert.equal(step?.background, true, "background");
  assert.equal(step?.state.status, "terminal");
  assert.equal(step?.state.outcome?.status, "completed");
  const since = store.batches.slice(before);
  const completing = since.filter((batch) =>
    batch.some(
      (write) =>
        write.type === "task" && write.value.id === id && write.value.state.status === "terminal",
    ),
  );
  assert.equal(completing.length, 1, "one batch completes the step task");
  assert.deepEqual(
    completing[0]?.filter(isDocumentWrite),
    [],
    "the step's own commit writes no document",
  );
  assert.deepEqual(
    since.flat().filter(isDocumentWrite),
    [],
    "no batch since the step's creation writes a document",
  );
  assertSameRecords((await readRecords(harness)).records, records, "the step recorded nothing");

  // A host step is the same no-op, reaching storage zero times.
  const hostAt = store.batches.length;
  const host = expectApplied(await operate(target));
  assert.deepEqual(host.recorded, []);
  assert.deepEqual(host.actions, []);
  assert.equal(store.batches.length, hostAt, "zero storage batches");
});

test("a step under a changed policy admits the new round exactly once, beside concurrent host steps", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setupA = fauxSetup();
  const installedA = installBinding(setupA, { policy: policyA, accept: true });
  const first = await openBinding(t, await openNodeSqliteStorage(path), setupA, installedA);
  expectApplied(await operate(first.target, startOp()));
  await quiesce(first.opened.harness);
  const underA = (await readRecords(first.opened.harness)).records;
  await first.opened.dispose();

  // Reopen under policy B: the records were reconciled under A, so B's round is new work.
  const setupB = fauxSetup();
  const installedB = installBinding(setupB, { policy: policyB, accept: false });
  const { opened, target } = await openBinding(
    t,
    await openNodeSqliteStorage(path),
    setupB,
    installedB,
  );
  const { harness } = opened;
  await harness.commit((tx) => createStepTask(tx, installedB.step, opened.root.id), context);
  harness.resume();
  const hosts = await Promise.all([1, 2, 3].map(() => operate(target)));
  await waitFor(() => !harness.wake().active);

  const [step] = await tasksOfKind(harness, STEP_TASK_NAME);
  assert.equal(step?.state.outcome?.status, "completed", "the step task completed");
  const admitting = hosts.map(expectApplied).filter((outcome) => outcome.actions.length > 0);
  assert.ok(admitting.length <= 1, "at most one host step admitted (otherwise the step task did)");
  const { records, durableMap } = await readRecords(harness);
  const capsetB = capabilitySetDigest(policyB.capabilitySet);
  const underB = ofType(records, "assignment").filter((record) =>
    record.assignmentId.endsWith(capsetB),
  );
  assert.equal(underB.length, 2, "exactly two assignments under policy B");
  assert.ok(
    underB.every((record) => record.subject.digest === T1),
    "over T1",
  );
  const attemptsB = [attemptIdOf("a", T1, policyB), attemptIdOf("b", T1, policyB)];
  assert.deepEqual(
    ofType(records, "attempt")
      .filter((record) => attemptsB.includes(record.attemptId))
      .map((record) => record.attemptId)
      .sort(),
    [...attemptsB].sort(),
    "exactly two attempts under policy B",
  );
  assert.deepEqual(
    attemptsB.filter((attempt) => durableMap.has(launchOpId(attempt))),
    attemptsB,
    "both launched",
  );
  const keysA = new Set(underA.map(keyOf));
  assertSameRecords(
    records.filter((record) => keysA.has(keyOf(record))),
    underA,
    "the policy-A records are unchanged",
  );
  assert.equal(
    records.length,
    underA.length + 4,
    "the new round is two admissions and two attempts",
  );
});

test("a step task on an unstarted store faults and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const { opened } = await openBinding(
    t,
    await openNodeSqliteStorage(await sqlitePath(t)),
    setup,
    installed,
  );
  const { harness } = opened;
  const id = await harness.commit(
    (tx) => createStepTask(tx, installed.step, opened.root.id),
    context,
  );
  await quiesce(harness);
  const [step] = await tasksOfKind(harness, STEP_TASK_NAME);
  assert.equal(step?.id, id);
  assert.equal(step?.state.status, "terminal");
  assert.equal(step?.state.outcome?.status, "faulted");
  assert.ok(
    setup.infos.some((info) => info.type === "task_faulted" && info.task.id === id),
    "Durable reported the fault",
  );
  assert.equal(await harness.snapshot(CatalogDoc, context), undefined, "no catalog");
});
