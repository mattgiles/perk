// Test-only fixture for the OPTIONAL installed pi-subagents engine: boot the real executor,
// RPC bridge and result watcher over an isolated scratch HOME with a scripted child-session
// factory, and tear the detached native runners down under a bounded deadline. Shared by the
// installed-engine compat suites (`waves/planBoundReviewCompat.test.ts`,
// `waves/reportOnlyCompletionCompat.test.ts`); each suite keeps its own assertions and its own
// network prohibition (`t.mock` needs the test context). Production has NO dependency on these
// engine-internal module paths — a missing installation is a skip, an incompatible one a failure.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import type { TestContext } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import type { WaveBus } from "../waves/transport.ts";

/** The optional installed pi-subagents root (the repo's `.pi/npm` package install). */
export const INSTALLED_PI_SUBAGENTS = resolve(
  import.meta.dirname,
  "../../.pi/npm/node_modules/pi-subagents",
);

/** The `skip` value for an installed-engine test: a reason when absent, false when present. */
export function installedEngineSkip(): string | false {
  return !existsSync(INSTALLED_PI_SUBAGENTS) && "optional pi-subagents installation absent";
}

type Execute = (
  id: string,
  params: object,
  signal: AbortSignal,
  update: undefined,
  ctx: object,
) => Promise<unknown>;
interface ExecutorModule {
  createSubagentExecutor(deps: object): { executePublic: Execute };
}
interface RpcModule {
  registerSubagentRpcBridge(options: {
    events: WaveBus;
    getContext(): object;
    execute: Execute;
    state: object;
  }): { dispose(): void };
}
interface FactoryModule {
  setChildSessionFactoryModule(path: string | undefined): void;
  childSessionFactoryModule(): string | undefined;
}

/** A minimal in-process `WaveBus` (the fake `pi.events` the RPC bridge and ReportWave share). */
export function waveBus(): WaveBus {
  const handlers = new Map<string, Set<(data: unknown) => void>>();
  return {
    emit(event, data) {
      for (const handler of handlers.get(event) ?? []) handler(data);
    },
    on(event, handler) {
      let listeners = handlers.get(event);
      if (!listeners) {
        listeners = new Set();
        handlers.set(event, listeners);
      }
      listeners.add(handler);
      return () => {
        listeners.delete(handler);
      };
    },
  };
}

export function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") return false;
    throw error;
  }
}

/** Runner status files are teardown evidence only; reports come exclusively through ReportWave. */
export function runnerIdentities(
  root: string,
): Array<{ path: string; pid: number; runId: string }> {
  if (!existsSync(root)) return [];
  return readdirSync(root, { recursive: true, withFileTypes: true }).flatMap((entry) => {
    if (!entry.isFile() || entry.name !== "status.json") return [];
    const path = join(entry.parentPath, entry.name);
    const status = JSON.parse(readFileSync(path, "utf8"));
    return Number.isInteger(status.pid) &&
      status.pid > 0 &&
      status.pid !== process.pid &&
      typeof status.runId === "string"
      ? [{ path, pid: status.pid, runId: status.runId }]
      : [];
  });
}

/**
 * Isolate the process env for a credential-free engine boot: drop every credential/perk/pi
 * variable, point HOME + the pi agent dir + the native temp root into `scratch`, and neutralize
 * global git config. Returns the restore function (the ORIGINAL env is reinstated wholesale).
 */
export function isolateEngineEnv(scratch: string): { agentHome: string; nativeTemp: string } & {
  restore(): void;
} {
  const before = { ...process.env };
  for (const key of Object.keys(process.env)) {
    if (/API_KEY|TOKEN|SECRET|CREDENTIAL|^PI_|^PERK_|^ANTHROPIC_|^OPENAI_|^GITHUB_|^GH_/.test(key))
      delete process.env[key];
  }
  const agentHome = join(scratch, "agent-home");
  const nativeTemp = join(scratch, "native");
  process.env.HOME = scratch;
  process.env.PI_CODING_AGENT_DIR = agentHome;
  process.env.PI_SUBAGENTS_TEMP_ROOT = nativeTemp;
  process.env.GIT_CONFIG_NOSYSTEM = "1";
  process.env.GIT_CONFIG_GLOBAL = join(scratch, "empty-gitconfig");
  writeFileSync(process.env.GIT_CONFIG_GLOBAL, "");
  return {
    agentHome,
    nativeTemp,
    restore() {
      for (const key of Object.keys(process.env)) if (!(key in before)) delete process.env[key];
      Object.assign(process.env, before);
    },
  };
}

