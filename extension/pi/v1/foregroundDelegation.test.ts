import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { nativeWorktreeRefusal } from "../../delivery/conflictResolution.ts";
import {
  FakeDelegationBus,
  fakeConflictResolver,
  providerHistoryDiagnostics,
  providerRetryDiagnostics,
} from "../../testing/fakeConflictResolver.ts";
import { WAVE_INTERCOM_BRIDGE } from "../../waves/transport.ts";
import {
  CANCEL_GRACE_MS,
  DELEGATION_EVENTS,
  type DelegationProgress,
  type DelegationTuple,
  dispatchForeground,
  FOREGROUND_INTERCOM_BRIDGE,
  type ForegroundLaunch,
  nativeWorktreeFix,
  REQUEST_TIMEOUT_MS,
  readNativeWorktreeDefault,
  START_ACK_MS,
} from "./foregroundDelegation.ts";

const SCHEMA = { type: "object", properties: { ok: { type: "boolean" } } };
const TUPLE: DelegationTuple = { requestId: "req-1", ownerRunId: "run-1", nodeId: "node-1" };
const LAUNCH: ForegroundLaunch = {
  agent: "perk.writer",
  task: "do it",
  cwd: "/tmp/x",
  schema: SCHEMA,
};

function requests(bus: FakeDelegationBus): Record<string, unknown>[] {
  return bus.sent
    .filter((e) => e.event === DELEGATION_EVENTS.request)
    .map((e) => e.data as Record<string, unknown>);
}
function cancels(bus: FakeDelegationBus): unknown[] {
  return bus.sent.filter((e) => e.event === DELEGATION_EVENTS.cancel).map((e) => e.data);
}
function respond(bus: FakeDelegationBus, fields: Record<string, unknown>) {
  bus.emit(DELEGATION_EVENTS.response, { ...TUPLE, ...fields });
}
function update(bus: FakeDelegationBus, fields: Record<string, unknown> = {}) {
  bus.emit(DELEGATION_EVENTS.update, { ...TUPLE, ...fields });
}
/** A recording progress sink. */
function recorder(): { seen: DelegationProgress[]; sink: (p: DelegationProgress) => void } {
  const seen: DelegationProgress[] = [];
  return { seen, sink: (p) => seen.push(p) };
}
// The decoded shape of `providerRetryDiagnostics(phase)` (independent literals: the supplier's
// `message` is gone, everything else is carried field for field).
function decodedRetry(phase: "backoff" | "in_flight", attempt = 2) {
  return {
    errorCount: 1,
    lastError: { kind: "rate_limited", at: 1 },
    retry: { phase, attempt, maxAttempts: 5, delayMs: 8000, scheduledAt: 1 },
  };
}
const DECODED_HISTORY = { errorCount: 1, lastError: { kind: "rate_limited", at: 1 } };

test("an already-aborted signal emits nothing and leaves no subscription", async () => {
  const bus = new FakeDelegationBus();
  const controller = new AbortController();
  controller.abort();
  const outcome = await dispatchForeground(bus, LAUNCH, TUPLE, controller.signal);
  assert.deepEqual(outcome, {
    failure: "cancelled",
    release: true,
    termination: "not-requested",
  });
  assert.deepEqual(bus.sent, [], "no request, no cancel");
  assert.equal(bus.count(), 0, "no subscription was installed");
});

