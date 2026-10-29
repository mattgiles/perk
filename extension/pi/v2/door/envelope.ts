// The door envelope (docs/design/pi-durable-v2-foundations.md §11, contracts.md §8.77): the one
// versioned JSON result of a host CLI call, built from a host outcome. Python validates it with
// strict wire models (`src/perk/v2/envelope.py`), so its keys, their order and every variant's
// null fields are a cross-plane contract; the committed goldens under `golden/` pin them.
//
// Invariants:
// - Every key is always present, in one fixed order; a field an outcome does not set is `null`.
// - `ok` describes the door call: a quiescent `start`, `run` or `reply` whose wait reason is
//   `pending_decision` is `pending_decision`, every other consistent view is `ok`, `status`
//   included.
// - `incompatible` and `uncertain` carry a marker snapshot, so the snapshot alone distinguishes
//   every §11 state; `owner_busy`, `observation_failed` and `refused` carry none.
// - The receipt is the verb's own: a reply's (with the continuation task it created) or a
//   cancel's. A receipt of any other kind, or a continuation with no task row, is a binding bug
//   and throws, never an outcome.

import type { BindingReceipt } from "../durable/operate.ts";
import type { HostMismatch, HostRunOutcome, HostStatusOutcome, HostView } from "../host.ts";
import type { Refusal } from "../kernel/refusal.ts";
import { type Snapshot, type SnapshotInput, statusSnapshot } from "./snapshot.ts";

export const ENVELOPE_VERSION = 1;

export const DOOR_VERBS = ["start", "run", "status", "reply", "cancel"] as const;
export type DoorVerb = (typeof DOOR_VERBS)[number];

export const DOOR_OUTCOMES = [
  "ok",
  "pending_decision",
  "owner_busy",
  "incompatible",
  "observation_failed",
  "refused",
  "uncertain",
] as const;
export type EnvelopeOutcome = (typeof DOOR_OUTCOMES)[number];

export type ReceiptView = {
  readonly opId: string;
  readonly kind: "reply" | "cancellation";
  readonly continuation: { readonly opId: string; readonly taskId: number } | null;
};

export type Envelope = {
  readonly envelope: typeof ENVELOPE_VERSION;
  readonly outcome: EnvelopeOutcome;
  readonly verb: DoorVerb;
  readonly executionId: string;
  readonly epoch: number | null;
  readonly status: Snapshot | null;
  readonly receipt: ReceiptView | null;
  readonly refusal: Refusal | null;
  readonly mismatch: HostMismatch | null;
  readonly error: { readonly message: string } | null;
};

/** A host outcome as the door sees it: a consistent view, or one of the five other outcomes. */
export type DoorOutcome =
  | {
      readonly kind: "view";
      readonly epoch: number;
      readonly view: SnapshotInput;
      readonly receipt: BindingReceipt | null;
    }
  | { readonly kind: "owner_busy"; readonly epoch: number }
  | {
      readonly kind: "incompatible";
      readonly epoch: number | null;
      readonly mismatch: HostMismatch;
    }
  | { readonly kind: "observation_failed"; readonly epoch: number; readonly detail: string }
  | { readonly kind: "refused"; readonly epoch: number; readonly refusal: Refusal }
  | { readonly kind: "uncertain"; readonly epoch: number; readonly error: unknown };

function snapshotInput(view: HostView): SnapshotInput {
  return {
    records: view.records.records,
    live: view.inspection.tasks.map((task) => task.state),
    runnable: view.wake.active,
    endings: view.endings,
    waitReason: view.waitReason,
  };
}

/** A run outcome as a door outcome. */
export function doorOutcomeOfRun(outcome: HostRunOutcome): DoorOutcome {
  if (outcome.kind === "quiescent") {
    return {
      kind: "view",
      epoch: outcome.epoch,
      view: snapshotInput(outcome.view),
      receipt: outcome.receipt,
    };
  }
  return outcome;
}

/** A status outcome as a door outcome; a status view carries no receipt. */
export function doorOutcomeOfStatus(outcome: HostStatusOutcome): DoorOutcome {
  if (outcome.kind === "status") {
    return { kind: "view", epoch: outcome.epoch, view: snapshotInput(outcome.view), receipt: null };
  }
  return outcome;
}

/** The receipt as the envelope carries it; throws for a receipt kind no verb returns. */
export function receiptView(receipt: BindingReceipt): ReceiptView {
  const type = receipt.record.type;
  if (type !== "reply" && type !== "cancellation") {
    throw new Error(`a ${type} receipt is no door verb's receipt (${receipt.opId})`);
  }
  const { continuation } = receipt;
  if (continuation === null) return { opId: receipt.opId, kind: type, continuation: null };
  const row = receipt.durable.find(
    (entry) => entry.perkId === continuation.opId && entry.durableKind === "task",
  );
  if (row === undefined) {
    throw new Error(`receipt ${receipt.opId} has no task row for ${continuation.opId}`);
  }
  return {
    opId: receipt.opId,
    kind: type,
    continuation: { opId: continuation.opId, taskId: row.durableId },
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function mismatchView(mismatch: HostMismatch): HostMismatch {
  return mismatch.field === "manifest_missing"
    ? { field: "manifest_missing", expected: null, found: null }
    : { field: mismatch.field, expected: mismatch.expected, found: mismatch.found };
}

type EnvelopeFields = Partial<
  Pick<Envelope, "status" | "receipt" | "refusal" | "mismatch" | "error">
>;

/** The envelope of `verb` over execution `executionId`, built at wall-clock `now` (ms). */
export function envelopeOf(
  verb: DoorVerb,
  executionId: string,
  outcome: DoorOutcome,
  now: number,
): Envelope {
  const envelope = (name: EnvelopeOutcome, fields: EnvelopeFields): Envelope => ({
    envelope: ENVELOPE_VERSION,
    outcome: name,
    verb,
    executionId,
    epoch: outcome.epoch,
    status: null,
    receipt: null,
    refusal: null,
    mismatch: null,
    error: null,
    ...fields,
  });
  switch (outcome.kind) {
    case "view": {
      const pending = verb !== "status" && outcome.view.waitReason === "pending_decision";
      return envelope(pending ? "pending_decision" : "ok", {
        status: statusSnapshot(outcome.view, now),
        receipt: outcome.receipt === null ? null : receiptView(outcome.receipt),
      });
    }
    case "owner_busy":
      return envelope("owner_busy", {});
    case "incompatible":
      return envelope("incompatible", {
        status: { state: "incompatible" },
        mismatch: mismatchView(outcome.mismatch),
      });
    case "observation_failed":
      return envelope("observation_failed", { error: { message: outcome.detail } });
    case "refused":
      return envelope("refused", {
        refusal: { reason: outcome.refusal.reason, detail: outcome.refusal.detail },
      });
    case "uncertain":
      return envelope("uncertain", {
        status: { state: "uncertain" },
        error: { message: errorMessage(outcome.error) },
      });
  }
}
