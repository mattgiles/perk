// The warm `submit_pr_review` tool — the agent-driven curated-posting surface shared by the
// PR-review doors (`/pr-review-terminal`, `/pr-review-browser`, `/stack-review-browser`).
//
// `submit_pr_review` implements the per-door posting contract (contracts §8.4): nothing perk-
// driven reaches GitHub before the human triage; ALL perk-side posting flows through this tool
// on every door (`gh` mutations and direct `perk pr review-submit` calls are forbidden); the
// verdict lands last, atomically with the comments. On the terminal door this tool is the sole
// posting path. On the single-PR browser door the human platform-posts from the plannotator
// UI — that native posting IS the GitHub path; perk composes nothing by default and posts only
// what the human explicitly hands it (typically a request-changes verdict, which the UI cannot
// post). On the stack door the local-diff session has NO attached PR, so ALL posting is
// perk-side after triage: one real call per member PR, bottom→top, each under its own dry-run
// anchor validation. It delegates to the Python cold door (`perk pr review-submit` — mutations
// canonical in Python) via `runColdDoor` (the batch rides the run-scratch stdin channel), then
// appends `last_review` AND the accumulating `review_posts` ledger row to `perk:workflow-state`
// (the stack flow's resume authority — posted PRs are skipped, never replayed). The human gate
// splits: explicit conversational go-ahead ALWAYS (pinned in the guidelines/skill); formal
// events (`approve`/`request-changes`) additionally get the structural gate — headless refuses,
// interactive raises a blocking `ctx.ui.confirm`.
// `dry_run` is the anchor-repair loop: no gates, no record, nothing posted.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  booleanField,
  type ColdDoorCtx,
  type ColdJson,
  type ExecHost,
  numberField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import {
  arrayParam,
  booleanParam,
  numberParam,
  paramsOf,
  stringParam,
  type ToolParams,
} from "../substrate/toolParams.ts";
import {
  appendWorkflowState,
  branchOf,
  type EntrySink,
  rebuildWorkflowState,
} from "../substrate/workflowState.ts";
import type { Severity } from "../surfaces/report.ts";

// ------------------------------------------------------------------------ params

export type ReviewEvent = "approve" | "request-changes" | "comment";

/** One curated inline comment (the exact `review-submit --batch` `comments[]` row). */
export interface SubmitComment {
  path: string;
  line: number;
  side?: "LEFT" | "RIGHT";
  body: string;
}

export interface SubmitParams {
  pr: number;
  event: ReviewEvent;
  body: string;
  comments?: SubmitComment[];
  dry_run?: boolean;
  allow_repost?: boolean;
}

/** Decode the optional `comments` array; null = present-but-malformed (whole-batch refusal). */
function decodeSubmitComments(p: ToolParams): SubmitComment[] | undefined | null {
  const raw = arrayParam(p, "comments");
  if (raw === undefined) return undefined;
  if (raw === null) return null;
  const comments: SubmitComment[] = [];
  for (const item of raw) {
    const row = paramsOf(item);
    if (row === null) return null;
    const path = stringParam(row, "path");
    const line = numberParam(row, "line");
    const side = stringParam(row, "side");
    const body = stringParam(row, "body");
    if (typeof path !== "string" || path.length === 0) return null;
    if (typeof line !== "number" || !Number.isInteger(line)) return null;
    if (side !== undefined && side !== "LEFT" && side !== "RIGHT") return null;
    if (typeof body !== "string" || body.length === 0) return null;
    const comment: SubmitComment = { path, line, body };
    if (side !== undefined) comment.side = side;
    comments.push(comment);
  }
  return comments;
}

/**
 * Strict-decode unknown tool-call params into `SubmitParams` (the tool-boundary seam). Mirrors
 * `decodePostParams`: submitting a guessed/partial review is a durable GitHub mutation, so ANY
 * malformed field ⇒ null (whole-batch refusal). `pr` must be an int; `event` exactly one of the
 * three flag spellings; `body` a string (EMPTY ALLOWED — the cold door owns the event-conditioned
 * body rule and reports `bad_batch`); each `comments` row strict on
 * path/line(int)/side(LEFT|RIGHT)/body; `dry_run` and `allow_repost` booleans.
 */
export function decodeSubmitParams(params: unknown): SubmitParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const pr = numberParam(p, "pr");
  if (typeof pr !== "number" || !Number.isInteger(pr)) return null;
  const event = stringParam(p, "event");
  if (event !== "approve" && event !== "request-changes" && event !== "comment") return null;
  const body = stringParam(p, "body");
  if (typeof body !== "string") return null;
  const comments = decodeSubmitComments(p);
  if (comments === null) return null;
  const dryRun = booleanParam(p, "dry_run");
  if (dryRun === null) return null;
  const allowRepost = booleanParam(p, "allow_repost");
  if (allowRepost === null) return null;
  const result: SubmitParams = { pr, event, body };
  if (comments !== undefined) result.comments = comments;
  if (dryRun !== undefined) result.dry_run = dryRun;
  if (allowRepost !== undefined) result.allow_repost = allowRepost;
  return result;
}

