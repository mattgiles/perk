import assert from "node:assert/strict";
import { existsSync, mkdirSync, statSync, utimesSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  type ConflictResolutionRequest,
  classifyConflictResolution,
} from "../../../delivery/conflictResolution.ts";
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

test("entry authorization: an undefined mode is writable unless the effective floor is on; every invalid entry refuses before preparation and never authorizes either mode", async () => {
  for (const floor of [false, true]) {
    const w = setup();
    delete w.state.mode;
    let launches = 0;
    const c = createStackConflictResolver(
      {
        resolve: async () => {
          launches++;
          return w.ready;
        },
      },
      () => floor,
    );
    c.setContext(w.ctx);
    const r = await c.run(w.ctx, async () => w.prepared);
    assert.equal(r.kind, floor ? "state_error" : "executed");
    assert.equal(launches, floor ? 0 : 1);
  }
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
        `${invalid}: ${mode}`,
      );
    const r = await c.run(
      ctx,
      async () => {
        preparations++;
        return w.prepared;
      },
      signal.signal,
    );
    assert.equal(r.kind, "state_error", invalid);
    assert.equal(preparations, 0, invalid);
    assert.equal(launches, 0, invalid);
  }
});

test("revocation during execution: overlap refuses; a context change settles unauthorized with the actual receipt preserved", async () => {
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
  const running = c.run(w.ctx, async () => w.prepared);
  const request = await launched.promise;
  assert.equal(c.authorized(request), true);
  assert.equal(c.authorized({ ...request }), false);
  assert.equal(Object.isFrozen(request), true);
  assert.equal(Object.isFrozen(request.parent), true);
  if (request.mode === "retained-continuation") {
    w.prepared.dispatch.branch = "changed";
    assert.notEqual(request.branch, w.prepared.dispatch.branch);
  }
  const overlap = await c.run(w.ctx, async () => {
    assert.fail("overlap must not prepare");
  });
  assert.equal(overlap.kind, "state_error");
  c.setContext(w.ctx);
  assert.equal(c.authorized(request), false);
  finish.resolve();
  const r = await running;
  assert.equal(r.kind, "executed");
  if (r.kind !== "executed") return;
  assert.ok(r.resolution.kind === "failed" && r.resolution.reason === "unauthorized");
  assert.equal(r.resolution.receipt, w.receipt);
  assert.equal(r.isCurrent(), false);
});

test("preparation rechecks at the synchronous mutation ports: a revocation queued after the status read acquires no claim and writes no counter", async () => {
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
  let writes = 0;
  let launches = 0;
  const ctx: ExtensionContext = {
    ...w.ctx,
    cwd,
    sessionManager: {
      ...w.ctx.sessionManager,
      getBranch() {
        if (afterStatus && !queued) {
          queued = true;
          queueMicrotask(() => {
            revoked = true;
            c.setContext(ctx);
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
    () => false,
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
  const r = await runSyncResolution(pi, ctx, "7", null, c, new AbortController().signal);
  assert.ok(r.kind === "state_error" && r.reason.includes("unauthorized"));
  assert.equal(revoked, true);
  assert.equal(writes, 0);
  assert.equal(launches, 0);
  assert.equal(w.state.conflict_resolution_attempts, 0);
  assert.equal(existsSync(claimDir), false);
  assert.equal(
    statSync(claimParent).mtimeMs,
    originalMtime,
    "no claim acquisition, even transiently",
  );
});

test("the stack consumer refuses a PR-shaped success as malformed-result", async () => {
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

test("a failed post-result send preserves the settled continuation-ready result and appends one delivery-unconfirmed diagnostic", () => {
  const w = setup();
  const outcome = {
    ...w.prepared,
    kind: "executed" as const,
    resolution: w.ready,
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
    () => "guidance",
    () => "",
  );
  assert.deepEqual(result.details, baseline.details);
  assert.deepEqual(result.content[0], baseline.content[0]);
  assert.equal(result.terminate, baseline.terminate);
  assert.equal(result.content.length, 2);
  assert.match(result.content[1]?.text ?? "", /delivery is unconfirmed/);
  assert.equal(w.ready.receipt, w.receipt);
  assert.doesNotMatch(JSON.stringify(result), /SECRET/);
});
