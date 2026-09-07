import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import type { ConflictResolutionRequest } from "../../../delivery/conflictResolution.ts";
import { acquireWorktreeResolverLock } from "../../../substrate/worktreeResolverLock.ts";
import {
  completedResolution,
  deferred,
  FakeDelegationBus,
  fakeResolverProfile,
} from "../../../testing/fakeConflictResolver.ts";
import {
  CANCEL_GRACE_MS,
  type ConflictResolverEngineOptions,
  createConflictResolverEngine,
  DELEGATION_EVENTS,
  loadResolverPreflight,
  nativeWorktreeDefault,
  REQUEST_TIMEOUT_MS,
  START_ACK_MS,
} from "./conflictResolverEngine.ts";

function world(t: TestContext, overrides: Partial<ConflictResolverEngineOptions> = {}) {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), "perk-resolver-engine-")));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  execFileSync("git", ["init", "-q", cwd], { timeout: 5000 });
  const profile = fakeResolverProfile(cwd);
  const bus = new FakeDelegationBus();
  const request: ConflictResolutionRequest = {
    mode: "pr-rebase",
    worktree: cwd,
    parent: { sessionId: "session", runId: "parent-run" },
    model: "offline/model",
  };
  const emitted = deferred<Record<string, unknown>>();
  bus.on(DELEGATION_EVENTS.request, (data) => emitted.resolve(data as Record<string, unknown>));
  const options: ConflictResolverEngineOptions = {
    events: bus,
    engineEntry: () => undefined,
    readOnly: () => false,
    authorized: () => true,
    availableModels: () => [{ provider: "offline", id: "model" }],
    preflight: async () => profile,
    configPath: join(cwd, "native-config.json"),
    ...overrides,
  };
  const engine = createConflictResolverEngine(options);
  return {
    cwd,
    profile,
    bus,
    request,
    emitted,
    engine,
    options,
    lockPath: join(cwd, ".git/perk-submit-conflict.lock"),
  };
}
function tuple(r: Record<string, unknown>) {
  return { requestId: r.requestId, ownerRunId: r.ownerRunId, nodeId: r.nodeId };
}
function respond(
  w: ReturnType<typeof world>,
  r: Record<string, unknown>,
  status = "completed",
  value: unknown = completedResolution,
) {
  w.bus.emit(DELEGATION_EVENTS.response, {
    ...tuple(r),
    status,
    runId: "native-run",
    agent: "perk.conflict-resolver",
    exitCode: 0,
    launchContractDigest: "launch-digest",
    result: { kind: "structured", value },
  });
}

test("one source-bound foreground request, terminal before start, safe receipts, duplicate/foreign events", async (t) => {
  const w = world(t);
  const running = w.engine.resolve(w.request);
  const r = await w.emitted.promise;
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
      "model",
    ].sort(),
  );
  assert.equal(r.context, "fresh");
  assert.equal(r.cwd, w.cwd);
  assert.equal(r.timeoutMs, REQUEST_TIMEOUT_MS);
  for (const field of ["requestId", "ownerRunId", "nodeId"])
    w.bus.emit(DELEGATION_EVENTS.response, {
      ...tuple(r),
      [field]: "foreign",
      status: "completed",
    });
  w.bus.emit(DELEGATION_EVENTS.update, {
    ...tuple(r),
    runId: "native-run",
    recentOutput: "SECRET OUTPUT",
    currentToolArgs: "SECRET ARGS",
  });
  respond(w, r);
  const result = await running;
  assert.equal(result.kind, "resolved");
  const receipt = JSON.stringify(result.receipt);
  assert.doesNotMatch(receipt, /SECRET|Offline checks|schema|task|token|artifact|usage/);
  assert.equal(result.receipt.runId, "native-run");
  assert.equal(result.receipt.lock.disposition, "released");
  assert.equal(w.bus.count(), 1, "only the test's request observer remains");
  assert.equal(existsSync(w.lockPath), false);
  respond(w, r, "failed");
  assert.equal(result.kind, "resolved");
});

