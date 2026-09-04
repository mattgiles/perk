// Pi-free session-lifecycle gate policy: the planning-stage lifecycle-door refusal (the shared
// first check of the warm /submit, /address, /land, and /learn doors) and the plan-read handoff
// priming for a fresh implement session. The Pi registration half (the session_before_fork/
// switch hooks + the guard-only `/implement` command) lives in `pi/v1/lifecycleGates.ts`; this
// module carries the policy those adapters apply.

import type { PlanRef } from "../substrate/cache.ts";
import { planReadInstruction, render } from "../substrate/prompts.ts";
import { type BranchSource, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";

// The planning stages whose sessions never legitimately run lifecycle doors. After an approved
// save, a still-live planning session holds TWO plan identities — the cwd binding (a positioned
// stacked session's predecessor checkout, read via readPlanRef(ctx.cwd)) and the just-saved plan
// on active_plan_ref — so a door invocation there could act on the predecessor. At the repo root
// the same invocation fails confusingly today; the refusal is honest in both shapes.
const PLANNING_STAGES = new Set(["plan", "objective-plan"]);

/**
 * The planning-stage lifecycle-door refusal (the shared first check of the warm /submit,
 * /address, /land, and /learn doors): when this session's workflow-state `stage` is a planning
 * stage, return the refusal message directing the human at the fresh-session implement door;
 * `null` otherwise (non-planning stages — and stage-less sessions — are unaffected). Fail-CLOSED
 * on an unreadable branch: without the state this guard cannot prove the session is not a
 * positioned planning session (whose cwd binding is the PREDECESSOR — the exact target it
 * protects), so an unreadable read refuses rather than letting the door act.
 */
export function planningStageRefusal(ctx: BranchSource, door: string): string | null {
  let stage: string | undefined;
  try {
    stage = rebuildWorkflowState(branchOf(ctx)).stage;
  } catch (error) {
    return (
      `${door} is unavailable: the session's workflow state could not be read ` +
      `(${String(error)}), so this cannot be proven not to be a planning session — ` +
      "retry, or implement the saved plan with `perk impl <N>` in a fresh session."
    );
  }
  if (stage === undefined || !PLANNING_STAGES.has(stage)) return null;
  return (
    `${door} is unavailable in a planning session (stage ${stage}): a planning session can ` +
    "hold two plan identities (its checkout's own binding and the just-saved plan) — " +
    "implement the saved plan with `perk impl <N>` in a fresh session instead."
  );
}

/**
 * The plan-read priming seed for a fresh implement session. The in-session twin of
 * `perk/run/launch.py`'s `_implement_prompt`: carry the plan FORWARD (read it from its canonical
 * source), never summarize it — the plan is the only artifact that crosses the boundary.
 *
 * The wording lives in the canonical template `prompts/stages/implement.md`, rendered by the shared
 * seam (contracts.md §8.31); branching stays in code — only the `read_cmd` var differs. This warm
 * handoff is now byte-identical to the cold/worker primer, so it carries the same "Progress
 * tracking:" tail (the prior shorter near-copy omission is removed).
 */
export function implementHandoffPrompt(ref: PlanRef): string {
  const readCmd = planReadInstruction(ref.provider, String(ref.pr_id), ref.url);
  return render("stages/implement.md", {
    provider: ref.provider,
    pr_id: String(ref.pr_id),
    url: ref.url,
    read_cmd: readCmd,
  });
}
