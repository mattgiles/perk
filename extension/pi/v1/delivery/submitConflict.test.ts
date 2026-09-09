import assert from "node:assert/strict";
import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import {
  completedResolution,
  completedRetainedResolution,
  deferred,
  fakeConflictResolver,
} from "../../../testing/fakeConflictResolver.ts";
import {
  fakePerkRouter,
  gitInit,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import { DELEGATION_EVENTS, type DelegationEvents } from "./conflictResolverEngine.ts";

const publication = {
  success: true,
  pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
  mergeable: false,
  base: "main",
};
const threads = {
  success: true,
  results: [{ thread_id: "thread", success: true, comment_added: false, error: null }],
};
const input = { threads: [{ thread_id: "thread" }] };
function details(result: { details: unknown }) {
  return result.details as {
    ok: boolean;
    kind: string;
    reason?: string;
    receipt?: { lock: { disposition: string; path: string } };
  };
}
function text(result: { content: { text?: string }[] }) {
  return result.content.map((block) => ("text" in block ? block.text : "")).join("\n");
}
async function setup(script?: Parameters<typeof fakeConflictResolver>[1], nativeConfig?: string) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  gitInit(cwd, { dirty: false });
  const engine = fakeConflictResolver(cwd, script);
  // Planted BEFORE the session loads: the engine reads the file once at activation.
  if (nativeConfig !== undefined) writeFileSync(engine.resolverEngine.configPath, nativeConfig);
  const bin = fakePerkRouter(cwd, {
    "pr submit": { json: publication },
    "pr resolve-threads": { json: threads },
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    resolverEngine: engine.resolverEngine,
    extraExtensions: [engine.extension],
  });
  spyInjections(h);
  return { cwd, engine, bin, h };
}

test("single-use authorization: parameterless/sequential; bound to counter and identity; cleared by a clean re-submit or a failed finalization; consumed even by a cross-mode record", async () => {
  let answered = 0;
  const w = await setup((bus, r) =>
    bus.emit(DELEGATION_EVENTS.response, {
      requestId: r.requestId,
      ownerRunId: r.ownerRunId,
      nodeId: r.nodeId,
      status: "completed",
      result: {
        kind: "structured",
        value: answered++ === 0 ? completedRetainedResolution : completedResolution,
      },
    }),
  );
  try {
    const tool = w.h.registeredTool("resolve_submit_conflicts");
    assert.equal(tool?.executionMode, "sequential");
    assert.deepEqual(tool?.parameters, {
      type: "object",
      properties: {},
      additionalProperties: false,
    });
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    assert.equal(w.engine.requests.length, 0);
    writeFileSync(
      join(w.cwd, ".perk/config.toml"),
      '[models.subagents]\nconflict-resolver = "offline/override"\n',
    );
    await w.h.invokeTool("submit", {});
    const crossMode = details(await w.h.invokeTool("resolve_submit_conflicts", {}));
    assert.equal(crossMode.kind, "failed");
    assert.equal(crossMode.reason, "malformed-result");
    assert.equal(crossMode.receipt?.lock.disposition, "released");
    assert.equal(w.engine.requests.length, 1);
    assert.equal(w.engine.requests[0]?.model, "offline/override");
    assert.equal(w.engine.requests[0]?.ownerRunId, "01RID");
    assert.equal(Object.hasOwn(w.engine.requests[0] ?? {}, "extensionBindings"), false);
    await w.h.invokeTool("submit", {});
    w.h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      conflict_resolution_attempts: 0,
    });
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    assert.equal(w.engine.requests.length, 1);
    await w.h.invokeTool("submit", {});
    w.h.session.sessionManager.appendCustomEntry("perk:workflow-state", { run_id: "different" });
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    assert.equal(w.engine.requests.length, 1);
    await w.h.invokeTool("submit", {});
    fakePerkRouter(w.cwd, { "pr submit": { json: { ...publication, mergeable: true } } });
    await w.h.invokeTool("submit", {});
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    assert.equal(w.engine.requests.length, 1);
    fakePerkRouter(w.cwd, {
      "pr submit": { json: publication },
      "pr resolve-threads": { json: { success: false, message: "failed" }, code: 1 },
    });
    await w.h.invokeTool("submit", {});
    await w.h.invokeTool("finalize_address", input);
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    assert.equal(w.engine.requests.length, 1);
    await w.h.invokeTool("submit", {});
    const resolved = await w.h.invokeTool("resolve_submit_conflicts", {});
    assert.equal(details(resolved).kind, "resolved");
    assert.notEqual(resolved.terminate, true);
    assert.match(text(resolved), /call canonical submit again/i);
    assert.equal(w.engine.requests.length, 2);
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    assert.equal(w.engine.requests.length, 2);
  } finally {
    w.h.dispose();
  }
});

