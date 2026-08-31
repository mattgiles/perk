// The review-feedback finalization feature (the address half of the delivery pair), Pi-free.
//
// One entry point — `finalizeAddress` — owns the ordering and failure semantics of the
// submit-then-resolve loop: pre-effect refusal (empty batch) → publish (composing the sibling
// submit feature's `publishVerified` — one-way import, no cycle) → resolve → request↔row
// correlation → verified-success session record → the bounded conflict decision. The decision
// timing is deliberately DIFFERENT from `/submit`'s: it runs only after full corroborated
// resolve success — a resolve failure never burns an attempt.
//
// Uncertainty is a first-class value: one module-private correlation pass derives a
// per-requested-thread fate — `resolved` | `failed` (with the positively-reported reply fact) |
// `unknown` (no row: the effect may have happened, verification failed) — consumed by (a) the
// safe-retry derivation (a reply is retained ONLY on a positive not-posted report) and (b) the
// ok-arm corroboration guard (a nominal-success envelope that fails to corroborate every
// requested thread is `published_partial`, never recorded/terminated — contracts §8.52: "full
// success" = corroborated per-thread success). The two unresolved states are DISTINCT
// discriminants — `published_partial` (rows known, retry derivable) and `published_unverified`
// (no per-thread claim) — so retry-without-rows is unrepresentable. Refusals (`bad_input`,
// `planning_session`) are adapter shapes — they never enter the outcome union.

import type {
  ReviewBatchCounts,
  ReviewBatchRecord,
  WorkflowSession,
} from "../session/workflowSession.ts";
import {
  type ConflictFollowUp,
  decideConflictFollowUp,
  type PublishDeps,
  type PublishedChange,
  publishVerified,
} from "./submit.ts";

export interface ThreadInput {
  thread_id: string;
  comment?: string;
}

/** One per-thread outcome row from the resolve port's batch result. */
export interface ThreadResultRow {
  thread_id: string;
  success: boolean;
  comment_added: boolean;
  error?: string | null;
}

/** One external resolve attempt: full rows, a partial report with rows, or an uncertain fail. */
export type ResolveThreadsAttempt =
  | { ok: true; rows: ThreadResultRow[] }
  | { ok: false; kind: "partial"; rows: ThreadResultRow[]; message: string; errorType: string }
  | { ok: false; kind: "failed"; message: string; errorType: string };

/** The resolve port — production = `perk pr resolve-threads --json --batch`. */
export type ResolveThreads = (threads: ThreadInput[]) => Promise<ResolveThreadsAttempt>;

/** The finalization input (the adapter's decoded tool params). */
export interface AddressFinalization {
  threads: ThreadInput[];
  pr?: number;
  counts?: ReviewBatchCounts;
}

export interface FinalizeAddressDeps extends PublishDeps {
  resolve: ResolveThreads;
  session: WorkflowSession;
}

export type FinalizeAddressOutcome =
  | { kind: "empty_batch"; message: string }
  | {
      kind: "not_published";
      /** The raw publisher failure — the adapter reproduces today's scope-"submit" report. */
      publishMessage: string;
      message: string;
      errorType: string;
    }
  | {
      kind: "published_partial";
      change: PublishedChange;
      resolveMessage: string;
      message: string;
      errorType: string;
      results: ThreadResultRow[];
      resolvedThreadIds: string[];
      /** Possibly empty — the adapter omits retry_threads when empty (today's wire). */
      retryThreads: ThreadInput[];
    }
  | {
      kind: "published_unverified";
      change: PublishedChange;
      resolveMessage: string;
      message: string;
      errorType: string;
    }
  | {
      kind: "completed";
      change: PublishedChange;
      results: ThreadResultRow[];
      resolvedThreadIds: string[];
      record: ReviewBatchRecord;
      conflict: ConflictFollowUp;
    };

/** One requested thread's correlated fate (module-private — never exported). */
type ThreadFate =
  | { kind: "resolved" }
  | { kind: "failed"; replyPosted: boolean }
  | { kind: "unknown" };

/**
 * The one correlation pass: requested ids deduped by FIRST occurrence; the row lookup is built
 * `new Map(rows.map(...))` so a duplicate row's LAST observation wins (today's exact
 * precedence). Rows for never-requested ids are ignored.
 */
function correlateFates(
  requested: ThreadInput[],
  rows: ThreadResultRow[],
): Map<string, { input: ThreadInput; fate: ThreadFate }> {
  const byId = new Map(rows.map((row) => [row.thread_id, row]));
  const fates = new Map<string, { input: ThreadInput; fate: ThreadFate }>();
  for (const input of requested) {
    if (fates.has(input.thread_id)) continue;
    const row = byId.get(input.thread_id);
    const fate: ThreadFate =
      row === undefined
        ? { kind: "unknown" }
        : row.success
          ? { kind: "resolved" }
          : { kind: "failed", replyPosted: row.comment_added };
    fates.set(input.thread_id, { input, fate });
  }
  return fates;
}

