// The objective review arm of the `plan_review` door — relocated INTACT from the legacy review
// door module as the objective flavors' stable adapter home (the objective feature extraction
// arrives with its own slice; this module stays Pi-shaped adapter code until then). It imports
// the shared review-surface machinery from `pi/v1/review.ts`, the plannotator helpers from
// `pi/v1/providers/`, and the objective feature modules from `factories/` (the sanctioned
// pi/v1 → factories direction).
//
// THE OBJECTIVE ARM: an objective-authoring session (read-only, stage `objective-author` or
// `objective-save` — the two stages whose working draft IS the objective draft; neither carries
// `plan_draft`) routes through `executeObjectiveReview` instead of the plan path — the
// reviewed bytes are the RENDERED objective draft (`readObjectiveDraft` + `renderObjectiveDraft`,
// objectiveDraft.ts — never raw JSON, never the `plan` param, never the transcript; no draft
// soft-skips with `reason: "no_objective_draft"`). Dispatch mirrors the plan path (plannotator
// bridge or the first-party editor, VIEW-ONLY — edits are never written back; deny+feedback is
// the change channel). An APPROVED outcome wires into the `objectiveApprovalSave` seam
// (objectiveSave.ts): re-read the STRUCTURED artifact → `saveObjective` → D1a gate
// exit → a TERMINATING result; a failed save is non-terminating, leaves the gate read-only, and
// directs the human `/objective-save` failsafe.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  OBJECTIVE_DRAFT_ARTIFACT,
  readObjectiveDraft,
  renderObjectiveDraft,
} from "../../factories/objectiveDraft.ts";
import {
  type ObjectiveApprovalSaveOutcome,
  objectiveApprovalSave,
} from "../../factories/objectiveSave.ts";
import { readSessionArtifact } from "../../substrate/sessionData.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
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
 * Map an APPROVED objective review outcome + the `objectiveApprovalSave` outcome into the
 * model-facing tool result (exported for the offline tests) — the objective sibling of
 * `approvedSaveResult`, delegating to `approvedSubjectSaveResult` with `OBJECTIVE_SUBJECT` and
 * no opts (the objective path reviews only the rendered draft, view-only — no
 * `paramMismatch`/`edited`).
 */
export function approvedObjectiveSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ObjectiveApprovalSaveOutcome,
): ToolResult {
  return approvedSubjectSaveResult(
    OBJECTIVE_SUBJECT,
    outcome,
    save.status === "no-draft" ? { status: "no-source" } : save,
  );
}

