// Sole carrier of the optional source-bound public loader and native foreground delegation.
// No report-wave transport, private executor, task interpolation by the parent, or fallback.
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import {
  CONFLICT_RESOLUTION_SCHEMA,
  type ConflictResolutionFailure,
  type ConflictResolutionReceipt,
  type ConflictResolutionRequest,
  type ConflictResolutionResult,
  type ConflictResolver,
  classifyConflictResolution,
  conflictResolutionTask,
} from "../../../delivery/conflictResolution.ts";
import {
  acquireWorktreeResolverLock,
  type WorktreeResolverClaim,
} from "../../../substrate/worktreeResolverLock.ts";

export const DELEGATION_EVENTS = {
  request: "prompt-template:subagent:request",
  started: "prompt-template:subagent:started",
  update: "prompt-template:subagent:update",
  response: "prompt-template:subagent:response",
  cancel: "prompt-template:subagent:cancel",
} as const;
export const RESOLVER_AGENT = "perk.conflict-resolver";
const WRITER_TOOLS = ["read", "grep", "find", "ls", "bash", "edit", "write"];
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
export interface ResolverPreflightInput {
  agent: string;
  task: string;
  cwd: string;
  context: "fresh";
  model?: string;
  outputSchema: typeof CONFLICT_RESOLUTION_SCHEMA;
  availableModels: readonly { provider: string; id: string; reasoning?: boolean }[];
  parentModel?: { provider: string; id: string };
}
export type ResolverPreflight = (input: ResolverPreflightInput) => Promise<unknown>;
function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}
function identifier(value: unknown): value is string {
  return (
    typeof value === "string" && value.length > 0 && value.length <= 256 && !/[\0\r\n]/.test(value)
  );
}

/** The only accepted dependency root is the real registered subagent tool's ancestry. */
export async function loadResolverPreflight(
  entry: string | undefined,
): Promise<ResolverPreflight | null> {
  if (!entry) return null;
  try {
    let root = dirname(realpathSync(entry));
    for (;;) {
      const manifestPath = join(root, "package.json");
      if (existsSync(manifestPath)) {
        const manifest = object(JSON.parse(readFileSync(manifestPath, "utf8")));
        if (manifest?.name === "pi-subagents") {
          const exports = object(manifest.exports);
          let preflightPath: string | undefined;
          for (const name of ["./preflight", "./delegation"]) {
            const target = exports?.[name];
            if (typeof target !== "string" || !target.startsWith("./")) return null;
            const file = realpathSync(resolve(root, target));
            const rel = relative(root, file);
            if (
              rel === ".." ||
              rel.startsWith(`..${sep}`) ||
              isAbsolute(rel) ||
              !statSync(file).isFile()
            )
              return null;
            if (name === "./preflight") preflightPath = file;
          }
          // Only preflight is loaded in production. The public delegation export pins these
          // local event literals in installed compatibility tests, not another runtime loader.
          const require = createRequire(manifestPath);
          const loader: unknown = require("jiti");
          if (
            (typeof loader !== "object" && typeof loader !== "function") ||
            loader === null ||
            !("createJiti" in loader) ||
            typeof loader.createJiti !== "function" ||
            preflightPath === undefined
          )
            return null;
          const jiti = loader.createJiti(manifestPath) as {
            import?: (path: string) => Promise<unknown>;
          };
          if (typeof jiti.import !== "function") return null;
          const module = object(await jiti.import(preflightPath));
          if (typeof module?.resolveSubagentLaunchContract !== "function") return null;
          const preflight = module.resolveSubagentLaunchContract;
          return async (input) => preflight(input);
        }
      }
      const next = dirname(root);
      if (next === root) return null;
      root = next;
    }
  } catch {
    return null;
  }
}

export function nativeWorktreeConfigPath(): string {
  return join(getAgentDir(), "extensions/subagent/config.json");
}
type WorktreeDefault = "missing" | "absent" | "false" | "incompatible";
export function nativeWorktreeDefault(path: string): WorktreeDefault {
  try {
    const config = object(JSON.parse(readFileSync(path, "utf8")));
    if (config === null) return "incompatible";
    if (!("worktree" in config)) return "absent";
    return config.worktree === false ? "false" : "incompatible";
  } catch (error) {
    return object(error)?.code === "ENOENT" ? "missing" : "incompatible";
  }
}

