import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import type { TestContext } from "node:test";
import { DRAFT_REVIEW_REPORT_SCHEMA } from "../waves/draftReviewWave.ts";
import { reportWaveOver } from "../waves/reportWave.ts";
import { createRpcWaveAdapter } from "../waves/rpcAdapter.ts";
import { createFakeSubagents } from "./fakeSubagents.ts";

// Independent pins: fixtures carry hash-sized text, not vendored upstream implementation.
const SOURCES = {
  "src/runs/background/run-child-session.ts":
    "86f302832a21afdb0e79446d20d58be242d23c09f3d425bf4db254a09c10c940",
  "src/runs/background/subagent-runner.ts":
    "0468a7895fce4e7b54c7cb6616abb711c1860c531c103b963869c04072bf3a72",
  "src/runs/shared/structured-output.ts":
    "b251a8f692e9b8ddaa42692e30b751acb53529f34033c544f909bac9eaf90127",
};
function one<T>(value: T): [T, ...T[]] {
  return [value];
}

export function staleErrorFixture(
  t: TestContext,
  options: { key?: string; agent?: string; schema?: object } = {},
) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "perk-stale-error-")));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const engine = join(root, "engine");
  function put(path: string, data: string) {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, data);
  }
  const engineEntry = join(engine, "index.ts");
  put(engineEntry, "// test extension entry\n");
  put(join(engine, "package.json"), JSON.stringify({ name: "pi-subagents", version: "0.65.1" }));
  for (const [path, hash] of Object.entries(SOURCES)) put(join(engine, path), hash);
  const key = options.key ?? "custom";
  const agent = options.agent ?? "perk.draft-reviewer";
  const schema = structuredClone(options.schema ?? DRAFT_REVIEW_REPORT_SCHEMA);
  const report = { angle: key, streamed: false, summary: "Reviewed.", findings: [], fyi: [] };
  const handle = { asyncId: "workflow", asyncDir: join(root, "runs/workflow") };
  const childRoot = join(root, "runs/child");
  const outputPath = join(
    childRoot,
    "structured-output/pi-subagent-structured-capture/output.json",
  );
  const schemaPath = join(dirname(outputPath), "schema.json");
  const sessionFile = join(root, "session/run-0/session.jsonl");
  const error = "Run fan-out: 1/64 used, 63 remaining\nRequest timed out.";
  const parent = {
    runId: handle.asyncId,
    mode: "workflow",
    state: "complete",
    startedAt: 100,
    endedAt: 400,
    deadlineAt: 1000,
    sessionId: join(root, "session.jsonl"),
    cwd: root,
    toolCallId: "spawn-call",
    workflow: {
      value: one<{
        key: string;
        ok: boolean;
        report: unknown;
        error: string | null;
      }>({ key, ok: false, report: null, error }),
    },
    steps: one({
      workflowKey: key,
      agent,
      parentWorkflowRunId: handle.asyncId,
      status: "failed",
      async: true,
      runId: "child",
      sessionFile,
      error,
    }),
    workflowChildren: {
      version: 1,
      parentToolCallId: "spawn-call",
      inventoryComplete: true,
      workflowState: "completed",
      workflowRunId: handle.asyncId,
      children: one({ childId: key, agent, runId: "child", state: "failed" }),
    },
  };
  const child = {
    runId: "child",
    parentWorkflowRunId: handle.asyncId,
    workflowKey: key,
    mode: "single",
    state: "failed",
    sessionId: parent.sessionId,
    cwd: root,
    startedAt: 110,
    endedAt: 300,
    deadlineAt: 1000,
    timeoutMs: 900,
    processTerminal: {
      version: 1,
      state: "observed",
      runId: "child",
      runnerProcessInstanceId: "runner",
      instances: one({
        kind: "runner",
        processInstanceId: "runner",
        exitCode: 0,
        signal: null,
        closeObservedAt: 310,
      }),
    },
    steps: one({
      agent,
      context: "fresh",
      sessionFile,
      status: "failed",
      exitCode: 1,
      error: "Request timed out.",
      attemptedModels: ["test/model"],
      modelAttempts: one({
        model: "test/model",
        success: false,
        exitCode: 1,
        error: "Request timed out.",
      }),
      structuredOutputPath: outputPath,
      structuredOutputSchemaPath: schemaPath,
      effects: {
        settlementDiagnostic: {
          finalTextPresent: false,
          afterCompactionSettlement: false,
          mutation: { expected: false, attempted: false, observed: false },
          requiredOutput: { kind: "structured", missing: false, path: outputPath },
        },
      },
      acceptance: { status: "not-required", effectiveAcceptance: { level: "none" } },
    }),
  };
  const rootEvent = (type: string, ts: number, extra: object = {}) => ({
    type,
    ts,
    runId: "child",
    ...extra,
  });
  const wire = (type: string, extra: object = {}) => ({
    type,
    subagentSource: "child",
    subagentRunId: "child",
    subagentStepIndex: 0,
    subagentAgent: agent,
    observedAt: 200,
    ...extra,
  });
  const events: Record<string, unknown>[] = [
    rootEvent("subagent.run.started", 110, { mode: "single", cwd: root }),
    rootEvent("subagent.step.started", 120, { agent, stepIndex: 0 }),
    wire("message_end", {
      message: {
        role: "assistant",
        stopReason: "error",
        errorMessage: "Request timed out.",
        content: [],
      },
    }),
    wire("agent_end", { willRetry: true }),
    wire("auto_retry_start", { errorMessage: "Request timed out.", attempt: 1 }),
    wire("auto_retry_end", { success: true, attempt: 1 }),
    wire("message_end", {
      message: {
        role: "assistant",
        stopReason: "toolUse",
        content: [
          {
            type: "toolCall",
            name: "structured_output",
            id: "capture",
            arguments: { value: report },
          },
        ],
      },
    }),
    wire("tool_execution_start", {
      toolName: "structured_output",
      toolCallId: "capture",
      args: { value: report },
    }),
    wire("tool_execution_end", {
      toolName: "structured_output",
      toolCallId: "capture",
      isError: false,
      result: { terminate: true },
    }),
    wire("message_end", {
      message: {
        role: "toolResult",
        toolName: "structured_output",
        toolCallId: "capture",
        isError: false,
      },
    }),
    wire("agent_end", { willRetry: false }),
    wire("agent_settled"),
    rootEvent("subagent.step.failed", 290, { agent, stepIndex: 0, exitCode: 1 }),
    rootEvent("subagent.run.completed", 300, { status: "failed" }),
    rootEvent("subagent.run.process_terminal", 310, { processTerminal: child.processTerminal }),
  ];
  function flush() {
    put(join(handle.asyncDir, "status.json"), JSON.stringify(parent));
    put(join(childRoot, "status.json"), JSON.stringify(child));
    put(join(childRoot, "events.jsonl"), `${events.map((e) => JSON.stringify(e)).join("\n")}\n`);
    put(outputPath, JSON.stringify(report));
    put(schemaPath, JSON.stringify(schema));
  }
  flush();
  return {
    root,
    engine,
    engineEntry,
    handle,
    childRoot,
    outputPath,
    schemaPath,
    schema,
    report,
    parent,
    child,
    events,
    wire,
    flush,
    put,
    raw: () => readFileSync(join(handle.asyncDir, "status.json"), "utf8"),
    options: { engineEntry: () => engineEntry, assignments: [{ key, agent, schema }] },
    dependencies: { sourceDigest: (source: string) => source },
  };
}

