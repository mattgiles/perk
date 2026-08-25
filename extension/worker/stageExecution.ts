// The confined stage-execution seam (`runStage`) — the headless stage-drive primitive.
//
// Drives ONE read-write stage (`implement`/`address`) end-to-end on an already-prepared worktree,
// running the SAME `@mgiles/perk` extension package, with a locked resource set, auto-compaction and
// auto-retry off, and a budget/timeout watchdog. It seeds the stage's initial prompt, lets the
// model work (calling perk's real tools), detects the stage's terminal signal, and returns a
// structured `RunOutcome`. This implements the contract locked in
// `docs/design/headless-worker.md` §B — the event-stream substrate and the e2e
// harness consume.
//
// Scope here is the in-process drive primitive only. Positioning (worktree create, handoff/plan-ref
// /plan-body materialization, `run_id` mint) is the cold-door/runner's job and is a PREPARED-
// WORKTREE input (audit Gap 7): the worker inherits `PERK_RUN_ID` from the env and never re-mints.
//
// Budget semantics: `budget.tokens` counts FRESH WORK only — assistant `input + output` per
// `turn_end`. Cache reads/writes and the provider `reasoning` breakdown (a subset of `output` in
// pi-ai's normalization) are excluded by design; see the adapter's `applyEvent`.
//
// CONFINEMENT: this seam's caller surface carries no SDK shapes. Every `@earendil-works` import
// AND the session-drive mechanics (construction, raw events, prompt/abort, token accumulation)
// live in the private `./sdkAdapter.ts` — the seam drives the session only through the adapter's
// drive-session handle, and the one opaque model input (`StageRunOptions.model`) is the
// adapter-minted nominal `WorkerModelSelection` (see the adapter header for the exact — narrow —
// opacity guarantee: an import-edge ban plus nominal minting, nothing stronger). `workerMain.ts`
// imports ONLY this seam (guard Rule F) and carries zero SDK imports.

import { appendFileSync } from "node:fs";
import { env } from "node:process";
import { ensureRunScratch, type PlanRef, readPlanRef, runEventsPath } from "../substrate/cache.ts";
import { capForModel } from "../substrate/modelVisible.ts";
import { planReadInstruction, render } from "../substrate/prompts.ts";
import { captureSessionPointer } from "../substrate/sessionPointers.ts";
import { rebuildWorkflowState } from "../substrate/workflowState.ts";
import {
  applyEvent,
  createDriveSession,
  type DriveCounters,
  type DriveEvent,
  type DriveRuntimeLike,
  type DriveSessionHandle,
  defaultCreateRuntime,
  detailsOf,
  freshCounters,
  resolveAuth,
  type WorkerModelSelection,
} from "./sdkAdapter.ts";

export type {
  DriveEvent,
  DriveRuntimeLike,
  DriveSessionLike,
  ResolvedWorkerModel,
  WorkerModelSelection,
} from "./sdkAdapter.ts";
// Re-exports so `workerMain.ts` (and the harness tier) import ONLY the seam.
export { resolveWorkerModel } from "./sdkAdapter.ts";

// --- contract types (additive-stable; §B of docs/design/headless-worker.md) ---------------------

/** The two read-write stages with `doors.cold_remote: true` (shared/registry.yaml). */
export type DriveStage = "implement" | "address";

/** Terminal run status (audit §B outcome shape). */
export type RunStatus = "completed" | "failed" | "aborted" | "budget_exhausted";

/** The first-of terminal signal that ended the drive (audit §B). */
export type TerminalSignal =
  | "submit_tool"
  | "address_resolved"
  | "agent_idle_incomplete"
  | "budget"
  | "external_abort"
  | "model_error";

/** The budget/timeout watchdog inputs (Gap 2). */
export interface DriveBudget {
  maxTurns: number;
  maxTokens: number;
  wallClockMs: number;
}

/**
 * The structured run outcome (audit §B). **Additive-stable**: later fields may be added; existing
 * fields keep their meaning. Never thrown — `runStage` always resolves with one of these.
 */
export interface RunOutcome {
  run_id: string;
  stage: DriveStage;
  status: RunStatus;
  terminal_signal: TerminalSignal;
  pr: { number: number; url: string } | null;
  budget: { turns: number; tokens: number; elapsed_ms: number };
  error: { type: string; message: string; summary: string } | null;
}

