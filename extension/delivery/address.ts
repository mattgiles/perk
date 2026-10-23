// The review-feedback finalization feature (the address half of the delivery pair), Pi-free.
//
// One entry point — `finalizeAddress` — owns the ordering and failure semantics of the
// submit-then-resolve loop: pre-effect refusals → publish (composing the sibling submit feature's
// `publishVerified` — one-way import, no cycle) → published-PR identity check → resolve →
// request↔row correlation → verified-success session record → the bounded conflict decision. The
// finalizer is bound to the session's held classification (`BoundThreads`, projected by the
// adapter): it resolves only classified thread ids, only on the classified PR, and records the
// PR + counts perk derived — never model-supplied facts. The decision
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
// (no per-thread claim) — so retry-without-rows is unrepresentable. `empty_batch`,
// `no_classification` and `unknown_threads` are the feature's pre-effect refusals.
// `published_pr_mismatch` is the post-publish arm where resolve is NEVER CALLED (no thread was
// touched; the push happened and is not undone), distinct from `published_unverified`, where
// resolve WAS called and its effects are unknown (replies/resolutions may have landed before the
// report was lost), so a retry needs inspection first. `bad_input`/`planning_session` stay adapter shapes —
// they never enter the outcome union.

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

/**
 * The slice of the held classification the finalizer binds to (projected by the adapter —
 * delivery/ stays independent of waves/): the PR the snapshot was fetched for, the counts perk
 * derived, and the classified thread ids.
 */
export interface BoundThreads {
  pr: number;
  counts: ReviewBatchCounts;
  thread_ids: readonly string[];
}

/** The finalization input: the decoded tool params + the session's held classification. */
export interface AddressFinalization {
  threads: ThreadInput[];
  /** Null when no classification is held in this activation (refused before any effect). */
  bound: BoundThreads | null;
}

export interface FinalizeAddressDeps extends PublishDeps {
  resolve: ResolveThreads;
  session: WorkflowSession;
}

export type FinalizeAddressOutcome =
  | { kind: "empty_batch"; message: string }
  | { kind: "no_classification"; message: string }
  | { kind: "unknown_threads"; unknownIds: string[]; message: string }
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
      /** The publish landed on a different PR than the classification is bound to. */
      kind: "published_pr_mismatch";
      change: PublishedChange;
      expected: number;
      actual: number;
      message: string;
    }
  | {
      kind: "completed";
      change: PublishedChange;
      results: ThreadResultRow[];
      resolvedThreadIds: string[];
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
 * precedence — safe on the partial/retry path, where the envelope already failed; the ok-arm
 * corroboration guard additionally refuses contradictory duplicates via `contradictedIds`).
 * Rows for never-requested ids are ignored.
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
 * Requested ids whose rows DISAGREE on `success` (version-skew evidence). A contradictory
 * duplicate must never corroborate a nominal success — last-row precedence would erase the
 * failure observation before the guard runs — so the ok-arm treats these as uncorroborated
 * and retries them with the reply stripped (both the resolve and the reply outcome are
 * unknowable from contradictory evidence).
 */
function contradictedIds(requested: ThreadInput[], rows: ThreadResultRow[]): Set<string> {
  const requestedIds = new Set(requested.map((input) => input.thread_id));
  const lastSuccess = new Map<string, boolean>();
  const contradicted = new Set<string>();
  for (const row of rows) {
    if (!requestedIds.has(row.thread_id)) continue;
    const prior = lastSuccess.get(row.thread_id);
    if (prior !== undefined && prior !== row.success) contradicted.add(row.thread_id);
    lastSuccess.set(row.thread_id, row.success);
  }
  return contradicted;
}

/**
 * The only safe automatic retry batch, derived from the fates: resolved threads are omitted; a
 * reply is retained ONLY on a positive not-posted report (`failed` with `replyPosted: false`);
 * an `unknown` fate is outcome-unknown, so its reply is stripped rather than risked twice. A
 * `contradicted` id (ok-arm only) is likewise outcome-unknown: retried with the reply stripped.
 */
