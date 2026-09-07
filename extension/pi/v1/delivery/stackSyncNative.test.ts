// Registered-tool native-path coverage. Consent is scripted parent action, not model evidence.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ConflictResolutionResult } from "../../../delivery/conflictResolution.ts";
import { resolverLockDir } from "../../../substrate/resolverLease.ts";
import {
  completedResolution,
  completedRetainedResolution,
  deferred,
  fakeConflictResolver,
  RETAINED_OPERATION,
} from "../../../testing/fakeConflictResolver.ts";
import { gitInit, loadPerkSession, scaffoldRepo, spyInjections } from "../../../testing/harness.ts";
import { DELEGATION_EVENTS } from "./conflictResolverEngine.ts";
import type { StackResolutionDelivery } from "./stackSync.ts";

const conflict = {
  success: false,
  error_type: "rebase_conflict",
  message: "the candidate rebase for layer 2.1 ('plan-91' onto abc) hit a conflict",
};
async function setup(
  options: {
    value?: unknown;
    status?: string;
    continuation?: object;
    model?: string;
    delivery?: StackResolutionDelivery;
    pausePreflight?: () => Promise<void>;
    script?: Parameters<typeof fakeConflictResolver>[1];
  } = {},
) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  gitInit(cwd, { dirty: false });
  const worktree = join(cwd, `sync-${RETAINED_OPERATION}`);
  execFileSync("git", ["-C", cwd, "worktree", "add", "--detach", worktree], {
    timeout: 30_000,
    stdio: "ignore",
  });
  mkdirSync(join(cwd, "sync-continuations"));
  const manifest = join(cwd, "sync-continuations/01LIN.json");
  const status = {
    success: true,
    objective: { id: "7", url: "u/7", redirected_from: "old" },
    train: {
      base: "main",
      delivery_lineage: "01LIN",
      published_prefix_len: 1,
      layers: [{ node_id: "2.1", branch: "plan-91", pr_number: 91, publication: "published" }],
    },
    continuation: {
      operation_id: RETAINED_OPERATION,
      conflict_node_id: "2.1",
      adopted_node: null,
      created: "2026-01-01",
      worktree_path: worktree,
      manifest_path: manifest,
      parseable: true,
      targets_contained: true,
      ...options.continuation,
    },
    orphaned_residue: { observed: true, reason: null, worktrees: [], refs: [] },
  };
  const statusFile = join(cwd, "status.json");
  const syncFile = join(cwd, "sync.json");
  const argv = join(cwd, "argv.txt");
  writeFileSync(statusFile, JSON.stringify(status));
  writeFileSync(syncFile, JSON.stringify(conflict));
  const bin = join(cwd, "fake-stack-perk.sh");
  writeFileSync(
    bin,
    `#!/usr/bin/env bash\nprintf '%s\\n' "$*" >> '${argv}'\ncase "$3" in\nstatus) cat '${statusFile}';;\nsync) cat '${syncFile}';;\n*) exit 2;;\nesac\n`,
  );
  chmodSync(bin, 0o755);
  if (options.model !== undefined)
    writeFileSync(
      join(cwd, ".perk/config.toml"),
      `[models.subagents]\nconflict-resolver = "${options.model}"\n`,
    );
  const engine = fakeConflictResolver(
    worktree,
    options.script ??
      ((bus, r) => {
        bus.emit(DELEGATION_EVENTS.response, {
          requestId: r.requestId,
          ownerRunId: r.ownerRunId,
          nodeId: r.nodeId,
          status: options.status ?? "completed",
          runId: "native-retained",
          result: {
            kind: "structured",
            value: "value" in options ? options.value : completedRetainedResolution,
          },
        });
      }),
  );
  const preflight = engine.resolverEngine.preflight;
  engine.resolverEngine.preflight = async (input) => {
    const p = await preflight(input);
    await options.pausePreflight?.();
    return p;
  };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    resolverEngine: engine.resolverEngine,
    stackResolutionDelivery: options.delivery,
    extraExtensions: [engine.extension],
  });
  const injected = spyInjections(h);
  const lock = join(
    execFileSync("git", ["-C", worktree, "rev-parse", "--absolute-git-dir"], {
      encoding: "utf8",
      timeout: 30_000,
    }).trim(),
    "perk-submit-conflict.lock",
  );
  return {
    cwd,
    worktree,
    manifest,
    status,
    statusFile,
    syncFile,
    h,
    engine,
    injected,
    lock,
    calls: () => (existsSync(argv) ? readFileSync(argv, "utf8").trim().split("\n") : []),
    append: (value: object) =>
      h.session.sessionManager.appendCustomEntry("perk:workflow-state", value),
  };
}
function details(result: { details: unknown }) {
  return result.details as {
    ok: boolean;
    error_type?: string;
    objective?: string;
    resolution?: ConflictResolutionResult;
  };
}

