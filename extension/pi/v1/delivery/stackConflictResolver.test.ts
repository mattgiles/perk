import assert from "node:assert/strict";
import { existsSync, mkdirSync, statSync, utimesSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  type ConflictResolutionRequest,
  classifyConflictResolution,
} from "../../../delivery/conflictResolution.ts";
import { decideSyncResolution } from "../../../delivery/stackConflict.ts";
import { resolverLockDir } from "../../../substrate/resolverLease.ts";
import {
  completedResolution,
  completedRetainedResolution,
  deferred,
  retainedDispatch,
} from "../../../testing/fakeConflictResolver.ts";
import { scaffoldRepo } from "../../../testing/harness.ts";
import { createStackConflictResolver } from "./stackConflictResolver.ts";
import { deliverSyncResolution, runSyncResolution, stackResolutionResult } from "./stackSync.ts";

function setup() {
  const state: Record<string, unknown> = {
    run_id: "run",
    mode: "read-write",
    conflict_resolution_attempts: 1,
  };
  const ctx = {
    cwd: "/parent",
    sessionManager: {
      getSessionId: () => "session",
      getBranch: () => [{ type: "custom", customType: "perk:workflow-state", data: state }],
    },
  } as unknown as ExtensionContext;
  const receipt = {
    nodeId: "retained-conflict" as const,
    cwd: "/retained",
    disposition: "terminal",
    termination: "confirmed" as const,
    lock: { disposition: "released" as const },
  };
  const ready = classifyConflictResolution(
    "retained-continuation",
    "completed",
    completedRetainedResolution,
    receipt,
  );
  const prepared = {
    kind: "dispatched" as const,
    dispatch: retainedDispatch("/retained"),
    attempt: 1,
    cap: 2,
  };
  return { state, ctx, receipt, ready, prepared };
}

test("undefined mode cannot bypass the effective read-only floor", async () => {
  const w = setup();
  delete w.state.mode;
  const c = createStackConflictResolver(
    {
      resolve: async () => {
        assert.fail("no writer");
      },
    },
    () => true,
  );
  c.setContext(w.ctx);
  const r = await c.run(w.ctx, async () => {
    assert.fail("no preparation");
  });
  assert.equal(r.kind, "state_error");
});

for (const invalid of [
  "unbound",
  "run",
  "session",
  "read-only",
  "planning",
  "cwd",
  "shutdown",
  "cancel",
]) {
  test(`entry authorization ${invalid} refuses before preparation; unbound cross-mode requests never authorize`, async () => {
    const w = setup();
    let preparations = 0;
    let launches = 0;
    const c = createStackConflictResolver(
      {
        resolve: async () => {
          launches++;
          return w.ready;
        },
      },
      () => false,
    );
    if (invalid !== "unbound") c.setContext(w.ctx);
    const signal = new AbortController();
    let ctx = w.ctx;
    if (invalid === "run") delete w.state.run_id;
    if (invalid === "session")
      ctx = { ...w.ctx, sessionManager: { ...w.ctx.sessionManager, getSessionId: () => "" } };
    if (invalid === "read-only") w.state.mode = "read-only";
    if (invalid === "planning") w.state.stage = "plan";
    if (invalid === "cwd") ctx = { ...w.ctx, cwd: "/elsewhere" };
    if (invalid === "shutdown") c.shutdown();
    if (invalid === "cancel") signal.abort();
    for (const mode of ["pr-rebase", "retained-continuation"] as const)
      assert.equal(
        c.authorized({
          ...w.prepared.dispatch,
          mode,
          parent: { sessionId: "session", runId: "run" },
        }),
        false,
      );
    const r = await c.run(
      ctx,
      async () => {
        preparations++;
        return w.prepared;
      },
      signal.signal,
    );
    assert.equal(r.kind, "state_error");
    assert.equal(preparations, 0);
    assert.equal(launches, 0);
  });
}

