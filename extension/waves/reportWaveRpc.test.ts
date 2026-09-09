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
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import {
  createFakeSubagents,
  type FakeSettlement,
  type FakeSpawnPlan,
  waveScriptItems,
} from "../testing/fakeSubagents.ts";
import { createReportWave, type ReportWaveRequest } from "./reportWave.ts";
import { WAVE_RPC_REPLY_EVENT_PREFIX, WAVE_RPC_REQUEST_EVENT } from "./rpcAdapter.ts";
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

function partialFixture(
  value: unknown = undefined,
  results: unknown = [
    {
      workflowKey: "plan-fidelity",
      runId: "child-a",
      success: true,
      structuredOutput: { verdict: "clean" },
    },
  ],
): FakeSettlement {
  return {
    aggregate: { state: "failed", error: "native failure", value },
    completion: {
      state: "failed",
      success: false,
      terminalOutcome: { state: "partial", reason: "timeout" },
      results,
    },
  };
}

for (const value of [
  undefined,
  null,
  [],
  [{ key: "correctness", ok: true, report: { verdict: "durable" } }],
]) {
  test(`fake settlement preserves ${JSON.stringify(value) ?? "omitted"} value and overwrites identity`, async () => {
    const bus = createFakeBus();
    const fixture = partialFixture(value);
    const payloads: Record<string, unknown>[] = [];
    bus.on("subagent:async-complete", (raw) => payloads.push(raw as Record<string, unknown>));
    const fake = createFakeSubagents([
      {
        delivery: "manual",
        executeSettlement: async (script, handle) => {
          assert.equal(Object.isFrozen(handle), true);
          assert.equal(waveScriptItems(script).length, 2);
          return {
            ...fixture,
            completion: {
              ...fixture.completion,
              id: "foreign",
              runId: "foreign",
              asyncDir: "/foreign",
            },
          };
        },
      },
    ]);
    fake.attach(bus);
    const wave = createReportWave(bus);
    const start = await wave.start(makeSpec());
    assert.ok(start.ok);
    const status = JSON.parse(readFileSync(join(start.asyncDir, "status.json"), "utf8"));
    assert.equal(status.runId, start.runId);
    assert.equal(status.mode, "workflow");
    if (value === undefined) assert.equal("workflow" in status, false);
    else assert.deepEqual(status.workflow.value, value);
    assert.equal(payloads.length, 0, "manual mode does not auto-deliver");
    fake.complete(0);
    assert.equal(payloads[0]?.id, start.runId);
    assert.equal(payloads[0]?.runId, start.runId);
    assert.equal(payloads[0]?.asyncDir, start.asyncDir);
    const collected = await wave.collect(start.ref);
    assert.equal(collected.kind, "settled");
    if (collected.kind !== "settled") return;
    assert.equal(collected.result.complete, false);
    assert.deepEqual(
      collected.result.reports,
      Array.isArray(value)
        ? value.map(({ key, report }) => ({ key, report }))
        : [{ key: "plan-fidelity", report: { verdict: "clean" } }],
    );
    assert.equal(collected.result.receipt.runId, start.runId);
    assert.equal(fake.stops.length, 0);
    rmSync(start.asyncDir, { recursive: true, force: true });
  });
}

test("report-bearing pre-reply events select only the first match, before the status write", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([
    {
      executeSettlement: async (_script, handle) => {
        const event = (owner: string) =>
          partialFixture(undefined, [
            { workflowKey: "plan-fidelity", success: true, structuredOutput: { owner } },
          ]).completion;
        fake.emit({ ...event("foreign"), id: "foreign" });
        fake.emit({ ...event("first"), id: handle.asyncId });
        fake.emit({ ...event("duplicate"), id: handle.asyncId });
        return partialFixture();
      },
      delivery: "manual",
    },
  ]);
  fake.attach(bus);
  const wave = createReportWave(bus);
  const start = await wave.start(makeSpec());
  assert.ok(start.ok);
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  assert.deepEqual(collected.result.reports, [
    { key: "plan-fidelity", report: { owner: "first" } },
  ]);
  assert.equal(fake.stops.length, 0);
});

test("fake legacy evaluator still receives one argument, supersedes value, and repeats the last plan", async () => {
  const bus = createFakeBus();
  let calls = 0;
  const fake = createFakeSubagents([
    {
      value: ["ignored"],
      executeScript: async (...args) => {
        assert.equal(args.length, 1);
        calls++;
        return DERIVE_REPORTS(args[0]);
      },
    },
  ]);
  fake.attach(bus);
  const wave = createReportWave(bus);
  for (let i = 0; i < 2; i++) assert.equal((await wave.run(makeSpec())).complete, true);
  assert.equal(calls, 2);
});

