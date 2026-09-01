// The PRIVATE SDK adapter behind the stage-execution seam (contracts.md §8.11).
//
// Every `@earendil-works/*` import on the drive path lives HERE — construction, raw session
// events (translated at the boundary into the perk-owned `StageEvent` union), and prompt/abort
// ownership are adapter-confined so the seam (`stageExecution.ts`) carries no SDK vocabulary on
// its caller surface and folds policy (budget, terminal capture, outcome) over perk shapes only. The only production
// importer is the seam itself (enforced by `extension/importDirectionGuard.test.ts` Rule F);
// tests import this module deliberately (to mint `WorkerModelSelection` and drive the handle).
//
// The opacity contract (narrow, stated exactly): `WorkerModelSelection` is *nominal* —
// `#private` fields make structural forgery impossible — and is minted only here (production
// imports of this module are guard-banned outside the seam). SDK types still appear on this
// adapter-owned class surface; the caller-side guarantee is the import-edge ban plus nominal
// minting, nothing stronger.

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
  if (event.type === "turn_end") {
    const usage = event.message?.usage;
    const freshTokens = usage ? Math.max(0, usage.input ?? 0) + Math.max(0, usage.output ?? 0) : 0;
    return { kind: "turn_ended", freshTokens };
  }
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
 */