/** Real adapter → transport → ReportWave → collect, with one proven and one unproven failure. */
export function staleErrorReviewWave(
  t: TestContext,
  options: { keys: string[]; agent: string; schema: object },
) {
  const f = staleErrorFixture(t, { ...options, key: options.keys[0] });
  for (const [i, key] of options.keys.slice(1).entries()) {
    f.parent.workflow.value.push(
      i === 0
        ? { key, ok: false, report: null, error: "Request timed out." }
        : { key, ok: true, report: { ...f.report, angle: key }, error: null },
    );
  }
  f.options.assignments = options.keys.map((key) => ({
    key,
    agent: options.agent,
    schema: options.schema,
  }));
  f.flush();
  const channels = new Map<string, Set<(data: unknown) => void>>();
  const bus = {
    emit(channel: string, data: unknown) {
      for (const handler of channels.get(channel) ?? []) handler(data);
    },
    on(channel: string, handler: (data: unknown) => void) {
      const handlers = channels.get(channel) ?? new Set<(data: unknown) => void>();
      channels.set(channel, handlers);
      handlers.add(handler);
      return () => {
        handlers.delete(handler);
      };
    },
  };
  const fake = createFakeSubagents([{ existingRun: f.handle, delivery: "manual" }]);
  fake.attach(bus);
  const wave = reportWaveOver(createRpcWaveAdapter(bus, f.options, f.dependencies));
  return {
    f,
    wave,
    fake,
    complete() {
      fake.emit({
        id: f.handle.asyncId,
        asyncDir: f.handle.asyncDir,
        state: "complete",
        results: [{ agent: options.keys[0], runId: "child", success: false }],
      });
    },
  };
}
