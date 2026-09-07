import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import {
  clearDraftReviewContext,
  type DraftReviewWaveState,
  primeDraftReviewContext,
} from "../../authoring/review/draftContext.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { RegistrationResult } from "../../session/draftReviewState.ts";
import { bindingSuffix } from "../../substrate/bindingDelivery.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { interceptConsoleError } from "../../substrate/consoleCapture.ts";
import { render } from "../../substrate/prompts.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { branchOf, rebuildWorkflowState } from "../../substrate/workflowState.ts";
import { type ReportTarget, report } from "../../surfaces/report.ts";
import {
  type DraftReviewAccess,
  draftReviewCompletionResult,
  draftReviewRefusalText,
  type PreparedDraftReview,
} from "./draftReviewActivation.ts";
import { planSaveDepsFor } from "./plan.ts";
import { completePlanReviewV1 } from "./planReview.ts";
import {
  type AnnotationState,
  clearAnnotationSurface,
  primeAnnotationSurface,
  resumeAnnotationDelivery,
} from "./providers/annotations.ts";
import type { PlannotatorRefusal, PlannotatorReviewOutcome } from "./providers/plannotator.ts";
import {
  plannotatorPresent,
  type RespondSink,
  type StartBrowserDeps,
  type StartedSurface,
  startPlannotatorPlanReview,
} from "./providers/plannotatorHandoff.ts";
import type { DraftReviewLaunchResult, ReviewOutcome } from "./review.ts";

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
  "The plannotator plan-review browser is unavailable — " +
  "degrade in-session: surface the draft-review wave's findings in your reply for the human. " +
  "Both door surfaces are cleared — `push_annotations` now refuses (`no_surface`) and the " +
  "draft-review context is gone. The human decides the next step: `plan_review` (the in-session " +
  "review door) or `/plan-save` (the manual failsafe).";

/**
 * One door open's shared liveness token: the degrade arm flips `degraded` and the decision task
 * refuses to route a later bridge decision through the save path — without it, a readiness
 * false-negative (endpoint/version drift while the browser is actually open) could let a
 * post-degrade approval auto-save and exit the gate AFTER the human already followed the
 * fallback path.
 */
export interface PlanReviewDoorSession {
  degraded: boolean;
}

/**
 * Keep readiness and decisions independent: a timeout suppresses late local callbacks, but
 * only an identity-bound verified invalidation grants fallback permission. A dispatch winner
 * cannot be rolled back. Companion resource cleanup leaves any early wave collectable.
 */
export async function observePlanReviewReadiness(
  pi: RespondSink,
  ctx: ReportTarget & Pick<ExtensionContext, "isIdle">,
  started: StartedSurface<PlannotatorReviewOutcome>,
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  session: PlanReviewDoorSession,
  isCurrent: () => boolean,
  degrade: () => RegistrationResult,
): Promise<void> {
  const surface = annotations.surface;
  const state = await started.readiness;
  if (!isCurrent() || session.degraded) return;
  if (state === "ready") {
    report(ctx, SCOPE, "info", `plannotator is up at ${started.url} — browser opening`);
    resumeAnnotationDelivery(annotations, surface, pi, ctx);
    return;
  }
  if (state === "aborted") return; // the turn was interrupted — no-op
  if (state === "bridge_settled") {
    const out = await started.bridgePromise;
    if (!isCurrent() || out.status !== "unavailable") return; // the decision task routes the settled outcome
  }
  fallbackPlanReview(
    pi,
    ctx,
    draftReview,
    annotations,
    session,
    isCurrent,
    degrade,
    `the plannotator plan-review server did not become ready at ${started.url} — the browser review is unavailable`,
  );
}

/** One local fallback attempt, whether readiness or transport failure arrives first. */
function fallbackPlanReview(
  pi: RespondSink,
  ctx: ReportTarget & Pick<ExtensionContext, "isIdle">,
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  session: PlanReviewDoorSession,
  isCurrent: () => boolean,
  degrade: () => RegistrationResult,
  detail: string,
): void {
  if (!isCurrent() || session.degraded) return;
  // Local suppression survives an unverified invalidation, but grants no fallback permission.
  session.degraded = true;
  clearAnnotationSurface(annotations);
  clearDraftReviewContext(draftReview);
  const invalidated = degrade();
  if (!invalidated.ok) {
    report(
      ctx,
      SCOPE,
      "error",
      draftReviewRefusalText({
        status: "refused",
        code: invalidated.reason,
        phase: "mutation",
        detail: invalidated.detail,
      }),
    );
    return;
  }
  report(ctx, SCOPE, "error", detail, { alsoLog: true });
  if (ctx.isIdle()) {
    pi.sendUserMessage(DEGRADE_NOTICE);
  } else {
    pi.sendUserMessage(DEGRADE_NOTICE, { deliverAs: "followUp" });
  }
}

