// The warm `/pr-review-terminal` door: the TERMINAL entry into human-in-the-loop adversarial PR
// review — hunk always, no provider dispatch (the surface-named command IS the selection).
//
// Three modes, keyed off the arg parse + the active-PR resolution ladder:
//   foreign — `/pr-review-terminal <pr|url> [focus]`: the detached `perk pr review checkout`,
//             the R7 handoff, the full adversarial-reviewer flow (async fan-out + live findings
//             streaming per the injected guidance).
//   active  — `/pr-review-terminal [focus]` from a plan worktree whose branch HAS a PR: the same
//             flow re-homed to the human's own worktree (no checkout, no cleanup) on the local
//             since-base diff (`sinceBaseSha` — best-effort fetch, then merge-base).
//   local   — no PR yet (`perk pr url` → `no_pr`): a surface-only since-base review — hunk is
//             launched, NO reviewers are spawned and NOTHING posts to GitHub; the guidance is a
//             minimal notes read-back loop.
// Every launch carries `--agent-notes` so pushed findings are visible in hunk immediately.
//
// The door registers NO tools — posting reuses `submit_pr_review` (registered by
// `registerSubmitPrReview`), whose gate ladder (contracts §8.4) applies unchanged.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { runColdDoor } from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { loadPerkConfig } from "../substrate/config.ts";
import { sinceBaseSha } from "../substrate/git.ts";
import { render } from "../substrate/prompts.ts";
import { report } from "../surfaces/report.ts";
import {
  type CheckoutOk,
  decodeCheckout,
  HUNK_INSTALL_HINT,
  handleHunkLaunch,
  hunkPresent,
  parseReviewArgs,
} from "./hunkHandoff.ts";
import { decodePrUrl, planRefBaseOf, resolveReviewTarget } from "./plannotatorHandoff.ts";

/** The door's report scope — also the `command:<id>` binding trigger id. */
const SCOPE = "pr-review-terminal";

// ------------------------------------------------------------------------ arg parse

/** A parsed review-door invocation: foreign (a PR arg) or active (everything else). */
export type ReviewDoorArgs =
  | { mode: "foreign"; pr: number; directive: string }
  | { mode: "active"; directive: string };

/**
 * Parse the review-door args (shared by BOTH doors — the browser door imports this, so one
 * function ⇒ identical grammar by construction) — both tokens optional:
 * - empty/whitespace → active mode, no focus;
 * - a leading PR number/URL (the shared PR-token grammar) → foreign mode (+ optional focus);
 * - a leading `http(s)://` token that FAILS the PR parse → null (usage error: a mistyped PR URL
 *   never silently becomes a focus note);
 * - anything else → active mode with the whole string as the focus note.
 */
