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
// drift tripwire, and every pi-subagents bump warrants an adapter re-verify. Re-verified at
// 0.75.0: `spawn` takes the inline script text as `script` (0.74.0 removed `workflowScript`/
// `workflowScriptPath`; 0.75.0 rejects them `invalid_params` with the message naming `script`).
// Re-verified at 0.76.1 (`src/extension/rpc.js`): both spawn keys are still rejected
// `invalid_params` (`workflowScriptPath` with its own message); the RPC `stop` (its own
// `stopAsyncRun`, not the model-facing tool action) replies `{runId, asyncDir, previousState,
// state: "stopping", message: "Stop requested for async run <id>."}` — a request, never exit proof
// — or refuses with a typed `not_found` / `invalid_state` / `execution_failed` error (e.g.
// `Workflow <id> has no live run controller available to stop.`: workflow controllers live
// in-process, so a persisted run dir cannot restore them after a reload); `status {id}` replies
// `{text, details, fleet, asyncSnapshot}` with the workflow terminal proof at
// `details.workflowTerminalProof`.
//
// TERMINAL PROOF (source-read-derived, 0.76.1 `src/runs/background/run-status.js` +
// `src/runs/background/workflow-terminal-proof.js::readWorkflowTerminalProof`): the proof is
// `observed` only after dispatch closed AND every async child has resolved process evidence — an
// observed runner exit, or a recorded never-started launch failure — otherwise `pending` or
// `unknown` with a reason. perk reads it ONCE, after its own stop, for diagnostics only: it never
// touches reports, receipt children, coverage or completeness, is never polled, and a stop
// acknowledgement never upgrades it. The model-facing stop action (`async-stop-action.js`, which
// seals a delivered paused run) is a different implementation perk never calls.
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
// of receipts; a row the engine projects as `state: "running"` (a child still working when the
// workflow deadline fired — it carries no `success`) projects to an explicit `ok: false` entry so
// the normalizer reports the lane as failed, never as a malformed report. 0.81.0
// (`src/runs/foreground/subagent-executor.js`) builds the partial `results` from the settled
// children only, so a lane still running at the deadline can be absent from `results` and present
// only in the `workflowChildren` roster with `state: "running"`; perk derives only that lane's KEY
// from the correlated inventory (`unfinishedLanes`), never report DATA. The runner retains only
// its first matched completion, never a report cache.

import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  LANE_STILL_RUNNING_ERROR,
  type WaveAdapter,
  type WaveAggregate,
  type WaveBus,
  type WaveChildReceipt,
  type WaveCompletion,
  type WavePing,
  type WaveRunHandle,
  type WaveSpawnParams,
  type WaveStopOutcome,
  type WaveTerminationProof,
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

function errorDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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

// The `workflowChildren` envelope check: undefined when absent; an EMPTY list when present but
// not a version-1 inventory bound to this completion's workflow run id (a withheld inventory);
// otherwise the raw children.
function inventoryChildren(data: Record<string, unknown>): unknown[] | undefined {
  if (!("workflowChildren" in data)) return undefined;
  const inventory = data.workflowChildren;
  const runId = data.id ?? data.runId;
  if (
    !isRecord(inventory) ||
    inventory.version !== 1 ||
    typeof runId !== "string" ||
    inventory.workflowRunId !== runId ||
    !Array.isArray(inventory.children)
  )
    return [];
  return inventory.children;
}

// A present malformed/mismatched inventory withholds correlation rather than inventing keys
// from agent names. Duplicate run identities are ambiguous, even when their childIds agree.
function workflowReceiptKeys(
  data: Record<string, unknown>,
): Map<string, string | null> | undefined {
  const children = inventoryChildren(data);
  if (children === undefined) return undefined;
  const keys = new Map<string, string | null>();
  for (const child of children) {
    if (!isRecord(child) || typeof child.runId !== "string" || child.runId === "") continue;
    const key = typeof child.childId === "string" && child.childId !== "" ? child.childId : null;
    keys.set(child.runId, keys.has(child.runId) ? null : key);
  }
  return keys;
}

/**
 * The roster-only lanes still running at native partial settlement (contracts.md §8.35), in
 * inventory order — identity only. Reuses the receipt correlation map (`keys`): no inventory or a
 * withheld one diagnoses nothing. A child qualifies only when its state is `running`, its nonempty
 * `runId` maps uniquely to its own nonempty `childId` (a duplicated run id maps to null), that
 * `childId` is unique in the inventory, and no `results` row carries its key or its run id (the
 * carrier already speaks for that run).
 */
