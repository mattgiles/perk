// The PRIVATE SDK adapter behind the stage-execution seam (contracts.md §8.11).
//
// Every `@earendil-works/*` import on the drive path lives HERE — construction, raw session
// events (translated at the boundary into the perk-owned `StageEvent` union), and prompt/abort
// ownership are adapter-confined so the seam (`stageExecution.ts`) carries no SDK vocabulary on
// its caller surface and folds policy (budget, terminal capture, outcome) over perk shapes only. The only production
// importer is the seam itself (enforced by `extension/importDirectionGuard.test.ts` Rule F);
// tests import this module deliberately (to inject a model runtime and drive the handle).
//
// The opacity contract (narrow, stated exactly): `WorkerModelRequest` is *nominal* — a
// `#private` field makes structural forgery impossible — and its class lives only here (the seam
// re-exports it so `workerMain.ts` can mint one with zero SDK imports; production imports of this
// module are guard-banned outside the seam). SDK types still appear on this adapter-owned class
// surface; the caller-side guarantee is the import-edge ban plus nominal minting, nothing
// stronger.

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
// pi-ai's `ModelThinkingLevel` (`"off" | minimal | … | xhigh`) is the union `resolveCliModel`
// returns and `createAgentSessionFromServices` accepts; the pi-coding-agent root does not
// re-export a thinking-level type (only `ThinkingLevelChangeEntry`).
import type { Api, Model, ModelThinkingLevel as ThinkingLevel } from "@earendil-works/pi-ai";
import {
  type CreateAgentSessionRuntimeFactory,
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  ModelRuntime,
  resolveCliModel,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

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
   * Optional (presence-gated): when the session exposes its extension runner, the seam
   * preflights the stage's terminating perk tool post-bind and fails fast (zero-turn
   * `no_extension_tools`) instead of burning the budget on a tool-less session.
   */
  extensionRunner?: { getAllRegisteredTools(): { definition: { name: string } }[] };
  /**
   * Optional (presence-gated): the agent whose `finishTurn` hook the handle wraps so a turn cap
   * ends the run AT the cap. Pi's agent loop never re-checks the abort signal between turns, so
   * an abort fired on the cap's `turn_end` still starts one more turn; `{ action: "end" }` from
   * `finishTurn` is the loop's own "no further request" decision. Method syntax keeps the
   * structural check bivariant against pi-agent-core's `FinishTurn`.
   */
  agent?: { finishTurn?(turn: DriveTurn, signal?: AbortSignal): unknown };
}

/** The slice of pi-agent-core's `AgentTurnContext` the turn gate reads. */
export interface DriveTurn {
  message?: DriveEvent["message"];
}

/** The runtime surface (structurally satisfied by pi's `AgentSessionRuntime`). */
export interface DriveRuntimeLike {
  readonly session: DriveSessionLike;
  dispose(): Promise<void> | void;
}

/** Extract a tool's `details` object from a captured `tool_execution_end.result`; null if absent. */
function detailsOf(result: unknown): Record<string, unknown> | null {
  if (result && typeof result === "object" && "details" in result) {
    const details = (result as { details: unknown }).details;
    if (details && typeof details === "object") return details as Record<string, unknown>;
  }
  return null;
}

// --- the perk-owned drive-event union -------------------------------------------------------------

/**
 * The perk-owned drive event union — the ONLY event vocabulary that crosses the handle boundary
 * to the seam. The adapter translates raw SDK session events into these (`translateEvent`); all
 * policy folding (budget counters, terminal capture, outcome classification) stays in the seam,
 * so SDK event-shape churn is absorbed here and never reaches stage policy.
 */