/**
 * The objective review arm, mirroring the plan arm's shape but
 * with the rendered objective draft as the SOLE review source (never the `plan` param, never
 * the transcript). First-party reviews run VIEW-ONLY (edits are never written back;
 * deny+feedback is the change channel). An APPROVED outcome wires into the
 * `objectiveApprovalSave` seam (re-read the STRUCTURED artifact → `saveObjective` → D1a gate
 * exit → terminating); every other outcome maps via `objectiveReviewOutcomeResult`. ONE
 * carve-out (plannotator only): an approval whose feedback opens a Direct Edits section SKIPS
 * the save — rendered-markdown edits cannot be folded back into the structured draft
 * mechanically — and returns a NON-terminating revise round with the gate untouched (fold the
 * diff in via `objective_draft`, re-review to confirm); perk never saves an objective the
 * reviewer explicitly edited away from.
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
  // 2. The wave arm's stale-guard baseline is captured BEFORE the validated read below (the
  //    objective door's fail-closed ordering): the rendered bytes always derive from a read at
  //    or after this baseline, so a concurrent objective_draft write between the two reads makes
  //    the browsed render NEWER than the baseline and routeObjectiveReviewDecision's existing
  //    guard refuses the approval — the reverse order would fail open (approve unreviewed
  //    bytes). Raw artifact bytes on purpose: the save-authoritative surface catches
  //    render-invisible changes.
  const baseline = readSessionArtifact(ctx, OBJECTIVE_DRAFT_ARTIFACT);
  // 3. The draft artifact is the sole review source — no draft → soft skip with the
  //    objective_draft redirect.
  const draft = readObjectiveDraft(ctx);
  if (draft === null) {
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
  // 4. The reviewed bytes are the RENDERED markdown (prose + roadmap table) — never raw JSON.
  const rendered = renderObjectiveDraft(draft);
  // 5. Backend dispatch (mirrors the plan path): plannotator-selected → the bridge; ANY other
  //    selection → the first-party editor, view-only.
  const sig = signal ?? ctx.signal;
  let outcome: ReviewOutcome;
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    // The launch chooser (contracts.md §8.23): every eligible round the human picks with/without
    // the streamed reviewer wave BEFORE anything launches. Eligibility is drafts-only — the wave
    // door stale-guards the raw artifact baseline, so a null baseline keeps the plain path
    // (silently: there is no forced mode to warn about).
    if (wave?.present() && baseline !== null) {
      const choice = await chooseReviewLaunch(ctx.ui, "Objective", sig);
      if (choice.launch === "aborted") return objectiveReviewOutcomeResult({ status: "aborted" });
      if (choice.launch === "wave") {
        const guidance = await wave.objective(ctx, {
          rendered,
          artifactRaw: baseline.content,
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
    outcome = await bridge.review(rendered, sig);
    // APPROVE + Direct Edits (browser edits of the RENDERED markdown), checked BEFORE the
    // approved-save routing (the approved-first discipline): the save seam re-reads the
    // STRUCTURED artifact, so rendered-markdown edits — roadmap-table rows included — cannot be
    // folded back without model judgment. Skip the save, keep the gate read-only, and route ONE
    // revise round: the model folds the diff into `objective_draft`, then re-reviews to confirm.
    // The heading check suffices (extraction success is irrelevant here — the diff goes to the
    // model verbatim either way).
    if (
      outcome.status === "completed" &&
      outcome.approved &&
      outcome.feedback !== undefined &&
      hasDirectEditsHeading(outcome.feedback)
    ) {
      return {
        content: [
          {
            type: "text",
            text:
              "objective APPROVED with direct browser edits — these cannot be auto-applied to " +
              "the structured draft, so nothing was saved. Fold the Direct Edits diff below into " +
              "the working draft with objective_draft (prose hunks → the prose; roadmap-table " +
              "hunks → the matching node fields), then call plan_review again to confirm.\n\n" +
              `Reviewer feedback:\n${outcome.feedback}`,
          },
        ],
        details: {
          ok: true,
          status: "revise",
          reason: "direct_edits",
          approved: true,
          feedback: outcome.feedback,
          reviewId: outcome.reviewId,
          subject: "objective",
        },
      };
    }
  } else {
    const fp = await runFirstPartyReview({
      ui: ctx.ui,
      plan: rendered,
      writeDraft: () => true, // unreachable under viewOnly — the branch is skipped
      signal: sig,
      editorTitle: OBJECTIVE_REVIEW_EDITOR_TITLE,
      verdicts: verdictsFor(OBJECTIVE_SUBJECT),
      viewOnly: true,
    });
    outcome = fp.outcome;
  }
  // 6. An APPROVED decision (either backend) wires into the objectiveApprovalSave seam (the
  //    STRUCTURED artifact is re-read at save time — never the rendered bytes; auto-save → D1a
  //    gate exit → terminating result); everything else maps via objectiveReviewOutcomeResult.
  //    Approved-first routing: objectiveReviewOutcomeResult's completed case renders DENIED.
  if (outcome.status === "completed" && outcome.approved) {
    const save = await objectiveApprovalSave(pi, ctx, gating);
    return approvedObjectiveSaveResult(outcome, save);
  }
  return objectiveReviewOutcomeResult(outcome);
}
