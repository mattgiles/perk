// The shared `WaveAdapter` contract suite: one set of behavioral assertions registered against
// BOTH adapters — the in-memory test double directly, and the production RPC adapter wired to a
// fake in-memory bus plus the shared fake pi-subagents responder (`createFakeSubagents` — the one
// mirror of the v1 envelope in pi-subagents `src/extension/rpc.ts`; `readAggregate` reads a real
// `status.json` written to a temp dir). Keeping the double and the production adapter behaviorally aligned is what makes
// the runner's memory-adapter coverage trustworthy.

import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { createFakeSubagents } from "../testing/fakeSubagents.ts";
import { createMemoryWaveAdapter } from "../testing/memoryAdapter.ts";
import { createRpcWaveAdapter } from "./rpcAdapter.ts";
import {
  WAVE_ACCEPTANCE,
  WAVE_INTERCOM_BRIDGE,
  type WaveAdapter,
  type WaveBus,
  type WaveChildReceipt,
  type WaveCompletion,
  type WaveRunHandle,
  type WaveSpawnParams,
} from "./transport.ts";

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
  completeRunPartial(handle: WaveRunHandle): void;
  /** Arrange the durable aggregate `readAggregate(handle)` will see. */
  stageAggregate(handle: WaveRunHandle, aggregate: StagedAggregate): void;
  /** How many status queries reached the flavor's engine seam so far. */
  statusRequests(): number;
}

/** A handle no adapter ever spawned (the refused/bogus arm). */
const BOGUS_HANDLE: WaveRunHandle = { asyncId: "no-such-run", asyncDir: "/no/such/dir" };

