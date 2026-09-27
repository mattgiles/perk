import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { nativeWorktreeRefusal } from "../../delivery/conflictResolution.ts";
import { FakeDelegationBus } from "../../testing/fakeConflictResolver.ts";
import {
  CANCEL_GRACE_MS,
  DELEGATION_EVENTS,
  type DelegationTuple,
  dispatchForeground,
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

test("the emitted request shape: fresh context, the transport deadline, the schema by identity, model only when given", async () => {
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
        ...(model !== undefined ? ["model"] : []),
      ].sort(),
    );
    for (const absent of ["extensionBindings", "async", "worktree"])
      assert.equal(Object.hasOwn(r, absent), false, absent);
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
