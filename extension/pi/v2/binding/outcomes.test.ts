// The binding's outcome proof B4 and its commit-failure classification
// (docs/design/pi-durable-v2-foundations.md §8 refusals, §9 the outcome taxonomy and
// classification). Over SQLite: a refused operation records nothing — not even its observation, or
// the catalog on an unstarted store — and leaves the Harness serving the next operation. A storage
// failure, from the commit or from inside the callback, is `uncertain`. Anything else in a Harness
// that has not failed is a thrown `BindingFault` carrying the original rejection — corruption, a
// launcher bug, an operation on a closed Harness — never a refusal; and a close racing the commit
// never replaces the original cause.

import assert from "node:assert/strict";
import { test } from "node:test";
import { type Harness, SessionFailed } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { AttemptFamily, CatalogDoc } from "../durable/documents.ts";
import { BindingFault, operate } from "../durable/operate.ts";
import { readRecords } from "../durable/records.ts";
import { deriveAttemptId, submitOpId } from "../kernel/identity.ts";
import { KernelInvariantError } from "../kernel/records.ts";
import { KernelRefusal } from "../kernel/refusal.ts";
import {
  acceptOp,
  assertSameRecords,
  assignmentIdOf,
  C1B,
  C2,
  C2B,
  cancelOp,
  expectApplied,
  expectRefused,
  expectUncertain,
  FAKE_ASSIGNMENT_NAME,
  facts,
  fakeLauncher,
  fakeReport,
  installBinding,
  ofType,
  openBinding,
  policyA,
  quiesce,
  replyOp,
  runOp,
  startOp,
  T1,
  T2,
  tasksOfKind,
} from "../testing/binding.ts";
import {
  CASE_TIMEOUT_MS,
  context,
  failing,
  failingMint,
  fauxSetup,
  flush,
  recording,
  sqlitePath,
} from "../testing/durable.ts";

/** The rejection of `promise`, asserting it rejects. */
async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  assert.fail("expected a rejection");
}

/** Assert `error` is a `BindingFault` (never a refusal) and return its cause. */
function faultCause(error: unknown): unknown {
  assert.ok(error instanceof BindingFault, `a BindingFault, not ${String(error)}`);
  assert.ok(!(error instanceof KernelRefusal), "a fault is never a refusal");
  return error.cause;
}

/** Whether the Harness is still open one macrotask later. */
async function stillOpen(harness: Harness): Promise<boolean> {
  return Promise.race([harness.closed.then(() => false), flush().then(() => true)]);
}

test("B4: a refused operation leaves no record and the Harness usable", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = recording(await openNodeSqliteStorage(await sqlitePath(t)));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  const { harness } = opened;
  expectApplied(await operate(target, startOp()));

  // Never resumed: three refusals, each reaching storage zero times.
  const records = (await readRecords(harness)).records;
  const before = store.batches.length;
  expectRefused(
    await operate(target, acceptOp("a", T1, { report: { ...fakeReport(T1), summary: "" } })),
    "invalid_report",
  );
  expectRefused(await operate(target, replyOp(T1)), "unknown_decision");
  expectRefused(
    await operate(target, {
      type: "run",
      observation: { ...facts(T1, C1B), repo: "/another/.git" },
    }),
    "invalid_input",
  );
  assert.equal(store.batches.length, before, "no refusal reached storage");
  assertSameRecords((await readRecords(harness)).records, records, "refusals record nothing");

  // The same Harness serves the next operation, and the run continues.
  expectApplied(await operate(target, acceptOp("a", T1)));
  await quiesce(harness);
  const settled = (await readRecords(harness)).records;
  assert.equal(ofType(settled, "report-outcome").length, 2, "fake a replayed; fake b accepted");
  assert.equal(ofType(settled, "decision").length, 1, "the decision opened");
  for (const task of await tasksOfKind(harness, FAKE_ASSIGNMENT_NAME)) {
    assert.equal(task.state.outcome?.status, "completed", "a replaying fake still completes");
  }
  expectApplied(await operate(target, runOp(T2, C2)));
  await quiesce(harness);

  // A reply to the T1 decision observing T2 is stale; it records nothing, not its observation.
  const observations = ofType((await readRecords(harness)).records, "observation").length;
  const staleAt = store.batches.length;
  expectRefused(
    await operate(target, replyOp(T1, { observation: facts(T2, C2B) })),
    "stale_subject",
  );
  assert.equal(store.batches.length, staleAt, "the stale reply reached storage zero times");
  assert.equal(ofType((await readRecords(harness)).records, "observation").length, observations);
});

test("a refused operation on an unstarted store records nothing, not even the catalog", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = recording(await openNodeSqliteStorage(await sqlitePath(t)));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  const before = store.batches.length;
  expectRefused(await operate(target), "invalid_input");
  expectRefused(await operate(target, cancelOp()), "invalid_input");
  assert.equal(store.batches.length, before, "zero storage batches");
  assert.equal(await opened.harness.snapshot(CatalogDoc, context), undefined, "no catalog");
  expectApplied(await operate(target, startOp()));
});

test("a storage commit failure is uncertain and closes the Harness", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = failing(await openNodeSqliteStorage(path));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  expectApplied(await operate(target, startOp()));

  const lost = new Error("disk gone");
  store.armNextCommit(lost);
  assert.equal(
    expectUncertain(await operate(target, cancelOp())),
    lost,
    "the cancellation's commit failed",
  );
  assert.deepEqual(await opened.harness.closed, { reason: "failed", error: lost });

  const reopened = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  assert.deepEqual(
    ofType((await readRecords(reopened.opened.harness)).records, "cancellation"),
    [],
  );
  expectApplied(await operate(reopened.target, cancelOp()));
});

