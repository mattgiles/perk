// V1 — the status snapshot (docs/design/pi-durable-v2-foundations.md §11, contracts.md §8.77) over
// synthetic kernel-model record sets: every state and waiting reason, the observation's age, current
// and stale assignments with their attempts, endings and outcome ids, the decision shown only for
// the current subject and never once cancelled or continued, and the diagnostics counts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { statusSnapshot, type ViewSnapshot } from "../door/snapshot.ts";
import type { AttemptEnding } from "../durable/ending.ts";
import type { LiveTaskState } from "../durable/waitReason.ts";
import { FIXTURE_ACTIONS, FIXTURE_ACTOR } from "../kernel/fixture.ts";
import { acceptReportOpId } from "../kernel/identity.ts";
import type { KernelRecord } from "../kernel/records.ts";
import { WAIT_REASONS } from "../kernel/waitReason.ts";
import {
  acceptOp,
  assignmentIdOf,
  attemptIdOf,
  C1,
  C2,
  cancelOp,
  decisionIdOf,
  digestOf,
  manifest,
  modelChain,
  REF,
  REPO,
  replyOp,
  runOp,
  startOp,
  T1,
  T2,
} from "../testing/binding.ts";
import { snapshotInput } from "../testing/door.ts";

/** `facts()` observes at 1000 ms; a minute later. */
const NOW = 61_000;

const STARTED = modelChain([startOp()]);
const ACCEPTED = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1)]);
const SECOND_ROUND = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1), runOp(T2, C2)]);
const CANCELLED = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1), cancelOp()]);
const COMPLETED = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1), replyOp(T1)]);

function snapshot(
  records: readonly KernelRecord[],
  waitReason: Parameters<typeof snapshotInput>[1],
  overrides: Parameters<typeof snapshotInput>[2] = {},
  now = NOW,
): ViewSnapshot {
  return statusSnapshot(snapshotInput(records, waitReason, overrides), now);
}

test("V1: the snapshot's keys are in their fixed order", () => {
  assert.deepEqual(Object.keys(snapshot(ACCEPTED, "pending_decision")), [
    "state",
    "waitReason",
    "observation",
    "assignments",
    "decision",
    "cancellation",
    "diagnostics",
  ]);
});

test("V1: every state: running, each waiting reason, completed and cancelled", () => {
  const running = snapshot(STARTED, null, { runnable: true, live: [{ kind: "running" }] });
  assert.equal(running.state, "running");
  assert.equal(running.waitReason, null);
  assert.equal(running.diagnostics.runnable, true);

  const waiting = WAIT_REASONS.filter((reason) => reason !== "completed" && reason !== "cancelled");
  assert.deepEqual(
    [...waiting].sort(),
    [
      "assignment_incomplete",
      "blocked",
      "parked",
      "pending_decision",
      "repair_required",
      "sleeping",
      "unmet_prerequisite",
    ],
    "the seven waiting reasons, the synthetic `unmet_prerequisite` included",
  );
  for (const reason of waiting) {
    const view = snapshot(STARTED, reason);
    assert.equal(view.state, "waiting", reason);
    assert.equal(view.waitReason, reason);
  }

  const completed = snapshot(COMPLETED, "completed");
  assert.equal(completed.state, "completed");
  assert.equal(completed.waitReason, null);
  const cancelled = snapshot(CANCELLED, "cancelled");
  assert.equal(cancelled.state, "cancelled");
  assert.equal(cancelled.waitReason, null);
  assert.deepEqual(cancelled.cancellation, { reason: "operator stop" });
  assert.equal(completed.cancellation, null);
});

test("V1: the latest observation and its age, clamped at zero; none before any observation", () => {
  assert.deepEqual(snapshot(SECOND_ROUND, "assignment_incomplete").observation, {
    seq: 2,
    repo: REPO,
    ref: REF,
    commit: C2,
    tree: T2,
    manifestDigest: digestOf(T2),
    observedAt: 1000,
    ageMs: NOW - 1000,
  });
  assert.equal(snapshot(ACCEPTED, "pending_decision", {}, 400).observation?.ageMs, 0);
  assert.equal(snapshot(STARTED, null, {}, 1000).observation?.ageMs, 0);

  for (const records of [[], [manifest()]]) {
    const empty = snapshot(records, null);
    assert.equal(empty.observation, null);
    assert.deepEqual(empty.assignments, []);
    assert.equal(empty.decision, null);
  }
  assert.equal(snapshot(STARTED, null).observation?.commit, C1);
});

