// The warm `/plan-review-browser` door: the summonable streaming draft review — from a
// plan-authoring session the human summons a plannotator PLAN-REVIEW browser on the working
// plan draft, a draft-reviewer wave streams phrase-anchored findings into that browser via
// `push_annotations`, and the browser decision routes through the existing seams: APPROVE →
// the shared Direct-Edits mechanical apply (`applyPlannotatorDirectEdits`, unchanged) →
// `approvalSave`; DENY → a model-mediated `plan_draft` revision round. Plannotator always, no
// provider dispatch (the surface-named command IS the selection — the `/pr-review-browser`
// precedent); only the plannotator PRESENCE probe gates it.
//
// ARTIFACT-FIRST, DRAFTS ONLY: the reviewed bytes are the validated `plan-draft.md` artifact —
// no param tier, no transcript tier (the review-surface law, tightened to drafts-only: an
// approval auto-saves the reviewed bytes). Stage-gated to the three registry stages whose
// STAGE_TOOLS carry `plan_draft` ({plan, save, objective-plan} — every session where the plan
// draft is the working draft); anything else refuses loudly.
//
// THE BACKGROUND OPEN: the plan server's URL is deterministic the moment the port is picked
// (the preset-PLANNOTATOR_PORT mechanism — see plannotatorHandoff.ts), so the handler starts
// `startPlannotatorPlanReview`, primes BOTH companion surfaces (the `push_annotations` plan-mode
// annotation surface + the draft-review wave context), injects the guidance IMMEDIATELY, and
// ends its turn. The readiness poll is observed in a background task (ready → info; never-ready
// → a loud degrade clearing both surfaces); the human DECISION is awaited in a second background
// task (open-ended — exactly the model-called `plan_review` bridge semantics; a turn abort
// settles `aborted` via the existing bridge abort handling) and routes the outcome.
//
// THE COMPANION TOOLS: the reviewer fan-out is the globally registered
// `start_draft_review_wave` / `collect_draft_review_wave` pair (door-primed inputs — the model
// picks only the angles), and the annotation delivery is the globally registered
// `push_annotations` PRIMED BY THIS DOOR in plan mode. The door registers no tools of its own.
//
// Accepted edges (the /pr-review-browser posture — noted, not engineered around):
//  - concurrent double-open stale-clear: a second /plan-review-browser re-primes both surfaces
//    (a new browser session supersedes everything), and the FIRST bridge's later settle clears
//    the second session's surfaces — rare and loud already (the fixed-port EADDRINUSE caveat).
//  - an early human decision mid-wave is authoritative — the save proceeds; the cleared surface
//    makes any late `push_annotations` refuse `no_surface`; a still-pending wave stays
//    collectable (the wave module's timeout is the orphan insurance).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { PLAN_DRAFT_ARTIFACT } from "../factories/planDraft.ts";
import {
  applyPlannotatorDirectEdits,
  approvedSaveResult,
  type ReviewOutcome,
} from "../factories/planReview.ts";
import { approvalSave } from "../factories/planSave.ts";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { interceptConsoleError } from "../substrate/consoleCapture.ts";
import { render } from "../substrate/prompts.ts";
import { readSessionArtifact } from "../substrate/sessionData.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { type ReportTarget, report } from "../surfaces/report.ts";
import { clearAnnotationSurface, primeAnnotationSurface } from "./annotationPush.ts";
import { clearDraftReviewContext, primeDraftReviewContext } from "./draftReviewWaveTools.ts";
import {
  plannotatorPresent,
  type RespondSink,
  type StartBrowserDeps,
  type StartedSurface,
  startPlannotatorPlanReview,
} from "./plannotatorHandoff.ts";

/** The door's report scope — also the `command:<id>` binding trigger id. */
const SCOPE = "plan-review-browser";

/**
 * The stage gate: the three registry stages whose STAGE_TOOLS carry `plan_draft` — every
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

// ------------------------------------------------------------------------ the background open

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

/**
 * Observe the readiness poll in the background (the plan flavor of `observeBrowserReadiness`;
 * the handler has already injected the guidance and ended): `ready` → an info note naming the
 * URL; `aborted` → no-op; `bridge_settled` → await the bridge — a completed/aborted outcome
 * returns silently (the decision task routes them) while `unavailable` falls through to the
 * degrade; `timeout` → degrade. Degrade = a loud error report PLUS the degrade notice injected
 * to the model (idle → immediate, streaming → followUp) AND both door surfaces cleared (the
 * annotation surface + the draft-review context — idempotent beside the decision task's
 * clears). Structural param slices keep it offline-testable; exported for the door tests.
 */
