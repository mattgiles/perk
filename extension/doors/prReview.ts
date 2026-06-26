// The warm `/pr-review` door: multi-angle, classify-then-act code review.
//
// Like `/address`, `/pr-review` now FOLLOWS the read-only-child convention: the parent spawns 2–3
// angle-specialized `perk.pr-reviewer` children (`context: "fresh"`, so the implementation session's
// history never biases the review), each reviewing ONE assigned angle and REPORTING structured
// findings back (no posting, no file writes). The PARENT reconciles (union/dedupe, derive the
// verdict) and records ONE consolidated outcome on the PR via the `post_pr_review` tool.
//
// `post_pr_review` is the mechanical half (mirror of `/address`'s `resolve_review_threads`): it
// DELEGATES the GitHub mutation to the Python cold door (`perk pr review-post` — mutations
// canonical in Python) via the shared cold-door client (`runColdDoor`, the batch rides the
// run-scratch stdin channel), then appends `last_pr_review` to `perk:workflow-state`. Never throws
// (soft `details.ok`, mirrors resolveReviewThreads). This is documented in shared/contracts.md §8.3.
//
// The review model is configurable via `[subagents] pr-reviewer` in `.perk/config.toml`; because
// `subagents.agentOverrides` does NOT reach project agents, the warm command injects that model as a
// per-call inline `model` override on EVERY reviewer spawn (the agent's frontmatter model is the
// default).
//
// Headless-safe: all rich UI stays behind the `report()` surface seam (no `ctx.hasUI`-gated calls),
// exactly like `resolve_review_threads`.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { type ColdJson, numberField, runColdDoor, stringField } from "../substrate/coldDoor.ts";
import { loadPerkConfig } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import {
  arrayParam,
  numberParam,
  paramsOf,
  stringParam,
  type ToolParams,
} from "../substrate/toolParams.ts";
import { appendWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";

/** One reconciled inline finding (the exact `review-post --batch` `comments[]` row). */
interface ReviewComment {
  path: string;
  line: number;
  body: string;
}

interface PostParams {
  verdict: "clean" | "actionable";
  summary: string;
  comments?: ReviewComment[];
  fyi?: string[];
  /** Recorded only (into last_pr_review). */
  pr?: number;
  /** Recorded only (the angle names the parent ran). */
  angles?: string[];
}

/** Decode the optional `comments` array; null = present-but-malformed (whole-batch refusal). */
function decodeComments(p: ToolParams): ReviewComment[] | undefined | null {
  const raw = arrayParam(p, "comments");
  if (raw === undefined) return undefined;
  if (raw === null) return null;
  const comments: ReviewComment[] = [];
  for (const item of raw) {
    const row = paramsOf(item);
    if (row === null) return null;
    const path = stringParam(row, "path");
    const line = numberParam(row, "line");
    const body = stringParam(row, "body");
    if (typeof path !== "string" || path.length === 0) return null;
    if (typeof line !== "number" || !Number.isInteger(line)) return null;
    if (typeof body !== "string" || body.length === 0) return null;
    comments.push({ path, line, body });
  }
  return comments;
}

/** Decode an optional array-of-non-empty-strings param; null = present-but-malformed. */
function decodeStringArray(p: ToolParams, key: string): string[] | undefined | null {
  const raw = arrayParam(p, key);
  if (raw === undefined) return undefined;
  if (raw === null) return null;
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string" || item.length === 0) return null;
    out.push(item);
  }
  return out;
}

/**
 * Strict-decode unknown tool-call params into `PostParams` (the tool-boundary seam). Mirrors
 * `decodeResolveParams`: posting a guessed/partial review is a durable GitHub mutation, so ANY
 * malformed field ⇒ null (whole-batch refusal). `verdict` must be exactly `"clean"`/`"actionable"`;
 * `summary` a non-empty string; each `comments` row strict on path/line(int)/body; `fyi`/`angles`
 * rows non-empty strings; `pr` a number. A `clean` verdict carrying `comments` ⇒ null (the cold
 * door also rejects it as `bad_batch`).
 */
