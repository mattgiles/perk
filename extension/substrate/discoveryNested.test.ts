// The discovery pilot's nested-execution leg (contracts.md §8.40 "Native discovery"): in a
// discovery-cohort session a deferred, INACTIVE family member stays callable through Pi's
// nested-execution API (`ctx.executeTool`), its call is recorded on the parent tool result, and
// the read-only backstop still governs it — under the gate through its nested policy (only a
// gate-eligible query and the core builtin reads run through another tool). Driven through REAL
// bound AgentSessions (Mode A, fully offline). Its own file so the probe fixture's catalog
// registration never enters the census process (`discoveryPilot.test.ts`).
//
// `PERK_PRINT_DISCOVERY_CENSUS=1` prints the probe session's JSONL path to stderr for the
// `perk learn evidence --render` live leg.

import assert from "node:assert/strict";
import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
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
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { readOnlyBashVerdict } from "./readOnlyBash.ts";

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

test("nested execution under the gate (A): the nested policy admits the query and the builtin reads and refuses every write and action, each with its parent call id; a bounded writer is not even found", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(join(cwd, "notes.txt"), "nested notes\n");
  const file = plantSession(cwd, [{ stage: "implement", mode: "read-only" }]);
  const bin = fakePerkRouter(cwd, { "objective stack": { json: STATUS } });
  const rt = await recordingRuntime();
  const script: { calls: NestedCall[] } = {
    calls: [
      { name: "objective_stack_status", args: { objective: "7" } },
      { name: "read", args: { path: "notes.txt" } },
      // The scaffold is not a git repo: `ls` is the allowlisted read here.
      { name: "bash", args: { command: "ls" } },
      { name: "bash", args: { command: "touch nested-x" } },
      { name: "write", args: { path: "nested-target.txt", content: "nested\n" } },
      // A bounded writer (mode-over-stage: direct-eligible in the gated implement landing) is
      // model-only: agent-core answers not-found before any tool_call hook.
      { name: "plan_draft", args: { plan: "# nested" } },
      // The deferred INACTIVE action: nested-callable per Pi, refused by the nested policy.
      { name: "push_annotations", args: { angle: "probe", findings: [] } },
    ],
  };
  const observed: Observed[] = [];
  const h = await loadAt(cwd, {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    extraExtensions: [toolSearch(), nestedProbe(script, observed)],
    settings: COHORT_SETTINGS,
    sessionManager: SessionManager.open(file),
  });
  const runner = h.session.extensionRunner;
  const seen: { toolName: string; parentToolCallId?: string; reason?: string }[] = [];
  const emit = runner.emitToolCall.bind(runner);
  runner.emitToolCall = async (event) => {
    const result = await emit(event);
    if (event.parentToolCallId !== undefined) {
      seen.push({
        toolName: event.toolName,
        parentToolCallId: event.parentToolCallId,
        reason: (result as { reason?: string } | undefined)?.reason,
      });
    }
    return result;
  };
  const touchVeto = readOnlyBashVerdict("touch nested-x");
  assert.ok(!touchVeto.allowed, "touch is vetoed");
  const nested = (name: string, kind: string) =>
    `perk read-only mode: ${name} is blocked (nested call — ${kind} is never a nested grant; only gate-eligible queries and builtin reads run through another tool).`;
  try {
    assert.equal(h.toolInfo("objective_stack_status")?.exposure, "deferred", "a cohort session");
    assert.ok(!h.session.getActiveToolNames().includes("push_annotations"), "inactive");
    rt.callThenStop(PROBE, {});
    await h.session.prompt("probe under the gate");
    assert.equal(observed.length, script.calls.length, "the probe ran (it is gate-allowed)");
    assert.deepEqual(
      observed.map((o) => o.isError),
      [false, false, false, true, true, true, true],
      JSON.stringify(observed.map((o) => o.text)),
    );
    assert.deepEqual(observed[0]?.structuredContent, { ok: true, objective: "7", status: STATUS });
    assert.match(observed[1]?.text ?? "", /nested notes/, "the nested read saw the file");
    assert.match(observed[2]?.text ?? "", /notes\.txt/, "the nested ls listed it");
    assert.equal(existsSync(join(cwd, "nested-x")), false, "the vetoed touch never ran");
    assert.equal(existsSync(join(cwd, "nested-target.txt")), false, "the write never landed");
    assert.match(observed[5]?.text ?? "", /Tool plan_draft not found/, "the writer is not found");
    // Every call that reached tool_call carries the parent id; the writer never reaches it.
    assert.deepEqual(seen, [
      { toolName: "objective_stack_status", parentToolCallId: PARENT_ID, reason: undefined },
      { toolName: "read", parentToolCallId: PARENT_ID, reason: undefined },
      { toolName: "bash", parentToolCallId: PARENT_ID, reason: undefined },
      {
        toolName: "bash",
        parentToolCallId: PARENT_ID,
        reason: `perk read-only mode: command blocked (not allowlisted).\nCommand: touch nested-x\nReason: ${touchVeto.reason}`,
      },
      {
        toolName: "write",
        parentToolCallId: PARENT_ID,
        reason: "perk read-only mode: write is blocked (file modifications disabled).",
      },
      {
        toolName: "push_annotations",
        parentToolCallId: PARENT_ID,
        reason: nested("push_annotations", "an action tool"),
      },
    ]);
    assert.ok(
      !h.session.getActiveToolNames().includes("objective_stack_status"),
      "a nested call never activates the deferred tool",
    );
  } finally {
    h.dispose();
  }
});
