// The runner-over-real-RPC-adapter integration suite: `startReportWave`/`runReportWave` driven
// through the PRODUCTION `createRpcWaveAdapter` on a bare fake bus, answered by the shared
// `createFakeSubagents` responder — proving, at the offline tier, the four behaviors the memory
// adapter can only simulate: the real spawn (v1 envelope + the fixed spawn contract), completion
// CORRELATION (a foreign completion on the advertised channel is ignored; the matching identity
// settles), best-effort STOP on timeout (the recorded stop request names the spawned run), and
// the durable AGGREGATE (a real temp `status.json` read through the adapter). The live
// pi-subagents leg remains the phase dogfood's.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createFakeSubagents, waveScriptItems } from "../testing/fakeSubagents.ts";
import { runReportWave, startReportWave, type WaveSpec } from "./reportWave.ts";
import { createRpcWaveAdapter } from "./rpcAdapter.ts";
import { WAVE_ACCEPTANCE, type WaveBus } from "./transport.ts";

/** A synchronous in-memory bus (the adapter-contract suite's shape). */
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
      return () => {
        set?.delete(handler);
      };
    },
  };
}

function makeSpec(overrides: Partial<WaveSpec> = {}): WaveSpec {
  return {
    flow: "pr-review",
    assignments: [
      { key: "plan-fidelity", agent: "perk.pr-reviewer", task: "review plan fidelity" },
      { key: "correctness", agent: "perk.pr-reviewer", task: "review correctness" },
    ],
    outputSchema: { type: "object", properties: { verdict: { type: "string" } } },
    completeness: "strict",
    timeoutMs: 5_000,
    ...overrides,
  };
}

/** One ok report per lane key, derived from the actually-spawned script. */
const DERIVE_REPORTS = async (script: string): Promise<unknown> =>
  waveScriptItems(script).map(({ key }) => ({
    key,
    ok: true,
    error: null,
    report: { angle: key, verdict: "clean" },
  }));

/** Probe whether a promise settles within `ms` (the still-pending assertion helper). */
async function settlesWithin(promise: Promise<unknown>, ms: number): Promise<boolean> {
  return await Promise.race([
    promise.then(() => true),
    new Promise<boolean>((resolve) => setTimeout(() => resolve(false), ms)),
  ]);
}

test("rpc integration: the real spawn envelope + the durable aggregate round-trip", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS }]);
  fake.attach(bus);
  const spec = makeSpec({ model: "anthropic/claude-sonnet-4" });
  const result = await runReportWave(createRpcWaveAdapter(bus), spec);

  // The spawn crossed the real v1 envelope with the fixed module contract.
  assert.equal(fake.spawns.length, 1);
  const spawn = fake.spawns[0] as {
    workflowScript?: string;
    async?: boolean;
    mission?: boolean;
    context?: string;
    acceptance?: unknown;
    outputSchema?: unknown;
    model?: string;
    timeoutMs?: number;
  };
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.deepEqual(spawn.acceptance, WAVE_ACCEPTANCE);
  assert.deepEqual(spawn.outputSchema, spec.outputSchema);
  assert.equal(spawn.model, "anthropic/claude-sonnet-4");
  assert.equal(spawn.timeoutMs, 5_000);
  assert.deepEqual(
    waveScriptItems(String(spawn.workflowScript ?? "")).map(({ key }) => key),
    ["plan-fidelity", "correctness"],
  );

  // The aggregate was read from the run's REAL temp status.json through the adapter.
  assert.equal(result.complete, true);
  assert.deepEqual(result.reports, [
    { key: "plan-fidelity", report: { angle: "plan-fidelity", verdict: "clean" } },
    { key: "correctness", report: { angle: "correctness", verdict: "clean" } },
  ]);
  assert.deepEqual(result.failures, []);
  assert.equal(result.receipt.state, "complete");
});

test("rpc integration: a FOREIGN completion is ignored; the matching manual delivery settles", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS, delivery: "manual" }]);
  fake.attach(bus);
  const start = await startReportWave(createRpcWaveAdapter(bus), makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;

  // Another run completes on the same advertised channel — the wave must NOT settle on it.
  fake.emit({ id: "foreign-run", asyncDir: "/nowhere/foreign-run" });
  assert.equal(await settlesWithin(start.result, 30), false);

  fake.complete(0);
  const result = await start.result;
  assert.equal(result.complete, true);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["plan-fidelity", "correctness"],
  );
  assert.equal(result.receipt.runId, start.handle.asyncId);
});

test("rpc integration: timeout stops the real run best-effort (the recorded stop names it)", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ delivery: "never" }]);
  fake.attach(bus);
  const result = await runReportWave(createRpcWaveAdapter(bus), makeSpec({ timeoutMs: 30 }));
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "timeout"]],
  );
  assert.equal(result.receipt.state, "timed-out");
  assert.equal(fake.stops.length, 1);
  assert.equal(fake.stops[0]?.id, result.receipt.runId, "the stop request names the spawned run");
});
