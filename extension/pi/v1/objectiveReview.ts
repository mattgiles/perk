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
// result; an unconfirmed save is non-terminating, leaves the gate read-only, and latches
// automatic saves off for the activation (`draftReview.ts`) — `/objective-save` is the
// deliberate retry. Every arm opens the current-review slot at entry and runs the decision
// ladder on a completed verdict before anything is saved.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { renderObjectiveDraft, resumeObjectiveDraft } from "../../authoring/objective/draft.ts";
import {
  completeObjectiveReview,
  type ObjectiveReviewOutcome,
  type ReviewObjectiveDraftResult,
} from "../../authoring/objective/review.ts";
import { objectiveApprovalSave } from "../../authoring/objective/save.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import {
  checkDraftReviewDecision,
  type DecisionCheck,
  type DraftReviewSlot,
  destinationChangedResult,
  type OpenDraftReview,
  openRefusedResult,
  recordSaveOutcome,
  saveUnconfirmedResult,
  staleApprovalResult,
  supersededReviewResult,
  withDraftChangedNote,
} from "./draftReview.ts";
import {
  type ObjectiveApprovalSaveV1Outcome,
  objectiveSaveDepsFor,
  renderObjectiveApprovalSave,
} from "./objectiveAuthoring.ts";
import { hasDirectEditsHeading } from "./providers/plannotator.ts";
import { isPlannotatorPlanSelected } from "./providers/selection.ts";
import {
  approvedSubjectSaveResult,
  chooseReviewLaunch,
  type DraftReviewBridge,
  type ReviewOutcome,
  type ReviewSubject,
  runFirstPartyReview,
  skipResult,
  subjectReviewOutcomeResult,
  type ToolResult,
  untrustedReviewFeedback,
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
          `Reviewer feedback:\n${untrustedReviewFeedback(feedback)}`,
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

/**
 * The first-party reviewer: the in-TUI editor review, VIEW-ONLY (3 verdicts). Returns the door
 * vocabulary (`ReviewOutcome`) so both arms share one ladder + completion path.
 */
async function firstPartyObjectiveReview(
  ctx: ExtensionContext,
  rendered: string,
  signal: AbortSignal | undefined,
): Promise<ReviewOutcome> {
  const fp = await runFirstPartyReview({
    ui: ctx.ui,
    plan: rendered,
    writeDraft: () => true, // unreachable under viewOnly — the branch is skipped
    signal,
    editorTitle: OBJECTIVE_REVIEW_EDITOR_TITLE,
    verdicts: verdictsFor(OBJECTIVE_SUBJECT),
    viewOnly: true,
  });
  return fp.outcome;
}

/** Whether a completed bridge outcome's effect is a save (an approval without Direct Edits). */
export function objectiveEffectOf(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
): "save" | "revision" {
  return outcome.approved &&
    !(outcome.feedback !== undefined && hasDirectEditsHeading(outcome.feedback))
    ? "save"
    : "revision";
}

/**
 * Render a non-`proceed` ladder verdict as the objective arm's tool result (nothing saved; the
 * gate untouched). Shared by the Plannotator arm, the first-party arm and the browser door.
 */
export function objectiveGuardResult(
  check: Exclude<DecisionCheck, { kind: "proceed" }>,
  review: OpenDraftReview,
  feedback: string | undefined,
): ToolResult {
  switch (check.kind) {
    case "superseded":
      return supersededReviewResult("objective");
    case "save-unconfirmed":
      return saveUnconfirmedResult("objective", review.runId, check.detail, feedback);
    case "stale-approval":
      return staleApprovalResult("objective", check.reviewedDigest, feedback);
    case "destination-changed":
      return destinationChangedResult("objective", check.changed, feedback);
  }
}

/** Report a completed objective review's save result into the unconfirmed-save latch. */
function recordObjectiveSaveOutcome(
  slot: DraftReviewSlot,
  result: ReviewObjectiveDraftResult<ObjectiveApprovalSaveV1Outcome>,
): void {
  if (result.status !== "approvedSave") return;
  const save = result.save;
  switch (save.status) {
    case "saved":
      recordSaveOutcome(slot, "objective", { confirmed: true });
      return;
    case "save-failed":
      recordSaveOutcome(slot, "objective", {
        confirmed: false,
        detail: save.result.details.ok ? undefined : save.result.details.error,
      });
      return;
    case "no-draft":
    case "refused-draft":
      // Nothing reached the backend — no attempt to confirm.
      return;
  }
}

/**
 * The objective review arm, mirroring the plan arm's shape: the headless skip, the wave arm's
 * launch chooser, the slot open (both arms — the resume's raw artifact bytes are the reviewed
 * bytes, the rendered markdown what the reviewer saw; ONE validated read serves both), the
 * review, the decision ladder on a completed verdict, then the subject completion with the
 * save reported into the latch.
 */
export async function executeObjectiveReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: DraftReviewBridge,
  slot: DraftReviewSlot,
  signal?: AbortSignal,
  wave?: WaveLaunch,
): Promise<ToolResult> {
  // 1. Headless → soft skip (fail-open; never wedges CI/supervisor runs on an interactive UI).
  if (!ctx.hasUI) return skipResult();
  const sig = signal ?? ctx.signal;
  // 2. ONE validated read serves both the rendering and the reviewed-bytes baseline (the
  //    resume carries the exact bytes it decoded), so the baseline can never be newer than
  //    what the human saw — a second read could straddle a concurrent objective_draft write
  //    and let an approval save bytes nobody reviewed. Raw artifact bytes as the baseline on
  //    purpose: the save-authoritative surface catches render-invisible changes.
  const session = openBranchWorkflowSession(pi, ctx);
  // 3. Backend dispatch (mirrors the plan path): plannotator-selected → the bridge; ANY other
  //    selection → the first-party editor, view-only.
  const plannotator = isPlannotatorPlanSelected(ctx.cwd);
  if (plannotator && wave?.present()) {
    // The launch chooser (contracts.md §8.23): every eligible round the human picks with/without
    // the streamed reviewer wave BEFORE anything launches. Eligibility is drafts-only — the wave
    // door stale-guards the raw artifact bytes, so an absent draft keeps the plain path
    // (silently: there is no forced mode to warn about). A `refused` resume (raw bytes
    // present but refused) also skips the wave arm — the plain review below renders the
    // refused-draft skip exactly once.
    const resumed = resumeObjectiveDraft(session);
    if (resumed.kind === "valid") {
      const choice = await chooseReviewLaunch(ctx.ui, "Objective", sig);
      if (choice.launch === "aborted") return objectiveReviewOutcomeResult({ status: "aborted" });
      if (choice.launch === "wave") {
        const guidance = await wave.objective(ctx, {
          // The reviewed bytes are the RENDERED markdown (prose + roadmap table) — never raw
          // JSON; the stale-guard baseline is the SAME read's raw bytes.
          rendered: renderObjectiveDraft(resumed.draft),
          artifactRaw: resumed.raw,
          ...(choice.custom !== undefined ? { custom: choice.custom } : {}),
        });
        // Abort outranks the opener result too: a turn interrupted during the awaited open must
        // never report a successful launch (the door's own bridge abort handling settles the
        // background tasks and clears the primed surfaces).
        if (sig?.aborted) return objectiveReviewOutcomeResult({ status: "aborted" });
        if (guidance !== null) return waveLaunchedResult(OBJECTIVE_SUBJECT, guidance);
        // null = the synchronous port-pick failure (already loudly reported inside the core) —
        // fall open to the plain blocking review in the same call: the review never wedges.
      }
    }
  }

  if (sig?.aborted) return objectiveReviewOutcomeResult({ status: "aborted" });
  // 4. Resolve the reviewed bytes: a fresh validated resume (the chooser above was a human
  //    wait) — its draft for the render, its raw bytes for the guard (never the rendered bytes
  //    — the save re-reads the STRUCTURED artifact).
  const resumed = resumeObjectiveDraft(session);
  if (resumed.kind === "absent") return noObjectiveDraftResult();
  if (resumed.kind === "refused")
    return renderObjectiveReviewResult({ status: "refusedDraft", problem: resumed.problem });
  const rendered = renderObjectiveDraft(resumed.draft);
  const opened = slot.open(ctx, {
    subject: "objective",
    source: plannotator ? "artifact" : "editor",
    raw: resumed.raw,
    markdown: rendered,
  });
  if (!opened.ok) return openRefusedResult(opened);
  const review = opened.review;

  // 5. The review itself, then the ladder, then the completion.
  const outcome = plannotator
    ? await bridge.review(rendered, sig)
    : await firstPartyObjectiveReview(ctx, rendered, sig);
  if (sig?.aborted) return objectiveReviewOutcomeResult({ status: "aborted" });
  if (outcome.status !== "completed") return objectiveReviewOutcomeResult(outcome);
  const check = checkDraftReviewDecision(slot, ctx, review, objectiveEffectOf(outcome));
  if (check.kind !== "proceed") return objectiveGuardResult(check, review, outcome.feedback);
  return withDraftChangedNote(
    await completeObjectiveReviewV1(pi, ctx, gating, slot, outcome),
    check.draftChanged,
  );
}

export function renderObjectiveReviewResult(
  result: ReviewObjectiveDraftResult<ObjectiveApprovalSaveV1Outcome>,
): ToolResult {
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

/**
 * The objective completion shared by both tool arms and the browser door: a completed outcome
 * → the feature completion (an approval re-reads the STRUCTURED artifact and saves through the
 * production deps; Direct Edits is the no-save revise round) → the latch record → the rendered
 * tool result. The caller has already run the decision ladder.
 */
export async function completeObjectiveReviewV1(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  slot: DraftReviewSlot,
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
): Promise<ToolResult> {
  const result = await completeObjectiveReview(objectiveOutcomeOf(outcome), async () =>
    renderObjectiveApprovalSave(
      pi,
      ctx,
      await objectiveApprovalSave(objectiveSaveDepsFor(pi, ctx, gating)),
    ),
  );
  recordObjectiveSaveOutcome(slot, result);
  return renderObjectiveReviewResult(result);
}
