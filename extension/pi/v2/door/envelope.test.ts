// V2 — the door envelope (docs/design/pi-durable-v2-foundations.md §11, contracts.md §8.77): every
// door outcome maps to its envelope variant with every unset field `null`; `pending_decision` versus
// `ok`; the receipt views and their binding-bug throws; the host-outcome adapters; and the twelve
// committed goldens, byte-pinned. Regenerate them with
// `PERK_UPDATE_V2_ENVELOPES=1 node --test extension/pi/v2/door/envelope.test.ts`, which rewrites
// them and then still re-reads and asserts. Python validates the same goldens
// (`tests/test_v2_envelope.py`).

import assert from "node:assert/strict";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import {
  DOOR_OUTCOMES,
  type DoorOutcome,
  type DoorVerb,
  doorOutcomeOfRun,
  doorOutcomeOfStatus,
  type Envelope,
  envelopeOf,
  receiptView,
} from "../door/envelope.ts";
import { statusSnapshot } from "../door/snapshot.ts";
import type { AttemptEnding } from "../durable/ending.ts";
import type { BindingReceipt } from "../durable/operate.ts";
import type { HostMismatch, HostView } from "../host.ts";
import { acceptReportOpId, cancelOpId, continuationOpId, replyOpId } from "../kernel/identity.ts";
import { receiptFor } from "../kernel/reconcile.ts";
import type { KernelRecord } from "../kernel/records.ts";
import {
  acceptOp,
  attemptIdOf,
  cancelOp,
  decisionIdOf,
  E,
  modelChain,
  replyOp,
  startOp,
  T1,
} from "../testing/binding.ts";
import { snapshotInput } from "../testing/door.ts";

const GOLDEN_DIR = join(import.meta.dirname, "golden");
const UPDATE = process.env.PERK_UPDATE_V2_ENVELOPES === "1";
/** `facts()` observes at 1000 ms; the envelopes are built a minute later. */
const NOW = 61_000;

const STARTED = modelChain([startOp()]);
const PARTIAL = modelChain([startOp(), acceptOp("a", T1)]);
const ACCEPTED = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1)]);
const COMPLETED = modelChain([startOp(), acceptOp("a", T1), acceptOp("b", T1), replyOp(T1)]);
const CANCELLED = modelChain([startOp(), cancelOp()]);
const D = decisionIdOf(T1);
const A = attemptIdOf("a", T1);
const B = attemptIdOf("b", T1);
const CONTINUATION_TASK = 9;

function receiptOf(records: readonly KernelRecord[], opId: string): BindingReceipt {
  const receipt = receiptFor(records, opId);
  assert.ok(receipt !== null, `a receipt under ${opId}`);
  return {
    ...receipt,
    durable:
      receipt.record.type === "reply"
        ? [
            {
              perkId: continuationOpId(D),
              durableKind: "task",
              durableId: CONTINUATION_TASK,
            },
          ]
        : [],
  };
}

const REPLY_RECEIPT = receiptOf(COMPLETED, replyOpId(D));
const CANCEL_RECEIPT = receiptOf(CANCELLED, cancelOpId(E));

function accepted(attemptId: string): AttemptEnding {
  return { end: "accepted", outcomeId: acceptReportOpId(attemptId) };
}

const MANIFEST_MISSING: HostMismatch = { field: "manifest_missing", expected: null, found: null };

type Golden = { readonly verb: DoorVerb; readonly outcome: DoorOutcome };

