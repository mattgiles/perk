import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  decodeObjectiveDraft,
  OBJECTIVE_DRAFT_ARTIFACT,
  renderObjectiveDraft,
} from "../../authoring/objective/draft.ts";
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
import { completeObjectiveReviewV1 } from "./objectiveReview.ts";
import {
  type AnnotationState,
  clearAnnotationSurface,
  primeAnnotationSurface,
  resumeAnnotationDelivery,
} from "./providers/annotations.ts";
import type { PlannotatorRefusal, PlannotatorReviewOutcome } from "./providers/plannotator.ts";
import { hasDirectEditsHeading } from "./providers/plannotator.ts";
import {
  plannotatorPresent,
  type RespondSink,
  type StartBrowserDeps,
  type StartedSurface,
  startPlannotatorPlanReview,
} from "./providers/plannotatorHandoff.ts";
import type { DraftReviewLaunchResult, ReviewOutcome } from "./review.ts";

/** The door's report scope — also the `command:<id>` binding trigger id. */
const SCOPE = "objective-review-browser";

/**
 * The stage gate: the two registry stages whose STAGE_TOOLS carry `objective_draft` — every
 * session where the objective draft is the working draft. Other/absent stage → loud refusal.
 */
const DRAFT_STAGES: ReadonlySet<string> = new Set(["objective-author", "objective-save"]);

// ------------------------------------------------------------------------ guidance

/**
 * The seed guidance the door injects (the perk-objective-review-browser skill pointer rides
 * the skill-binding suffix — command:objective-review-browser — not hardcoded here). Pure +
 * exported for offline tests. One arm (no foreign/active split): `custom` renders the primed
 * custom-lane note when the human supplied a custom-angle definition.
 */
export function objectiveReviewBrowserGuidance(opts: { custom?: string }): string {
  return render("stages/objective-review-browser.md", { custom: opts.custom ?? "" });
}

// ------------------------------------------------------------------------ the background open

/**
 * The degrade notice injected when the browser never comes up — the model surfaces the wave's
 * findings in-session for the human, and the human falls back to `plan_review` (the in-session
 * review door) or `/objective-save` (the manual failsafe).
 */
const DEGRADE_NOTICE =
  "The plannotator plan-review browser is unavailable (the review server never became ready) — " +
  "degrade in-session: surface the draft-review wave's findings in your reply for the human. " +
  "Both door surfaces are cleared — `push_annotations` now refuses (`no_surface`) and the " +
  "draft-review context is gone. The human decides the next step: `plan_review` (the in-session " +
  "review door) or `/objective-save` (the manual failsafe).";

/**
 * One door open's shared liveness token: the degrade arm flips `degraded` and the decision task
 * refuses to route a later bridge decision through the save path — without it, a readiness
 * false-negative (endpoint/version drift while the browser is actually open) could let a
 * post-degrade approval auto-save and exit the gate AFTER the human already followed the
 * fallback path. A local twin of the plan door's token on purpose — importing
 * `PlanReviewDoorSession` here would mislead.
 */
export interface ObjectiveReviewDoorSession {
  degraded: boolean;
}

/**
 * Keep readiness and decisions independent: a timeout suppresses late local callbacks, but
 * only an identity-bound verified invalidation grants fallback permission. A dispatch winner
 * cannot be rolled back. Companion resource cleanup leaves any early wave collectable.
 */
export async function observeObjectiveReviewReadiness(
  pi: RespondSink,
  ctx: ReportTarget & Pick<ExtensionContext, "isIdle">,
  started: StartedSurface<PlannotatorReviewOutcome>,
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  session: ObjectiveReviewDoorSession,
  isCurrent: () => boolean,
  degrade: () => RegistrationResult,
): Promise<void> {
  const surface = annotations.surface;
  const state = await started.readiness;
  if (!isCurrent()) return;
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
}

