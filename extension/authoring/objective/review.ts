// The objective review feature: the `ObjectiveDraftReviewer` role (one production adapter per
// review backend — plannotator bridge or first-party editor, both built in pi/v1 — plus a
// scripted fake in the tests) and the one-entry `reviewObjectiveDraft` operation.
//
// Ordering is the review door's exact discipline: resume FIRST (the validated artifact only —
// objectives have no param/transcript tier; none ⇒ `noDraft`) → render (the reviewed bytes are
// ALWAYS the rendered markdown — the review-surface law: JSON is storage/transport, never the
// human surface) → review → the abort checkpoint → route the verdict. Provider vocabulary
// (plannotator's `# Direct Edits` heading) is translated INTO `ObjectiveReviewOutcome` at the
// adapter — the feature sees typed variants only.
//
// No implement-here arm (the no-save exit is plan-arm-only — contracts §8.23) and no
// edited-bytes channel: objective reviews are VIEW-ONLY (rendered-markdown edits cannot fold
// back into the structured draft mechanically), so `approvedDirectEdits` is the revise-round
// refusal arm — NOTHING saved, the gate untouched; deny+feedback is the change channel.
//
// Cancellation ownership: `signal?.aborted` is checked at entry AND re-checked immediately
// after `reviewer.review` resolves, BEFORE any effect (save, gate exit) — abort ⇒ the `aborted`
// arm with nothing saved and the gate untouched.

import type { WorkflowSession } from "../../session/workflowSession.ts";
import { renderObjectiveDraft, resumeObjectiveDraft } from "./draft.ts";

/**
 * The reviewer's verdict on the rendered objective bytes. `approvedDirectEdits` carries the
 * FULL raw feedback (the adapter renders the revise-round guidance with it); the heading check
 * that produces it stays adapter-side (provider vocabulary).
 */
export type ObjectiveReviewOutcome =
  | { status: "approved"; feedback?: string; reviewId?: string }
  | { status: "approvedDirectEdits"; rawFeedback: string; reviewId?: string }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/** The reviewer role: judge the rendered objective markdown (view-only). */
export interface ObjectiveDraftReviewer {
  review(rendered: string, signal?: AbortSignal): Promise<ObjectiveReviewOutcome>;
}

/**
 * The structural approval-save shape the review op routes over. The adapter binds a RICHER twin
 * (`objectiveApprovalSaveV1` — arms carrying rendered results + `gateExited`); the arms flow
 * through VERBATIM via the generic, so no information is erased and no cast is needed.
 */
export interface ObjectiveApprovalSaveShape {
  status: "no-draft" | "saved" | "save-failed";
}

/** The one-entry review outcome — each arm carries exactly what its caller renders. */
export type ReviewObjectiveDraftResult<A extends ObjectiveApprovalSaveShape> =
  | { status: "noDraft" }
  | { status: "approvedSave"; save: A; feedback?: string; reviewId?: string }
  | { status: "approvedDirectEdits"; rawFeedback: string; reviewId?: string }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/**
 * Review the working objective draft end-to-end: resume (none ⇒ `noDraft` — the adapter renders
 * the `no_objective_draft` skip) → render → review → the abort checkpoint → route. Routing:
 * `approved` ⇒ `approvalSave()` (the injected orchestration re-resumes the draft itself — the
 * artifact is the save source, never the rendered bytes; one extra validated read, no
 * observable delta) · `approvedDirectEdits` ⇒ the revise-round refusal arm — NOTHING saved, the
 * gate untouched · `denied`/`dismissed`/`aborted`/`unavailable` pass through. Never throws.
 */
export async function reviewObjectiveDraft<A extends ObjectiveApprovalSaveShape>(
  deps: {
    session: WorkflowSession;
    reviewer: ObjectiveDraftReviewer;
    approvalSave: () => Promise<A>;
  },
  signal?: AbortSignal,
): Promise<ReviewObjectiveDraftResult<A>> {
  if (signal?.aborted) return { status: "aborted" };
  const draft = resumeObjectiveDraft(deps.session);
  if (draft === null) return { status: "noDraft" };

  const outcome = await deps.reviewer.review(renderObjectiveDraft(draft), signal);
  // The abort checkpoint: a turn interrupted while the reviewer ran must produce NO effect —
  // no save, no gate exit (the aborted arm wins over any verdict).
  if (signal?.aborted) return { status: "aborted" };

  switch (outcome.status) {
    case "approved":
      return {
        status: "approvedSave",
        save: await deps.approvalSave(),
        ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
        ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
      };
    case "approvedDirectEdits":
      // The revise-round refusal: rendered-markdown edits cannot fold back into the structured
      // draft mechanically — nothing saved, the gate untouched; the adapter renders the
      // revise guidance with the FULL feedback.
      return {
        status: "approvedDirectEdits",
        rawFeedback: outcome.rawFeedback,
        ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
      };
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
