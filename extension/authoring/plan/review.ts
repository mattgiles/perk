// The plan review feature: the `PlanDraftReviewer` role (one production adapter per review
// backend — plannotator bridge or first-party editor, both built in pi/v1 — plus a scripted fake
// in the tests), the reviewer-edits mechanical-apply ladder, and the one-entry `reviewPlanDraft`
// operation.
//
// Ordering is the review door's exact discipline: resolve FIRST (artifact → param ONLY — the
// review surface never sees a transcript tier; none ⇒ `noPlan`) → review → the abort checkpoint
// → route the verdict. Provider vocabulary (plannotator's `# Direct Edits` prose) is translated
// INTO `PlanReviewOutcome` at the adapter — the feature sees typed variants only.
//
// Cancellation ownership: `signal?.aborted` is checked at entry AND re-checked immediately
// after `reviewer.review` resolves, BEFORE any effect (apply ladder, save, gate exit) — abort ⇒
// the `aborted` arm with nothing saved and the gate untouched. The backend save itself is not
// abortable mid-flight (today's behavior, stated in save.ts).
//
// The gate-safety invariant is FEATURE-OWNED: an `implementHere` verdict under
// `allowImplementHere: false` (an objective-node planning session — a node-linked plan must
// save) REFUSES with the distinct `implementHereRefused` arm — nothing saved, gate untouched.
// The adapter's verdict suppression under a node claim remains the UX layer (the option is
// never offered); this arm is the defensive backstop.

import type { WorkflowSession } from "../../session/workflowSession.ts";
import { applyUnifiedDiff } from "../../substrate/unifiedDiff.ts";
import type { ApprovalGate } from "../review/approvalGate.ts";
import { PLAN_DRAFT_ARTIFACT, resumePlanDraft } from "./draft.ts";
import {
  type PlanApprovalSaveOutcome,
  type PlanBackend,
  type PlanSaveDeps,
  planApprovalSave,
} from "./save.ts";
import { resolvePlanSource } from "./source.ts";

/**
 * The reviewer's verdict on the plan bytes. `approvedDirectEdits` carries the reviewer's
 * extracted unified diff (`remainder` is the annotation feedback surviving after the applied
 * section is stripped; `rawFeedback` the FULL original — the fail-open ladder saves verbatim
 * with it). `approvedEditsUnparseable` is the seen-heading/unextractable-diff arm: the section
 * was seen but cannot be honored — verbatim save of the ORIGINAL bytes with the FULL feedback
 * preserved and the loud `directEditsFailed` flag.
 */
export type PlanReviewOutcome =
  | { status: "approved"; feedback?: string; reviewId?: string }
  | {
      status: "approvedDirectEdits";
      diff: string;
      remainder?: string;
      rawFeedback: string;
      reviewId?: string;
    }
  | { status: "approvedEditsUnparseable"; rawFeedback: string; reviewId?: string }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "implementHere"; reviewId: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/**
 * What one review round produced: the typed outcome, the FINAL reviewed bytes (`plan`), and
 * whether the human edited them. The first-party reviewer adapter writes human edits back to
 * the draft INSIDE the reviewer (before the verdict — a failed write-back is the `unavailable`
 * abort), so `plan` is the final reviewed bytes and `edited` the differ bit; the plannotator
 * reviewer returns the input unchanged (`edited: false` — browser edits arrive as the Direct
 * Edits diff on the outcome, applied feature-side).
 */
export type PlanDraftReviewResult = { outcome: PlanReviewOutcome; plan: string; edited: boolean };

/** The reviewer role: judge the resolved plan bytes. */
export interface PlanDraftReviewer {
  review(plan: string, signal?: AbortSignal): Promise<PlanDraftReviewResult>;
}

/**
 * The plan-arm mechanical-apply ladder for reviewer edits: strict `applyUnifiedDiff` → draft
 * write-back through the session (reviewed bytes == artifact bytes == saved bytes). Every rung
 * fails open — the caller renders the loud warning and saves verbatim. Never throws.
 */
export function applyReviewerEdits(
  session: WorkflowSession,
  basePlan: string,
  edits: { diff: string },
): { status: "applied"; plan: string } | { status: "failed" } {
  const patched = applyUnifiedDiff(basePlan, edits.diff);
  if (patched === null) return { status: "failed" };
  const written = session.writeArtifact(PLAN_DRAFT_ARTIFACT, patched);
  if (written.status !== "applied" && written.status !== "unchanged") return { status: "failed" };
  return { status: "applied", plan: patched };
}

/** The review-operation dependency bag (the adapter composes production values). */
export interface ReviewPlanDraftDeps extends PlanSaveDeps {
  reviewer: PlanDraftReviewer;
  backend: PlanBackend;
  gate: ApprovalGate;
  /** The `plan` param fallback (the artifact wins; review mode never sees a transcript). */
  explicit?: string;
  /** False in an objective-node planning session — the no-save exit refuses there. */
  allowImplementHere: boolean;
}

/** The plan-arm save flags every approved arm carries (the adapter's rendering opts). */
interface ApprovedFlags {
  feedback?: string;
  reviewId?: string;
  paramMismatch: boolean;
  edited: boolean;
  directEditsFailed: boolean;
}