export function createDriveSession(
  runtime: DriveRuntimeLike,
  listener: (event: StageEvent) => void,
) {
  const binding = headlessBinding();
  let bound: DriveSessionLike = runtime.session;
  let unsubscribe: (() => void) | null = null;
  let retainedAbort: Promise<void> | null = null;
  const rawListener = (event: DriveEvent): void => {
    const translated = translateEvent(event);
    if (translated !== null) listener(translated);
  };

  async function bindTo(target: DriveSessionLike): Promise<void> {
    if (unsubscribe) unsubscribe();
    await target.bindExtensions(binding);
    unsubscribe = target.subscribe(rawListener);
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

// --- model/auth (Gap 5), unified around one nominal type ------------------------------------------

/**
 * The opaque model input the seam's `StageRunOptions.model` carries. NOMINAL: the `#private`
 * fields make structural forgery impossible — a selection is minted only by this adapter
 * (`resolveWorkerModel`/`resolveAuth`) and by tests that import the adapter deliberately. The
 * SDK-typed reads below are adapter-internal by the import-edge ban (Rule F); they appear on
 * this adapter-owned surface only.
 */
export class WorkerModelSelection {
  // The ONE `#private` field supplies the nominal guarantee; the payload rides ordinary readonly
  // fields. (Constructor parameter properties would be smaller still, but node's type-stripping
  // test runner rejects non-erasable TS syntax.)
  readonly #modelRuntime: ModelRuntime;
  /** The EXPLICIT model only; `undefined` defers the pick to the SDK at session creation. */
  readonly model: Model<Api> | undefined;
  /**
   * Thinking level parsed from the `--model <pattern>:<level>` suffix (`resolveWorkerModel`).
   * `undefined` ⇒ the SDK's settings-default resolution — unchanged behavior.
   */
  readonly thinkingLevel: ThinkingLevel | undefined;

  constructor(modelRuntime: ModelRuntime, model?: Model<Api>, thinkingLevel?: ThinkingLevel) {
    this.#modelRuntime = modelRuntime;
    this.model = model;
    this.thinkingLevel = thinkingLevel;
  }

  /** The canonical model/auth runtime (pi 0.84 `ModelRuntime`). */
  get modelRuntime(): ModelRuntime {
    return this.#modelRuntime;
  }
}

/** What a `--model` flag resolves to — discriminated so no contradictory state is expressible. */
export type ResolvedWorkerModel =
  | { ok: true; selection: WorkerModelSelection; warning: string | undefined }
  | { ok: false; error: string; warning: string | undefined };

/**
 * Resolve an explicit `--model` flag with pi's OWN CLI semantics (`resolveCliModel`): fuzzy
 * matching, bare-id resolution, `provider/pattern`, and a `:thinking` suffix — the same chain the
 * flag's string hits in an interactive pi launch, closing the warm/cold parity gap (cf.
 * docs/learned/workflow/execution-path-parity.md).
 *
 * `raw` absent **or `""`** ⇒ `ok: true` with a selection carrying only a default-created
 * `ModelRuntime` (model/thinking undefined — the SDK's own initial-model resolution at session
 * creation stays the default). The `""` ≡ omitted equivalence is deliberate: workerMain's flag
 * grammar produces `""` for a bare `--model`, and the tolerance is pinned by a test. A
 * resolution that yields neither a model nor an error is normalized to the worker's not-found
 * error (`ok: false` — fail fast, never guess). `warning` is a non-fatal resolution diagnostic
 * (e.g. an invalid `:thinking` suffix) — the caller surfaces it only when proceeding.
 *
 * The optional `modelRuntime` param is the test-injection seam (deterministic `stubRuntime`
 * tests); `ModelRuntime.create()` runs only when it is absent.
 */
export async function resolveWorkerModel(
  raw: string | undefined,
  modelRuntime?: ModelRuntime,
): Promise<ResolvedWorkerModel> {
  const runtime = modelRuntime ?? (await ModelRuntime.create());
  if (!raw) {
    return { ok: true, selection: new WorkerModelSelection(runtime), warning: undefined };
  }
  const result = resolveCliModel({ cliModel: raw, modelRuntime: runtime });
  if (result.model === undefined && result.error === undefined) {
    return {
      ok: false,
      error: `model '${raw}' not found in the registry.`,
      warning: result.warning,
    };
  }
  if (result.error !== undefined) {
    return { ok: false, error: result.error, warning: result.warning };
  }
  return {
    ok: true,
    selection: new WorkerModelSelection(runtime, result.model, result.thinkingLevel),
    warning: result.warning,
  };
}

/**
 * Normalize the seam's optional model input for the production drive path; returns null (never
 * throws a domain error) when no model is available at all. `selection` absent ⇒ a
 * default-runtime selection (async because pi 0.84's `ModelRuntime.create` is async; the default
 * creation stays offline — `allowModelNetwork` defaults false). `null` iff there is no explicit
 * model AND `getAvailableSnapshot()` is empty — the `no_model` fail-fast, unchanged. The model is
 * NOT pre-pinned from the runtime: an `undefined` model lets `createAgentSession` run its own
 * initial-model resolution (settings `defaultModel` → pi's curated per-provider defaults → first
 * available), which picks a current-generation model instead of the catalogue's
 * alphabetically-first (= oldest) entry.
 */
export async function resolveAuth(
  selection: WorkerModelSelection | undefined,
): Promise<WorkerModelSelection | null> {
  const effective = selection ?? new WorkerModelSelection(await ModelRuntime.create());
  if (!effective.model && effective.modelRuntime.getAvailableSnapshot().length === 0) return null;
  return effective;
}

// --- the production runtime factory ---------------------------------------------------------------

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
 * the seam's catch arm → a loud `failed`/`drive_error`. No `tools` allowlist — read-write
 * defaults + extension tools. The `createAgentSessionServices` factory builds the
 * `DefaultResourceLoader` internally from `cwd`/`agentDir` (recipe correction #1).
 *
 * Adapter-owned inputs only (`worktree` + the nominal selection): no seam type appears in the
 * signature, so a reverse seam←adapter type edge is impossible by construction. The throwaway
 * `mkdtempSync` agentDir is best-effort removed (fail-soft `rm`; a removal failure logs and
 * never affects the outcome) at exactly two moments — dispose, and a construction failure that
 * would otherwise orphan it — the isolation invariant is untouched: no removal while the
 * session lives.
 */
export async function defaultCreateRuntime(
  worktree: string,
  selection: WorkerModelSelection,
): Promise<DriveRuntimeLike> {
  const agentDir = mkdtempSync(join(tmpdir(), "perk-worker-agent-"));
  const removeAgentDir = (): void => {
    try {
      rmSync(agentDir, { recursive: true, force: true });
    } catch (err) {
      console.error(`perk worker: throwaway agentDir removal failed — ${String(err)}`);
    }
  };
  try {
    return await constructRuntime(worktree, selection, agentDir, removeAgentDir);
  } catch (err) {
    // Construction failed before the disposer-wrapping runtime existed — without this arm every
    // failed worker invocation would leak its `perk-worker-agent-*` directory.
    removeAgentDir();
    throw err;
  }
}

/** The construction body behind `defaultCreateRuntime`'s failure-cleanup guard. */
async function constructRuntime(
  worktree: string,
  selection: WorkerModelSelection,
  agentDir: string,
  removeAgentDir: () => void,
): Promise<DriveRuntimeLike> {
  const settingsManager = SettingsManager.create(worktree, agentDir);
  settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } });
  const factory: CreateAgentSessionRuntimeFactory = async (factoryOpts) => {
    const services = await createAgentSessionServices({
      cwd: factoryOpts.cwd,
      agentDir: factoryOpts.agentDir,
      settingsManager,
      modelRuntime: selection.modelRuntime,
    });
    const result = await createAgentSessionFromServices({
      services,
      sessionManager: factoryOpts.sessionManager,
      sessionStartEvent: factoryOpts.sessionStartEvent,
      // `undefined` ⇒ the SDK's initial-model resolution picks the model (see `resolveAuth`);
      // an `undefined` thinkingLevel likewise defers to the settings default.
      model: selection.model,
      thinkingLevel: selection.thinkingLevel,
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
