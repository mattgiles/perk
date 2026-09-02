// The wave-over-real-RPC-adapter integration suite: the PRODUCTION `createReportWave` factory
// driven on a bare fake bus, answered by the shared `createFakeSubagents` responder — proving,
// at the offline tier, the behaviors the memory adapter can only simulate: the real spawn (v1
// envelope + the fixed spawn contract), completion CORRELATION (a foreign completion on the
// advertised channel is ignored; the matching identity settles), best-effort STOP on timeout
// (the recorded stop request names the spawned run), the durable AGGREGATE (a real temp
// `status.json` read through the adapter), and PER-LAUNCH ADAPTER FRESHNESS (two overlapping
// waves each ping+subscribe independently; out-of-order completions correlate to the right
// refs). The live pi-subagents leg remains the phase dogfood's.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createFakeSubagents, waveScriptItems } from "../testing/fakeSubagents.ts";
import { createReportWave, type ReportWaveRequest } from "./reportWave.ts";
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

function makeSpec(overrides: Partial<ReportWaveRequest> = {}): ReportWaveRequest {
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

test("rpc integration: the real spawn envelope + the durable aggregate round-trip", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS }]);
  fake.attach(bus);
  const spec = makeSpec({ model: "anthropic/claude-sonnet-4" });
  const result = await createReportWave(bus).run(spec);

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
  const wave = createReportWave(bus);
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;

  // Another run completes on the same advertised channel — the wave must NOT settle on it
  // (still `running` under a tiny env grace; the ref stays pending).
  fake.emit({ id: "foreign-run", asyncDir: "/nowhere/foreign-run" });
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "30";
  try {
    assert.deepEqual(await wave.collect(start.ref), { kind: "running" });
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }

  fake.complete(0);
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  const result = collected.result;
  assert.equal(result.complete, true);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["plan-fidelity", "correctness"],
  );
  assert.equal(result.receipt.runId, start.runId);
});

test("rpc integration: timeout stops the real run best-effort (the recorded stop names it)", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ delivery: "never" }]);
  fake.attach(bus);
  const result = await createReportWave(bus).run(makeSpec({ timeoutMs: 30 }));
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "timeout"]],
  );
  assert.equal(result.receipt.state, "timed-out");
  assert.equal(fake.stops.length, 1);
  assert.equal(fake.stops[0]?.id, result.receipt.runId, "the stop request names the spawned run");
});

test("rpc integration: two OVERLAPPING waves ride fresh per-launch adapters (out-of-order correlation)", async () => {
  // NEW coverage (not a port): the production factory constructs a FRESH rpc adapter per
  // launch — each launch pings + subscribes independently (no shared advertised state), and
  // completions arriving OUT OF LAUNCH ORDER correlate to the right refs.
  const bus = createFakeBus();
  let pings = 0;
  const countingBus: WaveBus = {
    emit(channel, data) {
      if (
        typeof data === "object" &&
        data !== null &&
        (data as { method?: unknown }).method === "ping"
      ) {
        pings += 1;
      }
      bus.emit(channel, data);
    },
    on: (channel, handler) => bus.on(channel, handler),
  };
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS, delivery: "manual" }]);
  fake.attach(bus);
  const wave = createReportWave(countingBus);
  const a = await wave.start(
    makeSpec({
      assignments: [
        { key: "plan-fidelity", agent: "perk.pr-reviewer", task: "review plan fidelity" },
        { key: "correctness", agent: "perk.pr-reviewer", task: "review correctness" },
      ],
    }),
  );
  const b = await wave.start(
    makeSpec({
      assignments: [
        { key: "tests", agent: "perk.pr-reviewer", task: "review tests" },
        { key: "quality", agent: "perk.pr-reviewer", task: "review quality" },
      ],
    }),
  );
  assert.equal(a.ok, true);
  assert.equal(b.ok, true);
  if (!a.ok || !b.ok) return;
  assert.equal(pings, 2, "each launch pings independently (a fresh adapter per launch)");
  assert.equal(fake.spawns.length, 2);
  assert.notEqual(a.runId, b.runId);

  // Complete OUT of launch order: B first — B drains while A stays pending…
  fake.complete(1);
  const collectedB = await wave.collect(b.ref);
  assert.equal(collectedB.kind, "settled");
  if (collectedB.kind !== "settled") return;
  assert.deepEqual(
    collectedB.result.reports.map((r) => r.key),
    ["tests", "quality"],
  );
  assert.equal(collectedB.result.receipt.runId, b.runId);
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "30";
  try {
    assert.deepEqual(await wave.collect(a.ref), { kind: "running" });
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }

  // …then A completes and drains with ITS reports (no cross-wave bleed).
  fake.complete(0);
  const collectedA = await wave.collect(a.ref);
  assert.equal(collectedA.kind, "settled");
  if (collectedA.kind !== "settled") return;
  assert.deepEqual(
    collectedA.result.reports.map((r) => r.key),
    ["plan-fidelity", "correctness"],
  );
  assert.equal(collectedA.result.receipt.runId, a.runId);
});