test("the emitted request shape: fresh context, the transport deadline, the schema by identity, the bridge off, model only when given", async () => {
  for (const model of [undefined, "offline/model"]) {
    const bus = new FakeDelegationBus();
    const running = dispatchForeground(
      bus,
      { ...LAUNCH, ...(model !== undefined ? { model } : {}) },
      TUPLE,
      new AbortController().signal,
    );
    const [r] = requests(bus);
    assert.ok(r, "the request is emitted synchronously");
    assert.deepEqual(
      Object.keys(r).sort(),
      [
        "requestId",
        "ownerRunId",
        "nodeId",
        "agent",
        "task",
        "cwd",
        "context",
        "timeoutMs",
        "result",
        "intercomBridge",
        ...(model !== undefined ? ["model"] : []),
      ].sort(),
    );
    for (const absent of ["extensionBindings", "async", "worktree"])
      assert.equal(Object.hasOwn(r, absent), false, absent);
    assert.deepEqual(r.intercomBridge, { mode: "off" });
    assert.equal(r.agent, "perk.writer");
    assert.equal(r.task, "do it");
    assert.equal(r.cwd, "/tmp/x");
    assert.equal(r.context, "fresh");
    assert.equal(r.timeoutMs, REQUEST_TIMEOUT_MS);
    assert.equal((r.result as { schema: unknown }).schema, SCHEMA, "the schema rides by identity");
    assert.equal((r.result as { kind: unknown }).kind, "structured");
    if (model !== undefined) assert.equal(r.model, model);
    bus.emit(DELEGATION_EVENTS.update, { ...TUPLE, runId: "native-run" });
    respond(bus, { status: "completed", result: { kind: "structured", value: { ok: true } } });
    const outcome = await running;
    assert.equal(outcome.termination, "confirmed");
    assert.equal(outcome.release, true);
    assert.equal(outcome.observedRunId, "native-run");
    assert.deepEqual(outcome.terminal, { status: "completed", value: { ok: true } });
    assert.equal(outcome.failure, undefined);
    assert.equal(bus.count(), 0, "every subscription is released");
  }
});

test("perk's two spawn surfaces carry the same bridge disable, byte for byte", () => {
  assert.deepEqual(FOREGROUND_INTERCOM_BRIDGE, WAVE_INTERCOM_BRIDGE);
  assert.equal(JSON.stringify(FOREGROUND_INTERCOM_BRIDGE), JSON.stringify(WAVE_INTERCOM_BRIDGE));
});

test("the bridge is not caller-selectable: a widened launch still emits it off and leaks nothing", async () => {
  const bus = new FakeDelegationBus();
  const widened = {
    ...LAUNCH,
    intercomBridge: { mode: "always" },
    worktree: true,
  } as unknown as ForegroundLaunch;
  const running = dispatchForeground(bus, widened, TUPLE, new AbortController().signal);
  const [r] = requests(bus);
  assert.ok(r);
  assert.deepEqual(r.intercomBridge, { mode: "off" });
  assert.equal(Object.hasOwn(r, "worktree"), false, "no other launch-side key leaks");
  assert.deepEqual(
    Object.keys(r).sort(),
    [
      "requestId",
      "ownerRunId",
      "nodeId",
      "agent",
      "task",
      "cwd",
      "context",
      "timeoutMs",
      "result",
      "intercomBridge",
    ].sort(),
  );
  respond(bus, { status: "completed", result: { kind: "structured", value: { ok: true } } });
  assert.equal((await running).termination, "confirmed");
});

test("the fake engine mirrors the engine's request validation: census and bridge rules are live", async () => {
  const bus = new FakeDelegationBus();
  const fake = fakeConflictResolver("/tmp/x");
  fake.extension({ registerTool() {}, events: bus } as unknown as ExtensionAPI);
  const responses: Record<string, unknown>[] = [];
  bus.on(DELEGATION_EVENTS.response, (data) => responses.push(data as Record<string, unknown>));
  function emitByHand(requestId: string, extra: Record<string, unknown>) {
    bus.emit(DELEGATION_EVENTS.request, {
      requestId,
      ownerRunId: "run-1",
      nodeId: "node-1",
      agent: "perk.writer",
      task: "do it",
      cwd: "/tmp/x",
      context: "fresh",
      result: { kind: "structured", schema: SCHEMA },
      ...extra,
    });
    const reply = responses.find((r) => r.requestId === requestId);
    assert.ok(reply, `${requestId} was answered`);
    return reply;
  }
  const rejected: [string, Record<string, unknown>, string][] = [
    ["stray-key", { extensionBindings: [] }, "Unsupported delegation field: extensionBindings."],
    [
      "typed-field",
      { intercomBridge: { mode: "off", resultDelivery: "false" } },
      "intercomBridge.resultDelivery must be a boolean.",
    ],
    ["bridge-array", { intercomBridge: [] }, "intercomBridge must be an object."],
    ["bridge-key", { intercomBridge: { off: true } }, "intercomBridge.off is not supported."],
    ["bridge-mode", { intercomBridge: { mode: "never" } }, "intercomBridge.mode is invalid."],
    [
      "bridge-file-type",
      { intercomBridge: { instructionFile: 7 } },
      "intercomBridge.instructionFile must be a string.",
    ],
    [
      "bridge-file-size",
      { intercomBridge: { instructionFile: "\u00e9".repeat(513) } },
      "intercomBridge.instructionFile exceeds 1 KiB when UTF-8 encoded.",
    ],
  ];
  for (const [requestId, extra, error] of rejected) {
    assert.deepEqual(emitByHand(requestId, extra), {
      requestId,
      ownerRunId: "run-1",
      nodeId: "node-1",
      status: "invalid_request",
      error,
    });
  }
  for (const [requestId, bridge] of [
    ["empty-bridge", {}],
    ["mode-omitted", { resultDelivery: true }],
    ["file-at-cap", { instructionFile: "\u00e9".repeat(512) }],
  ] as const) {
    assert.equal(emitByHand(requestId, { intercomBridge: bridge }).status, "completed", requestId);
  }
  const outcome = await dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
  assert.equal(outcome.terminal?.status, "completed", "the real transport request is accepted");
  assert.equal(outcome.termination, "confirmed");
  assert.equal(fake.requests.length, rejected.length + 4);
});

