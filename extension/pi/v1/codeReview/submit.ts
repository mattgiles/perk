// The v1 Pi installer for the curated-submission flow: `installCuratedSubmissionBindings` owns
// the warm `submit_pr_review` tool — the agent-driven curated-posting surface shared by the
// PR-review doors (`/pr-review-terminal`, `/pr-review-browser`, `/stack-review-browser`).
// Registration metadata is pinned by the suite's registration-parity tests; the policy (gate ladder, resume guard, session
// records) lives in `codeReview/submission.ts` — this module decodes at the tool boundary,
// composes the `perk pr review-submit` cold-door `ReviewSubmitter` (mutations canonical in
// Python; the batch rides the run-scratch stdin channel), selects the `FormalEventGate` arm
// from `ctx.hasUI`, opens the branch `WorkflowSession` at the execute site, and renders the
// Result envelope (`kind` → the error_type vocabulary; success texts).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  type CuratedSubmission,
  type FormalEventGate,
  type InvalidAnchor,
  type ReviewSubmitOutcome,
  type ReviewSubmitter,
  type SubmitBatch,
  type SubmitComment,
  type SubmitCuratedOutcome,
  type SubmitOk,
  submitCuratedReview,
} from "../../../codeReview/submission.ts";
import { openBranchWorkflowSession } from "../../../session/branchWorkflowSession.ts";
import {
  booleanField,
  type ColdDoorCtx,
  type ColdJson,
  type ExecHost,
  numberField,
  runColdDoor,
  stringField,
} from "../../../substrate/coldDoor.ts";
import { failFor, ok, type Result } from "../../../substrate/result.ts";
import {
  arrayParam,
  booleanParam,
  numberParam,
  paramsOf,
  stringParam,
  type ToolParams,
} from "../../../substrate/toolParams.ts";
import type { Severity } from "../../../surfaces/report.ts";

// ------------------------------------------------------------------------ params

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
 * Strict-decode unknown tool-call params straight into the normalized `CuratedSubmission`
 * feature input (the tool-boundary seam — no intermediate wire DTO: the two boolean defaults
 * are applied here, absent ⇒ false). Mirrors `decodePostParams`: submitting a guessed/partial
 * review is a durable GitHub mutation, so ANY malformed field ⇒ null (whole-batch refusal).
 * `pr` must be an int; `event` exactly one of the three flag spellings; `body` a string (EMPTY
 * ALLOWED — the cold door owns the event-conditioned body rule and reports `bad_batch`); each
 * `comments` row strict on path/line(int)/side(LEFT|RIGHT)/body; `dry_run` and `allow_repost`
 * booleans.
 */
export function decodeSubmitParams(params: unknown): CuratedSubmission | null {
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
  const result: CuratedSubmission = {
    pr,
    event,
    body,
    dryRun: dryRun === true,
    allowRepost: allowRepost === true,
  };
  if (comments !== undefined) result.comments = comments;
  return result;
}

// ------------------------------------------------------------------------ port productions

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

/**
 * The production `ReviewSubmitter`: the `perk pr review-submit` cold-door composition (the exact
 * `--batch` shape: `{body, comments?}` — the event rides the flag). The adapter performs the
 * strict `invalid[]` decode; decode drift ⇒ the `failed` arm.
 */
export function createColdDoorReviewSubmitter(pi: ExecHost, ctx: ColdDoorCtx): ReviewSubmitter {
  return {
    async submit(batch: SubmitBatch): Promise<ReviewSubmitOutcome> {
      const payload: Record<string, unknown> = { body: batch.body };
      if (batch.comments !== undefined) payload.comments = batch.comments;
      const r = await runColdDoor<SubmitOk>(
        pi,
        ctx,
        [
          "pr",
          "review-submit",
          "--pr",
          String(batch.pr),
          "--event",
          batch.event,
          ...(batch.dryRun ? ["--dry-run"] : []),
          "--json",
        ],
        {
          label: "perk pr review-submit",
          decode: decodeSubmitResult,
          stdin: {
            flag: "--batch",
            content: `${JSON.stringify(payload, null, 2)}\n`,
            filename: `review-submit-${Date.now()}.json`,
          },
        },
      );
      if (r.ok) return { ok: true, data: r.data };
      if (r.errorType === "bad_anchors" && r.payload !== undefined) {
        const rows = decodeInvalidAnchors(r.payload);
        if (rows !== null && rows.length > 0) {
          return { ok: false, kind: "bad_anchors", invalid: rows, message: r.message };
        }
      }
      return { ok: false, kind: "failed", message: r.message, errorType: r.errorType };
    },
  };
}

