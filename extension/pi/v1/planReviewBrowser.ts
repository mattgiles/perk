// The warm `/plan-review-browser` door: the summonable streaming draft review — from a
// plan-authoring session the human summons a plannotator PLAN-REVIEW browser on the working
// plan draft, a draft-reviewer wave streams phrase-anchored findings into that browser via
// `push_annotations`, and the browser decision routes through the shared seams: APPROVE → the
// decision ladder → the shared plan completion (`completePlanReviewV1`: the Direct-Edits
// mechanical apply, `planApprovalSave`); DENY → a model-mediated `plan_draft` revision round.
// Plannotator always, no provider dispatch (the surface-named command IS the selection — the
// `/pr-review-browser` precedent); only the plannotator PRESENCE probe gates it.
//
// ARTIFACT-FIRST, DRAFTS ONLY: the reviewed bytes are the validated `plan-draft.md` artifact —
// no param tier, no transcript tier (the review-surface law, tightened to drafts-only: an
// approval auto-saves the reviewed bytes). Stage-gated to the three registry stages whose
// stage diet carries `plan_draft` ({plan, save, objective-plan} — every session where the plan
// draft is the working draft); anything else refuses loudly.
//
// THE GUARDS (`draftReview.ts`, contracts.md §8.23): the door opens the activation's
// current-review slot at entry (superseding any other open review — blocking or browser) and
// runs every completed browser decision through the decision ladder: a superseded review's
// decision is ignored loudly; an APPROVE over a moved draft, a moved save destination, or a
// latched unconfirmed save saves nothing and tells the model why; a DENY over a moved draft
// proceeds with a one-line note. Nothing is persisted — a browser decision does not survive a
// Pi restart (the human re-runs the door).
//
// THE BROWSER OPERATION (`browserOperation.ts`, contracts.md §8.23): the door opens through the
// activation's browser-operation owner, which owns the start (port pick + env preset), the
// priming of BOTH companion surfaces (the `push_annotations` plan-mode annotation surface + the
// draft-review wave context), readiness and decision observation, console interception and
// cleanup; the door injects its guidance immediately and supplies only its subject hooks — the
// degrade notice, `review.isCurrent` as the applicability fence, and the decision router.
// Opening the door again REPLACES the earlier browser review (its tab is marked detached, its
// wait aborted, its in-flight decision drained); a turn abort or a session reload/replacement
// detaches it the same way. The slot keeps decision authority: a blocking `plan_review` or
// `/implement-here` supersession leaves the tab open but its verdict is ignored loudly by the
// ladder. An early human decision mid-wave is authoritative and forgoes the reviewer findings —
// the save proceeds, a still-pending wave stays collectable (the wave module's timeout is the
// orphan insurance); the code-owned `perk:wave` marker plus the door-open notice make that
// early decision an informed one.
//
// THE COMPANION TOOLS: the reviewer fan-out is the globally registered
// `start_draft_review_wave` / `collect_draft_review_wave` pair (door-primed inputs — the model
// picks only the angles), and the annotation delivery is the globally registered
// `push_annotations` PRIMED BY THIS DOOR in plan mode. The door registers no tools of its own.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import {
  clearDraftReviewContext,
  DRAFT_REVIEW_DOOR_PRIMES,
  type DraftReviewWaveState,
  primeDraftReviewContext,
} from "../../authoring/review/draftContext.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { bindingSuffix } from "../../substrate/bindingDelivery.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { render } from "../../substrate/prompts.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { branchOf, rebuildWorkflowState } from "../../substrate/workflowState.ts";
import { report } from "../../surfaces/report.ts";
import {
  type BrowserOperationOwner,
  type BrowserOperationSpec,
  settleReviewOutcome,
} from "./browserOperation.ts";
import {
  checkDraftReviewDecision,
  type DraftReviewSlot,
  injectDraftReviewResult,
  type OpenDraftReview,
  SUPERSEDED_DECISION_WARNING,
  withDraftChangedNote,
} from "./draftReview.ts";
import { planSaveDepsFor, planSaveNeedsRepair } from "./plan.ts";
import { completePlanReviewV1, planGuardResult } from "./planReview.ts";
import { plannotatorPresent, startPlannotatorPlanReview } from "./providers/plannotatorHandoff.ts";
import { WAVE_ARRIVAL_NOTICE } from "./providers/waveStatus.ts";
import {
  type DoorOpenResult,
  type ReviewOutcome,
  type ToolResult,
  untrustedReviewFeedback,
} from "./review.ts";

