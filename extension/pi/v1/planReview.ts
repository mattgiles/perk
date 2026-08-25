// The `plan_review` door's execute paths — the backend-neutral review dispatcher and the PLAN
// arm's adapter over the `authoring/plan/` feature. perk's UNIVERSAL plan-review surface: the
// model calls ONE tool (registered by `pi/v1/plan.ts`, which injects the production dependency
// bag built by `planSaveDepsFor` — the ONE composition point, so this module never imports
// `plan.ts` back); this module dispatches to the configured review backend.
// Plannotator-selected → the event-bus bridge (`createPlannotatorBridge`,
// providers/plannotator.ts — the AUGMENT-posture path, byte-stable); ANY other selection
// (perk-plan, tombell, unknown ids) → the FIRST-PARTY in-TUI editor review
// (`runFirstPartyReview`, pi/v1/review.ts): display the draft in pi's built-in `ctx.ui.editor`
// dialog (scrollable, Ctrl+G opens the user's external $EDITOR), write optional human edits
// back to the draft via the session seam BEFORE the verdict (reviewed bytes == artifact bytes
// == saved bytes — a failed write-back ABORTS the review fail-open, nothing saved), then an
// approve/deny/skip `ctx.ui.select` verdict — on the plan arm with a 4th "Implement here — no
// issue saved" option (§8.23; suppressed in objective-node planning sessions) — with deny
// feedback via a second editor dialog.
//
// REVIEW SEMANTICS (file-first, approval auto-saves): the review runs while the session is still
// read-only (the tool is in READ_ONLY_TOOLS — review happens before the gate ever comes off).
// The reviewed plan resolves FILE-FIRST via `resolvePlanSource` (the validated `plan-draft.md`
// artifact wins; the `plan` param is the fallback; the transcript scrape is NEVER reviewed — an
// approval would auto-save scraped conversation bytes, so no draft + no param soft-skips with a
// `plan_draft` redirect). An APPROVED outcome (either backend) wires into the shared
// `planApprovalSave` seam (authoring/plan/save.ts): auto-save → D1a gate exit → terminating
// result, node link recovered from the `objective_node_claim` carrier inside `savePlan`. A DENY
// returns feedback and directs a `plan_draft` rewrite + re-review. Plannotator's browser
// "Direct Edits" (a `# Direct Edits` unified diff opening the feedback) are translated INTO the
// feature's typed `PlanReviewOutcome` at the reviewer adapter below and handled feature-side:
// the PLAN arm mechanically applies an approved diff (strict apply → draft write-back → save
// the edited bytes; any failure falls open to the verbatim save + a loud warning); DENY stays
// model-mediated. Strict on deny, FAIL-OPEN everywhere else: headless / dismissed (Esc anywhere
// = skip, mirroring ask_user_question's dismissal — deny is always explicit) /
// backend-unavailable all soft-skip so plan authoring never wedges — those arms keep the
// present-the-plan + human-`/plan-save` discipline (the manual failsafe).
//
// THE LAUNCH CHOOSER (plannotator arms only, §8.23): on an eligible round (injected `WaveLaunch`
// deps present, plannotator loaded, the review source a validated draft artifact) the tool first
// asks the human — "Browser review + reviewer wave" vs "Browser review only" — before anything
// launches. The wave choice collects an optional trimmed custom angle, delegates to the door's
// guidance-returning open core (openPlanReviewSurface / openObjectiveReviewSurface, injected —
// never imported: doors value-import the review arms), and returns the NON-terminating
// `wave_launched` result carrying the door guidance verbatim; the browser decision then routes
// through the door's background decision task. Esc ⇒ the plain flavor (never a cancel); abort
// outranks every dialog result AND the awaited opener (an interrupted turn never reports a
// launched wave); a null opener return (synchronous port-pick failure, loudly reported in the
// core) falls open to the plain blocking review in the same call.
//
// THE OBJECTIVE ARM routes to `pi/v1/objectiveReview.ts`; THE GIST ARM routes to
// `pi/v1/gist.ts`'s `runGistReviewV1` — direct sibling imports (the injected-arm indirection
// died with the factories home; `pi/v1` siblings import directly, and none of them import this
// module back).
//
// INVARIANTS HELD: never calls `setActiveTools`, never registers a `tool_call` handler, never
// restamps `cache.plan-ref.provider`. The door composes the gate AND the save EXCLUSIVELY
// through the feature seams (Invariant 1: composes, never owns).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { GIST_AUTHOR_STAGE } from "../../authoring/gist/draft.ts";
import { OBJECTIVE_AUTHOR_STAGE, OBJECTIVE_SAVE_STAGE } from "../../authoring/objective/prose.ts";
import { resumePlanDraft, revisePlanDraft } from "../../authoring/plan/draft.ts";
import {
  applyReviewerEdits,
  type PlanDraftReviewer,
  type PlanReviewOutcome,
  type ReviewPlanDraftResult,
  reviewPlanDraft,
} from "../../authoring/plan/review.ts";
import type {
  ObjectiveNodeLink,
  PlanApprovalSaveDeps,
  SavePlanOutcome,
} from "../../authoring/plan/save.ts";
import { type PlanSource, resolvePlanSource } from "../../authoring/plan/source.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import { bindingSuffix } from "../../substrate/bindingDelivery.ts";
import type { PlanRef } from "../../substrate/cache.ts";
import type { Result } from "../../substrate/result.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { paramsOf, stringParam } from "../../substrate/toolParams.ts";
import { branchOf, rebuildWorkflowState } from "../../substrate/workflowState.ts";
import { report } from "../../surfaces/report.ts";
import { runGistReviewV1 } from "./gist.ts";
import { executeObjectiveReview } from "./objectiveReview.ts";
import { extractDirectEdits, hasDirectEditsHeading } from "./providers/plannotator.ts";
import { isPlannotatorPlanSelected } from "./providers/selection.ts";
import {
  approvedSubjectSaveResult,
  chooseReviewLaunch,
  PLAN_SUBJECT,
  type ReviewOutcome,
  runFirstPartyReview,
  skipResult,
  subjectReviewOutcomeResult,
  type ToolResult,
  VERDICT_IMPLEMENT_HERE,
  verdictsFor,
  type WaveLaunch,
  waveLaunchedResult,
} from "./review.ts";

