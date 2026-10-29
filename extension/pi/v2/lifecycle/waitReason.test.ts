// Wait-reason derivation (docs/design/pi-durable-v2-foundations.md §10 step 8) over kernel model
// record sets and hand-built live task states: the derived and underived reasons partition the
// closed vocabulary, the precedence is pinned row by row, only a decision over the current subject
// is a human wait, and the rows produce every derived reason.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DERIVED_WAIT_REASONS,
  deriveWaitReason,
  type LiveTaskState,
  UNDERIVED_WAIT_REASONS,
} from "../durable/waitReason.ts";
import type { KernelRecord } from "../kernel/records.ts";
import { WAIT_REASONS, type WaitReason } from "../kernel/waitReason.ts";
import {
  acceptOp,
  C2,
  cancelOp,
  modelChain,
  ofType,
  policyA,
  replyOp,
  runOp,
  startOp,
  T1,
  T2,
} from "../testing/binding.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";

const SLEEPING: LiveTaskState = { kind: "sleeping", until: 5000 };
const PARKED: LiveTaskState = { kind: "blocked", reason: "restart_limit" };
const MISSING: LiveTaskState = { kind: "blocked", reason: "missing_task" };
const READY: LiveTaskState = { kind: "ready", migrates: false };

const started = modelChain([startOp()]);
const decided = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1)]);
const replied = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1), replyOp(T1)]);

type Row = {
  readonly name: string;
  readonly records: readonly KernelRecord[];
  readonly live: readonly LiveTaskState[];
  readonly expected: WaitReason | null;
};

const ROWS: readonly Row[] = [
  { name: "empty", records: [], live: [], expected: null },
  {
    name: "start-only, nothing live",
    records: started,
    live: [],
    expected: "assignment_incomplete",
  },
  { name: "a sleeping task", records: started, live: [SLEEPING, READY], expected: "sleeping" },
  { name: "a parked task", records: started, live: [PARKED], expected: "parked" },
  { name: "a missing-task block", records: started, live: [MISSING], expected: "blocked" },
  {
    name: "blocked, parked and sleeping",
    records: started,
    live: [SLEEPING, PARKED, MISSING],
    expected: "blocked",
  },
  { name: "parked and sleeping", records: started, live: [SLEEPING, PARKED], expected: "parked" },
  {
    name: "a decision over the current subject, even with a parked task",
    records: decided,
    live: [PARKED],
    expected: "pending_decision",
  },
  { name: "a reply", records: replied, live: [], expected: "completed" },
  {
    name: "a reply, then a cancellation",
    records: modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1), replyOp(T1), cancelOp()]),
    live: [],
    expected: "completed",
  },
  {
    name: "a cancellation, with a parked task",
    records: modelChain([startOp(), cancelOp()]),
    live: [PARKED],
    expected: "cancelled",
  },
  {
    name: "an earlier tree's decision is not a human wait",
    records: modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1), runOp(T2, C2)]),
    live: [],
    expected: "assignment_incomplete",
  },
];

test("census: derived and underived reasons partition the vocabulary; precedence is pinned", {
  timeout: CASE_TIMEOUT_MS,
}, () => {
  assert.deepEqual(DERIVED_WAIT_REASONS, [
    "completed",
    "cancelled",
    "pending_decision",
    "blocked",
    "parked",
    "sleeping",
    "assignment_incomplete",
  ]);
  const derived: readonly string[] = DERIVED_WAIT_REASONS;
  assert.deepEqual(
    UNDERIVED_WAIT_REASONS.filter((reason) => derived.includes(reason)),
    [],
    "disjoint",
  );
  assert.deepEqual(
    [...DERIVED_WAIT_REASONS, ...UNDERIVED_WAIT_REASONS].sort(),
    [...WAIT_REASONS].sort(),
    "together they are the closed vocabulary",
  );
});

test("each row derives its wait reason", { timeout: CASE_TIMEOUT_MS }, () => {
  for (const row of ROWS) {
    assert.equal(deriveWaitReason(row.records, policyA, row.live), row.expected, row.name);
  }
});

test("vacuity: the rows produce every derived reason over the records they name", {
  timeout: CASE_TIMEOUT_MS,
}, () => {
  const produced = new Set(ROWS.map((row) => row.expected));
  for (const reason of DERIVED_WAIT_REASONS) assert.ok(produced.has(reason), reason);
  for (const row of ROWS.filter((r) => r.name.includes("cancellation"))) {
    assert.equal(ofType(row.records, "cancellation").length, 1, `${row.name}: cancel applied`);
  }
  assert.equal(ofType(decided, "decision").length, 1, "the T1 decision opened");
  const moved = ROWS.at(-1)?.records ?? [];
  assert.equal(ofType(moved, "decision").length, 1, "the T1 decision survives the move to T2");
});