test("fake rejects mixed settlement plans at construction, including own undefined value", () => {
  for (const fields of [{ value: undefined }, { value: [] }, { executeScript: DERIVE_REPORTS }]) {
    // Deliberately bypass static optional-never exclusions to test the runtime boundary.
    const mixed = { ...fields, executeSettlement: async () => partialFixture() } as FakeSpawnPlan;
    assert.throws(() => createFakeSubagents([mixed]), /cannot mix/);
  }
  // @ts-expect-error The two fixture modes cannot be combined.
  const mixed: FakeSpawnPlan = { value: [], executeSettlement: async () => partialFixture() };
  assert.ok(mixed);
});

for (const mode of ["executeScript", "executeSettlement", "write-preparation"] as const) {
  test(`fake ${mode} rejection produces exactly one failed reply, no completion`, async () => {
    const bus = createFakeBus();
    const replies: unknown[] = [];
    const completions: unknown[] = [];
    bus.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
      const request = raw as { method: string; requestId: string };
      if (request.method === "spawn")
        bus.on(`${WAVE_RPC_REPLY_EVENT_PREFIX}${request.requestId}`, (reply) =>
          replies.push(reply),
        );
    });
    bus.on("subagent:async-complete", (data) => completions.push(data));
    const reject = async (): Promise<never> => {
      throw new Error("fixture assertion failed");
    };
    const cyclic: unknown[] = [];
    cyclic.push(cyclic);
    const fake = createFakeSubagents([
      mode === "write-preparation"
        ? { executeSettlement: async () => partialFixture(cyclic) }
        : { [mode]: reject },
    ]);
    fake.attach(bus);
    const start = await createReportWave(bus).start(makeSpec());
    assert.equal(start.ok, false);
    if (start.ok) return;
    assert.equal(start.result.failures[0]?.reason, "spawn-failed");
    assert.match(
      start.result.failures[0]?.detail ?? "",
      mode === "write-preparation"
        ? /fake_settlement_failed:.*circular/i
        : /fake_settlement_failed: fixture assertion failed/,
    );
    assert.equal(replies.length, 1);
    assert.deepEqual(completions, []);
    assert.throws(() => fake.complete(0), /has not launched/);
  });
}

test("overlapping partial waves ignore foreign/duplicate reports and collect after source removal", async (t) => {
  const bus = createFakeBus();
  const active = new Set<unknown>();
  const methods: unknown[] = [];
  const sourcePayloads: Record<string, unknown>[] = [];
  bus.on("subagent:async-complete", (raw) => sourcePayloads.push(raw as Record<string, unknown>));
  const tracked: WaveBus = {
    emit: (channel, data) => bus.emit(channel, data),
    on(channel, handler) {
      const off = bus.on(channel, handler);
      if (channel === "subagent:async-complete") active.add(handler);
      return () => {
        active.delete(handler);
        off();
      };
    },
  };
  bus.on(WAVE_RPC_REQUEST_EVENT, (raw) => methods.push((raw as { method: string }).method));
  const fixtures = ["A", "B"].map((owner) =>
    partialFixture(undefined, [
      {
        workflowKey: "plan-fidelity",
        runId: `child-${owner}`,
        success: true,
        structuredOutput: { owner },
      },
    ]),
  );
  const fake = createFakeSubagents(
    fixtures.map((fixture) => ({ delivery: "manual", executeSettlement: async () => fixture })),
  );
  fake.attach(bus);
  const wave = createReportWave(tracked);
  const a = await wave.start(makeSpec());
  const b = await wave.start(makeSpec());
  assert.ok(a.ok && b.ok);
  t.after(() => {
    for (const run of [a, b]) rmSync(run.asyncDir, { recursive: true, force: true });
  });
  assert.equal(active.size, 2);
  fake.emit({ ...partialFixture().completion, id: "foreign", asyncDir: "/foreign" });
  assert.equal(active.size, 2);
  fake.complete(1);
  fake.emit({ ...partialFixture().completion, id: b.runId }); // cannot replace first matching data
  const collectedB = await wave.collect(b.ref);
  assert.equal(collectedB.kind, "settled");
  if (collectedB.kind !== "settled") return;
  assert.deepEqual(collectedB.result.reports, [{ key: "plan-fidelity", report: { owner: "B" } }]);
  assert.equal(collectedB.result.receipt.runId, b.runId);
  assert.equal(active.size, 1);
  fake.complete(0);
  // A macrotask barrier lets the normalized promise settle; collection is deliberately later.
  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.equal(active.size, 0);
  for (const fixture of fixtures) {
    delete fixture.completion.results;
    fixture.aggregate.value = undefined;
  }
  // These are the actual raw objects held by the fake for manual delivery, not just the
  // callback's original fixtures. Removing their results leaves only the normalized promise.
  for (const payload of sourcePayloads) delete payload.results;
  rmSync(join(a.asyncDir, "status.json"));
  fake.complete(0);
  const collectedA = await wave.collect(a.ref);
  assert.equal(collectedA.kind, "settled");
  if (collectedA.kind !== "settled") return;
  assert.deepEqual(collectedA.result.reports, [{ key: "plan-fidelity", report: { owner: "A" } }]);
  assert.equal(collectedA.result.receipt.runId, a.runId);
  assert.deepEqual(await wave.collect(a.ref), { kind: "none" });
  assert.deepEqual(methods, ["ping", "spawn", "ping", "spawn"]);
});

