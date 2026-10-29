// The binding's Durable task definitions and their registration
// (docs/design/pi-durable-v2-foundations.md §7 the step task and task ownership, §10 the
// manifest's definitions).
//
// Invariants:
// - `perk.v2.step` is `operate()` with no input, run from the step task's own commit, which also
//   completes the task. A refusal or fault propagates out of that commit: it rolls back and Durable
//   faults the task.
// - Step and continuation tasks are conversation-owned, `background: true`, on the execution
//   conversation, so no abort cascade from a worker conversation reaches them.

import {
  type ConversationId,
  defineExtension,
  defineTask,
  type Extension,
  type Task,
  type TaskId,
  type Tx,
} from "@earendil-works/pi-durable";
import {
  CONTINUATION_TASK_NAME,
  CONTINUATION_TASK_VERSION,
  ContinuationTask,
} from "./continuation.ts";
import { V2_DOCUMENTS } from "./documents.ts";
import { type BindingDeps, operateInTx } from "./operate.ts";

export const STEP_TASK_NAME = "perk.v2.step";
export const STEP_TASK_VERSION = 1;
export const BINDING_EXTENSION_NAME = "perk.v2.binding";

export type StepTask = Task<null, { phase: "run" }, null, object>;

/** The step task over the host's dependencies. */
export function defineStepTask(deps: BindingDeps): StepTask {
  return defineTask<null, { phase: "run" }, null>({
    name: STEP_TASK_NAME,
    version: STEP_TASK_VERSION,
    initial: () => ({ phase: "run" }),
    phases: {
      run: async (_task, runtime, context) => {
        await runtime.commit(async (tx) => {
          await operateInTx(tx, undefined, deps, runtime.conversationId);
          return { status: "terminal", outcome: { status: "completed", result: null } };
        }, context);
      },
    },
    abort: async (_task, runtime, context) => {
      await runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), context);
    },
  });
}

/** Create a step task on the execution conversation (conversation-owned, background). */
export function createStepTask(
  tx: Tx,
  step: StepTask,
  executionConversationId: ConversationId,
): Promise<TaskId<null>> {
  return tx.createTask(step, null, {
    ownership: { kind: "conversation" },
    conversationId: executionConversationId,
    background: true,
  });
}

/** The binding's extension (the step and continuation tasks) and its step task. */
export function bindingExtension(deps: BindingDeps): { extension: Extension; step: StepTask } {
  const step = defineStepTask(deps);
  return {
    extension: defineExtension({ name: BINDING_EXTENSION_NAME, tasks: [step, ContinuationTask] }),
    step,
  };
}

/**
 * Every binding-owned definition and its version — the ten v2 documents and the two tasks — for the
 * execution manifest's `definitions`. A launcher owner adds its own task definition.
 */
export function bindingDefinitions(): Readonly<Record<string, number>> {
  const definitions: Record<string, number> = {};
  for (const token of V2_DOCUMENTS) definitions[token.definition.kind] = token.definition.version;
  definitions[STEP_TASK_NAME] = STEP_TASK_VERSION;
  definitions[CONTINUATION_TASK_NAME] = CONTINUATION_TASK_VERSION;
  return definitions;
}