export function parseReviewDoorArgs(args: string): ReviewDoorArgs | null {
  const trimmed = args.trim();
  if (trimmed.length === 0) return { mode: "active", directive: "" };
  const parsed = parseReviewArgs(trimmed);
  if (parsed !== null) return { mode: "foreign", pr: parsed.pr, directive: parsed.directive };
  const first = trimmed.split(/\s+/, 1)[0] ?? "";
  if (/^https?:\/\//.test(first)) return null;
  return { mode: "active", directive: trimmed };
}

// ------------------------------------------------------------------------ guidance

/** The per-mode guidance selector input (the local arm has no PR and threads no directive). */
export type PrReviewTerminalGuidanceOpts =
  | {
      mode: "foreign" | "active";
      pr: number;
      worktree: string;
      baseSha: string;
      model?: string;
      directive?: string;
    }
  | { mode: "local"; worktree: string; baseSha: string };

/**
 * The seed guidance the door injects (the perk-pr-review-terminal skill pointer rides the
 * skill-binding suffix — command:pr-review-terminal — not hardcoded here). Pure + exported for
 * offline tests.
 * Mode selects the arm file under `prompts/stages/pr-review-terminal/` (the bodies differ
 * load-bearingly: foreign carries the untrusted-checkout framing + cleanup; active re-homes to
 * the human's worktree with neither; local is the reviewers-skipped surface-only note).
 */
export function prReviewTerminalGuidance(opts: PrReviewTerminalGuidanceOpts): string {
  if (opts.mode === "local") {
    return render("stages/pr-review-terminal/local.md", {
      worktree: opts.worktree,
      base_sha: opts.baseSha,
    });
  }
  return render(`stages/pr-review-terminal/${opts.mode}.md`, {
    pr: String(opts.pr),
    worktree: opts.worktree,
    base_sha: opts.baseSha,
    model: opts.model ?? "",
    directive: opts.directive ?? "",
  });
}

// ------------------------------------------------------------------------ registration

/** Register the warm `/pr-review-terminal` command (no tools — posting rides submit_pr_review). */
export function registerPrReviewTerminal(pi: ExtensionAPI): void {
  registerPerkCommand(pi, SCOPE, {
    description:
      "Review a PR human-in-the-loop in the hunk terminal TUI: no arg reviews the active " +
      "worktree's PR (or, pre-PR, opens a since-base hunk review); a PR number/URL reviews " +
      "that foreign PR. Any other text is a focus note for the reviewers.",
    handler: async (args, ctx: ExtensionContext) => {
      // Entry gates, in order — nothing executed on refusal, each a loud error.
      const parsed = parseReviewDoorArgs(args ?? "");
      if (parsed === null) {
        report(ctx, SCOPE, "error", "usage: /pr-review-terminal [pr number|url] [focus note]");
        return;
      }
      if (!ctx.hasUI) {
        report(
          ctx,
          SCOPE,
          "error",
          "/pr-review-terminal requires an interactive session — the hunk surface and the " +
            "human triage are constitutive",
        );
        return;
      }
      if (!(await hunkPresent(pi, ctx))) {
        report(
          ctx,
          SCOPE,
          "error",
          `the \`hunk\` review CLI is not available — install it: ${HUNK_INSTALL_HINT}`,
        );
        return;
      }

      const config = loadPerkConfig(ctx.cwd);
      const model = config.subagents["adversarial-reviewer"] ?? "";

      if (parsed.mode === "foreign") {
        // The foreign arm: detached checkout + handoff.
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
            ? `PR #${parsed.pr} → adversarial reviewers (focus: ${parsed.directive}) → hunk triage → curated post`
            : `PR #${parsed.pr} → adversarial reviewers → hunk triage → curated post`,
        );
        // 12 hex chars: the full sha wraps in the TUI and a wrapped paste runs a bare
        // `hunk diff`; git resolves 12 chars unambiguously (the first dogfood's lesson).
        const baseSha = checkout.data.base_sha.slice(0, 12);
        const hunkCmd = `hunk diff ${baseSha} --agent-notes`;
        const launchLine = `cd ${checkout.data.path} && ${hunkCmd}`;
        await handleHunkLaunch(pi, ctx, {
          cwd: checkout.data.path,
          hunkCmd,
          launchLine,
          scope: SCOPE,
        });
        pi.sendUserMessage(
          prReviewTerminalGuidance({
            mode: "foreign",
            pr: parsed.pr,
            worktree: checkout.data.path,
            baseSha,
            model,
            directive: parsed.directive,
          }) + bindingSuffix(ctx.cwd, `command:${SCOPE}`),
        );
        return;
      }

      // The active arm: resolve the worktree's own PR via the shared active-PR ladder.
      const r = await runColdDoor<{ number: number; url: string }>(
        pi,
        ctx,
        ["pr", "url", "--json"],
        { label: "perk pr url", decode: decodePrUrl },
      );
      const planRefBase = planRefBaseOf(ctx.cwd);
      const target = resolveReviewTarget(r, planRefBase);
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

      // The since-base merge-base (best-effort fetch first): the sha hunk diffs the working tree
      // against. On the local arm the target threads the plan-ref's pinned base; on the PR arm
      // the plan-ref base is read the same way (null ⇒ repo default via origin/HEAD).
      const fullSha = sinceBaseSha(
        ctx.cwd,
        target.mode === "local" ? target.defaultBranch : planRefBase,
      );
      if (fullSha === null) {
        report(
          ctx,
          SCOPE,
          "error",
          "could not resolve the since-base merge-base — pass a PR number/URL instead",
        );
        return;
      }
      const baseSha = fullSha.slice(0, 12);

      if (target.mode === "pr") {
        report(
          ctx,
          SCOPE,
          "info",
          parsed.directive
            ? `PR #${target.number} (active worktree) → adversarial reviewers (focus: ${parsed.directive}) → hunk triage → curated post`
            : `PR #${target.number} (active worktree) → adversarial reviewers → hunk triage → curated post`,
        );
      } else {
        report(
          ctx,
          SCOPE,
          "info",
          "no PR yet — since-base review in hunk; reviewers skipped (no PR to review)",
        );
      }

      const hunkCmd = `hunk diff ${baseSha} --agent-notes`;
      const launchLine = `cd ${ctx.cwd} && ${hunkCmd}`;
      await handleHunkLaunch(pi, ctx, { cwd: ctx.cwd, hunkCmd, launchLine, scope: SCOPE });

      const guidance =
        target.mode === "pr"
          ? prReviewTerminalGuidance({
              mode: "active",
              pr: target.number,
              worktree: ctx.cwd,
              baseSha,
              model,
              directive: parsed.directive,
            })
          : prReviewTerminalGuidance({ mode: "local", worktree: ctx.cwd, baseSha });
      pi.sendUserMessage(guidance + bindingSuffix(ctx.cwd, `command:${SCOPE}`));
    },
  });
}
