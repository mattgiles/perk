// The wave-over-real-RPC-adapter integration suite: the PRODUCTION `createReportWave` factory
// driven on a bare fake bus, answered by the shared `createFakeSubagents` responder — proving,
// at the offline tier, the behaviors the memory adapter can only simulate: the real spawn (v1
// envelope + the fixed spawn contract), completion CORRELATION (a foreign completion on the
// advertised channel is ignored; the matching identity settles — including pi-subagents 0.76.1's
// per-child AWAITED-CHILD events on the same channel, before the spawn reply and while siblings
// run), the STOP REQUEST on timeout/cancel (the recorded stop names the spawned run, the
// engine's answer — acknowledged or refused — and ONE terminal-proof `status` read ride the
// detail and the receipt), the durable AGGREGATE (a real temp
// `status.json` read through the adapter), native PARTIAL settlement (the explicit
// `terminalOutcome` carrier retains the engine-validated sibling report while the wave stays
// incomplete), and PER-LAUNCH ADAPTER FRESHNESS (two overlapping waves each ping+subscribe
// independently; out-of-order completions correlate to the right refs). The live pi-subagents
// leg remains the phase dogfood's.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import {
  attachGhostResponder,
  createFakeSubagents,
  type FakeSettlement,
  noLiveRunController,
  waveScriptItems,
} from "../testing/fakeSubagents.ts";
import { createReportWave, type ReportWaveRequest, type WaveNotice } from "./reportWave.ts";
import { createRpcWaveAdapter } from "./rpcAdapter.ts";
import {
  WAVE_ACCEPTANCE,
  WAVE_INTERCOM_BRIDGE,
  WAVE_SETTLEMENT_GRACE_MS,
  type WaveBus,
  type WaveRunHandle,
  type WaveSpawnParams,
} from "./transport.ts";

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

/**
 * Drain the ping/spawn RPC round trips (microtasks + the fake's async preparation) under mocked
 * `setTimeout` so the runner's expiry timer is armed before a test ticks it (`setImmediate` is
 * never mocked).
 */
async function drain(): Promise<void> {
  await new Promise((resolve) => setImmediate(resolve));
}

/**
 * pi-subagents 0.76.1's awaited-child completion, exactly as
 * `subagent-executor.js::emitWorkflowAwaitedChildComplete` emits it on the async-complete channel
 * while the workflow is still running: the CHILD's own run id and run directory (a sibling of the
 * workflow's under the async root — a path string only, never created; the transport compares
 * identities and never reads it), plus the lineage fields perk never reads.
 */
function awaitedChildEvent(
  handle: Readonly<WaveRunHandle>,
  child: { key: string; state: "complete" | "failed" | "stopped"; agent?: string },
): Record<string, unknown> {
  const childId = `${handle.asyncId}-child-${child.key}`;
  return {
    id: childId,
    runId: childId,
    sessionId: "session-1",
    completionOwnerId: "owner-1",
    asyncDir: join(dirname(handle.asyncDir), childId),
    agent: child.agent ?? "perk.pr-reviewer",
    mode: "single",
    state: child.state,
    success: child.state === "complete",
    timestamp: 1,
    triggerTurn: false,
    awaitedByWorkflow: true,
    parentWorkflowRunId: handle.asyncId,
  };
}

