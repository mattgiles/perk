// The binding's one commit operation, its outcome classification and receipt lookup
// (docs/design/pi-durable-v2-foundations.md §6 receipt lookup, §7 the write contract and the
// binding, §9 classification).
//
// Invariants:
// - `operate(input?)` is one commit: load the presented set, `evaluateOperation`, then persist the
//   result in that same commit — `recorded`, then each action's record in order, exactly as the
//   kernel's reference applier `nextRecords`. The binding checks nothing before evaluation, so the
//   kernel's receipt lookup stays first.
// - Every Durable object the commit creates (the launched attempt task, the continuation task) is
//   mapped to its Perk id in that same commit.
// - A rejected commit is `uncertain` when the Harness has failed, `refused` for a `KernelRefusal`,
//   and otherwise a thrown `BindingFault` carrying the original rejection. A fault records nothing
//   and is never a refusal.

import { copyJson } from "@earendil-works/chord";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import {
  type ConversationId,
  type DocumentReader,
  type Harness,
  SessionFailed,
  type TaskId,
  type Tx,
} from "@earendil-works/pi-durable";
import type { FixturePolicy } from "../kernel/fixture.ts";
import { continuationOpId, launchOpId } from "../kernel/identity.ts";
import {
  type Action,
  evaluateOperation,
  nextRecords,
  type Operation,
  type Receipt,
  receiptFor,
} from "../kernel/reconcile.ts";
import {
  type AssignmentRecord,
  type AttemptRecord,
  indexRecords,
  KernelInvariantError,
  type KernelRecord,
  type ObservationRecord,
  type OperationRecord,
} from "../kernel/records.ts";
import { KernelRefusal, type Refusal } from "../kernel/refusal.ts";
import { ContinuationTask } from "./continuation.ts";
import { DurableMapFamily, familyForOpKind, opKindOf } from "./documents.ts";
import {
  asDurableMapRow,
  asKernelRecord,
  type DurableMapRow,
  loadRecords,
  projectContinuation,
} from "./records.ts";

/** What `start-attempt` hands the host's launcher: the attempt and the facts its work needs. */
export type AttemptLaunch = {
  readonly attempt: AttemptRecord;
  readonly assignment: AssignmentRecord;
  readonly latest: ObservationRecord;
  readonly executionConversationId: ConversationId;
};

/**
 * The host-supplied seam that starts an attempt's work. Contract: it runs inside the reconcile
 * commit, after the attempt record is staged, and creates exactly one Durable task — the attempt's
 * work — whose id it returns. It performs no table reads (it may run after the commit's first table
 * write, where a read throws `ReadAfterWrite`), and it writes no v2 document: the binding writes the
 * attempt's `launch` row. A throw is a binding fault.
 */
export type AttemptLauncher = (tx: Tx, launch: AttemptLaunch) => Promise<TaskId>;

export type BindingDeps = { readonly policy: FixturePolicy; readonly launcher: AttemptLauncher };

/** Every operation a caller commits; the input-less `step` is `operate()` with no input. */
export type CommitInput = Exclude<Operation, { readonly type: "step" }>;

/** A kernel receipt plus the durable-map rows of the result ids its record derives. */
export type BindingReceipt = Receipt & {
  readonly durable: readonly ({ readonly perkId: string } & DurableMapRow)[];
};

export type OperateOutcome =
  | {
      readonly kind: "applied";
      readonly recorded: readonly KernelRecord[];
      readonly actions: readonly Action[];
      readonly receipt: BindingReceipt | null;
    }
  | { readonly kind: "replayed"; readonly receipt: BindingReceipt }
  | { readonly kind: "refused"; readonly refusal: Refusal }
  | { readonly kind: "uncertain"; readonly error: unknown };

/** The Harness the caller holds open, its execution conversation, and the host's dependencies. */
export type BindingTarget = {
  readonly harness: Harness;
  readonly executionConversationId: ConversationId;
  readonly deps: BindingDeps;
};

/** A rejection that is neither a refusal nor uncertain: a binding or caller bug. */
export class BindingFault extends Error {
  constructor(cause: unknown) {
    super(`binding fault: ${cause instanceof Error ? cause.message : String(cause)}`, { cause });
    this.name = "BindingFault";
  }
}

const STEP: Operation = { type: "step" };

/** The Perk ids whose durable-map rows a receipt of `record` carries. */
function resultIds(record: OperationRecord): string[] {
  switch (record.type) {
    case "reply":
      return [continuationOpId(record.decisionId)];
    case "continuation":
      return [record.opId];
    case "attempt":
      return [launchOpId(record.attemptId)];
    default:
      return [];
  }
}

function bindingReceipt(
  receipt: Receipt,
  durableMap: ReadonlyMap<string, DurableMapRow>,
): BindingReceipt {
  const durable = resultIds(receipt.record).flatMap((perkId) => {
    const row = durableMap.get(perkId);
    return row === undefined
      ? []
      : [{ perkId, durableKind: row.durableKind, durableId: row.durableId }];
  });
  return { ...receipt, durable };
}

/**
 * Run one operation inside an open commit: the body of `operate`, and of the step task's own
 * commit. A refusal throws `KernelRefusal` so the commit rolls back; a malformed record set throws
 * `KernelInvariantError`. Every returned value is a plain copy, safe after the callback.
 */
