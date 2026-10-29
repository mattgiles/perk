// The attempt ending (docs/design/pi-durable-v2-foundations.md §12 the native assignment, §10 wait
// reasons): the native assignment task's typed terminal result, read back through the attempt's
// `launch` row.
//
// Invariants:
// - Diagnostic only. An ending explains an incomplete attempt and authorizes nothing (P6): it is
//   never a kernel record, and acceptance lives only in the report outcome record.
// - The parser is strict: any other shape — a fake task's `null` result included — is "no ending".
// - Reading endings is committed reads only (`getTask`), never a commit, so a status open may read
//   them.

import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import type { Harness, SubmissionRecord, TaskId } from "@earendil-works/pi-durable";
import { launchOpId } from "../kernel/identity.ts";
import { isRefusalReason, type RefusalReason } from "../kernel/refusal.ts";
import type { ReadRecordSet } from "./records.ts";

/** Why an attempt needs repair before it can progress; never a refusal of an operation. */
export const REPAIR_CAUSES = [
  "instructions_unrenderable",
  "capability_missing",
  "snapshot_tampered",
  "duplicate_conflict",
] as const;

export type RepairCause = (typeof REPAIR_CAUSES)[number];

/**
 * The code prefix of a report-tool refusal diagnostic, `perk.v2.refusal:<reason>`. Durable persists
 * a tool result's diagnostics on its `pi.tool-result` entry; only the report tool emits this prefix.
 */
export const REFUSAL_DIAGNOSTIC_PREFIX = "perk.v2.refusal:";

/** The submission statuses an ending can carry. */
export type SubmissionStatus = SubmissionRecord["status"];

export type AttemptEnding =
  | { readonly end: "accepted"; readonly outcomeId: string }
  | {
      readonly end: "incomplete";
      readonly submission: SubmissionStatus;
      readonly reason: string | null;
      /** The reason of the last report refusal in the worker transcript, or `null` when none. */
      readonly refusal: RefusalReason | null;
    }
  | { readonly end: "repair"; readonly cause: RepairCause; readonly detail: string };

const SUBMISSION_STATUSES: readonly string[] = ["queued", "placed", "done", "unanswered"];

function isPlainObject(value: unknown): value is { readonly [key: string]: unknown } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasExactKeys(value: object, keys: readonly string[]): boolean {
  const own = Object.keys(value).sort();
  const want = [...keys].sort();
  return own.length === want.length && own.every((key, i) => key === want[i]);
}

export function isRepairCause(value: unknown): value is RepairCause {
  return typeof value === "string" && (REPAIR_CAUSES as readonly string[]).includes(value);
}

function isSubmissionStatus(value: unknown): value is SubmissionStatus {
  return typeof value === "string" && SUBMISSION_STATUSES.includes(value);
}

/** `value` as an attempt ending, or `null` when it is any other shape. */
export function parseAttemptEnding(value: unknown): AttemptEnding | null {
  if (!isPlainObject(value)) return null;
  switch (value.end) {
    case "accepted": {
      const { outcomeId } = value;
      if (!hasExactKeys(value, ["end", "outcomeId"])) return null;
      if (typeof outcomeId !== "string" || outcomeId === "") return null;
      return { end: "accepted", outcomeId };
    }
    case "incomplete": {
      const { submission, reason, refusal } = value;
      if (!hasExactKeys(value, ["end", "submission", "reason", "refusal"])) return null;
      if (!isSubmissionStatus(submission)) return null;
      if (reason !== null && typeof reason !== "string") return null;
      if (refusal !== null && (typeof refusal !== "string" || !isRefusalReason(refusal))) {
        return null;
      }
      return { end: "incomplete", submission, reason, refusal };
    }
    case "repair": {
      const { cause, detail } = value;
      if (!hasExactKeys(value, ["end", "cause", "detail"])) return null;
      if (!isRepairCause(cause) || typeof detail !== "string") return null;
      return { end: "repair", cause, detail };
    }
    default:
      return null;
  }
}

/** A durable-map task id, re-branded at the one decoding boundary that stored it. */
function storedTaskId(durableId: number): TaskId {
  return durableId as TaskId;
}

/**
 * The ending of every attempt whose `launch` row names a terminal, `completed` task with a
 * parseable result, by attempt id. Committed reads only; it never commits.
 */
export async function readAttemptEndings(
  reader: Pick<Harness, "getTask">,
  read: ReadRecordSet,
): Promise<ReadonlyMap<string, AttemptEnding>> {
  const endings = new Map<string, AttemptEnding>();
  for (const record of read.records) {
    if (record.type !== "attempt") continue;
    const row = read.durableMap.get(launchOpId(record.attemptId));
    if (row === undefined || row.durableKind !== "task") continue;
    const task = await reader.getTask(storedTaskId(row.durableId), BACKGROUND_CONTEXT);
    if (task?.state.status !== "terminal" || task.state.outcome.status !== "completed") continue;
    const ending = parseAttemptEnding(task.state.outcome.result);
    if (ending !== null) endings.set(record.attemptId, ending);
  }
  return endings;
}
