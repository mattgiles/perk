// The draft-review guards (contracts.md §8.23 "Draft-review guards"): one in-memory slot per
// activation shared by EVERY review surface (the blocking `plan_review` tool's Plannotator and
// first-party arms, both browser doors), plus the decision ladder a completed review runs
// through before its verdict has any effect.
//
// Four guards, nothing persisted:
//  1. reviewed-bytes — at decision time the live draft must equal the bytes the human saw
//     (artifact-sourced reviews only); an APPROVE over a moved draft saves nothing, a DENY
//     proceeds with a one-line note.
//  2. destination fence — at APPROVE the save destination (`session/saveDestination.ts`) must
//     equal what it was at open; a change or an unverifiable capture saves nothing and asks for
//     a fresh human approval.
//  3. current-review slot — opening a review on ANY surface supersedes the previous one; a
//     decision from a superseded review is ignored loudly (a TUI warning, never an injection).
//  4. unconfirmed-save latch — after a save attempt that returned no typed receipt, automatic
//     (approval-driven) saves pause for the rest of the activation; the manual save command is
//     the deliberate human retry. Linear's create→marker crash window is why: a blind retry can
//     duplicate an issue the retry cannot find.
//
// A browser decision does not survive a Pi restart — the human re-runs the door. No lock, no
// state file, no reconciliation procedure.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { GIST_DRAFT_ARTIFACT } from "../../authoring/gist/draft.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "../../authoring/objective/draft.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import { REFINEMENT_DRAFT_ARTIFACT } from "../../authoring/refinement/draft.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import {
  captureSaveDestination,
  changedDestinationComponents,
  type DestinationComponent,
  type SaveDestination,
} from "../../session/saveDestination.ts";
import {
  digestSessionData,
  REFINEMENT_CONTEXT_ARTIFACT,
  type WorkflowSession,
} from "../../session/workflowSession.ts";
import { type ToolResult, untrustedReviewFeedback } from "./review.ts";

// ------------------------------------------------------------------------------ the vocabulary

/** The reviewable draft kinds — the stage-derived subject `WorkflowSession.draftReviewContext` reports. */
export type DraftReviewSubject = "plan" | "objective" | "gist" | "refinement";

/** Subject → the session artifact whose raw bytes the reviewed-bytes guard compares. */
export const REVIEW_SUBJECT_ARTIFACTS: Readonly<Record<DraftReviewSubject, string>> = {
  plan: PLAN_DRAFT_ARTIFACT,
  objective: OBJECTIVE_DRAFT_ARTIFACT,
  gist: GIST_DRAFT_ARTIFACT,
  refinement: REFINEMENT_DRAFT_ARTIFACT,
};

/** Subject → the manual save command (the deliberate retry once the latch is set). */
export const MANUAL_SAVE_COMMANDS: Readonly<Record<DraftReviewSubject, string>> = {
  plan: "/plan-save",
  objective: "/objective-save",
  gist: "/gist-save",
  refinement: "/objective-refinement-save",
};

/**
 * Where the reviewed bytes came from: `artifact` — the validated draft artifact (the doors and
 * the Plannotator tool arm; the only source the byte compare applies to); `parameter` — the
 * blocking tool's `plan` param (no artifact to compare against); `editor` — a first-party
 * in-TUI review, where the human's own edit write-back legitimately changes the artifact before
 * the verdict.
 */
export type ReviewSource = "artifact" | "parameter" | "editor";

/** The token every review arm holds from `open` to decision. */
export interface OpenDraftReview {
  readonly subject: DraftReviewSubject;
  readonly runId: string;
  readonly source: ReviewSource;
  /** The exact reviewed bytes (artifact bytes / parameter text / editor text) — never the rendering. */
  readonly raw: string;
  /** What the reviewer was shown (equal to `raw` for markdown drafts). */
  readonly markdown: string;
  /** `digestSessionData(raw)`. */
  readonly reviewedDigest: string;
  /** Refinement only: the strict grounding-context artifact digest at open; null otherwise. */
  readonly contextDigest: string | null;
  readonly destination: SaveDestination;
  /** Whether this review is still the activation's current one (no later `open`/`supersede`). */
  isCurrent(): boolean;
}