export async function observePlanReviewReadiness(
  pi: RespondSink,
  ctx: ReportTarget & Pick<ExtensionContext, "isIdle">,
  started: StartedSurface<ReviewOutcome>,
): Promise<void> {
  const state = await started.readiness;
  if (state === "ready") {
    report(ctx, SCOPE, "info", `plannotator is up at ${started.url} — browser opening`);
    return;
  }
  if (state === "aborted") return; // the turn was interrupted — no-op
  if (state === "bridge_settled") {
    const out = await started.bridgePromise;
    if (out.status !== "unavailable") return; // the decision task routes the settled outcome
  }
  report(
    ctx,
    SCOPE,
    "error",
    `the plannotator plan-review server did not become ready at ${started.url} — the browser ` +
      "review is unavailable",
    { alsoLog: true },
  );
  if (ctx.isIdle()) {
    pi.sendUserMessage(DEGRADE_NOTICE);
  } else {
    pi.sendUserMessage(DEGRADE_NOTICE, { deliverAs: "followUp" });
  }
  // Consistent with "surface findings in-session": a post-degrade push_annotations refuses
  // loudly (`no_surface`) and a post-degrade start_draft_review_wave refuses
  // `no_draft_context`. Idempotent beside the decision task's clears.
  clearAnnotationSurface();
  clearDraftReviewContext();
}

/**
 * Route the settled browser decision back into the session (the decision task's core; exported
 * for the door tests — pure over the injected pi/ctx/gating slices):
 *
 * - `aborted` → no-op (the turn was interrupted);
 * - `unavailable` → a loud error report (the readiness observer's degrade arm owns the model
 *   notice — never inject it twice);
 * - `completed && approved` → the shared Direct-Edits mechanical apply → `approvalSave` → the
 *   `approvedSaveResult` composition (its `terminate` is tool-path-only — ignored here); the
 *   text is reported (info on saved, error on save-failed with the `/plan-save` failsafe named)
 *   AND injected to the model so the session records the save + any reviewer implementation
 *   guidance;
 * - `completed && !approved` (DENY) → model-mediated: the feedback (Direct Edits diff included)
 *   is injected verbatim driving a `plan_draft` rewrite; the human re-runs /plan-review-browser
 *   (or the model calls plan_review) for the next round;
 * - `dismissed`/`implement-here` → defensively unreachable (the plannotator bridge never
 *   produces them) — no-op.
 */
export async function routePlanReviewDecision(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  out: ReviewOutcome,
  draft: string,
): Promise<void> {
  if (out.status === "unavailable") {
    report(ctx, SCOPE, "error", out.warning, { alsoLog: true });
    return;
  }
  if (out.status !== "completed") return; // aborted (+ the bridge-unreachable arms) — no-op

  const inject = (message: string): void => {
    if (ctx.isIdle()) {
      pi.sendUserMessage(message);
    } else {
      pi.sendUserMessage(message, { deliverAs: "followUp" });
    }
  };

  if (out.approved) {
    // APPROVE: the shared mechanical-apply path (byte-identical to plan_review's plannotator
    // arm), then the shared approval→save seam. The claim carrier (`objective_node_claim`)
    // recovery rides `approvalSave`→`savePlan` unchanged.
    const applied = applyPlannotatorDirectEdits(pi, ctx, out, draft);
    const save = await approvalSave(pi, ctx, gating, { reviewedPlan: applied.reviewedPlan });
    const result = approvedSaveResult(applied.outcome, save, {
      paramMismatch: false,
      edited: applied.edited,
      directEditsFailed: applied.directEditsFailed,
    });
    const text = result.content[0]?.text ?? "";
    if (save.status === "saved") {
      report(ctx, SCOPE, "info", "plan APPROVED in the browser — saved");
    } else {
      // save-failed + the defensively-unreachable no-plan arm: loud, gate left on, the
      // /plan-save manual failsafe named (the composed text carries it too).
      report(
        ctx,
        SCOPE,
        "error",
        "plan APPROVED in the browser but the auto-save FAILED — the session stays read-only; " +
          "run /plan-save (the manual failsafe) to retry",
        { alsoLog: true },
      );
    }
    inject(text);
    return;
  }

  // DENY: model-mediated revise round (contracts.md §8.23) — no auto re-open.
  report(ctx, SCOPE, "info", "plan DENIED in the browser — feedback routed for a revision round");
  const feedback = out.feedback ? `\n\nReviewer feedback:\n${out.feedback}` : "";
  inject(
    "The human DENIED the plan in the browser review — revise the working draft with " +
      "plan_draft per this feedback; the human re-runs /plan-review-browser (or you call " +
      `plan_review) for the next round.${feedback}`,
  );
}

