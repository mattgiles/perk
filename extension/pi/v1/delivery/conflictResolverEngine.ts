// Sole carrier of the public delegation event literals: one foreground request per authorized
// dispatch with no restriction packet and no fallback transport.
import { randomUUID } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import {
  type ConflictResolutionFailure,
  type ConflictResolutionReceipt,
  type ConflictResolutionRequest,
  type ConflictResolutionResult,
  type ConflictResolver,
  classifyConflictResolution,
  conflictResolutionSchema,
  conflictResolutionTask,
  retainedConflictResolutionTask,
} from "../../../delivery/conflictResolution.ts";
import { acquireWorktreeResolverLock } from "../../../substrate/worktreeResolverLock.ts";

export const DELEGATION_EVENTS = {
  request: "prompt-template:subagent:request",
  started: "prompt-template:subagent:started",
  update: "prompt-template:subagent:update",
  response: "prompt-template:subagent:response",
  cancel: "prompt-template:subagent:cancel",
} as const;
export const RESOLVER_AGENT = "perk.conflict-resolver";
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

type NativeWorktreeVerdict = { compatible: true } | { compatible: false; observed: string };

/**
 * pi-subagents applies its global `worktree` default to every delegation that omits the field
 * and reads that file once at ITS activation, so perk reads it once at engine activation too.
 * Deliberately stricter than the engine's own fallback: only a missing file, an absent key or
 * an explicit `false` lets a writer launch; any other state is refused with what was observed,
 * because perk will not infer from pi-subagents' private fallback rules what a broken config
 * file will do — and perk never rewrites the file.
 */