for (const results of [
  undefined,
  null,
  [],
  [{ agent: "plan-fidelity", success: true, structuredOutput: {} }],
]) {
  test(`partial RPC without usable keyed results stays incomplete (${JSON.stringify(results)})`, async () => {
    const bus = createFakeBus();
    const fixture = partialFixture();
    fixture.completion.results = results;
    const fake = createFakeSubagents([{ executeSettlement: async () => fixture }]);
    fake.attach(bus);
    const result = await createReportWave(bus).run(makeSpec());
    assert.deepEqual(result.reports, []);
    assert.deepEqual(
      result.failures.map((failure) => failure.reason),
      ["run-failed", "missing-lane", "missing-lane"],
    );
  });
}

test("partial event never bypasses a missing or malformed durable aggregate", async () => {
  for (const content of [undefined, "{bad", JSON.stringify({ workflow: { value: [] } })]) {
    const bus = createFakeBus();
    const fake = createFakeSubagents([
      { delivery: "manual", executeSettlement: async () => partialFixture() },
    ]);
    fake.attach(bus);
    const wave = createReportWave(bus);
    const start = await wave.start(makeSpec());
    assert.ok(start.ok);
    const path = join(start.asyncDir, "status.json");
    if (content === undefined) rmSync(path);
    else writeFileSync(path, content);
    fake.complete(0);
    const collected = await wave.collect(start.ref);
    assert.equal(collected.kind, "settled");
    if (collected.kind !== "settled") return;
    assert.deepEqual(collected.result.reports, []);
    assert.equal(collected.result.failures[0]?.reason, "aggregate-unreadable");
  }
});

function assertCompletionStorageLifetime(source: string): void {
  assert.equal((source.match(/buffered\.push\(/g) ?? []).length, 1);
  assert.match(source, /if \(handle === null\) \{\s*buffered\.push\(completion\);\s*return;\s*\}/);
  assert.match(source, /matched = buffered\.find\(matchesHandle\);\s*buffered\.length = 0;/);
  assert.match(source, /if \(!accepting\) return;/);
  assert.match(source, /if \(!matchesHandle\(completion\) \|\| matched !== undefined\) return;/);
  assert.match(
    source,
    /finally \{\s*accepting = false;\s*unsubscribe\(\);\s*buffered\.length = 0;\s*matched = undefined;\s*notifyMatch = null;/,
  );
  assert.match(
    source,
    /catch \(error\) \{\s*accepting = false;\s*unsubscribe\(\);\s*buffered\.length = 0;\s*matched = undefined;\s*notifyMatch = null;/,
  );
}

test("completion storage is pre-reply-only and releases held references (non-vacuous source pin)", () => {
  // Output assertions cannot prove release of foreign report references; pin the storage sites,
  // not GC timing or heap thresholds. Mutation controls prove both lifetime checks are live.
  const source = readFileSync(new URL("./transport.ts", import.meta.url), "utf8");
  assertCompletionStorageLifetime(source);
  const unguarded = source.replace("if (handle === null) {", "if (true) {");
  assert.notEqual(unguarded, source);
  assert.throws(() => assertCompletionStorageLifetime(unguarded));
  const undrained = source.replace(
    "matched = buffered.find(matchesHandle);\n    buffered.length = 0;",
    "matched = buffered.find(matchesHandle);",
  );
  assert.notEqual(undrained, source);
  assert.throws(() => assertCompletionStorageLifetime(undrained));
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