test("a synchronous response delivered during emit is honored", async () => {
  const bus = new FakeDelegationBus();
  bus.on(DELEGATION_EVENTS.request, () =>
    respond(bus, {
      status: "completed",
      runId: "sync-run",
      agent: "perk.writer",
      exitCode: 0,
      result: { kind: "structured", value: { ok: true } },
    }),
  );
  const outcome = await dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
  assert.equal(outcome.termination, "confirmed");
  assert.deepEqual(outcome.terminal, {
    status: "completed",
    value: { ok: true },
    runId: "sync-run",
    agent: "perk.writer",
    exitCode: 0,
  });
});

test("a malformed correlated terminal is malformed-result and never releases; foreign tuples are ignored", async () => {
  const bus = new FakeDelegationBus();
  const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
  bus.emit(DELEGATION_EVENTS.response, { ...TUPLE, requestId: "foreign", status: "completed" });
  respond(bus, { status: "completed", runId: { output: "SECRET" } });
  const outcome = await running;
  assert.deepEqual(outcome, {
    failure: "malformed-result",
    release: false,
    termination: "unconfirmed",
  });
});

test("release: completed and an unstarted pre-launch status release; a started pre-launch or a failure does not", async () => {
  const rows = [
    { status: "completed", started: false, release: true, termination: "confirmed" },
    { status: "invalid_request", started: false, release: true, termination: "confirmed" },
    { status: "invalid_request", started: true, release: false, termination: "unconfirmed" },
    { status: "failed", started: false, release: false, termination: "unconfirmed" },
  ] as const;
  for (const row of rows) {
    const bus = new FakeDelegationBus();
    const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
    if (row.started) bus.emit(DELEGATION_EVENTS.started, TUPLE);
    respond(bus, { status: row.status });
    const outcome = await running;
    assert.equal(outcome.release, row.release, row.status);
    assert.equal(outcome.termination, row.termination, row.status);
    assert.equal(outcome.terminal?.status, row.status);
  }
});

// pi-subagents 0.76.1 can free a capacity slot (a sealed paused run, `abandonedSlotReleaseAfterMs`
// after a dead runner PID) independently of the child's terminal — engine slot state is never
// writer termination evidence; `release` derives from the correlated `status` alone.
const SLOT_DECORATIONS = {
  processTerminal: { state: "observed", observedAt: 7 },
  slotReleased: true,
  capacity: { active: 0, limit: 4, released: ["native-run"] },
  lifecycleStatus: { processTerminal: { state: "observed" } },
};

