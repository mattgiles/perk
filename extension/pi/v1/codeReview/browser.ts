// The warm `/pr-review-browser` door: the BROWSER entry into human-in-the-loop adversarial PR
// review — plannotator always, no provider dispatch (the surface-named command IS the selection).
//
// Three modes, keyed off the arg parse + the active-PR resolution ladder (the parse is IMPORTED
// from terminal.ts — one function ⇒ identical arg semantics by construction):
//   foreign — `/pr-review-browser <pr|url> [focus]`: the detached `perk pr review checkout`, the
//             browser opened in the background on the PR URL, the async adversarial-reviewer
//             fan-out with per-angle annotation waves streamed to the local plannotator server.
//   active  — `/pr-review-browser [focus]` from a plan worktree whose branch HAS a PR: the same
//             flow re-homed to the human's own worktree (no checkout, no cleanup).
//   local   — no PR yet (`perk pr url` → `no_pr`): the absorbed pre-PR since-base browser review
//             ({cwd, diffType: "since-base", defaultBranch: the plan-ref base}) — NO reviewers,
//             no guidance injection, no port dance (no waves to stream); the door ends
//             immediately and the single respond routes back later.
//
// THE BACKGROUND OPEN: the server URL is deterministic the moment the port is picked
// (plannotator reads `PLANNOTATOR_PORT` at bind time — see plannotatorHandoff.ts), so in the PR
// modes the handler starts `startPlannotatorBrowser`, injects the mode guidance IMMEDIATELY, and
// ends its turn — no blocking readiness poll in the handler. The readiness promise is observed
// in a background task: ready → an info note + a continuation for pending annotation work;
// timeout / an error-or-unavailable bridge settle →
// a loud error plus a degrade notice injected to the model (findings render in-session; posting
// unchanged) AND the annotation surface cleared. `push_annotations` owns the
// hold-and-accumulate discipline: a held batch before any door failure notice means "not up
// yet", never a degrade.
//
// THE POSTING FLIP (contracts §8.4): plannotator's native platform-posting is THE GitHub path —
// the human posts inline comments + APPROVE/COMMENT directly from the UI. Perk composes nothing
// by default; `submit_pr_review` (gates unchanged) is used ONLY for a request-changes verdict
// (the UI cannot post it) or on the human's explicit request.
//
// THE COMPANION TOOLS: the reviewer fan-out is the globally registered `start_review_wave` /
// `collect_review_wave` pair, and the annotation delivery is the globally registered
// `push_annotations` tool PRIMED BY THIS DOOR (`primeAnnotationSurface` over the threaded
// per-activation annotation state on a PR-mode open, cleared on bridge settle and on the
// readiness-degrade arm — the model never sees the URL).
// The door still registers NO tools of its own; perk-side posting reuses `submit_pr_review`
// (installed by `installCuratedSubmissionBindings`). The local (pre-PR) mode never primes.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import { runColdDoor } from "../../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../../substrate/command.ts";
import { interceptConsoleError } from "../../../substrate/consoleCapture.ts";
import { render } from "../../../substrate/prompts.ts";
import { type ReportTarget, report } from "../../../surfaces/report.ts";
import {
  type AnnotationState,
  clearAnnotationSurface,
  primeAnnotationSurface,
  resumeAnnotationDelivery,
} from "../providers/annotations.ts";
import {
  type CodeReviewOutcome,
  decodePrUrl,
  LOCAL_REVIEW_DIFF_TYPE,
  type PrUrl,
  plannotatorPresent,
  planRefBaseOf,
  type RespondSink,
  requestPlannotatorCodeReview,
  resolveReviewTarget,
  routeBrowserRespond,
  routePrReviewOutcome,
  type StartedBrowser,
  startPlannotatorBrowser,
} from "../providers/plannotatorHandoff.ts";
import { type CheckoutOk, decodeCheckout } from "./checkout.ts";
import { parseReviewDoorArgs } from "./terminal.ts";

/** The door's report scope — also the `command:<id>` binding trigger id. */
const SCOPE = "pr-review-browser";

// ------------------------------------------------------------------------ guidance

