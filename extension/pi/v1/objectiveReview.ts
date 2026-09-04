// The objective review arm of the `plan_review` door — a thin ADAPTER over the feature's
// `reviewObjectiveDraft` (authoring/objective/review.ts). This module owns what is genuinely
// Pi/provider-shaped: the headless skip, the wave arm's raw-baseline read ordering, the launch
// chooser, the two reviewer constructions (plannotator bridge / first-party view-only editor —
// provider vocabulary is translated INTO `ObjectiveReviewOutcome` here, the `# Direct Edits`
// heading check included), the composed `objectiveApprovalSaveV1` binding, and the rendered
// Result envelopes (every text/details shape byte-stable, `details.subject: "objective"`
// included).
//
// THE OBJECTIVE ARM: an objective-authoring session (read-only, stage `objective-author` or
// `objective-save` — the two stages whose working draft IS the objective draft; neither carries
// `plan_draft`) routes through `executeObjectiveReview` instead of the plan path — the
// reviewed bytes are the RENDERED objective draft (the feature's resume+render — never raw
// JSON, never the `plan` param, never the transcript; no draft soft-skips with
// `reason: "no_objective_draft"`). First-party reviews run VIEW-ONLY (edits are never written
// back; deny+feedback is the change channel). An APPROVED outcome wires into the approval→save
// seam: re-read the STRUCTURED artifact → `saveObjective` → D1a gate exit → a TERMINATING
// result; a failed save is non-terminating, leaves the gate read-only, and directs the human
// `/objective-save` failsafe.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  OBJECTIVE_DRAFT_ARTIFACT,
  renderObjectiveDraft,
  resumeObjectiveDraft,
} from "../../authoring/objective/draft.ts";
import {
  type ObjectiveDraftReviewer,
  type ObjectiveReviewOutcome,
  reviewObjectiveDraft,
} from "../../authoring/objective/review.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import {
  type ObjectiveApprovalSaveV1Outcome,
  objectiveApprovalSaveV1,
} from "./objectiveAuthoring.ts";
import { hasDirectEditsHeading } from "./providers/plannotator.ts";
import { isPlannotatorPlanSelected } from "./providers/selection.ts";
import {
  approvedSubjectSaveResult,
  chooseReviewLaunch,
  type ReviewOutcome,
  type ReviewSubject,
  runFirstPartyReview,
  skipResult,
  subjectReviewOutcomeResult,
  type ToolResult,
  verdictsFor,
  type WaveLaunch,
  waveLaunchedResult,
} from "./review.ts";

/** The objective-arm descriptor for the shared renderer cores. */
export const OBJECTIVE_SUBJECT: ReviewSubject = {
  noun: "objective",
  present: "the complete objective + structured roadmap to the user",
  presentUnavailable: "the complete objective + structured roadmap to the user",
  implementHereWhere: "on the objective path",
  draftTool: "objective_draft",
  failsafeCmd: "/objective-save",
  detailsExtra: { subject: "objective" },
  noSourceError: "no objective draft resolved",
};

export const OBJECTIVE_REVIEW_EDITOR_TITLE =
  "Objective review (view only — edits are not saved) — Enter: continue to verdict · Esc: skip · " +
  "Ctrl+G: $EDITOR";

/**
 * Map a non-approved objective review outcome into the model-facing tool result (exported for
 * the offline tests) — the objective-flavored sibling of `reviewOutcomeResult`, delegating to
 * `subjectReviewOutcomeResult` with `OBJECTIVE_SUBJECT`. Every arm carries
 * `details.subject: "objective"`; the texts redirect to `objective_draft` / `/objective-save`.
 * The execute path routes approved outcomes to `approvedObjectiveSaveResult` first, so
 * `completed` renders DENIED here.
 */
export function objectiveReviewOutcomeResult(outcome: ReviewOutcome): ToolResult {
  return subjectReviewOutcomeResult(OBJECTIVE_SUBJECT, outcome);
}

/**
 * Map an APPROVED objective review outcome + the approval-save outcome into the model-facing
 * tool result (exported for the offline tests) — the objective sibling of `approvedSaveResult`,
 * delegating to `approvedSubjectSaveResult` with `OBJECTIVE_SUBJECT` and no opts (the objective
 * path reviews only the rendered draft, view-only — no `paramMismatch`/`edited`).
 */
export function approvedObjectiveSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ObjectiveApprovalSaveV1Outcome,
): ToolResult {
  return approvedSubjectSaveResult(
    OBJECTIVE_SUBJECT,
    outcome,
    save.status === "no-draft"
      ? { status: "no-source" }
      : save.status === "refused-draft"
        ? { status: "refused-draft", problem: save.problem }
        : save,
  );
}

