// The shared `WaveAdapter` contract suite: one set of behavioral assertions registered against
// BOTH adapters — the in-memory test double directly, and the production RPC adapter wired to a
// fake in-memory bus plus a scripted fake pi-subagents responder (replies mirror the v1 envelope
// in pi-subagents `src/extension/rpc.ts`; `readAggregate` reads a real `status.json` written to
// a temp dir). Keeping the double and the production adapter behaviorally aligned is what makes
// the runner's memory-adapter coverage trustworthy.

import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { test } from "node:test";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";
import type {
  WaveAdapter,
  WaveBus,
  WaveChildReceipt,
  WaveCompletion,
  WaveRunHandle,
  WaveSpawnParams,
} from "./reportWave.ts";
import {
  createRpcWaveAdapter,
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REQUEST_EVENT,
} from "./rpcAdapter.ts";

interface StagedAggregate {
  state: string;
  error?: string;
  value: unknown;
}

/** Adapter-specific plumbing the contract needs beyond the `WaveAdapter` interface itself. */
interface WaveAdapterHarness {
  adapter: WaveAdapter;
  /** Deliver one async-complete notification for a spawned run. */
  completeRun(handle: WaveRunHandle): void;
  /**
   * Deliver a completion carrying `RECEIPT_CHILDREN` through the flavor's native path. The RPC
   * flavor's raw payload additionally carries `output`/`summary`/`structuredOutput`, unknown
   * fields, and malformed rows — the adapter must strip/drop them without failing the wave.
   */
  completeRunDetailed(handle: WaveRunHandle): void;
  /** Arrange the durable aggregate `readAggregate(handle)` will see. */
  stageAggregate(handle: WaveRunHandle, aggregate: StagedAggregate): void;
}

/** The normalized receipt children every flavor's detailed completion must deliver. */
const RECEIPT_CHILDREN: WaveChildReceipt[] = [
  {
    key: "plan-fidelity",
    runId: "child-run-1",
    success: true,
    outputState: "present",
    artifactPaths: { outputPath: "/tmp/artifacts/child-run-1_output.md" },
  },
  { key: "correctness", runId: "child-run-2", success: false, outputState: "absent" },
];

const COMPLETION_KEYS = ["asyncId", "asyncDir", "state", "success", "children"];
const CHILD_KEYS = ["key", "agent", "runId", "success", "outputState", "artifactPaths"];

function minimalSpawnParams(): WaveSpawnParams {
  return {
    workflowScript: "return [];",
    async: true,
    mission: false,
    context: "fresh",
    outputSchema: { type: "object" },
    timeoutMs: 60_000,
  };
}