function readNativeWorktreeDefault(path: string): NativeWorktreeVerdict {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch (error) {
    const code = object(error)?.code;
    return code === "ENOENT"
      ? { compatible: true }
      : { compatible: false, observed: `unreadable (${String(code)})` };
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
  return { compatible: false, observed: `worktree=${JSON.stringify(config.worktree)}` };
}

interface Terminal {
  status: string;
  value?: unknown;
  runId?: string;
  agent?: string;
  exitCode?: number;
}
function terminal(value: Record<string, unknown>): Terminal | null {
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

export interface ConflictResolverEngineOptions {
  events: DelegationEvents;
  /**
   * Pi's public tool census says pi-subagents' `subagent` tool is registered — the only
   * engine-presence fact perk reads; a false answer refuses before any lock.
   */
  enginePresent: () => boolean;
  readOnly: () => boolean;
  authorized: (request: ConflictResolutionRequest) => boolean;
  /** Offline seams are construction-only, never model/tool input. */
  configPath?: string;
  acquire?: typeof acquireWorktreeResolverLock;
}

export function createConflictResolverEngine(
  options: ConflictResolverEngineOptions,
): ConflictResolver & { shutdown(): Promise<void> } {
  const configPath = options.configPath ?? nativeWorktreeConfigPath();
  const nativeWorktree = readNativeWorktreeDefault(configPath);
  let disposed = false;
  const active = new Map<AbortController, Promise<ConflictResolutionResult>>();
  function allowed(request: ConflictResolutionRequest): boolean {
    try {
      return !disposed && !options.readOnly() && options.authorized(request);
    } catch {
      return false;
    }
  }
  function present(): boolean {
    try {
      return options.enginePresent();
    } catch {
      return false;
    }
  }
  async function dispatch(
    request: ConflictResolutionRequest,
    signal: AbortSignal,
  ): Promise<ConflictResolutionResult> {
    const receipt: ConflictResolutionReceipt & { requestId: string; ownerRunId: string } = {
      parentSessionId: request.parent.sessionId,
      ownerRunId: request.parent.runId,
      requestId: randomUUID(),
      nodeId: request.mode === "pr-rebase" ? "submit-conflict" : "retained-conflict",
      cwd: request.worktree,
      termination: "not-requested",
      lock: { disposition: "not-acquired" },
    };
    function failed(reason: ConflictResolutionFailure): ConflictResolutionResult {
      return { kind: "failed", reason, receipt };
    }
    if (signal.aborted) return failed("cancelled");
    if (!allowed(request)) return failed("unauthorized");
    const task =
      request.mode === "pr-rebase"
        ? conflictResolutionTask(request.worktree)
        : retainedConflictResolutionTask(request);
    try {
      if (!task || !isAbsolute(request.worktree) || !statSync(request.worktree).isDirectory())
        return failed("invalid-worktree");
    } catch {
      return failed("invalid-worktree");
    }
    if (!present()) return failed("unavailable");
    if (!nativeWorktree.compatible) {
      receipt.nativeWorktreeConfig = { path: configPath, observed: nativeWorktree.observed };
      return failed("incompatible-worktree-default");
    }
    const acquisition = (options.acquire ?? acquireWorktreeResolverLock)(request.worktree, {
      ...request.parent,
      requestId: receipt.requestId,
    });
    if (acquisition.kind === "unavailable") return failed("invalid-worktree");
    if (acquisition.kind === "busy") {
      receipt.lock = { path: acquisition.path, disposition: "busy" };
      return failed("lock-busy");
    }
    if (acquisition.kind === "io-error") {
      receipt.lock = {
        path: acquisition.path,
        disposition: acquisition.residue ? "retained" : "not-acquired",
      };
      return failed(acquisition.residue ? "lock-retained" : "lock-io");
    }
    const claim = acquisition.claim;
    receipt.lock = { path: claim.path, disposition: "retained" };
    function finishLock(release: boolean): ConflictResolutionFailure | null {
      const result = claim.finish(release ? "release" : "retain");
      receipt.lock.disposition =
        result.kind === "released" || result.kind === "retained" ? result.kind : "ownership-error";
      return result.kind === "ownership-error"
        ? "lock-ownership"
        : result.kind === "io-error"
          ? "lock-io"
          : null;
    }
    const result = await waitForTerminal(options.events, request, task, receipt, signal);
    const lockFailure = finishLock(result.release);
    if (lockFailure) return failed(lockFailure);
    if (result.failure) return failed(result.failure);
    if (!result.terminal) return failed("termination-unconfirmed");
    return classifyConflictResolution(
      request.mode,
      result.terminal.status,
      result.terminal.value,
      receipt,
    );
  }
  return {
    resolve(request, signal) {
      const controller = new AbortController();
      const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
      const result = dispatch(request, combined);
      active.set(controller, result);
      void result.finally(() => active.delete(controller));
      return result;
    },
    async shutdown() {
      disposed = true;
      for (const c of active.keys()) c.abort();
      await Promise.all(active.values());
    },
  };
}

interface WaitResult {
  terminal?: Terminal;
  failure?: ConflictResolutionFailure;
  release: boolean;
}
function waitForTerminal(
  events: DelegationEvents,
  request: ConflictResolutionRequest,
  task: string,
  receipt: ConflictResolutionReceipt,
  signal: AbortSignal,
): Promise<WaitResult> {
  return new Promise((resolveResult) => {
    const tuple = {
      requestId: receipt.requestId,
      ownerRunId: receipt.ownerRunId,
      nodeId: receipt.nodeId,
    };
    const subscriptions: (() => void)[] = [];
    let started = false;
    let emitted = false;
    let settled = false;
    let emitting = false;
    let pendingTerminal: Terminal | undefined;
    let cancellation: ConflictResolutionFailure | undefined;
    let ack: ReturnType<typeof setTimeout> | undefined;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    let grace: ReturnType<typeof setTimeout> | undefined;
    function settle(result: WaitResult) {
      if (settled) return;
      settled = true;
      clearTimeout(ack);
      clearTimeout(deadline);
      clearTimeout(grace);
      signal.removeEventListener("abort", abort);
      for (const unsubscribe of subscriptions) unsubscribe();
      resolveResult(result);
    }
    function cancel(reason: ConflictResolutionFailure) {
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
        events.emit(DELEGATION_EVENTS.cancel, tuple);
      } catch {
        /* Ambiguous cancellation retains the lock at grace expiry. */
      }
    }
    function abort() {
      cancel("cancelled");
    }
    function correlated(data: unknown): Record<string, unknown> | null {
      const r = object(data);
      return r !== null &&
        r.requestId === tuple.requestId &&
        r.ownerRunId === tuple.ownerRunId &&
        r.nodeId === tuple.nodeId
        ? r
        : null;
    }
    function completed(t: Terminal) {
      const release = t.status === "completed" || (PRELAUNCH.has(t.status) && !started);
      receipt.nativeStatus = t.status;
      receipt.termination = release ? "confirmed" : "unconfirmed";
      for (const key of ["runId", "agent", "exitCode"] as const) {
        // Construct each whitelisted field explicitly, never spread native data.
        if (key === "runId" && t.runId !== undefined) receipt.runId = t.runId;
        if (key === "agent" && t.agent !== undefined) receipt.agent = t.agent;
        if (key === "exitCode" && t.exitCode !== undefined) receipt.exitCode = t.exitCode;
      }
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
          if (identifier(r.runId)) receipt.runId = r.runId;
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
      receipt.termination = "unconfirmed";
      try {
        events.emit(DELEGATION_EVENTS.request, {
          ...tuple,
          agent: RESOLVER_AGENT,
          task,
          cwd: request.worktree,
          context: "fresh",
          timeoutMs: REQUEST_TIMEOUT_MS,
          result: { kind: "structured", schema: conflictResolutionSchema(request.mode) },
          ...(request.model !== undefined ? { model: request.model } : {}),
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