/** Collect under a tiny collect grace: `running` proves the ref is still pending. */
async function collectRunning(
  wave: ReturnType<typeof createReportWave>,
  ref: Parameters<ReturnType<typeof createReportWave>["collect"]>[0],
): Promise<void> {
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "30";
  try {
    assert.deepEqual(await wave.collect(ref), { kind: "running" });
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }
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
    script?: string;
    async?: boolean;
    mission?: boolean;
    context?: string;
    acceptance?: unknown;
    intercomBridge?: unknown;
    outputSchema?: unknown;
    model?: string;
    timeoutMs?: number;
  };
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.deepEqual(spawn.acceptance, WAVE_ACCEPTANCE);
  assert.deepEqual(spawn.intercomBridge, WAVE_INTERCOM_BRIDGE);
  assert.deepEqual(spawn.outputSchema, spec.outputSchema);
  assert.equal(spawn.model, "anthropic/claude-sonnet-4");
  assert.equal(spawn.timeoutMs, 5_000);
  assert.deepEqual(
    waveScriptItems(String(spawn.script ?? "")).map(({ key }) => key),
    ["plan-fidelity", "correctness"],
  );

  for (const item of waveScriptItems(String(spawn.script))) {
    assert.deepEqual(item.extensionBindings, { "perk.parent-restrictions/1": { readOnly: true } });
    assert.equal(item.worktree, false);
  }

  // The wire key is pi-subagents' current RPC `script`; the removed `workflowScript` key is
  // absent outright (the engine rejects even an `undefined`-valued one via `Object.hasOwn`).
  assert.equal(Object.hasOwn(fake.spawns[0] ?? {}, "workflowScript"), false);
  assert.equal(typeof fake.spawns[0]?.script, "string");
  assert.ok(String(fake.spawns[0]?.script).startsWith("const reports = await runs.all("));

  // The aggregate was read from the run's REAL temp status.json through the adapter.
  assert.equal(result.complete, true);
  assert.deepEqual(result.reports, [
    { key: "plan-fidelity", report: { angle: "plan-fidelity", verdict: "clean" } },
    { key: "correctness", report: { angle: "correctness", verdict: "clean" } },
  ]);
  assert.deepEqual(result.failures, []);
  assert.equal(result.receipt.state, "complete");
});

/** A valid spawn body for the hand-built rejection cases (the producer never builds these). */
const VALID_SPAWN: WaveSpawnParams = {
  script: "return [];",
  async: true,
  mission: false,
  context: "fresh",
  acceptance: WAVE_ACCEPTANCE,
  intercomBridge: WAVE_INTERCOM_BRIDGE,
  args: { launch: "rpc-fixture-launch" },
  outputSchema: { type: "object" },
  timeoutMs: 5_000,
};

const { script: _validScript, ...SPAWN_WITHOUT_SCRIPT } = VALID_SPAWN;

const WORKFLOW_SCRIPT_REJECTION =
  "invalid_params: RPC spawn workflowScript was removed; pass inline script text as script.";
const WORKFLOW_SCRIPT_PATH_REJECTION =
  'invalid_params: RPC spawn workflowScriptPath was removed; pass the file as workflow: "./path/to/script.js".';

for (const [label, legacy, removedKey, expected] of [
  [
    "a workflowScript key in place of script",
    { ...SPAWN_WITHOUT_SCRIPT, workflowScript: "return [];" },
    "workflowScript",
    WORKFLOW_SCRIPT_REJECTION,
  ],
  [
    "an undefined-valued workflowScript key beside a valid script",
    { ...VALID_SPAWN, workflowScript: undefined },
    "workflowScript",
    WORKFLOW_SCRIPT_REJECTION,
  ],
  [
    "a workflowScriptPath key beside a valid script",
    { ...VALID_SPAWN, workflowScriptPath: "./wave.js" },
    "workflowScriptPath",
    WORKFLOW_SCRIPT_PATH_REJECTION,
  ],
  [
    "an undefined-valued workflowScriptPath key beside a valid script",
    { ...VALID_SPAWN, workflowScriptPath: undefined },
    "workflowScriptPath",
    WORKFLOW_SCRIPT_PATH_REJECTION,
  ],
] as const) {
  test(`rpc spawn: ${label} is rejected invalid_params and surfaced verbatim`, async () => {
    // The shape a reverted producer hits offline: the fake mirrors pi-subagents 0.76.1's
    // `Object.hasOwn` rejections and the real adapter surfaces `code: message` untouched.
    const bus = createFakeBus();
    const fake = createFakeSubagents();
    fake.attach(bus);
    const adapter = createRpcWaveAdapter(bus);
    // Deliberately off-contract: `WaveSpawnParams` has neither removed field.
    const params = legacy as unknown as WaveSpawnParams;
    await assert.rejects(adapter.spawn(params), (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(error.message, expected);
      return true;
    });
    assert.equal(fake.spawns.length, 1);
    assert.equal(Object.hasOwn(fake.spawns[0] ?? {}, removedKey), true);
  });
}

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