function unfinishedRosterLanes(
  data: Record<string, unknown>,
  keys: Map<string, string | null> | undefined,
): string[] {
  if (keys === undefined || keys.size === 0) return [];
  const children = inventoryChildren(data) ?? [];
  const childIdCounts = new Map<string, number>();
  for (const child of children) {
    if (isRecord(child) && typeof child.childId === "string" && child.childId !== "") {
      childIdCounts.set(child.childId, (childIdCounts.get(child.childId) ?? 0) + 1);
    }
  }
  const carriedKeys = new Set<string>();
  const carriedRuns = new Set<string>();
  if (Array.isArray(data.results)) {
    for (const row of data.results) {
      if (!isRecord(row)) continue;
      if (typeof row.workflowKey === "string") carriedKeys.add(row.workflowKey);
      if (typeof row.runId === "string") carriedRuns.add(row.runId);
    }
  }
  const unfinished: string[] = [];
  for (const child of children) {
    if (!isRecord(child) || child.state !== "running") continue;
    const { childId, runId } = child;
    if (typeof childId !== "string" || childId === "") continue;
    if (typeof runId !== "string" || runId === "") continue;
    if (keys.get(runId) !== childId || childIdCounts.get(childId) !== 1) continue;
    if (carriedKeys.has(childId) || carriedRuns.has(runId)) continue;
    unfinished.push(childId);
  }
  return unfinished;
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
    entries.set(
      key,
      row.state === "running"
        ? { key, ok: false, error: LANE_STILL_RUNNING_ERROR, report: null }
        : {
            key,
            ok: row.success ?? null,
            error: typeof row.error === "string" ? row.error : null,
            report: row.structuredOutput ?? null,
          },
    );
  }
  return [...entries.values()].map((entry) =>
    ambiguous.has(entry.key) ? { key: entry.key, ok: null, error: null, report: null } : entry,
  );
}

/**
 * Project a `status` reply onto the termination-proof vocabulary (module header, TERMINAL PROOF).
 * Only the engine's own `observed` state reads as observed; `pending`/`unknown` keep the engine's
 * reason; a reply without an object `details.workflowTerminalProof` carrying one of those three
 * states is `unavailable`. Pure; never throws.
 */
export function narrowTerminalProof(data: unknown): WaveTerminationProof {
  const details = isRecord(data) && isRecord(data.details) ? data.details : {};
  const proof = details.workflowTerminalProof;
  if (isRecord(proof)) {
    if (proof.state === "observed") return { state: "observed" };
    if (proof.state === "pending" || proof.state === "unknown") {
      const reason =
        typeof proof.reason === "string" && proof.reason !== "" ? proof.reason : "no reason given";
      return { state: proof.state, reason };
    }
  }
  return { state: "unavailable", reason: "status reply carried no workflow terminal proof" };
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

    // The params object is forwarded verbatim as the request's `params`, so the wire key is
    // `WaveSpawnParams.script`. A `success: false` reply's `code: message` (the engine's
    // `disabledFeatures` setting-naming error included) surfaces verbatim as the `spawn-failed`
    // detail — no perk-side mapping, no retry under another parameter dialect.
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
        const unfinished = terminalOutcome !== undefined ? unfinishedRosterLanes(data, keys) : [];
        handler({
          ...(typeof data.id === "string" ? { asyncId: data.id } : {}),
          ...(typeof data.asyncDir === "string" ? { asyncDir: data.asyncDir } : {}),
          ...(typeof data.state === "string" && data.state !== "" ? { state: data.state } : {}),
          ...(typeof data.success === "boolean" ? { success: data.success } : {}),
          ...(children !== undefined ? { children } : {}),
          ...(terminalOutcome !== undefined
            ? {
                terminalOutcome,
                retainedEntries: narrowRetainedEntries(data.results),
                ...(unfinished.length > 0 ? { unfinishedLanes: unfinished } : {}),
              }
            : {}),
        });
      });
    },

    // The success reply's data shape is not inspected: `state: "stopping"` is a request either
    // way. Every rejection — a typed refusal, a held-then-timed-out reply, silence — becomes the
    // outcome's reason verbatim; the method never throws.
    async stop(handle: WaveRunHandle): Promise<WaveStopOutcome> {
      try {
        await call("stop", { id: handle.asyncId }, replyTimeoutMs());
        return { acknowledged: true };
      } catch (error) {
        return { acknowledged: false, reason: errorDetail(error) };
      }
    },

    // ONE status query; the context-less hold applies like any other method. Never throws.
    async terminalProof(handle: WaveRunHandle): Promise<WaveTerminationProof> {
      let data: unknown;
      try {
        data = await call("status", { id: handle.asyncId }, replyTimeoutMs());
      } catch (error) {
        return { state: "unavailable", reason: errorDetail(error) };
      }
      return narrowTerminalProof(data);
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
