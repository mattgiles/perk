// Installed-engine OFFLINE compatibility: supported public loading + real native parser/bridge
// and result projection, with fake child execution. Not a live resolver/rebase certification.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
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
import {
  CONFLICT_RESOLUTION_SCHEMA,
  conflictResolutionTask,
} from "../../../delivery/conflictResolution.ts";
import {
  completedResolution,
  deferred,
  FakeDelegationBus,
} from "../../../testing/fakeConflictResolver.ts";
import {
  createConflictResolverEngine,
  DELEGATION_EVENTS,
  loadResolverPreflight,
  nativeWorktreeConfigPath,
} from "./conflictResolverEngine.ts";

interface ChildResult {
  exitCode: number;
  error?: string;
  structuredOutput?: unknown;
}
interface BridgeResult {
  details: { runId?: string; results: object[] };
  isError?: boolean;
}
interface Bridge {
  registerPromptTemplateDelegationBridge(options: {
    events: FakeDelegationBus;
    getContext(): { cwd: string };
    execute(
      id: string,
      params: Record<string, unknown>,
      signal: AbortSignal,
      ctx: { cwd: string },
      update: (r: BridgeResult) => void,
    ): Promise<BridgeResult>;
  }): { dispose(): void };
}
const installation = resolve(import.meta.dirname, "../../../../.pi/npm/node_modules/pi-subagents");