// --- structured run-event stream (§8.12) ----------------------------------------------

/**
 * The structured run-event stream (contracts §8.12). A small, JSON-serializable,
 * **additive-stable** discriminated union keyed on `kind` (distinct from `DriveEvent.type`). Every
 * event carries a monotonic `seq` (0-based) and `t` (elapsed ms, same basis as
 * `RunOutcome.budget.elapsed_ms`). Future nodes may add variants/fields; existing ones keep
 * meaning — including deprecated variants that are no longer emitted (see `step_marker`).
 */
export type RunEvent =
  | { kind: "run_started"; seq: number; t: number; run_id: string; stage: DriveStage }
  // DEPRECATED — never emitted: the `[WIP:n]`/`[DONE:n]` marker protocol died with the
  // checkpoints removal. Kept for additive-stable grammar — historical `events.ndjson` files
  // may carry the variant (contracts §8.12).
  | { kind: "step_marker"; seq: number; t: number; marker: "wip" | "done"; step: number }
  | {
      kind: "tool_outcome";
      seq: number;
      t: number;
      tool: string;
      ok: boolean;
      summary: string | null;
    }
  | { kind: "run_finished"; seq: number; t: number; outcome: RunOutcome };

/** The injectable delivery seam: default = a run-scoped NDJSON file sink; tests inject an array. */
export type RunEventSink = (event: RunEvent) => void;

/** Distributive `Omit` so each `RunEvent` variant keeps its own fields when `seq`/`t` are stamped. */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
type RunEventInput = DistributiveOmit<RunEvent, "seq" | "t">;

/** Per-event free-text cap (route-don't-relay): events carry the narrative, not raw tool payloads. */
export const EVENT_SUMMARY_CAP = 2 * 1024;

export interface StageRunOptions {
  /** Absolute path to the already-positioned worktree (Gap 7). */
  worktree: string;
  stage: DriveStage;
  /** The seeded first prompt (see `initialPromptFor`). */
  initialPrompt: string;
  /**
   * The one opaque model input: an adapter-minted nominal `WorkerModelSelection` (from
   * `resolveWorkerModel`). Absent ⇒ the adapter builds a default-runtime selection and the SDK's
   * own default resolution picks the model at session creation (settings `defaultModel` → pi's
   * per-provider defaults → first available — Gap 5). Never pre-pinned here: `getAvailable()`
   * sorts alphabetically, so `[0]` is the *oldest* model of the first provider (a since-removed
   * `claude-3-5-haiku` date-pin 404'd a whole remote drive).
   */
  model?: WorkerModelSelection;
  budget: DriveBudget;
  /** External cancellation; OR'd with the budget watchdog. */
  signal?: AbortSignal;
}

/**
 * The offline seam. `createRuntime` overrides the production runtime factory so tests drive
 * synthetic sessions; `now` injects the clock for deterministic `elapsed_ms`.
 */
export interface StageRunDeps {
  createRuntime?: (opts: StageRunOptions) => Promise<DriveRuntimeLike>;
  now?: () => number;
  /** The structured run-event sink. Absent ⇒ the default run-scoped NDJSON file sink. */
  eventSink?: RunEventSink;
}

/** The natural-idle terminal classification (before watchdog/abort overrides). */
export interface TerminalVerdict {
  status: RunStatus;
  terminal_signal: TerminalSignal;
  pr: { number: number; url: string } | null;
  errorType: string | null;
  errorMessage: string | null;
}

// --- pure helpers (offline-testable) ------------------------------------------------------------

/** True when the budget watchdog should trip from the current counters. */
export function budgetTripped(counters: DriveCounters, budget: DriveBudget): boolean {
  return counters.turns >= budget.maxTurns || counters.tokens >= budget.maxTokens;
}

/**
 * Classify a natural-idle terminal from the captured state (pure). `modelError` wins (post-
 * acceptance error, §B #4); else the stage success predicate:
 *  - implement: a successful `submit` carrying a `pr` → completed/submit_tool;
 *  - address: `finalize_address` ok, `last_review_batch` appended, and the latest submit-bearing
 *    evidence is successful and not definitively unmergeable → completed/address_resolved;
 *  - otherwise the agent went idle without completing the stage → failed/agent_idle_incomplete.
 */