/** The review bridge slice the installer builds over the plannotator event bus. */
export interface PlanReviewBridge {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
}

/** The warm-door ok-arm fields — the `details` surface doubles as branch-safe persisted state. */
export interface PlanSaveOk {
  /** `issue.id` is the opaque string issue id (GitHub "42", Linear "ENG-123") — §8.21. */
  issue: { id: string; url: string };
  plan_ref: PlanRef;
  cached: boolean;
  existed: boolean | null;
  updated: boolean;
  objective_node: ObjectiveNodeLink | null;
  plan_source: PlanSource | null;
}

/**
 * The rendered save result every plan-save surface returns (AgentToolResult has no `isError`;
 * failure is signaled via `details.ok`). Declared HERE with the `renderSave` port it types (the
 * concrete shape must stay visible through `approvalSave` — callers narrow `details.ok` and read
 * `objective_node` WITHOUT assertions); the one production renderer lives in `plan.ts`.
 */
export type SaveResult = Result<PlanSaveOk>;

/**
 * The injected production dependency bag (built by `plan.ts`'s `planSaveDepsFor` — the ONE
 * composition point; declared HERE so `plan.ts` imports the port and the graph stays acyclic):
 * the feature approval-save deps plus the installer-owned save rendering (its message assembly
 * lives with the save surfaces in `plan.ts`).
 */
export interface PlanReviewV1Deps extends PlanApprovalSaveDeps {
  /** Render a feature `SavePlanOutcome` as the warm-door SaveResult (byte-stable messages). */
  renderSave(save: SavePlanOutcome): SaveResult;
}

// ---------------------------------------------------------------------- plan-flavor mappers

/**
 * Map a non-approved review outcome into the model-facing tool result (exported for the offline
 * tests) — the plan flavor of `subjectReviewOutcomeResult`. The execute path routes approved
 * outcomes to `approvedSaveResult` first, so `completed` renders DENIED here.
 */
export function reviewOutcomeResult(outcome: ReviewOutcome): ToolResult {
  return subjectReviewOutcomeResult(PLAN_SUBJECT, outcome);
}

/**
 * The approval→save orchestration outcome as the ADAPTER renders it: the feature's
 * `PlanApprovalSaveOutcome` with the save already rendered as the warm-door Result (the browser
 * door consumes this shape via the `approvalSave` seam in `plan.ts`).
 */
export type ApprovalSaveOutcome =
  | { status: "no-plan" }
  | { status: "saved" | "save-failed"; result: SaveResult; gateExited: boolean };