/**
 * The only safe automatic retry batch, derived from the fates: resolved threads are omitted; a
 * reply is retained ONLY on a positive not-posted report (`failed` with `replyPosted: false`);
 * an `unknown` fate is outcome-unknown, so its reply is stripped rather than risked twice.
 */
function retryFromFates(
  fates: Map<string, { input: ThreadInput; fate: ThreadFate }>,
): ThreadInput[] {
  const retry: ThreadInput[] = [];
  for (const { input, fate } of fates.values()) {
    if (fate.kind === "resolved") continue;
    if (fate.kind === "failed" && !fate.replyPosted && input.comment !== undefined) {
      retry.push({ thread_id: input.thread_id, comment: input.comment });
    } else {
      retry.push({ thread_id: input.thread_id });
    }
  }
  return retry;
}

const EMPTY_BATCH_MESSAGE = "no threads to finalize (pass { threads: [{thread_id, comment?}] })";

const INSPECT_GUIDANCE =
  "Inspect the resolution failure before retrying; omit any reply that may already have posted.";
const RETRY_GUIDANCE =
  "Re-run finalize_address with only details.retry_threads; successful rows were omitted " +
  "and replies already reported as posted were stripped.";

function resolveFailedMessage(resolveMessage: string, retryable: boolean): string {
  return (
    `propagation succeeded, but thread resolution failed: ${resolveMessage}. ` +
    `The submit already succeeded. ${retryable ? RETRY_GUIDANCE : INSPECT_GUIDANCE}`
  );
}

/** All success rows, in row order (the wire's `resolved_thread_ids` — row-derived, not fates). */
function resolvedIdsOf(rows: ThreadResultRow[]): string[] {
  return rows.filter((row) => row.success).map((row) => row.thread_id);
}

/**
 * Publish committed address fixes, then resolve their review threads. Ordering policy: the
 * empty refusal fires before any port; a failed publish returns with no resolve call, no
 * session writes, and no counter activity; the batch record and the conflict decision happen
 * ONLY after corroborated full resolve success (never-burn-an-attempt). The record's
 * classification is ignored — the session seam owns loudness.
 */
export async function finalizeAddress(
  deps: FinalizeAddressDeps,
  input: AddressFinalization,
): Promise<FinalizeAddressOutcome> {
  if (input.threads.length === 0) {
    return { kind: "empty_batch", message: EMPTY_BATCH_MESSAGE };
  }

  const published = await publishVerified(deps);
  if (!published.ok) {
    return {
      kind: "not_published",
      publishMessage: published.message,
      message:
        `propagation failed; threads were NOT resolved — ${published.message}. ` +
        "Fix the publication failure, then re-run finalize_address.",
      errorType: published.errorType,
    };
  }
  const change = published.change;

  const resolved = await deps.resolve(input.threads);
  if (!resolved.ok && resolved.kind === "failed") {
    return {
      kind: "published_unverified",
      change,
      resolveMessage: resolved.message,
      message: resolveFailedMessage(resolved.message, false),
      errorType: resolved.errorType,
    };
  }

  const rows = resolved.rows;
  const fates = correlateFates(input.threads, rows);
  const retryThreads = retryFromFates(fates);
  const resolvedThreadIds = resolvedIdsOf(rows);

  if (!resolved.ok) {
    return {
      kind: "published_partial",
      change,
      resolveMessage: resolved.message,
      message: resolveFailedMessage(resolved.message, retryThreads.length > 0),
      errorType: resolved.errorType,
      results: rows,
      resolvedThreadIds,
      retryThreads,
    };
  }

  // The ok-arm corroboration guard: a nominal-success envelope must corroborate EVERY requested
  // thread (missing/failed/duplicate-conflicting rows under version skew route to partial —
  // nothing recorded, nothing termination-eligible).
  const uncorroborated = [...fates.values()].filter(({ fate }) => fate.kind !== "resolved").length;
  if (uncorroborated > 0) {
    const resolveMessage = `the resolve report did not corroborate ${uncorroborated} requested thread(s)`;
    return {
      kind: "published_partial",
      change,
      resolveMessage,
      message: resolveFailedMessage(resolveMessage, retryThreads.length > 0),
      errorType: "partial_failure",
      results: rows,
      resolvedThreadIds,
      retryThreads,
    };
  }

  const record: ReviewBatchRecord = {
    pr: input.pr ?? null,
    counts: input.counts ?? null,
    resolved_thread_ids: resolvedThreadIds,
    at: new Date().toISOString(),
  };
  // Classification deliberately ignored: the seam reports its own read-back warnings, and a
  // recording miss must never sink an already-corroborated resolve success.
  deps.session.apply({ kind: "record-review-batch", record });

  return {
    kind: "completed",
    change,
    results: rows,
    resolvedThreadIds,
    record,
    conflict: decideConflictFollowUp(change, deps.attempts),
  };
}
