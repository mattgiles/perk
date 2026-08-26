// The curated-submission flow (contracts §8.4's per-door posting contract) — the typed feature
// operation behind the warm `submit_pr_review` tool: nothing perk-driven reaches GitHub before
// the human triage; the verdict lands last, atomically with the comments. This module owns the
// POLICY: the enforced `already_posted` resume guard over the `review_posts` ledger (presence
// refuses; absence is NOT proof — the ledger is best-effort), the formal-event gate ladder
// (headless refuses, interactive confirms, `comment` posts on the conversational go-ahead
// alone), the `dry_run` anchor-repair loop's bypass of both gates, and the two session records
// a real success always attempts (`record-review` then `append-review-post`, unconditionally in
// that order, ignoring both classifications — the session seam owns loudness).
//
// Pi-free by construction (importDirectionGuard Rule D): the Pi adapter
// (`pi/v1/codeReview/submit.ts`) owns registration, tool-boundary decode, the cold-door
// composition, and Result rendering; this module sees only the ports below.

import type {
  ReviewPostRow,
  ReviewSubmissionRecord,
  WorkflowSession,
} from "../session/workflowSession.ts";

// ------------------------------------------------------------------------ vocabulary

export type ReviewEvent = "approve" | "request-changes" | "comment";

/** One curated inline comment (the exact `review-submit --batch` `comments[]` row). */
export interface SubmitComment {
  path: string;
  line: number;
  side?: "LEFT" | "RIGHT";
  body: string;
}

/** The cold door's ok-arm fields (the `review-submit --json` surface; render-only → lenient). */
export interface SubmitOk {
  dry_run?: boolean;
  pr?: number;
  event?: string;
  mode?: string;
  comment_count?: number;
}

/** One `bad_anchors` `invalid[]` row (the cold door's per-comment repair detail). */
export interface InvalidAnchor {
  index: number;
  path: string;
  line: number;
  side: string;
  reason: string;
}

/** The feature input (booleans normalized at the adapter decode). */
export interface CuratedSubmission {
  pr: number;
  event: ReviewEvent;
  body: string;
  comments?: SubmitComment[];
  dryRun: boolean;
  allowRepost: boolean;
}

/**
 * The posting port's input — deliberately WITHOUT `allowRepost`: that flag is feature ledger
 * policy and never crosses the posting boundary.
 */
export interface SubmitBatch {
  pr: number;
  event: ReviewEvent;
  body: string;
  comments?: SubmitComment[];
  dryRun: boolean;
}

// ------------------------------------------------------------------------ ports

/**
 * The posting outcome: `bad_anchors` carries the strict-decoded repair rows (decode drift ⇒ the
 * `failed` arm — uncertainty renders plain, never a half table). `errorType` is required on the
 * `failed` arm — the cold-door seam always supplies it.
 */
export type ReviewSubmitOutcome =
  | { ok: true; data: SubmitOk }
  | { ok: false; kind: "bad_anchors"; invalid: InvalidAnchor[]; message: string }
  | { ok: false; kind: "failed"; message: string; errorType: string };

/** The external posting role (production: the `perk pr review-submit` cold-door composition). */
export interface ReviewSubmitter {
  submit(batch: SubmitBatch): Promise<ReviewSubmitOutcome>;
}

/**
 * The formal-event human gate — a discriminated union, so the unsafe call is unrepresentable:
 * a headless gate HAS no confirm to invoke. Production: `ctx.hasUI` selects the arm; the
 * interactive arm wraps `ctx.ui.confirm`.
 */
export type FormalEventGate =
  | { kind: "headless" }
  | { kind: "interactive"; confirm(question: string, summary: string): Promise<boolean> };

// ------------------------------------------------------------------------ the result union

/** The enumerated curated-submission outcome; every arm carries its policy-owned message text. */
export type SubmitCuratedOutcome =
  | { kind: "already_posted"; prior: ReviewPostRow; message: string }
  | { kind: "headless_formal_event"; message: string }
  | { kind: "user_declined"; message: string }
  | { kind: "bad_anchors"; invalid: InvalidAnchor[]; message: string }
  | { kind: "submit_failed"; message: string; errorType: string }
  | { kind: "dry_run_ok"; data: SubmitOk }
  | { kind: "posted"; data: SubmitOk; record: ReviewSubmissionRecord; row: ReviewPostRow };

/** Flag spelling → the REST wire spelling shown in the human confirm. */
const WIRE_EVENT: Record<ReviewEvent, string> = {
  approve: "APPROVE",
  "request-changes": "REQUEST_CHANGES",
  comment: "COMMENT",
};

