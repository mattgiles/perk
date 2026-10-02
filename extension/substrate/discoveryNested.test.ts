// The discovery pilot's nested-execution leg (contracts.md §8.40 "The discovery pilot"): in a
// discovery-cohort session a deferred, INACTIVE family member stays callable through Pi's
// nested-execution API (`ctx.executeTool`), its call is recorded on the parent tool result, and
// the read-only backstop still governs it. Driven through REAL bound AgentSessions (Mode A, fully
// offline). Its own file so the probe fixture's catalog registration never enters the census
// process (`discoveryPilot.test.ts`).
//
// `PERK_PRINT_DISCOVERY_CENSUS=1` prints the probe session's JSONL path to stderr for the
// `perk learn evidence --render` live leg.

import assert from "node:assert/strict";
import { before, test } from "node:test";
import type { AgentToolResult } from "@earendil-works/pi-coding-agent";
import { type InlineExtension, SessionManager } from "@earendil-works/pi-coding-agent";
import { registerPerkTool } from "../pi/perkTool.ts";
import {
  COHORT_SETTINGS,
  fakePerkRouter,
  loadAt,
  type PerkSession,
  plantSession,
  recordingRuntime,
  scaffoldRepo,
  staged,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";

before(ensureToolCatalog);

const PRINT = process.env.PERK_PRINT_DISCOVERY_CENSUS === "1";
const PROBE = "fixture_nested_probe";
const PARENT_ID = `call-${PROBE}`;

/** One nested call the probe makes, and what it observed. */
type NestedCall = { name: string; args: Record<string, unknown>; signal?: AbortSignal };
type Observed = { isError: boolean; text: string; structuredContent: unknown };

/**
 * A gate-allowed, implement-only action perk tool that makes the scripted nested calls through
 * `ctx.executeTool(name, args, { signal })` and records each outcome.
 */
function nestedProbe(script: { calls: NestedCall[] }, observed: Observed[]): InlineExtension {
  return {
    name: "perk-nested-probe",
    factory: (pi) => {
      registerPerkTool(
        pi,
        {
          name: PROBE,
          label: PROBE,
          description: "Make the scripted nested calls (test-only).",
          parameters: { type: "object", additionalProperties: false, properties: {} } as never,
          async execute(_id, _params, _signal, _onUpdate, ctx) {
            for (const call of script.calls) {
              const outcome = await ctx.executeTool(
                call.name,
                call.args,
                call.signal !== undefined ? { signal: call.signal } : {},
              );
              const result = outcome.result as AgentToolResult<unknown>;
              observed.push({
                isError: outcome.isError,
                text: result.content.map((c) => (c.type === "text" ? c.text : "")).join(""),
                structuredContent: result.structuredContent,
              });
            }
            return { content: [{ type: "text" as const, text: "probed" }], details: {} };
          },
        },
        { stages: ["implement"], gated: "allowed", kind: "action" },
      );
    },
  };
}

/** The fixed `perk objective stack status --json` payload the fake cold door serves. */
const STATUS = { success: true, objective: { id: "7" }, no_train: "no stacked train" };

/** A nested-call record as Pi persists it on the parent tool result. */
type NestedRecord = {
  id: string;
  name: string;
  status: string;
  arguments?: unknown;
  argumentsBytes?: number;
  error?: string;
};

/** The `nestedCalls` record on the persisted result of the LAST probe call. */
function lastProbeRecord(h: PerkSession): { calls: NestedRecord[]; complete: boolean } {
  const entries = h.session.sessionManager.getBranch() as unknown as {
    type: string;
    message?: { role?: string; toolCallId?: string; nestedCalls?: unknown };
  }[];
  const results = entries.filter(
    (e) =>
      e.type === "message" &&
      e.message?.role === "toolResult" &&
      e.message.toolCallId === PARENT_ID,
  );
  const record = results.at(-1)?.message?.nestedCalls;
  assert.ok(record !== undefined, "the parent tool result carries nestedCalls");
  return record as { calls: NestedRecord[]; complete: boolean };
}

test("nested execution in the cohort (A): a deferred inactive member is callable and recorded ok; a pre-aborted signal and an oversized argument record as Pi pins them", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ stage: "implement", mode: "read-write" }]);
  const bin = fakePerkRouter(cwd, { "objective stack": { json: STATUS } });
  const script: { calls: NestedCall[] } = { calls: [] };
  const observed: Observed[] = [];
  const rt = await recordingRuntime();
  const h = await loadAt(cwd, {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    extraExtensions: [toolSearch(), nestedProbe(script, observed)],
    settings: COHORT_SETTINGS,
    sessionManager: SessionManager.open(file),
  });
  try {
    if (PRINT) process.stderr.write(`nested probe session: ${file}\n`);
    assert.equal(h.toolInfo("objective_stack_status")?.exposure, "deferred");
    assert.ok(!h.session.getActiveToolNames().includes("objective_stack_status"), "inactive");
    assert.ok(h.session.getCallableToolNames().includes("objective_stack_status"), "callable");

    // 1. The deferred, inactive query resolves to its structured value; the call records ok.
    script.calls = [{ name: "objective_stack_status", args: { objective: "7" } }];
    rt.callThenStop(PROBE, {});
    await h.session.prompt("read the stack status through the probe");
    assert.equal(observed.length, 1, "the probe ran");
    assert.equal(observed[0]?.isError, false, observed[0]?.text);
    assert.deepEqual(observed[0]?.structuredContent, { ok: true, objective: "7", status: STATUS });
    const ok = lastProbeRecord(h);
    assert.equal(ok.complete, true);
    assert.deepEqual(
      ok.calls.map(({ id, name, status, arguments: args }) => ({ id, name, status, args })),
      [
        {
          id: `${PARENT_ID}/1`,
          name: "objective_stack_status",
          status: "ok",
          args: { objective: "7" },
        },
      ],
    );
    assert.ok(
      !h.session.getActiveToolNames().includes("objective_stack_status"),
      "a nested call never activates the deferred tool",
    );

    // 2. A pre-aborted signal: the nested call fails and Pi records the error.
    const aborted = new AbortController();
    aborted.abort();
    script.calls = [
      { name: "objective_stack_status", args: { objective: "7" }, signal: aborted.signal },
    ];
    rt.callThenStop(PROBE, {});
    await h.session.prompt("read it again, cancelled");
    assert.equal(observed[1]?.isError, true, observed[1]?.text);
    const cancelled = lastProbeRecord(h);
    if (PRINT) process.stderr.write(`cancelled record: ${JSON.stringify(cancelled)}\n`);
    assert.equal(cancelled.calls.length, 1);
    assert.equal(cancelled.calls[0]?.status, "error");
    assert.match(cancelled.calls[0]?.error ?? "", /aborted/i, "the abort text is recorded");
    assert.equal(cancelled.complete, true, "a finished error call keeps the record complete");

    // 3. An argument over Pi's 8 KiB per-call limit: recorded by size only, record incomplete.
    const findings = [
      { path: "x.ts", line: 1, severity: "minor", confidence: "low", body: "x".repeat(9000) },
    ];
    script.calls = [{ name: "push_annotations", args: { angle: "probe", findings } }];
    rt.callThenStop(PROBE, {});
    await h.session.prompt("push an oversized batch");
    assert.equal(observed[2]?.isError, true, "the tool refuses outside a door-opened surface");
    const oversized = lastProbeRecord(h);
    if (PRINT) process.stderr.write(`oversized record: ${JSON.stringify(oversized)}\n`);
    const [call] = oversized.calls;
    assert.equal(call?.name, "push_annotations");
    assert.match(call?.error ?? "", /no annotation surface is primed/, "the tool's own refusal");
    assert.ok((call?.argumentsBytes ?? 0) > 8 * 1024, "the argument size is recorded");
    assert.equal(call !== undefined && "arguments" in call, false, "the arguments are omitted");
    assert.equal(oversized.complete, false);
  } finally {
    h.dispose();
  }
});