/** The door's report scope — also the `command:<id>` binding trigger id. */
const SCOPE = "plan-review-browser";

/**
 * The stage gate: the three registry stages whose stage diet carries `plan_draft` — every
 * session where the plan draft is the working draft. Other/absent stage → loud refusal.
 */
const DRAFT_STAGES: ReadonlySet<string> = new Set(["plan", "save", "objective-plan"]);

// ------------------------------------------------------------------------ guidance

/**
 * The seed guidance the door injects (the perk-plan-review-browser skill pointer rides the
 * skill-binding suffix — command:plan-review-browser — not hardcoded here). Pure + exported for
 * offline tests. One arm (no foreign/active split): `custom` renders the primed custom-lane
 * note when the human supplied a custom-angle definition.
 */
export function planReviewBrowserGuidance(opts: { custom?: string }): string {
  return render("stages/plan-review-browser.md", { custom: opts.custom ?? "" });
}

// ------------------------------------------------------------------------ the browser operation

/**
 * The degrade notice injected when the browser never comes up — the model surfaces the wave's
 * findings in-session for the human, and the human falls back to `plan_review`/`/plan-save`.
 */
const DEGRADE_NOTICE =
  "The plannotator plan-review browser is unavailable (the review server never became ready) — " +
  "degrade in-session: surface the draft-review wave's findings in your reply for the human. " +
  "Both door surfaces are cleared — `push_annotations` now refuses (`no_surface`) and the " +
  "draft-review context is gone. The human decides the next step: `plan_review` (the in-session " +
  "review door) or `/plan-save` (the manual failsafe).";

/** The model-facing DENY revision result (the feedback delimited as untrusted DATA). */
function planRevisionResult(out: Extract<ReviewOutcome, { status: "completed" }>): ToolResult {
  const feedback = out.feedback
    ? `\n\nReviewer feedback:\n${untrustedReviewFeedback(out.feedback)}`
    : "";
  return {
    content: [
      {
        type: "text",
        text:
          "The human DENIED the plan in the browser review — revise the working draft with " +
          "plan_draft per this feedback; the human re-runs /plan-review-browser (or you call " +
          `plan_review) for the next round.${feedback}`,
      },
    ],
    details: { ok: true, status: "denied", subject: "plan" },
  };
}

/**
 * Route a DECIDED browser verdict back into the session (the owner's `onDecision`; exported for
 * the door tests — pure over the injected pi/ctx/gating/slot slices). The bridge's
 * `unavailable`/`aborted` arms never reach here (the owner degrades/detaches them):
 *
 * - the decision ladder (`checkDraftReviewDecision`, effect `save` on APPROVE, `revision` on
 *   DENY): `superseded` → one TUI warning, nothing injected, nothing saved;
 *   `save-unconfirmed` / `stale-approval` / `destination-changed` → an error report AND the
 *   matching fixed model text injected (nothing saved, gate untouched);
 * - `proceed` on APPROVE → the shared plan completion (Direct-Edits mechanical apply →
 *   `planApprovalSave` → the latch record) with its text injected; the TUI line is `info` on a
 *   clean save, `warning` carrying the single-line save message when the saved plan needs a
 *   repair (`planSaveNeedsRepair`: a failed node advance, a held session link or claim clear),
 *   `error` on a failed save;
 * - `proceed` on DENY → the model-mediated revision round (the feedback delimited as untrusted
 *   DATA), prefixed with `DRAFT_CHANGED_NOTE` when the draft moved.
 */