/** The body's first line, truncated for the confirm-dialog summary. */
function bodyFirstLine(body: string): string {
  const line = body.split("\n", 1)[0] ?? "";
  return line.length > 120 ? `${line.slice(0, 117)}…` : line;
}

// ------------------------------------------------------------------------ the operation

/**
 * Submit the human-curated review batch to the foreign PR. Policy order (exactly): the resume
 * guard (skipped on `dryRun`/`allowRepost`; refusal on a prior ledger row for the PR — absence
 * is NOT proof of no post) → the formal-event gate (skipped on `dryRun` and for `comment`; the
 * headless arm refuses; a decline executes nothing) → the posting port → on a real success the
 * two session records, `record-review` then `append-review-post`, unconditionally in that order,
 * ignoring both classifications (the seam owns loudness).
 */
export async function submitCuratedReview(
  input: CuratedSubmission,
  deps: { submitter: ReviewSubmitter; gate: FormalEventGate; session: WorkflowSession },
): Promise<SubmitCuratedOutcome> {
  const commentCount = input.comments?.length ?? 0;

  // The enforced resume guard (before the confirm AND the cold-door mutation): a PR that
  // already has a review_posts ledger row in this session is a confirmed success — a repeat
  // real post is refused unless explicitly deliberate. A ledger row can only be MISSING
  // spuriously (best-effort tier), never present spuriously — so the guard refuses on
  // presence and stays silent on absence (a missing row still means: verify posted-vs-pending
  // against GitHub before re-posting).
  if (!input.dryRun && !input.allowRepost) {
    const prior = deps.session.reviewPosts().filter((row) => row.pr === input.pr);
    const last = prior.at(-1);
    if (last !== undefined) {
      return {
        kind: "already_posted",
        prior: last,
        message:
          `a ${last.event} review was already posted to PR #${input.pr} in this session ` +
          `(review_posts row at ${last.at}) — on a stack resume skip this member; pass ` +
          "allow_repost: true only for a deliberate second review of the same PR",
      };
    }
  }

  if (!input.dryRun && input.event !== "comment") {
    if (deps.gate.kind === "headless") {
      return {
        kind: "headless_formal_event",
        message:
          "headless sessions cannot post formal review verdicts — re-run interactively or use " +
          "event: comment",
      };
    }
    const wire = WIRE_EVENT[input.event];
    const firstLine = bodyFirstLine(input.body);
    const summary =
      `event: ${wire} · ${commentCount} inline comment(s)` +
      (firstLine.length > 0 ? `\nbody: ${firstLine}` : "");
    const yes = await deps.gate.confirm(`Post ${wire} review to PR #${input.pr}?`, summary);
    if (!yes) {
      return {
        kind: "user_declined",
        message: `user declined the ${input.event} review — nothing was submitted`,
      };
    }
  }

  const batch: SubmitBatch = {
    pr: input.pr,
    event: input.event,
    body: input.body,
    ...(input.comments !== undefined ? { comments: input.comments } : {}),
    dryRun: input.dryRun,
  };
  const outcome = await deps.submitter.submit(batch);

  if (!outcome.ok) {
    if (outcome.kind === "bad_anchors") {
      // The repair-loop arm: render the per-comment invalid[] detail (rows already strict-
      // decoded by the adapter — a drifting payload arrived as the `failed` arm instead).
      const table = outcome.invalid
        .map(
          (row) => `  comment[${row.index}] ${row.path}:${row.line} (${row.side}) — ${row.reason}`,
        )
        .join("\n");
      return {
        kind: "bad_anchors",
        invalid: outcome.invalid,
        message: `${outcome.message}\n${table}\nrepair these anchors and re-run with dry_run: true`,
      };
    }
    return { kind: "submit_failed", message: outcome.message, errorType: outcome.errorType };
  }

  if (input.dryRun) return { kind: "dry_run_ok", data: outcome.data };

  // Record the outcome (best-effort tier, seam-reported): record-review then append-review-post,
  // BOTH always attempted, in that order, ignoring both classifications — the submission already
  // succeeded and the seam owns the loud read-back warnings.
  const record: ReviewSubmissionRecord = {
    pr: outcome.data.pr ?? input.pr,
    event: input.event,
    comment_count: outcome.data.comment_count ?? null,
    mode: outcome.data.mode ?? null,
    at: new Date().toISOString(),
  };
  const row: ReviewPostRow = { pr: record.pr, event: input.event, at: record.at };
  deps.session.apply({ kind: "record-review", record });
  deps.session.apply({ kind: "append-review-post", row });
  return { kind: "posted", data: outcome.data, record, row };
}
