// The production `WaveAdapter` over the pi-subagents v1 extension RPC seam, pure over pi's
// in-process event bus (unit-testable offline with a fake bus + a fake RPC responder, exactly
// like the plannotator bridge).
//
// ENVELOPE (pinned against pi-subagents 0.43.0, re-verified at 0.45.0; `src/extension/rpc.ts`):
// requests are emitted on
// `subagents:rpc:v1:request` as `{version: 1, requestId, method, params?, source?}`; the reply
// arrives once on `subagents:rpc:v1:reply:<requestId>` as
// `{version, requestId, method?, success: true, data} | {…, success: false, error: {code, message}}`.
// `ping` works even with no active session and advertises capabilities plus the event channel
// names — `events.asyncComplete` is the ADVERTISED async-complete channel, deliberately NOT
// pinned here (only the versioned request/reply literals are; that is what the versioned
// envelope is for). `pi-subagents` is not an allowed bare import (`bareImportGuard.test.ts`), so
// its constants/types cannot be imported — the doctor `subagent-compat` version warning is the
// drift tripwire, and every pi-subagents bump warrants an adapter re-verify.
//
// REPLY SELECTION (the context-less hold): pi's two-phase trust load (pi 0.85.1,
// `loadProjectTrustExtensions` → `loadFinalExtensionSet`) loads the USER-scope packages'
// extensions before project trust resolves and then drops a user-scope duplicate of the
// project's pi-subagents from the final set WITHOUT invalidating it — its factory already
// subscribed its RPC bridge on the shared `pi.events` bus, and event-bus subscriptions are
// cleared only on `runtime.invalidate()`. The orphan never receives `session_start`, so its
// `getContext()` stays null forever: `ping` still succeeds (it needs no ctx), but every other
// method throws `no_active_session` synchronously BEFORE any work — milliseconds before the live
// instance's success reply on the same per-request channel. A first-reply policy would settle on
// the ghost's error while the wave actually launched (orphaned). So `request()` HOLDS a
// `no_active_session` reply and keeps listening: a later success wins (and the superseded reply
// is reported through the fail-open `onDuplicateResponder` callback), any DIFFERENT error
// surfaces immediately (the live instance's real diagnosis is never masked), and only the reply
// timeout surfaces the held error (suffixed). `ping` stays first-reply: the context-less
// responder cannot fail it.
//
// COMPLETION PAYLOAD (source-read-derived, 0.45.0 `src/runs/background/result-watcher.ts` +
// `src/runs/foreground/subagent-executor.ts`): the async-complete event spreads the result-file
// data plus a normalized per-child `results` array. Current engines provide workflow childIds
// separately in `workflowChildren`, correlated by runId; legacy payloads overload `agent` with
// the lane key. Normalization is defensively output-free: `output`/`summary`/
// `structuredOutput` never enter a receipt child, unknown fields are ignored, and malformed
// rows are dropped without failing the wave (receipt absence degrades correlation only).
// Explicit native partial settlement additionally carries keyed structured results, independently
// of receipts. The runner retains only its first matched completion, never a report cache.

import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type {
  WaveAdapter,
  WaveAggregate,
  WaveBus,
  WaveChildReceipt,
  WaveCompletion,
  WavePing,
  WaveRunHandle,
  WaveSpawnParams,
} from "./transport.ts";

/** The pinned v1 request channel (pi-subagents `SUBAGENT_RPC_REQUEST_EVENT`). */
export const WAVE_RPC_REQUEST_EVENT = "subagents:rpc:v1:request";
/** The pinned v1 reply-channel prefix (pi-subagents `SUBAGENT_RPC_REPLY_EVENT_PREFIX`). */
export const WAVE_RPC_REPLY_EVENT_PREFIX = "subagents:rpc:v1:reply:";
/** The pinned v1 protocol version. */
export const WAVE_RPC_PROTOCOL_VERSION = 1;
/**
 * The pi-subagents `SubagentRpcErrorCode` a responder throws — before any work — when it holds no
 * extension context (`src/extension/rpc.ts::handleRequest`, re-verified at 0.68.0; `ping` is
 * exempt). Held rather than surfaced: see the module header's REPLY SELECTION paragraph.
 */
export const WAVE_RPC_CONTEXTLESS_ERROR_CODE = "no_active_session";

/**
 * The ping reply timeout: fast loud-degrade when pi-subagents is absent (ping is a pure
 * in-process lookup on the responder side). Overridable for tests via PERK_WAVE_RPC_PING_MS.
 */
export const WAVE_RPC_PING_TIMEOUT_MS = 5_000;