function retryFromFates(
  fates: Map<string, { input: ThreadInput; fate: ThreadFate }>,
  contradicted: Set<string> = new Set(),
): ThreadInput[] {
  const retry: ThreadInput[] = [];
  for (const [id, { input, fate }] of fates) {
    const effective: ThreadFate = contradicted.has(id) ? { kind: "unknown" } : fate;
    if (effective.kind === "resolved") continue;
    if (effective.kind === "failed" && !effective.replyPosted && input.comment !== undefined) {
      retry.push({ thread_id: input.thread_id, comment: input.comment });
    } else {
      retry.push({ thread_id: input.thread_id });
    }
  }
  return retry;
}

const EMPTY_BATCH_MESSAGE = "no threads to finalize (pass { threads: [{thread_id, comment?}] })";

const NO_CLASSIFICATION_MESSAGE =
  "no bound classification in this session — call classify_review_feedback first " +
  "(finalize_address resolves only threads from the last classification)";

function unknownThreadsMessage(ids: string[]): string {
  return (
    `${ids.length} requested thread(s) are outside the bound classification: ` +
    `${ids.join(", ")} — re-run classify_review_feedback if the PR gained feedback, and pass ` +
    "only classified thread_ids"
  );
}

function prMismatchMessage(expected: number, actual: number): string {
  return (
    `propagation succeeded to PR #${actual}, but the classification is bound to PR ` +
    `#${expected}; threads were NOT resolved and nothing was recorded. The submit already ` +
    "succeeded. Re-run classify_review_feedback (it binds to the PR the worktree now resolves) " +
    "and finalize again."
  );
}

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
 * pre-effect refusals (empty batch → no held classification → ids outside it) fire before any
 * port; a failed publish returns with no resolve call, no session writes, and no counter
 * activity; a publish that landed on a PR other than the bound one resolves nothing and records
 * nothing (the mutation response is the one authoritative target identity, so this check is
 * necessarily post-publish); the batch record and the conflict decision happen ONLY after
 * corroborated full resolve success (never-burn-an-attempt). The record's classification is
 * ignored — the session seam owns loudness.
 */
export async function finalizeAddress(
  deps: FinalizeAddressDeps,
  input: AddressFinalization,
): Promise<FinalizeAddressOutcome> {
  if (input.threads.length === 0) {
    return { kind: "empty_batch", message: EMPTY_BATCH_MESSAGE };
  }
  const bound = input.bound;
  if (bound === null) {
    return { kind: "no_classification", message: NO_CLASSIFICATION_MESSAGE };
  }
  const classified = new Set(bound.thread_ids);
  const unknownIds = [
    ...new Set(input.threads.map((t) => t.thread_id).filter((id) => !classified.has(id))),
  ];
  if (unknownIds.length > 0) {
    return { kind: "unknown_threads", unknownIds, message: unknownThreadsMessage(unknownIds) };
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
  if (change.pr.number !== bound.pr) {
    return {
      kind: "published_pr_mismatch",
      change,
      expected: bound.pr,
      actual: change.pr.number,
      message: prMismatchMessage(bound.pr, change.pr.number),
    };
  }

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
  // thread (missing/failed/duplicate-CONTRADICTING rows under version skew route to partial —
  // nothing recorded, nothing termination-eligible).
  const contradicted = contradictedIds(input.threads, rows);
  const uncorroborated = [...fates.entries()].filter(
    ([id, { fate }]) => fate.kind !== "resolved" || contradicted.has(id),
  ).length;
  if (uncorroborated > 0) {
    const guardRetry = retryFromFates(fates, contradicted);
    const resolveMessage = `the resolve report did not corroborate ${uncorroborated} requested thread(s)`;
    return {
      kind: "published_partial",
      change,
      resolveMessage,
      message: resolveFailedMessage(resolveMessage, guardRetry.length > 0),
      errorType: "partial_failure",
      results: rows,
      resolvedThreadIds,
      retryThreads: guardRetry,
    };
  }

  // The mismatch arm already returned, so `bound.pr === change.pr.number` holds here.
  const record: ReviewBatchRecord = {
    pr: bound.pr,
    counts: bound.counts,
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
    conflict: decideConflictFollowUp(change, deps.attempts),
  };
}