/** The no-draft soft skip (byte-stable redirect to objective_draft). */
function noObjectiveDraftResult(): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          "no objective draft to review — write the working objective with objective_draft " +
          "(prose + the structured roadmap), then call plan_review again.",
      },
    ],
    details: {
      ok: false,
      error: "no objective draft to review — write it with objective_draft first",
      error_type: "no_objective_draft",
      status: "skipped",
      reason: "no_objective_draft",
    },
  };
}

/**
 * The Direct-Edits revise round (plannotator only, contracts §8.23's objective arm): the save
 * seam re-reads the STRUCTURED artifact, so rendered-markdown edits — roadmap-table rows
 * included — cannot be folded back without model judgment. Nothing was saved, the gate stays
 * read-only; the model folds the diff into `objective_draft`, then re-reviews to confirm.
 */
function directEditsReviseResult(feedback: string, reviewId: string | undefined): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          "objective APPROVED with direct browser edits — these cannot be auto-applied to " +
          "the structured draft, so nothing was saved. Fold the Direct Edits diff below into " +
          "the working draft with objective_draft (prose hunks → the prose; roadmap-table " +
          "hunks → the matching node fields), then call plan_review again to confirm.\n\n" +
          `Reviewer feedback:\n${feedback}`,
      },
    ],
    details: {
      ok: true,
      status: "revise",
      reason: "direct_edits",
      approved: true,
      feedback,
      reviewId,
      subject: "objective",
    },
  };
}

/** Rebuild the door's completed outcome from the feature arm (the shared mappers consume it). */
function completedOutcome(
  approved: boolean,
  carried: { feedback?: string; reviewId?: string },
): Extract<ReviewOutcome, { status: "completed" }> {
  return {
    status: "completed",
    approved,
    ...(carried.feedback !== undefined ? { feedback: carried.feedback } : {}),
    reviewId: carried.reviewId ?? "",
  };
}

/**
 * Translate a review-door outcome (`ReviewOutcome`) into the feature's
 * `ObjectiveReviewOutcome`. Plannotator's vocabulary is translated here: an approval whose
 * feedback OPENS with the `# Direct Edits` heading becomes the `approvedDirectEdits` variant —
 * the heading check suffices (extraction success is irrelevant: the diff goes to the model
 * verbatim either way; the variant requires the feedback, so the edits can never be dropped).
 * The `implement-here` arm is unreachable on the objective path (neither reviewer offers it)
 * and maps defensively to `dismissed`.
 */
function objectiveOutcomeOf(outcome: ReviewOutcome): ObjectiveReviewOutcome {
  switch (outcome.status) {
    case "completed": {
      const carried = {
        ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
        reviewId: outcome.reviewId,
      };
      if (outcome.approved) {
        if (outcome.feedback !== undefined && hasDirectEditsHeading(outcome.feedback)) {
          return {
            status: "approvedDirectEdits",
            rawFeedback: outcome.feedback,
            reviewId: outcome.reviewId,
          };
        }
        return { status: "approved", ...carried };
      }
      return { status: "denied", ...carried };
    }
    case "unavailable":
      return { status: "unavailable", warning: outcome.warning };
    case "aborted":
      return { status: "aborted" };
    case "dismissed":
      return { status: "dismissed" };
    case "implement-here":
      return { status: "dismissed" };
  }
}

/** The plannotator reviewer adapter: the event-bus bridge judges the rendered draft. */
function plannotatorObjectiveReviewer(bridge: {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
}): ObjectiveDraftReviewer {
  return {
    async review(rendered, signal) {
      return objectiveOutcomeOf(await bridge.review(rendered, signal));
    },
  };
}

/** The first-party reviewer adapter: the in-TUI editor review, VIEW-ONLY (3 verdicts). */
function firstPartyObjectiveReviewer(ctx: ExtensionContext): ObjectiveDraftReviewer {
  return {
    async review(rendered, signal) {
      const fp = await runFirstPartyReview({
        ui: ctx.ui,
        plan: rendered,
        writeDraft: () => true, // unreachable under viewOnly — the branch is skipped
        signal,
        editorTitle: OBJECTIVE_REVIEW_EDITOR_TITLE,
        verdicts: verdictsFor(OBJECTIVE_SUBJECT),
        viewOnly: true,
      });
      return objectiveOutcomeOf(fp.outcome);
    },
  };
}

/**
 * The objective review arm, mirroring the plan arm's shape: the headless skip, the wave arm's
 * fail-closed baseline ordering + launch chooser, reviewer dispatch (plannotator bridge or
 * first-party view-only editor), then the feature's `reviewObjectiveDraft` routing with
 * `approvalSave` bound to the composed `objectiveApprovalSaveV1` — byte-stable results.
 */