test("rpc integration: timeout — stop acknowledged, then exactly ONE status query; both diagnoses render and ride the receipt", async (t) => {
  // `delivery: "never"` schedules no completion timer; the RPC reply timers are cleared on settle.
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = createFakeBus();
  const fake = createFakeSubagents([
    { delivery: "never", executeSettlement: async () => partialFixture() },
  ]);
  fake.attach(bus);
  const pending = createReportWave(bus).run(makeSpec({ timeoutMs: 30 }));
  await drain();
  t.mock.timers.tick(30 + WAVE_SETTLEMENT_GRACE_MS);
  const result = await pending;
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "timeout"]],
  );
  assert.match(
    result.failures[0]?.detail ?? "",
    /; stop requested; child termination unconfirmed \(pending: Workflow dispatch is still open\.\)$/,
  );
  assert.equal(result.receipt.state, "timed-out");
  assert.deepEqual(result.receipt.termination, {
    stop: { acknowledged: true },
    proof: { state: "pending", reason: "Workflow dispatch is still open." },
  });
  assert.deepEqual(
    result.reports,
    [],
    "an undelivered native partial payload is not recovery authority",
  );
  const runId = result.receipt.runId;
  assert.deepEqual(fake.stops, [{ id: runId }], "the stop request names the spawned run");
  assert.deepEqual(fake.statuses, [{ id: runId }], "exactly one status query, after the stop");
});

for (const [label, plan, expected] of [
  [
    "an observed proof renders as observed",
    { terminalProof: { state: "observed", dispatchClosed: true, observedAt: 7, children: [] } },
    "; stop requested; child termination observed (engine process-terminal proof)",
  ],
  [
    "a status miss renders unavailable with the engine's text",
    { statusReply: "error" },
    "; stop requested; child termination unconfirmed (unavailable: execution_failed: Async run not found. Provide id or dir.)",
  ],
  [
    "an unknown proof keeps the engine's reason",
    {
      terminalProof: {
        state: "unknown",
        dispatchClosed: true,
        reason: "async workflow child correctness process-terminal proof is missing",
      },
    },
    "; stop requested; child termination unconfirmed (unknown: async workflow child correctness process-terminal proof is missing)",
  ],
] as const) {
  test(`rpc integration: timeout — ${label}`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const bus = createFakeBus();
    const fake = createFakeSubagents([{ delivery: "never", ...plan }]);
    fake.attach(bus);
    const pending = createReportWave(bus).run(makeSpec({ timeoutMs: 30 }));
    await drain();
    t.mock.timers.tick(30 + WAVE_SETTLEMENT_GRACE_MS);
    const result = await pending;
    const detail = result.failures[0]?.detail ?? "";
    assert.ok(detail.endsWith(expected), detail);
    assert.equal(fake.stops.length, 1);
    assert.equal(fake.statuses.length, 1);
  });
}

test("rpc integration: timeout — a REFUSED stop (invalid_state) with a successful status keeps both diagnoses", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ delivery: "never", stopReply: noLiveRunController }]);
  fake.attach(bus);
  const pending = createReportWave(bus).run(makeSpec({ timeoutMs: 30 }));
  await drain();
  t.mock.timers.tick(30 + WAVE_SETTLEMENT_GRACE_MS);
  const result = await pending;
  const runId = result.receipt.runId ?? "";
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "timeout"]],
    "a refused stop never rejects the wave nor changes the reason literal",
  );
  assert.match(
    result.failures[0]?.detail ?? "",
    /; stop refused \(invalid_state: Workflow .* has no live run controller available to stop\.\); child termination unconfirmed \(pending: Workflow dispatch is still open\.\)$/,
  );
  assert.deepEqual(result.receipt.termination, {
    stop: {
      acknowledged: false,
      reason: `invalid_state: Workflow ${runId} has no live run controller available to stop.`,
    },
    proof: { state: "pending", reason: "Workflow dispatch is still open." },
  });
  assert.deepEqual(fake.stops, [{ id: runId }]);
  assert.deepEqual(fake.statuses, [{ id: runId }]);
});