/** The twelve goldens: every outcome, every verb, every snapshot variant. */
const GOLDENS: Readonly<Record<string, Golden>> = {
  "start-pending-decision": {
    verb: "start",
    outcome: {
      kind: "view",
      epoch: 1,
      view: snapshotInput(ACCEPTED, "pending_decision", {
        endings: new Map([
          [A, accepted(A)],
          [B, accepted(B)],
        ]),
      }),
      receipt: null,
    },
  },
  "status-ok-running": {
    verb: "status",
    outcome: {
      kind: "view",
      epoch: 2,
      view: snapshotInput(STARTED, null, {
        runnable: true,
        live: [{ kind: "running" }, { kind: "ready", migrates: false }],
      }),
      receipt: null,
    },
  },
  "status-ok-assignment-incomplete": {
    verb: "status",
    outcome: {
      kind: "view",
      epoch: 2,
      view: snapshotInput(PARTIAL, "assignment_incomplete", {
        endings: new Map<string, AttemptEnding>([
          [A, accepted(A)],
          [
            B,
            {
              end: "incomplete",
              submission: "done",
              reason: "the worker finished without an accepted report",
              refusal: "invalid_report",
            },
          ],
        ]),
      }),
      receipt: null,
    },
  },
  "status-ok-repair-required": {
    verb: "status",
    outcome: {
      kind: "view",
      epoch: 2,
      view: snapshotInput(PARTIAL, "repair_required", {
        endings: new Map<string, AttemptEnding>([
          [A, accepted(A)],
          [
            B,
            {
              end: "repair",
              cause: "snapshot_tampered",
              detail: "the snapshot of the subject no longer verifies",
            },
          ],
        ]),
      }),
      receipt: null,
    },
  },
  "reply-ok-completed": {
    verb: "reply",
    outcome: {
      kind: "view",
      epoch: 3,
      view: snapshotInput(COMPLETED, "completed", {
        endings: new Map([
          [A, accepted(A)],
          [B, accepted(B)],
        ]),
      }),
      receipt: REPLY_RECEIPT,
    },
  },
  "cancel-ok-cancelled": {
    verb: "cancel",
    outcome: {
      kind: "view",
      epoch: 2,
      view: snapshotInput(CANCELLED, "cancelled"),
      receipt: CANCEL_RECEIPT,
    },
  },
  "status-owner-busy": { verb: "status", outcome: { kind: "owner_busy", epoch: 4 } },
  "run-incompatible-missing": {
    verb: "run",
    outcome: { kind: "incompatible", epoch: null, mismatch: MANIFEST_MISSING },
  },
  "status-incompatible-mismatch": {
    verb: "status",
    outcome: {
      kind: "incompatible",
      epoch: 2,
      mismatch: { field: "policyVersion", expected: 1, found: 2 },
    },
  },
  "start-observation-failed": {
    verb: "start",
    outcome: {
      kind: "observation_failed",
      epoch: 1,
      detail: 'ref "refs/heads/missing" does not resolve to a commit in /repo',
    },
  },
  "reply-refused-stale": {
    verb: "reply",
    outcome: {
      kind: "refused",
      epoch: 3,
      refusal: {
        reason: "stale_subject",
        detail: `${D} is over ${T1}, not the observed subject`,
      },
    },
  },
  "run-uncertain": {
    verb: "run",
    outcome: { kind: "uncertain", epoch: 2, error: new Error("commit failed") },
  },
};

function canonical(envelope: Envelope): string {
  return `${JSON.stringify(envelope, null, 2)}\n`;
}

function build(golden: Golden): Envelope {
  return envelopeOf(golden.verb, E, golden.outcome, NOW);
}

const NULLS = { status: null, receipt: null, refusal: null, mismatch: null, error: null };

test("V2: the envelope's keys are in their fixed order", () => {
  for (const [name, golden] of Object.entries(GOLDENS)) {
    assert.deepEqual(
      Object.keys(build(golden)),
      [
        "envelope",
        "outcome",
        "verb",
        "executionId",
        "epoch",
        "status",
        "receipt",
        "refusal",
        "mismatch",
        "error",
      ],
      name,
    );
  }
});

test("V2: every door outcome maps to its variant, every unset field null", () => {
  const head = (outcome: string, verb: DoorVerb, epoch: number | null) => ({
    envelope: 1,
    outcome,
    verb,
    executionId: E,
    epoch,
  });
  assert.deepEqual(envelopeOf("status", E, { kind: "owner_busy", epoch: 4 }, NOW), {
    ...head("owner_busy", "status", 4),
    ...NULLS,
  });
  assert.deepEqual(
    envelopeOf("run", E, { kind: "incompatible", epoch: null, mismatch: MANIFEST_MISSING }, NOW),
    {
      ...head("incompatible", "run", null),
      ...NULLS,
      status: { state: "incompatible" },
      mismatch: MANIFEST_MISSING,
    },
  );
  assert.deepEqual(
    envelopeOf("reply", E, { kind: "observation_failed", epoch: 2, detail: "gone" }, NOW),
    { ...head("observation_failed", "reply", 2), ...NULLS, error: { message: "gone" } },
  );
  const refusal = { reason: "cancelled", detail: "the execution is cancelled" } as const;
  assert.deepEqual(envelopeOf("cancel", E, { kind: "refused", epoch: 2, refusal }, NOW), {
    ...head("refused", "cancel", 2),
    ...NULLS,
    refusal,
  });
  assert.deepEqual(
    envelopeOf("run", E, { kind: "uncertain", epoch: 3, error: new Error("boom") }, NOW),
    {
      ...head("uncertain", "run", 3),
      ...NULLS,
      status: { state: "uncertain" },
      error: { message: "boom" },
    },
  );
  assert.deepEqual(
    envelopeOf("status", E, { kind: "uncertain", epoch: 3, error: "not an Error" }, NOW).error,
    { message: "not an Error" },
    "a non-Error is rendered with String()",
  );
  const input = snapshotInput(CANCELLED, "cancelled");
  assert.deepEqual(
    envelopeOf("cancel", E, { kind: "view", epoch: 2, view: input, receipt: CANCEL_RECEIPT }, NOW),
    {
      ...head("ok", "cancel", 2),
      ...NULLS,
      status: statusSnapshot(input, NOW),
      receipt: { opId: cancelOpId(E), kind: "cancellation", continuation: null },
    },
  );
});

