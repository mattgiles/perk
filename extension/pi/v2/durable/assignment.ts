// The native assignment task (docs/design/pi-durable-v2-foundations.md §12 the native assignment):
// the one task an attempt launches, which creates and drives the attempt's worker conversation,
// plus the launcher and the assignment's composed work.
//
// Invariants:
// - The task input is only `{attemptId}`; every other fact comes from records — the assignment, its
//   recorded capability set, role and subject, and the observed manifest digest. The capability set
//   binds at admission (P7): the host's current policy is never consulted.
// - Every capability resolves before the worker exists, failing closed: the model through
//   `Models.getModel`, each extension through the registry, and each tool to exactly one tool of the
//   selected extensions. A failure is a repair ending, with no worker conversation.
// - Three phases, each ending in one commit: `prepare` creates the task-owned worker conversation,
//   configures it explicitly and maps it under the attempt id; `submit` submits under the `submit`
//   op id as Durable's request id — the Perk identity is bound in Durable's own admission commit —
//   then maps the submission and owns §4's `{conversationId}` comparison in its next commit; `settle`
//   waits for the worker and commits the attempt ending. A crash reruns the phase from its
//   committed checkpoint, and Durable deduplicates the resubmission by request id.
// - The task always completes with a typed `AttemptEnding`, which explains and never authorizes:
//   acceptance happens only in the report tool's reconcile commit.

import type { Context } from "@earendil-works/chord";
import type { Models } from "@earendil-works/pi-ai";
import {
  type ConversationId,
  configure,
  defineTask,
  type Extension,
  type HarnessOptions,
  type ModelRef,
  type NextTaskState,
  type RegistrySnapshot,
  type Task,
  type TaskRuntime,
  type ToolRegistration,
  ToolResultEntry,
  type Tx,
} from "@earendil-works/pi-durable";
import { isWellFormedText, sha256Hex } from "../kernel/canonical.ts";
import type { CapabilitySet } from "../kernel/capability.ts";
import { fixtureWorkerPrompt } from "../kernel/fixture.ts";
import { submitOpId } from "../kernel/identity.ts";
import { indexRecords, KernelInvariantError, manifestDigestFor } from "../kernel/records.ts";
import { isRefusalReason, type Refusal, type RefusalReason } from "../kernel/refusal.ts";
import { type AttemptEnding, REFUSAL_DIAGNOSTIC_PREFIX, type RepairCause } from "./ending.ts";
import type { AttemptLauncher, BindingDeps } from "./operate.ts";
import { type DurableMapRow, loadRecords, readRecords } from "./records.ts";
import { snapshotEnvFactory, WORKSPACE_ROOT } from "./snapshotEnv.ts";
import { type SnapshotVerifier, workerExtension } from "./workerTools.ts";

export type { SnapshotVerification, SnapshotVerifier, VerifyPoint } from "./workerTools.ts";

/** The model catalog a worker's model resolves through. */
export type WorkerModels = Models;

export const FIXTURE_REPORT_TASK_NAME = "perk.v2.fixture-report";
export const FIXTURE_REPORT_TASK_VERSION = 1;

export type FixtureReportInput = { readonly attemptId: string };

export type FixtureReportState =
  | { readonly phase: "prepare" }
  | { readonly phase: "submit"; readonly conversationId: ConversationId }
  | { readonly phase: "settle"; readonly conversationId: ConversationId };

export type FixtureReportTask = Task<FixtureReportInput, FixtureReportState, AttemptEnding, object>;

type Runtime = TaskRuntime<FixtureReportInput, FixtureReportState, AttemptEnding, object>;

/** How many transcript entries `settle` reads per page. */
const ENTRY_PAGE = 256;

export type FixtureReportTaskOptions = {
  readonly verify: SnapshotVerifier;
  readonly renderInstructions: () => string;
};

/** The facts one attempt's work reads from records. */
type AttemptFacts = {
  readonly attemptId: string;
  readonly role: string;
  readonly tree: string;
  readonly manifestDigest: string;
  readonly capabilitySet: CapabilitySet;
};