function profileEvidence(
  value: unknown,
  cwd: string,
): ConflictResolutionReceipt["preflight"] | null {
  const result = object(value);
  const c = object(result?.contract);
  const agent = object(c?.agent);
  const tools = object(c?.tools);
  const roots = object(c?.roots);
  if (result?.ok !== true || !c || !agent || !tools || !roots) return null;
  const declared = tools.declaredBuiltin;
  const effective = tools.effectiveAllowlist;
  const internal = tools.internalTools;
  if (
    agent.name !== RESOLVER_AGENT ||
    agent.source !== "project" ||
    (agent.disabled !== undefined && agent.disabled !== false) ||
    !Array.isArray(agent.shadowedCandidates) ||
    agent.shadowedCandidates.length !== 0 ||
    typeof agent.filePath !== "string" ||
    typeof agent.definitionDigest !== "string" ||
    c.systemPromptMode !== "replace" ||
    c.inheritProjectContext !== true ||
    c.inheritSkills !== true ||
    c.inheritGlobalContext !== false ||
    c.context !== "fresh" ||
    !identifier(c.model) ||
    !strings(c.modelCandidates) ||
    c.modelCandidates.length === 0 ||
    roots.cwd !== resolve(cwd) ||
    !strings(declared) ||
    declared.length !== WRITER_TOOLS.length ||
    !WRITER_TOOLS.every((t) => declared.includes(t)) ||
    !strings(effective) ||
    !strings(internal) ||
    tools.fanoutAuthorized !== false ||
    tools.explicitAllowlist !== true ||
    effective.some((t) => !WRITER_TOOLS.includes(t) && !internal.includes(t)) ||
    WRITER_TOOLS.some((t) => !effective.includes(t)) ||
    !Array.isArray(c.diagnostics) ||
    c.diagnostics.some((d) => object(d)?.severity === "error") ||
    !identifier(c.launchContractDigest)
  )
    return null;
  for (const field of ["configuredExtensions", "toolExtensionPaths", "effectiveMcpTools"]) {
    if (!Array.isArray(tools[field]) || tools[field].length !== 0) return null;
  }
  try {
    const canonical = realpathSync(join(cwd, ".pi/agents/perk/conflict-resolver.md"));
    if (realpathSync(agent.filePath) !== canonical) return null;
    return { source: canonical, digest: c.launchContractDigest };
  } catch {
    return null;
  }
}

interface Terminal {
  status: string;
  value?: unknown;
  runId?: string;
  agent?: string;
  exitCode?: number;
  launchContractDigest?: string;
}
function terminal(value: Record<string, unknown>): Terminal | null {
  if (typeof value.status !== "string" || !STATUSES.has(value.status)) return null;
  for (const key of ["runId", "agent", "launchContractDigest"]) {
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
    ...(typeof value.launchContractDigest === "string"
      ? { launchContractDigest: value.launchContractDigest }
      : {}),
  };
}

export interface ConflictResolverEngineOptions {
  events: DelegationEvents;
  engineEntry: () => string | undefined;
  readOnly: () => boolean;
  authorized: (request: ConflictResolutionRequest) => boolean;
  availableModels: () => ResolverPreflightInput["availableModels"];
  parentModel?: () => ResolverPreflightInput["parentModel"];
  /** Offline seams are construction-only, never model/tool input. */
  preflight?: ResolverPreflight;
  configPath?: string;
  acquire?: typeof acquireWorktreeResolverLock;
}

/** Stop waiting for read-only preflight on abort; a late result can never cause dispatch. */
async function untilAborted<T>(promise: Promise<T>, signal: AbortSignal): Promise<T | undefined> {
  if (signal.aborted) return undefined;
  let abort = () => {};
  const cancelled = new Promise<undefined>((settle) => {
    abort = () => settle(undefined);
    signal.addEventListener("abort", abort, { once: true });
  });
  try {
    return await Promise.race([promise, cancelled]);
  } finally {
    signal.removeEventListener("abort", abort);
  }
}