/** The per-mode guidance selector input (the local mode injects no guidance at all). */
export interface PrReviewBrowserGuidanceOpts {
  mode: "foreign" | "active";
  pr: number;
  prUrl: string;
  worktree: string;
  directive?: string;
}

/**
 * The seed guidance the door injects (the perk-pr-review-browser skill pointer rides the
 * skill-binding suffix — command:pr-review-browser — not hardcoded here). Pure + exported for
 * offline tests.
 * Mode selects the arm file under `prompts/stages/pr-review-browser/` (the bodies differ
 * load-bearingly: foreign carries the untrusted-checkout framing + cleanup; active re-homes to
 * the human's worktree with neither). The local mode has no template — the door injects nothing.
 */
export function prReviewBrowserGuidance(opts: PrReviewBrowserGuidanceOpts): string {
  return render(`stages/pr-review-browser/${opts.mode}.md`, {
    pr: String(opts.pr),
    pr_url: opts.prUrl,
    worktree: opts.worktree,
    directive: opts.directive ?? "",
  });
}

// ------------------------------------------------------------------------ the background open

/**
 * The degrade notice injected when the browser never comes up — the model renders the findings
 * in-session and runs the same triage conversationally; the posting contract is unchanged.
 * Exported as the `openReviewBrowserCore` default (the stack door supplies its own).
 */
export const DEGRADE_NOTICE =
  "The plannotator browser review is unavailable (the review server never became ready) — " +
  "degrade in-session: render the reviewers' reconciled findings as a table in your reply and " +
  "run the same triage loop conversationally. The annotation surface is cleared — " +
  "`push_annotations` now refuses (`no_surface`); render findings in-session. Posting is " +
  "unchanged: perk composes nothing by default; `submit_pr_review` (dry-run first; gates " +
  "unchanged) only for a request-changes verdict or on the human's explicit request.";

/**
 * Observe the readiness poll in the background (the handler has already injected the guidance
 * and ended): ready → an info note + an immediate/followUp annotation-delivery continuation
 * when the still-current surface has held or in-flight work; timeout / an error-or-unavailable
 * bridge settle → a loud error report PLUS the degrade notice injected to the model (idle → immediate,
 * streaming → followUp). A bridge that settled `handled` (the human finished before the poll saw
 * the server) or `aborted` routes via the respond routing alone — no degrade. Structural param
 * slices keep it offline-testable; exported for the door tests.
 */
export async function observeBrowserReadiness(
  pi: RespondSink,
  ctx: ReportTarget & Pick<ExtensionContext, "isIdle">,
  started: StartedBrowser,
  annotations: AnnotationState,
  opts?: { scope?: string; degradeNotice?: string },
): Promise<void> {
  const scope = opts?.scope ?? SCOPE;
  const degradeNotice = opts?.degradeNotice ?? DEGRADE_NOTICE;
  const surface = annotations.surface;
  const state = await started.readiness;
  if (state === "ready") {
    report(ctx, scope, "info", `plannotator is up at ${started.url} — browser opening`);
    resumeAnnotationDelivery(annotations, surface, pi, ctx);
    return;
  }
  if (state === "aborted") return; // the turn was interrupted — no-op
  if (state === "bridge_settled") {
    const out = await started.bridgePromise;
    if (out.status === "handled" || out.status === "aborted") return;
  }
  report(
    ctx,
    scope,
    "error",
    `the plannotator review server did not become ready at ${started.url} — the browser ` +
      "review is unavailable",
    { alsoLog: true },
  );
  if (ctx.isIdle()) {
    pi.sendUserMessage(degradeNotice);
  } else {
    pi.sendUserMessage(degradeNotice, { deliverAs: "followUp" });
  }
  // Consistent with "render findings in-session": a post-degrade push_annotations refuses
  // loudly (`no_surface`). Idempotent beside the bridge-settle clear.
  clearAnnotationSurface(annotations);
}