/**
 * Map an APPROVED review outcome + the `approvalSave` outcome into the model-facing tool result
 * (exported for the offline tests) — the plan flavor of `approvedSubjectSaveResult`. `edited`
 * flags that human edits were written back to the draft pre-verdict (the first-party editor, or
 * the plannotator Direct Edits auto-apply), so the saved bytes carry them. `directEditsFailed`
 * (plannotator-only, optional — absent keeps every existing call site byte-stable) flags a
 * Direct Edits section that could not be honored: the plan saved verbatim, a loud warning added.
 */
export function approvedSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ApprovalSaveOutcome,
  opts: { paramMismatch: boolean; edited?: boolean; directEditsFailed?: boolean },
): ToolResult {
  return approvedSubjectSaveResult(
    PLAN_SUBJECT,
    outcome,
    save.status === "no-plan" ? { status: "no-source" } : save,
    opts,
  );
}

// ------------------------------------------------------------------- the implement-here seam

/** The core instruction text (exported for the offline content pins). */
export const IMPLEMENT_HERE_GUIDANCE = `The human chose IMPLEMENT HERE: implement the reviewed plan directly in this session — no plan issue was created and none will be.

- The read-only gate is off: make the plan's edits now, in this checkout.
- Run the checks the plan calls for before declaring done.
- Do NOT commit, branch, or push unless the user explicitly asks — git gestures stay with the human.
- perk's lifecycle doors (/submit, /land, /learn) do not apply — there is no plan issue or plan-ref.
- The plan draft artifact is untouched: /plan-save can still create the canonical issue later.`;

/** The one info line every implement-here gate exit reports (the seam + the review arm share it). */
const IMPLEMENT_HERE_EXIT_NOTICE =
  "plan mode off — implementing here; no issue saved (draft intact; /plan-save can still create it)";

/**
 * Build the implement-here instruction text. When `editedPlan` is set (review-path human edits
 * were written back to the draft pre-verdict), the final reviewed bytes are inlined so the model
 * implements THOSE, not its stale in-context version. Always appends the Mechanism-B skill-binding
 * suffix for `command:implement-here` (a `[[bindings]]` hook; delivers nothing by default).
 */
export function implementHereGuidance(cwd: string, opts: { editedPlan?: string }): string {
  const edited =
    opts.editedPlan === undefined
      ? ""
      : `\n\nThe human edited the plan during review; implement THESE final bytes:\n\n${opts.editedPlan}`;
  return `${IMPLEMENT_HERE_GUIDANCE}${edited}${bindingSuffix(cwd, "command:implement-here")}`;
}

/**
 * The gate-exit-WITHOUT-save seam — the no-save sibling of `planApprovalSave`'s D1a arm. If the
 * gate is active, exit it and report one info line; otherwise a no-op. Keeps Invariant 1:
 * callers (the review arm's implement-here verdict, the `/implement-here` command) compose the
 * gate through this seam, never own it.
 */
export function implementHereExit(
  ctx: ExtensionContext,
  gating: ToolGating,
): { gateExited: boolean } {
  if (!gating.isActive()) return { gateExited: false };
  gating.exit(ctx);
  report(ctx, "implement-here", "info", IMPLEMENT_HERE_EXIT_NOTICE);
  return { gateExited: true };
}

/**
 * Map an IMPLEMENT-HERE review outcome + the gate-exit outcome into the model-facing
 * tool result (exported for the offline tests). NON-terminating on purpose — the model continues
 * the turn and implements immediately. The text is the implement-here guidance; when the human
 * edited the plan during review (`edited`), the final reviewed bytes are inlined so the model
 * implements THOSE, not its stale in-context version (the draft write-back already happened
 * pre-verdict). Nothing is saved: no issue, no plan-ref, the draft artifact intact (§8.23).
 */
export function implementHereResult(
  outcome: Extract<ReviewOutcome, { status: "implement-here" }>,
  exit: { gateExited: boolean },
  opts: { cwd: string; plan: string; edited: boolean },
): ToolResult {
  return {
    content: [
      {
        type: "text",
        text: implementHereGuidance(opts.cwd, { editedPlan: opts.edited ? opts.plan : undefined }),
      },
    ],
    details: {
      ok: true,
      status: "implement-here",
      saved: false,
      gateExited: exit.gateExited,
      reviewId: outcome.reviewId,
      ...(opts.edited ? { edited: true } : {}),
    },
  };
}