export function createConflictResolverEngine(
  options: ConflictResolverEngineOptions,
): ConflictResolver & { shutdown(): Promise<void> } {
  const configPath = options.configPath ?? nativeWorktreeConfigPath();
  const configAtActivation = nativeWorktreeDefault(configPath);
  let loaded: Promise<ResolverPreflight | null> | undefined;
  let disposed = false;
  const active = new Map<AbortController, Promise<ConflictResolutionResult>>();
  function allowed(request: ConflictResolutionRequest): boolean {
    try {
      return !disposed && !options.readOnly() && options.authorized(request);
    } catch {
      return false;
    }
  }
  function configCompatible(): boolean {
    const current = nativeWorktreeDefault(configPath);
    return current !== "incompatible" && current === configAtActivation;
  }
  async function dispatch(
    request: ConflictResolutionRequest,
    signal: AbortSignal,
  ): Promise<ConflictResolutionResult> {
    const receipt: ConflictResolutionReceipt & { requestId: string; ownerRunId: string } = {
      parentSessionId: request.parent.sessionId,
      ownerRunId: request.parent.runId,
      requestId: randomUUID(),
      nodeId: "submit-conflict",
      cwd: request.worktree,
      disposition: "preflight",
      termination: "not-requested",
      lock: { disposition: "not-acquired" },
    };
    function failed(reason: ConflictResolutionFailure): ConflictResolutionResult {
      receipt.disposition = reason;
      return { kind: "failed", reason, receipt };
    }
    if (signal.aborted) return failed("cancelled");
    if (!allowed(request)) return failed("unauthorized");
    const task = conflictResolutionTask(request.worktree);
    try {
      if (!task || !isAbsolute(request.worktree) || !statSync(request.worktree).isDirectory())
        return failed("invalid-worktree");
    } catch {
      return failed("invalid-worktree");
    }
    if (!configCompatible()) return failed("incompatible-worktree-default");
    let proof: ConflictResolutionReceipt["preflight"];
    try {
      loaded ??= options.preflight
        ? Promise.resolve(options.preflight)
        : loadResolverPreflight(options.engineEntry());
      const preflight = await untilAborted(loaded, signal);
      if (signal.aborted) return failed("cancelled");
      if (!preflight) return failed("unavailable");
      const parentModel = options.parentModel?.();
      proof =
        profileEvidence(
          await untilAborted(
            preflight({
              agent: RESOLVER_AGENT,
              cwd: request.worktree,
              task,
              context: "fresh",
              outputSchema: CONFLICT_RESOLUTION_SCHEMA,
              availableModels: options.availableModels(),
              ...(parentModel ? { parentModel } : {}),
              ...(request.model !== undefined ? { model: request.model } : {}),
            }),
            signal,
          ),
          request.worktree,
        ) ?? undefined;
    } catch {
      return failed("unavailable");
    }
    if (signal.aborted) return failed("cancelled");
    if (!allowed(request)) return failed("unauthorized");
    if (!proof) return failed("incompatible-profile");
    receipt.preflight = proof;
    if (!configCompatible()) return failed("incompatible-worktree-default");
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
    if (signal.aborted || !allowed(request) || !configCompatible() || claim.check() !== "owned") {
      return failed(
        finishLock(true) ??
          (signal.aborted
            ? "cancelled"
            : !configCompatible()
              ? "incompatible-worktree-default"
              : "unauthorized"),
      );
    }
    const result = await waitForTerminal(
      options.events,
      request,
      task,
      receipt,
      claim,
      signal,
      () => allowed(request) && configCompatible(),
    );
    const lockFailure = finishLock(result.release);
    if (lockFailure) return failed(lockFailure);
    if (result.failure) return failed(result.failure);
    if (!result.terminal) return failed("termination-unconfirmed");
    receipt.disposition = "terminal";
    return classifyConflictResolution(result.terminal.status, result.terminal.value, receipt);
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
  claim: WorktreeResolverClaim,
  signal: AbortSignal,
  authorized: () => boolean,
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
      for (const key of ["runId", "agent", "exitCode", "launchContractDigest"] as const) {
        // Construct each whitelisted field explicitly, never spread native data.
        if (key === "runId" && t.runId !== undefined) receipt.runId = t.runId;
        if (key === "agent" && t.agent !== undefined) receipt.agent = t.agent;
        if (key === "exitCode" && t.exitCode !== undefined) receipt.exitCode = t.exitCode;
        if (key === "launchContractDigest" && t.launchContractDigest !== undefined)
          receipt.launchContractDigest = t.launchContractDigest;
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
      if (signal.aborted || !authorized() || claim.check() !== "owned") {
        settle({ failure: signal.aborted ? "cancelled" : "unauthorized", release: true });
        return;
      }
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
          result: { kind: "structured", schema: CONFLICT_RESOLUTION_SCHEMA },
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
