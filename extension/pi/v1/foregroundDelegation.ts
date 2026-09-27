// The one foreground-delegation transport both writer children ride: the sole carrier of the
// public delegation event literals, one correlated request per dispatch, no restriction packet
// (writers never get the read-only floor) and no fallback transport. Callers own authorization,
// locks, task construction and classification; this module owns only the correlation lifecycle
// and reports the native facts it observed.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

export const DELEGATION_EVENTS = {
  request: "prompt-template:subagent:request",
  started: "prompt-template:subagent:started",
  update: "prompt-template:subagent:update",
  response: "prompt-template:subagent:response",
  cancel: "prompt-template:subagent:cancel",
} as const;
const STATUSES = new Set([
  "completed",
  "failed",
  "timed_out",
  "cancelled",
  "interrupted",
  "tool_budget_exhausted",
  "structured_output_failed",
  "acceptance_failed",
  "invalid_request",
  "unavailable_context",
  "duplicate_node",
]);
const PRELAUNCH = new Set(["invalid_request", "unavailable_context", "duplicate_node"]);
export const REQUEST_TIMEOUT_MS = 1_800_000;
export const START_ACK_MS = 5_000;
export const CANCEL_GRACE_MS = 5_000;

export interface DelegationEvents {
  on(event: string, handler: (data: unknown) => void): () => void;
  emit(event: string, data: unknown): void;
}

/** The correlation identity every started/update/response/cancel event must carry exactly. */
export interface DelegationTuple {
  requestId: string;
  ownerRunId: string;
  nodeId: string;
}

/** One foreground launch. The deadline is always `REQUEST_TIMEOUT_MS` — no per-launch knob. */
export interface ForegroundLaunch {
  agent: string;
  task: string;
  cwd: string;
  /** The plain-JSON structured-result schema (never TypeBox's non-enumerable metadata). */
  schema: Record<string, unknown>;
  model?: string;
}

/** The validated native terminal envelope — only whitelisted scalar facts survive. */
export interface NativeTerminal {
  status: string;
  value?: unknown;
  runId?: string;
  agent?: string;
  exitCode?: number;
}

export type TransportFailure =
  | "cancelled"
  | "transport-failed"
  | "malformed-result"
  | "termination-unconfirmed";

/**
 * What the transport observed. `termination` is `not-requested` until the request was emitted,
 * then `unconfirmed`, then `confirmed` on a qualifying terminal. `release` means the child is
 * provably quiescent: a `completed` terminal, a pre-launch status with no started evidence, or
 * nothing ever emitted.
 */
export interface ForegroundOutcome {
  terminal?: NativeTerminal;
  failure?: TransportFailure;
  release: boolean;
  termination: "not-requested" | "confirmed" | "unconfirmed";
  observedRunId?: string;
}

function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function identifier(value: unknown): value is string {
  return (
    typeof value === "string" && value.length > 0 && value.length <= 256 && !/[\0\r\n]/.test(value)
  );
}

export function nativeWorktreeConfigPath(): string {
  return join(getAgentDir(), "extensions/subagent/config.json");
}

export type NativeWorktreeVerdict = { compatible: true } | { compatible: false; observed: string };

/**
 * pi-subagents applies its global `worktree` default to every delegation that omits the field
 * and reads that file once at ITS activation, so perk reads it once at engine activation too.
 * Deliberately stricter than the engine's own fallback: only a missing file, an absent key or
 * an explicit `false` lets a writer launch; any other state is refused with what was observed,
 * because perk will not infer from pi-subagents' private fallback rules what a broken config
 * file will do — and perk never rewrites the file. The observation reaches receipts and the
 * model-facing diagnostics, so it is bounded and never content-bearing: only JSON scalars that
 * cannot carry text (booleans, numbers, null) are rendered; a string, array or object is named
 * by type alone.
 */
