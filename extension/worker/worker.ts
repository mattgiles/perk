// The headless stage-drive primitive (`driveStage`).
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
// pi-ai's normalization) are excluded by design; see `applyEvent`.
//
// Inverse of `extension/worker/readOnlySession.ts`: that builds a fully-isolated READ-ONLY child (loads
// nothing, `["read","grep","find","ls"]`); the worker is the OPPOSITE — read-write defaults + the
// real perk extension loaded from the worktree's `.pi/settings.json` (disk-layered settings:
// `SettingsManager.create(worktree, throwawayAgentDir)` resolves the managed project-tier
// `packages` list — perk + the borrowed set, the same package set as a warm session), with the
// user-global tier locked out via a throwaway `agentDir`.

import { appendFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { env } from "node:process";
// pi-ai's `ModelThinkingLevel` (`"off" | minimal | … | xhigh`) is the union `resolveCliModel`
// returns and `createAgentSessionFromServices` accepts; the pi-coding-agent root does not
// re-export a thinking-level type (only `ThinkingLevelChangeEntry`).
import type { Api, Model, ModelThinkingLevel as ThinkingLevel } from "@earendil-works/pi-ai";
import {
  AuthStorage,
  type CreateAgentSessionRuntimeFactory,
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  ModelRegistry,
  resolveCliModel,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { planReadInstruction } from "../doors/lifecycleGates.ts";
import { ensureRunScratch, type PlanRef, readPlanRef, runEventsPath } from "../substrate/cache.ts";
import { loadPerkConfig } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import { captureSessionPointer } from "../substrate/sessionPointers.ts";
import { rebuildWorkflowState } from "../substrate/workflowState.ts";
import { capForModel } from "./readOnlySession.ts";

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
 * fields keep their meaning. Never thrown — `driveStage` always resolves with one of these.
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
 * `RunOutcome.budget.elapsed_ms`). Future nodes may add variants/fields; existing ones keep meaning.
 */
export type RunEvent =
  | { kind: "run_started"; seq: number; t: number; run_id: string; stage: DriveStage }
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

export interface DriveStageOptions {
  /** Absolute path to the already-positioned worktree (Gap 7). */
  worktree: string;
  stage: DriveStage;
  /** The seeded first prompt (see `initialPromptFor`). */
  initialPrompt: string;
  /**
   * Explicit model; else the SDK's own default resolution picks one at session creation
   * (settings `defaultModel` → pi's per-provider defaults → first available — Gap 5). Never
   * pre-pinned here: `getAvailable()` sorts alphabetically, so `[0]` is the *oldest* model of
   * the first provider (a since-removed `claude-3-5-haiku` date-pin 404'd a whole remote drive).
   */
  model?: Model<Api>;
  /**
   * Thinking level parsed from the `--model <pattern>:<level>` suffix (`resolveWorkerModel`).
   * `undefined` ⇒ the SDK's settings-default resolution — unchanged behavior.
   */
  thinkingLevel?: ThinkingLevel;
  authStorage?: AuthStorage;
  modelRegistry?: ModelRegistry;
  budget: DriveBudget;
  /** External cancellation; OR'd with the budget watchdog. */
  signal?: AbortSignal;
}

/**
 * The offline seam (mirrors `readOnlySession.test.ts`'s `runTask` injection). `createRuntime`
 * overrides the production runtime factory so tests drive synthetic sessions; `now` injects the
 * clock for deterministic `elapsed_ms`.
 */
export interface DriveStageDeps {
  createRuntime?: (opts: DriveStageOptions) => Promise<DriveRuntimeLike>;
  now?: () => number;
  /** The structured run-event sink. Absent ⇒ the default run-scoped NDJSON file sink. */
  eventSink?: RunEventSink;
}

// --- structural shapes (kept minimal so pure helpers stay offline-testable) ---------------------

/** The slice of an agent session event the worker reads (structural — see agent-session.d.ts). */
export interface DriveEvent {
  type: string;
  toolName?: string;
  result?: unknown;
  isError?: boolean;
  message?: {
    role?: string;
    stopReason?: string;
    errorMessage?: string;
    /**
     * Assistant token usage. `reasoning` is a provider-reported breakdown that is a **subset of
     * `output`** on every pi-ai provider that populates it (anthropic `thinking_tokens`, google
     * `thoughtsTokenCount` folded into `output`, openai `reasoning_tokens` inside completion/
     * output tokens — verified @ pi-ai 0.80.5), so it is deliberately EXCLUDED from the budget
     * sum: adding it would double-count.
     */
    usage?: { input?: number; output?: number; reasoning?: number };
    /** Assistant text/content blocks (where `[WIP:n]`/`[DONE:n]` markers live). */
    content?: unknown;
  };
}

/** The session surface the worker drives (structurally satisfied by pi's `AgentSession`). */
export interface DriveSessionLike {
  bindExtensions(bindings: unknown): Promise<void>;
  subscribe(listener: (event: DriveEvent) => void): () => void;
  prompt(text: string): Promise<void>;
  abort(): Promise<void>;
  dispose(): void;
  sessionManager: { getBranch(): unknown[]; getSessionFile?(): string | null };
  /**
   * Optional (presence-gated): when the session exposes its extension runner, `driveStage`
   * preflights the stage's terminating perk tool post-bind and fails fast (zero-turn
   * `no_extension_tools`) instead of burning the budget on a tool-less session.
   */
  extensionRunner?: { getAllRegisteredTools(): { definition: { name: string } }[] };
}

/** The runtime surface (structurally satisfied by pi's `AgentSessionRuntime`). */
export interface DriveRuntimeLike {
  readonly session: DriveSessionLike;
  dispose(): Promise<void> | void;
}

/** Mutable counters/captures the subscribe listener accumulates over the drive. */
export interface DriveCounters {
  turns: number;
  tokens: number;
  submitDetails: Record<string, unknown> | null;
  resolveDetails: Record<string, unknown> | null;
  modelError: { message: string } | null;
}

export function freshCounters(): DriveCounters {
  return { turns: 0, tokens: 0, submitDetails: null, resolveDetails: null, modelError: null };
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

/** Extract a tool's `details` object from a captured `tool_execution_end.result`; null if absent. */
function detailsOf(result: unknown): Record<string, unknown> | null {
  if (result && typeof result === "object" && "details" in result) {
    const details = (result as { details: unknown }).details;
    if (details && typeof details === "object") return details as Record<string, unknown>;
  }
  return null;
}

/**
 * Fold one agent-session event into the running counters (pure). Counts `turn_end` turns, sums
 * assistant token usage (the `sumAssistantTokens` pattern in objective.ts), captures the `submit`
 * /`resolve_review_threads` terminal tool details, and records a post-acceptance model error
 * (assistant `message_end` with `stopReason:"error"`, surfaced with retry off — audit §B #4).
 *
 * The token sum is `input + output` ONLY: `usage.reasoning` is a subset of `output` on every
 * pi-ai provider that reports it (see the `DriveEvent.usage` doc), so summing it would
 * double-count.
 */
export function applyEvent(counters: DriveCounters, event: DriveEvent): void {
  if (event.type === "turn_end") {
    counters.turns += 1;
    const usage = event.message?.usage;
    if (usage) counters.tokens += Math.max(0, usage.input ?? 0) + Math.max(0, usage.output ?? 0);
    return;
  }
  if (event.type === "tool_execution_end") {
    if (event.toolName === "submit") counters.submitDetails = detailsOf(event.result);
    else if (event.toolName === "resolve_review_threads") {
      counters.resolveDetails = detailsOf(event.result);
    }
    return;
  }
  if (event.type === "message_end") {
    if (event.message?.role === "assistant" && event.message.stopReason === "error") {
      counters.modelError = { message: event.message.errorMessage ?? "model error" };
    }
  }
}

/** True when the budget watchdog should trip from the current counters. */
export function budgetTripped(counters: DriveCounters, budget: DriveBudget): boolean {
  return counters.turns >= budget.maxTurns || counters.tokens >= budget.maxTokens;
}

/**
 * Classify a natural-idle terminal from the captured state (pure). `modelError` wins (post-
 * acceptance error, §B #4); else the stage success predicate:
 *  - implement: a successful `submit` carrying a `pr` → completed/submit_tool;
 *  - address: `resolve_review_threads` ok AND `last_review_batch` appended → completed/address_resolved;
 *  - otherwise the agent went idle without completing the stage → failed/agent_idle_incomplete.
 */
export function evaluateTerminal(args: {
  stage: DriveStage;
  submitDetails: Record<string, unknown> | null;
  resolveSucceeded: boolean;
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

  // address
  if (args.resolveSucceeded && args.lastReviewBatchPresent) {
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
    errorMessage: "address drive went idle without resolving feedback (no last_review_batch).",
  };
}

/**
 * The post-bind preflight rule (pure): the stage's terminating perk tool must be registered —
 * `implement` → `submit`, `address` → `resolve_review_threads`. Returns the required tool name
 * when absent, else `null`. Deliberately does NOT require the `subagent` tool for `address` — the
 * subagent-under-worker live smoke stays the §8.11 carried risk.
 */
export function missingTerminatingTool(stage: DriveStage, toolNames: string[]): string | null {
  const required = stage === "implement" ? "submit" : "resolve_review_threads";
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
 * Extract `[WIP:n]`/`[DONE:n]` markers from assistant text in **textual appearance order** (pure).
 * A single combined, case-insensitive regex so interleaved markers (`[WIP:2]` before `[DONE:1]` in
 * the same message) emit in that order — unlike checkpoints.ts's separate `extractWip/DoneSteps`
 * lists, which lose cross-marker order. Returns `[]` when there are no markers.
 */
export function extractStepMarkers(text: string): { marker: "wip" | "done"; step: number }[] {
  const out: { marker: "wip" | "done"; step: number }[] = [];
  for (const m of text.matchAll(/\[(WIP|DONE):(\d+)\]/gi)) {
    const step = Number(m[2]);
    if (Number.isFinite(step)) {
      out.push({ marker: (m[1] ?? "").toLowerCase() === "done" ? "done" : "wip", step });
    }
  }
  return out;
}

/** Flatten a `DriveEvent`'s assistant `message.content` (string | `{type:'text',text}[]`) to text. */
export function assistantText(event: DriveEvent): string {
  const content = event.message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((b) => {
        const block = b as { type?: string; text?: string };
        return block.type === "text" && typeof block.text === "string" ? block.text : "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

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
 * plane (asserted reciprocally in `worker.test.ts` + `tests/test_worker_prompt_parity.py`). No
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
 * (preview is a warm/cold flag only), so it always renders the action body. The classifier
 * present/absent split builds the `model_clause` render var in code.
 */
export function initialPromptFor(
  stage: DriveStage,
  planRef: PlanRef | null,
  classifierModel?: string,
): string | null {
  if (planRef === null) return null;
  const provider = String(planRef.provider ?? "");
  const prId = String(planRef.pr_id ?? "");
  const url = String(planRef.url ?? "");
  if (stage === "implement") {
    const readCmd = planReadInstruction(provider, prId, url);
    return render("stages/implement.md", { provider, pr_id: prId, url, read_cmd: readCmd });
  }
  // address
  const modelClause = classifierModel
    ? `, passing \`model: "${classifierModel}"\` on that call (the configured [models.subagents] review-classifier model)`
    : "";
  return render("stages/address/action.md", {
    provider,
    pr_id: prId,
    url,
    model_clause: modelClause,
  });
}

// --- bind / subscribe management (Gap 1) --------------------------------------------------------

/** The binding the worker applies to every (re)bound session: headless (`hasUI === false`). */
export function headlessBinding(): {
  uiContext: undefined;
  mode: "json";
  onError: (err: unknown) => void;
} {
  return {
    uiContext: undefined,
    mode: "json",
    onError: (err: unknown) => console.error(`perk worker: extension error — ${String(err)}`),
  };
}

/**
 * Manage the bind+subscribe lifecycle across session replacement (Gap 1). `bind(target)` binds the
 * perk extension and attaches the terminal/budget listener; calling it again (after a runtime
 * replacement) unsubscribes the prior listener first so events are never double-counted. A mid-drive
 * replacement is not expected on the happy path (the prompt instructs `/submit`, never `/implement`;
 * `lifecycleGates.newSession` is `hasUI`-guarded; objective compaction is inert with no active
 * objective) — so an observed `rebind()` is a loud structured-log error.
 */
export function createBindManager(binding: unknown, listener: (event: DriveEvent) => void) {
  let unsubscribe: (() => void) | null = null;
  return {
    async bind(target: DriveSessionLike): Promise<void> {
      if (unsubscribe) unsubscribe();
      await target.bindExtensions(binding);
      unsubscribe = target.subscribe(listener);
    },
    dispose(): void {
      if (unsubscribe) {
        unsubscribe();
        unsubscribe = null;
      }
    },
  };
}

// --- the production runtime factory -------------------------------------------------------------

/**
 * Build the asymmetric runtime: `cwd = worktree` (project tier — perk's `@mgiles/perk` extension via the
 * managed `.pi/settings.json`, the managed `AGENTS.md`/`APPEND_SYSTEM.md`) and `agentDir = throwaway`
 * (user-global tier OUT — the throwaway dir has no `settings.json`, so the global tier is empty),
 * env-var/registry auth+model (Gap 5). Settings are DISK-LAYERED (`SettingsManager.create` +
 * `applyOverrides`, the SDK's sanctioned "with overrides" shape — docs/sdk.md "Settings
 * Management"): the project tier resolves the managed `packages` list, while the compaction-off/
 * retry-off determinism overrides ride the merged view only (package resolution reads the
 * per-scope raws — overrides cannot leak into it). Missing `npm:` packages auto-install into
 * `.pi/npm` during the loader's reload (skipped under `PI_OFFLINE`); an install failure throws →
 * `driveStage`'s catch arm → a loud `failed`/`drive_error`. No `tools` allowlist — read-write
 * defaults + extension tools. The `createAgentSessionServices` factory builds the
 * `DefaultResourceLoader` internally from `cwd`/`agentDir` (recipe correction #1).
 */
async function defaultCreateRuntime(
  opts: DriveStageOptions,
  resolved: ResolvedAuth,
): Promise<DriveRuntimeLike> {
  const agentDir = mkdtempSync(join(tmpdir(), "perk-worker-agent-"));
  const settingsManager = SettingsManager.create(opts.worktree, agentDir);
  settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } });
  const factory: CreateAgentSessionRuntimeFactory = async (factoryOpts) => {
    const services = await createAgentSessionServices({
      cwd: factoryOpts.cwd,
      agentDir: factoryOpts.agentDir,
      authStorage: resolved.authStorage,
      settingsManager,
      modelRegistry: resolved.modelRegistry,
    });
    const result = await createAgentSessionFromServices({
      services,
      sessionManager: factoryOpts.sessionManager,
      sessionStartEvent: factoryOpts.sessionStartEvent,
      // `undefined` ⇒ the SDK's initial-model resolution picks the model (see `resolveAuth`);
      // an `undefined` thinkingLevel likewise defers to the settings default.
      model: resolved.model,
      thinkingLevel: opts.thinkingLevel,
    });
    // Name the model that will actually drive (the SDK may have picked it) — the remote step
    // log is otherwise silent about it until a provider error.
    const chosen = result.session.model;
    console.error(
      `perk worker: model ${chosen ? `${chosen.provider}/${chosen.id}` : "unresolved"}`,
    );
    // Loud construction diagnostics (the CAUSE behind a later `no_extension_tools` symptom):
    // settings I/O errors and extension load errors are recorded, not raised, by the SDK —
    // surfacing them is the app layer's job. Fail-soft reporting only; never throws.
    for (const entry of result.extensionsResult.errors) {
      console.error(`perk worker: extension load error — ${entry.path}: ${entry.error}`);
    }
    for (const entry of settingsManager.drainErrors()) {
      console.error(`perk worker: settings error (${entry.scope}) — ${String(entry.error)}`);
    }
    return { ...result, services, diagnostics: services.diagnostics };
  };
  const runtime = await createAgentSessionRuntime(factory, {
    cwd: opts.worktree,
    agentDir,
    sessionManager: SessionManager.create(opts.worktree),
  });
  return runtime as unknown as DriveRuntimeLike;
}

// --- model/auth resolution (Gap 5) --------------------------------------------------------------

export interface ResolvedAuth {
  authStorage: AuthStorage;
  modelRegistry: ModelRegistry;
  /** The EXPLICIT model only; `undefined` defers the pick to the SDK at session creation. */
  model: Model<Api> | undefined;
}

/**
 * Resolve auth; returns null (never throws) when no model is available at all. The model is NOT
 * pre-pinned from the registry: an `undefined` model lets `createAgentSession` run its own
 * initial-model resolution (settings `defaultModel` → pi's curated per-provider defaults → first
 * available), which picks a current-generation model instead of the registry's
 * alphabetically-first (= oldest) entry.
 */
export function resolveAuth(opts: DriveStageOptions): ResolvedAuth | null {
  const authStorage = opts.authStorage ?? AuthStorage.create();
  const modelRegistry = opts.modelRegistry ?? ModelRegistry.create(authStorage);
  if (!opts.model && modelRegistry.getAvailable().length === 0) return null;
  return { authStorage, modelRegistry, model: opts.model };
}

/** What an explicit `--model` flag resolves to (a thin projection of `ResolveCliModelResult`). */
export interface ResolvedWorkerModel {
  model: Model<Api> | undefined;
  thinkingLevel: ThinkingLevel | undefined;
  /** Non-fatal resolution diagnostic (e.g. an invalid `:thinking` suffix) — surface, continue. */
  warning: string | undefined;
  /** Fatal: the pattern resolved to no model — fail fast, never guess. */
  error: string | undefined;
}

/**
 * Resolve an explicit `--model` flag with pi's OWN CLI semantics (`resolveCliModel`): fuzzy
 * matching, bare-id resolution, `provider/pattern`, and a `:thinking` suffix — the same chain the
 * flag's string hits in an interactive pi launch, closing the warm/cold parity gap (cf.
 * docs/learned/workflow/execution-path-parity.md). `raw` falsy ⇒ all-undefined (the SDK's own
 * default resolution picks the model at session creation — see `resolveAuth`). A resolution that
 * yields neither a model nor an error is normalized to the worker's not-found error.
 */
export function resolveWorkerModel(
  raw: string | undefined,
  modelRegistry: ModelRegistry,
): ResolvedWorkerModel {
  if (!raw) {
    return { model: undefined, thinkingLevel: undefined, warning: undefined, error: undefined };
  }
  const result = resolveCliModel({ cliModel: raw, modelRegistry });
  if (result.model === undefined && result.error === undefined) {
    return {
      model: undefined,
      thinkingLevel: undefined,
      warning: result.warning,
      error: `model '${raw}' not found in the registry.`,
    };
  }
  return {
    model: result.model,
    thinkingLevel: result.thinkingLevel,
    warning: result.warning,
    error: result.error,
  };
}

// --- the drive primitive ------------------------------------------------------------------------

/**
 * Drive one stage to terminal and return a structured `RunOutcome` — never throws (fail-soft like
 * `submitPr`). Seeds `initialPrompt`, races the driving `prompt()` against the budget watchdog and
 * the external `signal`, classifies the terminal at idle, and disposes the runtime in `finally`.
 */
export async function driveStage(
  opts: DriveStageOptions,
  deps: DriveStageDeps = {},
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

  const resolved = resolveAuth(opts);
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
  let runtime: DriveRuntimeLike | null = null;
  const bindManager = createBindManager(headlessBinding(), (event) => {
    applyEvent(counters, event);
    if (event.type === "turn_end") {
      // Emit this turn's `[WIP:n]`/`[DONE:n]` markers in textual appearance order (one event each).
      for (const m of extractStepMarkers(assistantText(event))) {
        emitter.emit({ kind: "step_marker", marker: m.marker, step: m.step });
      }
      if (budgetTripped(counters, opts.budget)) trip("budget");
    } else if (event.type === "tool_execution_end") {
      const o = toolOutcomeOf(event);
      emitter.emit({ kind: "tool_outcome", tool: o.tool, ok: o.ok, summary: o.summary });
    }
  });

  function trip(reason: "budget" | "abort"): void {
    if (settled) return;
    if (terminationReason === "natural") terminationReason = reason;
    if (runtime) void runtime.session.abort();
  }

  const onSignal = (): void => trip("abort");

  try {
    runtime = deps.createRuntime
      ? await deps.createRuntime(opts)
      : // biome-ignore lint/style/noNonNullAssertion: resolved is non-null on the production path.
        await defaultCreateRuntime(opts, resolved!);

    let boundSession = runtime.session;
    await bindManager.bind(boundSession);
    emitter.emit({ kind: "run_started", run_id: runId, stage: opts.stage });

    // Terminating-tool preflight (presence-gated on `extensionRunner`): disk discovery has a
    // silent-zero arm — a missing/unparseable `.pi/settings.json` or an unresolvable local-path
    // package yields ZERO extension tools without throwing — so fail fast (zero turns) instead of
    // burning the whole budget on a drive that can never call its terminating tool. Reuses the
    // `model_error` terminal signal with a distinct `error.type` (the `no_model` precedent).
    if (boundSession.extensionRunner) {
      const toolNames = boundSession.extensionRunner
        .getAllRegisteredTools()
        .map((t) => t.definition.name);
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
        sessionFile: boundSession.sessionManager.getSessionFile?.() ?? null,
      });
    }

    // Budget/abort wiring (Gap 2): wall-clock timer + external signal both trip → session.abort().
    const timer = setTimeout(() => trip("budget"), opts.budget.wallClockMs);
    if (opts.signal) {
      if (opts.signal.aborted) onSignal();
      else opts.signal.addEventListener("abort", onSignal, { once: true });
    }

    try {
      await runtime.session.prompt(opts.initialPrompt);
    } finally {
      clearTimeout(timer);
      opts.signal?.removeEventListener("abort", onSignal);
      settled = true;
    }

    // Defensive rebind (Gap 1): the happy path never replaces the session; a replacement is loud.
    if (runtime.session !== boundSession) {
      console.error("perk worker: unexpected mid-drive session replacement — rebinding listener.");
      boundSession = runtime.session;
      await bindManager.bind(boundSession);
    }

    const verdict = classify(opts, counters, terminationReason, boundSession);
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
    bindManager.dispose();
    if (runtime) await runtime.dispose();
  }
}

/** Pick the terminal verdict: watchdog/abort override the natural-idle classification. */
function classify(
  opts: DriveStageOptions,
  counters: DriveCounters,
  terminationReason: "natural" | "budget" | "abort",
  session: DriveSessionLike,
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
    rebuildWorkflowState(session.sessionManager.getBranch() as never).last_review_batch != null;
  return evaluateTerminal({
    stage: opts.stage,
    submitDetails: counters.submitDetails,
    resolveSucceeded: counters.resolveDetails?.ok === true,
    lastReviewBatchPresent,
    modelError: counters.modelError,
  });
}

/** Convenience: re-derive the initial prompt for a prepared worktree (reads its `cache.plan-ref`). */
export function initialPromptForWorktree(worktree: string, stage: DriveStage): string | null {
  const classifierModel = loadPerkConfig(worktree).subagents["review-classifier"];
  return initialPromptFor(stage, readPlanRef(worktree), classifierModel);
}
