// The continuation task (docs/design/pi-durable-v2-foundations.md §7 task ownership, §12): the one
// conversation-owned, background task a reply creates to carry its decision forward.
//
// Invariants:
// - It only completes. Completion is already derived: an existing continuation is the kernel's
//   terminal state, so the task carries no further work and records nothing.
// - Its own module, so the commit operation and the task definitions both import it without a cycle.

import { defineTask } from "@earendil-works/pi-durable";

export const CONTINUATION_TASK_NAME = "perk.v2.continuation";
export const CONTINUATION_TASK_VERSION = 1;

export type ContinuationInput = { readonly decisionId: string };

export const ContinuationTask = defineTask<ContinuationInput, { phase: "run" }, null>({
  name: CONTINUATION_TASK_NAME,
  version: CONTINUATION_TASK_VERSION,
  initial: () => ({ phase: "run" }),
  phases: {
    run: async (_task, runtime, context) => {
      await runtime.commit(
        () => ({ status: "terminal", outcome: { status: "completed", result: null } }),
        context,
      );
    },
  },
  abort: async (_task, runtime, context) => {
    await runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), context);
  },
});