for (const change of ["tree", "shutdown", "cancel", "counter", "identity"]) {
  test(`active snapshot revoked during execution: ${change}, actual receipt preserved and no readiness`, async () => {
    const w = setup();
    const launched = deferred<ConflictResolutionRequest>();
    const finish = deferred<void>();
    const c = createStackConflictResolver(
      {
        resolve: async (request) => {
          launched.resolve(request);
          await finish.promise;
          return w.ready;
        },
      },
      () => false,
    );
    c.setContext(w.ctx);
    const signal = new AbortController();
    const running = c.run(w.ctx, async () => w.prepared, signal.signal);
    const request = await launched.promise;
    assert.equal(c.authorized(request), true);
    assert.equal(c.authorized({ ...request }), false);
    assert.equal(Object.isFrozen(request), true);
    assert.equal(Object.isFrozen(request.parent), true);
    if (request.mode === "retained-continuation") {
      w.prepared.dispatch.branch = "changed";
      assert.notEqual(request.branch, w.prepared.dispatch.branch);
    }
    const overlap = await c.run(
      w.ctx,
      async () => {
        assert.fail("overlap must not prepare");
      },
      signal.signal,
    );
    assert.equal(overlap.kind, "state_error");
    if (change === "tree") c.setContext(w.ctx);
    if (change === "shutdown") c.shutdown();
    if (change === "cancel") signal.abort();
    if (change === "counter") w.state.conflict_resolution_attempts = 0;
    if (change === "identity") w.state.run_id = "other";
    assert.equal(c.authorized(request), false);
    finish.resolve();
    const r = await running;
    assert.equal(r.kind, "executed");
    if (r.kind !== "executed") return;
    assert.ok(
      r.resolution.kind === "failed" &&
        r.resolution.reason === (change === "cancel" ? "cancelled" : "unauthorized"),
    );
    assert.equal(r.resolution.receipt, w.receipt);
    assert.equal(r.isCurrent(), false);
  });
}

test("guarded awaited status revocation is state_error before any claim or increment", async () => {
  const w = setup();
  const status = deferred<void>();
  const entered = deferred<void>();
  let writes = 0;
  let claims = 0;
  const c = createStackConflictResolver(
    {
      resolve: async () => {
        assert.fail("no launch");
      },
    },
    () => false,
  );
  c.setContext(w.ctx);
  const running = c.run(w.ctx, (isCurrent) =>
    decideSyncResolution(
      {
        readProjection: async () => {
          entered.resolve();
          await status.promise;
          if (!isCurrent()) throw new Error("retained resolver preparation unauthorized");
          return { ok: false, message: "unused" };
        },
        claim: {
          acquire: () => {
            claims++;
            return { acquired: true, token: "t" };
          },
          release() {},
        },
        attempts: {
          read: () => 0,
          write: () => {
            writes++;
            return true;
          },
        },
      },
      null,
    ),
  );
  await entered.promise;
  c.setContext(w.ctx);
  status.resolve();
  const r = await running;
  assert.ok(r.kind === "state_error" && /unauthorized/.test(r.reason));
  assert.equal(claims, 0);
  assert.equal(writes, 0);
});

for (const cancellation of [true, false]) {
  test(`production preparation catches revocation after awaited status, tool signal forwarded: ${cancellation}`, async () => {
    const w = setup();
    const entered = deferred<void>();
    const status = deferred<void>();
    const signal = new AbortController();
    let writes = 0;
    const c = createStackConflictResolver(
      {
        resolve: async () => {
          assert.fail("no writer");
        },
      },
      () => false,
    );
    c.setContext(w.ctx);
    const pi = {
      exec: async (_bin: string, argv: string[], options: { signal?: AbortSignal }) => {
        assert.deepEqual(argv, ["objective", "stack", "status", "7", "--json"]);
        assert.equal(options.signal, signal.signal);
        entered.resolve();
        await status.promise;
        return { code: 0, killed: false, stdout: '{"success":true}', stderr: "" };
      },
      appendEntry: () => {
        writes++;
      },
    } as unknown as ExtensionAPI;
    const running = runSyncResolution(pi, w.ctx, "7", null, c, signal.signal);
    await entered.promise;
    if (cancellation) signal.abort();
    else c.setContext(w.ctx);
    status.resolve();
    const r = await running;
    assert.ok(
      r.kind === "state_error" && r.reason.includes(cancellation ? "cancelled" : "unauthorized"),
    );
    assert.equal(writes, 0);
  });
}