export function evaluateTerminal(args: {
  stage: DriveStage;
  submitDetails: Record<string, unknown> | null;
  finalizeDetails: Record<string, unknown> | null;
  lastReviewBatchPresent: boolean;
  modelError: { message: string } | null;
}): TerminalVerdict {
  if (args.modelError !== null) {
    return {
      status: "failed",
      terminal_signal: "model_error",
      pr: null,
      errorType: "model_error",
      errorMessage: args.modelError.message,
    };
  }

  if (args.stage === "implement") {
    const pr = extractPr(args.submitDetails);
    if (args.submitDetails?.ok === true && pr !== null) {
      // Completion additionally requires the submit to be mergeable: a definitively-
      // unmergeable PR (merge conflicts unresolved) is NOT done. `mergeable === true`/`null`/
      // absent all allow completion (fail-open); only a definitive `false` blocks it. On the
      // happy path the resolver follow-up turns re-submit, overwriting submitDetails with a
      // mergeable result, so the natural-idle classification then passes.
      if (args.submitDetails.mergeable === false) {
        return {
          status: "failed",
          terminal_signal: "agent_idle_incomplete",
          pr: null,
          errorType: "incomplete",
          errorMessage:
            "implement drive went idle with an unmergeable PR (merge conflicts unresolved).",
        };
      }
      return {
        status: "completed",
        terminal_signal: "submit_tool",
        pr,
        errorType: null,
        errorMessage: null,
      };
    }
    return {
      status: "failed",
      terminal_signal: "agent_idle_incomplete",
      pr: null,
      errorType: "incomplete",
      errorMessage: "implement drive went idle without an opened PR (no successful submit).",
    };
  }

  // address. `applyEvent` keeps submitDetails as the latest submit-bearing evidence: the nested
  // finalizer submit first, then a later standalone submit from the conflict-resolution re-drive.
  const nestedSubmit = args.finalizeDetails?.submit;
  const fallbackSubmit: Record<string, unknown> | null =
    nestedSubmit && typeof nestedSubmit === "object" && !Array.isArray(nestedSubmit)
      ? { ok: true, ...(nestedSubmit as Record<string, unknown>) }
      : null;
  const effectiveSubmit = args.submitDetails ?? fallbackSubmit;
  if (
    args.finalizeDetails?.ok === true &&
    args.lastReviewBatchPresent &&
    effectiveSubmit?.ok === true &&
    effectiveSubmit.mergeable !== false
  ) {
    return {
      status: "completed",
      terminal_signal: "address_resolved",
      pr: null,
      errorType: null,
      errorMessage: null,
    };
  }
  return {
    status: "failed",
    terminal_signal: "agent_idle_incomplete",
    pr: null,
    errorType: "incomplete",
    errorMessage:
      "address drive went idle without fully finalizing feedback " +
      "(publication, thread resolution, and last_review_batch are required).",
  };
}

/**
 * The post-bind preflight rule (pure): the stage's terminating perk tool must be registered —
 * `implement` → `submit`, `address` → `finalize_address`. Returns the required tool name
 * when absent, else `null`. Deliberately does NOT require the `subagent` tool for `address` — the
 * subagent-under-worker live smoke stays the §8.11 carried risk.
 */
export function missingTerminatingTool(stage: DriveStage, toolNames: string[]): string | null {
  const required = stage === "implement" ? "submit" : "finalize_address";
  return toolNames.includes(required) ? null : required;
}

/** Pull a `{ number, url }` PR from a captured `submit` details block; null when malformed. */
function extractPr(
  details: Record<string, unknown> | null,
): { number: number; url: string } | null {
  if (!details || typeof details.pr !== "object" || details.pr === null) return null;
  const pr = details.pr as { number?: unknown; url?: unknown };
  if (typeof pr.number === "number" && typeof pr.url === "string") {
    return { number: pr.number, url: pr.url };
  }
  return null;
}

/**
 * Compose the final `RunOutcome` (pure). `run_id` is read from `PERK_RUN_ID` (inherited from
 * positioning, Gap 7), overridable for tests. On a non-completed status the `error` block carries a
 * capped `error.summary` (route-don't-relay discipline); a completed status has `error: null`.
 */
