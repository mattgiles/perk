// The Pi adapter over the current-review record (`authoring/review/currentReview.ts`): one
// activation-scoped runtime the composition root threads to both browser doors and the
// `plan_review` bridge. It owns the two real-world readings the Pi-free record cannot take
// itself — the save-destination snapshot (`substrate/config.ts::issueDestination` +
// `substrate/git.ts::remoteUrls`) and the approve-time artifact re-read through the
// branch-backed session — and the two stale renderers (a tool result for the blocking arms, a
// notice for the doors' `sendUserMessage` injection). Contracts.md §8.23.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  type ApproveGate,
  type CurrentReview,
  closeCurrentReview,
  createCurrentReviewState,
  gateApprovedSave,
  isCurrentReview,
  openCurrentReview,
  type ReviewDestination,
  type StaleReason,
} from "../../authoring/review/currentReview.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import { issueDestination } from "../../substrate/config.ts";
import { remoteUrls } from "../../substrate/git.ts";
import type { ReviewSubject, ToolResult } from "./review.ts";
import type { ReviewOutcome } from "./reviewOutcome.ts";

export type {
  CurrentReview,
  ReviewDestination,
  StaleReason,
} from "../../authoring/review/currentReview.ts";

/** The production save-destination snapshot: the three readings, nothing else is fingerprinted. */
function readReviewDestination(cwd: string): ReviewDestination {
  return { ...issueDestination(cwd), remotes: remoteUrls(cwd) };
}

/**
 * The review bridge slice the plan installer builds: the plannotator event-bus bridge plus the
 * activation's current-review record runtime — the fence every Plannotator `plan_review` arm
 * opens a record on. Declared here (not in `planReview.ts`) so the sibling arms it dispatches to
 * can name the type without importing the dispatcher back.
 */
export interface PlanReviewBridge {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
  current: CurrentReviewRuntime;
}

export interface CurrentReviewRuntime {
  /** Open a review over `source` (the artifact baseline, or null); the destination snapshot is taken here. */
  open(ctx: ExtensionContext, source: { name: string; raw: string } | null): CurrentReview;
  isCurrent(review: CurrentReview): boolean;
  /**
   * The approve gate: re-reads the source artifact through the session (`found` → its content,
   * else null — absent/invalid never equals) and re-takes the destination, then marks the record
   * saved on `ok`.
   */
  approve(ctx: ExtensionContext, review: CurrentReview): ApproveGate;
  close(review: CurrentReview): void;
}

/**
 * `deps.destination` is the injectable destination snapshot (tests drive drift without touching
 * git or config); `deps.session` is the artifact re-read seam. Both default to production.
 */
export function createCurrentReviewRuntime(
  pi: ExtensionAPI,
  deps: {
    destination?: (cwd: string) => ReviewDestination;
    session?: (ctx: ExtensionContext) => WorkflowSession;
  } = {},
): CurrentReviewRuntime {
  const destination = deps.destination ?? readReviewDestination;
  const session = deps.session ?? ((ctx: ExtensionContext) => openBranchWorkflowSession(pi, ctx));
  const state = createCurrentReviewState();
  return {
    open(ctx, source) {
      return openCurrentReview(state, { source, destination: destination(ctx.cwd) });
    },
    isCurrent(review) {
      return isCurrentReview(state, review);
    },
    approve(ctx, review) {
      let source: string | null = null;
      if (review.source !== null) {
        const read = session(ctx).readArtifact(review.source.name);
        source = read.status === "found" ? read.content : null;
      }
      return gateApprovedSave(state, review, { source, destination: destination(ctx.cwd) });
    },
    close(review) {
      closeCurrentReview(state, review);
    },
  };
}

/** One text template drives both stale renderers; `what` names the reason in human terms. */
function staleReviewText(subject: ReviewSubject, reason: StaleReason): string {
  const verb = reason === "superseded" ? "arrived" : "APPROVED by reviewer";
  const what = {
    superseded: "a newer review superseded this one (the decision is ignored)",
    "already-saved": `this review already attempted its save (use ${subject.failsafeCmd} to retry manually)`,
    "source-changed": "the working draft was rewritten after the reviewed version was shown",
    "destination-unreadable": "the save destination could not be read (git remotes unavailable)",
    "destination-changed":
      "the save destination ([issues] backend/team or the git remotes) changed after the review opened",
  }[reason];
  return (
    `${subject.noun} review decision ${verb}, but ${what} — nothing was saved and the session ` +
    "stays read-only. Call plan_review again over the current draft."
  );
}

/**
 * The blocking arms' stale tool result. A `completed` outcome's feedback is retained in details
 * as DATA only (never rendered as guidance — nothing was saved).
 */
export function staleReviewResult(
  subject: ReviewSubject,
  reason: StaleReason,
  outcome?: Extract<ReviewOutcome, { status: "completed" }>,
): ToolResult {
  return {
    content: [{ type: "text", text: staleReviewText(subject, reason) }],
    details: {
      ok: false,
      status: "stale",
      reason,
      approved: outcome?.approved,
      ...(outcome?.feedback !== undefined ? { feedback: outcome.feedback } : {}),
      ...subject.detailsExtra,
    },
  };
}

/** The doors' stale notice (reported AND injected via `sendUserMessage`). */
export function staleReviewNotice(subject: ReviewSubject, reason: StaleReason): string {
  return (
    `${staleReviewText(subject, reason)} Present the current draft and re-run the review ` +
    "(the human re-runs the door, or you call plan_review)."
  );
}