export type StageEvent =
  | {
      kind: "turn_ended";
      /**
       * Fresh-work tokens for the turn: assistant `input + output` ONLY. `usage.reasoning` is a
       * provider-reported breakdown that is a **subset of `output`** on every pi-ai provider that
       * populates it (anthropic `thinking_tokens`, google `thoughtsTokenCount` folded into
       * `output`, openai `reasoning_tokens` inside completion/output tokens — verified @ pi-ai
       * 0.80.5), so it is deliberately EXCLUDED: adding it would double-count.
       */
      freshTokens: number;
    }
  | {
      kind: "tool_ended";
      tool: string;
      /** `details.ok` when the result carries the boolean, else `!isError`. */
      ok: boolean;
      /** The tool's structured `details` block (perk tools' result shape), null when absent. */
      details: Record<string, unknown> | null;
      /** Pre-cap error text for a failed tool (null when `ok`); the seam applies its cap. */
      errorText: string | null;
    }
  | { kind: "model_errored"; message: string };

/** Best-effort error text for a failed tool (details.error | result string | a generic fallback). */
function toolErrorMessage(event: DriveEvent): string {
  const details = detailsOf(event.result);
  if (details && typeof details.error === "string" && details.error) return details.error;
  if (typeof event.result === "string" && event.result) return event.result;
  return `tool ${event.toolName ?? ""} failed`;
}

/**
 * Translate one raw agent-session event into the perk-owned union (pure); `null` for event types
 * the drive does not observe. This is the entire SDK-event vocabulary the drive consumes: turn
 * completion (with the fresh-work token sum — the `sumAssistantTokens` pattern in objective.ts),
 * tool completion (with the parsed `details` block and pre-cap error text), and a
 * post-acceptance model error (assistant `message_end` with `stopReason:"error"`, surfaced with
 * retry off — audit §B #4).
 */
export function translateEvent(event: DriveEvent): StageEvent | null {
  if (event.type === "turn_end") return { kind: "turn_ended", freshTokens: freshTokensOf(event) };
  if (event.type === "tool_execution_end") {
    const details = detailsOf(event.result);
    const ok = typeof details?.ok === "boolean" ? details.ok === true : !event.isError;
    return {
      kind: "tool_ended",
      tool: event.toolName ?? "",
      ok,
      details,
      errorText: ok ? null : toolErrorMessage(event),
    };
  }
  if (
    event.type === "message_end" &&
    event.message?.role === "assistant" &&
    event.message.stopReason === "error"
  ) {
    return { kind: "model_errored", message: event.message.errorMessage ?? "model error" };
  }
  return null;
}

/** A turn's fresh-work tokens (`input + output`; see `StageEvent.turn_ended.freshTokens`). */
function freshTokensOf(turn: DriveTurn): number {
  const usage = turn.message?.usage;
  return usage ? Math.max(0, usage.input ?? 0) + Math.max(0, usage.output ?? 0) : 0;
}

/**
 * The seam's turn-boundary verdict, asked once per finished turn BEFORE its `turn_end`: `true`
 * ends the run there (no next turn starts). Receives the turn's fresh-work tokens — the same sum
 * the following `turn_ended` event carries — so the seam can decide on the post-turn counters.
 */
export type EndRunAfterTurn = (turn: { freshTokens: number }) => boolean;

// --- the drive-session handle --------------------------------------------------------------------