export function assembleOutcome(args: {
  stage: DriveStage;
  verdict: TerminalVerdict;
  budget: { turns: number; tokens: number; elapsed_ms: number };
  runId?: string;
}): RunOutcome {
  const { verdict } = args;
  const error =
    verdict.status === "completed" || verdict.errorMessage === null
      ? null
      : {
          type: verdict.errorType ?? "error",
          message: verdict.errorMessage,
          summary: capForModel(verdict.errorMessage).shown,
        };
  return {
    run_id: args.runId ?? env.PERK_RUN_ID ?? "",
    stage: args.stage,
    status: verdict.status,
    terminal_signal: verdict.terminal_signal,
    pr: verdict.pr,
    budget: args.budget,
    error,
  };
}

// --- run-event helpers (offline-testable) ---------------------------------------------

/**
 * Compute a `tool_outcome` `{ tool, ok, summary }` from a `tool_execution_end` `DriveEvent` (pure).
 * `ok` = `details.ok === true` when the result carries a `details.ok` boolean, else `!isError`.
 * `summary` is `null` on success and, on failure, a capped (route-don't-relay) synthesis of the
 * tool's error message — never the raw tool result.
 */
export function toolOutcomeOf(event: DriveEvent): {
  tool: string;
  ok: boolean;
  summary: string | null;
} {
  const details = detailsOf(event.result);
  const ok = typeof details?.ok === "boolean" ? details.ok === true : !event.isError;
  let summary: string | null = null;
  if (!ok) {
    const raw = toolErrorMessage(event);
    summary = capForModel(raw, EVENT_SUMMARY_CAP).shown;
  }
  return { tool: event.toolName ?? "", ok, summary };
}

/** Best-effort error text for a failed tool (details.error | result string | a generic fallback). */
function toolErrorMessage(event: DriveEvent): string {
  const details = detailsOf(event.result);
  if (details && typeof details.error === "string" && details.error) return details.error;
  if (typeof event.result === "string" && event.result) return event.result;
  return `tool ${event.toolName ?? ""} failed`;
}

/**
 * The run-event emitter: owns the monotonic `seq` counter and stamps `t = max(0, now() - startMs)`
 * (same basis as `RunOutcome.budget.elapsed_ms`). Fail-soft: a throwing injected sink is caught and
 * swallowed so a broken sink never aborts the drive.
 */
export function createEventEmitter(sink: RunEventSink, now: () => number, startMs: number) {
  let seq = 0;
  return {
    emit(event: RunEventInput): void {
      const full = { ...event, seq: seq++, t: Math.max(0, now() - startMs) } as RunEvent;
      try {
        sink(full);
      } catch (err) {
        console.error(`perk worker: run-event sink threw — ${String(err)}`);
      }
    },
  };
}

/**
 * The default run-event sink: a fail-soft NDJSON appender to `runEventsPath(worktree, runId)`. A
 * **no-op when `runId` is empty** (keeps the offline drive tests, which set no `PERK_RUN_ID`,
 * write-free). Each append is wrapped so a write error logs and is swallowed.
 */
export function defaultEventSink(worktree: string, runId: string): RunEventSink {
  if (!runId) return () => {};
  let ensured = false;
  const path = runEventsPath(worktree, runId);
  return (event: RunEvent): void => {
    try {
      if (!ensured) {
        ensureRunScratch(worktree, runId);
        ensured = true;
      }
      appendFileSync(path, `${JSON.stringify(event)}\n`, "utf8");
    } catch (err) {
      console.error(`perk worker: run-event sink write failed — ${String(err)}`);
    }
  };
}

/**
 * Re-derive the stage's initial prompt from the plan-ref — the TS twin of
 * `perk/run/launch.py._implement_prompt`/`_address_prompt`. INVARIANT: textual parity with the Python
 * plane (asserted reciprocally in `stageExecution.test.ts` + `tests/test_worker_prompt_parity.py`). No
 * skill-binding suffix is appended here: in the driven session the bindings arrive via Mechanism A
 * (bindingDelivery.ts injects the handoff stage's render because this prompt carries no
 * `BINDING_HEADER`) — content byte-identical to the cold door's suffix (contracts.md §8.38).
 * Returns `null` when there is no plan-ref (nothing to prime).
 *
 * The implement primer's wording lives in the canonical template `prompts/stages/implement.md`,
 * rendered by the shared seam (contracts.md §8.31); branching stays in code — only the `read_cmd`
 * var differs. This implement output is byte-identical to the warm `implementHandoffPrompt`.
 *
 * The `address` wording lives in the shared canonical template `prompts/stages/address/action.md`
 * rendered via the cross-plane render seam (contracts.md §8.31); the worker has no preview path
 * (preview is a warm/cold flag only), so it always renders the action body. The classify step is
 * the `classify_review_feedback` tool, which reads the configured classifier model at execute
 * time — nothing model-shaped rides the prompt.
 */