for (const revokeAt of ["microtask-abort", "microtask-tree", "increment"]) {
  test(`production preparation rechecks at synchronous mutation ports: ${revokeAt}`, async () => {
    const w = setup();
    w.state.conflict_resolution_attempts = 0;
    const cwd = scaffoldRepo();
    const claimParent = join(cwd, "sync-continuations");
    mkdirSync(claimParent);
    const manifest = join(claimParent, "01LIN.json");
    const claimDir = resolverLockDir(manifest);
    // Even acquire-then-release changes this deliberately old mtime: rollback cannot hide a write.
    utimesSync(claimParent, new Date(1000), new Date(1000));
    const originalMtime = statSync(claimParent).mtimeMs;
    const dispatch = retainedDispatch(join(cwd, "sync-01ARZ3NDEKTSV4RRFFQ69G5FAV"));
    const projection = {
      success: true,
      objective: { id: dispatch.objective },
      train: {
        delivery_lineage: "01LIN",
        layers: [{ node_id: dispatch.node, branch: dispatch.branch, pr_number: dispatch.pr }],
      },
      continuation: {
        operation_id: dispatch.operationId,
        conflict_node_id: dispatch.node,
        worktree_path: dispatch.worktree,
        manifest_path: manifest,
        parseable: true,
        targets_contained: true,
      },
    };
    let afterStatus = false;
    let queued = false;
    let revoked = false;
    let incrementGuardObserved = false;
    let writes = 0;
    let launches = 0;
    const signal = new AbortController();
    const ctx: ExtensionContext = {
      ...w.ctx,
      cwd,
      sessionManager: {
        ...w.ctx.sessionManager,
        getBranch() {
          if (afterStatus && !queued && revokeAt !== "increment") {
            queued = true;
            queueMicrotask(() => {
              revoked = true;
              if (revokeAt === "microtask-abort") signal.abort();
              else c.setContext(ctx);
            });
          }
          return w.ctx.sessionManager.getBranch();
        },
      },
    };
    const c = createStackConflictResolver(
      {
        resolve: async () => {
          launches++;
          return w.ready;
        },
      },
      () => {
        if (revokeAt === "increment" && existsSync(claimDir)) incrementGuardObserved = true;
        return incrementGuardObserved;
      },
    );
    c.setContext(ctx);
    const pi = {
      exec: async () => {
        afterStatus = true;
        return { code: 0, killed: false, stdout: JSON.stringify(projection), stderr: "" };
      },
      appendEntry: (_type: string, data: object) => {
        writes++;
        Object.assign(w.state, data);
      },
    } as unknown as ExtensionAPI;
    const r = await runSyncResolution(pi, ctx, "7", null, c, signal.signal);
    assert.ok(
      r.kind === "state_error" &&
        r.reason.includes(revokeAt === "microtask-abort" ? "cancelled" : "unauthorized"),
    );
    assert.equal(writes, 0);
    assert.equal(launches, 0);
    assert.equal(w.state.conflict_resolution_attempts, 0);
    assert.equal(existsSync(claimDir), false);
    if (revokeAt === "increment") {
      assert.equal(incrementGuardObserved, true);
      assert.notEqual(
        statSync(claimParent).mtimeMs,
        originalMtime,
        "this call's acquired claim was released",
      );
    } else {
      assert.equal(revoked, true);
      assert.equal(
        statSync(claimParent).mtimeMs,
        originalMtime,
        "no claim acquisition, even transiently",
      );
    }
  });
}

test("stack consumer refuses a PR-shaped success and never authorizes it as retained", async () => {
  const w = setup();
  const c = createStackConflictResolver(
    {
      resolve: async () =>
        classifyConflictResolution("pr-rebase", "completed", completedResolution, w.receipt),
    },
    () => false,
  );
  c.setContext(w.ctx);
  const r = await c.run(w.ctx, async () => w.prepared);
  assert.ok(
    r.kind === "executed" &&
      r.resolution.kind === "failed" &&
      r.resolution.reason === "malformed-result",
  );
});