for (const params of [
  { objective: "old" },
  { objective: "old", continue: true },
  { objective: "old", resolve: true },
]) {
  test(`awaited native completion, status-only explicit resolve, no continuation without NEW consent: ${JSON.stringify(params)}`, async () => {
    const w = await setup();
    try {
      const result = await w.h.invokeTool("objective_stack_sync", params);
      assert.equal(details(result).ok, "resolve" in params);
      if (!("resolve" in params)) {
        assert.deepEqual(result.details, {
          ok: false,
          error: conflict.message,
          error_type: "rebase_conflict",
        });
        assert.equal(result.content[0]?.text, `objective_stack_sync failed: ${conflict.message}`);
      } else {
        assert.equal(details(result).objective, "7");
        assert.equal(details(result).resolution?.kind, "continuation-ready");
      }
      assert.deepEqual(
        w.calls(),
        "resolve" in params
          ? ["objective stack status old --json"]
          : [
              `objective stack sync old ${"continue" in params ? "--continue " : ""}--yes --json`,
              "objective stack status old --json",
            ],
      );
      assert.equal(w.engine.requests.length, 1);
      assert.equal(w.engine.requests[0]?.cwd, w.worktree);
      assert.equal(w.engine.preflights[0]?.cwd, w.worktree);
      assert.equal(w.engine.requests[0]?.nodeId, "retained-conflict");
      assert.match(String(w.engine.requests[0]?.task), /\nRETAINED-CONTINUATION SENTINEL:/);
      assert.equal(w.injected.length, 1);
      assert.match(w.injected[0] ?? "", /NEW explicit human approval/);
      assert.match(w.injected[0] ?? "", /objective: 7, continue: true/);
      assert.doesNotMatch(w.injected[0] ?? "", /workflowScript|RETAINED-CONTINUATION SENTINEL/);
      assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
      assert.equal(existsSync(resolverLockDir(w.manifest)), true);
      assert.equal(existsSync(w.lock), false);
      assert.equal(existsSync(join(w.cwd, ".git/perk-submit-conflict.lock")), false);
      assert.notEqual(result.terminate, true);
      // No approval means no action. A separately scripted decline never resets the episode.
      const before = [...w.calls()];
      assert.deepEqual(w.calls(), before);
      writeFileSync(w.syncFile, JSON.stringify({ success: true, declined: true }));
      await w.h.invokeTool("objective_stack_sync", { objective: "7", continue: true });
      assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
      assert.equal(w.engine.requests.length, 1);
    } finally {
      w.h.dispose();
    }
  });
}

