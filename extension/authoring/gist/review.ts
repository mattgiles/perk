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
import { renderGistDraft, resumeGistDraft } from "./draft.ts";
import { type GistApprovalSaveOutcome, type GistBackend, type GistGate, gistApprovalSave } from "./save.ts";

/**
 * The reviewer's verdict on the rendered draft. `directEdits` is true when an approval carries
 * reviewer edits of the rendered markdown (the backend adapter translates its own vocabulary —
 * e.g. plannotator's `# Direct Edits` feedback section — into this flag).
 */
export type GistReviewOutcome =
  | { status: "approved"; feedback?: string; reviewId?: string; directEdits: boolean }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/** The reviewer role: judge the RENDERED markdown surface (never raw artifact JSON). */
export interface GistDraftReviewer {
  review(rendered: string, signal?: AbortSignal): Promise<GistReviewOutcome>;
}

/** The one-entry review outcome — each arm carries exactly what its caller renders. */
export type ReviewGistResult =
  | { status: "noDraft" }
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
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/**
 * Review the working gist draft end-to-end: resume → render → review → route. An approval with
 * `directEdits` (and feedback to fold) returns the revise round with NOTHING saved and the gate
 * untouched; a plain approval runs `gistApprovalSave` (which re-reads the artifact at save time
 * — `approvedNoDraft` is the defensive vanished-between-reads arm). Never throws.
 */
export async function reviewGist(
  deps: {
    session: WorkflowSession;
    reviewer: GistDraftReviewer;
    backend: GistBackend;
    gate: GistGate;
  },
  signal?: AbortSignal,
): Promise<ReviewGistResult> {
  const draft = resumeGistDraft(deps.session);
  if (draft === null) return { status: "noDraft" };
  const rendered = renderGistDraft(draft);
  const outcome = await deps.reviewer.review(rendered, signal);
  if (outcome.status === "approved") {
    const carried = {
      ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
      ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
    };
    if (outcome.directEdits && outcome.feedback !== undefined) {
      return { status: "directEditsRevise", ...carried, feedback: outcome.feedback };
    }
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