export async function routePlanReviewDecision(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  slot: DraftReviewSlot,
  out: Extract<ReviewOutcome, { status: "completed" }>,
  review: OpenDraftReview,
): Promise<void> {
  const check = checkDraftReviewDecision(slot, ctx, review, out.approved ? "save" : "revision");
  if (check.kind === "superseded") {
    report(ctx, SCOPE, "warning", SUPERSEDED_DECISION_WARNING);
    return;
  }
  if (check.kind !== "proceed") {
    const result = planGuardResult(check, review, out.feedback);
    report(ctx, SCOPE, "error", result.content[0]?.text.split("\n")[0] ?? check.kind, {
      alsoLog: true,
    });
    injectDraftReviewResult(pi, ctx, result);
    return;
  }

  if (out.approved) {
    // APPROVE: the shared completion (byte-identical to plan_review's plannotator arm) — the
    // claim carrier (`objective_node_claim`) recovery rides `planApprovalSave`→`savePlan`.
    const completion = await completePlanReviewV1(
      ctx,
      slot,
      planSaveDepsFor(pi, ctx, gating),
      review.markdown,
      out,
    );
    if (completion.saved !== null) {
      // The plan saved either way; a repair-needed save names its repair (the single-line
      // save message carries the retry), like `/plan-save`'s severity rule.
      if (planSaveNeedsRepair(completion.saved.details)) {
        report(
          ctx,
          SCOPE,
          "warning",
          `plan APPROVED in the browser — saved; ${completion.saved.message}`,
        );
      } else {
        report(ctx, SCOPE, "info", "plan APPROVED in the browser — saved");
      }
    } else {
      // save-failed (+ the defensively-unreachable no-plan arm): loud, gate left on; the
      // composed text names the check-the-backend step and the /plan-save deliberate retry.
      report(
        ctx,
        SCOPE,
        "error",
        "plan APPROVED in the browser but the auto-save did not confirm — the session stays " +
          "read-only and automatic saves are paused; check the backend for this run id, then " +
          "run /plan-save (the deliberate retry)",
        { alsoLog: true },
      );
    }
    injectDraftReviewResult(pi, ctx, withDraftChangedNote(completion.result, check.draftChanged));
    return;
  }

  // DENY: model-mediated revise round (contracts.md §8.23) — no auto re-open. The feedback is
  // passed through verbatim (Direct Edits diff included) but DELIMITED as untrusted DATA.
  report(ctx, SCOPE, "info", "plan DENIED in the browser — feedback routed for a revision round");
  injectDraftReviewResult(
    pi,
    ctx,
    withDraftChangedNote(planRevisionResult(out), check.draftChanged),
  );
}

/**
 * The guidance-returning open core: open the current-review slot (a refusal is reported and
 * returns `null` — nothing launched), open the plan-review browser through the activation's
 * browser-operation owner (which retires any earlier browser review first, starts the handoff,
 * primes BOTH companion surfaces and observes readiness + the human decision in the background),
 * and RETURN the composed guidance string (template + the `command:plan-review-browser` binding
 * suffix) — the caller decides how to deliver it (the door wrapper injects it via
 * `sendUserMessage`; `plan_review`'s wave arm returns it as a non-terminating tool result,
 * contracts.md §8.23) as `launched`. Nothing launched is CALLER-handled: `unlaunched` (a slot
 * refusal or the port-pick failure, already reported loudly) → the door wrapper injects nothing,
 * while `plan_review`'s wave arm — the one fallback caller — falls open to the plain blocking
 * review; `retired` (a newer open took over before this one started) → nothing injected and
 * never a fallback.
 */
export async function openPlanReviewSurface(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { draft: string; custom?: string },
  draftReview: DraftReviewWaveState,
  slot: DraftReviewSlot,
  owner: BrowserOperationOwner,
): Promise<DoorOpenResult> {
  // The slot open FIRST: no browser launches for a review that could never be routed (no run
  // identity, the wrong subject, an unverifiable destination).
  const opened = slot.open(ctx, {
    subject: "plan",
    source: "artifact",
    raw: opts.draft,
    markdown: opts.draft,
  });
  if (!opened.ok) {
    report(ctx, SCOPE, "error", `cannot open the browser review: ${opened.detail}`, {
      alsoLog: true,
    });
    return { kind: "unlaunched" };
  }
  const review = opened.review;

  const spec: BrowserOperationSpec<ReviewOutcome> = {
    scope: SCOPE,
    start: (launch) =>
      startPlannotatorPlanReview(
        pi.events,
        { plan: opts.draft, signal: launch.signal, activity: launch.activity },
        launch.deps,
      ),
    mode: "plan",
    primes: DRAFT_REVIEW_DOOR_PRIMES,
    // The draft-review wave reviews exactly the browsed bytes (reviewed bytes == browsed bytes
    // == wave bytes); priming resets any pending wave.
    companion: {
      prime: () =>
        primeDraftReviewContext(draftReview, {
          draftType: "plan",
          draft: opts.draft,
          ...(opts.custom !== undefined ? { custom: opts.custom } : {}),
        }),
      clear: () => clearDraftReviewContext(draftReview),
    },
    applicable: review.isCurrent,
    degradeNotice: DEGRADE_NOTICE,
    settle: settleReviewOutcome,
    onDecision: async (out) => {
      // `settleReviewOutcome` routes only `completed` here; the narrowing keeps the router typed.
      if (out.status === "completed") {
        await routePlanReviewDecision(pi, ctx, gating, slot, out, review);
      }
    },
  };
  const launched = await owner.open(ctx, spec);
  if (launched.kind === "failed") return { kind: "unlaunched" };
  if (launched.kind === "retired") return { kind: "retired" };

  report(
    ctx,
    SCOPE,
    "info",
    (opts.custom !== undefined
      ? `working plan draft → plannotator browser review + draft reviewers (custom lane: ${opts.custom}) → APPROVE auto-saves / DENY returns feedback`
      : "working plan draft → plannotator browser review + draft reviewers → APPROVE auto-saves / DENY returns feedback") +
      WAVE_ARRIVAL_NOTICE,
  );
  return {
    kind: "launched",
    guidance:
      planReviewBrowserGuidance({ ...(opts.custom !== undefined ? { custom: opts.custom } : {}) }) +
      bindingSuffix(ctx.cwd, `command:${SCOPE}`),
  };
}

