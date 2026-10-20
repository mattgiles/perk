// The warm `/pr-review-browser` door: the BROWSER entry into human-in-the-loop adversarial PR
// review — plannotator always, no provider dispatch (the surface-named command IS the selection).
//
// Three modes, keyed off the arg parse + the active-PR resolution ladder (the parse is IMPORTED
// from terminal.ts — one function ⇒ identical arg semantics by construction):
//   foreign — `/pr-review-browser <pr|url> [focus]`: the detached `perk pr review checkout`, the
//             browser opened in the background on the PR URL, the async adversarial-reviewer
//             fan-out whose reconciled per-angle findings land on the local plannotator server
//             after collection (completion-only — the code-owned `perk:wave` marker shows the
//             wave running until then).
//   active  — `/pr-review-browser [focus]` from a plan worktree whose branch HAS a PR: the same
//             flow re-homed to the human's own worktree (no checkout, no cleanup).
//   local   — no PR yet (`perk pr url` → `no_pr`): the absorbed pre-PR since-base browser review
//             ({cwd, diffType: "since-base", defaultBranch: the plan-ref base}) — NO reviewers,
//             no guidance injection, no port dance (no wave, so no annotation endpoint needed);
//             the door ends immediately and the single respond routes back later.
//
// THE BACKGROUND OPEN THROUGH THE OWNER (`browserOperation.ts`, contracts §8.23): the PR modes
// open through the activation's browser-operation owner with the code-review spec (mode
// `review`, `REVIEW_BROWSER_PRIMES`, no companion, no applicability fence). The server URL is
// deterministic the moment the owner picks the port (mirroring Plannotator's own port selection;
// plannotator reads the preset `PLANNOTATOR_PORT` at bind time — see plannotatorHandoff.ts), so
// the handler injects the mode guidance IMMEDIATELY and ends its turn — no blocking readiness
// poll in the handler. The owner observes readiness in the background: ready → an info note + a
// continuation for pending annotation work; timeout / an error-or-unavailable bridge settle → a
// loud error plus a degrade notice injected to the model (findings render in-session; posting
// unchanged) AND the annotation surface cleared. A decision made after that degrade is ignored
// with one warning naming the re-run (the owner's one post-degrade rule). The owner clears the
// surface only while this review still owns it, so an older review can never clear a
// successor's; opening ANY browser door again REPLACES this review (its tab is marked detached
// through the `perk:wave` slot, its wait aborted, its decision never routed), and a turn abort or
// a session reload/replacement detaches it the same way. `push_annotations` owns the
// hold-and-accumulate discipline: a batch held before readiness means "not up yet", never a
// degrade (the readiness notice flushes it); a batch held AFTER readiness exhausted the tool's
// bounded retries and is presented in-session.
//
// THE POSTING FLIP (contracts §8.4): plannotator's native platform-posting is THE GitHub path —
// the human posts inline comments + APPROVE/COMMENT directly from the UI. Perk composes nothing
// by default; `submit_pr_review` (gates unchanged) is used ONLY for a request-changes verdict
// (the UI cannot post it) or on the human's explicit request.
//
// THE COMPANION TOOLS: the reviewer fan-out is the globally registered `start_review_wave` /
// `collect_review_wave` pair, and the annotation delivery is the globally registered
// `push_annotations` tool, PRIMED through the owner on a PR-mode open (over the activation's
// annotation state — the model never sees the URL) and cleared by it on settle, degrade or
// detach. The door still registers NO tools of its own; perk-side posting reuses
// `submit_pr_review` (installed by `installCuratedSubmissionBindings`). The local (pre-PR) mode
// never primes. In a discovery-cohort session the guidance names two deferred tools, so the same
// moment also activates them (`REVIEW_BROWSER_PRIMES`) before the guidance reaches the model.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import { runColdDoor } from "../../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../../substrate/command.ts";
import { interceptConsoleError } from "../../../substrate/consoleCapture.ts";
import { render } from "../../../substrate/prompts.ts";
import { report } from "../../../surfaces/report.ts";
import {
  type BrowserOperationOwner,
  type BrowserOperationSpec,
  settleCodeReviewOutcome,
} from "../browserOperation.ts";
import {
  type CodeReviewOutcome,
  type CodeReviewSource,
  decodePrUrl,
  type PrUrl,
  plannotatorPresent,
  planRefBaseOf,
  requestPlannotatorCodeReview,
  resolveReviewTarget,
  routeBrowserRespond,
  routePrReviewOutcome,
  startPlannotatorBrowser,
} from "../providers/plannotatorHandoff.ts";
import { WAVE_ARRIVAL_NOTICE } from "../providers/waveStatus.ts";
import type { DoorOpenResult } from "../review.ts";
import { type CheckoutOk, decodeCheckout } from "./checkout.ts";
import { parseReviewDoorArgs } from "./terminal.ts";