for (const value of [
  { ...completedRetainedResolution, outcome: "verification-failed", verification: "failed" },
  ...["missing worktree", "no rebase in progress", "ambiguous task", "context-fetch failure"].map(
    (summary) => ({
      ...completedRetainedResolution,
      outcome: "stopped-before-mutation",
      verification: "not-run",
      summary,
    }),
  ),
  { ...completedRetainedResolution, outcome: "unresolvable-conflict", verification: "not-run" },
  { ...completedRetainedResolution, outcome: "aborted" },
  { ...completedRetainedResolution, verification: "not-run" },
  completedResolution,
  "completed",
  null,
]) {
  test(`registered retained withholding never offers continuation: ${JSON.stringify(value)}`, async () => {
    const w = await setup({ value });
    try {
      const r = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
      assert.equal(details(r).ok, false);
      assert.notEqual(details(r).resolution?.kind, "continuation-ready");
      assert.match(w.injected[0] ?? "", /Continuation offer withheld/);
      assert.doesNotMatch(w.injected[0] ?? "", /objective: 7, continue: true/);
      assert.equal(existsSync(w.lock), false);
      assert.equal(existsSync(resolverLockDir(w.manifest)), true);
      assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
      assert.deepEqual(w.calls(), ["objective stack status 7 --json"]);
    } finally {
      w.h.dispose();
    }
  });
}

for (const continue_ of [false, true])
  for (const value of [
    { ...completedRetainedResolution, outcome: "verification-failed", verification: "failed" },
    { ...completedRetainedResolution, outcome: "unresolvable-conflict", verification: "not-run" },
    { ...completedRetainedResolution, outcome: "stopped-before-mutation", verification: "not-run" },
    "completed",
    completedResolution,
  ]) {
    test(`automatic withholding preserves refusal and delivers no offer: continue=${continue_}, ${JSON.stringify(value)}`, async () => {
      const w = await setup({ value });
      try {
        const r = await w.h.invokeTool("objective_stack_sync", {
          objective: "7",
          ...(continue_ ? { continue: true } : {}),
        });
        assert.deepEqual(r.details, {
          ok: false,
          error: conflict.message,
          error_type: "rebase_conflict",
        });
        assert.equal(r.content.length, 1);
        assert.equal(w.injected.length, 1);
        assert.match(w.injected[0] ?? "", /Continuation offer withheld/);
        assert.doesNotMatch(w.injected[0] ?? "", /NEW explicit human approval/);
        assert.equal(w.calls().length, 2);
        assert.equal(w.engine.requests.length, 1);
      } finally {
        w.h.dispose();
      }
    });
  }

for (const change of ["cancel", "tree", "replacement"]) {
  test(`registered revocation during native execution preserves actual receipt: ${change}`, async () => {
    const started = deferred<() => void>();
    const signal = new AbortController();
    const w = await setup({
      script: (bus, request) => {
        bus.emit(DELEGATION_EVENTS.started, request);
        started.resolve(() =>
          bus.emit(DELEGATION_EVENTS.response, {
            requestId: request.requestId,
            ownerRunId: request.ownerRunId,
            nodeId: request.nodeId,
            status: "completed",
            runId: "actual-completed-run",
            result: { kind: "structured", value: completedRetainedResolution },
          }),
        );
      },
    });
    try {
      let notifications = 0;
      const running = w.h.invokeTool(
        "objective_stack_sync",
        { objective: "7", resolve: true },
        {
          signal: signal.signal,
          ui: {
            notify: () => {
              notifications++;
            },
          },
        },
      );
      const finish = await started.promise;
      if (change === "cancel") signal.abort();
      else if (change === "tree")
        await w.h.emitLifecycle({ type: "session_tree", newLeafId: "same", oldLeafId: "same" });
      else await w.h.emitSessionStart();
      finish();
      const r = await running;
      const resolution = details(r).resolution;
      assert.ok(
        resolution?.kind === "failed" &&
          resolution.reason === (change === "cancel" ? "cancelled" : "unauthorized"),
      );
      assert.equal(resolution.receipt.runId, "actual-completed-run");
      assert.equal(resolution.receipt.nativeStatus, "completed");
      assert.equal(resolution.receipt.lock.disposition, "released");
      assert.equal(notifications, 0);
      assert.deepEqual(w.injected, []);
      assert.equal(w.calls().length, 1);
      assert.equal(w.engine.requests.length, 1);
      assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
      assert.equal(existsSync(resolverLockDir(w.manifest)), true);
    } finally {
      w.h.dispose();
    }
  });
}

