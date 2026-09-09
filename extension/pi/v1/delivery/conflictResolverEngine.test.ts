import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import {
  type ConflictResolutionRequest,
  type ConflictResolutionResult,
  conflictResolutionSchema,
} from "../../../delivery/conflictResolution.ts";
import {
  completedResolution,
  completedRetainedResolution,
  FakeDelegationBus,
  RETAINED_OPERATION,
  retainedDispatch,
} from "../../../testing/fakeConflictResolver.ts";
import {
  CANCEL_GRACE_MS,
  type ConflictResolverEngineOptions,
  createConflictResolverEngine,
  DELEGATION_EVENTS,
  REQUEST_TIMEOUT_MS,
  RESOLVER_AGENT,
  START_ACK_MS,
} from "./conflictResolverEngine.ts";

for (const mode of ["pr-rebase", "retained-continuation"] as const) {
  const successKind = mode === "pr-rebase" ? "resolved" : "continuation-ready";
  const completion = mode === "pr-rebase" ? completedResolution : completedRetainedResolution;
  function world(t: TestContext, overrides: Partial<ConflictResolverEngineOptions> = {}) {
    const parent = realpathSync(mkdtempSync(join(tmpdir(), "perk-resolver-engine-")));
    t.after(() => rmSync(parent, { recursive: true, force: true }));
    execFileSync("git", ["init", "-q", parent], { timeout: 30_000 });
    let cwd = parent;
    if (mode === "retained-continuation") {
      execFileSync(
        "git",
        [
          "-C",
          parent,
          "-c",
          "user.name=Test",
          "-c",
          "user.email=test@example.org",
          "commit",
          "--allow-empty",
          "-qm",
          "base",
        ],
        { timeout: 30_000 },
      );
      cwd = join(parent, `sync-${RETAINED_OPERATION}`);
      execFileSync("git", ["-C", parent, "worktree", "add", "--detach", cwd], { timeout: 30_000 });
    }
    const bus = new FakeDelegationBus();
    const request: ConflictResolutionRequest = {
      ...retainedDispatch(cwd),
      mode,
      worktree: cwd,
      parent: { sessionId: "session", runId: "parent-run" },
      model: "offline/model",
    };
    const requests: Record<string, unknown>[] = [];
    bus.on(DELEGATION_EVENTS.request, (data) => requests.push(data as Record<string, unknown>));
    const options: ConflictResolverEngineOptions = {
      events: bus,
      enginePresent: () => true,
      readOnly: () => false,
      authorized: () => true,
      configPath: join(cwd, "native-config.json"),
      ...overrides,
    };
    const engine = createConflictResolverEngine(options);
    return {
      cwd,
      bus,
      request,
      requests,
      engine,
      options,
      parent,
      configPath: options.configPath as string,
      lockPath: join(
        execFileSync("git", ["-C", cwd, "rev-parse", "--absolute-git-dir"], {
          encoding: "utf8",
          timeout: 30_000,
        }).trim(),
        "perk-submit-conflict.lock",
      ),
    };
  }
  type World = ReturnType<typeof world>;
  function tuple(r: Record<string, unknown>) {
    return { requestId: r.requestId, ownerRunId: r.ownerRunId, nodeId: r.nodeId };
  }
  /** Entry to emission is synchronous, so the emitted request is observable as `resolve` returns. */
  function launch(w: World, engine = w.engine, signal?: AbortSignal) {
    const before = w.requests.length;
    const running = engine.resolve(w.request, signal);
    assert.equal(w.requests.length, before + 1, "one request is emitted synchronously from entry");
    return { running, r: w.requests[before] as Record<string, unknown> };
  }
  function respond(
    w: World,
    r: Record<string, unknown>,
    status = "completed",
    value: unknown = completion,
  ) {
    w.bus.emit(DELEGATION_EVENTS.response, {
      ...tuple(r),
      status,
      runId: "native-run",
      agent: "perk.conflict-resolver",
      exitCode: 0,
      result: { kind: "structured", value },
    });
  }
  function cancels(w: World) {
    return w.bus.sent.filter((e) => e.event === DELEGATION_EVENTS.cancel).map((e) => e.data);
  }

  test(`[${mode}] request shape: one public delegation request carrying NO restriction packet; foreign/duplicate events are ignored; receipts carry no output`, async (t) => {
    const w = world(t);
    const { running, r } = launch(w);
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
    assert.equal(
      Object.hasOwn(r, "extensionBindings"),
      false,
      "no perk.parent-restrictions packet: the writer never gets the read-only floor",
    );
    assert.equal(r.agent, RESOLVER_AGENT);
    assert.equal(r.context, "fresh");
    assert.equal(r.nodeId, mode === "pr-rebase" ? "submit-conflict" : "retained-conflict");
    assert.deepEqual(r.result, { kind: "structured", schema: conflictResolutionSchema(mode) });
    if (mode === "retained-continuation")
      assert.equal(existsSync(join(w.parent, ".git/perk-submit-conflict.lock")), false);
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
    assert.equal(result.kind, successKind);
    const receipt = JSON.stringify(result.receipt);
    assert.doesNotMatch(receipt, /SECRET|Offline checks|schema|task|token|artifact|usage/);
    assert.equal(result.receipt.runId, "native-run");
    assert.equal(result.receipt.lock.disposition, "released");
    assert.equal(w.bus.count(), 1, "only the test's request observer remains");
    assert.equal(existsSync(w.lockPath), false);
    respond(w, r, "failed");
    assert.equal(result.kind, successKind);
  });

  test(`[${mode}] terminal → outcome and lock disposition; a retained lock is never reclaimed`, async (t) => {
    const withheld =
      mode === "pr-rebase"
        ? { ...completedResolution, outcome: "aborted", push: "not-attempted" }
        : {
            ...completedRetainedResolution,
            outcome: "verification-failed",
            verification: "failed",
          };
    const rows: {
      status: string;
      value?: unknown;
      started?: boolean;
      kind: ConflictResolutionResult["kind"];
      reason?: string;
      released: boolean;
    }[] = [
      { status: "completed", value: completion, kind: successKind, released: true },
      {
        status: "completed",
        value: null,
        kind: "failed",
        reason: "malformed-result",
        released: true,
      },
      { status: "completed", value: withheld, kind: "withheld", released: true },
      { status: "invalid_request", kind: "failed", reason: "native-failed", released: true },
      { status: "invalid_request", started: true, kind: "failed", released: false },
      { status: "failed", kind: "failed", released: false },
    ];
    for (const row of rows) {
      const label = JSON.stringify(row);
      const w = world(t);
      const { running, r } = launch(w);
      if (row.started) w.bus.emit(DELEGATION_EVENTS.started, tuple(r));
      respond(w, r, row.status, row.value);
      const result = await running;
      assert.equal(result.kind, row.kind, label);
      if (row.reason) assert.ok(result.kind === "failed" && result.reason === row.reason, label);
      assert.equal(result.receipt.lock.disposition, row.released ? "released" : "retained", label);
      assert.equal(existsSync(w.lockPath), !row.released, label);
      if (!row.released) {
        const reopened = createConflictResolverEngine(w.options);
        const blocked = await reopened.resolve(w.request);
        assert.ok(blocked.kind === "failed" && blocked.reason === "lock-busy", label);
        await reopened.shutdown();
      }
      assert.equal(w.bus.count(), 1, label);
    }
  });

  test(`[${mode}] malformed correlated envelopes retain the lock; uncorrelated payloads do nothing`, async (t) => {
    const envelopes: Record<string, unknown>[] = [
      { status: "completed", runId: { output: "SECRET" } },
      { status: "completed", result: { kind: "structured" } },
      { status: "completed", result: { kind: "structured", value: completion }, usage: "output" },
    ];
    for (const [index, envelope] of envelopes.entries()) {
      const w = world(t);
      const { running, r } = launch(w);
      if (index === 0) w.bus.emit(DELEGATION_EVENTS.response, null);
      w.bus.emit(DELEGATION_EVENTS.response, { ...tuple(r), ...envelope });
      const result = await running;
      assert.ok(result.kind === "failed" && result.reason === "malformed-result");
      assert.equal(result.receipt.lock.disposition, "retained");
      assert.doesNotMatch(JSON.stringify(result), /SECRET/);
    }
  });

  test(`[${mode}] cancellation: the exact tuple once; completion inside grace releases but never promotes; grace expiry retains`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const w = world(t);
    const first = new AbortController();
    const one = launch(w, w.engine, first.signal);
    first.abort();
    assert.deepEqual(cancels(w), [tuple(one.r)]);
    respond(w, one.r);
    const released = await one.running;
    assert.ok(released.kind === "failed" && released.reason === "cancelled");
    assert.equal(released.receipt.lock.disposition, "released");
    const second = new AbortController();
    const two = launch(w, w.engine, second.signal);
    second.abort();
    assert.deepEqual(cancels(w), [tuple(one.r), tuple(two.r)]);
    t.mock.timers.tick(CANCEL_GRACE_MS);
    const retained = await two.running;
    assert.ok(retained.kind === "failed" && retained.reason === "termination-unconfirmed");
    assert.equal(retained.receipt.lock.disposition, "retained");
    assert.equal(existsSync(w.lockPath), true);
    t.mock.timers.tick(REQUEST_TIMEOUT_MS * 2);
    assert.equal(cancels(w).length, 2);
    assert.doesNotMatch(JSON.stringify([released, retained]), /SECRET/);
  });

  test(`[${mode}] no start-ack, the request deadline and an emission error each cancel with the tuple and retain`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const w = world(t);
    const one = launch(w);
    t.mock.timers.tick(START_ACK_MS);
    assert.deepEqual(cancels(w), [tuple(one.r)]);
    t.mock.timers.tick(CANCEL_GRACE_MS);
    const noAck = await one.running;
    assert.ok(noAck.kind === "failed" && noAck.reason === "termination-unconfirmed");
    assert.equal(noAck.receipt.lock.disposition, "retained");
    rmSync(w.lockPath);
    const two = launch(w);
    w.bus.emit(DELEGATION_EVENTS.started, tuple(two.r));
    t.mock.timers.tick(REQUEST_TIMEOUT_MS);
    assert.deepEqual(cancels(w), [tuple(one.r), tuple(two.r)]);
    t.mock.timers.tick(CANCEL_GRACE_MS);
    const deadline = await two.running;
    assert.ok(deadline.kind === "failed" && deadline.reason === "termination-unconfirmed");
    assert.equal(deadline.receipt.lock.disposition, "retained");
    rmSync(w.lockPath);
    w.bus.on(DELEGATION_EVENTS.request, () => {
      throw new Error("SECRET transport");
    });
    const three = launch(w);
    assert.deepEqual(cancels(w), [tuple(one.r), tuple(two.r), tuple(three.r)]);
    t.mock.timers.tick(CANCEL_GRACE_MS);
    const emission = await three.running;
    assert.ok(emission.kind === "failed" && emission.reason === "termination-unconfirmed");
    assert.equal(emission.receipt.lock.disposition, "retained");
    assert.equal(existsSync(w.lockPath), true);
    assert.doesNotMatch(JSON.stringify([noAck, deadline, emission]), /SECRET/);
    assert.equal(w.bus.count(), 2, "the request observer and the throwing handler remain");
  });

  test(`[${mode}] local refusals emit nothing and hold no lock: pre-aborted, unauthorized, invalid worktree, absent engine, throwing read-only, disposed engine`, async (t) => {
    const w = world(t);
    function refused(result: ConflictResolutionResult, reason: string) {
      assert.ok(result.kind === "failed" && result.reason === reason, JSON.stringify(result));
      assert.equal(result.receipt.termination, "not-requested");
      assert.deepEqual(result.receipt.lock, { disposition: "not-acquired" });
      assert.deepEqual(w.bus.sent, []);
      assert.equal(existsSync(w.lockPath), false);
    }
    const aborted = new AbortController();
    aborted.abort();
    refused(await w.engine.resolve(w.request, aborted.signal), "cancelled");
    const unauthorized = createConflictResolverEngine({ ...w.options, authorized: () => false });
    refused(await unauthorized.resolve(w.request), "unauthorized");
    for (const worktree of ["relative", `${w.cwd}\n`, join(w.cwd, "missing")])
      refused(await w.engine.resolve({ ...w.request, worktree }), "invalid-worktree");
    for (const enginePresent of [
      () => false,
      () => {
        throw new Error("SECRET census");
      },
    ]) {
      const absent = createConflictResolverEngine({ ...w.options, enginePresent });
      refused(await absent.resolve(w.request), "unavailable");
    }
    const throwing = createConflictResolverEngine({
      ...w.options,
      readOnly: () => {
        throw new Error("SECRET");
      },
    });
    refused(await throwing.resolve(w.request), "unauthorized");
    await w.engine.shutdown();
    refused(await w.engine.resolve(w.request), "unauthorized");
  });

  test(`[${mode}] native worktree default: read once at activation; an incompatible default refuses every dispatch naming the file and the observation`, async (t) => {
    const w = world(t);
    const path = w.configPath;
    async function succeeds(engine = createConflictResolverEngine(w.options)) {
      const { running, r } = launch(w, engine);
      respond(w, r);
      const result = await running;
      assert.equal(result.kind, successKind);
      assert.equal("nativeWorktreeConfig" in result.receipt, false);
      assert.equal(existsSync(w.lockPath), false);
    }
    async function refuses(
      engine: ReturnType<typeof createConflictResolverEngine>,
      observed: string,
    ) {
      const sent = w.bus.sent.length;
      const result = await engine.resolve(w.request);
      assert.ok(result.kind === "failed" && result.reason === "incompatible-worktree-default");
      assert.deepEqual(result.receipt.nativeWorktreeConfig, { path, observed });
      assert.deepEqual(result.receipt.lock, { disposition: "not-acquired" });
      assert.equal(w.bus.sent.length, sent, "no writer request or cancellation was emitted");
      assert.equal(existsSync(w.lockPath), false);
    }
    assert.equal(existsSync(path), false);
    await succeeds();
    for (const compatible of ["{}", '{"worktree":false}']) {
      writeFileSync(path, compatible);
      await succeeds();
    }
    for (const [content, observed] of [
      ['{"worktree":true}', "worktree=true"],
      ['{"worktree":"false"}', 'worktree="false"'],
      ["{", "unparseable JSON"],
      ["null", "not a JSON object"],
    ] as const) {
      writeFileSync(path, content);
      await refuses(createConflictResolverEngine(w.options), observed);
    }
    rmSync(path);
    mkdirSync(path);
    await refuses(createConflictResolverEngine(w.options), "unreadable (EISDIR)");
    rmSync(path, { recursive: true });
    writeFileSync(path, '{"worktree":true}');
    const stale = createConflictResolverEngine(w.options);
    writeFileSync(path, "{}");
    await refuses(stale, "worktree=true");
    await succeeds();
  });

  test(`[${mode}] PR and retained requests cannot both emit against one retained canonical Git directory`, async (t) => {
    if (mode !== "retained-continuation") return;
    const w = world(t);
    const { running, r } = launch(w);
    const competitor = createConflictResolverEngine(w.options);
    const blocked = await competitor.resolve({
      mode: "pr-rebase",
      worktree: w.cwd,
      parent: { sessionId: "other", runId: "other" },
    });
    assert.ok(blocked.kind === "failed" && blocked.reason === "lock-busy");
    assert.equal(w.requests.length, 1);
    assert.equal(existsSync(join(w.parent, ".git/perk-submit-conflict.lock")), false);
    respond(w, r);
    assert.equal((await running).kind, "continuation-ready");
    await competitor.shutdown();
  });

  test(`[${mode}] a replaced lock file fails release as lock-ownership and is left alone`, async (t) => {
    const w = world(t);
    const { running, r } = launch(w);
    writeFileSync(w.lockPath, "successor");
    respond(w, r);
    const result = await running;
    assert.ok(result.kind === "failed" && result.reason === "lock-ownership");
    assert.equal(readFileSync(w.lockPath, "utf8"), "successor");
  });
}
