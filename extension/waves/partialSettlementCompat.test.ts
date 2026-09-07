// Controlled installed-source acceptance: real workflow timer/partial children and settlement
// projection through Perk's production collection path. Not a live executor/watcher/model test.
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { Socket } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { createFakeSubagents } from "../testing/fakeSubagents.ts";
import { createReportWave } from "./reportWave.ts";
import type { WaveAggregate, WaveBus } from "./transport.ts";

// Optional installed private modules have narrow TEST-ONLY interop views. A present incompatible
// installation fails; absence alone skips. Production never imports these engine internals.
interface NativeChild {
  key: string;
  ok: boolean;
  runId?: string;
  output: string;
  error?: string;
  structuredOutput?: unknown;
  artifactPaths: string[];
}
interface NativeTrace {
  key: string;
  state: string;
}
interface NativePartial {
  children: NativeChild[];
  trace: NativeTrace[];
}
interface NativeError extends Error {
  errorKind?: string;
  partial: NativePartial;
}
interface NativeWorkflow {
  WorkflowScriptError: new (...args: never[]) => NativeError;
  runWorkflowScript(options: {
    script: string;
    timeoutMs: number;
    signal: AbortSignal;
    launch(key: string, params: Record<string, unknown>, signal: AbortSignal): Promise<NativeChild>;
    status(): Promise<never>;
    onTrace(trace: NativeTrace[]): void;
  }): Promise<{ value: unknown } & NativePartial>;
}

