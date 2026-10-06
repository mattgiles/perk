// A Pi `tool_call` refusal hook over a pure, caller-owned decision (the registration half of a
// tool-call policy; the decision stays with its owner and takes no Pi vocabulary).
//
// The hook runs before a tool executes; a non-null reason blocks the call, and Pi returns the
// reason to the model as the call's error result. It never sets `terminate`: a refusal is an
// ordinary failed tool call the model recovers from, not the end of the turn.

import type { ExtensionFactory } from "@earendil-works/pi-coding-agent";

/** The refusal decision: the reason to block `toolName` with `input`, or `null` to let it run. */
export type ToolCallRefusal = (toolName: string, input: Record<string, unknown>) => string | null;

/** An extension factory registering one `tool_call` hook that blocks on `refusalFor`'s reason. */
export function toolCallRefusalHook(refusalFor: ToolCallRefusal): ExtensionFactory {
  return (pi) => {
    pi.on("tool_call", (event) => {
      const reason = refusalFor(event.toolName, event.input as Record<string, unknown>);
      return reason === null ? undefined : { block: true, reason };
    });
  };
}