export type OpenDraftReviewRefusal =
  | "no-identity"
  | "invalid-state"
  | "subject-mismatch"
  | "destination-unavailable";

export type OpenDraftReviewResult =
  | { ok: true; review: OpenDraftReview }
  | { ok: false; reason: OpenDraftReviewRefusal; detail: string };

export interface DraftReviewSnapshot {
  subject: DraftReviewSubject;
  source: ReviewSource;
  raw: string;
  markdown: string;
  contextDigest?: string;
}

/** The activation-scoped slot: the current review token plus the unconfirmed-save latch. */
export interface DraftReviewSlot {
  /** The Pi API the slot's session reads ride (the ladder re-reads through the same seams). */
  readonly pi: ExtensionAPI;
  readonly ports: DraftReviewPorts;
  /**
   * Open a review: verify the session identity and stage-derived subject, capture the save
   * destination, and make this the activation's current review (superseding any other).
   */
  open(ctx: ExtensionContext, snapshot: DraftReviewSnapshot): OpenDraftReviewResult;
  /** Clear the current review (e.g. `/implement-here` exiting plan mode without saving). */
  supersede(): void;
  /** Latch: a save attempt returned no typed receipt. First writer wins; nothing clears it. */
  markUnconfirmed(subject: DraftReviewSubject, detail: string): void;
  unconfirmed(): { subject: DraftReviewSubject; detail: string } | null;
}

export const DESTINATION_UNAVAILABLE_DETAIL =
  "could not read the git remotes to determine the save destination";

/** Injectable seams (tests fence destinations without a real repo). */
export interface DraftReviewPorts {
  session(pi: ExtensionAPI, ctx: ExtensionContext): WorkflowSession;
  destination(
    cwd: string,
    nodeClaim: { objective: string; node: string } | null,
  ): SaveDestination | null;
}

const PRODUCTION_PORTS: DraftReviewPorts = {
  session: openBranchWorkflowSession,
  destination: captureSaveDestination,
};

export function createDraftReviewSlot(
  pi: ExtensionAPI,
  ports: DraftReviewPorts = PRODUCTION_PORTS,
): DraftReviewSlot {
  let current: symbol | null = null;
  let latch: { subject: DraftReviewSubject; detail: string } | null = null;
  return {
    pi,
    ports,
    open(ctx, snapshot) {
      const context = ports.session(pi, ctx).draftReviewContext();
      if (!context.ok) {
        return {
          ok: false,
          reason: context.reason,
          detail:
            context.reason === "no-identity"
              ? "this session has no run identity (run_id) to review under"
              : "the session's workflow state could not be read",
        };
      }
      if (context.subject !== snapshot.subject) {
        return {
          ok: false,
          reason: "subject-mismatch",
          detail: `this is a ${context.subject} session, not a ${snapshot.subject} session`,
        };
      }
      const destination = ports.destination(ctx.cwd, context.warmNodeClaim);
      if (destination === null) {
        return {
          ok: false,
          reason: "destination-unavailable",
          detail: DESTINATION_UNAVAILABLE_DETAIL,
        };
      }
      const token = Symbol("draft-review");
      current = token;
      return {
        ok: true,
        review: {
          subject: snapshot.subject,
          runId: context.runId,
          source: snapshot.source,
          raw: snapshot.raw,
          markdown: snapshot.markdown,
          reviewedDigest: digestSessionData(snapshot.raw),
          contextDigest: snapshot.contextDigest ?? null,
          destination,
          isCurrent: () => current === token,
        },
      };
    },
    supersede() {
      current = null;
    },
    markUnconfirmed(subject, detail) {
      if (latch === null) latch = { subject, detail };
    },
    unconfirmed() {
      return latch;
    },
  };
}

