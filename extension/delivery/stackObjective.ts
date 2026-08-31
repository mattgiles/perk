// The stack surfaces' shared command vocabulary: the objective-argument parse and the
// no-objective refusal prose. Stack-OWNED (not substrate): these are binding concerns — how a
// stack slash-command reads its argument and what its soft-fail says — so they live with the
// delivery feature family, imported by the status adapter and the mutating stack doors alike.
// The state-resolution primitive they pair with (`resolveStackObjective`) stays in
// `substrate/workflowState.ts` — that half IS workflow-state read-back. Pi-free.

/** The shared no-objective refusal every stack surface emits (soft fail / warning text). */
export const STACK_NO_OBJECTIVE_MESSAGE =
  "no objective given and none active or linked — pass the objective explicitly.";

/** The first command-arg token as the explicit objective (leading `#` stripped); null if none. */
export function parseStackObjectiveArg(args: string): string | null {
  const token = args.trim().split(/\s+/)[0]?.replace(/^#/, "") ?? "";
  return token.length > 0 ? token : null;
}
