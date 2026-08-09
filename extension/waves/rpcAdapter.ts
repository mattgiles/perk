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
// its constants/types cannot be imported — the doctor `subagent-compat` probes are the drift
// tripwire, and every pi-subagents bump warrants an adapter re-verify.
//
// COMPLETION PAYLOAD (source-read-derived, 0.45.0 `src/runs/background/result-watcher.ts` +
// `src/runs/foreground/subagent-executor.ts`): the async-complete event spreads the result-file
// data plus a normalized per-child `results` array; on workflow rows the `agent` field carries
// the workflow LANE KEY (the overloaded upstream field — mapped to `WaveChildReceipt.key` here,
// never exposed). Normalization is defensively output-free: `output`/`summary`/
// `structuredOutput` never enter a receipt child, unknown fields are ignored, and malformed
// rows are dropped without failing the wave (receipt absence degrades correlation only).

import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type {
  WaveAdapter,
  WaveBus,
  WaveChildReceipt,
  WaveCompletion,
  WavePing,
  WaveRunHandle,
  WaveSpawnParams,
} from "./reportWave.ts";

/** The pinned v1 request channel (pi-subagents `SUBAGENT_RPC_REQUEST_EVENT`). */
export const WAVE_RPC_REQUEST_EVENT = "subagents:rpc:v1:request";
/** The pinned v1 reply-channel prefix (pi-subagents `SUBAGENT_RPC_REPLY_EVENT_PREFIX`). */
export const WAVE_RPC_REPLY_EVENT_PREFIX = "subagents:rpc:v1:reply:";
/** The pinned v1 protocol version. */
export const WAVE_RPC_PROTOCOL_VERSION = 1;

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
 * One v1 request/reply round trip: subscribe the per-request reply channel (disposed via the
 * returned unsubscribe once settled), emit the request envelope, await the reply within
 * `timeoutMs`. A `success: false` reply narrows to a thrown `Error` carrying `code: message`.
 */
async function request(
  bus: WaveBus,
  method: string,
  params: unknown,
  timeoutMs: number,
): Promise<unknown> {
  const requestId = randomUUID();
  return await new Promise<unknown>((resolve, reject) => {
    let settled = false;
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
        settle(() => resolve(data.data));
        return;
      }
      const error = isRecord(data.error) ? data.error : {};
      const code = typeof error.code === "string" ? error.code : "unknown_error";
      const message = typeof error.message === "string" ? error.message : "no error detail";
      settle(() => reject(new Error(`${code}: ${message}`)));
    });
    const timer = setTimeout(
      () =>
        settle(() => reject(new Error(`subagent RPC ${method} timed out after ${timeoutMs}ms`))),
      timeoutMs,
    );
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
 * malformed row never fails the wave). The upstream `agent` field carries the workflow lane key
 * — it becomes `key`; `agent` is deliberately left unset (enriched from Perk-owned lane specs
 * upstream). `output`/`summary`/`structuredOutput` and unknown fields are NEVER copied.
 */
function narrowReceiptChild(row: unknown): WaveChildReceipt | null {
  if (!isRecord(row)) return null;
  const key = row.agent;
  if (typeof key !== "string" || key === "") return null;
  const artifactPaths = narrowArtifactPaths(row);
  return {
    key,
    ...(typeof row.runId === "string" && row.runId !== "" ? { runId: row.runId } : {}),
    ...(typeof row.success === "boolean" ? { success: row.success } : {}),
    ...(row.outputState === "present" || row.outputState === "absent" || row.outputState === "unknown"
      ? { outputState: row.outputState }
      : {}),
    ...(artifactPaths !== undefined ? { artifactPaths } : {}),
  };
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
 * ping's advertised `events.asyncComplete`, never pinned.
 */
export function createRpcWaveAdapter(bus: WaveBus): WaveAdapter {
  let advertised: WavePing | null = null;

  return {
    async ping(): Promise<WavePing | null> {
      let data: unknown;
      try {
        data = await request(bus, "ping", undefined, pingTimeoutMs());
      } catch {
        return null;
      }
      advertised = narrowPing(data);
      return advertised;
    },

    async spawn(params: WaveSpawnParams): Promise<WaveRunHandle> {
      const data = await request(bus, "spawn", params, replyTimeoutMs());
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
        const children = Array.isArray(data.results)
          ? data.results.flatMap((row) => {
              const child = narrowReceiptChild(row);
              return child === null ? [] : [child];
            })
          : undefined;
        handler({
          ...(typeof data.id === "string" ? { asyncId: data.id } : {}),
          ...(typeof data.asyncDir === "string" ? { asyncDir: data.asyncDir } : {}),
          ...(typeof data.state === "string" && data.state !== "" ? { state: data.state } : {}),
          ...(typeof data.success === "boolean" ? { success: data.success } : {}),
          ...(children !== undefined ? { children } : {}),
        });
      });
    },

    async stop(handle: WaveRunHandle): Promise<void> {
      try {
        await request(bus, "stop", { id: handle.asyncId }, replyTimeoutMs());
      } catch {
        // Best-effort by contract: the run may already be terminal, or the responder gone.
      }
    },

    async readAggregate(
      handle: WaveRunHandle,
    ): Promise<{ state: string; error?: string; value: unknown }> {
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