/** Same subject completion as the tool; dispatch owns every effect and delivery attempt. */
export async function routePlanReviewDecision(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  out: ReviewOutcome,
  review: PreparedDraftReview,
): Promise<void> {
  if (out.status === "unavailable") {
    report(ctx, SCOPE, "error", out.warning, { alsoLog: true });
    return;
  }
  if (out.status !== "completed") return;
  const completion = await review.complete(out, {
    effect: out.approved ? "save" : "revision",
    carrier: { kind: "user" },
    execute: async (capability) => {
      const result = await completePlanReviewV1(
        ctx,
        planSaveDepsFor(pi, ctx, gating),
        review.snapshot.markdown,
        out,
        capability,
      );
      report(
        ctx,
        SCOPE,
        "info",
        result.details.saved === true
          ? "plan APPROVED in the browser — saved"
          : "plan browser decision prepared",
      );
      return result;
    },
  });
  const result = draftReviewCompletionResult(completion);
  report(
    ctx,
    SCOPE,
    completion.ok ? "info" : "error",
    completion.ok
      ? "plan browser decision dispatched; persisted delivery confirmation is pending"
      : result.content.map((block) => block.text).join("\n"),
  );
}

/**
 * The guidance-returning open core: start the plan-review browser, prime BOTH companion
 * surfaces the moment the port is picked (the URL is deterministic — see the header note),
 * observe readiness and the human decision in background tasks, and RETURN the composed
 * guidance string (template + the `command:plan-review-browser` binding suffix) — the caller
 * decides how to deliver it (the door wrapper injects it via `sendUserMessage`; `plan_review`'s
 * wave arm returns it as a non-terminating tool result, contracts.md §8.23). Returns `null` on
 * the synchronous port-pick failure arm — loudly reported here, then CALLER-handled: the door
 * wrapper simply injects nothing (the report already spoke), while `plan_review`'s wave arm —
 * the one fallback caller — falls open to the plain blocking review. While
 * plannotator sets up, its in-process `console.error` chatter re-routes through the TUI-safe
 * report() seam (the debounce restores once setup goes quiet, with the `finally` as a
 * backstop). `deps` is the injectable browser-open seam (tests drive a fake port
 * picker/probe/clock).
 */