/**
 * The `/implement-here` command body (the registration stays in `plan.ts`; the handler lives
 * HERE, next to the seam it composes — and so the `sendUserMessage` call sites stay out of the
 * installer file, whose registration prose the prose-review workbench edits through the
 * TypeScript source adapter's whole-file validation). Three arms: (1) an objective-node
 * planning session refuses — an implement-here would strand the node in `planning` (the claim
 * is only cleared by a node-linked save or a non-planning transition); gate untouched, nothing
 * injected. (2) Nothing to exit — the command's meaning is *exiting plan mode without saving*.
 * (3) Gate off → instruct the model. No inlined plan: the model authored the draft in its own
 * context (the review-path edited-bytes inlining is `implementHereResult`'s arm).
 */
export async function runImplementHereCommand(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
): Promise<void> {
  // The claim read rides the session seam (the one workflow-state owner) — the command has no
  // injected deps bag, so it opens the branch-backed session the production composition uses.
  if (openBranchWorkflowSession(pi, ctx).nodeClaim() !== null) {
    report(
      ctx,
      "implement-here",
      "warning",
      "this is an objective-node planning session — a node-linked plan must be saved " +
        "(the node advance and backlink depend on it). Use plan_review / /plan-save instead.",
    );
    return;
  }
  if (!gating.isActive()) {
    report(
      ctx,
      "implement-here",
      "warning",
      "not in plan mode — nothing to exit; just ask the model to implement.",
    );
    return;
  }
  implementHereExit(ctx, gating);
  const message = implementHereGuidance(ctx.cwd, {});
  if (ctx.isIdle()) {
    pi.sendUserMessage(message);
  } else {
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
}

/**
 * The defensive refusal arm (the feature's gate-safety invariant surfacing): an implement-here
 * verdict reached the execute path in an objective-node planning session — a node-linked plan
 * must save (the node advance and backlink depend on it). Loud, NON-terminating: nothing saved,
 * the gate untouched.
 */
function implementHereRefusedResult(): ToolResult {
  const error =
    "this is an objective-node planning session — a node-linked plan must be saved " +
    "(the node advance and backlink depend on it)";
  return {
    content: [
      {
        type: "text",
        text:
          `WARNING: implement-here refused — ${error}. Nothing was saved and the session stays ` +
          "read-only; approve the plan via plan_review or ask the user to run /plan-save.",
      },
    ],
    details: {
      ok: false,
      error,
      error_type: "implement_here_refused",
      status: "skipped",
      reason: "implement_here_refused",
    },
  };
}

// ------------------------------------------------------ the plannotator Direct-Edits apply

/**
 * The shared plannotator APPROVE mechanical-apply path (contracts.md §8.23): inspect an
 * APPROVED outcome's feedback for a `# Direct Edits` section and mechanically apply the
 * reviewer's diff to the exact bytes reviewed (`basePlan`), writing the patched bytes back to
 * the draft (reviewed bytes == artifact bytes == saved bytes). Consumed by the
 * `/plan-review-browser` door's decision routing — one apply path, byte-identical semantics
 * with the feature routing the in-tool plannotator arm rides:
 *
 * - only an `approved` outcome WITH feedback is inspected (anything else passes through
 *   verbatim);
 * - a clean extract + apply + write-back swaps `reviewedPlan` to the patched bytes, sets
 *   `edited: true`, and strips the applied section from the returned outcome's feedback (only
 *   the annotation remainder survives — the applied diff must never render as "apply these
 *   exact changes" guidance);
 * - a seen-but-unhonorable heading (or a failed apply / write-back) sets
 *   `directEditsFailed: true` with the plan left verbatim (the caller renders the loud warning;
 *   the diff stays in the surfaced feedback for a manual follow-up).
 */
export function applyPlannotatorDirectEdits(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  basePlan: string,
): {
  outcome: Extract<ReviewOutcome, { status: "completed" }>;
  reviewedPlan: string;
  edited: boolean;
  directEditsFailed: boolean;
} {
  if (!outcome.approved || outcome.feedback === undefined) {
    return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: false };
  }
  const section = extractDirectEdits(outcome.feedback);
  if (section !== null) {
    const session = openBranchWorkflowSession(pi, ctx);
    const applied = applyReviewerEdits(session, basePlan, { diff: section.diff });
    if (applied.status === "applied") {
      return {
        outcome: { ...outcome, feedback: section.remainder },
        reviewedPlan: applied.plan,
        edited: true,
        directEditsFailed: false,
      };
    }
    return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: true };
  }
  if (hasDirectEditsHeading(outcome.feedback)) {
    return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: true };
  }
  return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: false };
}

