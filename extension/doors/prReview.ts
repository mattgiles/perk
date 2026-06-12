// #175 — the warm `/pr-review` door: automated code review in a FRESH, isolated subagent session.
//
// Unlike `/address` (which spawns a read-only classifier and the PARENT applies fixes), `/pr-review`
// has no parent-side action: the review's only output sink is the PR itself. So the spawned
// `perk.pr-reviewer` child — running in a FRESH context so the implementation session's history
// never biases it — POSTS its own review to the PR through the Python gateway (`perk pr review-post`,
// D1: GitHub mutations stay canonical in Python). The parent merely surfaces the child's terse
// confirmation. This deliberate departure from the read-only-child convention is documented in
// shared/contracts.md §8.3.
//
// No model tool here — the model uses the borrowed `pi-subagents` `subagent` tool to spawn the
// reviewer. The review model is configurable via `[subagents] pr-reviewer` in `.pi/perk.toml`;
// because `subagents.agentOverrides` does NOT reach project agents, the warm command injects that
// model as a per-call inline `model` override on the spawn (the agent's frontmatter model is the
// default).
//
// Headless-safe: rich UI is guarded by `ctx.hasUI`; without a UI it logs to stderr.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { loadPerkConfig } from "../substrate/config.ts";
import { report } from "../surfaces/report.ts";

/**
 * The seed guidance the warm `/pr-review` injects to spawn the reviewer (the perk-pr-review skill
 * pointer rides the skill-binding suffix — command:pr-review — not hardcoded here). Pure + exported
 * for offline tests. When `model` is set, the spawn carries an inline `model` override; otherwise
 * the agent's default model is used.
 */
export function prReviewGuidance(model?: string): string {
  const modelClause = model
    ? `, and pass \`model: "${model}"\` on that call (the configured [subagents] pr-reviewer model)`
    : " (no model override — the agent's default model is used)";
  return [
    "perk /pr-review — automated code review of the active PR in a FRESH, isolated session.",
    `1. Spawn the \`perk.pr-reviewer\` agent via the \`subagent\` tool with \`context: "fresh"\`${modelClause}. ` +
      "A fresh context keeps this implementation session's history from biasing the review.",
    "2. The child reviews the active plan's PR (it runs `perk pr review-context` itself) and posts " +
      "a verdict-driven outcome via `perk pr review-post`: actionable findings land as an advisory " +
      "COMMENT review; a clean PR gets a single \u{1F44D} reaction (no comments land on the PR). " +
      "The raw diff never enters this session.",
    "3. Take NO further action: simply surface the child's terse confirmation \u2014 the verdict, " +
      "the next step (clean \u21D2 `/land`, actionable \u21D2 `/address`), the PR number and comment " +
      "count, and any FYI notes (in-session only, never posted to GitHub). The review lives on the " +
      "PR; you neither apply fixes nor resolve threads here.",
  ].join("\n");
}

/** Register the warm pr-review door: the `/pr-review` command (no model tool — the child posts). */
export function registerPrReview(pi: ExtensionAPI): void {
  pi.registerCommand("pr-review", {
    description:
      "Review the active PR in a fresh, isolated subagent that posts its review to the PR. " +
      "The review model is configurable via [subagents] pr-reviewer in .pi/perk.toml.",
    handler: async (_args, ctx: ExtensionContext) => {
      const model = loadPerkConfig(ctx.cwd).subagents["pr-reviewer"];
      const guidance = prReviewGuidance(model);
      report(ctx, "pr-review", "info", "fresh-context review → posts to the PR");
      // Inject the spawn guidance as a user message so the model starts the review (warm entry).
      // The perk-pr-review pointer rides the skill-binding suffix (command:pr-review, D5).
      pi.sendUserMessage(guidance + bindingSuffix(ctx.cwd, "command:pr-review"));
    },
  });
}
