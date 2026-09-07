// Bounded installed-engine OFFLINE evidence: report golden, profile/preparation and restrictions.
// Writer native bridge/cancellation coverage lives beside conflictResolverEngine. No live model.
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
import { parseChildIdentity } from "../substrate/childIdentity.ts";
import { decodeChildRestrictions } from "../substrate/childRestrictions.ts";
import { waveScriptItems } from "../testing/fakeSubagents.ts";

// Narrow test-only interop views: private installed modules are optional on clean CI hosts.
// Production neither imports them nor depends on these declarations.
interface Agent extends Record<string, unknown> {
  name: string;
  defaultAsync?: boolean;
}
interface WorkflowModule {
  validateWorkflowScript(script: string): { ok: boolean; errors: unknown[] };
}

const installation = resolve(import.meta.dirname, "../../.pi/npm/node_modules/pi-subagents");

test("installed engine: native child profile/preparation and report compatibility", {
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

  await t.test("installed validator accepts actual report golden", () => {
    const golden = readFileSync(
      resolve(import.meta.dirname, "../../shared/subagents/representative-wave-script.js"),
      "utf8",
    );
    assert.deepEqual(waveScriptItems(golden)[0]?.extensionBindings, {
      "perk.parent-restrictions/1": { readOnly: false },
    });
    const result = workflow.validateWorkflowScript(golden);
    assert.equal(result.ok, true, JSON.stringify(result.errors));
  });
});