test("nested execution under the gate (A): a nested deferred member and a nested write meet the backstop with their parent call id", async () => {
  const rt = await recordingRuntime();
  const script: { calls: NestedCall[] } = {
    calls: [
      { name: "objective_stack_status", args: { objective: "7" } },
      { name: "write", args: { path: "nested-target.txt", content: "nested\n" } },
    ],
  };
  const observed: Observed[] = [];
  const h = await staged("implement", "read-only", {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch(), nestedProbe(script, observed)],
    settings: COHORT_SETTINGS,
  });
  const runner = h.session.extensionRunner;
  const seen: { toolName: string; parentToolCallId?: string; reason?: string }[] = [];
  const emit = runner.emitToolCall.bind(runner);
  runner.emitToolCall = async (event) => {
    const result = await emit(event);
    if ((event as { parentToolCallId?: string }).parentToolCallId !== undefined) {
      seen.push({
        toolName: event.toolName,
        parentToolCallId: (event as { parentToolCallId?: string }).parentToolCallId,
        reason: (result as { reason?: string } | undefined)?.reason,
      });
    }
    return result;
  };
  try {
    assert.equal(h.toolInfo("objective_stack_status")?.exposure, "deferred", "a cohort session");
    rt.callThenStop(PROBE, {});
    await h.session.prompt("probe under the gate");
    assert.equal(observed.length, 2, "the probe ran (it is gate-allowed)");
    assert.ok(observed.every((o) => o.isError));
    assert.deepEqual(seen, [
      {
        toolName: "objective_stack_status",
        parentToolCallId: PARENT_ID,
        reason: "perk read-only mode: objective_stack_status is blocked (tool not allowlisted).",
      },
      {
        toolName: "write",
        parentToolCallId: PARENT_ID,
        reason: "perk read-only mode: write is blocked (file modifications disabled).",
      },
    ]);
  } finally {
    h.dispose();
  }
});
