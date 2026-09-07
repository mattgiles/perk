// Test-only detached-runner session: measure placement through the engine's validated tool.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

async function optionalText(path) {
  try {
    return await readFile(path, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

export default function childSessionFactory() {
  return {
    async create(launch) {
      assert.equal(typeof launch.runtime.runId, "string");
      assert.ok(launch.runtime.runId.length > 0, "missing child run identity");
      const packet = JSON.parse(launch.processEnv.PI_SUBAGENT_EXTENSION_BINDINGS);
      assert.ok(packet !== null && typeof packet === "object" && !Array.isArray(packet));
      const restriction = packet["perk.parent-restrictions/1"];
      assert.ok(
        restriction !== null && typeof restriction === "object" && !Array.isArray(restriction),
      );
      assert.deepEqual(Object.keys(restriction), ["readOnly"]);
      const readOnly = restriction.readOnly;
      assert.equal(typeof readOnly, "boolean", "missing/malformed restriction packet");
      const observation = {
        child_run_id: launch.runtime.runId,
        pid: process.pid,
        launch_cwd: launch.cwd,
        process_cwd: process.cwd(),
        plan_ref_text: await optionalText(join(launch.cwd, ".perk/workflow/plan-ref.json")),
        plan_snapshot_text: await optionalText(join(launch.cwd, ".perk/workflow/plan.md")),
        read_only: readOnly,
      };
      const tools = new Map();
      for (const hook of launch.hooks) {
        hook.factory({
          on() {},
          events: { on: () => () => {}, emit() {} },
          registerTool(tool) {
            tools.set(tool.name, tool);
          },
        });
      }
      const structured = tools.get("structured_output");
      assert.ok(structured, "engine did not provide structured_output hook");
      const listeners = new Set();
      const emit = (event) => {
        for (const listener of listeners) listener(event);
      };
      return {
        messages: [],
        sessionFile: undefined,
        sessionId: launch.runtime.runId,
        modelId: "scripted/observation",
        subscribe(listener) {
          listeners.add(listener);
          return () => {
            listeners.delete(listener);
          };
        },
        async prompt() {
          const call = {
            toolCallId: "placement-observation",
            toolName: "structured_output",
            args: { value: observation },
          };
          emit({ type: "tool_execution_start", ...call });
          const result = await structured.execute(call.toolCallId, call.args);
          assert.equal(result.terminate, true);
          emit({ type: "tool_execution_end", ...call, result, isError: false });
          emit({ type: "agent_end", messages: [] });
        },
        async steer() {
          throw new Error("unexpected steer");
        },
        async followUp() {
          throw new Error("unexpected follow-up");
        },
        async abort() {},
        async dispose() {},
      };
    },
    async dispose() {},
  };
}
