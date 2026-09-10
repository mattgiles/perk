// The wave-over-real-RPC-adapter integration suite: the PRODUCTION `createReportWave` factory
// driven on a bare fake bus, answered by the shared `createFakeSubagents` responder — proving,
// at the offline tier, the behaviors the memory adapter can only simulate: the real spawn (v1
// envelope + the fixed spawn contract), completion CORRELATION (a foreign completion on the
// advertised channel is ignored; the matching identity settles), best-effort STOP on timeout
// (the recorded stop request names the spawned run), the durable AGGREGATE (a real temp
// `status.json` read through the adapter), native PARTIAL settlement (the explicit
// `terminalOutcome` carrier retains the engine-validated sibling report while the wave stays
// incomplete), and PER-LAUNCH ADAPTER FRESHNESS (two overlapping waves each ping+subscribe
// independently; out-of-order completions correlate to the right refs). The live pi-subagents
// leg remains the phase dogfood's.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  createFakeSubagents,
  type FakeSettlement,
  waveScriptItems,
} from "../testing/fakeSubagents.ts";
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

test("rpc round-trip: every child carries the constant packet and caller-checkout placement", async () => {
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

  for (const item of waveScriptItems(String(spawn.workflowScript))) {
    assert.deepEqual(item.extensionBindings, { "perk.parent-restrictions/1": { readOnly: true } });
    assert.equal(item.worktree, false);
  }

  // The aggregate was read from the run's REAL temp status.json through the adapter.
  assert.equal(result.complete, true);
  assert.deepEqual(result.reports, [
    { key: "plan-fidelity", report: { angle: "plan-fidelity", verdict: "clean" } },
    { key: "correctness", report: { angle: "correctness", verdict: "clean" } },
  ]);
  assert.deepEqual(result.failures, []);
  assert.equal(result.receipt.state, "complete");
});

for (const shape of [
  "current",
  "legacy",
  "malformed",
  "foreign",
  "duplicate",
  "unmatched",
] as const) {
  test(`rpc receipts: ${shape} workflow identities are output-free and do not determine coverage`, async () => {
    const bus = createFakeBus();
    const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS, delivery: "manual" }]);
    fake.attach(bus);
    const wave = createReportWave(bus);
    const start = await wave.start(makeSpec());
    assert.ok(start.ok);
    if (!start.ok) return;
    const identities = [
      { childId: "correctness", runId: "child-b", agent: "perk.pr-reviewer" },
      { childId: "plan-fidelity", runId: "child-a", agent: "perk.pr-reviewer" },
    ];
    fake.emit({
      id: start.runId,
      asyncDir: start.asyncDir,
      state: "complete",
      results: ["a", "b"].map((id, i) => ({
        agent: shape === "legacy" ? ["plan-fidelity", "correctness"][i] : "perk.pr-reviewer",
        runId: `child-${id}`,
        success: true,
        output: "SECRET",
        summary: "SECRET",
        structuredOutput: { SECRET: true },
      })),
      ...(shape === "legacy"
        ? {}
        : {
            workflowChildren:
              shape === "malformed"
                ? []
                : {
                    version: 1,
                    workflowRunId: shape === "foreign" ? "foreign" : start.runId,
                    children:
                      shape === "unmatched"
                        ? []
                        : shape === "duplicate"
                          ? [...identities, ...identities]
                          : identities,
                  },
          }),
    });
    const collected = await wave.collect(start.ref);
    assert.equal(collected.kind, "settled");
    if (collected.kind !== "settled") return;
    assert.equal(collected.result.complete, true);
    assert.equal(collected.result.reports.length, 2);
    const children = collected.result.receipt.children;
    assert.deepEqual(
      children,
      ["current", "legacy"].includes(shape)
        ? [
            { key: "plan-fidelity", runId: "child-a", success: true, agent: "perk.pr-reviewer" },
            { key: "correctness", runId: "child-b", success: true, agent: "perk.pr-reviewer" },
          ]
        : [],
    );
    assert.doesNotMatch(JSON.stringify(collected.result.receipt), /SECRET|structuredOutput/);
  });
}

test("rpc integration: a failed aggregate row stays failed despite a report and successful receipt", async () => {
  const bus = createFakeBus();
  const report = { verdict: "clean" };
  const fake = createFakeSubagents([
    {
      delivery: "manual",
      value: [
        { key: "plan-fidelity", ok: false, error: "engine failure", report },
        { key: "correctness", ok: true, error: null, report },
      ],
    },
  ]);
  fake.attach(bus);
  const wave = createReportWave(bus);
  const start = await wave.start(makeSpec());
  assert.ok(start.ok);
  fake.emit({
    id: start.runId,
    asyncDir: start.asyncDir,
    state: "complete",
    results: [{ agent: "plan-fidelity", runId: "child", success: true }],
  });
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  assert.equal(collected.result.complete, false);
  assert.deepEqual(collected.result.reports, [{ key: "correctness", report }]);
  assert.deepEqual(collected.result.failures, [
    { key: "plan-fidelity", reason: "lane-failed", detail: "engine failure" },
  ]);
  assert.equal(collected.result.receipt.children[0]?.success, true);
  assert.equal(fake.spawns.length, 1);
  assert.equal(fake.stops.length, 0);
  assert.deepEqual(await wave.collect(start.ref), { kind: "none" });
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
  const fake = createFakeSubagents([
    { delivery: "never", executeSettlement: async () => partialFixture() },
  ]);
  fake.attach(bus);
  const result = await createReportWave(bus).run(makeSpec({ timeoutMs: 30 }));
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "timeout"]],
  );
  assert.equal(result.receipt.state, "timed-out");
  assert.deepEqual(
    result.reports,
    [],
    "an undelivered native partial payload is not recovery authority",
  );
  assert.equal(fake.stops.length, 1);
  assert.equal(fake.stops[0]?.id, result.receipt.runId, "the stop request names the spawned run");
});