for (const disposition of ["ready", "withheld", "failed"])
  for (const deliveryFailure of ["guidance", "suffix", "send"]) {
    test(`fallback preserves complete settled result: ${disposition}, ${deliveryFailure}`, () => {
      const w = setup();
      const resolution =
        disposition === "ready"
          ? w.ready
          : classifyConflictResolution(
              "retained-continuation",
              disposition === "failed" ? "failed" : "completed",
              {
                ...completedRetainedResolution,
                outcome: "verification-failed",
                verification: "failed",
              },
              w.receipt,
            );
      const outcome = {
        ...w.prepared,
        kind: "executed" as const,
        resolution,
        isCurrent: () => true,
      };
      const result = stackResolutionResult(outcome);
      result.terminate = false;
      const baseline = structuredClone(result);
      const boom = (): never => {
        throw Error("SECRET");
      };
      const pi = { sendUserMessage: boom } as unknown as ExtensionAPI;
      const ctx = {
        ...w.ctx,
        hasUI: true,
        isIdle: () => true,
        ui: { notify: boom },
      } as unknown as ExtensionContext;
      deliverSyncResolution(
        pi,
        ctx,
        outcome,
        result,
        deliveryFailure === "guidance" ? boom : () => "guidance",
        deliveryFailure === "suffix" ? boom : () => "",
      );
      assert.deepEqual(result.details, baseline.details);
      assert.deepEqual(result.content[0], baseline.content[0]);
      assert.equal(result.terminate, baseline.terminate);
      assert.equal(result.content.length, 2);
      assert.equal(resolution.receipt, w.receipt);
      assert.doesNotMatch(JSON.stringify(result), /SECRET/);
    });
  }

for (const change of ["none", "render", "idle", "send", "throw-check"])
  for (const idle of [true, false]) {
    test(`delivery boundary preserves classification while suppressing stale UI: ${change}, idle=${idle}`, async () => {
      const w = setup();
      const c = createStackConflictResolver({ resolve: async () => w.ready }, () => false);
      c.setContext(w.ctx);
      const outcome = await c.run(w.ctx, async () => w.prepared);
      assert.equal(outcome.kind, "executed");
      if (outcome.kind !== "executed") return;
      const result = stackResolutionResult(outcome);
      const before = JSON.stringify(result);
      let sends = 0;
      let reports = 0;
      let options: unknown;
      const pi = {
        sendUserMessage: (_text: string, opts: unknown) => {
          sends++;
          options = opts;
          if (change === "send") {
            c.setContext(w.ctx);
            throw Error("SECRET");
          }
        },
      } as unknown as ExtensionAPI;
      const ctx = {
        ...w.ctx,
        hasUI: true,
        isIdle: () => {
          if (change === "idle") c.setContext(w.ctx);
          return idle;
        },
        ui: {
          notify: () => {
            reports++;
          },
        },
      } as unknown as ExtensionContext;
      if (change === "throw-check")
        outcome.isCurrent = () => {
          throw Error("SECRET");
        };
      deliverSyncResolution(
        pi,
        ctx,
        outcome,
        result,
        () => {
          if (change === "render") c.setContext(w.ctx);
          return "guidance";
        },
        () => "",
      );
      assert.equal(result.details.ok, true);
      assert.equal(sends, change === "none" || change === "send" ? 1 : 0);
      assert.equal(reports, 0);
      if (change === "none")
        assert.deepEqual(options, idle ? undefined : { deliverAs: "followUp" });
      if (change === "send" || change === "throw-check") {
        assert.equal(result.content.length, 2);
        assert.match(result.content[1]?.text ?? "", /delivery is unconfirmed/);
        if (change === "throw-check")
          assert.match(result.content[1]?.text ?? "", /Secondary current-context check/);
        result.content.pop();
      }
      assert.equal(JSON.stringify(result), before);
    });
  }