// -------------------------------------------------------------------- the reviewer adapters

/** Rebuild the door's completed outcome from carried facts (the mappers consume it). */
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
 * Translate a bridge outcome (`ReviewOutcome`) into the feature's `PlanReviewOutcome` —
 * provider vocabulary dies HERE: an approval whose feedback opens with `# Direct Edits`
 * becomes `approvedDirectEdits` (extractable diff + remainder) or `approvedEditsUnparseable`
 * (seen heading, unextractable body — the fail-open-but-loud arm); DENY passes the raw
 * feedback (diff included) through for the model-mediated `plan_draft` rewrite.
 */
function planOutcomeOf(outcome: ReviewOutcome): PlanReviewOutcome {
  switch (outcome.status) {
    case "completed": {
      const carried = {
        ...(outcome.reviewId !== "" ? { reviewId: outcome.reviewId } : {}),
      };
      if (!outcome.approved) {
        return {
          status: "denied",
          ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
          ...carried,
        };
      }
      if (outcome.feedback !== undefined) {
        const section = extractDirectEdits(outcome.feedback);
        if (section !== null) {
          return {
            status: "approvedDirectEdits",
            diff: section.diff,
            ...(section.remainder !== undefined ? { remainder: section.remainder } : {}),
            rawFeedback: outcome.feedback,
            ...carried,
          };
        }
        if (hasDirectEditsHeading(outcome.feedback)) {
          return { status: "approvedEditsUnparseable", rawFeedback: outcome.feedback, ...carried };
        }
        return { status: "approved", feedback: outcome.feedback, ...carried };
      }
      return { status: "approved", ...carried };
    }
    case "implement-here":
      // Unreachable from the bridge (its browser envelope returns only approve/deny) — kept
      // total; the feature's allowImplementHere routing owns the safety either way.
      return { status: "implementHere", reviewId: outcome.reviewId };
    case "unavailable":
      return { status: "unavailable", warning: outcome.warning };
    case "aborted":
      return { status: "aborted" };
    case "dismissed":
      return { status: "dismissed" };
  }
}

/** The plannotator reviewer adapter: the event-bus bridge judges the resolved bytes verbatim. */
function plannotatorPlanReviewer(bridge: PlanReviewBridge): PlanDraftReviewer {
  return {
    async review(plan, signal) {
      // Browser edits arrive as the Direct Edits diff ON the outcome (applied feature-side);
      // the reviewed bytes ride through unchanged.
      return { outcome: planOutcomeOf(await bridge.review(plan, signal)), plan, edited: false };
    },
  };
}

/**
 * The first-party reviewer adapter: the in-TUI editor review with the draft write-back bound to
 * the session seam (edits land BEFORE the verdict — a failed write-back is the `unavailable`
 * abort inside the core). The 4th verdict (implement-here, the no-save exit) is offered UNLESS
 * this is an objective-node planning session — a node-linked plan must save (the node advance
 * and backlink depend on it), so the claim suppresses it back to the 3-option select (the UX
 * layer; the feature's `allowImplementHere` refusal is the structural backstop).
 */
function firstPartyPlanReviewer(
  ctx: ExtensionContext,
  session: WorkflowSession,
  nodeClaimed: boolean,
): PlanDraftReviewer {
  return {
    async review(plan, signal) {
      const fp = await runFirstPartyReview({
        ui: ctx.ui,
        plan,
        writeDraft: (text) => {
          const written = revisePlanDraft({ plan: text }, session);
          return written.status === "revised" || written.status === "unchanged";
        },
        ...(signal !== undefined ? { signal } : {}),
        ...(nodeClaimed
          ? {}
          : {
              verdicts: { ...verdictsFor(PLAN_SUBJECT), implementHere: VERDICT_IMPLEMENT_HERE },
            }),
      });
      return { outcome: planOutcomeOf(fp.outcome), plan: fp.plan, edited: fp.edited };
    },
  };
}

// ------------------------------------------------------------------------- the execute paths

