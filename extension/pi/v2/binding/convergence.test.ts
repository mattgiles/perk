// The binding's convergence proof B2 (docs/design/pi-durable-v2-foundations.md §4 replay rule, §6
// receipt lookup, §7 the binding): duplicate and concurrent operations converge to one admission.
// Over SQLite, operations admitted together in one process are serialized on Durable's one mutation
// line; each commit evaluates over the records its predecessors wrote, so exactly one applies and
// the rest replay or find nothing to do — including a competitor enqueued from inside another
// operation's commit window.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  type AttemptLauncher,
  type BindingTarget,
  type OperateOutcome,
  operate,
} from "../durable/operate.ts";
import { readRecords } from "../durable/records.ts";
import { launchOpId, observeOpId } from "../kernel/identity.ts";
import {
  acceptOp,
  attemptIdOf,
  C2,
  C2B,
  C2C,
  C3,
  C3B,
  cancelOp,
  E,
  expectApplied,
  expectRefused,
  fakeLauncher,
  installBinding,
  ofType,
  openBinding,
  policyA,
  runOp,
  startOp,
  T1,
  T2,
  T3,
} from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, fauxSetup, recording, sqlitePath } from "../testing/durable.ts";

/** A started store (never resumed) over recording SQLite storage. */
async function started(
  t: Parameters<typeof sqlitePath>[0],
  launcher?: (fake: Parameters<typeof fakeLauncher>[0]) => AttemptLauncher,
) {
  const setup = fauxSetup();
  const installed = installBinding(setup, {
    policy: policyA,
    accept: true,
    ...(launcher === undefined ? {} : { launcher }),
  });
  const store = recording(await openNodeSqliteStorage(await sqlitePath(t)));
  const { opened, target } = await openBinding(t, store.storage, setup, installed);
  expectApplied(await operate(target, startOp()));
  return { store, opened, target };
}

function kinds(outcomes: readonly OperateOutcome[]): string[] {
  return outcomes.map((outcome) => outcome.kind).sort();
}

test("B2: duplicates in flight together converge to one acceptance and one storage batch", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { store, opened, target } = await started(t);
  const before = store.batches.length;
  const outcomes = await Promise.all([1, 2, 3, 4].map(() => operate(target, acceptOp("a", T1))));
  assert.deepEqual(kinds(outcomes), ["applied", "replayed", "replayed", "replayed"]);
  const receipts = outcomes.map((outcome) => {
    assert.ok(outcome.kind === "applied" || outcome.kind === "replayed");
    return outcome.receipt?.record;
  });
  for (const receipt of receipts)
    assert.deepEqual(receipt, receipts[0], "every receipt is the one outcome");
  const { records } = await readRecords(opened.harness);
  assert.equal(
    ofType(records, "report-outcome").filter((record) => record.attemptId === attemptIdOf("a", T1))
      .length,
    1,
  );
  assert.equal(store.batches.length, before + 1, "exactly one storage batch");
});

test("B2: concurrent runs of a new tree admit it exactly once", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { opened, target } = await started(t);
  const outcomes = (
    await Promise.all([C2, C2B, C2C].map((commit) => operate(target, runOp(T2, commit))))
  ).map(expectApplied);
  assert.deepEqual(
    outcomes.map((outcome) =>
      outcome.recorded.map((record) => (record.type === "manifest" ? "" : record.opId)),
    ),
    [[observeOpId(E, 2)], [observeOpId(E, 3)], [observeOpId(E, 4)]],
    "observations 2–4, in commit order",
  );
  assert.deepEqual(
    outcomes.map((outcome) => outcome.actions.length).sort(),
    [0, 0, 4],
    "exactly one run admits and launches; the others find nothing to do",
  );
  const { records, durableMap } = await readRecords(opened.harness);
  assert.equal(
    ofType(records, "assignment").filter((record) => record.subject.digest === T2).length,
    2,
  );
  const attempts = ofType(records, "attempt").filter((record) =>
    [attemptIdOf("a", T2), attemptIdOf("b", T2)].includes(record.attemptId),
  );
  assert.equal(attempts.length, 2);
  assert.equal(
    attempts.filter((record) => durableMap.has(launchOpId(record.attemptId))).length,
    2,
    "two launch rows over T2",
  );
});

test("B2: a competitor enqueued inside the commit window converges", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  // Armed only for T3: the launcher's first armed call runs inside `run(T3, C3)`'s commit and fires
  // a competing run without awaiting it there (it queues behind that very commit).
  const race: { target?: BindingTarget; armed: boolean; competitor?: Promise<OperateOutcome> } = {
    armed: false,
  };
  const { opened, target } = await started(t, (fake) => {
    const inner = fakeLauncher(fake);
    return (tx, launch) => {
      if (race.armed && race.competitor === undefined && race.target !== undefined) {
        race.competitor = operate(race.target, runOp(T3, C3B));
      }
      return inner(tx, launch);
    };
  });
  race.target = target;
  race.armed = true;
  const first = expectApplied(await operate(target, runOp(T3, C3)));
  assert.ok(race.competitor !== undefined, "the competitor fired inside the commit window");
  const competitor = expectApplied(await race.competitor);
  assert.equal(first.actions.length, 4, "the first run admits T3 and launches both attempts");
  assert.deepEqual(
    competitor.recorded.map((record) => record.type),
    ["observation"],
    "the competitor records only its observation",
  );
  assert.deepEqual(competitor.actions, [], "and finds nothing to do");
  const { records } = await readRecords(opened.harness);
  const overT3 = ofType(records, "assignment").filter((record) => record.subject.digest === T3);
  assert.deepEqual(
    overT3.map((record) => record.role).sort(),
    ["a", "b"],
    "T3 admitted once per role",
  );
});

test("B2: concurrent identical cancels converge; another reason conflicts", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { opened, target } = await started(t);
  const outcomes = await Promise.all([
    operate(target, cancelOp("stop")),
    operate(target, cancelOp("stop")),
  ]);
  assert.deepEqual(kinds(outcomes), ["applied", "replayed"]);
  expectRefused(await operate(target, cancelOp("another reason")), "duplicate_conflict");
  assert.equal(ofType((await readRecords(opened.harness)).records, "cancellation").length, 1);
});