/** The parameterized browser-lifecycle core's options (see `openReviewBrowserCore`). */
export interface ReviewBrowserCoreOpts {
  /** The invoking door's report scope. */
  scope: string;
  /** The `startPlannotatorBrowser` opts minus `signal` (the core threads `ctx.signal`). */
  browserOpts: { cwd: string; prUrl?: string; diffType?: string; defaultBranch?: string };
  /** The fully composed guidance to inject (binding suffix included by the caller). */
  guidance: string;
  /** The degrade notice for the browser-never-ready arm (default: the PR-mode notice). */
  degradeNotice?: string;
  /** The respond → injection mapper (default: `respondMessage` — the single-PR contract). */
  respondMessageFor?: (outcome: CodeReviewOutcome) => string | null;
  /**
   * Whether the core injects `guidance` as a user message at the end (default true — the warm
   * doors). The `open_stack_review` tool passes false and returns the guidance as its ok text
   * instead (the tool result is the seeded session's delivery channel).
   */
  injectGuidance?: boolean;
}

/**
 * The full browser-lifecycle core, extracted from the PR-mode arm and parameterized for the
 * stack door: start the browser open in the background, prime the annotation surface the
 * moment the port is picked (push_annotations now serves this browser session), observe
 * readiness in the background (degrade notice on never-ready), route the bridge respond
 * through the injectable mapper, clear the surface on settle, and inject the guidance
 * immediately (the URL is deterministic once the port is picked). While plannotator sets up,
 * its in-process `console.error` chatter re-routes through the TUI-safe report() seam (the
 * debounce restores once setup goes quiet, with the `finally` as a backstop).
 *
 * Accepted stale-clear edge (unchanged from the pre-extraction arm): a second browser door
 * while this browser is still open re-primes (a new browser session supersedes everything),
 * and THIS bridge's later settle would clear the second session's surface — rare and loud
 * (the fixed-port EADDRINUSE caveat, contracts §8.4), noted, not engineered around.
 */
