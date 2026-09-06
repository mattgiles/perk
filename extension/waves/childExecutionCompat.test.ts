// Bounded installed-engine OFFLINE evidence: real parser/preparation and workflow cancellation
// with a per-call fake child. No model/session provider is launched; this is not a live mode PASS.
import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire, stripTypeScriptTypes } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { syncConflictResolutionGuidance } from "../pi/v1/delivery/stackSync.ts";
import { conflictResolutionGuidance } from "../pi/v1/delivery/submit.ts";
import { parseChildIdentity } from "../substrate/childIdentity.ts";
import { decodeChildRestrictions } from "../substrate/childRestrictions.ts";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import { writerScript } from "../testing/writerScript.ts";

// Narrow test-only interop views: private installed modules are optional on clean CI hosts.
// Production neither imports them nor depends on these declarations.
interface Agent extends Record<string, unknown> {
  name: string;
  defaultAsync?: boolean;
}
interface SingleResult {
  exitCode: number;
  error?: string;
  stopped?: boolean;
}
interface WorkflowChild {
  key: string;
  ok: boolean;
  output: string;
  error?: string;
}
interface WorkflowModule {
  validateWorkflowScript(script: string): { ok: boolean; errors: unknown[] };
  runWorkflowScript(options: {
    script: string;
    signal: AbortSignal;
    timeoutMs: number;
    launch(
      key: string,
      params: Record<string, unknown>,
      signal: AbortSignal,
    ): Promise<WorkflowChild>;
    status(): Promise<never>;
  }): Promise<unknown>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const installation = resolve(import.meta.dirname, "../../.pi/npm/node_modules/pi-subagents");

test("installed engine: native child profile/preparation and injected cancellation compatibility", {
  skip:
    !existsSync(installation) &&
    "optional pi-subagents installation missing (not implementing-checkout evidence)",
  timeout: 60_000,
}, async (t) => {
  const root = realpathSync(installation);
  const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  assert.equal(manifest.name, "pi-subagents");
  assert.equal(manifest.version, "0.66.0", "version changed: owner re-verification required");
  const scratch = mkdtempSync(join(tmpdir(), "perk-child-compat-"));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const priorEnv = { ...process.env };
  // Keep discovery and model credentials out of the test world. Loading the installed source
  // still uses its own real loader and peers, without repairing aliases or installing anything.
  for (const key of Object.keys(process.env)) {
    if (/API_KEY|TOKEN|SECRET|CREDENTIAL|^PI_|^PERK_|^ANTHROPIC_|^OPENAI_/.test(key))
      delete process.env[key];
  }
  process.env.HOME = scratch;
  process.env.PI_CODING_AGENT_DIR = join(scratch, "agent-home");
  t.after(() => {
    for (const key of Object.keys(process.env)) if (!(key in priorEnv)) delete process.env[key];
    Object.assign(process.env, priorEnv);
  });
  t.mock.method(globalThis, "fetch", () => {
    throw new Error("network forbidden in offline compatibility test");
  });
  const require = createRequire(join(root, "package.json"));
  const { createJiti } = require("jiti");
  const jiti = createJiti(join(root, "package.json"));
  const parser = (await jiti.import(join(root, "src/agents/agents.ts"))) as {
    discoverAgents(cwd: string, scope: string): { agents: Agent[] };
  };
  const executor = (await jiti.import(join(root, "src/runs/foreground/subagent-executor.ts"))) as {
    prepareWorkflowLaunchParams(
      defaults: object,
      child: object,
      run: string,
      key: string,
    ): Record<string, unknown>;
  };
  const bindings = (await jiti.import(join(root, "src/runs/shared/extension-bindings.ts"))) as {
    normalizeExtensionBindings(value: unknown): { value: unknown; json: string };
  };
  const launch = (await jiti.import(join(root, "src/runs/shared/child-launch.ts"))) as {
    buildInProcessChildLaunch(input: object): { session: Record<string, unknown> };
  };
  const execution = (await jiti.import(join(root, "src/runs/foreground/execution.ts"))) as {
    runSync(
      cwd: string,
      agents: Agent[],
      name: string,
      task: string,
      options: object,
    ): Promise<SingleResult>;
  };
  const workflow = (await jiti.import(
    join(root, "src/workflows/scripted-workflow.ts"),
  )) as WorkflowModule;
  const source = readFileSync(join(root, "src/runs/foreground/subagent-executor.ts"), "utf8");
  const cwd = join(scratch, "actual-writer-cwd");
  mkdirSync(join(cwd, ".pi/agents"), { recursive: true });
  writeFileSync(
    join(cwd, ".pi/settings.json"),
    JSON.stringify({ subagents: { disableBuiltins: true } }),
  );
  for (const stem of ["objective-explorer", "conflict-resolver"]) {
    writeFileSync(
      join(cwd, `.pi/agents/${stem}.md`),
      readFileSync(resolve(import.meta.dirname, `../../agents/${stem}.md`)),
    );
  }
  const agents = parser.discoverAgents(cwd, "project").agents;
  const report = agents.find((agent) => agent.name === "perk.objective-explorer");
  const writer = agents.find((agent) => agent.name === "perk.conflict-resolver");
  assert.ok(
    report && writer,
    "real discovery at actual cwd must resolve both canonical definitions",
  );

  await t.test(
    "real definition parser, omitted async awaiting and opposing global defaults",
    () => {
      assert.equal(report.defaultAsync, true);
      assert.equal(writer.defaultAsync, undefined);
      for (const [agent, inherits] of [
        [report, false],
        [writer, true],
      ] as const) {
        assert.equal(agent.inheritGlobalContext, false);
        assert.equal(agent.inheritProjectContext, inherits);
        assert.equal(agent.inheritSkills, inherits);
        assert.equal(agent.systemPromptMode, "replace");
        assert.equal(agent.extensions, undefined);
        assert.equal(agent.subagentOnlyExtensions, undefined);
      }
      const prepared = executor.prepareWorkflowLaunchParams(
        { context: "fresh" },
        { agent: report.name, task: "report" },
        "wave",
        "report",
      );
      const explicit = executor.prepareWorkflowLaunchParams(
        {},
        { agent: report.name, task: "report", async: true },
        "wave",
        "report",
      );
      assert.equal(prepared.async, undefined);
      assert.equal(prepared.workflowAwaitAsync, true);
      assert.equal(explicit.workflowAwaitAsync, undefined);
      // Execute the installed private default function, not a copied approximation. Its bounded
      // source slice is type-stripped in memory; no installed bytes or exported surface change.
      const start = source.indexOf("function applySingleAgentLaunchDefaults(");
      const end = source.indexOf("export const DEFAULT_FOREGROUND_TIMEOUT_MS", start);
      assert.ok(start >= 0 && end > start);
      const applyDefaults = new Function(
        `${stripTypeScriptTypes(source.slice(start, end))}; return applySingleAgentLaunchDefaults;`,
      )() as (params: Record<string, unknown>, agents: Agent[]) => Record<string, unknown>;
      assert.equal(
        applyDefaults(prepared, agents).async ?? false,
        true,
        "report defeats foreground engine default",
      );
      const foreground = executor.prepareWorkflowLaunchParams(
        {},
        { agent: writer.name, task: "resolve", async: false, cwd },
        "wave",
        "resolve",
      );
      assert.equal(
        applyDefaults(foreground, agents).async ?? true,
        false,
        "writer defeats background engine default",
      );
      assert.equal(foreground.cwd, cwd);
      assert.match(
        source,
        /effectiveParams = applySingleAgentLaunchDefaults\(effectiveParams, discoveredAgents\)/,
      );
      assert.match(source, /effectiveParams\.async \?\? deps\.asyncByDefault/);
      assert.match(
        source,
        /const effectiveAsync = requestedAsync && effectiveParams\.clarify !== true/,
      );
      assert.match(
        source,
        /if \(params\.workflowAwaitAsync !== true \|\| !launchResult\.details\.asyncDir\) return launchResult/,
      );
      assert.match(source, /async: _workflowAsync[\s\S]*?\.\.\.workflowRequest/);
      assert.match(source, /async: _async[^\n]*\.\.\.workflowChildDefaults/);
      assert.match(
        source,
        /discoverWorkflowAgents\(childCwd, resolveExecutionAgentScope\(childRequest\.agentScope\)\)/,
      );
      const blocking = source.slice(source.indexOf("async: _async"));
      assert.match(blocking, /return execute\(randomUUID\(\), childRequest, workflowSignal,/);
    },
  );

  await t.test("exact binding normalization and runner-only launch envelope", () => {
    for (const readOnly of [false, true]) {
      const packet = { "perk.parent-restrictions/1": { readOnly } };
      const normalized = bindings.normalizeExtensionBindings(packet);
      assert.deepEqual(normalized.value, packet);
      assert.equal(normalized.json, JSON.stringify(packet));
      for (const host of ["parent", "runner"]) {
        const { session } = launch.buildInProcessChildLaunch({
          cwd,
          host,
          childAgentName: 'custom.&"<>',
          childIndex: 0,
          sessionEnabled: false,
          inheritProjectContext: false,
          inheritGlobalContext: false,
          inheritSkills: false,
          systemPromptMode: "replace",
          systemPrompt: "Report only.",
          tools: ["read"],
          extensionBindings: normalized.value,
        });
        assert.equal(session.cwd, cwd);
        assert.equal(session.ambientExtensions, host === "runner");
        assert.equal(typeof session.systemPrompt, "string");
        assert.deepEqual(parseChildIdentity(String(session.systemPrompt)), {
          status: "available",
          name: 'custom.&"<>',
          provenance: "native-system-prompt-prefix",
        });
        if (host === "runner") {
          const raw = (session.processEnv as Record<string, unknown>)
            .PI_SUBAGENT_EXTENSION_BINDINGS;
          assert.equal(raw, normalized.json);
          assert.deepEqual(decodeChildRestrictions(true, String(raw)), {
            status: "valid",
            readOnly,
          });
        } else assert.equal(session.processEnv, undefined);
      }
    }
  });

  const prScript = writerScript(conflictResolutionGuidance("main", 1, 2, cwd));
  const retainedScript = writerScript(
    syncConflictResolutionGuidance(
      {
        objective: "7",
        node: "2.1",
        branch: "plan-91",
        pr: 91,
        worktree: cwd,
        operationId: "01OP",
        manifestPath: join(scratch, "manifest.json"),
      },
      1,
      2,
    ),
  );
  await t.test("installed validator accepts actual report golden and both writer scripts", () => {
    const golden = readFileSync(
      resolve(import.meta.dirname, "../../shared/subagents/representative-wave-script.js"),
      "utf8",
    );
    assert.deepEqual(waveScriptItems(golden)[0]?.extensionBindings, {
      "perk.parent-restrictions/1": { readOnly: false },
    });
    for (const script of [golden, prScript, retainedScript]) {
      const result = workflow.validateWorkflowScript(script);
      assert.equal(result.ok, true, JSON.stringify(result.errors));
    }
  });

  for (const preAborted of [true, false]) {
    await t.test(
      `PR writer workflow → runSync injected child cancellation: pre-aborted=${preAborted}`,
      async () => {
        const controller = new AbortController();
        const prompted = deferred<void>();
        const promptEnd = deferred<void>();
        const disposed = deferred<void>();
        let starts = 0;
        let aborts = 0;
        let disposals = 0;
        let terminal: SingleResult | undefined;
        let childRun: Promise<SingleResult> | undefined;
        const factory = {
          async create(input: { cwd: string }) {
            starts++;
            assert.equal(input.cwd, cwd);
            return {
              messages: [],
              sessionFile: undefined,
              sessionId: "offline-child",
              modelId: "offline/model",
              subscribe: () => () => {},
              async prompt() {
                prompted.resolve();
                await promptEnd.promise;
              },
              async steer() {},
              async followUp() {},
              async abort() {
                aborts++;
                promptEnd.resolve();
              },
              async dispose() {
                disposals++;
                disposed.resolve();
              },
            };
          },
          async dispose() {
            assert.fail("process-global factory disposal is not used");
          },
        };
        if (preAborted) controller.abort();
        const running = workflow.runWorkflowScript({
          script: prScript,
          signal: controller.signal,
          timeoutMs: 10_000,
          async status() {
            throw new Error("no status lookup expected");
          },
          async launch(key, params, workflowSignal) {
            assert.equal(params.async, false);
            childRun = execution.runSync(cwd, agents, writer.name, String(params.task), {
              cwd: params.cwd,
              signal: workflowSignal,
              runId: "offline-writer",
              context: "fresh",
              childSessionFactory: factory,
              artifactConfig: { enabled: false },
              sessionDir: join(scratch, "sessions"),
              modelOverride: "offline/model",
            });
            terminal = await childRun;
            return { key, ok: terminal.exitCode === 0, output: "", error: terminal.error };
          },
        });
        const settled = assert.rejects(running, /abort|cancel/i);
        if (!preAborted) {
          await prompted.promise;
          controller.abort();
        }
        await settled;
        if (preAborted) {
          assert.equal(starts, 0);
          assert.equal(childRun, undefined);
        } else {
          await childRun;
          await disposed.promise;
          assert.equal(starts, 1);
          assert.equal(aborts, 1);
          assert.equal(disposals, 1);
          assert.notEqual(terminal?.exitCode, 0);
          assert.match(terminal?.error ?? "", /stop|abort/i);
        }
      },
    );
  }
});