export async function executeObjectiveReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  signal?: AbortSignal,
  wave?: WaveLaunch,
): Promise<ToolResult> {
  // 1. Headless → soft skip (fail-open; never wedges CI/supervisor runs on an interactive UI).
  if (!ctx.hasUI) return skipResult();
  const sig = signal ?? ctx.signal;
  // 2. The wave arm's stale-guard baseline is captured BEFORE any validated read (the
  //    objective door's fail-closed ordering): the reviewed bytes always derive from a read at
  //    or after this baseline, so a concurrent objective_draft write between the two reads makes
  //    the browsed render NEWER than the baseline and routeObjectiveReviewDecision's existing
  //    guard refuses the approval — the reverse order would fail open (approve unreviewed
  //    bytes). Raw artifact bytes on purpose: the save-authoritative surface catches
  //    render-invisible changes.
  const session = openBranchWorkflowSession(pi, ctx);
  const baseline = session.readArtifact(OBJECTIVE_DRAFT_ARTIFACT);
  // 3. Backend dispatch (mirrors the plan path): plannotator-selected → the bridge; ANY other
  //    selection → the first-party editor, view-only. The draft resume/render is owned by the
  //    feature op (step 4) — only the wave arm needs the rendered bytes up front.
  let reviewer: ObjectiveDraftReviewer;
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    // The launch chooser (contracts.md §8.23): every eligible round the human picks with/without
    // the streamed reviewer wave BEFORE anything launches. Eligibility is drafts-only — the wave
    // door stale-guards the raw artifact baseline, so a null baseline keeps the plain path
    // (silently: there is no forced mode to warn about). A non-`valid` resume (raw bytes
    // present but refused) also skips the wave arm — the plain review below renders the
    // refused-draft skip through the feature op's arm, exactly once.
    const resumed =
      wave?.present() && baseline.status === "found" ? resumeObjectiveDraft(session) : null;
    const draft = resumed !== null && resumed.kind === "valid" ? resumed.draft : null;
    if (draft !== null && baseline.status === "found") {
      const choice = await chooseReviewLaunch(ctx.ui, "Objective", sig);
      if (choice.launch === "aborted") return objectiveReviewOutcomeResult({ status: "aborted" });
      if (choice.launch === "wave") {
        const guidance = await wave?.objective(ctx, {
          // The reviewed bytes are the RENDERED markdown (prose + roadmap table) — never raw
          // JSON.
          rendered: renderObjectiveDraft(draft),
          artifactRaw: baseline.content,
          ...(choice.custom !== undefined ? { custom: choice.custom } : {}),
        });
        // Abort outranks the opener result too: a turn interrupted during the awaited open must
        // never report a successful launch (the door's own bridge abort handling settles the
        // background tasks and clears the primed surfaces).
        if (sig?.aborted) return objectiveReviewOutcomeResult({ status: "aborted" });
        if (guidance !== undefined && guidance !== null) {
          return waveLaunchedResult(OBJECTIVE_SUBJECT, guidance);
        }
        // null = the synchronous port-pick failure (already loudly reported inside the core) —
        // fall open to the plain blocking review in the same call: the review never wedges.
      }
    }
    reviewer = plannotatorObjectiveReviewer(bridge);
  } else {
    reviewer = firstPartyObjectiveReviewer(ctx);
  }
  // 4. The feature op owns the routing (resume → render → review → the abort checkpoint →
  //    route): a missing/invalid draft is its `noDraft` arm (rendered below as the soft skip
  //    with the objective_draft redirect); APPROVED wires into the approval→save seam (the
  //    STRUCTURED artifact is re-read at save time — never the rendered bytes; auto-save → D1a
  //    gate exit → terminating result); Direct Edits is the no-save revise round; everything
  //    else maps via objectiveReviewOutcomeResult. Approved-first routing: the completed case
  //    renders DENIED.
  const result = await reviewObjectiveDraft(
    { session, reviewer, approvalSave: () => objectiveApprovalSaveV1(pi, ctx, gating) },
    sig,
  );
  switch (result.status) {
    case "noDraft":
      return noObjectiveDraftResult();
    case "refusedDraft":
      // Fail-closed soft skip (the `noObjectiveDraftResult` shape): an invalid artifact is
      // never reviewed — rewrite, then re-review. Gate untouched.
      return {
        content: [
          {
            type: "text",
            text:
              `the working objective draft is invalid: ${result.problem} — rewrite it with ` +
              "objective_draft, then call plan_review again.",
          },
        ],
        details: {
          ok: false,
          error: result.problem,
          error_type: "bad_state",
          status: "skipped",
          reason: "objective_draft_refused",
        },
      };
    case "approvedDirectEdits":
      return directEditsReviseResult(result.rawFeedback, result.reviewId);
    case "approvedSave":
      return approvedObjectiveSaveResult(completedOutcome(true, result), result.save);
    case "denied":
      return objectiveReviewOutcomeResult(completedOutcome(false, result));
    case "dismissed":
      return objectiveReviewOutcomeResult({ status: "dismissed" });
    case "aborted":
      return objectiveReviewOutcomeResult({ status: "aborted" });
    case "unavailable":
      return objectiveReviewOutcomeResult({ status: "unavailable", warning: result.warning });
  }
}