test("V1: every assignment is listed, current or stale against the latest tree", () => {
  const view = snapshot(SECOND_ROUND, "assignment_incomplete");
  const rows = view.assignments.map((row) => [
    row.assignmentId,
    row.role,
    row.subjectDigest,
    row.current,
    row.acceptedOutcomeId !== null,
  ]);
  const expected = [
    [assignmentIdOf("a", T1), "a", T1, false, true],
    [assignmentIdOf("b", T1), "b", T1, false, true],
    [assignmentIdOf("a", T2), "a", T2, true, false],
    [assignmentIdOf("b", T2), "b", T2, true, false],
  ].sort((x, y) => (String(x[0]) < String(y[0]) ? -1 : 1));
  assert.deepEqual(rows, expected, "every round, in op-id order");
});

test("V1: attempts carry their outcome ids and endings; acceptance is the first outcome", () => {
  const records = modelChain([startOp(), acceptOp("a", T1)]);
  const a = attemptIdOf("a", T1);
  const b = attemptIdOf("b", T1);
  const accepted: AttemptEnding = { end: "accepted", outcomeId: acceptReportOpId(a) };
  const incomplete: AttemptEnding = {
    end: "incomplete",
    submission: "done",
    reason: "the worker ended without a report",
    refusal: "invalid_report",
  };
  const view = snapshot(records, "assignment_incomplete", {
    endings: new Map<string, AttemptEnding>([
      [a, accepted],
      [b, incomplete],
    ]),
  });
  const byRole = new Map(view.assignments.map((row) => [row.role, row]));
  assert.deepEqual(byRole.get("a"), {
    assignmentId: assignmentIdOf("a", T1),
    role: "a",
    subjectDigest: T1,
    current: true,
    acceptedOutcomeId: acceptReportOpId(a),
    attempts: [{ attemptId: a, ordinal: 1, outcomeId: acceptReportOpId(a), ending: accepted }],
  });
  assert.deepEqual(byRole.get("b"), {
    assignmentId: assignmentIdOf("b", T1),
    role: "b",
    subjectDigest: T1,
    current: true,
    acceptedOutcomeId: null,
    attempts: [{ attemptId: b, ordinal: 1, outcomeId: null, ending: incomplete }],
  });

  const repair: AttemptEnding = { end: "repair", cause: "snapshot_tampered", detail: "a.txt" };
  const repaired = snapshot(records, "repair_required", {
    endings: new Map<string, AttemptEnding>([[b, repair]]),
  });
  const rowB = repaired.assignments.find((row) => row.role === "b");
  assert.deepEqual(rowB?.attempts[0]?.ending, repair);
  const rowA = repaired.assignments.find((row) => row.role === "a");
  assert.equal(rowA?.attempts[0]?.ending, null, "an attempt with no ending");
});

test("V1: the decision is shown for the current subject only, and never once cancelled or continued", () => {
  const d = decisionIdOf(T1);
  assert.deepEqual(snapshot(ACCEPTED, "pending_decision").decision, {
    decisionId: d,
    subjectDigest: T1,
    allowedActions: [...FIXTURE_ACTIONS],
    actor: FIXTURE_ACTOR,
  });
  assert.equal(snapshot(SECOND_ROUND, "assignment_incomplete").decision, null, "stale");
  assert.equal(snapshot(CANCELLED, "cancelled").decision, null, "cancelled");
  assert.equal(snapshot(COMPLETED, "completed").decision, null, "continued");
  assert.equal(snapshot(STARTED, "assignment_incomplete").decision, null, "none opened yet");
});

test("V1: diagnostics count blocked, parked and sleeping live tasks", () => {
  const live: LiveTaskState[] = [
    { kind: "blocked", reason: "missing_task" },
    { kind: "blocked", reason: "migration_failed" },
    { kind: "blocked", reason: "restart_limit" },
    { kind: "sleeping", until: 5 },
    { kind: "sleeping", until: 6 },
    { kind: "sleeping", until: 7 },
    { kind: "running" },
    { kind: "ready", migrates: false },
    { kind: "waiting", on: [] },
    { kind: "completing" },
  ];
  assert.deepEqual(snapshot(STARTED, "blocked", { live }).diagnostics, {
    runnable: false,
    blocked: 2,
    parked: 1,
    sleeping: 3,
  });
  assert.deepEqual(snapshot(STARTED, "assignment_incomplete").diagnostics, {
    runnable: false,
    blocked: 0,
    parked: 0,
    sleeping: 0,
  });
});