// ------------------------------------------------------------------------ the tool core

/** The cold door's ok-arm fields (the `review-submit --json` surface; render-only → lenient). */
export interface SubmitOk {
  dry_run?: boolean;
  pr?: number;
  event?: string;
  mode?: string;
  comment_count?: number;
}

export type SubmitResult = Result<SubmitOk>;

/** Narrow the cold door's `review-submit --json` payload to the fields the tool reports. */
function decodeSubmitResult(payload: ColdJson): SubmitOk {
  return {
    dry_run: booleanField(payload, "dry_run"),
    pr: numberField(payload, "pr"),
    event: stringField(payload, "event"),
    mode: stringField(payload, "mode"),
    comment_count: numberField(payload, "comment_count"),
  };
}

/** One `bad_anchors` `invalid[]` row (the cold door's per-comment repair detail). */
interface InvalidAnchor {
  index: number;
  path: string;
  line: number;
  side: string;
  reason: string;
}

/**
 * Strict re-narrow of the `bad_anchors` fail payload's `invalid[]` rows. Null on ANY drift —
 * uncertainty renders as a plain fail, never a half table.
 */
function decodeInvalidAnchors(payload: ColdJson): InvalidAnchor[] | null {
  const raw = payload.invalid;
  if (!Array.isArray(raw)) return null;
  const rows: InvalidAnchor[] = [];
  for (const item of raw) {
    const row = paramsOf(item);
    if (row === null) return null;
    const index = row.index;
    const path = row.path;
    const line = row.line;
    const side = row.side;
    const reason = row.reason;
    if (typeof index !== "number" || !Number.isInteger(index)) return null;
    if (typeof path !== "string") return null;
    if (typeof line !== "number" || !Number.isInteger(line)) return null;
    if (typeof side !== "string") return null;
    if (typeof reason !== "string") return null;
    rows.push({ index, path, line, side, reason });
  }
  return rows;
}

// ------------------------------------------------------------------------ the posting ledger

/** One `review_posts` ledger row: a REAL submission that reached GitHub. */
export interface ReviewPostRow {
  pr: number;
  event: string;
  at: string;
}

/**
 * Tolerant re-narrow of the rebuilt `review_posts` list (best-effort tier: a malformed row is
 * dropped, never a refusal — the ledger only ever grows from this tool's own writes).
 */
export function reviewPostsOf(raw: unknown): ReviewPostRow[] {
  if (!Array.isArray(raw)) return [];
  const rows: ReviewPostRow[] = [];
  for (const item of raw) {
    const row = paramsOf(item);
    if (row === null) continue;
    if (typeof row.pr !== "number" || !Number.isInteger(row.pr)) continue;
    if (typeof row.event !== "string" || typeof row.at !== "string") continue;
    rows.push({ pr: row.pr, event: row.event, at: row.at });
  }
  return rows;
}

/** Ledger equality for the read-back verification (order-sensitive — posting order matters). */
function reviewPostsEqual(rebuilt: unknown, expected: unknown): boolean {
  const a = reviewPostsOf(rebuilt);
  const b = reviewPostsOf(expected);
  if (a.length !== b.length) return false;
  return a.every(
    (row, i) => row.pr === b[i]?.pr && row.event === b[i]?.event && row.at === b[i]?.at,
  );
}

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

/**
 * The minimal ctx slice `submitPrReview` needs — `ExtensionContext` satisfies it (compile-checked
 * in the test); tests fake it. The dialog method is called ONLY behind the `hasUI` guard.
 */
export interface SubmitCtx extends ColdDoorCtx {
  hasUI: boolean;
  ui: {
    notify(message: string, type?: Severity): void;
    confirm(title: string, message: string): Promise<boolean>;
  };
}

/**
 * Submit the human-curated review batch to the foreign PR (the terminal door's sole posting
 * surface; the browser door's request-changes / explicit-request path). Delegates to the Python
 * cold door; returns a soft result (never throws). Gate ladder (skipped when `dry_run`): formal
 * events refuse headless (`headless_formal_event`) and otherwise require a blocking confirm
 * (`user_declined` on decline, nothing executed); `comment` posts on the conversational
 * go-ahead alone. On a real success, records `last_review`.
 */