export function readNativeWorktreeDefault(path: string): NativeWorktreeVerdict {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch (error) {
    const code = object(error)?.code;
    if (code === "ENOENT") return { compatible: true };
    const errno = typeof code === "string" && /^[A-Z0-9_]{1,32}$/.test(code) ? code : "unknown";
    return { compatible: false, observed: `unreadable (${errno})` };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { compatible: false, observed: "unparseable JSON" };
  }
  const config = object(parsed);
  if (config === null) return { compatible: false, observed: "not a JSON object" };
  if (!("worktree" in config) || config.worktree === false) return { compatible: true };
  const value = config.worktree;
  const observed =
    value === null || typeof value === "boolean" || typeof value === "number"
      ? `worktree=${JSON.stringify(value)}`
      : `worktree is ${Array.isArray(value) ? "an array" : typeof value === "object" ? "an object" : `a ${typeof value}`}`;
  return { compatible: false, observed };
}

/** The one repair sentence; the file is pi-subagents', never perk's to edit. */
export function nativeWorktreeFix(config: { path: string; observed: string }): string {
  return `Native subagent config ${config.path} is incompatible (${config.observed}): set "worktree": false there (or delete the key), then quit and resume this Pi session.`;
}

function terminal(value: Record<string, unknown>): NativeTerminal | null {
  if (typeof value.status !== "string" || !STATUSES.has(value.status)) return null;
  for (const key of ["runId", "agent"]) {
    if (value[key] !== undefined && !identifier(value[key])) return null;
  }
  if (
    value.exitCode !== undefined &&
    (typeof value.exitCode !== "number" || !Number.isInteger(value.exitCode))
  )
    return null;
  for (const key of ["error", "model", "thinking"]) {
    if (value[key] !== undefined && typeof value[key] !== "string") return null;
  }
  const result = object(value.result);
  if (
    value.result !== undefined &&
    (!result ||
      (result.kind !== "structured" && result.kind !== "text") ||
      (result.kind === "structured" && !("value" in result)) ||
      (result.kind === "text" && typeof result.text !== "string"))
  )
    return null;
  if (value.usage !== undefined) {
    const usage = object(value.usage);
    if (
      !usage ||
      [
        "input",
        "output",
        "cacheRead",
        "cacheWrite",
        "cost",
        "turns",
        "toolCalls",
        "durationMs",
      ].some((key) => typeof usage[key] !== "number" || !Number.isFinite(usage[key]))
    )
      return null;
  }
  // Native completion is quiescence evidence even if the separate structured record is bad.
  return {
    status: value.status,
    ...(result?.kind === "structured" ? { value: result.value } : {}),
    ...(typeof value.runId === "string" ? { runId: value.runId } : {}),
    ...(typeof value.agent === "string" ? { agent: value.agent } : {}),
    ...(typeof value.exitCode === "number" ? { exitCode: value.exitCode } : {}),
  };
}

/**
 * Emit one correlated foreground request and wait for its terminal. An already-aborted signal
 * is refused FIRST — before any subscription or emission — because abort events are never
 * replayed to a listener installed later. Otherwise: subscribe before emit, correlate every
 * event on the exact tuple, honor a synchronous response delivered during `emit`, cancel with
 * the tuple on abort / missing start-ack / deadline / emission error, and settle after the
 * cancellation grace as `termination-unconfirmed` when no terminal arrives.
 */