/**
 * The minimal ctx slice the gate production needs — `ExtensionContext` satisfies it
 * (compile-checked in the test). The dialog method is reachable ONLY through the interactive arm.
 */
export interface SubmitGateCtx {
  hasUI: boolean;
  ui: {
    notify(message: string, type?: Severity): void;
    confirm(title: string, message: string): Promise<boolean>;
  };
}

/** The production `FormalEventGate`: `ctx.hasUI` selects the arm; interactive wraps the dialog. */
export function formalEventGateFor(ctx: SubmitGateCtx): FormalEventGate {
  return ctx.hasUI
    ? { kind: "interactive", confirm: (question, summary) => ctx.ui.confirm(question, summary) }
    : { kind: "headless" };
}

// ------------------------------------------------------------------------ result rendering

/** Map the enumerated feature outcome onto the tool Result envelope (texts pinned by tests). */
function renderSubmitOutcome(
  fail: (message: string, errorType: string) => Result<SubmitOk>,
  input: CuratedSubmission,
  outcome: SubmitCuratedOutcome,
): Result<SubmitOk> {
  const commentCount = input.comments?.length ?? 0;
  switch (outcome.kind) {
    case "already_posted":
      return fail(outcome.message, "already_posted");
    case "headless_formal_event":
      return fail(outcome.message, "headless_formal_event");
    case "user_declined":
      return fail(outcome.message, "user_declined");
    case "bad_anchors":
      return fail(outcome.message, "bad_anchors");
    case "submit_failed":
      return fail(outcome.message, outcome.errorType);
    case "dry_run_ok": {
      const n = outcome.data.comment_count ?? commentCount;
      return ok(
        `validated — ${n} inline comment(s), event ${input.event}; the batch is submittable`,
        { ...outcome.data },
      );
    }
    case "posted": {
      let text =
        `submitted ${input.event} review to PR #${outcome.record.pr} ` +
        `(${outcome.data.comment_count ?? commentCount} inline comment(s))`;
      if (outcome.data.mode === "review_folded") {
        text +=
          " — note: inline anchors rejected by GitHub; comments folded into the review body, " +
          "event preserved";
      } else if (outcome.data.mode === "comment_fallback") {
        text += " — note: degraded to a discussion comment";
      }
      return ok(`${text}.`, { ...outcome.data });
    }
  }
}

const TOOL_GUIDELINES = [
  "Call submit_pr_review only after the human triage has settled the batch AND the human has explicitly approved posting — nothing reaches GitHub before triage.",
  "Validate first with dry_run: true and repair any reported anchors until validation passes; a dry-run never posts, never gates, and records nothing. A stack review dry-runs ALL per-PR batches before ANY real post.",
  "Make ONE real call per target PR: comments + body + event land atomically in a single review — the verdict never lands before the comments. A stack review posts one review per member PR, bottom→top; each real success appends a {pr, event, at} row to the review_posts workflow-state ledger. The tool ENFORCES skip-on-resume: a real post to a PR that already has a ledger row is refused (already_posted) unless allow_repost: true — a deliberate second review only. A MISSING row is not proof of no post (the ledger is best-effort): verify posted-vs-pending against GitHub before re-posting.",
  "Formal events (approve / request-changes) additionally raise a blocking in-TUI confirm; headless sessions refuse them (use event: comment or re-run interactively).",
  "All perk-side GitHub posting flows through this tool on every review door — never post via gh or bash (direct perk pr review-submit calls are forbidden). On /pr-review-terminal this tool is the sole posting path. On /pr-review-browser the plannotator UI's native platform-posting is the human's own GitHub path, and perk posts only what the human explicitly hands it (typically a request-changes verdict). On /stack-review-browser the local-diff session has NO attached PR, so ALL posting is perk-side after triage.",
];

// ------------------------------------------------------------------------ registration

/** Install the `submit_pr_review` tool (the review doors register no posting tools of their own). */
export function installCuratedSubmissionBindings(pi: ExtensionAPI): void {
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
      const fail = failFor(ctx, "review", "submit_pr_review");
      const decoded = decodeSubmitParams(params);
      if (decoded === null) {
        return fail(
          "submit_pr_review needs { pr: int, event: 'approve'|'request-changes'|'comment', " +
            "body: string, comments?: [{path, line: int, side?: 'LEFT'|'RIGHT', body}], " +
            "dry_run?: bool }",
          "bad_input",
        );
      }
      const outcome = await submitCuratedReview(decoded, {
        submitter: createColdDoorReviewSubmitter(pi, ctx),
        gate: formalEventGateFor(ctx),
        session: openBranchWorkflowSession(pi, ctx),
      });
      return renderSubmitOutcome(fail, decoded, outcome);
    },
  });
}