test("a freed supplier slot is never writer termination: a failed terminal decorated with process/capacity fields still retains", async () => {
  for (const started of [false, true]) {
    const bus = new FakeDelegationBus();
    const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
    if (started) bus.emit(DELEGATION_EVENTS.started, TUPLE);
    respond(bus, { status: "failed", runId: "native-run", ...SLOT_DECORATIONS });
    const outcome = await running;
    assert.equal(outcome.release, false, `started=${started}`);
    assert.equal(outcome.termination, "unconfirmed", `started=${started}`);
    // Only the whitelisted scalar facts survive; the decorations never reach the outcome.
    assert.deepEqual(outcome.terminal, { status: "failed", runId: "native-run" });
  }
});

test("a completed terminal decorated the same way still releases on status alone", async () => {
  const bus = new FakeDelegationBus();
  const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
  bus.emit(DELEGATION_EVENTS.started, TUPLE);
  respond(bus, { status: "completed", runId: "native-run", ...SLOT_DECORATIONS });
  const outcome = await running;
  assert.equal(outcome.release, true);
  assert.equal(outcome.termination, "confirmed");
  assert.deepEqual(outcome.terminal, { status: "completed", runId: "native-run" });
});

test("provider diagnostics on a terminal are an ignored decoration: a failed terminal still retains, a completed one releases, and only the whitelist survives", async () => {
  for (const status of ["failed", "completed"] as const) {
    const bus = new FakeDelegationBus();
    const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
    bus.emit(DELEGATION_EVENTS.started, TUPLE);
    respond(bus, {
      status,
      runId: "native-run",
      providerDiagnostics: providerRetryDiagnostics("backoff"),
    });
    const outcome = await running;
    assert.equal(outcome.release, status === "completed", status);
    assert.equal(outcome.termination, status === "completed" ? "confirmed" : "unconfirmed");
    assert.deepEqual(outcome.terminal, { status, runId: "native-run" });
    assert.doesNotMatch(JSON.stringify(outcome), /SECRET|providerDiagnostics/);
  }
});

test("source pin: the writer transport never names engine capacity/slot state; release derives from the terminal status", () => {
  const source = readFileSync(new URL("./foregroundDelegation.ts", import.meta.url), "utf8");
  assert.doesNotMatch(source, /\b(capacity|abandonedSlot\w*|slotReleased)\b/);
  // The positive arm: the release rule reads the correlated terminal's status.
  assert.match(source, /const release = t\.status === "completed"/);
});

test("old payloads: an update without diagnostics reaches the sink as unavailable and still contributes the run id; a decorated terminal is unchanged", async () => {
  for (const status of ["completed", "failed"] as const) {
    const bus = new FakeDelegationBus();
    const progress = recorder();
    const running = dispatchForeground(
      bus,
      LAUNCH,
      TUPLE,
      new AbortController().signal,
      progress.sink,
    );
    update(bus, {
      runId: "observed-run",
      recentOutput: "SECRET output",
      currentToolArgs: "SECRET",
    });
    respond(bus, { status, providerDiagnostics: providerRetryDiagnostics("in_flight") });
    const outcome = await running;
    assert.deepEqual(progress.seen, [{}], status);
    assert.equal(Object.hasOwn(progress.seen[0] ?? {}, "diagnostics"), false);
    assert.equal(outcome.observedRunId, "observed-run");
    assert.deepEqual(outcome.terminal, { status });
    assert.equal(outcome.release, status === "completed");
    assert.doesNotMatch(JSON.stringify([outcome, progress.seen]), /SECRET/);
  }
});

test("backoff and in-flight transitions arrive in order and replace, never merge; a malformed snapshot is unavailable", async () => {
  const bus = new FakeDelegationBus();
  const progress = recorder();
  const running = dispatchForeground(
    bus,
    LAUNCH,
    TUPLE,
    new AbortController().signal,
    progress.sink,
  );
  update(bus, { providerDiagnostics: providerRetryDiagnostics("backoff") });
  update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
  update(bus, { providerDiagnostics: { ...providerRetryDiagnostics("backoff"), errorCount: -1 } });
  update(bus, { providerDiagnostics: providerHistoryDiagnostics() });
  update(bus, {
    providerDiagnostics: providerRetryDiagnostics("backoff", {
      retry: { phase: "backoff", attempt: 3, maxAttempts: 5, delayMs: 8000, scheduledAt: 1 },
    }),
  });
  update(bus, {
    ...TUPLE,
    requestId: "foreign",
    providerDiagnostics: providerHistoryDiagnostics(),
  });
  respond(bus, { status: "completed" });
  const outcome = await running;
  assert.deepEqual(progress.seen, [
    { diagnostics: decodedRetry("backoff") },
    { diagnostics: decodedRetry("in_flight") },
    {},
    { diagnostics: DECODED_HISTORY },
    { diagnostics: decodedRetry("backoff", 3) },
  ]);
  assert.equal(outcome.release, true);
  assert.doesNotMatch(JSON.stringify(progress.seen), /SECRET/);
});

