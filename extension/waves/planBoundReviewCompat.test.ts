// Installed-engine placement, not model review quality: two real detached native children.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve } from "node:path";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import type { Static } from "typebox";
import { Compile } from "typebox/compile";
import { createReportWave, type ReportWaveResult } from "./reportWave.ts";
import type { WaveBus } from "./transport.ts";

// Optional installed-source interop stays test-local; production has no dependency on these APIs.
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
const installation = resolve(import.meta.dirname, "../../.pi/npm/node_modules/pi-subagents");
const OBSERVATION_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "child_run_id",
    "pid",
    "launch_cwd",
    "process_cwd",
    "plan_ref_text",
    "plan_snapshot_text",
    "read_only",
  ],
  properties: {
    child_run_id: { type: "string", minLength: 1 },
    pid: { type: "integer", minimum: 1 },
    launch_cwd: { type: "string", minLength: 1 },
    process_cwd: { type: "string", minLength: 1 },
    plan_ref_text: { type: ["string", "null"] },
    plan_snapshot_text: { type: ["string", "null"] },
    read_only: { type: "boolean" },
  },
} as const;
type Observation = Static<typeof OBSERVATION_SCHEMA>;

function observationOf(result: ReportWaveResult, key: string): Observation {
  assert.equal(result.complete, true, JSON.stringify(result));
  assert.deepEqual(result.failures, []);
  assert.equal(result.reports.length, 1);
  assert.equal(result.reports[0]?.key, key);
  const observation = result.reports[0]?.report;
  assert.ok(Compile(OBSERVATION_SCHEMA).Check(observation), JSON.stringify(observation));
  assert.equal(result.receipt.children.length, 1);
  const child = result.receipt.children[0];
  assert.equal(child?.key, key);
  assert.equal(child?.runId, observation.child_run_id);
  assert.notEqual(observation.pid, process.pid);
  assert.doesNotMatch(
    JSON.stringify(result.receipt),
    /plan_ref_text|plan_snapshot_text|read_only|verdict/,
  );
  return observation;
}

function bus(): WaveBus {
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

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") return false;
    throw error;
  }
}