test("rpc integration: cancel after launch — the same stop request + one-shot proof", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ delivery: "never" }]);
  fake.attach(bus);
  const controller = new AbortController();
  const wave = createReportWave(bus);
  const start = await wave.start(makeSpec(), { signal: controller.signal });
  assert.ok(start.ok);
  controller.abort();
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  const result = collected.result;
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason, f.detail]),
    [
      [
        null,
        "cancelled",
        "wave 'pr-review' was cancelled; stop requested; child termination unconfirmed (pending: Workflow dispatch is still open.)",
      ],
    ],
  );
  assert.equal(result.receipt.state, "cancelled");
  assert.deepEqual(result.receipt.termination, {
    stop: { acknowledged: true },
    proof: { state: "pending", reason: "Workflow dispatch is still open." },
  });
  assert.deepEqual(fake.stops, [{ id: start.runId }]);
  assert.deepEqual(fake.statuses, [{ id: start.runId }]);
});

test("rpc integration: the complete arm issues NO stop and NO status query", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS }]);
  fake.attach(bus);
  const result = await createReportWave(bus).run(makeSpec());
  assert.equal(result.complete, true);
  assert.equal("termination" in result.receipt, false);
  assert.deepEqual(fake.stops, []);
  assert.deepEqual(fake.statuses, []);
});

test("rpc integration: a stopped workflow completion (state stopped, no terminalOutcome) is run-failed with no retained reports and no perk stop/status", async () => {
  // The engine settled (e.g. its RPC stop aborted the workflow controller): perk did not stop
  // anything, so it requests no stop and reads no terminal proof.
  const bus = createFakeBus();
  const fake = createFakeSubagents([
    {
      executeSettlement: async () => ({
        aggregate: { state: "stopped", error: "Workflow stopped by RPC.", value: undefined },
        completion: { state: "stopped", success: false },
      }),
    },
  ]);
  fake.attach(bus);
  const result = await createReportWave(bus).run(makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, []);
  assert.deepEqual(
    result.failures.filter((f) => f.key === null).map((f) => [f.reason, f.detail]),
    [["run-failed", "wave run ended 'stopped': Workflow stopped by RPC."]],
  );
  assert.equal(result.receipt.state, "failed");
  assert.equal("termination" in result.receipt, false);
  assert.deepEqual(fake.stops, []);
  assert.deepEqual(fake.statuses, []);
});

// --- the awaited-child completion events (pi-subagents 0.76.1) ---------------------------------

test("rpc integration: an awaited-child event BEFORE the spawn reply is buffered then discarded; the root completion settles", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([
    {
      delivery: "manual",
      executeSettlement: async (script, handle) => {
        // Emitted while the spawn reply is still unsent: the runner holds no handle yet.
        fake.emit(awaitedChildEvent(handle, { key: "plan-fidelity", state: "complete" }));
        return {
          aggregate: { state: "complete", value: await DERIVE_REPORTS(script) },
          completion: {
            state: "complete",
            success: true,
            results: [
              { runId: "root-child-a", success: true },
              { runId: "root-child-b", success: true },
            ],
            workflowChildren: {
              version: 1,
              workflowRunId: handle.asyncId,
              children: [
                { childId: "plan-fidelity", runId: "root-child-a" },
                { childId: "correctness", runId: "root-child-b" },
              ],
            },
          },
        };
      },
    },
  ]);
  fake.attach(bus);
  const wave = createReportWave(bus);
  const start = await wave.start(makeSpec());
  assert.ok(start.ok);
  if (!start.ok) return;
  await collectRunning(wave, start.ref);

  fake.complete(0);
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  assert.equal(collected.result.complete, true);
  assert.deepEqual(
    collected.result.reports.map((r) => r.key),
    ["plan-fidelity", "correctness"],
  );
  // Receipt children come from the ROOT completion only — never the early child event.
  assert.deepEqual(collected.result.receipt.children, [
    { key: "plan-fidelity", runId: "root-child-a", success: true, agent: "perk.pr-reviewer" },
    { key: "correctness", runId: "root-child-b", success: true, agent: "perk.pr-reviewer" },
  ]);
  assert.equal(collected.result.receipt.runId, start.runId);
  assert.doesNotMatch(JSON.stringify(collected.result.receipt), /-child-plan-fidelity/);
  assert.deepEqual(fake.stops, []);
});