/** The door's report scope — also the `command:<id>` binding trigger id. */
const SCOPE = "pr-review-browser";

/**
 * The deferred tools a browser review's guidance names — primed the moment the annotation
 * surface is (a no-op outside the discovery cohort).
 */
export const REVIEW_BROWSER_PRIMES = ["collect_review_wave", "push_annotations"] as const;

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

/** The code-review open's result: the door result, or a launch-time `beforeStart` refusal. */
export type ReviewBrowserOpenResult = DoorOpenResult | { kind: "refused"; detail: string };

/** The code-review spec's door-supplied options (see `openReviewBrowserCore`). */
export interface ReviewBrowserCoreOpts {
  /** The invoking door's report scope. */
  scope: string;
  /** The `startPlannotatorBrowser` opts minus `signal`/`activity` (both threaded by the owner). */
  browserOpts: { cwd: string; source: CodeReviewSource };
  /** The fully composed guidance a `launched` result carries (binding suffix included). */
  guidance: string;
  /** The degrade notice for the browser-never-ready arm (default: the PR-mode notice). */
  degradeNotice?: string;
  /** The respond → injection mapper (default: `respondMessage` — the single-PR contract). */
  respondMessageFor?: (outcome: CodeReviewOutcome) => string | null;
  /**
   * The launch-time gate, run inside the owner's start immediately before the request is
   * emitted (after any predecessor's retirement): throw `BrowserStartRefusal` to refuse — the
   * owner reports the message verbatim and nothing is emitted or primed.
   */
  beforeStart?: () => void;
}

/**
 * The code-review browser open over the activation's browser-operation owner (both code-review
 * doors): build the code-review spec — `startPlannotatorBrowser` as the handoff, mode `review`,
 * `REVIEW_BROWSER_PRIMES`, no companion, no applicability fence, the door's degrade notice and
 * respond mapper — and open it. The owner retires any earlier browser review first, starts the
 * handoff, primes the annotation surface + the deferred tools the guidance names, observes
 * readiness and the decision in the background, intercepts plannotator's setup chatter and
 * clears the surface only while this operation still owns it. Delivery is the caller's:
 * `launched` carries `opts.guidance`; `unlaunched` (the port-pick failure, already reported
 * loudly) and `retired` (a newer open took over — its guidance stands) deliver nothing;
 * `refused` (the caller's `beforeStart` refused, already reported) carries the refusal text.
 */
export async function openReviewBrowserCore(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  owner: BrowserOperationOwner,
  opts: ReviewBrowserCoreOpts,
): Promise<ReviewBrowserOpenResult> {
  const spec: BrowserOperationSpec<CodeReviewOutcome> = {
    scope: opts.scope,
    start: async (launch) => {
      opts.beforeStart?.();
      return await startPlannotatorBrowser(
        pi.events,
        { ...opts.browserOpts, signal: launch.signal, activity: launch.activity },
        launch.deps,
      );
    },
    mode: "review",
    primes: REVIEW_BROWSER_PRIMES,
    degradeNotice: opts.degradeNotice ?? DEGRADE_NOTICE,
    settle: settleCodeReviewOutcome,
    // The owner hands over `handled` only; the router stays total over the outcome union.
    onDecision: async (out) => {
      routeBrowserRespond(pi, ctx, out, opts.scope, opts.respondMessageFor);
    },
  };
  const opened = await owner.open(ctx, spec);
  if (opened.kind === "retired") return { kind: "retired" };
  if (opened.kind === "failed") {
    return opened.refused !== undefined
      ? { kind: "refused", detail: opened.refused }
      : { kind: "unlaunched" };
  }
  return { kind: "launched", guidance: opts.guidance };
}