/**
 * The reply timeout for the working methods (spawn does real work: writes run files, forks the
 * detached process). Overridable for tests via PERK_WAVE_RPC_REPLY_MS.
 */
export const WAVE_RPC_REPLY_TIMEOUT_MS = 30_000;

function envTimeoutMs(name: string, fallback: number): number {
  const raw = Number(process.env[name] ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

function pingTimeoutMs(): number {
  return envTimeoutMs("PERK_WAVE_RPC_PING_MS", WAVE_RPC_PING_TIMEOUT_MS);
}

function replyTimeoutMs(): number {
  return envTimeoutMs("PERK_WAVE_RPC_REPLY_MS", WAVE_RPC_REPLY_TIMEOUT_MS);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * One superseded context-less reply: a `no_active_session` error that a later success on the
 * same request overrode. `superseded` is the held reply's `code: message`.
 */
export interface DuplicateResponderEvent {
  method: string;
  superseded: string;
}

export interface RpcWaveAdapterOptions {
  /**
   * Observability only, invoked FAIL-OPEN (a throwing callback is logged and never affects
   * settlement) exactly once per request that resolved past a held context-less reply.
   */
  onDuplicateResponder?: (event: DuplicateResponderEvent) => void;
}

/** The `code: message` narrowing of a `success: false` reply's error record. */
function replyError(data: Record<string, unknown>): { code: string; text: string } {
  const error = isRecord(data.error) ? data.error : {};
  const code = typeof error.code === "string" ? error.code : "unknown_error";
  const message = typeof error.message === "string" ? error.message : "no error detail";
  return { code, text: `${code}: ${message}` };
}

/**
 * One v1 request/reply round trip: subscribe the per-request reply channel (disposed via the
 * returned unsubscribe once settled), emit the request envelope, await the reply within
 * `timeoutMs`. Reply policy, uniform for every method:
 *
 * - `success: true` → resolve `data` (a held context-less reply is first reported fail-open).
 * - `success: false` with `WAVE_RPC_CONTEXTLESS_ERROR_CODE` → HOLD the first one and keep
 *   listening (later identical replies are ignored; the timer keeps running).
 * - `success: false` with any other code → reject with `code: message` immediately, even over a
 *   held reply (the live instance's diagnosis wins; the held error is discarded).
 * - a non-object reply → reject immediately.
 * - timeout → reject with the held `code: message` (suffixed) when one is held, else the plain
 *   timeout error.
 *
 * Every arm settles exactly once: the timer is cleared and the reply subscription disposed.
 */
async function request(
  bus: WaveBus,
  method: string,
  params: unknown,
  timeoutMs: number,
  onDuplicateResponder?: (event: DuplicateResponderEvent) => void,
): Promise<unknown> {
  const requestId = randomUUID();
  return await new Promise<unknown>((resolve, reject) => {
    let settled = false;
    let held: string | null = null;
    const settle = (fn: () => void): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      unsubscribe();
      fn();
    };
    const unsubscribe = bus.on(`${WAVE_RPC_REPLY_EVENT_PREFIX}${requestId}`, (data) => {
      if (!isRecord(data)) {
        settle(() => reject(new Error(`subagent RPC ${method} reply is not an object`)));
        return;
      }
      if (data.success === true) {
        if (held !== null && onDuplicateResponder !== undefined) {
          const superseded = held;
          try {
            onDuplicateResponder({ method, superseded });
          } catch (error) {
            console.error(`perk: waves — onDuplicateResponder callback threw: ${error}`);
          }
        }
        settle(() => resolve(data.data));
        return;
      }
      const error = replyError(data);
      if (error.code === WAVE_RPC_CONTEXTLESS_ERROR_CODE) {
        held ??= error.text;
        return;
      }
      settle(() => reject(new Error(error.text)));
    });
    const timer = setTimeout(() => {
      const detail =
        held === null
          ? `subagent RPC ${method} timed out after ${timeoutMs}ms`
          : `${held} (held for a later reply that never arrived within ${timeoutMs}ms)`;
      settle(() => reject(new Error(detail)));
    }, timeoutMs);
    bus.emit(WAVE_RPC_REQUEST_EVENT, {
      version: WAVE_RPC_PROTOCOL_VERSION,
      requestId,
      method,
      ...(params !== undefined ? { params } : {}),
      source: { extension: "perk" },
    });
  });
}

/**
 * Narrow one completion-payload `results` row's `artifactPaths` to its string-valued own
 * properties; when none survive, fall back to the watcher-normalized `artifactPath` as
 * `{ outputPath }`. Undefined when neither yields a path.
 */
function narrowArtifactPaths(row: Record<string, unknown>): Record<string, string> | undefined {
  if (isRecord(row.artifactPaths)) {
    const paths: Record<string, string> = {};
    for (const [key, value] of Object.entries(row.artifactPaths)) {
      if (typeof value === "string") paths[key] = value;
    }
    if (Object.keys(paths).length > 0) return paths;
  }
  if (typeof row.artifactPath === "string" && row.artifactPath !== "") {
    return { outputPath: row.artifactPath };
  }
  return undefined;
}

/**
 * Narrow one `results` row into an output-free receipt child; null ⇒ the row is dropped (a
 * malformed row never fails the wave). Use run-correlated native childIds when the inventory is
 * present; only legacy inventory-absent payloads use overloaded `agent`. Agent names are enriched
 * from Perk-owned specs upstream. Output/summary/structuredOutput are NEVER copied.
 */
function narrowReceiptChild(
  row: unknown,
  keys: Map<string, string | null> | undefined,
): WaveChildReceipt | null {
  if (!isRecord(row)) return null;
  const key =
    keys === undefined
      ? row.agent
      : typeof row.runId === "string"
        ? keys.get(row.runId)
        : undefined;
  if (typeof key !== "string" || key === "") return null;
  const artifactPaths = narrowArtifactPaths(row);
  return {
    key,
    ...(typeof row.runId === "string" && row.runId !== "" ? { runId: row.runId } : {}),
    ...(typeof row.success === "boolean" ? { success: row.success } : {}),
    ...(row.outputState === "present" ||
    row.outputState === "absent" ||
    row.outputState === "unknown"
      ? { outputState: row.outputState }
      : {}),
    ...(artifactPaths !== undefined ? { artifactPaths } : {}),
  };
}

// A present malformed/mismatched inventory withholds correlation rather than inventing keys
// from agent names. Duplicate run identities are ambiguous, even when their childIds agree.
function workflowReceiptKeys(
  data: Record<string, unknown>,
): Map<string, string | null> | undefined {
  if (!("workflowChildren" in data)) return undefined;
  const keys = new Map<string, string | null>();
  const inventory = data.workflowChildren;
  const runId = data.id ?? data.runId;
  if (
    !isRecord(inventory) ||
    inventory.version !== 1 ||
    typeof runId !== "string" ||
    inventory.workflowRunId !== runId ||
    !Array.isArray(inventory.children)
  )
    return keys;
  for (const child of inventory.children) {
    if (!isRecord(child) || typeof child.runId !== "string" || child.runId === "") continue;
    const key = typeof child.childId === "string" && child.childId !== "" ? child.childId : null;
    keys.set(child.runId, keys.has(child.runId) ? null : key);
  }
  return keys;
}

// This is a narrow native envelope, not an inference from failure/notification prose.
function narrowPartialOutcome(data: Record<string, unknown>): WaveCompletion["terminalOutcome"] {
  if (data.state !== "failed" && data.state !== "partial") return undefined;
  const outcome = data.terminalOutcome;
  if (
    !isRecord(outcome) ||
    outcome.state !== "partial" ||
    (outcome.reason !== "timeout" && outcome.reason !== "budget_exhausted")
  )
    return undefined;
  return { state: "partial", reason: outcome.reason };
}

/** Project report DATA only by native workflowKey; ambiguous identities withhold evidence. */
function narrowRetainedEntries(results: unknown): unknown[] {
  if (!Array.isArray(results)) return [];
  const entries = new Map<
    string,
    { key: string; ok: unknown; error: string | null; report: unknown }
  >();
  const runKeys = new Map<string, string>();
  const ambiguous = new Set<string>();
  for (const row of results) {
    if (!isRecord(row) || typeof row.workflowKey !== "string" || row.workflowKey === "") continue;
    const key = row.workflowKey;
    if (entries.has(key)) ambiguous.add(key);
    if (typeof row.runId === "string" && row.runId !== "") {
      const previous = runKeys.get(row.runId);
      if (previous !== undefined && previous !== key) {
        ambiguous.add(previous);
        ambiguous.add(key);
      }
      runKeys.set(row.runId, key);
    }
    entries.set(key, {
      key,
      ok: row.success ?? null,
      error: typeof row.error === "string" ? row.error : null,
      report: row.structuredOutput ?? null,
    });
  }
  return [...entries.values()].map((entry) =>
    ambiguous.has(entry.key) ? { key: entry.key, ok: null, error: null, report: null } : entry,
  );
}

/** Narrow a ping reply to the advertised async-complete channel; any miss ⇒ null (unavailable). */
function narrowPing(data: unknown): WavePing | null {
  if (!isRecord(data)) return null;
  const capabilities = isRecord(data.capabilities) ? data.capabilities : {};
  if (capabilities.asyncSpawn !== true) return null;
  if (!Array.isArray(data.methods) || !data.methods.includes("spawn")) return null;
  const events = isRecord(data.events) ? data.events : {};
  const asyncComplete = events.asyncComplete;
  if (typeof asyncComplete !== "string" || asyncComplete === "") return null;
  return { asyncCompleteEvent: asyncComplete };
}

/**
 * Create the production wave adapter over pi's event bus. Sequencing contract (enforced): a
 * successful `ping()` must precede `onComplete()` — the completion channel name is taken from
 * ping's advertised `events.asyncComplete`, never pinned. `options.onDuplicateResponder` is the
 * fail-open observability seam for a superseded context-less reply (module header).
 */
export function createRpcWaveAdapter(bus: WaveBus, options?: RpcWaveAdapterOptions): WaveAdapter {
  let advertised: WavePing | null = null;
  const call = (method: string, params: unknown, timeoutMs: number): Promise<unknown> =>
    request(bus, method, params, timeoutMs, options?.onDuplicateResponder);

  return {
    async ping(): Promise<WavePing | null> {
      let data: unknown;
      try {
        // Effectively first-reply: pi-subagents' `pingData` needs no context, so the
        // context-less responder never answers ping with the held code, and the advertised
        // async-complete channel has been one constant across every verified release (two
        // loaded versions advertising different channels would time the wave out loudly,
        // never lose it silently — the accepted residual, §8.35).
        data = await call("ping", undefined, pingTimeoutMs());
      } catch {
        return null;
      }
      advertised = narrowPing(data);
      return advertised;
    },

    async spawn(params: WaveSpawnParams): Promise<WaveRunHandle> {
      const data = await call("spawn", params, replyTimeoutMs());
      const details = isRecord(data) && isRecord(data.details) ? data.details : {};
      const asyncId = details.asyncId;
      const asyncDir = details.asyncDir;
      if (typeof asyncId !== "string" || asyncId === "") {
        throw new Error("subagent RPC spawn reply carries no asyncId");
      }
      if (typeof asyncDir !== "string" || asyncDir === "") {
        throw new Error("subagent RPC spawn reply carries no asyncDir");
      }
      return { asyncId, asyncDir };
    },

    onComplete(handler: (completion: WaveCompletion) => void): () => void {
      if (advertised === null) {
        throw new Error(
          "onComplete requires a successful ping first (the async-complete channel is advertised, not pinned)",
        );
      }
      return bus.on(advertised.asyncCompleteEvent, (data) => {
        if (!isRecord(data)) return;
        // The payload spreads the result-file data: `id` is the async run id; `asyncDir` the
        // durable run directory. At least one is present on real payloads. The observability
        // fields (state/success/results) are optional — identity-only payloads stay valid.
        const terminalOutcome = narrowPartialOutcome(data);
        const keys = workflowReceiptKeys(data);
        const children = Array.isArray(data.results)
          ? data.results.flatMap((row) => {
              const child = narrowReceiptChild(row, keys);
              return child === null ? [] : [child];
            })
          : undefined;
        handler({
          ...(typeof data.id === "string" ? { asyncId: data.id } : {}),
          ...(typeof data.asyncDir === "string" ? { asyncDir: data.asyncDir } : {}),
          ...(typeof data.state === "string" && data.state !== "" ? { state: data.state } : {}),
          ...(typeof data.success === "boolean" ? { success: data.success } : {}),
          ...(children !== undefined ? { children } : {}),
          ...(terminalOutcome !== undefined
            ? { terminalOutcome, retainedEntries: narrowRetainedEntries(data.results) }
            : {}),
        });
      });
    },

    async stop(handle: WaveRunHandle): Promise<void> {
      try {
        await call("stop", { id: handle.asyncId }, replyTimeoutMs());
      } catch {
        // Best-effort by contract: the run may already be terminal, or the responder gone.
      }
    },

    async readAggregate(handle: WaveRunHandle): Promise<WaveAggregate> {
      const raw = readFileSync(join(handle.asyncDir, "status.json"), "utf8");
      const parsed: unknown = JSON.parse(raw);
      if (!isRecord(parsed) || typeof parsed.state !== "string") {
        throw new Error("status.json carries no state field");
      }
      const workflow = isRecord(parsed.workflow) ? parsed.workflow : {};
      return {
        state: parsed.state,
        ...(typeof parsed.error === "string" ? { error: parsed.error } : {}),
        value: workflow.value,
      };
    },
  };
}