export async function submitPrReview(
  pi: ExecHost & EntrySink,
  ctx: SubmitCtx,
  params: SubmitParams,
): Promise<SubmitResult> {
  const fail = failFor(ctx, "review", "submit_pr_review");
  const dryRun = params.dry_run === true;
  const commentCount = params.comments?.length ?? 0;

  // The enforced resume guard (before the confirm AND the cold-door mutation): a PR that
  // already has a review_posts ledger row in this session is a confirmed success — a repeat
  // real post is refused unless explicitly deliberate. A ledger row can only be MISSING
  // spuriously (best-effort tier), never present spuriously — so the guard refuses on
  // presence and stays silent on absence (a missing row still means: verify posted-vs-pending
  // against GitHub before re-posting).
  if (!dryRun && params.allow_repost !== true) {
    const prior = reviewPostsOf(rebuildWorkflowState(branchOf(ctx)).review_posts).filter(
      (row) => row.pr === params.pr,
    );
    const last = prior.at(-1);
    if (last !== undefined) {
      return fail(
        `a ${last.event} review was already posted to PR #${params.pr} in this session ` +
          `(review_posts row at ${last.at}) — on a stack resume skip this member; pass ` +
          "allow_repost: true only for a deliberate second review of the same PR",
        "already_posted",
      );
    }
  }

  if (!dryRun && params.event !== "comment") {
    if (!ctx.hasUI) {
      return fail(
        "headless sessions cannot post formal review verdicts — re-run interactively or use " +
          "event: comment",
        "headless_formal_event",
      );
    }
    const wire = WIRE_EVENT[params.event];
    const firstLine = bodyFirstLine(params.body);
    const summary =
      `event: ${wire} · ${commentCount} inline comment(s)` +
      (firstLine.length > 0 ? `\nbody: ${firstLine}` : "");
    const yes = await ctx.ui.confirm(`Post ${wire} review to PR #${params.pr}?`, summary);
    if (!yes) {
      return fail(
        `user declined the ${params.event} review — nothing was submitted`,
        "user_declined",
      );
    }
  }

  // The exact `perk pr review-submit --batch` shape ({body, comments?} — the event rides the flag).
  const batch: Record<string, unknown> = { body: params.body };
  if (params.comments !== undefined) batch.comments = params.comments;

  const r = await runColdDoor<SubmitOk>(
    pi,
    ctx,
    [
      "pr",
      "review-submit",
      "--pr",
      String(params.pr),
      "--event",
      params.event,
      ...(dryRun ? ["--dry-run"] : []),
      "--json",
    ],
    {
      label: "perk pr review-submit",
      decode: decodeSubmitResult,
      stdin: {
        flag: "--batch",
        content: `${JSON.stringify(batch, null, 2)}\n`,
        filename: `review-submit-${Date.now()}.json`,
      },
    },
  );

  if (!r.ok) {
    // The repair-loop arm: render the per-comment invalid[] detail when it decodes cleanly.
    if (r.errorType === "bad_anchors" && r.payload !== undefined) {
      const rows = decodeInvalidAnchors(r.payload);
      if (rows !== null && rows.length > 0) {
        const table = rows
          .map(
            (row) =>
              `  comment[${row.index}] ${row.path}:${row.line} (${row.side}) — ${row.reason}`,
          )
          .join("\n");
        return fail(
          `${r.message}\n${table}\nrepair these anchors and re-run with dry_run: true`,
          r.errorType,
        );
      }
    }
    return fail(r.message, r.errorType);
  }

  const data = r.data;
  if (dryRun) {
    const n = data.comment_count ?? commentCount;
    return ok(
      `validated — ${n} inline comment(s), event ${params.event}; the batch is submittable`,
      { ...data },
    );
  }

  // Record the outcome (tier-3, best-effort-with-logging, headless-safe). Strict read-back via
  // rebuild — loud-but-non-fatal, the submission already succeeded.
  const record = {
    pr: data.pr ?? params.pr,
    event: params.event,
    comment_count: data.comment_count ?? null,
    mode: data.mode ?? null,
    at: new Date().toISOString(),
  };
  appendWorkflowState(pi, ctx, {
    data: { last_review: record },
    field: "last_review",
    expected: record,
    scope: "review",
    failure: "last_review read-back failed",
  });

  // The accumulating per-PR ledger (read-rebuild-append): ordered rows, one per real success —
  // the stack flow's partial-outcome/resume authority. Same best-effort tier as last_review.
  const posts: ReviewPostRow[] = [
    ...reviewPostsOf(rebuildWorkflowState(branchOf(ctx)).review_posts),
    { pr: record.pr, event: params.event, at: record.at },
  ];
  appendWorkflowState(pi, ctx, {
    data: { review_posts: posts },
    field: "review_posts",
    expected: posts,
    scope: "review",
    failure: "review_posts read-back failed",
    equals: reviewPostsEqual,
  });

  let text =
    `submitted ${params.event} review to PR #${record.pr} ` +
    `(${data.comment_count ?? commentCount} inline comment(s))`;
  if (data.mode === "review_folded") {
    text +=
      " — note: inline anchors rejected by GitHub; comments folded into the review body, " +
      "event preserved";
  } else if (data.mode === "comment_fallback") {
    text += " — note: degraded to a discussion comment";
  }
  return ok(`${text}.`, { ...data });
}