// Runner status files are teardown evidence only; reports come exclusively through ReportWave.
function runnerIdentities(root: string): Array<{ path: string; pid: number; runId: string }> {
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

test("installed engine: plan-bound caller placement versus native worktree default", {
  skip: !existsSync(installation) && "optional pi-subagents installation absent",
  timeout: 180_000,
}, async (t) => {
  const root = realpathSync(installation);
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), "perk-plan-bound-")));
  const caller = join(scratch, "caller");
  const agentHome = join(scratch, "agent-home");
  const nativeTemp = join(scratch, "native");
  const before = { ...process.env };
  for (const key of Object.keys(process.env)) {
    if (/API_KEY|TOKEN|SECRET|CREDENTIAL|^PI_|^PERK_|^ANTHROPIC_|^OPENAI_|^GITHUB_|^GH_/.test(key))
      delete process.env[key];
  }
  process.env.HOME = scratch;
  process.env.PI_CODING_AGENT_DIR = agentHome;
  process.env.PI_SUBAGENTS_TEMP_ROOT = nativeTemp;
  process.env.GIT_CONFIG_NOSYSTEM = "1";
  process.env.GIT_CONFIG_GLOBAL = join(scratch, "empty-gitconfig");
  writeFileSync(process.env.GIT_CONFIG_GLOBAL, "");
  let bridge: ReturnType<RpcModule["registerSubagentRpcBridge"]> | undefined;
  let watcher: { startResultWatcher(): void; stopResultWatcher(): void } | undefined;
  let passed = false;
  let factory:
    | {
        setChildSessionFactoryModule(path: string | undefined): void;
        childSessionFactoryModule(): string | undefined;
      }
    | undefined;
  let previousFactory: string | undefined;
  let executor: ReturnType<ExecutorModule["createSubagentExecutor"]> | undefined;
  const events = bus();
  const ctx = {
    cwd: caller,
    hasUI: false,
    sessionManager: {
      getSessionId: () => "placement-parent",
      getSessionFile: () => undefined,
      getBranch: () => [],
      getEntries: () => [],
    },
    modelRegistry: { getAvailable: () => [] },
    ui: { setWidget() {}, notify() {} },
  };
  const state = {
    baseCwd: caller,
    currentSessionId: "placement-parent",
    parentSessionFile: null,
    trustedSessionRoots: [],
    subagentInProgress: false,
    lastUiContext: ctx,
    asyncJobs: new Map(),
    fleetJobs: new Map(),
    foregroundRuns: new Map(),
    foregroundControls: new Map(),
    cleanupTimers: new Map(),
    completionSeen: new Map(),
    lastForegroundControlId: null,
    poller: null,
    watcher: null,
    watcherRestartTimer: null,
    resultFileCoalescer: { schedule: () => false, clear() {} },
  };
  t.after(async () => {
    const deadline = Date.now() + 30_000;
    try {
      for (const runner of runnerIdentities(nativeTemp).filter(({ pid }) => alive(pid))) {
        if (executor) {
          let timer: ReturnType<typeof setTimeout> | undefined;
          try {
            await Promise.race([
              executor.executePublic(
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
      }
      bridge?.dispose();
      watcher?.stopResultWatcher();
      factory?.setChildSessionFactoryModule(previousFactory);
      for (const timer of state.cleanupTimers.values()) clearTimeout(timer);
      while (true) {
        const live = runnerIdentities(nativeTemp).filter(({ pid }) => alive(pid));
        if (live.length === 0) break;
        assert.ok(
          Date.now() < deadline,
          `runners still live; retained ${scratch}: ${JSON.stringify(live)}`,
        );
        await delay(50);
      }
      if (passed) rmSync(scratch, { recursive: true, force: true });
      else t.diagnostic(`failed measurement artifacts retained: ${scratch}`);
    } finally {
      bridge?.dispose();
      watcher?.stopResultWatcher();
      factory?.setChildSessionFactoryModule(previousFactory);
      for (const key of Object.keys(process.env)) if (!(key in before)) delete process.env[key];
      Object.assign(process.env, before);
    }
  });
  t.mock.method(globalThis, "fetch", () => {
    throw new Error("network forbidden in placement test");
  });
  const git = (...args: string[]) =>
    execFileSync("git", ["-C", caller, ...args], { encoding: "utf8", timeout: 10_000 });
  mkdirSync(join(caller, ".pi/agents/perk"), { recursive: true });
  mkdirSync(join(caller, ".perk/workflow"), { recursive: true });
  writeFileSync(join(caller, ".gitignore"), ".perk/\n.pi/subagents/\n");
  writeFileSync(
    join(caller, ".pi/agents/perk/pr-reviewer.md"),
    readFileSync(resolve(import.meta.dirname, "../../agents/pr-reviewer.md")),
  );
  writeFileSync(
    join(caller, ".pi/settings.json"),
    JSON.stringify({ subagents: { disableBuiltins: true } }),
  );
  const planRef = '{"plan_id":"synthetic","branch":"fixture"}\n';
  const planSnapshot = "# Synthetic caller-only plan\n\n Preserve these bytes. \n";
  writeFileSync(join(caller, ".perk/workflow/plan-ref.json"), planRef);
  writeFileSync(join(caller, ".perk/workflow/plan.md"), planSnapshot);
  git("init", "-q");
  git("add", ".gitignore", ".pi");
  git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "fixture");
  assert.equal(git("status", "--porcelain"), "");
  const inventory = git("worktree", "list", "--porcelain");
  const setupLog = join(scratch, "setup.log");
  const hook = join(scratch, "setup.sh");
  writeFileSync(hook, `#!/bin/sh\nprintf 'setup\\n' >> '${setupLog}'\nprintf '{}\\n'\n`);
  chmodSync(hook, 0o755);
  const configPath = join(agentHome, "extensions/subagent/config.json");
  mkdirSync(join(configPath, ".."), { recursive: true });
  writeFileSync(
    configPath,
    JSON.stringify({
      worktree: true,
      worktreeBaseDir: join(scratch, "worktrees"),
      worktreeSetupHook: hook,
      worktreeSetupHookTimeoutMs: 5_000,
      artifactDir: "temp",
      asyncByDefault: true,
    }),
  );
  const require = createRequire(join(root, "package.json"));
  const jiti = require("jiti").createJiti(join(root, "package.json"));
  const configModule = (await jiti.import(join(root, "src/extension/config.ts"))) as {
    loadConfig(): { worktree?: boolean };
    getConfigPath(): string;
  };
  assert.equal(configModule.getConfigPath(), configPath);
  const config = configModule.loadConfig();
  assert.equal(config.worktree, true);
  factory = await jiti.import(join(root, "src/runs/shared/child-session.ts"));
  assert.ok(factory);
  previousFactory = factory.childSessionFactoryModule();
  factory.setChildSessionFactoryModule(
    resolve(import.meta.dirname, "../testing/planBoundReviewChildFactory.mjs"),
  );
  const discovery = await jiti.import(join(root, "src/agents/agents.ts"));
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
  });
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
  const wave = createReportWave(events, { parentReadOnly: () => false });
  const request = {
    flow: "plan-bound-review-compat",
    completeness: "strict" as const,
    outputSchema: OBSERVATION_SCHEMA,
    timeoutMs: 60_000,
  };
  const task = "Measure the actual child launch via the scripted observation factory.";
  const protectedResult = await wave.run({
    ...request,
    execution: "caller-read-only",
    assignments: [{ key: "protected", agent: "perk.pr-reviewer", task }],
  });
  const protectedObservation = observationOf(protectedResult, "protected");
  assert.equal(realpathSync(protectedObservation.launch_cwd), realpathSync(caller));
  assert.equal(realpathSync(protectedObservation.process_cwd), realpathSync(caller));
  assert.equal(protectedObservation.plan_ref_text, planRef);
  assert.equal(protectedObservation.plan_snapshot_text, planSnapshot);
  assert.equal(protectedObservation.read_only, true);
  assert.equal(git("worktree", "list", "--porcelain"), inventory);
  assert.equal(existsSync(setupLog), false);
  const controlResult = await wave.run({
    ...request,
    assignments: [{ key: "control", agent: "perk.pr-reviewer", task }],
  });
  const control = observationOf(controlResult, "control");
  // The native engine may remove its clean worktree before returning; compare canonical-root
  // placement without requiring the allocation to remain on disk after settlement.
  const controlCwd = existsSync(control.launch_cwd)
    ? realpathSync(control.launch_cwd)
    : resolve(control.launch_cwd);
  assert.notEqual(controlCwd, realpathSync(caller));
  const allocated = relative(join(scratch, "worktrees"), controlCwd);
  assert.ok(allocated !== "" && !allocated.startsWith("..") && !isAbsolute(allocated), controlCwd);
  assert.notEqual(control.child_run_id, protectedObservation.child_run_id);
  assert.equal(control.plan_ref_text, null);
  assert.equal(control.plan_snapshot_text, null);
  assert.equal(control.read_only, false);
  assert.equal(readFileSync(setupLog, "utf8"), "setup\n");
  assert.deepEqual(
    new Set(runnerIdentities(nativeTemp).map(({ runId }) => runId)),
    new Set([protectedObservation.child_run_id, control.child_run_id]),
    "exactly two detached native children",
  );
  passed = true;
});
