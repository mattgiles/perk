// The learn flow's guidance prose: the judgment-bearing template renders the warm surfaces
// inject (`stages/learn.md`, `stages/learn-orchestrate.md`, and the per-kind factory seeds) over
// the cross-plane render seam (contracts.md §8.31). Skill pointers are NEVER hardcoded here —
// they ride the skill-binding suffix at the adapter's injection site. Pure + exported for
// offline tests.

import type { PlanRef } from "../substrate/cache.ts";
import { planReadInstruction, render } from "../substrate/prompts.ts";
import type { LearnFactoryKind } from "./routing.ts";

/**
 * Inject the learn-workflow guidance the model follows (the perk-learn skill pointer rides the
 * skill-binding suffix — not hardcoded here). The wording lives in the canonical template
 * `prompts/stages/learn.md`, rendered identically by both planes via the shared render seam
 * (contracts.md §8.31); the github/linear/other/no-ref branching is the template conditional on
 * `provider` (+ `pr_id` presence), and `read_cmd` is the plan-read instruction. Unified
 * onto the cold `_learn_prompt` body — byte-identical to it for every provider arm (the four
 * `learn-*` golden cases are the cross-plane parity proof). When no plan-ref is known, render the
 * no-ref arm (learn can proceed without a ref — no dead-end null-guard).
 */
export function learnGuidance(planRef: PlanRef | null): string {
  if (planRef === null) {
    return render("stages/learn.md", { provider: "", pr_id: "", url: "", read_cmd: "" });
  }
  const read_cmd = planReadInstruction(planRef.provider, planRef.pr_id, planRef.url);
  return render("stages/learn.md", {
    provider: planRef.provider,
    pr_id: planRef.pr_id,
    url: planRef.url,
    read_cmd,
  });
}

/**
 * The orchestration seed the warm bare `/learn` injects to run the analyst wave (via the
 * `run_learn_wave` tool) and reconcile the typed reports into one classified capture/skip (the
 * perk-learn skill pointer rides the skill-binding suffix — stage:learn — not hardcoded here).
 * Pure + exported for offline tests (mirrors `prReviewGuidance`). Judgment-bearing inputs only —
 * the wave mechanics (script, spawn params, model resolution) live in the tool.
 * `manifestPath` is absolute; `bundleDir` is the absolute bundle directory.
 */
export function learnOrchestrateGuidance(opts: {
  manifestPath: string;
  bundleDir: string;
}): string {
  return render("stages/learn-orchestrate.md", {
    manifest_path: opts.manifestPath,
    bundle_dir: opts.bundleDir,
  });
}

/**
 * The seed guidance the warm factory door injects to start the factory loop (the per-kind skill
 * pointer rides the skill-binding suffix — not hardcoded here). Pure + exported for offline
 * tests.
 */
export function learnFactoryGuidance(
  kind: LearnFactoryKind,
  inboxPath: string,
  learnNumbers: string[],
): string {
  return render(kind.seedTemplate, {
    inbox_path: inboxPath,
    num_list: learnNumbers.join(", "),
  });
}