test("V2: pending_decision only for a quiescent start, run or reply; status is ok", () => {
  const view = snapshotInput(ACCEPTED, "pending_decision");
  const outcomeOf = (verb: DoorVerb) =>
    envelopeOf(verb, E, { kind: "view", epoch: 1, view, receipt: null }, NOW).outcome;
  for (const verb of ["start", "run", "reply"] as const) {
    assert.equal(outcomeOf(verb), "pending_decision", verb);
  }
  assert.equal(outcomeOf("status"), "ok");
  for (const reason of ["assignment_incomplete", "repair_required", "completed"] as const) {
    const other = snapshotInput(ACCEPTED, reason);
    assert.equal(
      envelopeOf("run", E, { kind: "view", epoch: 1, view: other, receipt: null }, NOW).outcome,
      "ok",
      reason,
    );
  }
});

test("V2: receipt views — a reply's continuation task, a cancel's none, and the binding-bug throws", () => {
  assert.deepEqual(receiptView(REPLY_RECEIPT), {
    opId: replyOpId(D),
    kind: "reply",
    continuation: { opId: continuationOpId(D), taskId: CONTINUATION_TASK },
  });
  assert.deepEqual(receiptView(CANCEL_RECEIPT), {
    opId: cancelOpId(E),
    kind: "cancellation",
    continuation: null,
  });
  assert.throws(
    () => receiptView({ ...REPLY_RECEIPT, durable: [] }),
    /has no task row/,
    "a continuation without its task row",
  );
  assert.throws(
    () =>
      receiptView({
        ...REPLY_RECEIPT,
        durable: [{ perkId: continuationOpId(D), durableKind: "conversation", durableId: 3 }],
      }),
    /has no task row/,
    "a continuation row that is not a task",
  );
  const outcomeReceipt = receiptOf(ACCEPTED, acceptReportOpId(A));
  assert.throws(() => receiptView(outcomeReceipt), /is no door verb's receipt/);
});

test("V2: the host-outcome adapters", () => {
  const view: HostView & { readonly waitReason: "pending_decision" } = {
    records: { records: ACCEPTED, durableMap: new Map() },
    inspection: { scheduling: "paused", tasks: [], submissions: [] },
    wake: { active: false },
    endings: new Map([[A, accepted(A)]]),
    waitReason: "pending_decision",
  };
  assert.deepEqual(
    doorOutcomeOfRun({ kind: "quiescent", epoch: 5, receipt: REPLY_RECEIPT, view }),
    {
      kind: "view",
      epoch: 5,
      view: {
        records: ACCEPTED,
        live: [],
        runnable: false,
        endings: view.endings,
        waitReason: "pending_decision",
      },
      receipt: REPLY_RECEIPT,
    },
  );
  const status = doorOutcomeOfStatus({
    kind: "status",
    epoch: 6,
    view: { ...view, wake: { active: true }, waitReason: null },
  });
  assert.equal(status.kind, "view");
  assert.ok(status.kind === "view" && status.receipt === null && status.view.runnable);
  for (const passthrough of [
    { kind: "owner_busy", epoch: 2 },
    { kind: "incompatible", epoch: null, mismatch: MANIFEST_MISSING },
    { kind: "uncertain", epoch: 2, error: new Error("x") },
  ] as const) {
    assert.deepEqual(doorOutcomeOfRun(passthrough), passthrough);
    assert.deepEqual(doorOutcomeOfStatus(passthrough), passthrough);
  }
});

test("V2: the goldens cover every outcome and verb, and nothing else is committed", () => {
  const names = Object.keys(GOLDENS);
  assert.equal(names.length, 12);
  assert.deepEqual(
    [...new Set(Object.values(GOLDENS).map((golden) => build(golden).outcome))].sort(),
    [...DOOR_OUTCOMES].sort(),
  );
  assert.deepEqual([...new Set(Object.values(GOLDENS).map((golden) => golden.verb))].sort(), [
    "cancel",
    "reply",
    "run",
    "start",
    "status",
  ]);
  if (UPDATE) {
    for (const [name, golden] of Object.entries(GOLDENS)) {
      writeFileSync(join(GOLDEN_DIR, `${name}.json`), canonical(build(golden)));
    }
  }
  assert.deepEqual(
    readdirSync(GOLDEN_DIR).sort(),
    names.map((name) => `${name}.json`).sort(),
    "the golden directory holds exactly the twelve goldens",
  );
});

test("V2: the goldens are byte-pinned", () => {
  for (const [name, golden] of Object.entries(GOLDENS)) {
    const text = canonical(build(golden));
    if (UPDATE) writeFileSync(join(GOLDEN_DIR, `${name}.json`), text);
    assert.equal(readFileSync(join(GOLDEN_DIR, `${name}.json`), "utf8"), text, name);
  }
});