export async function openReviewBrowserCore(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  annotations: AnnotationState,
  opts: ReviewBrowserCoreOpts,
): Promise<boolean> {
  let started: StartedBrowser;
  try {
    started = await startPlannotatorBrowser(pi.events, {
      ...opts.browserOpts,
      signal: ctx.signal,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    report(
      ctx,
      opts.scope,
      "error",
      `could not pick a free local port for the plannotator review server: ${detail}`,
      { alsoLog: true },
    );
    return false;
  }

  primeAnnotationSurface(annotations, { mode: "review", url: started.url });

  void observeBrowserReadiness(pi, ctx, started, annotations, {
    scope: opts.scope,
    ...(opts.degradeNotice !== undefined ? { degradeNotice: opts.degradeNotice } : {}),
  });

  void (async () => {
    const interceptor = interceptConsoleError((line) => report(ctx, opts.scope, "info", line), {
      // plannotator can pause up to ~4s between setup lines — keep the quiet window above that.
      quietMs: 6000,
    });
    try {
      const out = await started.bridgePromise;
      routeBrowserRespond(pi, ctx, out, opts.scope, opts.respondMessageFor);
    } finally {
      // The browser session is over — drop the surface so a later push refuses (`no_surface`).
      clearAnnotationSurface(annotations);
      interceptor.restore();
    }
  })();

  if (opts.injectGuidance !== false) pi.sendUserMessage(opts.guidance);
  return true;
}

/**
 * The shared PR-mode arm (foreign + active): the extracted core with this door's values —
 * PR-mode browser opts, the mode guidance + binding suffix, and the default degrade notice /
 * respond mapper (the byte-stability of the pre-extraction behavior is proven by this door's
 * untouched tests).
 */
async function openBrowserAndGuide(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  annotations: AnnotationState,
  opts: PrReviewBrowserGuidanceOpts,
): Promise<void> {
  await openReviewBrowserCore(pi, ctx, annotations, {
    scope: SCOPE,
    browserOpts: { prUrl: opts.prUrl, cwd: ctx.cwd },
    guidance: prReviewBrowserGuidance(opts) + bindingSuffix(ctx.cwd, `command:${SCOPE}`),
  });
}

// ------------------------------------------------------------------------ registration

/** Install the warm `/pr-review-browser` command (no tools — posting rides submit_pr_review). */
export function installPrReviewBrowserBindings(
  pi: ExtensionAPI,
  annotations: AnnotationState,
): void {
  registerPerkCommand(pi, SCOPE, {
    description:
      "Review a PR human-in-the-loop in the plannotator browser UI: no arg reviews the active " +
      "worktree's PR (or, pre-PR, opens a since-base browser review); a PR number/URL reviews " +
      "that foreign PR. Any other text is a focus note for the reviewers. You post to GitHub " +
      "from the browser.",
    handler: async (args, ctx: ExtensionContext) => {
      // Entry gates, in order — nothing executed on refusal, each a loud error.
      const parsed = parseReviewDoorArgs(args ?? "");
      if (parsed === null) {
        report(ctx, SCOPE, "error", "usage: /pr-review-browser [pr number|url] [focus note]");
        return;
      }
      if (!ctx.hasUI) {
        report(
          ctx,
          SCOPE,
          "error",
          "/pr-review-browser requires an interactive session — the plannotator browser " +
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

      if (parsed.mode === "foreign") {
        // The foreign arm: the detached checkout, then the background browser open.
        const checkout = await runColdDoor<CheckoutOk>(
          pi,
          ctx,
          ["pr", "review", "checkout", "--pr", String(parsed.pr), "--json"],
          { label: "perk pr review checkout", decode: decodeCheckout },
        );
        if (!checkout.ok) {
          report(
            ctx,
            SCOPE,
            "error",
            `perk pr review checkout failed (${checkout.errorType}): ${checkout.message}`,
            { alsoLog: true },
          );
          return;
        }
        report(
          ctx,
          SCOPE,
          "info",
          parsed.directive
            ? `PR #${parsed.pr} → adversarial reviewers (focus: ${parsed.directive}) → plannotator browser triage → you post from the browser`
            : `PR #${parsed.pr} → adversarial reviewers → plannotator browser triage → you post from the browser`,
        );
        await openBrowserAndGuide(pi, ctx, annotations, {
          mode: "foreign",
          pr: parsed.pr,
          prUrl: checkout.data.url,
          worktree: checkout.data.path,
          directive: parsed.directive,
        });
        return;
      }

      // The active arm: resolve the worktree's own PR via the shared ladder.
      const r = await runColdDoor<PrUrl>(pi, ctx, ["pr", "url", "--json"], {
        label: "perk pr url",
        decode: decodePrUrl,
      });
      const target = resolveReviewTarget(r, planRefBaseOf(ctx.cwd));
      if (target.mode === "fail") {
        report(
          ctx,
          SCOPE,
          "error",
          `${target.message} (${target.errorType}) — pass a PR number/URL, or run from a plan ` +
            "worktree",
        );
        return;
      }

      if (target.mode === "pr") {
        report(
          ctx,
          SCOPE,
          "info",
          parsed.directive
            ? `PR #${target.number} (active worktree) → adversarial reviewers (focus: ${parsed.directive}) → plannotator browser triage → you post from the browser`
            : `PR #${target.number} (active worktree) → adversarial reviewers → plannotator browser triage → you post from the browser`,
        );
        await openBrowserAndGuide(pi, ctx, annotations, {
          mode: "active",
          pr: target.number,
          prUrl: target.prUrl,
          worktree: ctx.cwd,
          directive: parsed.directive,
        });
        return;
      }

      // The local / pre-PR mode (the absorbed since-base browser review): no reviewers, no
      // guidance, no port dance (no waves to stream — no endpoint needed). The bridge runs in
      // the background and the single respond routes back via routePrReviewOutcome.
      report(
        ctx,
        SCOPE,
        "info",
        `No PR yet — opening plannotator local review (since-base vs ${target.defaultBranch ?? "repo default"}) …`,
      );
      void (async () => {
        const interceptor = interceptConsoleError((line) => report(ctx, SCOPE, "info", line), {
          // plannotator can pause up to ~4s between setup lines — keep the quiet window
          // comfortably above that so the debounce doesn't restore mid-setup.
          quietMs: 6000,
        });
        try {
          const out = await requestPlannotatorCodeReview(pi.events, {
            cwd: ctx.cwd,
            diffType: LOCAL_REVIEW_DIFF_TYPE,
            defaultBranch: target.defaultBranch,
            signal: ctx.signal,
          });
          routePrReviewOutcome(pi, ctx, out, SCOPE);
        } finally {
          interceptor.restore();
        }
      })();
    },
  });
}