/**
 * The shared PR-mode arm (foreign + active): the code-review open with this door's values —
 * PR-mode browser opts, the mode guidance + binding suffix, and the default degrade notice /
 * respond mapper — injecting the guidance only when the browser launched (an unlaunched open
 * was already reported; a retired one yields to the newer open's guidance).
 */
async function openBrowserAndGuide(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  owner: BrowserOperationOwner,
  opts: PrReviewBrowserGuidanceOpts,
): Promise<void> {
  const opened = await openReviewBrowserCore(pi, ctx, owner, {
    scope: SCOPE,
    browserOpts: { cwd: ctx.cwd, source: { mode: "pr", prUrl: opts.prUrl } },
    guidance: prReviewBrowserGuidance(opts) + bindingSuffix(ctx.cwd, `command:${SCOPE}`),
  });
  if (opened.kind === "launched") pi.sendUserMessage(opened.guidance);
}

// ------------------------------------------------------------------------ registration

/**
 * Install the warm `/pr-review-browser` command (no tools — posting rides submit_pr_review).
 * `owner` is the activation's browser-operation owner (it carries the port selection):
 * both PR-mode opens go through it; the pre-PR local arm stays outside it (plannotator resolves
 * that port itself).
 */
export function installPrReviewBrowserBindings(
  pi: ExtensionAPI,
  owner: BrowserOperationOwner,
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
          (parsed.directive
            ? `PR #${parsed.pr} → adversarial reviewers (focus: ${parsed.directive}) → plannotator browser triage → you post from the browser`
            : `PR #${parsed.pr} → adversarial reviewers → plannotator browser triage → you post from the browser`) +
            WAVE_ARRIVAL_NOTICE,
        );
        await openBrowserAndGuide(pi, ctx, owner, {
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
          (parsed.directive
            ? `PR #${target.number} (active worktree) → adversarial reviewers (focus: ${parsed.directive}) → plannotator browser triage → you post from the browser`
            : `PR #${target.number} (active worktree) → adversarial reviewers → plannotator browser triage → you post from the browser`) +
            WAVE_ARRIVAL_NOTICE,
        );
        await openBrowserAndGuide(pi, ctx, owner, {
          mode: "active",
          pr: target.number,
          prUrl: target.prUrl,
          worktree: ctx.cwd,
          directive: parsed.directive,
        });
        return;
      }

      // The local / pre-PR mode (the absorbed since-base browser review): no reviewers, no
      // guidance, no port dance (no wave — no endpoint needed). The bridge runs in the
      // background and the single respond routes back via routePrReviewOutcome. It stays OUTSIDE
      // the browser-operation owner: plannotator picks its own port (no deterministic URL),
      // nothing is primed and readiness is not observed — nothing to own or mark. The task holds
      // this ctx (not reload-safe), so a respond reaching a stale ctx is contained to one stderr
      // line — a discarded promise owns its failure path, never an unhandled rejection.
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
            source: { mode: "local", defaultBranch: target.defaultBranch },
            signal: ctx.signal,
          });
          routePrReviewOutcome(pi, ctx, out, SCOPE);
        } finally {
          interceptor.restore();
        }
      })().catch((error: unknown) => {
        const detail = error instanceof Error ? error.message : String(error);
        console.error(`perk: ${SCOPE} — the local browser review task failed: ${detail}`);
      });
    },
  });
}