for (const status of [
  "completed",
  "invalid_request",
  "unavailable_context",
  "duplicate_node",
  "failed",
  "timed_out",
  "cancelled",
  "interrupted",
  "tool_budget_exhausted",
  "structured_output_failed",
  "acceptance_failed",
]) {
  for (const evidence of ["none", "started", "update"]) {
    test(`lock terminal table: ${status}, evidence=${evidence}`, async (t) => {
      const w = world(t);
      const running = w.engine.resolve(w.request);
      const r = await w.emitted.promise;
      if (evidence !== "none")
        w.bus.emit(DELEGATION_EVENTS[evidence === "started" ? "started" : "update"], tuple(r));
      respond(w, r, status);
      const result = await running;
      const release =
        status === "completed" ||
        (evidence === "none" &&
          ["invalid_request", "unavailable_context", "duplicate_node"].includes(status));
      assert.equal(result.kind, status === "completed" ? "resolved" : "failed");
      assert.equal(result.receipt.lock.disposition, release ? "released" : "retained");
      assert.equal(existsSync(w.lockPath), !release);
      assert.equal(w.bus.count(), 1);
      if (!release) {
        const reopened = createConflictResolverEngine(w.options);
        const blocked = await reopened.resolve(w.request);
        assert.ok(blocked.kind === "failed" && blocked.reason === "lock-busy");
        await reopened.shutdown();
      }
    });
  }
}

for (const value of [
  null,
  { ...completedResolution, extra: true },
  { ...completedResolution, outcome: "aborted", push: "not-attempted" },
]) {
  test(`native completed releases independently of invalid/withheld domain report: ${JSON.stringify(value)}`, async (t) => {
    const w = world(t);
    const running = w.engine.resolve(w.request);
    const r = await w.emitted.promise;
    respond(w, r, "completed", value);
    const result = await running;
    assert.notEqual(result.kind, "resolved");
    assert.equal(result.receipt.lock.disposition, "released");
  });
}

test("malformed correlated envelope retains; unrelated malformed payload does nothing", async (t) => {
  const w = world(t);
  const running = w.engine.resolve(w.request);
  const r = await w.emitted.promise;
  w.bus.emit(DELEGATION_EVENTS.response, null);
  w.bus.emit(DELEGATION_EVENTS.response, {
    ...tuple(r),
    status: "completed",
    runId: { output: "SECRET" },
  });
  const result = await running;
  assert.ok(result.kind === "failed" && result.reason === "malformed-result");
  assert.equal(result.receipt.lock.disposition, "retained");
});

for (const malformed of [
  { error: {} },
  { model: 1 },
  { usage: "output" },
  { result: { kind: "unknown" } },
  { result: { kind: "structured" } },
]) {
  test(`malformed envelope metadata retains rather than treating it as a bad domain record: ${JSON.stringify(malformed)}`, async (t) => {
    const w = world(t);
    const running = w.engine.resolve(w.request);
    const r = await w.emitted.promise;
    w.bus.emit(DELEGATION_EVENTS.response, {
      ...tuple(r),
      status: "completed",
      result: { kind: "structured", value: completedResolution },
      ...malformed,
    });
    const result = await running;
    assert.ok(result.kind === "failed" && result.reason === "malformed-result");
    assert.equal(result.receipt.lock.disposition, "retained");
  });
}

for (const trigger of ["abort", "no-ack", "deadline", "shutdown", "emission-error"]) {
  for (const completion of [false, true]) {
    test(`${trigger}: cancellation tuple and grace completion=${completion}`, async (t) => {
      t.mock.timers.enable({ apis: ["setTimeout"] });
      const w = world(t);
      if (trigger === "emission-error")
        w.bus.on(DELEGATION_EVENTS.request, () => {
          throw new Error("SECRET transport");
        });
      const controller = new AbortController();
      const running = w.engine.resolve(w.request, controller.signal);
      const r = await w.emitted.promise;
      let shutdown: Promise<void> | undefined;
      if (trigger === "abort") controller.abort();
      if (trigger === "shutdown") shutdown = w.engine.shutdown();
      if (trigger === "no-ack") t.mock.timers.tick(START_ACK_MS);
      if (trigger === "deadline") {
        w.bus.emit(DELEGATION_EVENTS.started, tuple(r));
        t.mock.timers.tick(REQUEST_TIMEOUT_MS);
      }
      assert.deepEqual(
        w.bus.sent.filter((e) => e.event === DELEGATION_EVENTS.cancel).map((e) => e.data),
        [tuple(r)],
      );
      if (completion) respond(w, r);
      else t.mock.timers.tick(CANCEL_GRACE_MS);
      const result = await running;
      await shutdown;
      assert.equal(result.kind, "failed", "local cancellation cannot race into success");
      assert.equal(result.receipt.lock.disposition, completion ? "released" : "retained");
      assert.doesNotMatch(JSON.stringify(result), /SECRET/);
      assert.equal(w.bus.count(), trigger === "emission-error" ? 2 : 1);
      t.mock.timers.tick(REQUEST_TIMEOUT_MS * 2);
      assert.equal(w.bus.sent.filter((e) => e.event === DELEGATION_EVENTS.cancel).length, 1);
    });
  }
}