test("installed public foreground compatibility (offline)", {
  skip:
    !existsSync(installation) &&
    "optional pi-subagents installation missing (not implementing-checkout evidence)",
  timeout: 60_000,
}, async (t) => {
  const root = realpathSync(installation);
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), "perk-foreground-compat-")));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const before = { ...process.env };
  for (const key of Object.keys(process.env))
    if (/API_KEY|TOKEN|SECRET|CREDENTIAL|^PI_|^PERK_|^ANTHROPIC_|^OPENAI_/.test(key))
      delete process.env[key];
  process.env.HOME = scratch;
  process.env.PI_CODING_AGENT_DIR = join(scratch, "agent-home");
  t.after(() => {
    for (const key of Object.keys(process.env)) if (!(key in before)) delete process.env[key];
    Object.assign(process.env, before);
  });
  t.mock.method(globalThis, "fetch", () => {
    throw new Error("network forbidden in offline compatibility test");
  });
  const manifestPath = join(root, "package.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  assert.equal(manifest.name, "pi-subagents"); // compatibility, not version equality
  const require = createRequire(manifestPath);
  const { createJiti } = require("jiti");
  const jiti = createJiti(manifestPath);
  const api = await jiti.import(resolve(root, manifest.exports["./delegation"]));
  for (const [key, event] of Object.entries(DELEGATION_EVENTS))
    assert.equal(event, api[`SUBAGENT_DELEGATION_${key.toUpperCase()}_EVENT`]);
  const preflight = await loadResolverPreflight(join(root, "src/extension/index.ts"));
  assert.ok(preflight, "source-bound public loader must load this installed engine");
  const config = (await jiti.import(join(root, "src/extension/config.ts"))) as {
    getConfigPath(): string;
  };
  assert.equal(nativeWorktreeConfigPath(), config.getConfigPath());
  const cwd = join(scratch, "actual-worktree");
  mkdirSync(join(cwd, ".pi/agents/perk"), { recursive: true });
  execFileSync("git", ["init", "-q", cwd], { timeout: 5000 });
  writeFileSync(
    join(cwd, ".pi/agents/perk/conflict-resolver.md"),
    readFileSync(resolve(import.meta.dirname, "../../../../agents/conflict-resolver.md")),
  );
  writeFileSync(
    join(cwd, ".pi/settings.json"),
    JSON.stringify({ subagents: { disableBuiltins: true } }),
  );
  const availableModels = [{ provider: "offline", id: "model" }];
  const pre = await preflight({
    agent: "perk.conflict-resolver",
    cwd,
    task: conflictResolutionTask(cwd) ?? "",
    context: "fresh",
    model: "offline/model",
    availableModels,
    outputSchema: CONFLICT_RESOLUTION_SCHEMA,
  });
  assert.equal((pre as { ok: boolean }).ok, true, JSON.stringify(pre));
  const inherited = await preflight({
    agent: "perk.conflict-resolver",
    cwd,
    task: "inherit probe",
    context: "fresh",
    model: "inherit",
    parentModel: { provider: "offline", id: "model" },
    availableModels,
    outputSchema: CONFLICT_RESOLUTION_SCHEMA,
  });
  assert.equal((inherited as { contract: { model: string } }).contract.model, "offline/model");
  const forceAsync = (await jiti.import(join(root, "src/runs/background/top-level-async.ts"))) as {
    applyForceTopLevelAsyncOverride(
      params: object,
      depth: number,
      forced: boolean,
    ): Record<string, unknown>;
  };
  const bridge = (await jiti.import(join(root, "src/slash/prompt-template-bridge.ts"))) as Bridge;
  const parser = (await jiti.import(join(root, "src/agents/agents.ts"))) as {
    discoverAgents(cwd: string, scope: string): { agents: Record<string, unknown>[] };
  };
  const execution = (await jiti.import(join(root, "src/runs/foreground/execution.ts"))) as {
    runSync(
      cwd: string,
      agents: object[],
      name: string,
      task: string,
      options: object,
    ): Promise<ChildResult>;
  };
  const agents = parser.discoverAgents(cwd, "project").agents;
  const writer = agents.find((a) => a.name === "perk.conflict-resolver");
  assert.ok(writer);

  await t.test(
    "actual public preflight and bridge forward acceptance/schema/fresh cwd with no artifact invention",
    async () => {
      const bus = new FakeDelegationBus();
      let calls = 0;
      const b = bridge.registerPromptTemplateDelegationBridge({
        events: bus,
        getContext: () => ({ cwd: scratch }),
        async execute(_id, params, _signal, _ctx, update) {
          calls++;
          assert.equal(params.cwd, cwd);
          assert.equal(params.context, "fresh");
          assert.equal(params.async, false);
          assert.equal(params.foregroundOnly, true);
          assert.equal(params.clarify, false);
          assert.equal(params.acceptance, false);
          assert.deepEqual(params.outputSchema, CONFLICT_RESOLUTION_SCHEMA);
          update({ details: { runId: "child", results: [] } });
          return {
            details: {
              runId: "child",
              results: [
                {
                  agent: "perk.conflict-resolver",
                  exitCode: 0,
                  launchContractDigest: "native-digest",
                  structuredOutput: completedResolution,
                  finalOutput: "SECRET",
                  savedOutputPath: "/secret/artifact",
                },
              ],
            },
          };
        },
      });
      const e = createConflictResolverEngine({
        events: bus,
        engineEntry: () => join(root, "src/extension/index.ts"),
        readOnly: () => false,
        authorized: () => true,
        availableModels: () => availableModels,
      });
      try {
        const result = await e.resolve({
          mode: "pr-rebase",
          worktree: cwd,
          parent: { sessionId: "session", runId: "parent" },
          model: "offline/model",
        });
        assert.equal(result.kind, "resolved", JSON.stringify({ result, pre }));
        assert.equal(calls, 1);
        assert.equal(result.receipt.launchContractDigest, "native-digest");
        assert.doesNotMatch(JSON.stringify(result.receipt), /SECRET|artifact/);
      } finally {
        b.dispose();
        await e.shutdown();
      }
    },
  );

  await t.test("foregroundOnly defeats forced background defaults in installed routing", () => {
    const source = readFileSync(join(root, "src/runs/foreground/subagent-executor.ts"), "utf8");
    const start = source.indexOf("function applySingleAgentLaunchDefaults(");
    const end = source.indexOf("export const DEFAULT_FOREGROUND_TIMEOUT_MS", start);
    assert.ok(start >= 0 && end > start);
    const apply = new Function(
      `${stripTypeScriptTypes(source.slice(start, end))}; return applySingleAgentLaunchDefaults;`,
    )() as (p: object, agents: object[]) => Record<string, unknown>;
    assert.equal(
      apply({ agent: writer.name, async: false, foregroundOnly: true }, [
        { ...writer, defaultAsync: true },
      ]).async,
      false,
    );
    assert.equal(
      forceAsync.applyForceTopLevelAsyncOverride(
        { agent: writer.name, async: false, foregroundOnly: true },
        0,
        true,
      ).async,
      false,
    );
    assert.equal(
      forceAsync.applyForceTopLevelAsyncOverride({ agent: writer.name, async: false }, 0, true)
        .async,
      true,
    );
    assert.match(source, /foregroundOnly/);
    // Installed implementation must route structured delegation through this guard, not RPC.
    assert.match(source, /executeDelegated/);
  });

  for (const preAborted of [true, false]) {
    await t.test(
      `real bridge → runSync fake ChildSessionFactory cancellation, preAborted=${preAborted}`,
      async () => {
        const bus = new FakeDelegationBus();
        const prompted = deferred<void>();
        const promptEnd = deferred<void>();
        let starts = 0;
        let aborts = 0;
        let disposals = 0;
        const b = bridge.registerPromptTemplateDelegationBridge({
          events: bus,
          getContext: () => ({ cwd: scratch }),
          async execute(_id, params, signal) {
            const child = await execution.runSync(
              cwd,
              agents,
              "perk.conflict-resolver",
              String(params.task),
              {
                cwd: params.cwd,
                signal,
                runId: "offline-writer",
                context: params.context,
                artifactConfig: { enabled: false },
                sessionDir: join(scratch, "sessions"),
                modelOverride: "offline/model",
                childSessionFactory: {
                  async create(input: { cwd: string }) {
                    starts++;
                    assert.equal(input.cwd, cwd);
                    return {
                      messages: [],
                      sessionFile: undefined,
                      sessionId: "fake",
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
                      },
                    };
                  },
                  async dispose() {
                    assert.fail("global factory disposal not expected");
                  },
                },
              },
            );
            assert.notEqual(child.exitCode, 0);
            return { details: { runId: "offline-writer", results: [child] } };
          },
        });
        const tuple = {
          requestId: `request-${preAborted}`,
          ownerRunId: "parent",
          nodeId: "submit-conflict",
        };
        const response = deferred<Record<string, unknown>>();
        bus.on(DELEGATION_EVENTS.response, (r) => response.resolve(r as Record<string, unknown>));
        if (preAborted) bus.emit(DELEGATION_EVENTS.cancel, tuple);
        bus.emit(DELEGATION_EVENTS.request, {
          ...tuple,
          agent: "perk.conflict-resolver",
          cwd,
          task: "Offline cancellation only",
          context: "fresh",
          result: { kind: "structured", schema: CONFLICT_RESOLUTION_SCHEMA },
        });
        if (!preAborted) {
          await prompted.promise;
          bus.emit(DELEGATION_EVENTS.cancel, { ...tuple, ownerRunId: "foreign" });
          assert.equal(aborts, 0);
          bus.emit(DELEGATION_EVENTS.cancel, tuple);
        }
        const result = await response.promise;
        assert.equal(result.status, "cancelled");
        assert.equal(starts, preAborted ? 0 : 1);
        assert.equal(aborts, starts);
        assert.equal(disposals, starts);
        b.dispose();
      },
    );
  }

  await t.test(
    "installed disabled/external/widened/shadowed profiles refuse before emission",
    async () => {
      const canonical = readFileSync(join(cwd, ".pi/agents/perk/conflict-resolver.md"), "utf8");
      // Each activation gets pre-existing inputs at a fresh root, not unsupported in-place
      // changes underneath the installed engine's already-discovered settings snapshot.
      const variants = [
        { disabled: true },
        { tools: ["read", "bash", "subagent"] },
        { inheritGlobalContext: true },
        "external",
        "shadowed",
      ];
      for (const [i, variant] of variants.entries()) {
        const worktree = join(scratch, `profile-${i}`);
        mkdirSync(join(worktree, ".pi/agents/perk"), { recursive: true });
        execFileSync("git", ["init", "-q", worktree], { timeout: 5000 });
        writeFileSync(
          join(worktree, ".pi/settings.json"),
          JSON.stringify({
            subagents: {
              disableBuiltins: true,
              ...(typeof variant === "object"
                ? { agentOverrides: { "perk.conflict-resolver": variant } }
                : {}),
            },
          }),
        );
        writeFileSync(
          join(worktree, ".pi/agents/perk/conflict-resolver.md"),
          variant === "external"
            ? canonical.replace(
                "tools: read, grep, find, ls, bash, edit, write",
                "runner:\n  type: external-cli\n  command: never-launched",
              )
            : canonical,
        );
        if (variant === "shadowed") {
          const userAgents = join(scratch, "agent-home/agents/perk");
          mkdirSync(userAgents, { recursive: true });
          writeFileSync(join(userAgents, "conflict-resolver.md"), canonical);
        }
        const bus = new FakeDelegationBus();
        const e = createConflictResolverEngine({
          events: bus,
          preflight,
          engineEntry: () => undefined,
          readOnly: () => false,
          authorized: () => true,
          availableModels: () => availableModels,
        });
        const r = await e.resolve({
          mode: "pr-rebase",
          worktree,
          parent: { sessionId: "s", runId: "r" },
          model: "offline/model",
        });
        assert.ok(
          r.kind === "failed" && ["unavailable", "incompatible-profile"].includes(r.reason),
          JSON.stringify({ variant, r }),
        );
        assert.equal(bus.sent.length, 0);
      }
    },
  );

  await t.test("native worktree allocation default is refused, never rewritten", async () => {
    const path = config.getConfigPath();
    mkdirSync(join(path, ".."), { recursive: true });
    writeFileSync(path, '{"worktree":true}');
    const bus = new FakeDelegationBus();
    const e = createConflictResolverEngine({
      events: bus,
      engineEntry: () => join(root, "src/extension/index.ts"),
      readOnly: () => false,
      authorized: () => true,
      availableModels: () => availableModels,
    });
    const r = await e.resolve({
      mode: "pr-rebase",
      worktree: cwd,
      parent: { sessionId: "session", runId: "parent" },
    });
    assert.ok(r.kind === "failed" && r.reason === "incompatible-worktree-default");
    assert.equal(bus.sent.length, 0);
    assert.equal(readFileSync(path, "utf8"), '{"worktree":true}');
  });
});