/** Register the shared behavioral assertions for one adapter flavor. */
export function assertWaveAdapterContract(
  name: string,
  makeHarness: () => WaveAdapterHarness,
): void {
  test(`${name}: ping advertises the async-complete channel`, async () => {
    const { adapter } = makeHarness();
    const ping = await adapter.ping();
    assert.notEqual(ping, null);
    assert.equal(typeof ping?.asyncCompleteEvent, "string");
    assert.notEqual(ping?.asyncCompleteEvent, "");
  });

  test(`${name}: spawn returns the detached run handle`, async () => {
    const { adapter } = makeHarness();
    await adapter.ping();
    const handle = await adapter.spawn(minimalSpawnParams());
    assert.equal(typeof handle.asyncId, "string");
    assert.notEqual(handle.asyncId, "");
    assert.equal(typeof handle.asyncDir, "string");
    assert.notEqual(handle.asyncDir, "");
  });

  test(`${name}: completions are delivered and unsubscribe stops delivery`, async () => {
    const harness = makeHarness();
    const { adapter } = harness;
    await adapter.ping();
    const received: Array<{ asyncId?: string; asyncDir?: string }> = [];
    const unsubscribe = adapter.onComplete((completion) => received.push(completion));
    const handle = await adapter.spawn(minimalSpawnParams());
    harness.completeRun(handle);
    assert.equal(received.length, 1);
    assert.ok(
      received[0]?.asyncId === handle.asyncId || received[0]?.asyncDir === handle.asyncDir,
      "completion does not identify the spawned run",
    );
    unsubscribe();
    harness.completeRun(handle);
    assert.equal(received.length, 1, "unsubscribed handler still received a completion");
  });

  test(`${name}: a completion without results carries no children (identity stays valid)`, async () => {
    const harness = makeHarness();
    const { adapter } = harness;
    await adapter.ping();
    const received: WaveCompletion[] = [];
    adapter.onComplete((completion) => received.push(completion));
    const handle = await adapter.spawn(minimalSpawnParams());
    harness.completeRun(handle);
    assert.equal(received.length, 1);
    assert.equal("children" in (received[0] ?? {}), false);
  });

  test(`${name}: a detailed completion normalizes output-free receipt children`, async () => {
    const harness = makeHarness();
    const { adapter } = harness;
    await adapter.ping();
    const received: WaveCompletion[] = [];
    adapter.onComplete((completion) => received.push(completion));
    const handle = await adapter.spawn(minimalSpawnParams());
    harness.completeRunDetailed(handle);
    assert.equal(received.length, 1);
    const completion = received[0];
    assert.ok(completion);
    assert.ok(
      completion.asyncId === handle.asyncId || completion.asyncDir === handle.asyncDir,
      "detailed completion does not identify the spawned run",
    );
    assert.equal(completion.state, "complete");
    assert.equal(completion.success, true);
    // Malformed rows dropped, unknown fields ignored, rich fields normalized.
    assert.deepEqual(completion.children, RECEIPT_CHILDREN);
    // The output-free invariant: no `output`/`summary`/`structuredOutput` (or any unknown
    // field) survives on the completion or its children.
    for (const key of Object.keys(completion)) {
      assert.ok(COMPLETION_KEYS.includes(key), `unexpected completion field '${key}'`);
    }
    for (const child of completion.children ?? []) {
      for (const key of Object.keys(child)) {
        assert.ok(CHILD_KEYS.includes(key), `unexpected receipt-child field '${key}'`);
      }
    }
  });

  test(`${name}: onComplete before a successful ping throws`, () => {
    const { adapter } = makeHarness();
    assert.throws(() => adapter.onComplete(() => {}), /ping/);
  });

  test(`${name}: stop never throws — live handle or bogus handle`, async () => {
    const { adapter } = makeHarness();
    await adapter.ping();
    const handle = await adapter.spawn(minimalSpawnParams());
    await adapter.stop(handle);
    await adapter.stop({ asyncId: "no-such-run", asyncDir: "/no/such/dir" });
  });

  test(`${name}: readAggregate narrows the durable aggregate`, async () => {
    const harness = makeHarness();
    const { adapter } = harness;
    await adapter.ping();
    const handle = await adapter.spawn(minimalSpawnParams());

    const value = [{ key: "alpha", ok: true, error: null, report: { verdict: "clean" } }];
    harness.stageAggregate(handle, { state: "complete", value });
    const complete = await adapter.readAggregate(handle);
    assert.equal(complete.state, "complete");
    assert.equal(complete.error, undefined);
    assert.deepEqual(complete.value, value);

    harness.stageAggregate(handle, { state: "failed", error: "boom", value: undefined });
    const failed = await adapter.readAggregate(handle);
    assert.equal(failed.state, "failed");
    assert.equal(failed.error, "boom");
    assert.equal(failed.value, undefined);
  });
}

// ------------------------------------------------------------------- the memory-adapter harness

function makeMemoryHarness(): WaveAdapterHarness {
  const adapter = createMemoryWaveAdapter({ completion: false });
  return {
    adapter,
    completeRun(handle) {
      adapter.emitCompletion({ asyncId: handle.asyncId, asyncDir: handle.asyncDir });
    },
    completeRunDetailed(handle) {
      // The memory flavor delivers the already-normalized shape (its input is typed).
      adapter.emitCompletion({
        asyncId: handle.asyncId,
        asyncDir: handle.asyncDir,
        state: "complete",
        success: true,
        children: RECEIPT_CHILDREN.map((child) => ({ ...child })),
      });
    },
    stageAggregate(_handle, aggregate) {
      adapter.setAggregate(aggregate);
    },
  };
}

// ---------------------------------------------------------------------- the RPC-adapter harness

/** A synchronous in-memory `WaveBus` (mirrors pi's EventBus: `on` returns an unsubscribe). */
function createFakeBus(): WaveBus {
  const channels = new Map<string, Set<(data: unknown) => void>>();
  return {
    emit(channel, data) {
      for (const handler of [...(channels.get(channel) ?? [])]) handler(data);
    },
    on(channel, handler) {
      let set = channels.get(channel);
      if (set === undefined) {
        set = new Set();
        channels.set(channel, set);
      }
      set.add(handler);
      return () => set.delete(handler);
    },
  };
}

const FAKE_ASYNC_COMPLETE_EVENT = "subagent:async-complete";