for (const model of [undefined, "offline/override", "inherit"]) {
  test(`retained configured/unset/inherit model is forwarded from parent at invocation: ${model}`, async () => {
    const w = await setup({ model });
    try {
      await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
      assert.equal(w.engine.requests[0]?.model, model);
      assert.equal(w.engine.preflights[0]?.model, model);
    } finally {
      w.h.dispose();
    }
  });
}

for (const flags of [
  { dry_run: true },
  { abort: true },
  { node: "2.1", confirm: true },
  { node: "2.1", dry_run: true },
]) {
  test(`registered exclusions perform zero resolution/status/claim/increment: ${JSON.stringify(flags)}`, async () => {
    const w = await setup();
    try {
      const tool = "node" in flags ? "objective_stack_adopt" : "objective_stack_sync";
      const r = await w.h.invokeTool(tool, { objective: "7", ...flags });
      assert.equal(details(r).error_type, "rebase_conflict");
      assert.equal(w.calls().length, 1);
      assert.match(w.calls()[0] ?? "", /objective stack sync/);
      assert.deepEqual(w.engine.requests, []);
      assert.deepEqual(w.engine.preflights, []);
      assert.deepEqual(w.injected, []);
      assert.equal(existsSync(resolverLockDir(w.manifest)), false);
      assert.equal(w.h.workflowState().conflict_resolution_attempts, undefined);
    } finally {
      w.h.dispose();
    }
  });
}