test("a storage failure inside the callback is uncertain, not a refusal", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const store = failingMint(await openNodeSqliteStorage(path));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);

  // The catalog's creation mints its document id inside the commit callback.
  const minted = new Error("mint failed");
  store.armNextMint(minted);
  assert.equal(
    expectUncertain(await operate(target, startOp())),
    minted,
    "the catalog's mint failed",
  );
  assert.deepEqual(await opened.harness.closed, { reason: "failed", error: minted });

  const reopened = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  assert.equal(
    await reopened.opened.harness.snapshot(CatalogDoc, context),
    undefined,
    "nothing recorded",
  );
});

test("a KernelInvariantError is a binding fault, distinct from a refusal", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const absentKey = submitOpId(deriveAttemptId(assignmentIdOf("a", T1), 2));
  const unadmitted = assignmentIdOf("a", T2);
  const unadmittedAttempt = deriveAttemptId(unadmitted, 1);
  const corruptions = [
    {
      name: "a catalog key with no member",
      corrupt: async (harness: Harness) => {
        await harness.commit(async (tx) => {
          (await tx.doc(CatalogDoc)).members["perk.v2.attempt"]?.push(absentKey);
        }, context);
      },
    },
    {
      name: "a cataloged attempt naming an unadmitted assignment",
      corrupt: async (harness: Harness) => {
        await harness.commit(async (tx) => {
          const opId = submitOpId(unadmittedAttempt);
          await tx.doc(AttemptFamily, opId, {
            type: "attempt",
            opId,
            attemptId: unadmittedAttempt,
            assignmentId: unadmitted,
            ordinal: 1,
          });
          (await tx.doc(CatalogDoc)).members["perk.v2.attempt"]?.push(opId);
        }, context);
      },
    },
  ];
  for (const { name, corrupt } of corruptions) {
    const setup = fauxSetup();
    const installed = installBinding(setup, { policy: policyA, accept: true });
    const { opened, target } = await openBinding(
      t,
      await openNodeSqliteStorage(await sqlitePath(t)),
      setup,
      installed,
    );
    const { harness } = opened;
    expectApplied(await operate(target, startOp()));
    await corrupt(harness);
    const catalog = await harness.snapshot(CatalogDoc, context);

    const cause = faultCause(await rejection(operate(target)));
    assert.ok(
      cause instanceof KernelInvariantError,
      `${name}: the cause is a KernelInvariantError`,
    );
    assert.deepEqual(
      await harness.snapshot(CatalogDoc, context),
      catalog,
      `${name}: nothing recorded`,
    );
    assert.equal(
      await harness.snapshot(AttemptFamily, absentKey, context),
      undefined,
      `${name}: the read created no member`,
    );
    assert.ok(await stillOpen(harness), `${name}: the Harness stays open`);
    await harness.commit(() => undefined, context);
  }
});

test("a launcher throw is a binding fault", { timeout: CASE_TIMEOUT_MS }, async (t) => {
  const setup = fauxSetup();
  const bug = new TypeError("launcher bug");
  const installed = installBinding(setup, {
    policy: policyA,
    accept: true,
    launcher: () => async () => {
      throw bug;
    },
  });
  const { opened, target } = await openBinding(
    t,
    await openNodeSqliteStorage(await sqlitePath(t)),
    setup,
    installed,
  );
  assert.equal(faultCause(await rejection(operate(target, startOp()))), bug);
  assert.equal(await opened.harness.snapshot(CatalogDoc, context), undefined, "nothing recorded");
  const healthy = { ...target, deps: { policy: policyA, launcher: fakeLauncher(installed.fake) } };
  expectApplied(await operate(healthy, startOp()));
});

test("a normally closed Harness is a binding fault, never a raw error", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const { opened, target } = await openBinding(
    t,
    await openNodeSqliteStorage(await sqlitePath(t)),
    setup,
    installed,
  );
  expectApplied(await operate(target, startOp()));
  await opened.dispose();
  assert.deepEqual(await opened.harness.closed, { reason: "closed" });

  const cause = faultCause(await rejection(operate(target, cancelOp())));
  assert.ok(cause instanceof Error, "the cause is Durable's closed error");
  assert.equal(cause.message, "Session is closed");
  assert.ok(!(cause instanceof SessionFailed), "a closed Harness is not a failed one");
});

test("a close inside the commit window keeps the original cause", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  const raced = new TypeError("raced");
  const race: { harness?: Harness } = {};
  const installed = installBinding(setup, {
    policy: policyA,
    accept: true,
    // Close sets its closing state synchronously and queues behind this running commit.
    launcher: () => async () => {
      void race.harness?.close(context).catch(() => {});
      throw raced;
    },
  });
  const { opened, target } = await openBinding(
    t,
    await openNodeSqliteStorage(path),
    setup,
    installed,
  );
  race.harness = opened.harness;

  // The probe meets a closing Harness and rejects with the plain closed error, which neither
  // escapes nor becomes the cause.
  assert.equal(faultCause(await rejection(operate(target, startOp()))), raced);
  assert.deepEqual(await opened.harness.closed, { reason: "closed" });

  const reopened = await openBinding(t, await openNodeSqliteStorage(path), setup, installed);
  assert.equal(
    await reopened.opened.harness.snapshot(CatalogDoc, context),
    undefined,
    "nothing recorded",
  );
});