export function initialPromptFor(stage: DriveStage, planRef: PlanRef | null): string | null {
  if (planRef === null) return null;
  const provider = String(planRef.provider ?? "");
  const prId = String(planRef.pr_id ?? "");
  const url = String(planRef.url ?? "");
  if (stage === "implement") {
    const readCmd = planReadInstruction(provider, prId, url);
    return render("stages/implement.md", { provider, pr_id: prId, url, read_cmd: readCmd });
  }
  // address
  return render("stages/address/action.md", { provider, pr_id: prId, url });
}

// --- the drive primitive ------------------------------------------------------------------------

/**
 * Drive one stage to terminal and return a structured `RunOutcome` — never throws (fail-soft like
 * `submitPr`). Seeds `initialPrompt`, races the driving `prompt()` against the budget watchdog and
 * the external `signal`, classifies the terminal at idle, and disposes the adapter handle in
 * `finally` (guarded — a cleanup error can never replace the computed outcome). All session
 * mechanics go through the adapter's drive-session handle; policy stays here.
 */
export async function runStage(
  opts: StageRunOptions,
  deps: StageRunDeps = {},
): Promise<RunOutcome> {
  const now = deps.now ?? Date.now;
  const startMs = now();
  const counters = freshCounters();
  const elapsed = (): number => Math.max(0, now() - startMs);

  // Structured run-event stream: resolve the sink + run_id once, build the emitter, and
  // route every terminal exit through `finish` so exactly one `run_finished` is emitted per drive.
  const runId = env.PERK_RUN_ID ?? "";
  const sink = deps.eventSink ?? defaultEventSink(opts.worktree, runId);
  const emitter = createEventEmitter(sink, now, startMs);
  const finish = (verdict: TerminalVerdict): RunOutcome => {
    const outcome = assembleOutcome({
      stage: opts.stage,
      verdict,
      budget: { turns: counters.turns, tokens: counters.tokens, elapsed_ms: elapsed() },
    });
    emitter.emit({ kind: "run_finished", outcome });
    return outcome;
  };

  // Auth/model resolution is a production-path concern only: with an injected runtime factory
  // (tests) the drive never touches the default `ModelRuntime.create` (no host file reads).
  const resolved = deps.createRuntime ? null : await resolveAuth(opts.model);
  if (resolved === null && !deps.createRuntime) {
    // A zero-turn run is still observable: emit a `run_started` + `run_finished` pair.
    emitter.emit({ kind: "run_started", run_id: runId, stage: opts.stage });
    return finish({
      status: "failed",
      terminal_signal: "model_error",
      pr: null,
      errorType: "no_model",
      errorMessage: "no model available — set an API key (e.g. ANTHROPIC_API_KEY) or pass a model.",
    });
  }

  let terminationReason: "natural" | "budget" | "abort" = "natural";
  let settled = false;
  let handle: DriveSessionHandle | null = null;
  const listener = (event: DriveEvent): void => {
    applyEvent(counters, event);
    if (event.type === "turn_end") {
      if (budgetTripped(counters, opts.budget)) trip("budget");
    } else if (event.type === "tool_execution_end") {
      const o = toolOutcomeOf(event);
      emitter.emit({ kind: "tool_outcome", tool: o.tool, ok: o.ok, summary: o.summary });
    }
  };

  function trip(reason: "budget" | "abort"): void {
    if (settled) return;
    if (terminationReason === "natural") terminationReason = reason;
    handle?.abort();
  }

  const onSignal = (): void => trip("abort");

  try {
    const runtime = deps.createRuntime
      ? await deps.createRuntime(opts)
      : // biome-ignore lint/style/noNonNullAssertion: resolved is non-null on the production path.
        await defaultCreateRuntime(opts.worktree, resolved!);
    handle = createDriveSession(runtime, listener);
    await handle.bind();
    emitter.emit({ kind: "run_started", run_id: runId, stage: opts.stage });

    // Terminating-tool preflight (presence-gated on the session's extension runner): disk
    // discovery has a silent-zero arm — a missing/unparseable `.pi/settings.json` or an
    // unresolvable local-path package yields ZERO extension tools without throwing — so fail
    // fast (zero turns) instead of burning the whole budget on a drive that can never call its
    // terminating tool. Reuses the `model_error` terminal signal with a distinct `error.type`
    // (the `no_model` precedent).
    const toolNames = handle.registeredToolNames();
    if (toolNames !== null) {
      const missing = missingTerminatingTool(opts.stage, toolNames);
      if (missing !== null) {
        return finish({
          status: "failed",
          terminal_signal: "model_error",
          pr: null,
          errorType: "no_extension_tools",
          errorMessage:
            `perk extension tools did not register — the ${opts.stage} stage's terminating ` +
            `tool \`${missing}\` is missing. Check the worktree's .pi/settings.json packages ` +
            "list (perk init converges it); construction diagnostics are on stderr.",
        });
      }
    }

    // Implementation/worker session pointer (contracts.md §8.35): the headless drive records the
    // inner driven session's file under THIS run id into the shared main checkout (the worktree's
    // `mainCheckoutRoot`), labelled `.worker` by capture site. The inner session's own
    // `session_start` records the matching `.main`. Best-effort + non-fatal (carrier warns).
    if (opts.stage === "implement") {
      captureSessionPointer({
        cwd: opts.worktree,
        runId,
        klass: "implementation",
        site: "worker",
        sessionFile: handle.sessionFile(),
      });
    }

    // Budget/abort wiring (Gap 2): wall-clock timer + external signal both trip → handle.abort().
    const timer = setTimeout(() => trip("budget"), opts.budget.wallClockMs);
    if (opts.signal) {
      if (opts.signal.aborted) onSignal();
      else opts.signal.addEventListener("abort", onSignal, { once: true });
    }

    try {
      await handle.prompt(opts.initialPrompt);
    } finally {
      clearTimeout(timer);
      opts.signal?.removeEventListener("abort", onSignal);
      settled = true;
    }

    // Defensive rebind (Gap 1): the happy path never replaces the session; a replacement is loud.
    if (await handle.rebindIfReplaced()) {
      console.error("perk worker: unexpected mid-drive session replacement — rebinding listener.");
    }

    const verdict = classify(opts, counters, terminationReason, () => handle?.workflowBranch());
    return finish(verdict);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return finish({
      status: "failed",
      terminal_signal: "model_error",
      pr: null,
      errorType: "drive_error",
      errorMessage: `headless drive failed: ${message}`,
    });
  } finally {
    if (handle) await handle.dispose();
  }
}