function barrier() {
  let resolve = () => {};
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const installation = resolve(import.meta.dirname, "../../.pi/npm/node_modules/pi-subagents");

test("installed engine: native timeout retains validated sibling through report-wave collect", {
  skip:
    !existsSync(installation) &&
    "optional pi-subagents installation missing (not implementing-checkout evidence)",
  timeout: 60_000,
}, async (t) => {
  const root = realpathSync(installation);
  const scratch = mkdtempSync(join(tmpdir(), "perk-partial-compat-"));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const priorEnv = { ...process.env };
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
    throw new Error("network forbidden");
  });
  t.mock.method(Socket.prototype, "connect", () => {
    throw new Error("network forbidden");
  });
  const require = createRequire(join(root, "package.json"));
  const { createJiti } = require("jiti");
  const jiti = createJiti(join(root, "package.json"));
  const native = (await jiti.import(
    join(root, "src/workflows/scripted-workflow.ts"),
  )) as NativeWorkflow;
  const validator = (await jiti.import(join(root, "src/runs/shared/structured-output.ts"))) as {
    validateStructuredOutputValue(schema: object, value: unknown): Promise<{ status: string }>;
  };
  const settlement = (await jiti.import(join(root, "src/workflows/workflow-settlement.ts"))) as {
    planWorkflowSettlement(input: object): {
      status: Omit<WaveAggregate, "value">;
      publicResult: Record<string, unknown>;
    };
  };
  const channels = new Map<string, Set<(data: unknown) => void>>();
  const bus: WaveBus = {
    emit(channel, data) {
      for (const handler of [...(channels.get(channel) ?? [])]) handler(data);
    },
    on(channel, handler) {
      const handlers = channels.get(channel) ?? new Set();
      channels.set(channel, handlers);
      handlers.add(handler);
      return () => {
        handlers.delete(handler);
      };
    },
  };
  const report = { verdict: "clean" };
  const schema = {
    type: "object",
    properties: { verdict: { const: "clean" } },
    required: ["verdict"],
    additionalProperties: false,
  };
  const nativeTimeoutMs = 60_123;
  let fireNativeTimeout: (() => void) | undefined;
  let nativeTimerCount = 0;
  let nativeTimer: ReturnType<typeof setTimeout> | undefined;
  const realSetTimeout = globalThis.setTimeout;
  const clearSpy = t.mock.method(globalThis, "clearTimeout");
  t.after(() => clearTimeout(nativeTimer));
  t.mock.method(
    globalThis,
    "setTimeout",
    (callback: (...args: unknown[]) => void, ms?: number, ...args: unknown[]) => {
      if (ms === nativeTimeoutMs) {
        nativeTimerCount++;
        fireNativeTimeout = callback;
        // Keep a real handle for native cleanup, but never expire the test's outer deadline.
        nativeTimer = realSetTimeout(() => {}, ms);
        return nativeTimer;
      }
      return realSetTimeout(() => callback(...args), ms);
    },
  );
  let projected = false;
  let siblingAborted = false;
  const fake = createFakeSubagents([
    {
      executeSettlement: async (script, handle) => {
        t.after(() => rmSync(handle.asyncDir, { recursive: true, force: true }));
        const firstRecorded = barrier();
        const secondStarted = barrier();
        const siblingSettled = barrier();
        const controller = new AbortController();
        assert.deepEqual(fake.spawns[0]?.outputSchema, schema);
        const execution = native
          .runWorkflowScript({
            script,
            timeoutMs: nativeTimeoutMs,
            signal: AbortSignal.any([controller.signal, t.signal]),
            launch: async (key, _params, signal) => {
              if (key === "finished") {
                assert.deepEqual(await validator.validateStructuredOutputValue(schema, report), {
                  status: "valid",
                });
                return {
                  key,
                  runId: "native-finished",
                  ok: true,
                  output: "PRIVATE OUTPUT",
                  structuredOutput: report,
                  artifactPaths: [],
                };
              }
              assert.equal(key, "pending");
              secondStarted.resolve();
              return await new Promise<NativeChild>((resolve) => {
                const abort = () => {
                  signal.removeEventListener("abort", abort);
                  siblingAborted = true;
                  resolve({
                    key,
                    runId: "native-pending",
                    ok: false,
                    output: "",
                    error: "aborted",
                    artifactPaths: [],
                  });
                  siblingSettled.resolve();
                };
                signal.addEventListener("abort", abort, { once: true });
                if (signal.aborted) abort();
              });
            },
            status: async () => {
              throw new Error("no status/recovery channel permitted");
            },
            onTrace: (trace) => {
              if (trace.some((entry) => entry.key === "finished" && entry.state === "completed"))
                firstRecorded.resolve();
            },
          })
          .then(
            (value) => ({ ok: true as const, value }),
            (error: unknown) => ({ ok: false as const, error }),
          );
        try {
          await Promise.race([
            Promise.all([firstRecorded.promise, secondStarted.promise]),
            execution.then((outcome) => {
              throw new Error(`native workflow settled before barrier: ${JSON.stringify(outcome)}`);
            }),
          ]);
          assert.equal(siblingAborted, false);
          assert.equal(nativeTimerCount, 1);
          assert.ok(fireNativeTimeout);
          fireNativeTimeout();
          const outcome = await execution;
          assert.equal(outcome.ok, false);
          if (outcome.ok) throw new Error("native timeout unexpectedly returned a value");
          assert.ok(outcome.error instanceof native.WorkflowScriptError);
          const error = outcome.error;
          assert.equal(error.errorKind, "timeout");
          assert.equal("value" in error.partial, false);
          assert.deepEqual(
            error.partial.children
              .filter((child) => child.ok)
              .map((child) => child.structuredOutput),
            [report],
          );
          assert.ok(
            error.partial.trace.some(
              (entry) => entry.key === "finished" && entry.state === "completed",
            ),
          );
          assert.ok(
            error.partial.trace.some(
              (entry) => entry.key === "pending" && entry.state === "started",
            ),
          );
          await siblingSettled.promise;
          // Characterize the executor's public async projection using ACTUAL partial children.
          const children = error.partial.children.map((child) => ({
            workflowKey: child.key,
            runId: child.runId,
            success: child.ok,
            structuredOutput: child.structuredOutput,
            output: child.output,
            outputState:
              child.output.trim() || child.structuredOutput !== undefined ? "present" : "absent",
            error: child.error,
          }));
          const plan = settlement.planWorkflowSettlement({
            status: {
              runId: handle.asyncId,
              mode: "workflow",
              state: "failed",
              error: error.message,
              startedAt: 0,
              workflow: { trace: error.partial.trace },
            },
            summary: error.message,
            children,
            baseResult: { id: handle.asyncId, asyncDir: handle.asyncDir },
            terminalOutcome: { state: "partial", reason: "timeout" },
          });
          projected = true;
          return {
            aggregate: { state: plan.status.state, error: plan.status.error, value: undefined },
            completion: plan.publicResult,
          };
        } finally {
          controller.abort();
          await execution;
        }
      },
    },
  ]);
  fake.attach(bus);
  const wave = createReportWave(bus, { parentReadOnly: () => true });
  const start = await wave.start({
    flow: "partial-compat",
    assignments: ["finished", "pending"].map((key) => ({
      key,
      agent: "controlled",
      task: "report only",
    })),
    outputSchema: schema,
    completeness: "strict",
  });
  assert.ok(start.ok, JSON.stringify(start));
  assert.equal(projected, true);
  assert.equal(siblingAborted, true);
  assert.ok(nativeTimer);
  assert.ok(
    clearSpy.mock.calls.some((call) => call.arguments[0] === nativeTimer),
    "native timer released on settlement",
  );
  const durable = JSON.parse(readFileSync(join(start.asyncDir, "status.json"), "utf8"));
  assert.equal(durable.state, "failed");
  assert.equal("workflow" in durable, false);
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  assert.equal(collected.result.complete, false);
  assert.deepEqual(collected.result.reports, [{ key: "finished", report }]);
  assert.deepEqual(
    collected.result.failures.map(({ key, reason }) => [key, reason]),
    [
      [null, "run-failed"],
      ["pending", "missing-lane"],
    ],
  );
  assert.match(collected.result.failures[0]?.detail ?? "", /native partial: timeout/);
  assert.equal(collected.result.receipt.state, "failed");
  assert.doesNotMatch(
    JSON.stringify(collected.result.receipt),
    /PRIVATE OUTPUT|verdict|structuredOutput/,
  );
  assert.equal(fake.stops.length, 0);
  assert.equal(fake.spawns.length, 1);
  assert.deepEqual(await wave.collect(start.ref), { kind: "none" });
});