test("incompatible native worktree default: the tool names the file, the observation and the fix without a request", async () => {
  const w = await setup(undefined, '{"worktree":true}');
  try {
    await w.h.invokeTool("submit", {});
    const r = await w.h.invokeTool("resolve_submit_conflicts", {});
    assert.equal(details(r).ok, false);
    assert.equal(details(r).reason, "incompatible-worktree-default");
    const rendered = text(r);
    assert.ok(rendered.includes(w.engine.resolverEngine.configPath), rendered);
    assert.ok(rendered.includes("worktree=true"), rendered);
    assert.ok(rendered.includes('set "worktree": false'), rendered);
    assert.ok(rendered.includes("quit and resume"), rendered);
    assert.doesNotMatch(rendered, /perk doctor|perk init|Inspect native/);
    assert.equal(w.engine.requests.length, 0, "the bus never received a request");
  } finally {
    w.h.dispose();
  }
});

test("two activations count separately but only one writer emits; contention never refunds or unlocks; a retained lock survives the second session", async () => {
  const emitted = deferred<{ bus: DelegationEvents; request: Record<string, unknown> }>();
  const w = await setup((bus, request) => emitted.resolve({ bus, request }));
  let second: Awaited<ReturnType<typeof loadPerkSession>> | undefined;
  try {
    await w.h.invokeTool("submit", {});
    const running = w.h.invokeTool("resolve_submit_conflicts", {});
    const { bus, request } = await emitted.promise;
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    await w.h.invokeTool("submit", {}); // counted, but cannot supersede the active writer
    const file = plantSession(w.cwd, [{ run_id: "other-run", mode: "read-write" }]);
    second = await loadPerkSession({
      cwd: w.cwd,
      sessionManager: SessionManager.open(file),
      env: { PERK_BIN: w.bin, PERK_RUN_ID: undefined },
      resolverEngine: w.engine.resolverEngine,
      extraExtensions: [w.engine.extension],
    });
    spyInjections(second);
    await second.invokeTool("submit", {});
    const blocked = details(await second.invokeTool("resolve_submit_conflicts", {}));
    assert.equal(blocked.reason, "lock-busy");
    assert.equal(
      second.workflowState().conflict_resolution_attempts,
      1,
      "contention neither refunds nor adds attempts",
    );
    assert.equal(w.engine.requests.length, 1);
    bus.emit(DELEGATION_EVENTS.response, {
      requestId: request.requestId,
      ownerRunId: request.ownerRunId,
      nodeId: request.nodeId,
      status: "failed",
      error: "SECRET OUTPUT",
      result: { kind: "structured", value: completedResolution },
    });
    const failed = await running;
    assert.equal(details(failed).receipt?.lock.disposition, "retained");
    assert.doesNotMatch(JSON.stringify(failed), /SECRET/);
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    const path = details(failed).receipt?.lock.path;
    assert.ok(path && existsSync(path));
    await second.invokeTool("submit", {});
    assert.equal(
      details(await second.invokeTool("resolve_submit_conflicts", {})).reason,
      "lock-busy",
    );
    assert.equal(w.engine.requests.length, 1);
    assert.ok(existsSync(path));
  } finally {
    second?.dispose();
    w.h.dispose();
  }
});