/**
 * Pick the terminal verdict: watchdog/abort override the natural-idle classification. `branch` is
 * a thunk so the workflow branch is read only on the natural path (exactly as before the seam).
 */
function classify(
  opts: StageRunOptions,
  counters: DriveCounters,
  terminationReason: "natural" | "budget" | "abort",
  branch: () => unknown[] | undefined,
): TerminalVerdict {
  if (terminationReason === "budget") {
    return {
      status: "budget_exhausted",
      terminal_signal: "budget",
      pr: null,
      errorType: "budget",
      errorMessage: "budget exhausted (turns/tokens/wall-clock) — drive aborted.",
    };
  }
  if (terminationReason === "abort") {
    return {
      status: "aborted",
      terminal_signal: "external_abort",
      pr: null,
      errorType: "external_abort",
      errorMessage: "drive aborted by external signal.",
    };
  }
  const lastReviewBatchPresent =
    rebuildWorkflowState((branch() ?? []) as never).last_review_batch != null;
  return evaluateTerminal({
    stage: opts.stage,
    submitDetails: counters.submitDetails,
    finalizeDetails: counters.finalizeDetails,
    lastReviewBatchPresent,
    modelError: counters.modelError,
  });
}

/** Convenience: re-derive the initial prompt for a prepared worktree (reads its `cache.plan-ref`). */
export function initialPromptForWorktree(worktree: string, stage: DriveStage): string | null {
  return initialPromptFor(stage, readPlanRef(worktree));
}