test("listener cleanup: nothing reaches the sink after settlement; subscriptions are released", async () => {
  for (const terminal of [{ status: "completed" }, { status: "bogus" }]) {
    const bus = new FakeDelegationBus();
    const progress = recorder();
    const running = dispatchForeground(
      bus,
      LAUNCH,
      TUPLE,
      new AbortController().signal,
      progress.sink,
    );
    update(bus, { providerDiagnostics: providerRetryDiagnostics("backoff") });
    respond(bus, terminal);
    update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
    const outcome = await running;
    update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
    assert.equal(progress.seen.length, 1, terminal.status);
    assert.equal(bus.count(), 0, terminal.status);
    assert.equal(outcome.failure, terminal.status === "bogus" ? "malformed-result" : undefined);
  }
});

test("terminal races during emit: the cutoff is settlement, not terminal arrival", async () => {
  for (const order of ["response-first", "update-first"] as const) {
    const bus = new FakeDelegationBus();
    const progress = recorder();
    bus.on(DELEGATION_EVENTS.request, () => {
      if (order === "update-first")
        update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
      respond(bus, { status: "completed" });
      if (order === "response-first")
        update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
    });
    const outcome = await dispatchForeground(
      bus,
      LAUNCH,
      TUPLE,
      new AbortController().signal,
      progress.sink,
    );
    // response-first: the terminal was parked during emit, so the following update still passes.
    assert.deepEqual(progress.seen, [{ diagnostics: decodedRetry("in_flight") }], order);
    assert.equal(outcome.termination, "confirmed", order);
    assert.equal(outcome.release, true, order);
    update(bus, { providerDiagnostics: providerRetryDiagnostics("backoff") });
    assert.equal(progress.seen.length, 1, `${order}: nothing after settlement`);
    assert.equal(bus.count(), 1, `${order}: only the test's own request handler remains`);
  }
});

test("cancellation grace: updates still reach the sink until grace expiry settles; a terminal inside the grace stops them", async (t: TestContext) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = new FakeDelegationBus();
  const first = new AbortController();
  const expired = recorder();
  const one = dispatchForeground(bus, LAUNCH, TUPLE, first.signal, expired.sink);
  bus.emit(DELEGATION_EVENTS.started, TUPLE);
  first.abort();
  update(bus, { providerDiagnostics: providerRetryDiagnostics("backoff") });
  assert.equal(expired.seen.length, 1, "an update during the grace is still observed");
  t.mock.timers.tick(CANCEL_GRACE_MS);
  const lapsed = await one;
  assert.equal(lapsed.failure, "termination-unconfirmed");
  update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
  assert.equal(expired.seen.length, 1, "nothing after grace expiry");

  const second = new AbortController();
  const cancelled = recorder();
  const two = dispatchForeground(bus, LAUNCH, TUPLE, second.signal, cancelled.sink);
  second.abort();
  update(bus, { providerDiagnostics: providerRetryDiagnostics("backoff") });
  respond(bus, { status: "completed" });
  update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
  const outcome = await two;
  assert.deepEqual(cancelled.seen, [{ diagnostics: decodedRetry("backoff") }]);
  assert.equal(outcome.failure, "cancelled");
  assert.equal(outcome.release, true);
  assert.equal(bus.count(), 0);
});

