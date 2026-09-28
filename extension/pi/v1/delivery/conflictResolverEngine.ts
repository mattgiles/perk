// The conflict writer's engine: authorization, task/worktree validation, engine presence, the
// native worktree default and the resolver lock around ONE foreground dispatch through the shared
// transport (`../foregroundDelegation.ts`), then classification of the untrusted record.
import { randomUUID } from "node:crypto";
import { statSync } from "node:fs";
import { isAbsolute } from "node:path";
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
import {
  type DelegationEvents,
  dispatchForeground,
  nativeWorktreeConfigPath,
  readNativeWorktreeDefault,
} from "../foregroundDelegation.ts";

// Re-exported so existing importers (the engine test, the fake engine) keep one import site.
export {
  CANCEL_GRACE_MS,
  DELEGATION_EVENTS,
  type DelegationEvents,
  nativeWorktreeConfigPath,
  REQUEST_TIMEOUT_MS,
  START_ACK_MS,
} from "../foregroundDelegation.ts";

export const RESOLVER_AGENT = "perk.conflict-resolver";

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
    const result = await dispatchForeground(
      options.events,
      {
        agent: RESOLVER_AGENT,
        task,
        cwd: request.worktree,
        schema: conflictResolutionSchema(request.mode),
        ...(request.model !== undefined ? { model: request.model } : {}),
      },
      { requestId: receipt.requestId, ownerRunId: receipt.ownerRunId, nodeId: receipt.nodeId },
      signal,
    );
    // Construct each whitelisted receipt field explicitly, never spread native data.
    receipt.termination = result.termination;
    if (result.observedRunId !== undefined) receipt.runId = result.observedRunId;
    if (result.terminal) {
      receipt.nativeStatus = result.terminal.status;
      if (result.terminal.runId !== undefined) receipt.runId = result.terminal.runId;
      if (result.terminal.agent !== undefined) receipt.agent = result.terminal.agent;
      if (result.terminal.exitCode !== undefined) receipt.exitCode = result.terminal.exitCode;
    }
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
