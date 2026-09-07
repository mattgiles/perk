import assert from "node:assert/strict";
import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import {
  completedResolution,
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
async function setup(
  script?: Parameters<typeof fakeConflictResolver>[1],
  pausePreflight?: () => Promise<void>,
) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  gitInit(cwd, { dirty: false });
  const engine = fakeConflictResolver(cwd, script);
  if (pausePreflight) {
    const preflight = engine.resolverEngine.preflight;
    engine.resolverEngine.preflight = async (input) => {
      const profile = await preflight(input);
      await pausePreflight();
      return profile;
    };
  }
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

test("registration is parameterless/sequential; direct/repeated calls refuse; configured model stays code-owned", async () => {
  const w = await setup();
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
    const r = await w.h.invokeTool("resolve_submit_conflicts", {});
    assert.equal(details(r).kind, "resolved");
    assert.notEqual(r.terminate, true);
    assert.equal(w.engine.requests[0]?.model, "offline/override");
    assert.equal(w.engine.preflights[0]?.model, "offline/override");
    assert.equal(w.engine.requests[0]?.ownerRunId, "01RID");
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    assert.equal(w.engine.requests.length, 1);
  } finally {
    w.h.dispose();
  }
});

for (const change of ["counter", "identity", "read-only", "planning", "clean-submit"]) {
  test(`unused authorization invalidated by ${change}`, async () => {
    const w = await setup();
    try {
      await w.h.invokeTool("submit", {});
      if (change === "clean-submit") {
        fakePerkRouter(w.cwd, { "pr submit": { json: { ...publication, mergeable: true } } });
        await w.h.invokeTool("submit", {});
      } else
        w.h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
          ...(change === "counter"
            ? { conflict_resolution_attempts: 0 }
            : change === "identity"
              ? { run_id: "different" }
              : change === "read-only"
                ? { mode: "read-only" }
                : { stage: "plan" }),
        });
      assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
      assert.equal(w.engine.requests.length, 0);
    } finally {
      w.h.dispose();
    }
  });
}

for (const change of ["counter", "identity"]) {
  test(`registered dispatch revalidates ${change} changed during awaited preflight`, async () => {
    const entered = deferred<void>();
    const resume = deferred<void>();
    const w = await setup(undefined, async () => {
      entered.resolve();
      await resume.promise;
    });
    let running: ReturnType<typeof w.h.invokeTool> | undefined;
    try {
      const submitted = await w.h.invokeTool("submit", {});
      assert.equal(submitted.terminate, true);
      assert.equal(w.h.workflowState().conflict_resolution_attempts, 1);
      running = w.h.invokeTool("resolve_submit_conflicts", {});
      await entered.promise;
      assert.equal(w.engine.preflights.length, 1, "the primed tool reached awaited preflight");
      assert.equal(w.engine.requests.length, 0);
      w.h.session.sessionManager.appendCustomEntry(
        "perk:workflow-state",
        change === "counter" ? { conflict_resolution_attempts: 0 } : { run_id: "different" },
      );
      assert.equal(
        w.h.workflowState().mode,
        "read-write",
        "the read-only guard is not the refusal",
      );
      resume.resolve();
      const result = await running;
      const outcome = details(result);
      assert.equal(outcome.ok, false);
      assert.equal(outcome.kind, "failed");
      assert.equal(outcome.reason, "unauthorized");
      assert.equal(outcome.receipt?.lock.disposition, "not-acquired");
      assert.notEqual(result.terminate, true);
      assert.equal(
        w.engine.requests.length,
        0,
        "controller-to-adapter revalidation prevents launch",
      );
      assert.equal(existsSync(join(w.cwd, ".git/perk-submit-conflict.lock")), false);
      assert.equal(w.h.workflowState().conflict_resolution_attempts, change === "counter" ? 0 : 1);
      assert.equal(w.h.workflowState().run_id, change === "identity" ? "different" : "01RID");
      assert.equal(details(submitted).ok, true, "the successful publication stands");
    } finally {
      resume.resolve();
      await running;
      w.h.dispose();
    }
  });
}

test("malformed finalizer leaves pending alone; valid failed finalizer clears; full success primes", async () => {
  const w = await setup();
  try {
    await w.h.invokeTool("submit", {});
    await w.h.invokeTool("finalize_address", { threads: [{ thread_id: 123 }] });
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).kind, "resolved");
    await w.h.invokeTool("submit", {});
    fakePerkRouter(w.cwd, {
      "pr submit": { json: publication },
      "pr resolve-threads": { json: { success: false, message: "failed" }, code: 1 },
    });
    await w.h.invokeTool("finalize_address", input);
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).ok, false);
    // Reset only the parent counter to permit one new fixture attempt; never touch a lock.
    w.h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      conflict_resolution_attempts: 0,
    });
    fakePerkRouter(w.cwd, {
      "pr submit": { json: publication },
      "pr resolve-threads": { json: threads },
    });
    const finalized = await w.h.invokeTool("finalize_address", input);
    assert.equal(finalized.terminate, true);
    assert.equal(details(await w.h.invokeTool("resolve_submit_conflicts", {})).kind, "resolved");
    assert.equal(w.engine.requests.length, 2);
  } finally {
    w.h.dispose();
  }
});

test("two activations count separately but only one writer emits; no replacement priming or reload unlock", async () => {
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