test("a throwing sink is contained: the dispatch still completes on the response", async () => {
  const bus = new FakeDelegationBus();
  let calls = 0;
  const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal, () => {
    calls++;
    throw new Error("SECRET render failure");
  });
  update(bus, { runId: "observed-run", providerDiagnostics: providerRetryDiagnostics("backoff") });
  update(bus, { providerDiagnostics: providerRetryDiagnostics("in_flight") });
  respond(bus, { status: "completed" });
  const outcome = await running;
  assert.equal(calls, 2);
  assert.equal(outcome.termination, "confirmed");
  assert.equal(outcome.release, true);
  assert.equal(outcome.observedRunId, "observed-run");
  assert.equal(bus.count(), 0);
  assert.doesNotMatch(JSON.stringify(outcome), /SECRET/);
});

test("no start-ack cancels with the exact tuple and settles termination-unconfirmed after the grace", async (t: TestContext) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = new FakeDelegationBus();
  const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
  t.mock.timers.tick(START_ACK_MS);
  assert.deepEqual(cancels(bus), [TUPLE]);
  t.mock.timers.tick(CANCEL_GRACE_MS);
  const outcome = await running;
  assert.deepEqual(outcome, {
    failure: "termination-unconfirmed",
    release: false,
    termination: "unconfirmed",
  });
});

test("abort after emit: cancel tuple once; grace expiry never releases; a terminal inside the grace is cancelled but releases", async (t: TestContext) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = new FakeDelegationBus();
  const first = new AbortController();
  const one = dispatchForeground(bus, LAUNCH, TUPLE, first.signal);
  bus.emit(DELEGATION_EVENTS.started, TUPLE);
  first.abort();
  assert.deepEqual(cancels(bus), [TUPLE]);
  t.mock.timers.tick(CANCEL_GRACE_MS);
  assert.deepEqual(await one, {
    failure: "termination-unconfirmed",
    release: false,
    termination: "unconfirmed",
  });
  const second = new AbortController();
  const two = dispatchForeground(bus, LAUNCH, TUPLE, second.signal);
  second.abort();
  respond(bus, { status: "completed" });
  const outcome = await two;
  assert.equal(outcome.failure, "cancelled");
  assert.equal(outcome.release, true);
  assert.equal(outcome.termination, "confirmed");
  assert.equal(cancels(bus).length, 2);
});

test("an emission error cancels with the tuple (transport-failed) and settles unconfirmed at grace expiry", async (t: TestContext) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const bus = new FakeDelegationBus();
  bus.on(DELEGATION_EVENTS.request, () => {
    throw new Error("SECRET transport");
  });
  const running = dispatchForeground(bus, LAUNCH, TUPLE, new AbortController().signal);
  assert.deepEqual(cancels(bus), [TUPLE]);
  t.mock.timers.tick(CANCEL_GRACE_MS);
  const outcome = await running;
  assert.equal(outcome.failure, "termination-unconfirmed");
  assert.equal(outcome.release, false);
  assert.doesNotMatch(JSON.stringify(outcome), /SECRET/);
});

test("readNativeWorktreeDefault: missing / false are compatible; true, a string and unparseable JSON are refused by observation", (t: TestContext) => {
  const dir = mkdtempSync(join(tmpdir(), "perk-native-default-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const path = join(dir, "config.json");
  assert.deepEqual(readNativeWorktreeDefault(path), { compatible: true });
  for (const [content, verdict] of [
    ['{"worktree":false}', { compatible: true }],
    ["{}", { compatible: true }],
    ['{"worktree":true}', { compatible: false, observed: "worktree=true" }],
    ['{"worktree":"SECRET"}', { compatible: false, observed: "worktree is a string" }],
    ["{", { compatible: false, observed: "unparseable JSON" }],
  ] as const) {
    writeFileSync(path, content);
    assert.deepEqual(readNativeWorktreeDefault(path), verdict, content);
  }
});

test("nativeWorktreeFix renders the same sentence as the Pi-free nativeWorktreeRefusal", () => {
  const config = { path: "/agent/extensions/subagent/config.json", observed: "worktree=true" };
  assert.equal(
    nativeWorktreeFix(config),
    nativeWorktreeRefusal({
      nodeId: "submit-conflict",
      cwd: "/x",
      termination: "not-requested",
      lock: { disposition: "not-acquired" },
      nativeWorktreeConfig: config,
    }),
  );
});