/** The plan arm's no-source soft skip (byte-stable redirect). */
function noPlanResult(): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          "no plan to review — write the working draft with plan_draft (or pass the plan " +
          "param), then call plan_review again.",
      },
    ],
    details: {
      ok: false,
      error: "no plan to review — write the draft with plan_draft first",
      error_type: "no_plan",
      status: "skipped",
      reason: "no_plan",
    },
  };
}

/**
 * The plan arm: headless skip → file-first resolution skip (`no_plan`) → the launch chooser
 * (plannotator + drafts-only eligibility, abort-outranks-everything ordering) → reviewer
 * construction (the plannotator bridge reviewer or the first-party editor reviewer) → the
 * feature `reviewPlanDraft` (`allowImplementHere` = no node claim) → result rendering.
 * (No `pi`/`gating` parameters: every effect rides `ctx` or the injected deps bag — the gate
 * is `deps.gate`, composed once in `plan.ts`.)
 */
export async function runPlanReviewV1(
  ctx: ExtensionContext,
  bridge: PlanReviewBridge,
  deps: PlanReviewV1Deps,
  plan: string | undefined,
  signal?: AbortSignal,
  wave?: WaveLaunch,
): Promise<ToolResult> {
  // 1. Headless → soft skip (fail-open; never wedges CI/supervisor runs on an interactive UI).
  if (!ctx.hasUI) return skipResult();
  // 2. File-first resolution: artifact → param, NEVER transcript — an approval
  //    auto-saves the reviewed bytes, and scraped conversation bytes must never be those.
  const src = resolvePlanSource(
    {
      draft: resumePlanDraft(deps.session),
      ...(plan !== undefined ? { explicit: plan } : {}),
    },
    "review",
  );
  if (src === null) return noPlanResult();
  const sig = signal ?? ctx.signal;
  // The claim read rides the injected session (the seam owns workflow-state reads — another
  // backing must never disagree with a raw branch read here).
  const nodeClaimed = deps.session.nodeClaim() !== null;
  // 3. Backend dispatch: plannotator-selected → the event-bus bridge; ANY other selection
  //    (perk-plan, tombell, unknown ids) → the first-party in-TUI editor review.
  let reviewer: PlanDraftReviewer;
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    // The launch chooser (contracts.md §8.23): every eligible round the human picks with/without
    // the streamed reviewer wave BEFORE anything launches. Eligibility is drafts-only — the wave
    // door reviews and stale-guards the validated artifact, so a param-tier source keeps the
    // plain path (silently: there is no forced mode to warn about; the `wave === undefined` arm
    // is defensive/test-only and behaves identically).
    if (wave?.present() && src.source === "plan-draft") {
      const choice = await chooseReviewLaunch(ctx.ui, "Plan", sig);
      if (choice.launch === "aborted") return reviewOutcomeResult({ status: "aborted" });
      if (choice.launch === "wave") {
        const guidance = await wave.plan(ctx, {
          draft: src.plan,
          ...(choice.custom !== undefined ? { custom: choice.custom } : {}),
        });
        // Abort outranks the opener result too: a turn interrupted during the awaited open must
        // never report a successful launch (the door's own bridge abort handling settles the
        // background tasks and clears the primed surfaces).
        if (sig?.aborted) return reviewOutcomeResult({ status: "aborted" });
        if (guidance !== null) return waveLaunchedResult(PLAN_SUBJECT, guidance);
        // null = the synchronous port-pick failure (already loudly reported inside the core) —
        // fall open to the plain blocking review in the same call: the review never wedges.
      }
    }
    reviewer = plannotatorPlanReviewer(bridge);
  } else {
    reviewer = firstPartyPlanReviewer(ctx, deps.session, nodeClaimed);
  }
  // 4. The feature review operation owns the resolve → review → abort-checkpoint → route
  //    discipline (incl. the Direct-Edits apply ladder and the D1a approval save).
  const result = await reviewPlanDraft(
    {
      session: deps.session,
      reviewer,
      backend: deps.backend,
      gate: deps.gate,
      generateTitle: deps.generateTitle,
      capturePlanningPointer: deps.capturePlanningPointer,
      ...(plan !== undefined ? { explicit: plan } : {}),
      allowImplementHere: !nodeClaimed,
    },
    sig,
  );
  return renderReviewResult(ctx, deps, result);
}