const TOOL_GUIDELINES = [
  "Call submit_pr_review only after the human triage has settled the batch AND the human has explicitly approved posting — nothing reaches GitHub before triage.",
  "Validate first with dry_run: true and repair any reported anchors until validation passes; a dry-run never posts, never gates, and records nothing. A stack review dry-runs ALL per-PR batches before ANY real post.",
  "Make ONE real call per target PR: comments + body + event land atomically in a single review — the verdict never lands before the comments. A stack review posts one review per member PR, bottom→top; each real success appends a {pr, event, at} row to the review_posts workflow-state ledger. The tool ENFORCES skip-on-resume: a real post to a PR that already has a ledger row is refused (already_posted) unless allow_repost: true — a deliberate second review only. A MISSING row is not proof of no post (the ledger is best-effort): verify posted-vs-pending against GitHub before re-posting.",
  "Formal events (approve / request-changes) additionally raise a blocking in-TUI confirm; headless sessions refuse them (use event: comment or re-run interactively).",
  "All perk-side GitHub posting flows through this tool on every review door — never post via gh or bash (direct perk pr review-submit calls are forbidden). On /pr-review-terminal this tool is the sole posting path. On /pr-review-browser the plannotator UI's native platform-posting is the human's own GitHub path, and perk posts only what the human explicitly hands it (typically a request-changes verdict). On /stack-review-browser the local-diff session has NO attached PR, so ALL posting is perk-side after triage.",
];

// ------------------------------------------------------------------------ registration

/** Register the `submit_pr_review` tool (the two review doors register no tools of their own). */
export function registerSubmitPrReview(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "submit_pr_review",
    label: "Submit PR review",
    description:
      "Submit the human-curated review-door outcome to the target PR as ONE atomic review " +
      "(comments + body + event) via the perk cold door — the posting surface of the " +
      "/pr-review-terminal, /pr-review-browser, and /stack-review-browser doors (a stack " +
      "review makes one real call per member PR). dry_run validates the anchors without " +
      "posting (the repair loop); a real submission records last_review and appends the " +
      "review_posts ledger row in workflow-state.",
    promptSnippet: "Submit the curated review batch to the PR",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["pr", "event", "body"],
      properties: {
        pr: { type: "number", description: "The foreign PR number being reviewed." },
        event: {
          type: "string",
          enum: ["approve", "request-changes", "comment"],
          description:
            "The review event, settled with the human during triage. Formal events " +
            "(approve/request-changes) additionally raise a blocking confirm dialog.",
        },
        body: {
          type: "string",
          description:
            "The overall review body (markdown). comment/request-changes require a non-empty " +
            "body; unanchorable findings fold in here.",
        },
        comments: {
          type: "array",
          description:
            "The curated inline comments — human-authored or human-approved only, each anchored " +
            "to a line in the PR diff. Single-PR mode: never re-anchor a child's finding. Stack " +
            "mode: the parent re-anchors combined-diff findings into per-PR coordinates under " +
            "the dry-run loop.",
          items: {
            type: "object",
            additionalProperties: false,
            required: ["path", "line", "body"],
            properties: {
              path: { type: "string", description: "The changed file path." },
              line: { type: "number", description: "A line present in the PR diff." },
              side: {
                type: "string",
                enum: ["LEFT", "RIGHT"],
                description: "The diff side the line anchors to (default RIGHT).",
              },
              body: { type: "string", description: "The comment (markdown)." },
            },
          },
        },
        dry_run: {
          type: "boolean",
          description:
            "Validate the batch + anchors without posting (the anchor-repair loop). No gates, " +
            "no last_review record.",
        },
        allow_repost: {
          type: "boolean",
          description:
            "Deliberately post ANOTHER review to a PR that already has a review_posts ledger " +
            "row in this session — the enforced resume guard refuses with already_posted " +
            "otherwise. Never pass it to work around a stack-resume refusal.",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeSubmitParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "review",
          "submit_pr_review",
        )(
          "submit_pr_review needs { pr: int, event: 'approve'|'request-changes'|'comment', " +
            "body: string, comments?: [{path, line: int, side?: 'LEFT'|'RIGHT', body}], " +
            "dry_run?: bool }",
          "bad_input",
        );
      }
      return submitPrReview(pi, ctx, decoded);
    },
  });
}