test("rpc integration: awaited-child events WHILE siblings remain active never settle — completed, failed and stopped children are ignored until the root completion", async () => {
  const bus = createFakeBus();
  const failedError = "child exited with code 1";
  const stoppedError = "Workflow child 'tests' stopped.";
  const fake = createFakeSubagents([
    {
      delivery: "manual",
      executeSettlement: async (_script, handle) => ({
        aggregate: {
          state: "complete",
          value: [
            { key: "plan-fidelity", ok: true, error: null, report: { verdict: "clean" } },
            { key: "correctness", ok: false, error: failedError, report: null },
            { key: "tests", ok: false, error: stoppedError, report: null },
          ],
        },
        completion: {
          state: "complete",
          success: true,
          results: [
            { runId: "root-a", success: true },
            { runId: "root-b", success: false },
            { runId: "root-c", success: false },
          ],
          workflowChildren: {
            version: 1,
            workflowRunId: handle.asyncId,
            children: [
              { childId: "plan-fidelity", runId: "root-a" },
              { childId: "correctness", runId: "root-b" },
              { childId: "tests", runId: "root-c" },
            ],
          },
        },
      }),
    },
  ]);
  fake.attach(bus);
  const wave = createReportWave(bus);
  const start = await wave.start(
    makeSpec({
      assignments: [
        { key: "plan-fidelity", agent: "perk.pr-reviewer", task: "review plan fidelity" },
        { key: "correctness", agent: "perk.pr-reviewer", task: "review correctness" },
        { key: "tests", agent: "perk.pr-reviewer", task: "review tests" },
      ],
    }),
  );
  assert.ok(start.ok);
  if (!start.ok) return;
  const handle = { asyncId: start.runId, asyncDir: start.asyncDir };
  for (const [key, state] of [
    ["plan-fidelity", "complete"],
    ["correctness", "failed"],
    ["tests", "stopped"],
  ] as const) {
    fake.emit(awaitedChildEvent(handle, { key, state }));
    await drain();
    await collectRunning(wave, start.ref);
  }

  // The positive arm: the root completion alone settles, with the aggregate as authority.
  fake.complete(0);
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  const result = collected.result;
  assert.equal(result.complete, false, "strict completeness over two failed lanes");
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(result.failures, [
    { key: "correctness", reason: "lane-failed", detail: failedError },
    { key: "tests", reason: "lane-failed", detail: stoppedError },
  ]);
  assert.deepEqual(
    result.receipt.children.map((child) => [child.key, child.runId, child.success]),
    [
      ["plan-fidelity", "root-a", true],
      ["correctness", "root-b", false],
      ["tests", "root-c", false],
    ],
  );
  assert.deepEqual(fake.stops, []);
  assert.deepEqual(fake.statuses, []);
});

test("rpc integration: a hostile awaited-child event copying the workflow's id as runId/parentWorkflowRunId but carrying its own identity never matches", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS, delivery: "manual" }]);
  fake.attach(bus);
  const wave = createReportWave(bus);
  const start = await wave.start(makeSpec());
  assert.ok(start.ok);
  if (!start.ok) return;
  const handle = { asyncId: start.runId, asyncDir: start.asyncDir };
  fake.emit({
    ...awaitedChildEvent(handle, { key: "plan-fidelity", state: "failed" }),
    runId: start.runId,
    parentWorkflowRunId: start.runId,
    results: [{ agent: "plan-fidelity", runId: "hostile", success: false }],
  });
  await collectRunning(wave, start.ref);

  fake.complete(0);
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  assert.equal(collected.result.complete, true);
  assert.equal(collected.result.reports.length, 2);
  assert.deepEqual(collected.result.receipt.children, []);
});