/** Render the feature's review result as the model-facing tool result (byte-stable texts). */
function renderReviewResult(
  ctx: ExtensionContext,
  deps: PlanReviewV1Deps,
  result: ReviewPlanDraftResult,
): ToolResult {
  switch (result.status) {
    case "noPlan":
      return noPlanResult();
    case "approvedSaved":
      return approvedSaveResult(
        completedOutcome(true, result),
        {
          status: "saved",
          result: deps.renderSave(result.save.result),
          gateExited: result.save.gateExited,
        },
        {
          paramMismatch: result.paramMismatch,
          edited: result.edited,
          directEditsFailed: result.directEditsFailed,
        },
      );
    case "approvedSaveFailed":
      return approvedSaveResult(
        completedOutcome(true, result),
        {
          status: "save-failed",
          result: deps.renderSave(result.save.result),
          gateExited: false,
        },
        {
          paramMismatch: result.paramMismatch,
          edited: result.edited,
          directEditsFailed: result.directEditsFailed,
        },
      );
    case "approvedNoPlan":
      // Defensively unreachable (the reviewed source is always non-blank) — the save-failed
      // shape with the no-source error, never a throw.
      return approvedSaveResult(
        completedOutcome(true, result),
        { status: "no-plan" },
        {
          paramMismatch: result.paramMismatch,
          edited: result.edited,
          directEditsFailed: result.directEditsFailed,
        },
      );
    case "implementHere": {
      // The feature exited the gate through the seam; surface the one info line the manual
      // `/implement-here` exit always reported (byte-identical notice, same scope/severity).
      if (result.gateExited) report(ctx, "implement-here", "info", IMPLEMENT_HERE_EXIT_NOTICE);
      return implementHereResult(
        { status: "implement-here", reviewId: result.reviewId },
        { gateExited: result.gateExited },
        { cwd: ctx.cwd, plan: result.plan, edited: result.edited },
      );
    }
    case "implementHereRefused":
      return implementHereRefusedResult();
    case "denied":
      return reviewOutcomeResult(completedOutcome(false, result));
    case "dismissed":
      return reviewOutcomeResult({ status: "dismissed" });
    case "aborted":
      return reviewOutcomeResult({ status: "aborted" });
    case "unavailable":
      return reviewOutcomeResult({ status: "unavailable", warning: result.warning });
  }
}

/**
 * The `plan_review` execute core — the STAGE DISPATCHER (exported for the offline tests). Arm
 * order: param decode → the objective arm (`executeObjectiveReview` — the rendered objective
 * draft is the review subject in BOTH objective-authoring stages) → the gist arm
 * (`runGistReviewV1` — the rendered gist draft) → the plan arm (`runPlanReviewV1`).
 */
export async function executePlanReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: PlanReviewBridge,
  deps: PlanReviewV1Deps,
  params: unknown,
  signal?: AbortSignal,
  wave?: WaveLaunch,
): Promise<ToolResult> {
  // Tool-boundary decode, in this tool's native fail-open vocabulary: a MISTYPED
  // `plan` (or non-object params) skip-shapes (`reason: "bad_input"`) without reviewing; an
  // ABSENT `plan` proceeds — the validated draft artifact is the preferred source.
  const p = paramsOf(params);
  const plan = p === null ? null : stringParam(p, "plan");
  if (plan === null) {
    return {
      content: [
        {
          type: "text",
          text: "plan_review takes { plan?: string } — omit it (the plan-draft artifact is preferred) or pass a string.",
        },
      ],
      details: {
        ok: false,
        error: "plan must be a string",
        error_type: "bad_input",
        status: "skipped",
        reason: "bad_input",
      },
    };
  }
  // An objective-authoring session (objective-author OR objective-save — both stages'
  // working draft is the objective draft, and neither carries `plan_draft`) → the objective
  // review arm: the rendered objective draft is the sole review source; a well-typed `plan`
  // param is ignored here — the plan-arm fallthrough could otherwise review/save an
  // unrelated plan param from an objective session. A gist-author session likewise routes to
  // the gist arm (the rendered gist draft).
  const launchedStage = rebuildWorkflowState(branchOf(ctx)).stage;
  if (launchedStage === OBJECTIVE_AUTHOR_STAGE || launchedStage === OBJECTIVE_SAVE_STAGE) {
    return executeObjectiveReview(pi, ctx, gating, bridge, signal ?? ctx.signal, wave);
  }
  if (launchedStage === GIST_AUTHOR_STAGE) {
    return runGistReviewV1(pi, ctx, gating, bridge, signal ?? ctx.signal);
  }
  return runPlanReviewV1(ctx, bridge, deps, plan, signal, wave);
}