/**
 * A scripted fake pi-subagents responder: answers ping/spawn/stop on the v1 envelope. Each spawn
 * mints a real temp dir as the run's `asyncDir` (so `readAggregate` reads a real `status.json`);
 * stop replies `success: false` — proving the adapter's best-effort swallow at contract level.
 */
function installFakeResponder(bus: WaveBus): void {
  bus.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
    const request = raw as { requestId: string; method: string };
    const reply = (payload: Record<string, unknown>): void => {
      bus.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${request.requestId}`, {
        version: WAVE_RPC_PROTOCOL_VERSION,
        requestId: request.requestId,
        method: request.method,
        ...payload,
      });
    };
    if (request.method === "ping") {
      reply({
        success: true,
        data: {
          version: WAVE_RPC_PROTOCOL_VERSION,
          methods: ["ping", "status", "spawn", "steer", "interrupt", "stop", "resume"],
          capabilities: { asyncSpawn: true },
          events: {
            ready: "subagents:rpc:v1:ready",
            request: WAVE_RPC_REQUEST_EVENT,
            replyPrefix: WAVE_RPC_REPLY_EVENT_PREFIX,
            asyncComplete: FAKE_ASYNC_COMPLETE_EVENT,
            processTerminal: "subagent:process-terminal",
          },
          session: {},
        },
      });
      return;
    }
    if (request.method === "spawn") {
      const asyncDir = mkdtempSync(join(tmpdir(), "perk-wave-contract-"));
      reply({
        success: true,
        data: { text: "Started async run.", details: { asyncId: basename(asyncDir), asyncDir } },
      });
      return;
    }
    reply({
      success: false,
      error: { code: "not_found", message: `fake responder rejects ${request.method}` },
    });
  });
}

function makeRpcHarness(): WaveAdapterHarness {
  const bus = createFakeBus();
  installFakeResponder(bus);
  return {
    adapter: createRpcWaveAdapter(bus),
    completeRun(handle) {
      // A minimal payload: the result-file data's identifiers only (no `results` array).
      bus.emit(FAKE_ASYNC_COMPLETE_EVENT, {
        id: handle.asyncId,
        runId: handle.asyncId,
        asyncDir: handle.asyncDir,
      });
    },
    completeRunDetailed(handle) {
      // A realistic 0.45.0 workflow completion payload: the result-file fields plus the
      // watcher-normalized `results` rows — each row's `agent` carries the lane KEY, and rows
      // carry output/summary/structuredOutput plus unknown fields the adapter must never copy;
      // malformed rows (non-record / no agent) must be dropped without failing the wave.
      bus.emit(FAKE_ASYNC_COMPLETE_EVENT, {
        id: handle.asyncId,
        runId: handle.asyncId,
        toolCallId: "tc-1",
        agent: "workflow",
        mode: "workflow",
        asyncDir: handle.asyncDir,
        state: "complete",
        success: true,
        summary: "workflow finished",
        output: "workflow finished",
        results: [
          {
            agent: "plan-fidelity",
            runId: "child-run-1",
            output: "the child's full prose output",
            outputState: "present",
            structuredOutput: { angle: "plan-fidelity", verdict: "clean" },
            success: true,
            artifactPaths: { outputPath: "/tmp/artifacts/child-run-1_output.md", bogus: 42 },
            status: "completed",
            summary: "child summary",
            index: 0,
            artifactPath: "/tmp/artifacts/child-run-1_output.md",
            sessionPath: "/tmp/sessions/child-run-1.jsonl",
            children: [],
          },
          {
            agent: "correctness",
            runId: "child-run-2",
            output: "",
            outputState: "absent",
            success: false,
            summary: "child failed",
            artifactPath: "",
            unknownFutureField: { nested: true },
          },
          { agent: "", runId: "dropped-empty-agent" },
          "not a record",
          { runId: "dropped-no-agent" },
        ],
        workflow: { value: [] },
        timestamp: 1,
        durationMs: 2,
      });
    },
    stageAggregate(handle, aggregate) {
      writeFileSync(
        join(handle.asyncDir, "status.json"),
        JSON.stringify({
          runId: handle.asyncId,
          mode: "workflow",
          state: aggregate.state,
          ...(aggregate.error !== undefined ? { error: aggregate.error } : {}),
          startedAt: 0,
          workflow: { value: aggregate.value },
        }),
      );
    },
  };
}

assertWaveAdapterContract("memory adapter", makeMemoryHarness);
assertWaveAdapterContract("rpc adapter", makeRpcHarness);
