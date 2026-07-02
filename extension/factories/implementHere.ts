// The sanctioned "implement here" exit from plan authoring (contracts.md §8.23): the read-only
// gate comes off WITHOUT saving to the issue backend, and the model is instructed to implement
// the reviewed plan draft directly in the current session/checkout — edits only, git gestures
// stay with the human. Human-only by construction: the two surfaces are the first-party review's
// 4th verdict (planReview.ts) and the `/implement-here` command registered here — no model tool
// exists, so the model can never choose to skip the backend on its own (the /btw posture).
//
// The seam, the guidance builder, and the command live in ONE module with no cycles:
// planReview.ts imports from here, never the reverse. `implementHereExit` is the
// gate-exit-WITHOUT-save sibling of `approvalSave`'s D1a arm — the review door composes the gate
// through this seam, never owns it (Invariant 1).
//
// Deliberately OUTSIDE the PR lifecycle: no issue, no plan-ref, no branch — /submit, /address,
// and /land all key off `cache.plan-ref` and stay inapplicable. The plan-draft artifact is left
// untouched, so /plan-save can still create the canonical issue afterwards.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { report } from "../surfaces/report.ts";
import { readNodeClaim } from "./objectivePlan.ts";

/** The core instruction text (exported for the offline content pins). */
export const IMPLEMENT_HERE_GUIDANCE = `The human chose IMPLEMENT HERE: implement the reviewed plan directly in this session — no plan issue was created and none will be.

- The read-only gate is off: make the plan's edits now, in this checkout.
- Run the checks the plan calls for before declaring done.
- Do NOT commit, branch, or push unless the user explicitly asks — git gestures stay with the human.
- perk's lifecycle doors (/submit, /land, /learn) do not apply — there is no plan issue or plan-ref.
- The plan draft artifact is untouched: /plan-save can still create the canonical issue later.`;

/**
 * Build the implement-here instruction text. When `editedPlan` is set (review-path human edits
 * were written back to the draft pre-verdict), the final reviewed bytes are inlined so the model
 * implements THOSE, not its stale in-context version. Always appends the Mechanism-B skill-binding
 * suffix for `command:implement-here` (a `[[bindings]]` hook; delivers nothing by default).
 */
export function implementHereGuidance(cwd: string, opts: { editedPlan?: string }): string {
  const edited =
    opts.editedPlan === undefined
      ? ""
      : `\n\nThe human edited the plan during review; implement THESE final bytes:\n\n${opts.editedPlan}`;
  return `${IMPLEMENT_HERE_GUIDANCE}${edited}${bindingSuffix(cwd, "command:implement-here")}`;
}

/**
 * The gate-exit-WITHOUT-save seam — the no-save sibling of `approvalSave`'s D1a arm. If the gate
 * is active, exit it and report one info line; otherwise a no-op. Keeps Invariant 1: callers
 * (the review door's implement-here verdict, the `/implement-here` command) compose the gate
 * through this seam, never own it.
 */
export function implementHereExit(
  ctx: ExtensionContext,
  gating: ToolGating,
): { gateExited: boolean } {
  if (!gating.isActive()) return { gateExited: false };
  gating.exit(ctx);
  report(
    ctx,
    "implement-here",
    "info",
    "plan mode off — implementing here; no issue saved (draft intact; /plan-save can still create it)",
  );
  return { gateExited: true };
}

/**
 * Register `/implement-here` — the universal manual gesture for the no-save exit (and the ONLY
 * reachable surface when the plannotator review is selected, whose browser envelope returns only
 * approve/deny). Handler order: the objective-node carve-out (a node-linked plan must save — the
 * node advance and backlink depend on it) → the gate-off warning (the command's meaning is
 * exiting plan mode without saving) → gate exit + guidance injection (the submit.ts routing:
 * idle → an immediate turn; streaming → a followUp).
 */
export function registerImplementHere(pi: ExtensionAPI, gating: ToolGating): void {
  registerPerkCommand(pi, "implement-here", {
    description:
      "Exit plan mode WITHOUT saving an issue and implement the current plan draft in this " +
      "session (the human-owned lightweight path).",
    handler: async (_args, ctx) => {
      // 1. Objective-node planning sessions must save: an implement-here would strand the node in
      //    `planning` (the claim is only cleared by a node-linked save or a non-planning
      //    transition). Gate untouched, nothing injected.
      if (readNodeClaim(ctx) !== null) {
        report(
          ctx,
          "implement-here",
          "warning",
          "this is an objective-node planning session — a node-linked plan must be saved " +
            "(the node advance and backlink depend on it). Use plan_review / /plan-save instead.",
        );
        return;
      }
      // 2. Nothing to exit: the command's meaning is *exiting plan mode without saving*.
      if (!gating.isActive()) {
        report(
          ctx,
          "implement-here",
          "warning",
          "not in plan mode — nothing to exit; just ask the model to implement.",
        );
        return;
      }
      // 3. Gate off → instruct the model. No inlined plan: the model authored the draft in its
      //    own context (the review-path edited-bytes inlining lives in planReview.ts).
      implementHereExit(ctx, gating);
      const message = implementHereGuidance(ctx.cwd, {});
      if (ctx.isIdle()) {
        pi.sendUserMessage(message);
      } else {
        pi.sendUserMessage(message, { deliverAs: "followUp" });
      }
    },
  });
}