const PROOF_STATES = ["observed", "pending", "unknown", "unavailable"];

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
    script: "return [];",
    async: true,
    mission: false,
    context: "fresh",
    acceptance: WAVE_ACCEPTANCE,
    intercomBridge: WAVE_INTERCOM_BRIDGE,
    args: { launch: "contract-fixture-launch" },
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

  test(`${name}: partial report carrier is separate from output-free receipts`, async () => {
    const harness = makeHarness();
    await harness.adapter.ping();
    const received: WaveCompletion[] = [];
    const unsubscribe = harness.adapter.onComplete((completion) => received.push(completion));
    const handle = await harness.adapter.spawn(minimalSpawnParams());
    harness.completeRunPartial(handle);
    unsubscribe();
    // Both adapters agree on the still-running lane's projection: an explicit `ok: false` with
    // the fixed error (the normalizer's `lane-failed`), never `ok: null` (`malformed-report`).
    assert.deepEqual(received, [
      {
        asyncId: handle.asyncId,
        asyncDir: handle.asyncDir,
        state: "failed",
        success: false,
        children: [
          { key: "a", runId: "child", success: true },
          { key: "late", runId: "child-late" },
        ],
        terminalOutcome: { state: "partial", reason: "budget_exhausted" },
        retainedEntries: [
          { key: "a", ok: true, error: null, report: { answer: 1 } },
          {
            key: "late",
            ok: false,
            error: "lane still running at native partial settlement",
            report: null,
          },
        ],
      },
    ]);
    // No roster correlates an unfinished lane here: the key set is omitted, never empty.
    assert.equal("unfinishedLanes" in (received[0] ?? {}), false);
    for (const child of received[0]?.children ?? []) {
      assert.ok(Object.keys(child).every((key) => CHILD_KEYS.includes(key)));
    }
  });

  test(`${name}: onComplete before a successful ping throws`, () => {
    const { adapter } = makeHarness();
    assert.throws(() => adapter.onComplete(() => {}), /ping/);
  });

  test(`${name}: stop never throws and returns a typed outcome (acknowledged for a live handle; acknowledged:false with a reason for a refused/bogus one)`, async () => {
    const { adapter } = makeHarness();
    await adapter.ping();
    const handle = await adapter.spawn(minimalSpawnParams());
    assert.deepEqual(await adapter.stop(handle), { acknowledged: true });
    const refused = await adapter.stop(BOGUS_HANDLE);
    assert.equal(refused.acknowledged, false);
    if (!refused.acknowledged) {
      assert.match(refused.reason, /^not_found: Async run not found/);
    }
  });

  test(`${name}: terminalProof never throws and yields one of the four states — live handle or bogus handle`, async () => {
    const { adapter } = makeHarness();
    await adapter.ping();
    const handle = await adapter.spawn(minimalSpawnParams());
    await adapter.stop(handle);
    const live = await adapter.terminalProof(handle);
    assert.ok(PROOF_STATES.includes(live.state), `unexpected proof state '${live.state}'`);
    // The class is the contract: engine reason text varies across releases and with the instant
    // of the read, so only the state and a nonempty reason are asserted.
    assert.equal(live.state, "pending");
    assert.notEqual(live.reason, "");
    const bogus = await adapter.terminalProof(BOGUS_HANDLE);
    assert.deepEqual(bogus, {
      state: "unavailable",
      reason: "execution_failed: Async run not found. Provide id or dir.",
    });
  });

  test(`${name}: exactly one status request per terminalProof call`, async () => {
    const harness = makeHarness();
    const { adapter } = harness;
    await adapter.ping();
    const handle = await adapter.spawn(minimalSpawnParams());
    assert.equal(harness.statusRequests(), 0, "spawn/ping issue no status query");
    await adapter.stop(handle);
    assert.equal(harness.statusRequests(), 0, "stop issues no status query");
    await adapter.terminalProof(handle);
    assert.equal(harness.statusRequests(), 1);
    await adapter.terminalProof(BOGUS_HANDLE);
    assert.equal(harness.statusRequests(), 2);
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
    completeRunPartial(handle) {
      adapter.emitCompletion({
        asyncId: handle.asyncId,
        asyncDir: handle.asyncDir,
        state: "failed",
        success: false,
        children: [
          { key: "a", runId: "child", success: true },
          { key: "late", runId: "child-late" },
        ],
        terminalOutcome: { state: "partial", reason: "budget_exhausted" },
        // The memory flavor emits the already-narrowed still-running entry (its input is typed).
        retainedEntries: [
          { key: "a", ok: true, error: null, report: { answer: 1 } },
          {
            key: "late",
            ok: false,
            error: "lane still running at native partial settlement",
            report: null,
          },
        ],
      });
    },
    stageAggregate(_handle, aggregate) {
      adapter.setAggregate(aggregate);
    },
    statusRequests: () => adapter.proofs.length,
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

/**
 * The production adapter over the shared fake engine (`createFakeSubagents`, mirroring
 * pi-subagents 0.76.1's RPC: each spawn mints a real temp `asyncDir` with a `status.json`; `stop`
 * acknowledges a spawned run and refuses any other id `not_found`; `status` answers a spawned
 * run's immediate post-stop proof and any other id with the engine's `execution_failed` miss).
 * `delivery: "manual"` leaves every completion to the harness's explicit emissions below.
 */
function makeRpcHarness(): WaveAdapterHarness {
  const bus = createFakeBus();
  const fake = createFakeSubagents([{ delivery: "manual" }]);
  fake.attach(bus);
  return {
    adapter: createRpcWaveAdapter(bus),
    statusRequests: () => fake.statuses.length,
    completeRun(handle) {
      // A minimal payload: the result-file data's identifiers only (no `results` array).
      fake.emit({
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
      fake.emit({
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
    completeRunPartial(handle) {
      fake.emit({
        id: handle.asyncId,
        asyncDir: handle.asyncDir,
        state: "failed",
        success: false,
        terminalOutcome: { state: "partial", reason: "budget_exhausted" },
        results: [
          {
            workflowKey: "a",
            agent: "a",
            runId: "child",
            success: true,
            structuredOutput: { answer: 1 },
            output: "SECRET",
            summary: "SECRET",
          },
          // The engine's projection of a child still working at the workflow deadline: no
          // `success`, `state: "running"`.
          { workflowKey: "late", agent: "late", runId: "child-late", state: "running" },
        ],
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