test("rpc integration: a ghost responder on the timeout arm — spawn, stop and status each resolve past a held reply, one notice per held request", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = createFakeBus();
  attachGhostResponder(bus);
  const fake = createFakeSubagents([{ delivery: "never" }]);
  fake.attach(bus);
  const notices: WaveNotice[] = [];
  const pending = createReportWave(bus, { onNotice: (notice) => notices.push(notice) }).run(
    makeSpec({ timeoutMs: 30 }),
  );
  await drain();
  t.mock.timers.tick(30 + WAVE_SETTLEMENT_GRACE_MS);
  const result = await pending;
  assert.deepEqual(result.receipt.termination, {
    stop: { acknowledged: true },
    proof: { state: "pending", reason: "Workflow dispatch is still open." },
  });
  const superseded = "no_active_session: No active extension context for subagent RPC.";
  assert.deepEqual(notices, [
    { method: "spawn", superseded },
    { method: "stop", superseded },
    { method: "status", superseded },
  ]);
  assert.equal(fake.stops.length, 1);
  assert.equal(fake.statuses.length, 1);
});

test("source pin: the wave modules never read the awaited-child lineage, capacity, partial-marker or reuse fields; the terminal proof is narrowed in rpcAdapter.ts only; transport.ts alone mints the launch token", () => {
  const adapter = readFileSync(new URL("./rpcAdapter.ts", import.meta.url), "utf8");
  const transport = readFileSync(new URL("./transport.ts", import.meta.url), "utf8");
  const logical = readFileSync(new URL("./reportWave.ts", import.meta.url), "utf8");
  // `ok` (the engine's `success`) is the sole status fact; reuse evidence is never consulted
  // because the launch token makes every launch fresh.
  const forbidden =
    /\b(awaitedByWorkflow|parentWorkflowRunId|triggerTurn|capacity|abandonedSlot\w*|slotReleased|outputPartial|timedOut|reused|reusedFrom|stopCause)\b/;
  assert.doesNotMatch(adapter, forbidden);
  assert.doesNotMatch(transport, forbidden);
  assert.doesNotMatch(logical, forbidden);
  // The positive arm: the one field perk does read after a stop, at the adapter only.
  assert.match(adapter, /\.workflowTerminalProof\b/);
  assert.doesNotMatch(transport, /workflowTerminalProof/);
  // The launch token is a transport invariant: minted at the one spawn site; the adapter
  // forwards the params verbatim and the logical tier never builds or reads `args` (its
  // `launch:` keys are the preflight manifest, a different thing).
  assert.match(transport, /args: \{ launch: randomUUID\(\) \}/);
  assert.doesNotMatch(adapter, /\bargs\b/);
  assert.doesNotMatch(logical, /\bargs\b/);
});

