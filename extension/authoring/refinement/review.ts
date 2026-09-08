// The objective-refinement REVIEW feature: the reviewer role over the rendered pair and the
// one-entry completion routing (contracts.md §8.67 / §8.23's refinement arm).
//
// Discipline: the (draft, context) pair is the SOLE review source — never a param, never the
// transcript. The Pi arm resumes the pair, renders it, reviews, then routes the verdict through
// `completeRefinementReview`. An approval carrying Direct Edits SKIPS the save and returns one
// revise round (the heading means no save and no gate exit — Markdown edits are folded via the
// draft tool and re-reviewed; target/provenance edits need a new grounding pass, never
// fabricated metadata). A plain approval re-reads the pair through `refinementApprovalSave`,
// which compares it with the REVIEWED pair when the caller captured one — approval never
// transfers to a replacement artifact. Denial stays untrusted DATA. Skipped / dismissed /
// unavailable outcomes save nothing — the caller offers the human `/objective-refinement-save`.

import type { RefinementApprovalSaveOutcome } from "./save.ts";

export type RefinementReviewOutcome =
  | { status: "approved"; feedback?: string; reviewId?: string }
  | { status: "approvedDirectEdits"; feedback: string; reviewId?: string }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/** The reviewer role: judge the RENDERED surface (never raw artifact JSON). */
export interface RefinementDraftReviewer {
  review(rendered: string, signal?: AbortSignal): Promise<RefinementReviewOutcome>;
}

export type ReviewRefinementResult =
  | { status: "noDraft" }
  | { status: "noContext" }
  | { status: "refusedDraft"; problem: string }
  | { status: "directEditsRevise"; feedback: string; reviewId?: string }
  | {
      status: "approvedSaved";
      save: Extract<RefinementApprovalSaveOutcome, { status: "saved" }>;
      feedback?: string;
      reviewId?: string;
    }
  | {
      status: "approvedSaveFailed";
      save: Extract<RefinementApprovalSaveOutcome, { status: "save-failed" }>;
      feedback?: string;
      reviewId?: string;
    }
  | { status: "approvedNoDraft"; feedback?: string; reviewId?: string }
  | { status: "approvedRefusedDraft"; problem: string; feedback?: string; reviewId?: string }
  | {
      /** The approval named a pair the session no longer holds: nothing saved, review again. */
      status: "approvedSourceChanged";
      changed: "draft" | "context";
      feedback?: string;
      reviewId?: string;
    }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/** Subject policy only: callers authorize effects before entering this completion seam. */
export async function completeRefinementReview(
  outcome: RefinementReviewOutcome,
  approvalSave: () => Promise<RefinementApprovalSaveOutcome>,
): Promise<ReviewRefinementResult> {
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
    const save = await approvalSave();
    switch (save.status) {
      case "saved":
        return { status: "approvedSaved", save, ...carried };
      case "save-failed":
        return { status: "approvedSaveFailed", save, ...carried };
      case "no-draft":
        return { status: "approvedNoDraft", ...carried };
      case "no-context":
        return {
          status: "approvedRefusedDraft",
          problem: "the refinement context vanished between the review and the save",
          ...carried,
        };
      case "refused-draft":
        return { status: "approvedRefusedDraft", problem: save.problem, ...carried };
      case "source-changed":
        return { status: "approvedSourceChanged", changed: save.changed, ...carried };
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