test("pre-aborted and cancellation during awaited preflight emit nothing, including late completion", async (t) => {
  const preflight = deferred<unknown>();
  const w = world(t, { preflight: () => preflight.promise });
  const a = new AbortController();
  a.abort();
  assert.equal((await w.engine.resolve(w.request, a.signal)).kind, "failed");
  const b = new AbortController();
  const running = w.engine.resolve(w.request, b.signal);
  b.abort();
  assert.equal((await running).kind, "failed");
  await w.engine.shutdown();
  preflight.resolve(w.profile);
  await Promise.resolve();
  assert.equal(w.bus.sent.length, 0);
  assert.equal(existsSync(w.lockPath), false);
});

for (const where of ["preflight", "acquisition"]) {
  test(`read-only changes after ${where} prevent emission`, async (t) => {
    let readonly = false;
    const w = world(t, { readOnly: () => readonly });
    const options = {
      ...w.options,
      preflight: async () => {
        if (where === "preflight") readonly = true;
        return w.profile;
      },
      acquire: (...args: Parameters<typeof acquireWorktreeResolverLock>) => {
        const r = acquireWorktreeResolverLock(...args);
        readonly = true;
        return r;
      },
    };
    const engine = createConflictResolverEngine(options);
    const result = await engine.resolve(w.request);
    assert.equal(result.kind, "failed");
    assert.equal(w.bus.sent.length, 0);
    assert.equal(existsSync(w.lockPath), false);
  });
}

for (const where of ["preflight", "acquisition"]) {
  test(`authorization revoked during ${where} refuses without requesting a writer`, async (t) => {
    let authorized = true;
    let acquisitions = 0;
    const observations: boolean[] = [];
    const entered = deferred<void>();
    const resume = deferred<void>();
    const w = world(t, {
      // Keep read-only state unchanged so only parent-authorization revalidation can refuse.
      readOnly: () => false,
      authorized: () => {
        observations.push(authorized);
        return authorized;
      },
    });
    const engine = createConflictResolverEngine({
      ...w.options,
      preflight: async () => {
        entered.resolve();
        await resume.promise;
        return w.profile;
      },
      acquire: (...args) => {
        const acquisition = acquireWorktreeResolverLock(...args);
        assert.equal(acquisition.kind, "acquired");
        assert.ok(existsSync(w.lockPath), "revocation happens while a real claim is held");
        acquisitions++;
        if (where === "acquisition") authorized = false;
        return acquisition;
      },
    });
    // If a regression emits, settle the fake child immediately so the assertions fail without
    // waiting for a production timeout. This responder must remain unused on the correct path.
    w.bus.on(DELEGATION_EVENTS.request, (r) => respond(w, r as Record<string, unknown>));
    const running = engine.resolve(w.request);
    try {
      await entered.promise;
      assert.deepEqual(observations, [true], "dispatch began with valid authorization");
      assert.equal(acquisitions, 0);
      assert.equal(existsSync(w.lockPath), false);
      if (where === "preflight") authorized = false;
      resume.resolve();
      const result = await running;
      assert.ok(result.kind === "failed" && result.reason === "unauthorized");
      assert.ok(observations.includes(false), "authorization was read again after revocation");
      assert.equal(acquisitions, where === "preflight" ? 0 : 1);
      assert.equal(
        result.receipt.lock.disposition,
        where === "preflight" ? "not-acquired" : "released",
      );
      assert.equal(result.receipt.termination, "not-requested");
      assert.deepEqual(w.bus.sent, [], "neither a writer request nor cancellation was emitted");
      assert.equal(existsSync(w.lockPath), false, "any never-emitted claim was released");
      assert.equal(w.bus.count(), 2, "only test observers remain");
    } finally {
      resume.resolve();
      await running;
      await engine.shutdown();
    }
  });
}