async function attemptFacts(runtime: Runtime, attemptId: string): Promise<AttemptFacts> {
  const index = indexRecords((await readRecords(runtime)).records);
  const attempt = index.attempts.get(attemptId);
  const assignment =
    attempt === undefined ? undefined : index.assignments.get(attempt.assignmentId);
  const tree = assignment?.subject.digest;
  const manifestDigest = tree === undefined ? null : manifestDigestFor(index, tree);
  if (assignment === undefined || tree === undefined || manifestDigest === null) {
    throw new KernelInvariantError(
      `${attemptId}: launched without an attempt, assignment or observed manifest digest`,
    );
  }
  return {
    attemptId,
    role: assignment.role,
    tree,
    manifestDigest,
    capabilitySet: assignment.capabilitySet,
  };
}

function terminal(ending: AttemptEnding): NextTaskState<FixtureReportState, AttemptEnding> {
  return { status: "terminal", outcome: { status: "completed", result: ending } };
}

function repair(cause: RepairCause, detail: string): AttemptEnding {
  return { end: "repair", cause, detail };
}

async function end(runtime: Runtime, ending: AttemptEnding, context: Context): Promise<void> {
  await runtime.commit(() => terminal(ending), context);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The rendered instructions, or why they do not render: the renderer must not throw, must return a
 * non-empty well-formed string, and its sha256 must be the recorded `instructionsDigest`.
 */
export function renderInstructionsChecked(
  render: () => string,
  instructionsDigest: string,
): { readonly ok: true; readonly text: string } | { readonly ok: false; readonly detail: string } {
  let text: unknown;
  try {
    text = render();
  } catch (error) {
    return { ok: false, detail: `the instructions renderer threw: ${errorMessage(error)}` };
  }
  if (typeof text !== "string" || text === "" || !isWellFormedText(text)) {
    return { ok: false, detail: "the instructions renderer returned no well-formed text" };
  }
  const digest = sha256Hex(text);
  if (digest !== instructionsDigest) {
    return {
      ok: false,
      detail: `the rendered instructions digest ${digest} is not the recorded ${instructionsDigest}`,
    };
  }
  return { ok: true, text };
}

export type ResolvedCapabilities = {
  readonly model: ModelRef;
  readonly extensions: readonly Extension[];
  readonly tools: readonly ToolRegistration[];
};

/**
 * Every capability of `capabilitySet`, resolved: the model through `models`, each extension
 * through `registry`, and each tool to exactly one tool of the selected extensions. The first
 * failure names what is missing.
 */
export function resolveCapabilities(
  capabilitySet: CapabilitySet,
  models: Pick<Models, "getModel">,
  registry: Pick<RegistrySnapshot, "extension">,
):
  | ({ readonly ok: true } & ResolvedCapabilities)
  | { readonly ok: false; readonly detail: string } {
  const { provider, modelId } = capabilitySet.model;
  if (models.getModel(provider, modelId) === undefined) {
    return { ok: false, detail: `model ${provider}/${modelId} is not available` };
  }
  const extensions: Extension[] = [];
  for (const name of capabilitySet.extensions) {
    const extension = registry.extension(name);
    if (extension === undefined) {
      return { ok: false, detail: `extension ${name} is not installed` };
    }
    extensions.push(extension);
  }
  const tools: ToolRegistration[] = [];
  for (const name of capabilitySet.tools) {
    const matches = extensions.flatMap((extension) =>
      (extension.tools ?? []).filter((tool) => tool.name === name),
    );
    const [tool] = matches;
    if (tool === undefined || matches.length > 1) {
      return {
        ok: false,
        detail: `tool ${name} is provided by ${matches.length} of the selected extensions, not exactly one`,
      };
    }
    tools.push(tool);
  }
  return { ok: true, model: { provider, modelId }, extensions, tools };
}

export type SubmitComparison =
  | { readonly kind: "record" }
  | { readonly kind: "replayed" }
  | { readonly kind: "refused"; readonly refusal: Refusal };

function conflict(detail: string): SubmitComparison {
  return { kind: "refused", refusal: { reason: "duplicate_conflict", detail } };
}

/**
 * §4's `submit` comparison over the durable map: the `<attempt-id>` row must name the worker
 * conversation, and the `<attempt-id>/submit` row may be absent (`record`) or name the submission
 * (`replayed`); anything else is `duplicate_conflict`. Pure.
 */
export function compareSubmit(
  durableMap: ReadonlyMap<string, DurableMapRow>,
  attemptId: string,
  conversationId: number,
  submissionId: number,
): SubmitComparison {
  const worker = durableMap.get(attemptId);
  if (worker?.durableKind !== "conversation" || worker.durableId !== conversationId) {
    return conflict(`${attemptId} does not map to the worker conversation ${conversationId}`);
  }
  const submitted = durableMap.get(submitOpId(attemptId));
  if (submitted === undefined) return { kind: "record" };
  if (submitted.durableKind === "submission" && submitted.durableId === submissionId) {
    return { kind: "replayed" };
  }
  return conflict(`${submitOpId(attemptId)} maps to another ${submitted.durableKind}`);
}

/** Every report refusal diagnostic in the worker transcript, oldest first. Table reads only. */
async function transcriptRefusals(
  tx: Tx,
  conversationId: ConversationId,
): Promise<{ readonly reason: RefusalReason; readonly message: string }[]> {
  const refusals: { reason: RefusalReason; message: string }[] = [];
  let page = await tx.scanEntries({ conversationId, order: "ascending" }, ENTRY_PAGE);
  for (;;) {
    for (const entry of page.items) {
      if (!ToolResultEntry.is(entry)) continue;
      for (const diagnostic of entry.data.diagnostics) {
        const code = diagnostic.code;
        if (code === undefined || !code.startsWith(REFUSAL_DIAGNOSTIC_PREFIX)) continue;
        const reason = code.slice(REFUSAL_DIAGNOSTIC_PREFIX.length);
        if (isRefusalReason(reason)) refusals.push({ reason, message: diagnostic.message });
      }
    }
    if (page.next === undefined) return refusals;
    page = await tx.scanEntries({ conversationId, order: "ascending" }, ENTRY_PAGE, page.next);
  }
}

/** The native assignment task over the snapshot verifier and the instructions renderer. */
export function defineFixtureReportTask(options: FixtureReportTaskOptions): FixtureReportTask {
  return defineTask<FixtureReportInput, FixtureReportState, AttemptEnding>({
    name: FIXTURE_REPORT_TASK_NAME,
    version: FIXTURE_REPORT_TASK_VERSION,
    initial: () => ({ phase: "prepare" }),
    phases: {
      prepare: async (task, runtime, context) => {
        const facts = await attemptFacts(runtime, task.input.attemptId);
        const instructions = renderInstructionsChecked(
          options.renderInstructions,
          facts.capabilitySet.instructionsDigest,
        );
        if (!instructions.ok) {
          return end(runtime, repair("instructions_unrenderable", instructions.detail), context);
        }
        const resolved = resolveCapabilities(facts.capabilitySet, runtime.models, runtime.registry);
        if (!resolved.ok) {
          return end(runtime, repair("capability_missing", resolved.detail), context);
        }
        const verification = await options.verify(
          facts.tree,
          facts.manifestDigest,
          "attempt-start",
        );
        if (!verification.ok) {
          return end(runtime, repair("snapshot_tampered", verification.problem), context);
        }
        await runtime.commit(async (tx) => {
          const set = await loadRecords(tx);
          const conversation = await tx.createConversation({
            ownership: { kind: "task", taskId: runtime.taskId },
          });
          await configure(tx, conversation.id, {
            model: resolved.model,
            extensions: resolved.extensions,
            tools: resolved.tools,
            modelTools: resolved.tools,
            instructions: instructions.text,
            cwd: WORKSPACE_ROOT,
          });
          await set.writeRow(facts.attemptId, {
            durableKind: "conversation",
            durableId: conversation.id,
          });
          return {
            status: "running",
            checkpoint: { phase: "submit", conversationId: conversation.id },
          };
        }, context);
      },
      submit: async (task, runtime, context) => {
        const { conversationId } = task.state.checkpoint;
        const facts = await attemptFacts(runtime, task.input.attemptId);
        const handle = await runtime.conversation(conversationId, context);
        if (handle === undefined) {
          throw new KernelInvariantError(`worker conversation ${conversationId} is absent`);
        }
        const requestId = submitOpId(facts.attemptId);
        const submission = await handle.submit(
          { type: "input", content: fixtureWorkerPrompt(facts.role, facts.tree), requestId },
          context,
        );
        await runtime.commit(async (tx) => {
          const record = await tx.submissionByRequest(conversationId, requestId);
          if (record?.id !== submission.id) {
            throw new KernelInvariantError(
              `${requestId}: the admitted submission is not committed`,
            );
          }
          const set = await loadRecords(tx);
          const comparison = compareSubmit(
            set.durableMap,
            facts.attemptId,
            conversationId,
            submission.id,
          );
          if (comparison.kind === "refused") {
            return terminal(repair("duplicate_conflict", comparison.refusal.detail));
          }
          if (comparison.kind === "record") {
            await set.writeRow(requestId, { durableKind: "submission", durableId: submission.id });
          }
          return { status: "running", checkpoint: { phase: "settle", conversationId } };
        }, context);
      },
      settle: async (task, runtime, context) => {
        const { conversationId } = task.state.checkpoint;
        const facts = await attemptFacts(runtime, task.input.attemptId);
        const handle = await runtime.conversation(conversationId, context);
        if (handle === undefined) {
          throw new KernelInvariantError(`worker conversation ${conversationId} is absent`);
        }
        await handle.waitForIdle(context);
        const verification = await options.verify(facts.tree, facts.manifestDigest, "settle");
        await runtime.commit(async (tx) => {
          const requestId = submitOpId(facts.attemptId);
          const submission = await tx.submissionByRequest(conversationId, requestId);
          if (submission === undefined) {
            throw new KernelInvariantError(`${requestId}: the mapped submission is absent`);
          }
          const refusals = await transcriptRefusals(tx, conversationId);
          const index = indexRecords((await loadRecords(tx)).records);
          const outcome = index.outcomesByAttempt.get(facts.attemptId);
          if (outcome !== undefined) return terminal({ end: "accepted", outcomeId: outcome.opId });
          const tampered = refusals.find((refusal) => refusal.reason === "snapshot_tampered");
          if (tampered !== undefined) {
            return terminal(repair("snapshot_tampered", tampered.message));
          }
          if (!verification.ok) return terminal(repair("snapshot_tampered", verification.problem));
          return terminal({
            end: "incomplete",
            submission: submission.status,
            reason: submission.status === "unanswered" ? submission.reason : null,
            refusal: refusals.at(-1)?.reason ?? null,
          });
        }, context);
      },
    },
    abort: async (_task, runtime, context) => {
      await runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), context);
    },
  });
}