export async function operateInTx(
  tx: Tx,
  input: CommitInput | undefined,
  deps: BindingDeps,
  executionConversationId: ConversationId,
): Promise<Extract<OperateOutcome, { readonly kind: "applied" | "replayed" }>> {
  const set = await loadRecords(tx);
  const result = evaluateOperation(set.records, input ?? STEP, deps.policy);
  if (result.kind === "refused") throw new KernelRefusal(result.refusal);
  if (result.kind === "replayed") {
    return { kind: "replayed", receipt: bindingReceipt(result.receipt, set.durableMap) };
  }
  const after = indexRecords(nextRecords(set.records, result));
  for (const record of result.recorded) await set.write(record);
  for (const action of result.actions) {
    switch (action.type) {
      case "admit":
      case "aggregate":
      case "open-decision":
        await set.write(action.record);
        break;
      case "start-attempt": {
        const attempt = action.record;
        await set.write(attempt);
        const assignment = after.assignments.get(attempt.assignmentId);
        const latest = after.latest;
        if (assignment === undefined || latest === null) {
          throw new KernelInvariantError(
            `${attempt.opId}: started without its assignment or an observation`,
          );
        }
        const taskId = await deps.launcher(tx, {
          attempt,
          assignment,
          latest,
          executionConversationId,
        });
        await set.writeRow(launchOpId(attempt.attemptId), {
          durableKind: "task",
          durableId: taskId,
        });
        break;
      }
      case "continue": {
        const taskId = await tx.createTask(
          ContinuationTask,
          { decisionId: action.record.decisionId },
          {
            ownership: { kind: "conversation" },
            conversationId: executionConversationId,
            background: true,
          },
        );
        await set.writeRow(action.record.opId, { durableKind: "task", durableId: taskId });
        break;
      }
    }
  }
  return {
    kind: "applied",
    recorded: result.recorded,
    actions: result.actions,
    receipt: result.receipt === null ? null : bindingReceipt(result.receipt, set.durableMap),
  };
}

/**
 * Whether the Harness has failed, read through a no-op probe commit: `true` iff the probe rejects
 * with `SessionFailed`. The probe only reports the failure latch, which a failed storage call sets
 * before its rejection reaches anyone. A closing or closed Harness is not a failed one — close lets
 * admitted commits settle and never runs a refused commit's callback — so any other probe rejection
 * (Durable's plain closed error) means "not failed", and the caller classifies the original
 * rejection. In a healthy Harness the probe writes nothing.
 */
async function harnessFailed(harness: Harness): Promise<boolean> {
  try {
    await harness.commit(() => undefined, BACKGROUND_CONTEXT);
    return false;
  } catch (probe) {
    return probe instanceof SessionFailed;
  }
}

/**
 * Run one operation as its own commit and classify the result: `applied` / `replayed` from the
 * commit, `refused` for a `KernelRefusal`, `uncertain` when the Harness has failed (whatever the
 * rejection — the conservative answer wins), and a thrown `BindingFault` for anything else.
 *
 * Requires a Harness the caller still holds open: on a closed one the commit is refused admission,
 * which is a `BindingFault` carrying Durable's closed error. Never await `operate` inside a commit
 * callback — it queues behind that very commit; use `operateInTx` there.
 */
export async function operate(target: BindingTarget, input?: CommitInput): Promise<OperateOutcome> {
  const { harness, deps, executionConversationId } = target;
  try {
    return await harness.commit(
      (tx) => operateInTx(tx, input, deps, executionConversationId),
      BACKGROUND_CONTEXT,
    );
  } catch (error) {
    if (error instanceof SessionFailed || (await harnessFailed(harness))) {
      return { kind: "uncertain", error };
    }
    if (error instanceof KernelRefusal) {
      return { kind: "refused", refusal: { reason: error.reason, detail: error.detail } };
    }
    throw new BindingFault(error);
  }
}

/**
 * The receipt recorded under `opId`, read outside commits (after a reopen, before resuming). It
 * addresses the one family the op id's kind names, through `snapshot()`, without the catalog, and
 * composes the kernel's `receiptFor` over what it finds. `null` when nothing is recorded under it —
 * a garbage id, or a `launch` id (a launch row is reached through its attempt's receipt).
 */
export async function lookupReceipt(
  reader: DocumentReader,
  opId: string,
): Promise<BindingReceipt | null> {
  const kind = opKindOf(opId);
  if (kind === null || kind === "launch") return null;
  const family = familyForOpKind(kind);
  const stored = await reader.snapshot(family, opId, BACKGROUND_CONTEXT);
  if (stored === undefined) return null;
  const durableMap = new Map<string, DurableMapRow>();
  const readRow = async (perkId: string): Promise<DurableMapRow | undefined> => {
    const known = durableMap.get(perkId);
    if (known !== undefined) return known;
    const value = await reader.snapshot(DurableMapFamily, perkId, BACKGROUND_CONTEXT);
    if (value === undefined) return undefined;
    const row = asDurableMapRow(perkId, value);
    durableMap.set(perkId, row);
    return row;
  };
  const records: KernelRecord[] = [];
  if (kind === "continuation") {
    durableMap.set(opId, asDurableMapRow(opId, stored));
    records.push(projectContinuation(opId));
  } else {
    const record = asKernelRecord(family.definition.kind, opId, copyJson(stored));
    records.push(record);
    if (record.type === "reply") {
      const continuation = continuationOpId(record.decisionId);
      if ((await readRow(continuation)) !== undefined)
        records.push(projectContinuation(continuation));
    }
  }
  const receipt = receiptFor(records, opId);
  if (receipt === null) return null;
  for (const perkId of resultIds(receipt.record)) await readRow(perkId);
  return bindingReceipt(receipt, durableMap);
}
