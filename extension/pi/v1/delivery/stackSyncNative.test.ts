// Registered-tool native-path coverage. Consent is scripted parent action, not model evidence.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ConflictResolutionResult } from "../../../delivery/conflictResolution.ts";
import { resolverLockDir } from "../../../substrate/resolverLease.ts";
import {
  completedRetainedResolution,
  fakeConflictResolver,
  RETAINED_OPERATION,
} from "../../../testing/fakeConflictResolver.ts";
import { gitInit, loadPerkSession, scaffoldRepo, spyInjections } from "../../../testing/harness.ts";
import { DELEGATION_EVENTS } from "./conflictResolverEngine.ts";

const conflict = {
  success: false,
  error_type: "rebase_conflict",
  message: "the candidate rebase for layer 2.1 ('plan-91' onto abc) hit a conflict",
};
async function setup(
  options: {
    value?: unknown;
    status?: string;
    model?: string;
    nativeConfig?: string;
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
  // Planted BEFORE the session loads: the engine reads the file once at activation.
  if (options.nativeConfig !== undefined)
    writeFileSync(engine.resolverEngine.configPath, options.nativeConfig);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    resolverEngine: engine.resolverEngine,
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

test("retained dispatch: one public request at the retained worktree; the offer needs NEW consent; a second conflict continues the episode; the third is capped", async () => {
  const w = await setup({ model: "offline/override" });
  try {
    const result = await w.h.invokeTool("objective_stack_sync", {
      objective: "old",
      resolve: true,
    });
    assert.equal(details(result).ok, true);
    assert.equal(details(result).objective, "7");
    assert.equal(details(result).resolution?.kind, "continuation-ready");
    assert.notEqual(result.terminate, true);
    assert.deepEqual(w.calls(), ["objective stack status old --json"]);
    assert.equal(w.engine.requests.length, 1);
    const request = w.engine.requests[0] ?? {};
    assert.equal(request.cwd, w.worktree);
    assert.equal(request.nodeId, "retained-conflict");
    assert.equal(request.agent, "perk.conflict-resolver");
    assert.equal(request.model, "offline/override");
    assert.match(String(request.task), /\nRETAINED-CONTINUATION SENTINEL:/);
    assert.equal(Object.hasOwn(request, "extensionBindings"), false);
    assert.equal(w.injected.length, 1);
    assert.match(w.injected[0] ?? "", /NEW explicit human approval/);
    assert.match(w.injected[0] ?? "", /objective: 7, continue: true/);
    assert.doesNotMatch(w.injected[0] ?? "", /workflowScript|RETAINED-CONTINUATION SENTINEL/);
    assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
    assert.equal(existsSync(resolverLockDir(w.manifest)), true);
    assert.equal(existsSync(w.lock), false);
    assert.equal(existsSync(join(w.cwd, ".git/perk-submit-conflict.lock")), false);
    // No approval means no action. A separately scripted decline never resets the episode.
    writeFileSync(w.syncFile, JSON.stringify({ success: true, declined: true }));
    await w.h.invokeTool("objective_stack_sync", { objective: "7", continue: true });
    assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
    assert.equal(w.engine.requests.length, 1);
    // The same operation hitting a new conflict on the next layer continues the episode.
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
    assert.equal(w.engine.requests.length, 2);
  } finally {
    w.h.dispose();
  }
});

test("retained execution lock: uncertain termination retains it and withholds the offer; a counter reset and session-claim reclamation never bypass it", async () => {
  const w = await setup({ status: "failed" });
  try {
    const r = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    assert.equal(details(r).ok, false);
    assert.equal(details(r).resolution?.kind, "failed");
    assert.match(w.injected[0] ?? "", /Continuation offer withheld/);
    assert.doesNotMatch(w.injected[0] ?? "", /NEW explicit human approval/);
    assert.equal(existsSync(w.lock), true);
    assert.equal(existsSync(resolverLockDir(w.manifest)), true);
    assert.equal(w.engine.requests.length, 1);
    w.append({ conflict_resolution_attempts: 0 });
    const file = join(resolverLockDir(w.manifest), "lease.json");
    const lease = JSON.parse(readFileSync(file, "utf8"));
    lease.pid = 2147483647;
    writeFileSync(file, JSON.stringify(lease));
    const next = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    assert.equal(details(next).error_type, "lock-busy");
    assert.equal(w.engine.requests.length, 1);
    assert.equal(existsSync(w.lock), true);
  } finally {
    w.h.dispose();
  }
});

test("retained refusal on the native worktree default names the file, the observation and the fix", async () => {
  const w = await setup({ nativeConfig: '{"worktree":"false"}' });
  try {
    const r = await w.h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    assert.equal(details(r).ok, false);
    const resolution = details(r).resolution;
    assert.ok(
      resolution?.kind === "failed" && resolution.reason === "incompatible-worktree-default",
    );
    const rendered = [
      ...r.content.map((block) => ("text" in block ? block.text : "")),
      ...w.injected,
    ].join("\n");
    assert.ok(rendered.includes(w.engine.resolverEngine.configPath), rendered);
    assert.ok(rendered.includes('worktree="false"'), rendered);
    assert.ok(rendered.includes("quit and resume this Pi session"), rendered);
    assert.equal(w.engine.requests.length, 0);
    assert.equal(existsSync(w.lock), false);
  } finally {
    w.h.dispose();
  }
});