/** Same subject completion as the tool; dispatch owns every effect and delivery attempt. */
export async function routeObjectiveReviewDecision(
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
    effect:
      out.approved && !(out.feedback !== undefined && hasDirectEditsHeading(out.feedback))
        ? "save"
        : "revision",
    carrier: { kind: "user" },
    execute: async (capability) => {
      const result = await completeObjectiveReviewV1(pi, ctx, gating, out, capability);
      report(
        ctx,
        SCOPE,
        "info",
        result.details.saved === true
          ? "objective APPROVED in the browser — saved"
          : "objective browser decision prepared",
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
      ? "objective browser decision dispatched; persisted delivery confirmation is pending"
      : result.content.map((block) => block.text).join("\n"),
  );
}

/**
 * The guidance-returning open core: start the plan-review browser on the RENDERED objective
 * draft, prime BOTH companion surfaces the moment the port is picked (the URL is deterministic
 * — see the header note), observe readiness and the human decision in background tasks, and
 * RETURN the composed guidance string (template + the `command:objective-review-browser`
 * binding suffix) — the caller decides how to deliver it (the door wrapper injects it via
 * `sendUserMessage`; `plan_review`'s wave arm returns it as a non-terminating tool result,
 * contracts.md §8.23). Returns `null` on the synchronous port-pick failure arm — loudly
 * reported here, then CALLER-handled: the door wrapper simply injects nothing (the report
 * already spoke), while `plan_review`'s wave arm — the one fallback caller — falls open to the
 * plain blocking review. While plannotator sets up, its in-process `console.error`
 * chatter re-routes through the TUI-safe report() seam (the debounce restores once setup goes
 * quiet, with the `finally` as a backstop). `deps` is the injectable browser-open seam (tests
 * drive a fake port picker/probe/clock). `rendered` is the reviewed markdown; `artifactRaw` is
 * the raw structured `objective-draft.json` bytes captured at open — the stale guard's
 * baseline.
 */
export async function openObjectiveReviewSurface(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { rendered: string; artifactRaw: string; custom?: string },
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  reviews: DraftReviewAccess,
  deps: StartBrowserDeps = {},
): Promise<DraftReviewLaunchResult> {
  const prepared = reviews.prepare(ctx);
  if (!prepared.ok) return prepared.refusal;
  const review = prepared.value;
  if (
    review.snapshot.binding.subject !== "objective" ||
    review.snapshot.markdown !== opts.rendered ||
    review.snapshot.raw !== opts.artifactRaw
  ) {
    review.dispose();
    return {
      status: "refused",
      code: "source-changed",
      phase: "open",
      detail: "objective review source changed before opening",
    };
  }
  let started: StartedSurface<PlannotatorReviewOutcome> | PlannotatorRefusal;
  try {
    // The plan-review bridge sends arbitrary string bytes as `planContent` — the rendered
    // objective rides it unchanged (no plan-specific validation).
    started = await startPlannotatorPlanReview(
      pi.events,
      { plan: opts.rendered, registration: review.registration, signal: review.signal },
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
  // browser session in plan mode (phrase-anchored — the rendered-objective findings reuse it
  // as-is), and the draft-review wave reviews exactly the browsed bytes (reviewed bytes ==
  // browsed bytes == wave bytes — all the RENDERED markdown). Priming resets any pending wave —
  // a new browser session supersedes everything (the accepted double-open edge in the header).
  primeAnnotationSurface(annotations, { mode: "plan", url: started.url });
  primeDraftReviewContext(draftReview, {
    draftType: "objective",
    draft: opts.rendered,
    ...(opts.custom !== undefined ? { custom: opts.custom } : {}),
  });

  // The shared liveness token: the observer's degrade arm flips it so the decision task never
  // routes a post-degrade decision through the save path (a readiness false-negative must not
  // let a late approval auto-save after the human followed the fallback).
  const session: ObjectiveReviewDoorSession = { degraded: false };
  void observeObjectiveReviewReadiness(
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
      await routeObjectiveReviewDecision(pi, ctx, gating, out, review);
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
      ? `working objective draft → plannotator browser review + draft reviewers (custom lane: ${opts.custom}) → APPROVE auto-saves / DENY returns feedback`
      : "working objective draft → plannotator browser review + draft reviewers → APPROVE auto-saves / DENY returns feedback",
  );
  return (
    objectiveReviewBrowserGuidance({
      ...(opts.custom !== undefined ? { custom: opts.custom } : {}),
    }) + bindingSuffix(ctx.cwd, `command:${SCOPE}`)
  );
}

/**
 * The door-facing open: the thin `sendUserMessage` wrapper over `openObjectiveReviewSurface` —
 * the command handler's delivery is the guidance injection; a `null` core return (port-pick
 * failure, already loudly reported) injects nothing.
 */
export async function openObjectiveReviewAndGuide(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { rendered: string; artifactRaw: string; custom?: string },
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  reviews: DraftReviewAccess,
  deps: StartBrowserDeps = {},
): Promise<void> {
  const guidance = await openObjectiveReviewSurface(
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

/** Register the warm `/objective-review-browser` command (no tools — the companions are global). */
export function registerObjectiveReviewBrowser(
  pi: ExtensionAPI,
  gating: ToolGating,
  draftReview: DraftReviewWaveState,
  annotations: AnnotationState,
  reviews: DraftReviewAccess,
): void {
  registerPerkCommand(pi, SCOPE, {
    description:
      "Review the working objective draft (prose + roadmap) human-in-the-loop in the " +
      "plannotator browser UI: draft reviewers stream findings into the browser; APPROVE " +
      "auto-saves the objective, DENY returns feedback for revision. Any argument text defines " +
      "an extra custom review angle.",
    handler: async (args, ctx: ExtensionContext) => {
      // Entry gates, in order — nothing executed on refusal, each a loud error.
      if (!ctx.hasUI) {
        report(
          ctx,
          SCOPE,
          "error",
          "/objective-review-browser requires an interactive session — the plannotator browser " +
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
          "/objective-review-browser only runs inside an objective-authoring session (stage " +
            "objective-author or objective-save) — the door reviews the working objective draft",
        );
        return;
      }
      // The draft resolve, artifact ONLY: no param tier, no transcript tier (the review-surface
      // law tightened to drafts-only — an approval auto-saves the reviewed bytes). ONE
      // seam-validated read (digest-checked): its bytes are BOTH the decode input and the stale
      // guard's baseline (the save-authoritative surface), so there is no check-to-open window
      // between what was validated and what the approval compares against.
      const artifact = openBranchWorkflowSession(pi, ctx).readArtifact(OBJECTIVE_DRAFT_ARTIFACT);
      if (artifact.status === "invalid") {
        // Seam-level corruption (pointer-without-file, digest mismatch) is NOT absence — the
        // classified problem + rewrite guidance surface here, mirroring the decode arm below.
        report(
          ctx,
          SCOPE,
          "error",
          `the working objective draft is invalid: ${artifact.problem} — rewrite it with ` +
            "objective_draft, then re-run /objective-review-browser",
        );
        return;
      }
      if (artifact.status !== "found" || artifact.content.trim().length === 0) {
        report(
          ctx,
          SCOPE,
          "error",
          "no working objective draft — write it with objective_draft (prose + the structured " +
            "roadmap), then re-run /objective-review-browser",
        );
        return;
      }
      // Decode the SAME bytes (schema-checked), classified: `refused` carries the problem.
      const resumed = decodeObjectiveDraft(artifact.content);
      if (resumed.kind === "refused") {
        report(
          ctx,
          SCOPE,
          "error",
          `the working objective draft is invalid: ${resumed.problem} — rewrite it with ` +
            "objective_draft, then re-run /objective-review-browser",
        );
        return;
      }
      const rendered = renderObjectiveDraft(resumed.draft);
      // The entire trimmed arg string is the optional custom-angle definition (no parse-failure
      // arm — any text is a valid lens definition).
      const custom = (args ?? "").trim();
      await openObjectiveReviewAndGuide(
        pi,
        ctx,
        gating,
        {
          rendered,
          artifactRaw: artifact.content,
          ...(custom.length > 0 ? { custom } : {}),
        },
        draftReview,
        annotations,
        reviews,
      );
    },
  });
}