/** The one-entry review outcome — each arm carries exactly what its caller renders. */
export type ReviewPlanDraftResult =
  | { status: "noPlan" }
  | ({
      status: "approvedSaved";
      save: Extract<PlanApprovalSaveOutcome, { status: "saved" }>;
    } & ApprovedFlags)
  | ({
      status: "approvedSaveFailed";
      save: Extract<PlanApprovalSaveOutcome, { status: "save-failed" }>;
    } & ApprovedFlags)
  | ({ status: "approvedNoPlan" } & ApprovedFlags)
  | {
      status: "implementHere";
      reviewId: string;
      gateExited: boolean;
      plan: string;
      edited: boolean;
    }
  | { status: "implementHereRefused" }
  | { status: "denied"; feedback?: string; reviewId?: string }
  | { status: "dismissed" }
  | { status: "aborted" }
  | { status: "unavailable"; warning: string };

/**
 * Review the working plan draft end-to-end: resolve (artifact → param ONLY; none ⇒ `noPlan`) →
 * review → the abort checkpoint → route. Routing: `approvedDirectEdits` ⇒ the apply ladder
 * (success ⇒ save the EDITED bytes with `edited: true` + remainder-only feedback; failure ⇒
 * verbatim save + `directEditsFailed`) · `approvedEditsUnparseable` ⇒ verbatim save + the FULL
 * raw feedback + `directEditsFailed` (fail-open-but-loud) · `approved` ⇒ `planApprovalSave`
 * with the reviewed bytes (`edited` rides into the flags) · `implementHere` ⇒ gate exit WITHOUT
 * save when allowed, else the `implementHereRefused` refusal · everything else passes through.
 * Never throws.
 */
export async function reviewPlanDraft(
  deps: ReviewPlanDraftDeps,
  signal?: AbortSignal,
): Promise<ReviewPlanDraftResult> {
  if (signal?.aborted) return { status: "aborted" };
  const src = resolvePlanSource(
    { draft: resumePlanDraft(deps.session), explicit: deps.explicit },
    "review",
  );
  if (src === null) return { status: "noPlan" };

  const result = await deps.reviewer.review(src.plan, signal);
  // The abort checkpoint: a turn interrupted while the reviewer ran must produce NO effect —
  // no apply ladder, no save, no gate exit (the aborted arm wins over any verdict).
  if (signal?.aborted) return { status: "aborted" };
  const outcome = result.outcome;

  const approvalSave = (reviewedPlan: string): Promise<PlanApprovalSaveOutcome> =>
    planApprovalSave(deps, { reviewedPlan });
  const flags = (
    partial: Pick<ApprovedFlags, "feedback" | "reviewId"> &
      Partial<Pick<ApprovedFlags, "edited" | "directEditsFailed">>,
  ): ApprovedFlags => ({
    ...(partial.feedback !== undefined ? { feedback: partial.feedback } : {}),
    ...(partial.reviewId !== undefined ? { reviewId: partial.reviewId } : {}),
    paramMismatch: src.paramMismatch,
    edited: partial.edited ?? false,
    directEditsFailed: partial.directEditsFailed ?? false,
  });
  const savedResult = (save: PlanApprovalSaveOutcome, f: ApprovedFlags): ReviewPlanDraftResult => {
    switch (save.status) {
      case "saved":
        return { status: "approvedSaved", save, ...f };
      case "save-failed":
        return { status: "approvedSaveFailed", save, ...f };
      case "no-plan":
        return { status: "approvedNoPlan", ...f };
    }
  };

  switch (outcome.status) {
    case "approvedDirectEdits": {
      // Mechanically apply the reviewer's diff to the exact bytes reviewed, write the patched
      // bytes back to the draft, and save THOSE (only the annotation remainder survives as
      // feedback — the applied diff must never render as "apply these exact changes" guidance).
      // Any rung failing falls open to the verbatim save + the loud directEditsFailed flag.
      const applied = applyReviewerEdits(deps.session, result.plan, { diff: outcome.diff });
      if (applied.status === "applied") {
        return savedResult(
          await approvalSave(applied.plan),
          flags({
            ...(outcome.remainder !== undefined ? { feedback: outcome.remainder } : {}),
            ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
            edited: true,
          }),
        );
      }
      return savedResult(
        await approvalSave(result.plan),
        flags({
          feedback: outcome.rawFeedback,
          ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
          directEditsFailed: true,
        }),
      );
    }
    case "approvedEditsUnparseable":
      // The seen-heading/unextractable-diff arm: verbatim save of the ORIGINAL bytes, the FULL
      // feedback preserved, plus the loud warning flag (fail-open-but-loud).
      return savedResult(
        await approvalSave(result.plan),
        flags({
          feedback: outcome.rawFeedback,
          ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
          directEditsFailed: true,
        }),
      );
    case "approved":
      return savedResult(
        await approvalSave(result.plan),
        flags({
          ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
          ...(outcome.reviewId !== undefined ? { reviewId: outcome.reviewId } : {}),
          edited: result.edited,
        }),
      );
    case "implementHere": {
      if (!deps.allowImplementHere) return { status: "implementHereRefused" };
      // The sanctioned no-save exit (contracts §8.23): gate off WITHOUT saving; the draft
      // artifact stays intact so /plan-save can still create the canonical issue later.
      const wasActive = deps.gate.isActive();
      if (wasActive) deps.gate.exit();
      return {
        status: "implementHere",
        reviewId: outcome.reviewId,
        gateExited: wasActive,
        plan: result.plan,
        edited: result.edited,
      };
    }
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