export function dispatchForeground(
  events: DelegationEvents,
  launch: ForegroundLaunch,
  tuple: DelegationTuple,
  signal: AbortSignal,
): Promise<ForegroundOutcome> {
  if (signal.aborted)
    return Promise.resolve({ failure: "cancelled", release: true, termination: "not-requested" });
  return new Promise((resolveOutcome) => {
    const correlation = {
      requestId: tuple.requestId,
      ownerRunId: tuple.ownerRunId,
      nodeId: tuple.nodeId,
    };
    const subscriptions: (() => void)[] = [];
    let started = false;
    let emitted = false;
    let settled = false;
    let emitting = false;
    let termination: ForegroundOutcome["termination"] = "not-requested";
    let observedRunId: string | undefined;
    let pendingTerminal: NativeTerminal | undefined;
    let cancellation: TransportFailure | undefined;
    let ack: ReturnType<typeof setTimeout> | undefined;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    let grace: ReturnType<typeof setTimeout> | undefined;
    function settle(result: Omit<ForegroundOutcome, "termination" | "observedRunId">) {
      if (settled) return;
      settled = true;
      clearTimeout(ack);
      clearTimeout(deadline);
      clearTimeout(grace);
      signal.removeEventListener("abort", abort);
      for (const unsubscribe of subscriptions) unsubscribe();
      resolveOutcome({
        ...result,
        termination,
        ...(observedRunId !== undefined ? { observedRunId } : {}),
      });
    }
    function cancel(reason: TransportFailure) {
      if (settled || cancellation) return;
      cancellation = reason;
      clearTimeout(ack);
      clearTimeout(deadline);
      if (!emitted) {
        settle({ failure: reason, release: true });
        return;
      }
      grace = setTimeout(
        () => settle({ failure: "termination-unconfirmed", release: false }),
        CANCEL_GRACE_MS,
      );
      try {
        events.emit(DELEGATION_EVENTS.cancel, correlation);
      } catch {
        /* An ambiguous cancellation settles unconfirmed at grace expiry. */
      }
    }
    function abort() {
      cancel("cancelled");
    }
    function correlated(data: unknown): Record<string, unknown> | null {
      const r = object(data);
      return r !== null &&
        r.requestId === correlation.requestId &&
        r.ownerRunId === correlation.ownerRunId &&
        r.nodeId === correlation.nodeId
        ? r
        : null;
    }
    function completed(t: NativeTerminal) {
      const release = t.status === "completed" || (PRELAUNCH.has(t.status) && !started);
      termination = release ? "confirmed" : "unconfirmed";
      settle({ terminal: t, ...(cancellation ? { failure: cancellation } : {}), release });
    }
    try {
      subscriptions.push(
        events.on(DELEGATION_EVENTS.started, (data) => {
          if (!emitted || !correlated(data) || settled) return;
          started = true;
          clearTimeout(ack);
        }),
      );
      subscriptions.push(
        events.on(DELEGATION_EVENTS.update, (data) => {
          const r = correlated(data);
          if (!emitted || !r || settled) return;
          started = true;
          if (identifier(r.runId)) observedRunId = r.runId;
        }),
      );
      subscriptions.push(
        events.on(DELEGATION_EVENTS.response, (data) => {
          const r = correlated(data);
          if (!emitted || !r || settled || pendingTerminal) return;
          const t = terminal(r);
          if (!t) {
            settle({ failure: "malformed-result", release: false });
            return;
          }
          clearTimeout(ack);
          if (emitting) pendingTerminal = t;
          else completed(t);
        }),
      );
      signal.addEventListener("abort", abort, { once: true });
      ack = setTimeout(() => cancel("termination-unconfirmed"), START_ACK_MS);
      deadline = setTimeout(() => cancel("termination-unconfirmed"), REQUEST_TIMEOUT_MS);
      emitted = true;
      emitting = true;
      termination = "unconfirmed";
      try {
        events.emit(DELEGATION_EVENTS.request, {
          ...correlation,
          agent: launch.agent,
          task: launch.task,
          cwd: launch.cwd,
          context: "fresh",
          timeoutMs: REQUEST_TIMEOUT_MS,
          result: { kind: "structured", schema: launch.schema },
          ...(launch.model !== undefined ? { model: launch.model } : {}),
        });
        emitting = false;
        if (pendingTerminal) completed(pendingTerminal);
      } catch {
        emitting = false;
        pendingTerminal = undefined;
        cancel("transport-failed");
      }
    } catch {
      settle({ failure: "transport-failed", release: !emitted });
    }
  });
}
