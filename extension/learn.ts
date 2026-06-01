// P1.T5b — the warm `/learn` door (turn-5 §7, D4). Thin and TS-only: it clears the `pending-learn`
// semaphore, closing the land→learn cycle so the worktree is releasable. No GitHub write, no Python
// worker this phase (the agentic capture + a `perk:learn` label/issue is Phase 2). Never throws.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { clearMarker, hasMarker, PENDING_LEARN } from "./cache.ts";

export interface LearnDetails {
  ok: boolean;
  was_pending: boolean;
}

export interface LearnResult {
  content: { type: "text"; text: string }[];
  details: LearnDetails;
  terminate?: boolean;
}

/** Clear `pending-learn` (idempotent — a no-op if it was not set). Reports whether it was set. */
export function learnDone(ctx: ExtensionContext): LearnResult {
  const wasPending = hasMarker(ctx.cwd, PENDING_LEARN);
  clearMarker(ctx.cwd, PENDING_LEARN);
  const text = wasPending
    ? "Cleared pending-learn — the worktree is releasable."
    : "No pending-learn set — nothing to clear.";
  return {
    content: [{ type: "text", text }],
    details: { ok: true, was_pending: wasPending },
    terminate: true,
  };
}

const TOOL_GUIDELINES = [
  "Call learn after a plan has landed and you have captured its learnings; it clears pending-learn so the worktree can be released.",
];

/** Register the warm door: the `learn` terminating tool + the `/learn` command twin. */
export function registerLearn(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "learn",
    label: "Finish learn",
    description:
      "Clear the pending-learn semaphore after capturing learnings from a landed plan, releasing " +
      "the worktree. Terminating: ends the turn.",
    promptSnippet: "Clear pending-learn to release the worktree (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      return learnDone(ctx);
    },
  });

  pi.registerCommand("learn", {
    description: "Clear pending-learn to release the worktree (land → learn).",
    handler: async (_args, ctx) => {
      const result = learnDone(ctx);
      if (ctx.hasUI) ctx.ui.notify(result.content[0]?.text ?? "learn done", "info");
    },
  });
}
