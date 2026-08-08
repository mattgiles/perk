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
import type { WaveAdapter, WaveBus, WaveRunHandle, WaveSpawnParams } from "./reportWave.ts";
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
  /** Arrange the durable aggregate `readAggregate(handle)` will see. */
  stageAggregate(handle: WaveRunHandle, aggregate: StagedAggregate): void;
}

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
      // The real payload spreads the result-file data (`id` + `asyncDir` identify the run).
      bus.emit(FAKE_ASYNC_COMPLETE_EVENT, {
        id: handle.asyncId,
        runId: handle.asyncId,
        asyncDir: handle.asyncDir,
        state: "complete",
        success: true,
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