export function decodePostParams(params: unknown): PostParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const verdict = stringParam(p, "verdict");
  if (verdict !== "clean" && verdict !== "actionable") return null;
  const summary = stringParam(p, "summary");
  if (typeof summary !== "string" || summary.length === 0) return null;
  const comments = decodeComments(p);
  if (comments === null) return null;
  if (verdict === "clean" && comments !== undefined && comments.length > 0) return null;
  const fyi = decodeStringArray(p, "fyi");
  if (fyi === null) return null;
  const angles = decodeStringArray(p, "angles");
  if (angles === null) return null;
  const pr = numberParam(p, "pr");
  if (pr === null) return null;
  const result: PostParams = { verdict, summary };
  if (comments !== undefined) result.comments = comments;
  if (fyi !== undefined) result.fyi = fyi;
  if (angles !== undefined) result.angles = angles;
  if (pr !== undefined) result.pr = pr;
  return result;
}

/** The cold door's ok-arm fields (the `review-post --json` surface). */
export interface PostOk {
  pr?: number;
  mode?: string;
  verdict?: string;
  comment_count?: number;
  next_command?: string;
}

export type PostResult = Result<PostOk>;

/** Narrow the cold door's `review-post --json` payload to the fields the tool reports. */
function decodePostResult(payload: ColdJson): PostOk {
  return {
    pr: numberField(payload, "pr"),
    mode: stringField(payload, "mode"),
    verdict: stringField(payload, "verdict"),
    comment_count: numberField(payload, "comment_count"),
    next_command: stringField(payload, "next_command"),
  };
}

/**
 * Post the reconciled multi-angle review to the active PR (the parent's mechanical record step).
 * Delegates to the Python cold door; returns a soft result (never throws). On success, records
 * `last_pr_review`.
 */
export async function postPrReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  params: PostParams,
): Promise<PostResult> {
  const fail = failFor(ctx, "pr-review", "post_pr_review");

  // The exact `perk pr review-post --batch` shape ({verdict, summary, comments?, fyi?}).
  const batch: Record<string, unknown> = { verdict: params.verdict, summary: params.summary };
  if (params.comments !== undefined) batch.comments = params.comments;
  if (params.fyi !== undefined) batch.fyi = params.fyi;

  const r = await runColdDoor<PostOk>(pi, ctx, ["pr", "review-post", "--json"], {
    label: "perk pr review-post",
    decode: (payload) => decodePostResult(payload),
    stdin: {
      flag: "--batch",
      content: `${JSON.stringify(batch, null, 2)}\n`,
      filename: `review-post-${Date.now()}.json`,
    },
  });

  if (!r.ok) return fail(r.message, r.errorType);

  const data = r.data;
  // Record the outcome (tier-3, best-effort-with-logging, idempotent, headless-safe). Strict
  // read-back via rebuild — loud-but-non-fatal, the post already succeeded.
  const record = {
    pr: data.pr ?? params.pr ?? null,
    verdict: params.verdict,
    angles: params.angles ?? [],
    comment_count: data.comment_count ?? null,
    mode: data.mode ?? null,
    at: new Date().toISOString(),
  };
  appendWorkflowState(pi, ctx, {
    data: { last_pr_review: record },
    field: "last_pr_review",
    expected: record,
    scope: "pr-review",
    failure: "last_pr_review read-back failed",
  });

  const nextStep = params.verdict === "clean" ? "/land" : "/address";
  const count = data.comment_count ?? 0;
  const text =
    params.verdict === "clean"
      ? `Clean review — posted 👍 to PR #${record.pr}. Next step: ${nextStep}.`
      : `Posted an advisory review with ${count} inline comment(s) to PR #${record.pr}. ` +
        `Next step: ${nextStep}.`;
  return ok(text, {
    pr: data.pr,
    mode: data.mode,
    verdict: data.verdict,
    comment_count: data.comment_count,
    next_command: data.next_command,
  });
}