/** The binding the worker applies to every (re)bound session: headless (`hasUI === false`). */
function headlessBinding(): {
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
 * Create the drive-session handle over an already-created runtime — the seam's ONLY window onto
 * the live session. Bind/subscribe, prompt, abort ownership, defensive rebind, and guarded
 * disposal live behind it; the seam never touches `.session`/`.sessionManager`/`.extensionRunner`
 * members directly. `listener` is the seam's policy fold and receives only the perk-owned
 * `StageEvent` union — raw `DriveEvent`s are translated at this boundary and never cross it.
 * Rebinding unsubscribes the prior raw listener first so events are never double-counted. The
 * handle is private to the confined pair (seam ↔ adapter); the seam's fake-session injection
 * seam (`deps.createRuntime` returning `DriveRuntimeLike`) is unchanged.
 *
 * `endRunAfterTurn` (optional) is installed as a wrapper over the bound agent's `finishTurn` —
 * after the session's own hook (which dispatches the extension `turn_end` boundary), so an
 * earlier `end` decision always stands — and removed on rebind and dispose. A session that
 * exposes no `agent` (the seam's fakes) skips the gate; the seam's abort still stops it.
 */
export function createDriveSession(
  runtime: DriveRuntimeLike,
  listener: (event: StageEvent) => void,
  endRunAfterTurn?: EndRunAfterTurn,
) {
  const binding = headlessBinding();
  let bound: DriveSessionLike = runtime.session;
  let unsubscribe: (() => void) | null = null;
  let uninstallGate: (() => void) | null = null;
  let retainedAbort: Promise<void> | null = null;
  const rawListener = (event: DriveEvent): void => {
    const translated = translateEvent(event);
    if (translated !== null) listener(translated);
  };

  function installGate(target: DriveSessionLike): (() => void) | null {
    const agent = target.agent;
    if (!endRunAfterTurn || !agent) return null;
    const previous = agent.finishTurn;
    const gate = async (turn: DriveTurn, signal?: AbortSignal): Promise<unknown> => {
      const decision = await previous?.call(agent, turn, signal);
      if ((decision as { action?: unknown } | undefined)?.action === "end") return decision;
      return endRunAfterTurn({ freshTokens: freshTokensOf(turn) }) ? { action: "end" } : decision;
    };
    agent.finishTurn = gate;
    return () => {
      if (agent.finishTurn === gate) agent.finishTurn = previous;
    };
  }

  async function bindTo(target: DriveSessionLike): Promise<void> {
    if (unsubscribe) unsubscribe();
    uninstallGate?.();
    await target.bindExtensions(binding);
    unsubscribe = target.subscribe(rawListener);
    uninstallGate = installGate(target);
    bound = target;
  }

  return {
    /** Headless bind + subscribe on the runtime's current session. */
    async bind(): Promise<void> {
      await bindTo(runtime.session);
    },
    /** The single driving prompt. */
    async prompt(text: string): Promise<void> {
      await bound.prompt(text);
    },
    /**
     * OWNED + IDEMPOTENT: fires `session.abort()` on the runtime's live session exactly once —
     * the drive can trip repeatedly (every post-trip `turn_ended` re-calls this), but later
     * calls are no-ops, so no abort work can outlive `dispose()`'s drain. The rejection has an
     * owner: the logging catch attaches immediately (never unhandled), and the caught chain is
     * retained so `dispose()` drains it before returning.
     */
    abort(): void {
      if (retainedAbort !== null) return;
      retainedAbort = runtime.session.abort().catch((err) => {
        console.error(`perk worker: session.abort() rejected — ${String(err)}`);
      });
    },
    /**
     * The defensive-rebind arm: when the runtime replaced its session mid-drive, unsubscribe the
     * prior listener, bind + subscribe the replacement, and return true (`false` = unchanged). A
     * replacement is not expected on the happy path (the prompt instructs `/submit`, never
     * `/implement`; `lifecycleGates.newSession` is `hasUI`-guarded; objective compaction is
     * inert with no active objective) — the seam logs an observed rebind loudly.
     */
    async rebindIfReplaced(): Promise<boolean> {
      if (runtime.session === bound) return false;
      await bindTo(runtime.session);
      return true;
    },
    /** Preflight read (null when the session exposes no `extensionRunner`). */
    registeredToolNames(): string[] | null {
      const runner = bound.extensionRunner;
      if (!runner) return null;
      return runner.getAllRegisteredTools().map((t) => t.definition.name);
    },
    /** §8.35 pointer-capture read. */
    sessionFile(): string | null {
      return bound.sessionManager.getSessionFile?.() ?? null;
    },
    /** `sessionManager.getBranch()` for the seam's terminal classification. */
    workflowBranch(): unknown[] {
      return bound.sessionManager.getBranch();
    },
    /**
     * Guarded cleanup: unsubscribe (caught) → runtime dispose (caught) → drain the retained
     * abort promise (caught). NEVER throws — a throwing unsubscribe or a rejecting
     * `runtime.dispose()` can never replace the seam's already-computed `RunOutcome` (the
     * never-throws contract, contracts.md §8.11, holds under adversarial fakes).
     */
    async dispose(): Promise<void> {
      try {
        unsubscribe?.();
      } catch (err) {
        console.error(`perk worker: listener unsubscribe threw — ${String(err)}`);
      }
      unsubscribe = null;
      uninstallGate?.();
      uninstallGate = null;
      try {
        await runtime.dispose();
      } catch (err) {
        console.error(`perk worker: runtime dispose failed — ${String(err)}`);
      }
      // Already a caught chain (see abort) — awaiting only drains it before return.
      if (retainedAbort) await retainedAbort;
    },
  };
}

/**
 * The handle's nameable type, derived from its sole factory (no duplicate interface to drift):
 * the object literal above carries the per-method contracts.
 */
export type DriveSessionHandle = ReturnType<typeof createDriveSession>;

// --- model request, selection and admission --------------------------------------------------------

/**
 * The seam's UNRESOLVED model input (`StageRunOptions.model`): the raw `--model` text plus, for
 * tests, the model runtime to use. NOMINAL: the `#private` field makes structural forgery
 * impossible. Nothing is resolved at mint time — the pattern is resolved inside the runtime
 * factory only after the worktree's extensions have registered their providers and virtual
 * models (`selectWorkerModel`), so an extension-registered model is visible to it.
 */
export class WorkerModelRequest {
  // The ONE `#private` field supplies the nominal guarantee; the payload rides an ordinary
  // readonly field. (Constructor parameter properties would be smaller still, but node's
  // type-stripping test runner rejects non-erasable TS syntax.)
  readonly #modelRuntime: ModelRuntime | undefined;
  /**
   * The raw `--model <pattern>[:<thinking>]` text, resolved with pi's CLI semantics. Absent or
   * `""` (a bare `--model`) defers the pick to the SDK's own default chain at session creation.
   */
  readonly pattern: string | undefined;

  constructor(options: { pattern?: string; modelRuntime?: ModelRuntime }) {
    this.#modelRuntime = options.modelRuntime;
    this.pattern = options.pattern;
  }

  /**
   * The injected model/auth runtime (the test seam). Absent ⇒ `defaultCreateRuntime` mints
   * `ModelRuntime.create()` inside the outcome boundary.
   */
  get modelRuntime(): ModelRuntime | undefined {
    return this.#modelRuntime;
  }
}

/** What a `--model` pattern resolves to — discriminated so no contradictory state is expressible. */
export type ResolvedWorkerModel =
  | {
      ok: true;
      /** The EXPLICIT model only; `undefined` defers the pick to the SDK at session creation. */
      model: Model<Api> | undefined;
      /** The parsed `:thinking` suffix; `undefined` ⇒ the settings default. */
      thinkingLevel: ThinkingLevel | undefined;
      warning: string | undefined;
    }
  | { ok: false; error: string; warning: string | undefined };

/** The worker's normalized not-found text for a resolution that yields neither model nor error. */
function notFoundError(pattern: string): string {
  return `model '${pattern}' not found in the registry.`;
}

/**
 * Resolve an explicit `--model` pattern over `modelRuntime` with pi's OWN CLI semantics
 * (`resolveCliModel`): fuzzy matching, bare-id resolution, `provider/pattern`, and a `:thinking`
 * suffix — the same chain the flag's string hits in an interactive pi launch, closing the
 * warm/cold parity gap (cf. docs/learned/workflow/execution-path-parity.md). Pure over the
 * runtime; resolves over `getModels()` regardless of auth (admission is `selectWorkerModel`'s).
 *
 * `pattern` absent **or `""`** ⇒ `ok: true` with no model (the SDK's own initial-model
 * resolution stays the default). The `""` ≡ omitted equivalence is deliberate: workerMain's flag
 * grammar produces `""` for a bare `--model`, and the tolerance is pinned by a test. A
 * resolution that yields neither a model nor an error is normalized to the worker's not-found
 * error (`ok: false` — fail fast, never guess). `warning` is a non-fatal resolution diagnostic
 * (e.g. an invalid `:thinking` suffix) — the caller surfaces it only when proceeding.
 */
export function resolveWorkerModel(
  pattern: string | undefined,
  modelRuntime: ModelRuntime,
): ResolvedWorkerModel {
  if (!pattern) {
    return { ok: true, model: undefined, thinkingLevel: undefined, warning: undefined };
  }
  const result = resolveCliModel({ cliModel: pattern, modelRuntime });
  if (result.error !== undefined) {
    return { ok: false, error: result.error, warning: result.warning };
  }
  if (result.model === undefined) {
    return { ok: false, error: notFoundError(pattern), warning: result.warning };
  }
  return {
    ok: true,
    model: result.model,
    thinkingLevel: result.thinkingLevel,
    warning: result.warning,
  };
}

/** The typed zero-turn refusals of the selection ladder (`error.type` under `model_error`). */
export type WorkerModelRefusalType = "model_not_found" | "no_model" | "model_auth";

/** The selection ladder's verdict over a post-registration runtime. */
export type WorkerModelPick =
  | {
      ok: true;
      /** The explicit model; `undefined` defers to the SDK's `findInitialModel` chain. */
      model: Model<Api> | undefined;
      thinkingLevel: ThinkingLevel | undefined;
      warning: string | undefined;
    }
  | {
      ok: false;
      type: WorkerModelRefusalType;
      message: string;
      warning: string | undefined;
    };

/** Drop one trailing period so an embedded sentence can be re-terminated exactly once. */
function withoutTrailingPeriod(text: string): string {
  return text.endsWith(".") ? text.slice(0, -1) : text;
}

/**
 * The selection + admission steps of the worker's ladder, run over the runtime AFTER
 * `createAgentSessionServices` applied the extensions' provider/native-provider/virtual-model
 * registrations (so those are visible here):
 *
 *  - an explicit `pattern` resolves through `resolveWorkerModel`; a miss ⇒ `model_not_found`;
 *  - no pattern ⇒ `no_model` iff the availability snapshot is empty, else a deferred pick
 *    (`model: undefined` — Pi's own default chain picks at session creation; perk never
 *    pre-picks a catalog entry). The deferred path adds no auth check: Pi's chain only picks
 *    configured providers;
 *  - an explicit model ⇒ `model_auth` unless its provider passes Pi's prompt-time auth predicate
 *    (`hasConfiguredAuth || (await checkAuth) !== undefined`) — the worker refuses exactly what
 *    Pi would refuse at the first request, only earlier, typed and zero-turn. A virtual model is
 *    admitted on its own provider's configured status; its physical target's auth stays Pi's
 *    request-time routing concern.
 */
export async function selectWorkerModel(
  pattern: string | undefined,
  modelRuntime: ModelRuntime,
): Promise<WorkerModelPick> {
  const resolved = resolveWorkerModel(pattern, modelRuntime);
  if (!resolved.ok) {
    const detail =
      pattern && resolved.error !== notFoundError(pattern)
        ? withoutTrailingPeriod(resolved.error)
        : "no match";
    return {
      ok: false,
      type: "model_not_found",
      message: `model '${pattern ?? ""}' not found in the registry (resolved after extension registration): ${detail}.`,
      warning: resolved.warning,
    };
  }
  const model = resolved.model;
  if (model === undefined) {
    if (modelRuntime.getAvailableSnapshot().length === 0) {
      const registered = modelRuntime.getRegisteredProviderIds();
      return {
        ok: false,
        type: "no_model",
        message:
          "no model available after extension registration — set a provider API key (e.g. " +
          "ANTHROPIC_API_KEY), save a credential for a provider in the agent dir's auth.json, " +
          `or pass --model; extension-registered providers: ${registered.length > 0 ? registered.join(", ") : "none"}.`,
        warning: resolved.warning,
      };
    }
    return { ok: true, model: undefined, thinkingLevel: undefined, warning: resolved.warning };
  }
  const provider = model.provider;
  const admitted =
    modelRuntime.hasConfiguredAuth(provider) ||
    (await modelRuntime.checkAuth(provider)) !== undefined;
  if (!admitted) {
    return {
      ok: false,
      type: "model_auth",
      message:
        `model ${provider}/${model.id} has no configured auth — set the provider's API key env ` +
        `var or save a credential for '${provider}' in the agent dir's auth.json, or pass a ` +
        "different --model.",
      warning: resolved.warning,
    };
  }
  return { ok: true, model, thinkingLevel: resolved.thinkingLevel, warning: resolved.warning };
}

/**
 * A typed selection refusal travelling out of the SDK runtime factory (a factory must resolve to
 * a session or reject); `defaultCreateRuntime` converts it into `{ ok: false, refusal }`.
 */
class WorkerModelRefusal extends Error {
  readonly refusal: { type: WorkerModelRefusalType; message: string };

  constructor(pick: Extract<WorkerModelPick, { ok: false }>) {
    super(pick.message);
    this.name = "WorkerModelRefusal";
    this.refusal = { type: pick.type, message: pick.message };
  }
}

// --- the production runtime factory ---------------------------------------------------------------

/** The production factory's result: a live runtime, or a typed zero-turn selection refusal. */
export type RuntimeConstruction =
  | { ok: true; runtime: DriveRuntimeLike }
  | { ok: false; refusal: { type: WorkerModelRefusalType; message: string } };

/**
 * Build the asymmetric runtime: `cwd = worktree` (project tier — perk's `@mgiles/perk` extension via the
 * managed `.pi/settings.json`, any project `.pi/extensions/`, the managed `AGENTS.md`/`APPEND_SYSTEM.md`)
 * and `agentDir = throwaway` (user-global RESOURCES out — the throwaway dir has no `settings.json`,
 * extensions or skills, so the global resource tier is empty). Auth + `models.json` come from the
 * worker-minted `ModelRuntime` instead: `request.modelRuntime ?? ModelRuntime.create()` (the global
 * agent dir's `auth.json`/`models.json`, `PI_CODING_AGENT_DIR`-aware, plus env keys; offline),
 * minted INSIDE this function's failure-cleanup guard so a rejection is the seam's
 * `runtime_init`. Settings are DISK-LAYERED (`SettingsManager.create` + `applyOverrides`, the
 * SDK's sanctioned "with overrides" shape — docs/sdk.md "Settings Management"): the project tier
 * resolves the managed `packages` list, while the compaction-off/retry-off determinism overrides
 * ride the merged view only (package resolution reads the per-scope raws — overrides cannot leak
 * into it). Missing `npm:` packages auto-install into `.pi/npm` during the loader's reload
 * (skipped under `PI_OFFLINE`); an install failure throws → the seam's catch arm → a loud
 * `failed`/`runtime_init`. No `tools` allowlist — read-write defaults + extension tools.
 *
 * The selection ladder runs inside the SDK runtime factory, mirroring pi's own CLI order:
 * services (extension load + registrations) → `selectWorkerModel` (explicit resolution,
 * admission) → `createAgentSessionFromServices`. A ladder refusal returns
 * `{ ok: false, refusal }`; every other construction error rethrows.
 *
 * Adapter-owned inputs only (`worktree` + the nominal request): no seam type appears in the
 * signature, so a reverse seam←adapter type edge is impossible by construction. The throwaway
 * `mkdtempSync` agentDir is best-effort removed (fail-soft `rm`; a removal failure logs and
 * never affects the outcome) at exactly two moments — dispose, and a construction failure or
 * refusal that would otherwise orphan it — the isolation invariant is untouched: no removal
 * while the session lives.
 */
export async function defaultCreateRuntime(
  worktree: string,
  request: WorkerModelRequest,
): Promise<RuntimeConstruction> {
  const agentDir = mkdtempSync(join(tmpdir(), "perk-worker-agent-"));
  const removeAgentDir = (): void => {
    try {
      rmSync(agentDir, { recursive: true, force: true });
    } catch (err) {
      console.error(`perk worker: throwaway agentDir removal failed — ${String(err)}`);
    }
  };
  try {
    const modelRuntime = request.modelRuntime ?? (await ModelRuntime.create());
    const runtime = await constructRuntime(
      worktree,
      request.pattern,
      modelRuntime,
      agentDir,
      removeAgentDir,
    );
    return { ok: true, runtime };
  } catch (err) {
    // Construction failed before the disposer-wrapping runtime existed — without this arm every
    // failed worker invocation would leak its `perk-worker-agent-*` directory.
    removeAgentDir();
    if (err instanceof WorkerModelRefusal) return { ok: false, refusal: err.refusal };
    throw err;
  }
}

/**
 * The construction body behind `defaultCreateRuntime`'s failure-cleanup guard. Services MUST
 * receive the worker-minted `modelRuntime`: left to itself, `createAgentSessionServices` would
 * derive a runtime from the throwaway `agentDir` — an empty auth store. The factory re-runs
 * identically on a session replacement (`/new`, `/resume`, fork).
 */
async function constructRuntime(
  worktree: string,
  pattern: string | undefined,
  modelRuntime: ModelRuntime,
  agentDir: string,
  removeAgentDir: () => void,
): Promise<DriveRuntimeLike> {
  const settingsManager = SettingsManager.create(worktree, agentDir);
  settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } });
  const reportSettingsErrors = (): void => {
    for (const entry of settingsManager.drainErrors()) {
      console.error(`perk worker: settings error (${entry.scope}) — ${String(entry.error)}`);
    }
  };
  const factory: CreateAgentSessionRuntimeFactory = async (factoryOpts) => {
    // 1. Services: load the project extensions and apply their provider / native-provider /
    //    virtual-model registrations onto the runtime, then refresh its availability.
    const services = await createAgentSessionServices({
      cwd: factoryOpts.cwd,
      agentDir: factoryOpts.agentDir,
      settingsManager,
      modelRuntime,
    });
    // 2. Loud construction diagnostics, before selection: extension load errors and
    //    registration errors are recorded, not raised, by the SDK — they are the CAUSE behind a
    //    later `model_not_found`/`no_model` (an extension that never loaded registers nothing)
    //    or `no_extension_tools`. Fail-soft reporting only; never throws.
    for (const entry of services.resourceLoader.getExtensions().errors) {
      console.error(`perk worker: extension load error — ${entry.path}: ${entry.error}`);
    }
    for (const entry of services.diagnostics) {
      if (entry.type !== "info") {
        console.error(`perk worker: extension ${entry.type} — ${entry.message}`);
      }
    }
    // 3. Selection + admission over the post-registration runtime.
    const pick = await selectWorkerModel(pattern, services.modelRuntime);
    if (!pick.ok) {
      reportSettingsErrors();
      throw new WorkerModelRefusal(pick);
    }
    if (pick.warning) console.error(`perk worker: ${pick.warning}`);
    // 4. Construction: an `undefined` model ⇒ the SDK's `findInitialModel` chain (saved default
    //    with configured auth → curated per-provider defaults → first available); an
    //    `undefined` thinkingLevel likewise defers to the settings default.
    const result = await createAgentSessionFromServices({
      services,
      sessionManager: factoryOpts.sessionManager,
      sessionStartEvent: factoryOpts.sessionStartEvent,
      model: pick.model,
      thinkingLevel: pick.thinkingLevel,
    });
    // Name the model that will actually drive (the SDK may have picked it) — the remote step
    // log is otherwise silent about it until a provider error.
    const chosen = result.session.model;
    console.error(
      `perk worker: model ${chosen ? `${chosen.provider}/${chosen.id}` : "unresolved"}`,
    );
    // Settings I/O errors are likewise recorded, not raised; drained after construction so the
    // session's own settings reads are included.
    reportSettingsErrors();
    return { ...result, services, diagnostics: services.diagnostics };
  };
  const runtime = await createAgentSessionRuntime(factory, {
    cwd: worktree,
    agentDir,
    sessionManager: SessionManager.create(worktree),
  });
  const inner = runtime as unknown as DriveRuntimeLike;
  return {
    get session(): DriveSessionLike {
      return inner.session;
    },
    async dispose(): Promise<void> {
      try {
        await inner.dispose();
      } finally {
        // Close the throwaway-agentDir leak at the one safe moment (post-dispose); a removal
        // failure logs and never affects the outcome.
        removeAgentDir();
      }
    },
  };
}