export interface InstalledEngineOptions {
  /** The realpath'd installation root. */
  root: string;
  /** The isolated scratch directory (`isolateEngineEnv` already applied). */
  scratch: string;
  /** The caller cwd the parent context reports. */
  caller: string;
  /** The `isolateEngineEnv` result (agent home + native temp root). */
  env: { agentHome: string; nativeTemp: string; restore(): void };
  /** The scripted child-session factory module the detached runner imports. */
  factoryModule: string;
  /** The subagent `config.json` the engine loads from the isolated agent home. */
  config: Record<string, unknown>;
  /** The parent session id the fake context reports. */
  parentSessionId: string;
}

export interface InstalledEngine {
  /** The installed package version (reported so a run names the actual supplier it exercised). */
  version: string;
  events: WaveBus;
  /** The loaded subagent config (for the suite's own config pins). */
  config: Record<string, unknown>;
  /** The real installed agent-definition discovery (`src/agents/agents.ts`). */
  discovery: { discoverAgents(...args: unknown[]): unknown };
  /**
   * Bounded teardown: stop live runners through the real executor, dispose the bridge/watcher,
   * restore the factory, wait for every runner to exit, then remove the scratch on success (or
   * retain it as a diagnostic) and reinstate the original env. Register with `t.after`.
   */
  teardown(t: TestContext, passed: () => boolean): Promise<void>;
}

/**
 * Boot the installed engine's foreground executor + RPC bridge + result watcher in-process, with
 * the detached runners importing `factoryModule` for their child sessions. The scripted factory
 * is installed through the engine's own seam (`setChildSessionFactoryModule`) and restored on
 * teardown — the installed dependency is never edited.
 */