test("same operation new conflict follows approved continuation, fresh layer, next capped attempt; mismatch is report-only", async () => {
  const w = await setup();
  try {
    await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    w.status.train.layers[0] = {
      node_id: "2.2",
      branch: "plan-92",
      pr_number: 92,
      publication: "published",
    };
    w.status.continuation.conflict_node_id = "2.2";
    writeFileSync(w.statusFile, JSON.stringify(w.status));
    writeFileSync(
      w.syncFile,
      JSON.stringify({ ...conflict, message: "the candidate rebase for layer 2.2 hit a conflict" }),
    );
    await w.h.invokeTool("objective_stack_sync", { objective: "7", continue: true });
    assert.equal(w.engine.requests.length, 2);
    assert.match(String(w.engine.requests[1]?.task), /node 2.2, branch plan-92, PR #92/);
    assert.equal(w.h.workflowState().conflict_resolution_attempts, 2);
    const capped = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    assert.equal(details(capped).error_type, "attempt_cap");
    assert.equal(details(capped).resolution, undefined);
    writeFileSync(
      w.syncFile,
      JSON.stringify({
        ...conflict,
        message: "the candidate rebase for layer 2.3 hit a conflict; manifest rewrite failed",
      }),
    );
    await w.h.invokeTool("objective_stack_sync", { objective: "7", continue: true });
    assert.equal(w.engine.requests.length, 2);
    assert.ok(w.h.notifies.some((s) => /stale snapshot/.test(s)));
  } finally {
    w.h.dispose();
  }
});

for (const failure of ["uncontained", "counter-dropped", "counter-thrown", "preflight", "native"]) {
  test(`preparation and execution failures keep independent claim/counter lifetimes: ${failure}`, async () => {
    const w = await setup(
      failure === "uncontained"
        ? { continuation: { targets_contained: false } }
        : failure === "native"
          ? { status: "failed" }
          : {},
    );
    try {
      if (failure.startsWith("counter")) {
        const sm = w.h.session.sessionManager;
        const original = sm.appendCustomEntry.bind(sm);
        sm.appendCustomEntry = (type, data) => {
          if (type !== "perk:workflow-state") return original(type, data);
          if (failure === "counter-thrown") throw new Error("counter write failed");
          return "dropped";
        };
      }
      if (failure === "preflight") {
        // Public profile evidence requires this exact canonical file to exist.
        rmSync(join(w.worktree, ".pi/agents/perk/conflict-resolver.md"));
      }
      const r = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
      assert.equal(details(r).ok, false);
      assert.equal(
        existsSync(resolverLockDir(w.manifest)),
        failure === "native" || failure === "preflight",
      );
      assert.equal(existsSync(w.lock), failure === "native");
      assert.equal(w.engine.requests.length, failure === "native" ? 1 : 0);
      if (failure === "native") {
        // Same-PID session reacquisition and a counter reset never bypass execution exclusion.
        w.append({ conflict_resolution_attempts: 0 });
        const next = await w.h.invokeTool("objective_stack_sync", {
          objective: "7",
          resolve: true,
        });
        assert.equal(details(next).error_type, "lock-busy");
        assert.equal(w.engine.requests.length, 1);
      }
    } finally {
      w.h.dispose();
    }
  });
}

test("registered busy session claim refuses before native preflight and increment", async () => {
  const w = await setup();
  try {
    mkdirSync(resolverLockDir(w.manifest));
    const r = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    assert.equal(details(r).error_type, "resolver_busy");
    assert.equal(details(r).resolution, undefined);
    assert.deepEqual(w.engine.preflights, []);
    assert.equal(w.h.workflowState().conflict_resolution_attempts, undefined);
    assert.equal(existsSync(w.lock), false);
  } finally {
    w.h.dispose();
  }
});

test("failed clean-reset write warns but preserves cold completion; clean continue resets", async () => {
  const w = await setup();
  try {
    w.append({ conflict_resolution_attempts: 2 });
    writeFileSync(w.syncFile, JSON.stringify({ success: true, continued: true }));
    const sm = w.h.session.sessionManager;
    const original = sm.appendCustomEntry.bind(sm);
    sm.appendCustomEntry = (type, data) =>
      type === "perk:workflow-state" ? "dropped" : original(type, data);
    const r = await w.h.invokeTool("objective_stack_sync", { objective: "7", continue: true });
    assert.equal(details(r).ok, true);
    assert.ok(w.h.notifies.some((s) => /conflict budget reset failed/.test(s)));
    assert.equal(w.h.workflowState().conflict_resolution_attempts, 2);
    sm.appendCustomEntry = original;
    await w.h.invokeTool("objective_stack_sync", { objective: "7", continue: true });
    assert.equal(w.h.workflowState().conflict_resolution_attempts, 0);
    assert.deepEqual(w.engine.preflights, []);
  } finally {
    w.h.dispose();
  }
});

for (const reclamation of ["changed-operation", "dead-holder", "reload"]) {
  test(`session-claim reclamation never bypasses execution exclusion: ${reclamation}`, async () => {
    const w = await setup({ status: "failed" });
    try {
      await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
      const file = join(resolverLockDir(w.manifest), "lease.json");
      const lease = JSON.parse(readFileSync(file, "utf8"));
      if (reclamation === "changed-operation") lease.operation_id = "old";
      if (reclamation === "dead-holder") lease.pid = 2147483647;
      writeFileSync(file, JSON.stringify(lease));
      if (reclamation === "reload") await w.h.reload();
      const r = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
      assert.equal(details(r).error_type, "lock-busy");
      assert.equal(w.engine.requests.length, 1);
      assert.equal(w.h.workflowState().conflict_resolution_attempts, 2);
      assert.equal(existsSync(w.lock), true);
    } finally {
      w.h.dispose();
    }
  });
}

for (const change of ["counter", "identity", "planning", "read-only", "tree", "cancel"]) {
  test(`native preflight revalidates ${change}; overlap refuses before second status`, async () => {
    const entered = deferred<void>();
    const resume = deferred<void>();
    const signal = new AbortController();
    const w = await setup({
      pausePreflight: async () => {
        entered.resolve();
        await resume.promise;
      },
    });
    try {
      const running = w.h.invokeTool(
        "objective_stack_sync",
        { objective: "7", resolve: true },
        { signal: signal.signal },
      );
      await entered.promise;
      const overlap = await w.h.invokeTool("objective_stack_sync", {
        objective: "7",
        resolve: true,
      });
      assert.equal(details(overlap).error_type, "state_error");
      assert.equal(w.calls().length, 1);
      if (change === "tree")
        await w.h.emitLifecycle({ type: "session_tree", newLeafId: "same", oldLeafId: "same" });
      else if (change === "cancel") signal.abort();
      else
        w.append(
          change === "counter"
            ? { conflict_resolution_attempts: 0 }
            : change === "identity"
              ? { run_id: "different" }
              : change === "planning"
                ? { stage: "plan" }
                : { mode: "read-only" },
        );
      resume.resolve();
      const r = await running;
      assert.equal(details(r).ok, false);
      assert.deepEqual(w.engine.requests, []);
      assert.deepEqual(w.injected, []);
      assert.equal(existsSync(resolverLockDir(w.manifest)), true);
      assert.equal(existsSync(w.lock), false);
    } finally {
      resume.resolve();
      w.h.dispose();
    }
  });
}

for (const explicit of [true, false])
  for (const outcome of ["completed", "withheld", "failed"])
    for (const failure of ["guidance", "suffix", "send", "queued-send", "warning"]) {
      test(`result-preserving delivery failure explicit=${explicit}, outcome=${outcome}, failure=${failure}`, async () => {
        const boom = (): never => {
          throw new Error("SECRET task/transcript");
        };
        const w = await setup({
          value:
            outcome === "withheld"
              ? {
                  ...completedRetainedResolution,
                  outcome: "verification-failed",
                  verification: "failed",
                }
              : completedRetainedResolution,
          status: outcome === "failed" ? "failed" : "completed",
          delivery:
            failure === "guidance"
              ? { guidance: boom }
              : failure === "suffix"
                ? { suffix: boom }
                : {},
        });
        let sends = 0;
        if (["send", "queued-send", "warning"].includes(failure)) {
          w.h.session.sendUserMessage = () => {
            sends++;
            if (failure === "queued-send") w.injected.push("queued");
            return boom();
          };
        }
        let warnings = 0;
        try {
          const r = await w.h.invokeTool(
            "objective_stack_sync",
            { objective: "7", ...(explicit ? { resolve: true } : {}) },
            {
              ui: {
                notify: (_message: string, severity: string) => {
                  if (severity === "warning") {
                    warnings++;
                    if (failure === "warning") boom();
                  }
                },
              },
            },
          );
          assert.equal(details(r).ok, explicit && outcome === "completed");
          if (explicit) {
            assert.equal(details(r).objective, "7");
            assert.equal(
              details(r).resolution?.kind,
              outcome === "completed" ? "continuation-ready" : outcome,
            );
          } else {
            assert.deepEqual(r.details, {
              ok: false,
              error: conflict.message,
              error_type: "rebase_conflict",
            });
            assert.equal(r.content[0]?.text, `objective_stack_sync failed: ${conflict.message}`);
          }
          assert.equal(r.content.length, 2);
          assert.match(
            r.content[1]?.text ?? "",
            /delivery is unconfirmed.*may already have queued/,
          );
          assert.match(r.content[1]?.text ?? "", /Stop for human direction/);
          assert.match(r.content[1]?.text ?? "", /Output-free receipt/);
          if (outcome !== "failed")
            assert.match(r.content[1]?.text ?? "", /Untrusted resolver DATA/);
          if (failure === "warning")
            assert.match(r.content[1]?.text ?? "", /warning reporting failed/);
          assert.doesNotMatch(JSON.stringify(r), /SECRET task\/transcript/);
          assert.equal(warnings, 1);
          assert.equal(sends, ["send", "queued-send", "warning"].includes(failure) ? 1 : 0);
          assert.equal(w.engine.requests.length, 1);
          assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
          assert.equal(existsSync(w.lock), outcome === "failed");
          assert.equal(existsSync(resolverLockDir(w.manifest)), true);
          assert.notEqual(r.terminate, true);
          assert.equal(w.calls().length, explicit ? 1 : 2);
        } finally {
          w.h.dispose();
        }
      });
    }