export async function openPlanReviewSurface(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { draft: string; custom?: string },
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  reviews: DraftReviewAccess,
  deps: StartBrowserDeps = {},
): Promise<DraftReviewLaunchResult> {
  const prepared = reviews.prepare(ctx, opts.draft);
  if (!prepared.ok) return prepared.refusal;
  const review = prepared.value;
  if (review.snapshot.binding.subject !== "plan" || review.snapshot.markdown !== opts.draft) {
    review.dispose();
    return {
      status: "refused",
      code: "source-changed",
      phase: "open",
      detail: "plan review source changed before opening",
    };
  }
  let started: StartedSurface<PlannotatorReviewOutcome> | PlannotatorRefusal;
  try {
    started = await startPlannotatorPlanReview(
      pi.events,
      { plan: opts.draft, registration: review.registration, signal: review.signal },
      deps,
    );
  } catch (error) {
    review.dispose();
    const detail = error instanceof Error ? error.message : String(error);
    report(
      ctx,
      SCOPE,
      "error",
      `could not pick a free local port for the plannotator plan-review server: ${detail}`,
      { alsoLog: true },
    );
    return null;
  }

  if ("status" in started) {
    review.dispose();
    return started;
  }
  if (review.signal.aborted) {
    review.dispose();
    return {
      status: "refused",
      code: "invalid-state",
      phase: "open",
      detail: "review opening aborted",
    };
  }
  const surface = started;

  // Prime BOTH companion surfaces the moment the port is picked: push_annotations serves this
  // browser session in plan mode, and the draft-review wave reviews exactly the browsed bytes
  // (reviewed bytes == browsed bytes == wave bytes). Priming resets any pending wave — a new
  // browser session supersedes everything (the accepted double-open edge in the header).
  primeAnnotationSurface(annotations, { mode: "plan", url: started.url });
  primeDraftReviewContext(draftReview, {
    draftType: "plan",
    draft: opts.draft,
    ...(opts.custom !== undefined ? { custom: opts.custom } : {}),
  });

  // The shared liveness token: the observer's degrade arm flips it so the decision task never
  // routes a post-degrade decision through the save path (a readiness false-negative must not
  // let a late approval auto-save after the human followed the fallback).
  const session: PlanReviewDoorSession = { degraded: false };
  void observePlanReviewReadiness(
    pi,
    ctx,
    surface,
    draftReview,
    annotations,
    session,
    review.isCurrent,
    review.degrade,
  ).catch(() => {
    session.degraded = true;
    console.error("perk: browser readiness observation failed; no fallback permission established");
  });

  // The decision task: the wait is open-ended (exactly the model-called `plan_review` bridge
  // semantics — a turn abort settles `aborted` via the bridge's abort handling).
  void (async () => {
    const interceptor = interceptConsoleError((line) => report(ctx, SCOPE, "info", line), {
      // plannotator can pause up to ~4s between setup lines — keep the quiet window above that.
      quietMs: 6000,
    });
    try {
      const out = await surface.bridgePromise;
      if (!review.isCurrent()) return;
      if (out.status === "refused") {
        report(ctx, SCOPE, "error", draftReviewRefusalText(out));
        return;
      }
      if (out.status === "unavailable") {
        // The poll may be asleep or already ready. Handle the verified transport stop before
        // dispose aborts observation; the shared local latch prevents a second fallback.
        fallbackPlanReview(
          pi,
          ctx,
          draftReview,
          annotations,
          session,
          review.isCurrent,
          review.degrade,
          out.warning,
        );
        return;
      }
      if (session.degraded) {
        // The review already degraded (surfaces cleared, the fallback announced) — a late
        // decision is ignored LOUDLY, never routed into a stale/duplicate save.
        if (out.status === "completed") {
          report(
            ctx,
            SCOPE,
            "warning",
            "a browser decision arrived after local readiness suppression — ignored; " +
              "inspect retained review state before further saves",
          );
        }
        return;
      }
      await routePlanReviewDecision(pi, ctx, gating, out, review);
    } finally {
      // The browser session is over — drop both surfaces so a late push refuses (`no_surface`)
      // and a late wave start refuses (`no_draft_context`). Idempotent beside the degrade-arm
      // clears; an early decision mid-wave leaves a still-pending wave collectable.
      if (review.isCurrent()) {
        clearAnnotationSurface(annotations);
        clearDraftReviewContext(draftReview);
      }
      review.dispose();
      interceptor.restore();
    }
  })().catch(() => {
    console.error(
      "perk: browser decision reporting failed; inspect retained review state before further saves",
    );
  });

  report(
    ctx,
    SCOPE,
    "info",
    opts.custom !== undefined
      ? `working plan draft → plannotator browser review + draft reviewers (custom lane: ${opts.custom}) → APPROVE auto-saves / DENY returns feedback`
      : "working plan draft → plannotator browser review + draft reviewers → APPROVE auto-saves / DENY returns feedback",
  );
  return (
    planReviewBrowserGuidance({ ...(opts.custom !== undefined ? { custom: opts.custom } : {}) }) +
    bindingSuffix(ctx.cwd, `command:${SCOPE}`)
  );
}

/**
 * The door-facing open: the thin `sendUserMessage` wrapper over `openPlanReviewSurface` — the
 * command handler's delivery is the guidance injection; a `null` core return (port-pick
 * failure, already loudly reported) injects nothing.
 */
export async function openPlanReviewAndGuide(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { draft: string; custom?: string },
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  reviews: DraftReviewAccess,
  deps: StartBrowserDeps = {},
): Promise<void> {
  const guidance = await openPlanReviewSurface(
    pi,
    ctx,
    gating,
    opts,
    draftReview,
    annotations,
    reviews,
    deps,
  );
  if (typeof guidance === "string") pi.sendUserMessage(guidance);
  else if (guidance !== null) report(ctx, SCOPE, "error", draftReviewRefusalText(guidance));
}

// ------------------------------------------------------------------------ registration

/** Register the warm `/plan-review-browser` command (no tools — the companions are global). */
export function registerPlanReviewBrowser(
  pi: ExtensionAPI,
  gating: ToolGating,
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  reviews: DraftReviewAccess,
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
        annotations,
        reviews,
      );
    },
  });
}