/**
 * The door-facing open: the thin `sendUserMessage` wrapper over `openPlanReviewSurface` — the
 * command handler's delivery is the guidance injection; an unlaunched core result (slot refusal
 * or port-pick failure, already loudly reported) or a retired one (a newer open took over)
 * injects nothing.
 */
export async function openPlanReviewAndGuide(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { draft: string; custom?: string },
  draftReview: DraftReviewWaveState,
  slot: DraftReviewSlot,
  owner: BrowserOperationOwner,
): Promise<void> {
  const opened = await openPlanReviewSurface(pi, ctx, gating, opts, draftReview, slot, owner);
  if (opened.kind === "launched") pi.sendUserMessage(opened.guidance);
}

// ------------------------------------------------------------------------ registration

/**
 * Register the warm `/plan-review-browser` command (no tools — the companions are global).
 * `owner` is the activation's browser-operation owner (it carries the port selection).
 */
export function registerPlanReviewBrowser(
  pi: ExtensionAPI,
  gating: ToolGating,
  draftReview: DraftReviewWaveState,
  slot: DraftReviewSlot,
  owner: BrowserOperationOwner,
): void {
  registerPerkCommand(pi, SCOPE, {
    description:
      "Review the working plan draft human-in-the-loop in the plannotator browser UI: draft " +
      "reviewers stream findings into the browser; APPROVE auto-saves, DENY returns feedback " +
      "for revision. Any argument text defines an extra custom review angle.",
    handler: async (args, ctx: ExtensionContext) => {
      // Entry gates, in order — nothing executed on refusal, each a loud error.
      if (!ctx.hasUI) {
        report(
          ctx,
          SCOPE,
          "error",
          "/plan-review-browser requires an interactive session — the plannotator browser " +
            "surface and the human are constitutive",
        );
        return;
      }
      if (!plannotatorPresent(pi)) {
        report(
          ctx,
          SCOPE,
          "error",
          "the plannotator extension is not loaded (its /plannotator-review command was not " +
            "found) — select the plannotator plan provider (`[providers] plan = " +
            '"plannotator-plan"`), run `perk init`, then restart pi',
        );
        return;
      }
      const stage = rebuildWorkflowState(branchOf(ctx)).stage;
      if (stage === undefined || !DRAFT_STAGES.has(stage)) {
        report(
          ctx,
          SCOPE,
          "error",
          "/plan-review-browser only runs inside a plan-authoring session (stage plan, save, " +
            "or objective-plan) — the door reviews the working plan draft",
        );
        return;
      }
      // The draft resolve, artifact ONLY: no param tier, no transcript tier (the review-surface
      // law tightened to drafts-only — an approval auto-saves the reviewed bytes).
      const artifact = openBranchWorkflowSession(pi, ctx).readArtifact(PLAN_DRAFT_ARTIFACT);
      if (artifact.status !== "found" || artifact.content.trim().length === 0) {
        report(
          ctx,
          SCOPE,
          "error",
          "no working plan draft — write it with plan_draft, then re-run /plan-review-browser",
        );
        return;
      }
      // The entire trimmed arg string is the optional custom-angle definition (no parse-failure
      // arm — any text is a valid lens definition).
      const custom = (args ?? "").trim();
      await openPlanReviewAndGuide(
        pi,
        ctx,
        gating,
        {
          draft: artifact.content,
          ...(custom.length > 0 ? { custom } : {}),
        },
        draftReview,
        slot,
        owner,
      );
    },
  });
}