test("rpc integration: adapter construction is per-launch inside the supplier (source pin)", () => {
  // The per-launch adapter freshness is not observable over the bus (a shared adapter would
  // still ping per launch and correlate per run), and the module deliberately ships no
  // test-only construction-count seam — so the invariant is pinned structurally: the module's
  // ONE `createRpcWaveAdapter` call site must be the lazy per-launch supplier arrow. Hoisting
  // the construction out of the supplier (one shared adapter, shared mutable ping state)
  // breaks this pin.
  const source = readFileSync(new URL("./reportWave.ts", import.meta.url), "utf8");
  const mentions = source.match(/createRpcWaveAdapter/g) ?? [];
  assert.equal(
    mentions.length,
    2,
    "reportWave.ts must reference createRpcWaveAdapter exactly twice: the import + the supplier",
  );
  assert.match(
    source,
    /waveOver\(\s*\(\)\s*=>\s*createRpcWaveAdapter\(bus\)/,
    "the one construction call must sit inside the per-launch supplier arrow",
  );
});

/** A native partial settlement: the durable aggregate failed without a `workflow.value`; the
 * completion event carries the explicit `terminalOutcome` plus one validated sibling report. */
function partialFixture(): FakeSettlement {
  return {
    aggregate: { state: "failed", error: "native failure", value: undefined },
    completion: {
      state: "failed",
      success: false,
      terminalOutcome: { state: "partial", reason: "timeout" },
      results: [
        {
          workflowKey: "plan-fidelity",
          runId: "child-a",
          success: true,
          structuredOutput: { verdict: "clean" },
        },
      ],
    },
  };
}

test("rpc integration: native partial settlement retains the validated sibling report; the wave stays incomplete", async () => {
  // The fixture's durable aggregate carries no `workflow.value`, so the retained report travels
  // the completion-carrier path: the real RPC adapter decoder, the transport's durable read and
  // the normalizer.
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeSettlement: async () => partialFixture() }]);
  fake.attach(bus);
  const result = await createReportWave(bus).run(makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(
    result.failures.map(({ key, reason }) => [key, reason]),
    [
      [null, "run-failed"],
      ["correctness", "missing-lane"],
    ],
  );
  assert.match(result.failures[0]?.detail ?? "", /native partial: timeout/);
  assert.equal(result.receipt.state, "failed");
  assert.doesNotMatch(JSON.stringify(result.receipt), /verdict|structuredOutput/);
  assert.equal(fake.stops.length, 0);
});

/** A native partial settlement whose `results` carry TWO rows for one workflowKey (distinct
 * child runs, different reports) beside one valid sibling row. */
function duplicatePartialFixture(): FakeSettlement {
  return {
    aggregate: { state: "failed", error: "native failure", value: undefined },
    completion: {
      state: "failed",
      success: false,
      terminalOutcome: { state: "partial", reason: "timeout" },
      results: [
        {
          workflowKey: "plan-fidelity",
          runId: "child-a",
          success: true,
          structuredOutput: { verdict: "clean", copy: 1 },
        },
        {
          workflowKey: "plan-fidelity",
          runId: "child-a2",
          success: true,
          structuredOutput: { verdict: "clean", copy: 2 },
        },
        {
          workflowKey: "correctness",
          runId: "child-b",
          success: true,
          structuredOutput: { verdict: "clean" },
        },
      ],
    },
  };
}

test("rpc integration: duplicate native results rows for one key collapse at the transport and classify malformed-report at the normalizer — evidence withheld end to end", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeSettlement: async () => duplicatePartialFixture() }]);
  fake.attach(bus);
  const result = await createReportWave(bus).run(makeSpec());
  assert.equal(result.complete, false);
  // Neither plan-fidelity report survives; the valid sibling does.
  assert.deepEqual(result.reports, [{ key: "correctness", report: { verdict: "clean" } }]);
  assert.deepEqual(
    result.failures.map(({ key, reason }) => [key, reason]),
    [
      [null, "run-failed"],
      ["plan-fidelity", "malformed-report"],
    ],
  );
  // The collapse happened at the transport tier: the normalizer saw ONE `ok: null` row, so its
  // own duplicate-count arm never fired — the classification and withholding still agree.
  const duplicateDetail = result.failures[1]?.detail ?? "";
  assert.match(duplicateDetail, /aggregate entry has no boolean 'ok'/);
  assert.doesNotMatch(duplicateDetail, /appears \d+ times/);
  assert.equal(result.receipt.state, "failed");
  assert.doesNotMatch(JSON.stringify(result.receipt), /verdict|structuredOutput|copy/);
  assert.equal(fake.stops.length, 0);
});

test("rpc integration: two OVERLAPPING waves through one factory correlate out of launch order", async () => {
  // NEW coverage (not a port): the behavioral half of per-launch freshness (the structural
  // half is the source pin above) — two overlapping launches each ping, and completions
  // arriving OUT OF LAUNCH ORDER correlate to the right refs with no cross-wave bleed.
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
  assert.equal(pings, 2, "each launch pings (the launch path never reuses a prior ping reply)");
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
