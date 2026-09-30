// The report child's task-restore hooks (contracts.md §8.3 "Runner task restore"). Report children
// may compact; compaction evicts the inline task the lane was given; these hooks put it back,
// hold `structured_output` until it is live again, and go inert once a report is accepted. The
// policy — the verdict order, the bounds, the restored text and the reasons — is pure and lives in
// `substrate/childTaskRestore.ts`; this module only adapts it to Pi's event shapes.
//
// Three hooks, all inert without a latched read-only floor (parents and the floor-less foreground
// writers keep Pi's ordinary compaction untouched):
// - `tool_result` latches acceptance: an executed `structured_output` whose result is not an
//   error. pi-subagents throws on a schema rejection, so a rejection arrives as an error result
//   and does not latch; a blocked call never executes, so it never reaches this hook.
// - `session_compact` (every reason) queues the restore as a steer. During turn preparation Pi
//   re-polls steering after compaction, so the restore normally reaches the very next request; in
//   the post-run check a queued steer makes Pi `agent.continue()` — desired for a lane that has not
//   reported, and never reached after acceptance because the latch short-circuits the verdict.
// - `tool_call` on `structured_output` is the backstop and the re-delivery point for a restore
//   that was delayed, omitted by a context edit, or never sent (a reload onto an already-compacted
//   branch fires no `session_compact`): it queues when nothing is in flight and blocks while the
//   task is not live. A blocked call captured nothing; the block reason says so to the model.
//
// Fail posture: report integrity is the safety property, so a failed branch/projection read in the
// gate blocks with the held reason (fail closed); in the other two hooks it is only logged.
// Registered after the read-only gate, whose `tool_call` hook therefore stays first.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  applyQueued,
  createRestoreState,
  firstUserPrompt,
  latestCompactionId,
  type RestoreVerdict,
  restoreDelivered,
  restoreVerdict,
  structuredOutputHoldReason,
  TASK_RESTORE_TYPE,
} from "../../substrate/childTaskRestore.ts";
import { activeContextMessages, contextCarriesMarker } from "./contextEvidence.ts";

const STRUCTURED_OUTPUT = "structured_output";

/**
 * Register the three hooks over one per-activation restore state. `hasFloor` is the composition
 * root's latched floor supplier — the same one the read-only gate takes.
 */
export function registerChildTaskRestore(pi: ExtensionAPI, hasFloor: () => boolean): void {
  const state = createRestoreState();
  let refusalLogged = false;

  // One evaluation over the selected branch: the full-branch readers for the prompt/compaction/
  // delivery facts, and Pi's own projection (typed evidence only — a summary quoting the prompt
  // never counts) for liveness.
  const evaluate = (
    ctx: ExtensionContext,
  ): { verdict: RestoreVerdict; compactionId: string | null } => {
    const branch = ctx.sessionManager.getBranch();
    const prompt = firstUserPrompt(branch);
    const compactionId = latestCompactionId(branch);
    const taskLive =
      prompt !== null &&
      contextCarriesMarker(activeContextMessages(ctx), {
        customType: TASK_RESTORE_TYPE,
        marker: prompt,
      });
    const verdict = restoreVerdict({
      state,
      prompt,
      taskLive,
      compactionId,
      delivered: restoreDelivered(branch),
    });
    return { verdict, compactionId };
  };

  // A visible steer in the child's transcript, not a hidden injection. Idle, Pi appends it at
  // once; mid-run it is queued and delivered before the next request.
  const queue = (text: string, compactionId: string | null): void => {
    pi.sendMessage(
      { customType: TASK_RESTORE_TYPE, content: [{ type: "text", text }], display: true },
      { deliverAs: "steer" },
    );
    applyQueued(state, compactionId);
  };

  pi.on("tool_result", async (event) => {
    try {
      if (!hasFloor()) return;
      if (event.toolName === STRUCTURED_OUTPUT && event.isError !== true) state.accepted = true;
    } catch (error) {
      console.error(`perk: task-restore acceptance hook failed — ${String(error)}`);
    }
    return;
  });

  pi.on("session_compact", async (_event, ctx) => {
    try {
      if (!hasFloor()) return;
      const { verdict, compactionId } = evaluate(ctx);
      if (verdict.kind === "queue") {
        queue(verdict.text, compactionId);
      } else if (verdict.kind === "refuse" && !refusalLogged) {
        // The gate carries the model-facing consequence; this is the operator's one line.
        refusalLogged = true;
        console.error(`perk: task restore refused after compaction — ${verdict.reason}`);
      }
    } catch (error) {
      console.error(`perk: task-restore compaction hook failed — ${String(error)}`);
    }
  });

  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName !== STRUCTURED_OUTPUT) return;
    try {
      if (!hasFloor()) return;
      const { verdict, compactionId } = evaluate(ctx);
      if (verdict.kind === "allow") return;
      if (verdict.kind === "queue") queue(verdict.text, compactionId);
      return { block: true, reason: verdict.reason };
    } catch (error) {
      console.error(`perk: task-restore gate failed; holding structured_output — ${String(error)}`);
      return { block: true, reason: structuredOutputHoldReason({ kind: "held" }) };
    }
  });
}
