// The gist review feature: the `GistDraftReviewer` role (one production adapter per review
// backend — plannotator bridge or first-party editor, both built in pi/v1 — plus a scripted fake
// in the tests) and the one-entry `reviewGist` operation.
//
// Ordering is the review door's exact discipline: resume-the-draft FIRST (absent → `noDraft` —
// the draft artifact is the SOLE review source, never a param, never the transcript), render the
// markdown surface, review, then route the verdict — an approval carrying direct edits SKIPS the
// save and returns one revise round (rendered edits cannot be folded back into the structured
// draft mechanically; the gate stays untouched); a plain approval re-reads the artifact through
// `gistApprovalSave` (the save source is the artifact, never the reviewed bytes). Headless
// detection stays in the adapter — the feature never sees `hasUI`.

import type { WorkflowSession } from "../../session/workflowSession.ts";
import type { ApprovalGate } from "../review/approvalGate.ts";
import { renderGistDraft, resumeGistDraft } from "./draft.ts";
import { type GistApprovalSaveOutcome, type GistBackend, gistApprovalSave } from "./save.ts";

/**
 * The reviewer's verdict on the rendered draft. An approval carrying reviewer edits of the
 * rendered markdown is its OWN variant (`approvedDirectEdits`) with `feedback` required — the
 * edits ARE the feedback, so an edits-without-feedback value is unrepresentable and can never
 * fall through to the save path. The backend adapter translates its own vocabulary (e.g.
 * plannotator's `# Direct Edits` feedback section) into this variant.
 */
export type GistReviewOutcome =
  | { status: "approved"; feedback?: string; reviewId?: string }
  | { status: "approvedDirectEdits"; feedback: string; reviewId?: string }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/** The reviewer role: judge the RENDERED markdown surface (never raw artifact JSON). */
export interface GistDraftReviewer {
  review(rendered: string, signal?: AbortSignal): Promise<GistReviewOutcome>;
}

/** The one-entry review outcome — each arm carries exactly what its caller renders.
 * `refusedDraft` (pre-review) and `approvedRefusedDraft` (the approval-time race) are the
 * fail-closed stops for an invalid artifact: nothing reviewed/saved, the gate untouched. */
export type ReviewGistResult =
  | { status: "noDraft" }
  | { status: "refusedDraft"; problem: string }
  | { status: "directEditsRevise"; feedback: string; reviewId?: string }
  | {
      status: "approvedSaved";
      save: Extract<GistApprovalSaveOutcome, { status: "saved" }>;
      feedback?: string;
      reviewId?: string;
    }
  | {
      status: "approvedSaveFailed";
      save: Extract<GistApprovalSaveOutcome, { status: "save-failed" }>;
      feedback?: string;
      reviewId?: string;
    }
  | { status: "approvedNoDraft"; feedback?: string; reviewId?: string }
  | { status: "approvedRefusedDraft"; problem: string; feedback?: string; reviewId?: string }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/**
 * Review the working gist draft end-to-end: resume → render → review → route. An approval with
 * `directEdits` (and feedback to fold) returns the revise round with NOTHING saved and the gate
 * untouched; a plain approval runs `gistApprovalSave` (which re-reads the artifact at save time
 * — `approvedNoDraft` is the defensive vanished-between-reads arm; `approvedRefusedDraft` its
 * corrupted-between-reads sibling, feedback/reviewId preserved across the race). Never throws.
 */
export async function reviewGist(
  deps: {
    session: WorkflowSession;
    reviewer: GistDraftReviewer;
    backend: GistBackend;
    gate: ApprovalGate;
  },
  signal?: AbortSignal,
): Promise<ReviewGistResult> {
  const resumed = resumeGistDraft(deps.session);
  if (resumed.kind === "absent") return { status: "noDraft" };
  if (resumed.kind === "refused") return { status: "refusedDraft", problem: resumed.problem };
  const rendered = renderGistDraft(resumed.draft);
  const outcome = await deps.reviewer.review(rendered, signal);
  if (outcome.status === "approvedDirectEdits") {
    return {
      status: "directEditsRevise",
      feedback: outcome.feedback,
      ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
    };
  }
  if (outcome.status === "approved") {
    const carried = {
      ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
      ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
    };
    const save = await gistApprovalSave({
      session: deps.session,
      backend: deps.backend,
      gate: deps.gate,
    });
    switch (save.status) {
      case "saved":
        return { status: "approvedSaved", save, ...carried };
      case "save-failed":
        return { status: "approvedSaveFailed", save, ...carried };
      case "no-draft":
        return { status: "approvedNoDraft", ...carried };
      case "refused-draft":
        return { status: "approvedRefusedDraft", problem: save.problem, ...carried };
    }
  }
  switch (outcome.status) {
    case "denied":
      return {
        status: "denied",
        ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
        ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
      };
    case "dismissed":
      return { status: "dismissed" };
    case "aborted":
      return { status: "aborted" };
    case "unavailable":
      return { status: "unavailable", warning: outcome.warning };
  }
}
