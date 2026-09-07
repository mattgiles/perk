// RPC-envelope specifics beyond the shared adapter contract: the exact v1 request envelope
// shape, bounded reply timeouts (ping → null, spawn → throw), `success: false` narrowing to a
// typed throw, the advertised-channel subscription (never a pinned channel name), reply-listener
// disposal after settle, and the capability-check misses that make ping return null.

import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  createRpcWaveAdapter,
  WAVE_RPC_PING_TIMEOUT_MS,
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REPLY_TIMEOUT_MS,
  WAVE_RPC_REQUEST_EVENT,
} from "./rpcAdapter.ts";
import { WAVE_ACCEPTANCE, type WaveBus, type WaveSpawnParams } from "./transport.ts";

/** A synchronous fake bus that additionally exposes live handler counts per channel. */
function createFakeBus(): WaveBus & { handlerCount(channel: string): number } {
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
    handlerCount(channel) {
      return channels.get(channel)?.size ?? 0;
    },
  };
}

interface CapturedRequest {
  version?: unknown;
  requestId?: unknown;
  method?: unknown;
  params?: unknown;
  source?: unknown;
}

/** Install a scripted responder; returns the captured request envelopes in arrival order. */
function respond(
  bus: WaveBus,
  script: (request: CapturedRequest) => Record<string, unknown> | null,
): CapturedRequest[] {
  const captured: CapturedRequest[] = [];
  bus.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
    const request = raw as CapturedRequest;
    captured.push(request);
    const payload = script(request);
    if (payload === null) return; // scripted silence — exercises the reply timeout
    bus.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${String(request.requestId)}`, {
      version: WAVE_RPC_PROTOCOL_VERSION,
      requestId: request.requestId,
      method: request.method,
      ...payload,
    });
  });
  return captured;
}

function pingData(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    version: WAVE_RPC_PROTOCOL_VERSION,
    methods: ["ping", "status", "spawn", "steer", "interrupt", "stop", "resume"],
    capabilities: { asyncSpawn: true },
    events: { asyncComplete: "subagent:async-complete" },
    session: {},
    ...overrides,
  };
}

function spawnParams(): WaveSpawnParams {
  return {
    workflowScript: "return [];",
    async: true,
    mission: false,
    context: "fresh",
    acceptance: WAVE_ACCEPTANCE,
    outputSchema: { type: "object" },
    timeoutMs: 60_000,
  };
}

test("requests carry the v1 envelope: version, requestId, method, params, source.extension", async () => {
  const bus = createFakeBus();
  const captured = respond(bus, (request) => {
    if (request.method === "ping") return { success: true, data: pingData() };
    return { success: true, data: { text: "ok", details: { asyncId: "a1", asyncDir: "/d1" } } };
  });
  const adapter = createRpcWaveAdapter(bus);
  await adapter.ping();
  const params = spawnParams();
  await adapter.spawn(params);

  assert.equal(captured.length, 2);
  const ping = captured[0];
  assert.equal(ping?.version, 1);
  assert.equal(ping?.method, "ping");
  assert.equal(typeof ping?.requestId, "string");
  assert.notEqual(ping?.requestId, "");
  assert.deepEqual(ping?.source, { extension: "perk" });
  assert.ok(ping !== undefined && !("params" in ping), "ping must omit params entirely");
  const spawn = captured[1];
  assert.equal(spawn?.method, "spawn");
  assert.deepEqual(spawn?.params, params);
  assert.deepEqual(spawn?.source, { extension: "perk" });
});

test("a silent responder times ping out to null (fast loud degrade)", async () => {
  assert.equal(WAVE_RPC_PING_TIMEOUT_MS, 5_000);
  process.env.PERK_WAVE_RPC_PING_MS = "20";
  try {
    const adapter = createRpcWaveAdapter(createFakeBus());
    assert.equal(await adapter.ping(), null);
  } finally {
    delete process.env.PERK_WAVE_RPC_PING_MS;
  }
});

test("a silent responder times spawn out to a throw", async () => {
  assert.equal(WAVE_RPC_REPLY_TIMEOUT_MS, 30_000);
  process.env.PERK_WAVE_RPC_REPLY_MS = "20";
  try {
    const bus = createFakeBus();
    respond(bus, (request) =>
      request.method === "ping" ? { success: true, data: pingData() } : null,
    );
    const adapter = createRpcWaveAdapter(bus);
    assert.notEqual(await adapter.ping(), null);
    await assert.rejects(adapter.spawn(spawnParams()), /spawn timed out after 20ms/);
  } finally {
    delete process.env.PERK_WAVE_RPC_REPLY_MS;
  }
});

test("a success:false reply narrows to a typed throw carrying code and message", async () => {
  const bus = createFakeBus();
  respond(bus, (request) =>
    request.method === "ping"
      ? { success: true, data: pingData() }
      : { success: false, error: { code: "invalid_params", message: "workflowScript required" } },
  );
  const adapter = createRpcWaveAdapter(bus);
  await adapter.ping();
  await assert.rejects(adapter.spawn(spawnParams()), /invalid_params: workflowScript required/);
});

test("ping misses null out: asyncSpawn false, spawn absent from methods, empty asyncComplete", async () => {
  const cases: Array<Record<string, unknown>> = [
    { capabilities: { asyncSpawn: false } },
    { methods: ["ping", "status"] },
    { events: { asyncComplete: "" } },
    { events: {} },
  ];
  for (const overrides of cases) {
    const bus = createFakeBus();
    respond(bus, () => ({ success: true, data: pingData(overrides) }));
    const adapter = createRpcWaveAdapter(bus);
    assert.equal(await adapter.ping(), null, `expected null for ${JSON.stringify(overrides)}`);
  }
});

test("a spawn reply without asyncId/asyncDir details throws", async () => {
  const bus = createFakeBus();
  respond(bus, (request) =>
    request.method === "ping"
      ? { success: true, data: pingData() }
      : { success: true, data: { text: "ok", details: { asyncId: "a1" } } },
  );
  const adapter = createRpcWaveAdapter(bus);
  await adapter.ping();
  await assert.rejects(adapter.spawn(spawnParams()), /no asyncDir/);
});

test("onComplete subscribes the ADVERTISED channel, honoring a nonstandard name", async () => {
  const bus = createFakeBus();
  respond(bus, () => ({
    success: true,
    data: pingData({ events: { asyncComplete: "custom:wave-done" } }),
  }));
  const adapter = createRpcWaveAdapter(bus);
  const ping = await adapter.ping();
  assert.equal(ping?.asyncCompleteEvent, "custom:wave-done");

  const received: Array<{ asyncId?: string; asyncDir?: string }> = [];
  adapter.onComplete((completion) => received.push(completion));
  // The standard channel name must be inert — only the advertised one is subscribed.
  bus.emit("subagent:async-complete", { id: "a1", asyncDir: "/d1" });
  assert.equal(received.length, 0);
  bus.emit("custom:wave-done", { id: "a1", asyncDir: "/d1", state: "complete" });
  assert.deepEqual(received, [{ asyncId: "a1", asyncDir: "/d1", state: "complete" }]);
  // Malformed payloads are dropped, never surfaced as phantom completions.
  bus.emit("custom:wave-done", "not an object");
  assert.equal(received.length, 1);
});

test("the per-request reply listener is disposed once the reply settles", async () => {
  const bus = createFakeBus();
  const captured = respond(bus, () => ({ success: true, data: pingData() }));
  const adapter = createRpcWaveAdapter(bus);
  await adapter.ping();
  const replyChannel = `${WAVE_RPC_REPLY_EVENT_PREFIX}${String(captured[0]?.requestId)}`;
  assert.equal(bus.handlerCount(replyChannel), 0);
});

test("stop swallows a rejecting responder (best-effort by contract)", async () => {
  const bus = createFakeBus();
  const captured = respond(bus, (request) => {
    if (request.method === "ping") return { success: true, data: pingData() };
    return { success: false, error: { code: "invalid_state", message: "already terminal" } };
  });
  const adapter = createRpcWaveAdapter(bus);
  await adapter.ping();
  await adapter.stop({ asyncId: "a1", asyncDir: "/d1" });
  const stop = captured.at(-1);
  assert.equal(stop?.method, "stop");
  assert.deepEqual(stop?.params, { id: "a1" });
});

test("readAggregate throws on a missing or corrupt status.json (aggregate-unreadable upstream)", async () => {
  const adapter = createRpcWaveAdapter(createFakeBus());
  const missingDir = mkdtempSync(join(tmpdir(), "perk-wave-rpc-"));
  await assert.rejects(adapter.readAggregate({ asyncId: "a1", asyncDir: missingDir }));

  const corruptDir = mkdtempSync(join(tmpdir(), "perk-wave-rpc-"));
  writeFileSync(join(corruptDir, "status.json"), "{not json");
  await assert.rejects(adapter.readAggregate({ asyncId: "a1", asyncDir: corruptDir }));

  const stateless = mkdtempSync(join(tmpdir(), "perk-wave-rpc-"));
  writeFileSync(join(stateless, "status.json"), JSON.stringify({ workflow: { value: [] } }));
  await assert.rejects(
    adapter.readAggregate({ asyncId: "a1", asyncDir: stateless }),
    /no state field/,
  );
});