test("rpc integration: a native partial delivered inside the settlement grace is retained through the real adapter", async (t) => {
  // The engine's deadline (the spawned `timeoutMs`) has passed when the completion lands; perk's
  // own timer (deadline + grace) has not fired, so the real RPC decoder, the transport's durable
  // read and the normalizer all consume the completion carrier instead of an empty timeout.
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = createFakeBus();
  const fake = createFakeSubagents([
    { delivery: "manual", executeSettlement: async () => partialFixture() },
  ]);
  fake.attach(bus);
  const pending = createReportWave(bus).run(makeSpec({ timeoutMs: 30 }));
  await drain();
  assert.equal(fake.spawns[0]?.timeoutMs, 30, "the spawned engine deadline excludes the grace");
  t.mock.timers.tick(31);
  fake.complete(0);
  const result = await pending;
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
  assert.equal(fake.stops.length, 0);
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
    /waveOver\(\s*\(\)\s*=>\s*createRpcWaveAdapter\(bus\b/,
    "the one construction call must sit inside the per-launch supplier arrow",
  );
});

// --- the duplicate-responder notice (the context-less hold end to end) -------------------------

test("rpc integration: a ghost context-less responder beside the live one — the run completes and onNotice fires once per launch", async () => {
  const bus = createFakeBus();
  attachGhostResponder(bus); // answers first, synchronously, with no_active_session
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS }]);
  fake.attach(bus); // the live responder replies after its async preparation
  const notices: WaveNotice[] = [];
  const wave = createReportWave(bus, { onNotice: (notice) => notices.push(notice) });

  const first = await wave.run(makeSpec());
  assert.equal(first.complete, true);
  assert.deepEqual(
    first.reports.map((r) => r.key),
    ["plan-fidelity", "correctness"],
  );
  assert.deepEqual(first.failures, []);
  assert.equal(first.receipt.state, "complete");
  assert.equal(fake.spawns.length, 1, "exactly one spawn reached the live responder");
  assert.deepEqual(notices, [
    {
      method: "spawn",
      superseded: "no_active_session: No active extension context for subagent RPC.",
    },
  ]);

  const second = await wave.run(makeSpec());
  assert.equal(second.complete, true);
  assert.equal(notices.length, 2, "one notice per launch — the reporter, not the wave, latches");
  assert.equal(fake.stops.length, 0);
});

test("rpc integration: without a ghost, onNotice is never called; without deps, behavior is unchanged", async () => {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ executeScript: DERIVE_REPORTS }]);
  fake.attach(bus);
  const notices: WaveNotice[] = [];
  const observed = await createReportWave(bus, { onNotice: (n) => notices.push(n) }).run(
    makeSpec(),
  );
  assert.equal(observed.complete, true);
  assert.deepEqual(notices, []);

  attachGhostResponder(bus);
  const bare = await createReportWave(bus).run(makeSpec());
  assert.equal(bare.complete, true);
  assert.deepEqual(
    bare.reports.map((r) => r.key),
    ["plan-fidelity", "correctness"],
  );
  assert.equal(fake.spawns.length, 2);
});

/** A native partial settlement: the durable aggregate failed without a `workflow.value`; the
 * completion event carries the explicit `terminalOutcome` plus one validated sibling report. */
/**
 * A native partial settlement retaining one valid sibling report. `timedOutLane` adds the
 * second lane as the engine's single-run partial shape \u2014 `success: false` beside the
 * `timedOut`/`outputPartial` markers, the partial-output text, a per-row `terminalOutcome`, AND a
 * schema-valid `structuredOutput` \u2014 which perk must still count as a failed lane.
 */
function partialFixture(opts: { timedOutLane?: boolean } = {}): FakeSettlement {
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
        ...(opts.timedOutLane === true
          ? [
              {
                workflowKey: "correctness",
                runId: "child-b",
                success: false,
                timedOut: true,
                outputPartial: true,
                error: "Subagent timed out.",
                output: 'Subagent timed out.\n\nPartial output before timeout:\n{"verdict":',
                structuredOutput: { verdict: "clean" },
                terminalOutcome: { state: "partial", reason: "timeout" },
              },
            ]
          : []),
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

test("rpc integration: a partial-marked lane with a retained schema-valid report is lane-failed, never covered", async () => {
  // `ok` (the engine's `success`) is the sole status fact: the `outputPartial`/`timedOut`
  // markers are never read, and a retained report on a failed row is never promoted.
  const bus = createFakeBus();
  const fake = createFakeSubagents([
    { executeSettlement: async () => partialFixture({ timedOutLane: true }) },
  ]);
  fake.attach(bus);
  const result = await createReportWave(bus).run(makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(
    result.failures.map(({ key, reason, detail }) => [key, reason, detail]),
    [
      [null, "run-failed", result.failures[0]?.detail],
      ["correctness", "lane-failed", "Subagent timed out."],
    ],
  );
  assert.match(result.failures[0]?.detail ?? "", /native partial: timeout/);
  assert.equal(result.receipt.state, "failed");
  assert.doesNotMatch(JSON.stringify(result.receipt), /verdict|structuredOutput|Partial output/);
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