test("abort after acquiring releases, but release ownership failure withholds success", async (t) => {
  const w = world(t);
  const a = new AbortController();
  const aborted = createConflictResolverEngine({
    ...w.options,
    acquire: (...args) => {
      const r = acquireWorktreeResolverLock(...args);
      a.abort();
      return r;
    },
  });
  assert.equal((await aborted.resolve(w.request, a.signal)).receipt.lock.disposition, "released");
  const running = w.engine.resolve(w.request);
  const r = await w.emitted.promise;
  writeFileSync(w.lockPath, "successor");
  respond(w, r);
  const result = await running;
  assert.ok(result.kind === "failed" && result.reason === "lock-ownership");
  assert.equal(readFileSync(w.lockPath, "utf8"), "successor");
});

test("profile, directory and throwing read-only backstops fail before launch", async (t) => {
  const w = world(t);
  for (const mutation of [
    { context: "fork" },
    { model: undefined },
    { inheritGlobalContext: true },
    { inheritSkills: false },
    { systemPromptMode: "append" },
    { agent: { ...w.profile.contract.agent, shadowedCandidates: [{}] } },
    { agent: { ...w.profile.contract.agent, source: "user" } },
    ...[true, "false", 0, {}].map((disabled) => ({
      agent: { ...w.profile.contract.agent, disabled },
    })),
    { tools: { ...w.profile.contract.tools, declaredBuiltin: ["read"] } },
    { tools: { ...w.profile.contract.tools, configuredExtensions: ["extra"] } },
    { tools: { ...w.profile.contract.tools, toolExtensionPaths: ["extra"] } },
    { tools: { ...w.profile.contract.tools, fanoutAuthorized: true } },
  ]) {
    const e = createConflictResolverEngine({
      ...w.options,
      preflight: async () => ({ ok: true, contract: { ...w.profile.contract, ...mutation } }),
    });
    assert.equal((await e.resolve(w.request)).kind, "failed");
  }
  for (const worktree of ["relative", `${w.cwd}\n`, join(w.cwd, "missing")])
    assert.equal((await w.engine.resolve({ ...w.request, worktree })).kind, "failed");
  const e = createConflictResolverEngine({
    ...w.options,
    readOnly: () => {
      throw new Error("SECRET");
    },
  });
  assert.equal((await e.resolve(w.request)).kind, "failed");
  assert.equal(w.bus.sent.length, 0);
});

test("native worktree defaults: compatible absence/false; changed or incompatible refuses", async (t) => {
  const w = world(t);
  const path = w.options.configPath as string;
  assert.equal(nativeWorktreeDefault(path), "missing");
  for (const content of [
    "{}",
    '{"worktree":false}',
    '{"worktree":true}',
    '{"worktree":"false"}',
    "{",
    "null",
  ]) {
    writeFileSync(path, content);
    assert.equal(
      (await w.engine.resolve(w.request)).kind,
      "failed",
      "changed setting requires reload",
    );
  }
  rmSync(path);
  mkdirSync(path);
  assert.equal(nativeWorktreeDefault(path), "incompatible");
  assert.equal(w.bus.sent.length, 0);
});

test("optional loader refuses missing/malformed/escaping public exports without a fallback", async (t) => {
  const w = world(t);
  const root = join(w.cwd, "engine");
  mkdirSync(root);
  const entry = join(root, "index.ts");
  writeFileSync(entry, "");
  assert.equal(await loadResolverPreflight(undefined), null);
  for (const exports of [
    {},
    { "./preflight": "./index.ts", "./delegation": "./index.ts" },
    { "./preflight": "../outside.ts", "./delegation": "./index.ts" },
    { "./preflight": {}, "./delegation": "./index.ts" },
  ]) {
    writeFileSync(join(root, "package.json"), JSON.stringify({ name: "pi-subagents", exports }));
    assert.equal(await loadResolverPreflight(entry), null);
  }
  writeFileSync(join(w.cwd, "outside.ts"), "");
  symlinkSync(join(w.cwd, "outside.ts"), join(root, "escape.ts"));
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({
      name: "pi-subagents",
      exports: { "./preflight": "./escape.ts", "./delegation": "./index.ts" },
    }),
  );
  assert.equal(await loadResolverPreflight(entry), null);
});