/**
 * The background open: start the plan-review browser, prime BOTH companion surfaces the moment
 * the port is picked (the URL is deterministic — see the header note), observe readiness and
 * the human decision in background tasks, and inject the guidance immediately. While
 * plannotator sets up, its in-process `console.error` chatter re-routes through the TUI-safe
 * report() seam (the debounce restores once setup goes quiet, with the `finally` as a
 * backstop). `deps` is the injectable browser-open seam (tests drive a fake port
 * picker/probe/clock).
 */
export async function openPlanReviewAndGuide(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { draft: string; custom?: string },
  deps: StartBrowserDeps = {},
): Promise<void> {
  let started: StartedSurface<ReviewOutcome>;
  try {
    started = await startPlannotatorPlanReview(
      pi.events,
      { plan: opts.draft, signal: ctx.signal },
      deps,
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    report(
      ctx,
      SCOPE,
      "error",
      `could not pick a free local port for the plannotator plan-review server: ${detail}`,
      { alsoLog: true },
    );
    return;
  }

  // Prime BOTH companion surfaces the moment the port is picked: push_annotations serves this
  // browser session in plan mode, and the draft-review wave reviews exactly the browsed bytes
  // (reviewed bytes == browsed bytes == wave bytes). Priming resets any pending wave — a new
  // browser session supersedes everything (the accepted double-open edge in the header).
  primeAnnotationSurface({ mode: "plan", url: started.url });
  primeDraftReviewContext({
    draftType: "plan",
    draft: opts.draft,
    ...(opts.custom !== undefined ? { custom: opts.custom } : {}),
  });

  void observePlanReviewReadiness(pi, ctx, started);

  // The decision task: the wait is open-ended (exactly the model-called `plan_review` bridge
  // semantics — a turn abort settles `aborted` via the bridge's abort handling).
  void (async () => {
    const interceptor = interceptConsoleError((line) => report(ctx, SCOPE, "info", line), {
      // plannotator can pause up to ~4s between setup lines — keep the quiet window above that.
      quietMs: 6000,
    });
    try {
      const out = await started.bridgePromise;
      await routePlanReviewDecision(pi, ctx, gating, out, opts.draft);
    } finally {
      // The browser session is over — drop both surfaces so a late push refuses (`no_surface`)
      // and a late wave start refuses (`no_draft_context`). Idempotent beside the degrade-arm
      // clears; an early decision mid-wave leaves a still-pending wave collectable.
      clearAnnotationSurface();
      clearDraftReviewContext();
      interceptor.restore();
    }
  })();

  report(
    ctx,
    SCOPE,
    "info",
    opts.custom !== undefined
      ? `working plan draft → plannotator browser review + draft reviewers (custom lane: ${opts.custom}) → APPROVE auto-saves / DENY returns feedback`
      : "working plan draft → plannotator browser review + draft reviewers → APPROVE auto-saves / DENY returns feedback",
  );
  pi.sendUserMessage(
    planReviewBrowserGuidance({ ...(opts.custom !== undefined ? { custom: opts.custom } : {}) }) +
      bindingSuffix(ctx.cwd, `command:${SCOPE}`),
  );
}

// ------------------------------------------------------------------------ registration

/** Register the warm `/plan-review-browser` command (no tools — the companions are global). */
export function registerPlanReviewBrowser(pi: ExtensionAPI, gating: ToolGating): void {
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
      const artifact = readSessionArtifact(ctx, PLAN_DRAFT_ARTIFACT);
      if (artifact === null || artifact.content.trim().length === 0) {
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
      await openPlanReviewAndGuide(pi, ctx, gating, {
        draft: artifact.content,
        ...(custom.length > 0 ? { custom } : {}),
      });
    },
  });
}
