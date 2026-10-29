// The binding's completeness proofs B6 and B5 (docs/design/pi-durable-v2-foundations.md §6 record
// tiers and record presentation). B6: at every state the set presented inside a commit, the set
// read outside one and the kernel's model chain are equal, including records nothing references
// (an attempt without an outcome, the latest observation, the cancellation) — omissions the kernel
// itself cannot detect — and the store holds exactly the cataloged documents. B5: no record lives
// only in task-scoped state; a control store shows the oracle sees one that does.

import assert from "node:assert/strict";
import { test } from "node:test";
import { defineDoc, defineTask } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  CATALOG_KIND,
  CatalogDoc,
  DURABLE_MAP_KIND,
  familyForRecordType,
  MANIFEST_KIND,
} from "../durable/documents.ts";
import { type CommitInput, operate } from "../durable/operate.ts";
import { loadRecords, type ReadRecordSet, readRecords } from "../durable/records.ts";
import { canonicalJson, type JsonValue } from "../kernel/canonical.ts";
import { cancelOpId, observeOpId, submitOpId } from "../kernel/identity.ts";
import { indexRecords, type KernelRecord } from "../kernel/records.ts";
import {
  acceptOp,
  assertSameRecords,
  attemptIdOf,
  C1B,
  C2,
  cancelOp,
  E,
  expectApplied,
  FAKE_ASSIGNMENT_NAME,
  type Installed,
  installBinding,
  modelChain,
  nonSessionV2Documents,
  ofType,
  openBinding,
  policyA,
  quiesce,
  runOp,
  startOp,
  storeDocuments,
  T1,
  T2,
  tasksOfKind,
} from "../testing/binding.ts";
import {
  CASE_TIMEOUT_MS,
  completed,
  context,
  fauxSetup,
  open,
  type Setup,
  sqlitePath,
} from "../testing/durable.ts";

type Session = Awaited<ReturnType<typeof openBinding>>;

/** The documents the catalog names, by kind then key, as canonical JSON (`""` for a singleton). */
function catalogedDocuments(
  read: ReadRecordSet,
  catalog: JsonValue,
): Map<string, Map<string, string>> {
  const expected = new Map<string, Map<string, string>>();
  const put = (kind: string, key: string, value: JsonValue) => {
    const byKey = expected.get(kind) ?? new Map<string, string>();
    byKey.set(key, canonicalJson(value));
    expected.set(kind, byKey);
  };
  put(CATALOG_KIND, "", catalog);
  for (const record of read.records) {
    if (record.type === "manifest") put(MANIFEST_KIND, "", record);
    else if (record.type !== "continuation")
      put(familyForRecordType(record.type).definition.kind, record.opId, record);
  }
  for (const [key, row] of read.durableMap) put(DURABLE_MAP_KIND, key, row);
  return expected;
}

function sorted(documents: Map<string, Map<string, string>>): [string, [string, string][]][] {
  return [...documents]
    .map(([kind, byKey]): [string, [string, string][]] => [
      kind,
      [...byKey].sort(([a], [b]) => (a < b ? -1 : 1)),
    ])
    .sort(([a], [b]) => (a < b ? -1 : 1));
}

/**
 * The three-way equality at one state — in-commit presentation, the outside read and the model —
 * then close: the storage oracle holds exactly the cataloged documents. Reopens and returns the
 * new session.
 */
async function checkState(
  t: Parameters<typeof sqlitePath>[0],
  label: string,
  session: Session,
  path: string,
  setup: Setup,
  installed: Installed,
  model: readonly KernelRecord[],
): Promise<Session> {
  const { harness } = session.opened;
  const presented = await harness.commit(async (tx) => (await loadRecords(tx)).records, context);
  const read = await readRecords(harness);
  assertSameRecords(presented, model, `${label}: presented in a commit vs the model`);
  assertSameRecords(read.records, model, `${label}: read outside a commit vs the model`);
  const catalog = await harness.snapshot(CatalogDoc, context);
  assert.ok(catalog !== undefined, `${label}: the catalog exists`);
  await session.opened.dispose();

  const stored = await storeDocuments(path);
  const actual = new Map(
    [...stored].map(([kind, byKey]) => [
      kind,
      new Map([...byKey].map(([key, value]) => [key, canonicalJson(value)])),
    ]),
  );
  assert.deepEqual(
    sorted(actual),
    sorted(catalogedDocuments(read, catalog)),
    `${label}: the store holds exactly the cataloged documents`,
  );
  return openBinding(t, await openNodeSqliteStorage(path), setup, installed);
}