/** The launcher: the native task, conversation-owned and background on the execution conversation. */
export function nativeLauncher(task: FixtureReportTask): AttemptLauncher {
  return (tx, launch) =>
    tx.createTask(
      task,
      { attemptId: launch.attempt.attemptId },
      {
        ownership: { kind: "conversation" },
        conversationId: launch.executionConversationId,
        background: true,
      },
    );
}

export type NativeAssignmentOptions = {
  /** The composed binding dependencies; a thunk, because the launcher is itself one of them. */
  readonly deps: () => BindingDeps;
  readonly models: WorkerModels;
  readonly verify: SnapshotVerifier;
  /** The snapshot directory of a subject tree. */
  readonly snapshotRoot: (tree: string) => string;
  readonly renderInstructions: () => string;
};

/** The native assignment's work; structurally the host's `AssignmentWork`. */
export type NativeAssignment = {
  readonly launcher: AttemptLauncher;
  readonly extension: Extension;
  readonly models: WorkerModels;
  readonly env: NonNullable<HarnessOptions["env"]>;
};

export function nativeAssignment(options: NativeAssignmentOptions): NativeAssignment {
  const task = defineFixtureReportTask({
    verify: options.verify,
    renderInstructions: options.renderInstructions,
  });
  return {
    launcher: nativeLauncher(task),
    extension: workerExtension({ deps: options.deps, verify: options.verify }, [task]),
    models: options.models,
    env: snapshotEnvFactory({ snapshotRoot: options.snapshotRoot }),
  };
}
