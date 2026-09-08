// Test-only detached-runner session: a report-only lane that performs NO mutation and completes
// through the engine-injected `structured_output` tool exactly as the lane fixture scripts it.
// The fixture (`PERK_TEST_REPORT_ONLY_FIXTURE`, a JSON file written by the suite) keys one
// script per runtime agent name: `report` submits the given value; `invalid` submits it and
// expects the engine's validation refusal; `missing` never calls the tool. Every lane writes one
// observation file (`<observationDir>/<agent>.json`) so the suite can prove the delivered task
// reached the child (length, trigger sentence) without the report having to carry it.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const TRIGGER = "Its no-resume-command assertion must change; its safety assertions must not.";

export default function childSessionFactory() {
  return {
    async create(launch) {
      assert.equal(typeof launch.runtime.runId, "string");
      assert.ok(launch.runtime.runId.length > 0, "missing child run identity");
      const agent = launch.runtime.agent;
      assert.equal(typeof agent, "string", "missing runtime agent name");
      const fixturePath = launch.processEnv?.PERK_TEST_REPORT_ONLY_FIXTURE ?? process.env.PERK_TEST_REPORT_ONLY_FIXTURE;
      assert.ok(fixturePath, "missing PERK_TEST_REPORT_ONLY_FIXTURE");
      const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
      const script = fixture.lanes[agent];
      assert.ok(script, `no lane script for agent ${agent}`);
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
      const observe = (prompt, structuredOutcome) => {
        writeFileSync(
          join(fixture.observationDir, `${agent}.json`),
          JSON.stringify({
            agent,
            child_run_id: launch.runtime.runId,
            pid: process.pid,
            launch_cwd: launch.cwd,
            prompt_length: prompt.length,
            prompt_has_trigger: prompt.includes(TRIGGER),
            structured: structuredOutcome,
          }),
        );
      };
      return {
        messages: [],
        sessionFile: undefined,
        sessionId: launch.runtime.runId,
        modelId: "scripted/report-only",
        subscribe(listener) {
          listeners.add(listener);
          return () => {
            listeners.delete(listener);
          };
        },
        async prompt(text) {
          if (script.mode === "missing") {
            observe(text, "not-called");
            emit({ type: "agent_end", messages: [] });
            return;
          }
          const call = {
            toolCallId: "report-only-completion",
            toolName: "structured_output",
            args: { value: script.report },
          };
          emit({ type: "tool_execution_start", ...call });
          try {
            const result = await structured.execute(call.toolCallId, call.args);
            assert.equal(script.mode, "report", "an invalid report must be refused by the engine");
            assert.equal(result.terminate, true);
            observe(text, "captured");
            emit({ type: "tool_execution_end", ...call, result, isError: false });
          } catch (error) {
            assert.equal(script.mode, "invalid", `unexpected structured_output refusal: ${error}`);
            observe(text, `rejected: ${error instanceof Error ? error.message : String(error)}`);
            emit({
              type: "tool_execution_end",
              ...call,
              result: { content: [{ type: "text", text: String(error) }], details: {} },
              isError: true,
            });
          }
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