const TOOL_GUIDELINES = [
  "Call post_pr_review ONCE, after you have reconciled the angle-specialized reviewers' returned findings (union + dedupe) and derived the overall verdict (actionable if ANY reviewer was actionable, else clean).",
  "Pass the unioned findings as comments[] ({path, line, body}) with each line already anchored to a line in the diff — you never see the diff, so never re-anchor; pass the reviewers' lines straight through. A clean verdict must carry no comments.",
  "Judgment stays with you (the parent): the reviewer children are read-only and report-only — they never post. This tool posts the verdict-driven outcome (clean → 👍, actionable → an advisory COMMENT review) and records last_pr_review.",
];

/**
 * The seed guidance the warm `/pr-review` injects to spawn the angle-specialized reviewers and
 * reconcile+post their findings (the perk-pr-review skill pointer rides the skill-binding suffix —
 * command:pr-review — not hardcoded here). Pure + exported for offline tests. When `model` is set,
 * EVERY reviewer spawn carries an inline `model` override; otherwise the agent's default is used.
 */
export function prReviewGuidance(model?: string): string {
  return render("stages/pr-review.md", { model: model ?? "" });
}

/** Register the warm pr-review door: the `post_pr_review` tool + the `/pr-review` command. */
export function registerPrReview(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "post_pr_review",
    label: "Post PR review",
    description:
      "Post the reconciled multi-angle /pr-review outcome to the active PR (clean → 👍, actionable " +
      "→ an advisory COMMENT review). Delegates the GitHub mutation to the perk cold door; records " +
      "last_pr_review in workflow-state.",
    promptSnippet: "Post the reconciled multi-angle review to the PR",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["verdict", "summary"],
      properties: {
        verdict: {
          type: "string",
          enum: ["clean", "actionable"],
          description:
            "The overall verdict (actionable if ANY reviewer was actionable, else clean).",
        },
        summary: {
          type: "string",
          description:
            "The consolidated review summary. On a clean verdict it is an in-session note only " +
            "(never reaches the PR); on actionable it is the posted overall review.",
        },
        comments: {
          type: "array",
          description:
            "The unioned, deduped inline findings (actionable only). Each line must anchor to a " +
            "line present in the diff. A clean verdict must carry no comments.",
          items: {
            type: "object",
            additionalProperties: false,
            required: ["path", "line", "body"],
            properties: {
              path: { type: "string", description: "The changed file path." },
              line: { type: "number", description: "A line present in the diff." },
              body: { type: "string", description: "The finding (markdown)." },
            },
          },
        },
        fyi: {
          type: "array",
          description: "Borderline/nit notes (in-session only — never posted to GitHub).",
          items: { type: "string" },
        },
        pr: { type: "number", description: "Optional PR number, recorded in last_pr_review." },
        angles: {
          type: "array",
          description: "The angle names you ran, recorded in last_pr_review.",
          items: { type: "string" },
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodePostParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "pr-review",
          "post_pr_review",
        )(
          "post_pr_review needs { verdict: 'clean'|'actionable', summary, comments?, fyi?, pr?, angles? } " +
            "(a clean verdict must carry no comments)",
          "bad_input",
        );
      }
      return postPrReview(pi, ctx, decoded);
    },
  });

  pi.registerCommand("pr-review", {
    description:
      "Review the active PR via 2–3 angle-specialized fresh-context reviewers, reconcile their " +
      "findings, and post one verdict-driven outcome. The review model is configurable via " +
      "[subagents] pr-reviewer in .perk/config.toml.",
    handler: async (_args, ctx: ExtensionContext) => {
      const model = loadPerkConfig(ctx.cwd).subagents["pr-reviewer"];
      const guidance = prReviewGuidance(model);
      report(ctx, "pr-review", "info", "multi-angle review → reconcile → post");
      // Inject the spawn guidance as a user message so the model starts the review (warm entry).
      // The perk-pr-review pointer rides the skill-binding suffix (command:pr-review).
      pi.sendUserMessage(guidance + bindingSuffix(ctx.cwd, "command:pr-review"));
    },
  });
}