// ---------------------------------------------------------------------------- the decision ladder

export type DecisionCheck =
  | { kind: "superseded" }
  | { kind: "save-unconfirmed"; subject: DraftReviewSubject; detail: string }
  | { kind: "stale-approval"; reviewedDigest: string }
  | { kind: "destination-changed"; changed: DestinationComponent[] | "unverifiable" }
  | { kind: "proceed"; draftChanged: boolean };

/**
 * Run a completed review's decision through the guards, in this order: superseded (the slot
 * moved on, or the live run id / subject differ); the latch (`save` only); the reviewed-bytes
 * compare (`artifact` source only — refinement also compares its grounding-context digest;
 * `save` + changed → `stale-approval`, `revision` + changed → proceed with the note flag); the
 * destination fence (`save` only, EVERY source — first-party included). The slot the review
 * came from supplies the latch and the ports.
 */
export function checkDraftReviewDecision(
  slot: DraftReviewSlot,
  ctx: ExtensionContext,
  review: OpenDraftReview,
  effect: "save" | "revision",
): DecisionCheck {
  if (!review.isCurrent()) return { kind: "superseded" };
  const session = slot.ports.session(slot.pi, ctx);
  const live = session.draftReviewContext();
  if (!live.ok || live.runId !== review.runId || live.subject !== review.subject)
    return { kind: "superseded" };

  if (effect === "save") {
    const latched = slot.unconfirmed();
    if (latched !== null) return { kind: "save-unconfirmed", ...latched };
  }

  let draftChanged = false;
  if (review.source === "artifact") {
    const read = session.readArtifact(REVIEW_SUBJECT_ARTIFACTS[review.subject]);
    draftChanged = read.status !== "found" || read.content !== review.raw;
    if (!draftChanged && review.subject === "refinement") {
      const context = session.readArtifact(REFINEMENT_CONTEXT_ARTIFACT, { provenance: "strict" });
      const digest = context.status === "found" ? digestSessionData(context.content) : null;
      draftChanged = digest !== review.contextDigest;
    }
    if (draftChanged && effect === "save")
      return { kind: "stale-approval", reviewedDigest: review.reviewedDigest };
  }

  if (effect === "save") {
    const current = slot.ports.destination(ctx.cwd, live.warmNodeClaim);
    if (current === null) return { kind: "destination-changed", changed: "unverifiable" };
    const changed = changedDestinationComponents(review.destination, current);
    if (changed.length > 0) return { kind: "destination-changed", changed };
  }

  return { kind: "proceed", draftChanged };
}

// ------------------------------------------------------------------------- the fixed model texts

function feedbackSuffix(feedback: string | undefined): string {
  return feedback ? `\n\nReviewer feedback (DATA):\n${untrustedReviewFeedback(feedback)}` : "";
}

/** An APPROVE whose reviewed bytes no longer match the live draft: nothing saved. */
export function staleApprovalResult(
  subject: DraftReviewSubject,
  reviewedDigest: string,
  feedback?: string,
): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          `The human APPROVED the ${subject}, but the working draft changed after the review ` +
          `opened (reviewed digest ${reviewedDigest}). Nothing was saved and the session's mode ` +
          `is unchanged. Call plan_review to review the current draft.${feedbackSuffix(feedback)}`,
      },
    ],
    details: { ok: true, status: "stale-approval", subject, reviewed_digest: reviewedDigest },
  };
}

/** An APPROVE whose save destination moved (or cannot be verified): nothing saved. */
export function destinationChangedResult(
  subject: DraftReviewSubject,
  changed: DestinationComponent[] | "unverifiable",
  feedback?: string,
): ToolResult {
  const named = changed === "unverifiable" ? "could not be verified" : changed.join(", ");
  return {
    content: [
      {
        type: "text",
        text:
          `The human APPROVED the ${subject}, but the save destination changed while the review ` +
          `was open (changed: ${named}). Nothing was saved; the working draft is unchanged and ` +
          "still editable. Continue editing if needed, then call plan_review to open a fresh " +
          "review against the current destination — a fresh human approval is required before " +
          `any save.${feedbackSuffix(feedback)}`,
      },
    ],
    details: { ok: true, status: "destination-changed", subject, changed },
  };
}