test("B6: the presented record set is complete, including records nothing references", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  // The fakes complete without accepting, so the attempts stay without outcomes.
  const installed = installBinding(setup, { policy: policyA, accept: false });
  let session = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  const inputs: (CommitInput | undefined)[] = [];

  // 1. Attempts without outcomes. Were they not presented, the step would re-launch them.
  inputs.push(startOp());
  expectApplied(await operate(session.target, startOp()));
  await quiesce(session.opened.harness);
  for (const task of await tasksOfKind(session.opened.harness, FAKE_ASSIGNMENT_NAME)) {
    assert.equal(task.state.outcome?.status, "completed", "the fake ended without accepting");
  }
  const step = expectApplied(await operate(session.target));
  assert.deepEqual(step.actions, [], "the attempts were presented: nothing re-launched");
  inputs.push(undefined);
  assert.deepEqual(ofType(modelChain(inputs), "report-outcome"), []);
  session = await checkState(
    t,
    "attempts without outcomes",
    session,
    path,
    setup,
    installed,
    modelChain(inputs),
  );

  // 2. A latest observation nothing references.
  inputs.push(runOp(T1, C1B));
  expectApplied(await operate(session.target, runOp(T1, C1B)));
  session = await checkState(
    t,
    "an unreferenced latest observation",
    session,
    path,
    setup,
    installed,
    modelChain(inputs),
  );

  // 3. The cancellation. Were the latest observation not presented, the next run would take seq 2;
  //    were the cancellation not presented, it would admit the new tree.
  inputs.push(cancelOp());
  expectApplied(await operate(session.target, cancelOp()));
  session = await checkState(
    t,
    "the cancellation",
    session,
    path,
    setup,
    installed,
    modelChain(inputs),
  );
  inputs.push(runOp(T2, C2));
  const run = expectApplied(await operate(session.target, runOp(T2, C2)));
  assert.deepEqual(
    run.recorded.map((record) => (record.type === "manifest" ? "manifest" : record.opId)),
    [observeOpId(E, 3)],
    "the latest observation was presented",
  );
  assert.deepEqual(
    run.actions,
    [],
    "the cancellation was presented: no admission for the new tree",
  );
  const final = modelChain(inputs);
  session = await checkState(t, "after the consequences", session, path, setup, installed, final);
  const finalRead = (await readRecords(session.opened.harness)).records;

  // Vacuity control: the kernel accepts each truncated set, so only presentation catches the
  // omission — and the comparison names the missing key.
  for (const key of [submitOpId(attemptIdOf("a", T1)), observeOpId(E, 3), cancelOpId(E)]) {
    const truncated = final.filter((record) => record.type === "manifest" || record.opId !== key);
    assert.equal(truncated.length, final.length - 1, `${key} is in the final set`);
    assert.doesNotThrow(() => indexRecords(truncated), `the kernel cannot detect a missing ${key}`);
    assert.throws(
      () => assertSameRecords(finalRead, truncated, "control"),
      (error: unknown) => error instanceof Error && error.message.includes(key),
      `the comparison names ${key}`,
    );
  }
});

test("B5: no record lives only in task-scoped state", { timeout: CASE_TIMEOUT_MS }, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });

  // Started, closed with the fake tasks still pending.
  const first = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  expectApplied(await operate(first.target, startOp()));
  const pending = await tasksOfKind(first.opened.harness, FAKE_ASSIGNMENT_NAME);
  assert.deepEqual(
    pending.map((task) => task.state.status),
    ["pending", "pending"],
  );
  await first.opened.dispose();
  assert.deepEqual(
    await nonSessionV2Documents(path),
    [],
    "nothing v2 outside session scope (pending tasks)",
  );

  // Reopened and run to quiescence: every task terminal, its runtime state gone.
  const second = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  await quiesce(second.opened.harness);
  await second.opened.dispose();
  assert.deepEqual(
    await nonSessionV2Documents(path),
    [],
    "nothing v2 outside session scope (terminal tasks)",
  );

  const third = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  assertSameRecords(
    (await readRecords(third.opened.harness)).records,
    modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1)]),
    "every record survives in session scope",
  );
});

test("B5 control: the oracle reports a task-scoped perk.v2.* document", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const Probe = defineDoc<{ value: string }>({
    kind: "perk.v2.probe",
    version: 1,
    scope: "task",
    initial: () => ({ value: "" }),
    checkpointWhen: () => true,
  });
  const Control = defineTask<null, { phase: "run" }, null>({
    name: "perk.v2.control",
    version: 1,
    initial: () => ({ phase: "run" }),
    phases: {
      run: async (_task, runtime, phaseContext) => {
        await runtime.commit(() => completed(null), phaseContext);
      },
    },
    abort: async () => {},
  });
  const path = await sqlitePath(t);
  const opened = await open(t, await openNodeSqliteStorage(path), fauxSetup());
  // A pending control task, never resumed, holding a task-scoped v2 document.
  const id = await opened.root.commit(
    (tx) => tx.createTask(Control, null, { ownership: { kind: "conversation" } }),
    context,
  );
  await opened.harness.commit(async (tx) => {
    (await tx.doc(Probe, id)).value = "task-scoped";
  }, context);
  await opened.dispose();
  assert.deepEqual(await nonSessionV2Documents(path), [
    { kind: "perk.v2.probe", scope: JSON.stringify({ kind: "task", taskId: id }) },
  ]);
});