export async function bootInstalledEngine(opts: InstalledEngineOptions): Promise<InstalledEngine> {
  const { root, scratch, caller, env, parentSessionId } = opts;
  const version = String(JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version);
  const configPath = join(env.agentHome, "extensions/subagent/config.json");
  mkdirSync(join(configPath, ".."), { recursive: true });
  writeFileSync(configPath, JSON.stringify(opts.config));

  const events = waveBus();
  const ctx = {
    cwd: caller,
    hasUI: false,
    sessionManager: {
      getSessionId: () => parentSessionId,
      getSessionFile: () => undefined,
      getBranch: () => [],
      getEntries: () => [],
    },
    modelRegistry: { getAvailable: () => [] },
    ui: { setWidget() {}, notify() {} },
  };
  const state = {
    baseCwd: caller,
    currentSessionId: parentSessionId,
    parentSessionFile: null,
    trustedSessionRoots: [],
    subagentInProgress: false,
    lastUiContext: ctx,
    asyncJobs: new Map(),
    fleetJobs: new Map(),
    foregroundRuns: new Map(),
    foregroundControls: new Map(),
    cleanupTimers: new Map<unknown, ReturnType<typeof setTimeout>>(),
    completionSeen: new Map(),
    lastForegroundControlId: null,
    poller: null,
    watcher: null,
    watcherRestartTimer: null,
    resultFileCoalescer: { schedule: () => false, clear() {} },
  };

  // Partial-boot hygiene: an incompatible installation fails the suite, but never leaves the
  // engine's process-wide factory seam or a started watcher behind.
  let factory: FactoryModule | undefined;
  let previousFactory: string | undefined;
  let watcher: { startResultWatcher(): void; stopResultWatcher(): void } | undefined;
  let bridge: { dispose(): void } | undefined;
  let executor: ReturnType<ExecutorModule["createSubagentExecutor"]>;
  let config: Record<string, unknown>;
  let discovery: { discoverAgents(...args: unknown[]): unknown };
  try {
    const require = createRequire(join(root, "package.json"));
    const jiti = require("jiti").createJiti(join(root, "package.json"));
    const configModule = (await jiti.import(join(root, "src/extension/config.ts"))) as {
      loadConfig(): Record<string, unknown>;
      getConfigPath(): string;
    };
    assert.equal(configModule.getConfigPath(), configPath);
    config = configModule.loadConfig();
    factory = (await jiti.import(join(root, "src/runs/shared/child-session.ts"))) as FactoryModule;
    assert.ok(factory);
    previousFactory = factory.childSessionFactoryModule();
    factory.setChildSessionFactoryModule(opts.factoryModule);
    discovery = (await jiti.import(join(root, "src/agents/agents.ts"))) as {
      discoverAgents(...args: unknown[]): unknown;
    };
    const executorModule = (await jiti.import(
      join(root, "src/runs/foreground/subagent-executor.ts"),
    )) as ExecutorModule;
    const rpcModule = (await jiti.import(join(root, "src/extension/rpc.ts"))) as RpcModule;
    const pi = { events, getSessionName: () => undefined, sendMessage() {}, appendEntry() {} };
    const watcherModule = await jiti.import(join(root, "src/runs/background/result-watcher.ts"));
    const nativeTypes = await jiti.import(join(root, "src/shared/types.ts"));
    watcher = watcherModule.createResultWatcher(pi, state, nativeTypes.DIRS.results, 600_000, {
      hasDeliveryDemand: () => true,
      deliverIntercomResults: false,
    }) as { startResultWatcher(): void; stopResultWatcher(): void };
    assert.ok(watcher);
    watcher.startResultWatcher();
    executor = executorModule.createSubagentExecutor({
      pi,
      state,
      config,
      asyncByDefault: true,
      tempArtifactsDir: join(scratch, "artifacts"),
      getSubagentSessionRoot: () => join(scratch, "sessions"),
      expandTilde: (path: string) => path.replace(/^~(?=\/|$)/, scratch),
      discoverAgents: discovery.discoverAgents,
    });
    bridge = rpcModule.registerSubagentRpcBridge({
      events,
      getContext: () => ctx,
      execute: executor.executePublic,
      state,
    });
  } catch (error) {
    bridge?.dispose();
    watcher?.stopResultWatcher();
    factory?.setChildSessionFactoryModule(previousFactory);
    throw error;
  }
  const booted = { executor, bridge, watcher, factory, previousFactory };

  return {
    version,
    events,
    config,
    discovery,
    async teardown(t, passed) {
      const deadline = Date.now() + 30_000;
      try {
        for (const runner of runnerIdentities(env.nativeTemp).filter(({ pid }) => alive(pid))) {
          let timer: ReturnType<typeof setTimeout> | undefined;
          try {
            await Promise.race([
              booted.executor.executePublic(
                `stop-${runner.runId}`,
                { action: "stop", id: runner.runId },
                AbortSignal.timeout(Math.max(1, deadline - Date.now())),
                undefined,
                ctx,
              ),
              new Promise<never>((_resolve, reject) => {
                timer = setTimeout(
                  () =>
                    reject(
                      new Error(`stop unsettled; retained ${scratch}: ${JSON.stringify(runner)}`),
                    ),
                  Math.max(1, deadline - Date.now()),
                );
              }),
            ]);
          } finally {
            clearTimeout(timer);
          }
        }
        booted.bridge.dispose();
        booted.watcher.stopResultWatcher();
        booted.factory.setChildSessionFactoryModule(booted.previousFactory);
        for (const timer of state.cleanupTimers.values()) clearTimeout(timer);
        while (true) {
          const live = runnerIdentities(env.nativeTemp).filter(({ pid }) => alive(pid));
          if (live.length === 0) break;
          assert.ok(
            Date.now() < deadline,
            `runners still live; retained ${scratch}: ${JSON.stringify(live)}`,
          );
          await delay(50);
        }
        if (passed()) rmSync(scratch, { recursive: true, force: true });
        else t.diagnostic(`failed measurement artifacts retained: ${scratch}`);
      } finally {
        booted.bridge.dispose();
        booted.watcher.stopResultWatcher();
        booted.factory.setChildSessionFactoryModule(booted.previousFactory);
        env.restore();
      }
    },
  };
}