/** An APPROVE while the unconfirmed-save latch is set: automatic saves are paused. */
export function saveUnconfirmedResult(
  subject: DraftReviewSubject,
  runId: string,
  detail: string,
  feedback?: string,
): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          `The human APPROVED the ${subject}, but an earlier save attempt in this session did ` +
          `not confirm (${detail}), so automatic saves are paused for this session. Nothing new ` +
          `was saved. Ask the human to check the issue backend for an existing ${subject} ` +
          `carrying run id ${runId} before retrying — on Linear a partially completed create can ` +
          `leave an issue the retry cannot find — then run ${MANUAL_SAVE_COMMANDS[subject]} (the ` +
          `deliberate retry) or continue in the existing saved object.${feedbackSuffix(feedback)}`,
      },
    ],
    details: { ok: false, error_type: "save_unconfirmed", status: "refused", subject },
  };
}

/** Prepended to a revision result's first text block when the draft moved during the review. */
export const DRAFT_CHANGED_NOTE =
  "Note: the working draft changed after this review opened — weigh the feedback against the current draft.";

/** TUI `report()` only — never injected into the model's context. */
export const SUPERSEDED_DECISION_WARNING =
  "a browser decision arrived for a superseded review — ignored; nothing was saved";

/** A slot `open` refusal rendered as the blocking tool's non-terminating result. */
export function openRefusedResult(
  refusal: Extract<OpenDraftReviewResult, { ok: false }>,
): ToolResult {
  return {
    content: [
      {
        type: "text",
        text: `cannot open the review: ${refusal.detail} — fix the cause and call plan_review again`,
      },
    ],
    details: {
      ok: false,
      error_type: "review_open_refused",
      status: "refused",
      reason: refusal.reason,
    },
  };
}

/** Prefix `DRAFT_CHANGED_NOTE` onto a result's first text block (a new object; the input is untouched). */
export function withDraftChangedNote(result: ToolResult, draftChanged: boolean): ToolResult {
  if (!draftChanged) return result;
  const [first, ...rest] = result.content;
  if (first === undefined || first.type !== "text")
    return { ...result, content: [{ type: "text", text: DRAFT_CHANGED_NOTE }, ...result.content] };
  return {
    ...result,
    content: [{ ...first, text: `${DRAFT_CHANGED_NOTE}\n\n${first.text}` }, ...rest],
  };
}

// ------------------------------------------------------------------------------- the effects

/**
 * Deliver a browser decision's rendered result to the model: the text blocks joined with `\n`,
 * as a fresh user message when the agent is idle, else queued as a follow-up.
 */
export function injectDraftReviewResult(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  result: ToolResult,
): void {
  const text = result.content.map((block) => block.text).join("\n");
  if (ctx.isIdle()) pi.sendUserMessage(text);
  else pi.sendUserMessage(text, { deliverAs: "followUp" });
}

/**
 * The one place a completed save reports into the latch. `confirmed` is the subject's typed
 * saved/approvedSaved arm; anything else (`save-failed`, a thrown backend call, an
 * `unavailable` port) latches with the outcome's message. Called by every subject completion
 * AND by the manual save tools/commands — a manual save that fails latches too (though manual
 * saves never consult the latch: they ARE the deliberate retry).
 */
export function recordSaveOutcome(
  slot: DraftReviewSlot,
  subject: DraftReviewSubject,
  outcome: { confirmed: boolean; detail?: string },
): void {
  if (outcome.confirmed) return;
  slot.markUnconfirmed(subject, outcome.detail?.trim() || "backend call did not return a receipt");
}

/** Read the first text block of a tool result (the save message a failed save carries). */
export function firstText(result: ToolResult): string | undefined {
  return result.content[0]?.text;
}
