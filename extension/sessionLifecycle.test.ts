// Live composition tests over a REAL bound AgentSession (offline — no LLM, no network): the
// ORDERED Pi effects (gate → verified linkage → capture → receiver sync on a consuming cold start;
// gate → receiver on navigation), gate-before-fallible-read, the LOADED registry gating linkage,
// and three wiring regressions through the real ports (the env-child adopt, the corrupt-handoff
// gate, the first-write-wins capture). The owning behavior matrix — every identity arm's exact
// append/trace, the tool scope, the lazy linkage and its capture/feedback facts — lives in
// `session/lifecycle.test.ts` and is not duplicated here: where a regression below touches an arm
// (adopt, the failed claim, keep), what it pins is the real ports/gate wiring around that arm, not
// the arm's decision table. The two runner-floor tests at the top stay as they are.

import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { AgentSession, SessionManager } from "@earendil-works/pi-coding-agent";
import type { HunkFeedbackReceiver, ReceiverSyncArgs } from "./hunkFeedback/receiver.ts";
import { AGENT_SCRATCH_CONTEXT_TYPE } from "./substrate/agentScratch.ts";
import {
  agentScratchDir,
  handoffPath,
  type PlanRef,
  runScratchDir,
  writePlanRef,
} from "./substrate/cache.ts";
import { perkVersion } from "./substrate/resources.ts";
import {
  readSessionPointers,
  recordSessionPointer,
  type SessionPointer,
} from "./substrate/sessionPointers.ts";
import { READ_ONLY_CONTEXT, READ_ONLY_TOOLS } from "./substrate/toolGating.ts";
import { WORKFLOW_STATE_TYPE } from "./substrate/workflowState.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";

const runnerPacket = {
  PI_SUBAGENT_CHILD: "1",
  PI_SUBAGENT_EXTENSION_BINDINGS: '{"perk.parent-restrictions/1":{"readOnly":true}}',
};

async function noScratch(h: Awaited<ReturnType<typeof loadPerkSession>>, cwd: string) {
  assert.equal(
    (await h.emitBeforeAgentStart()).some(
      (message) => message.customType === AGENT_SCRATCH_CONTEXT_TYPE,
    ),
    false,
  );
  assert.deepEqual(
    await h.emitContext([{ customType: AGENT_SCRATCH_CONTEXT_TYPE, content: "stale scratch" }]),
    [],
  );
  const runId = h.workflowState().run_id;
  if (runId) assert.equal(existsSync(agentScratchDir(cwd, runId)), false);
}

test("runner floor: latched for the activation, backstopped, and invisible to a sibling activation", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-write" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: runnerPacket,
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    for (const tool of ["write", "edit", "plan_save", "foreign_mutator"])
      assert.equal((await h.emitToolCall(tool, {}))?.block, true, tool);
    assert.equal((await h.emitToolCall("structured_output", { value: {} }))?.block, undefined);
    assert.equal((await h.emitToolCall("bash", { command: "git status" }))?.block, undefined);
    await noScratch(h, cwd);

    // A same-activation restart without the runner env, and a producer's honest `false`, cannot
    // clear a latched floor; neither can navigating to the read-write leaf.
    delete process.env.PI_SUBAGENT_CHILD;
    process.env.PI_SUBAGENT_EXTENSION_BINDINGS =
      '{"perk.parent-restrictions/1":{"readOnly":false}}';
    await h.emitSessionStart();
    assert.equal((await h.emitToolCall("write", {}))?.block, true);
    assert.equal((await h.emitToolCall("foreign_mutator", {}))?.block, true);
    await h.navigateTo("c0");
    assert.equal((await h.emitToolCall("write", {}))?.block, true);
    await noScratch(h, cwd);

    // The floor is per activation: a sibling session in the same process without the runner env
    // is untouched.
    const siblingFile = plantSession(cwd, [{ run_id: "SIB", mode: "read-write" }], {
      fileName: "planted-sibling.jsonl",
    });
    const sibling = await loadPerkSession({
      cwd,
      sessionManager: SessionManager.open(siblingFile),
    });
    try {
      assert.equal(sibling.workflowState().mode, "read-write");
      assert.equal((await sibling.emitToolCall("write", {}))?.block, undefined);
      assert.equal((await h.emitToolCall("write", {}))?.block, true);
    } finally {
      sibling.dispose();
    }
  } finally {
    h.dispose();
  }
});

test("escaping reflection exception reports safely and continues startup with backstop and scratch suppression", async () => {
  const cwd = scaffoldRepo();
  const manager = SessionManager.inMemory(cwd);
  const append = manager.appendCustomEntry.bind(manager);
  let reflections = 0;
  manager.appendCustomEntry = (type, data) => {
    if (
      type === "perk:workflow-state" &&
      typeof data === "object" &&
      data !== null &&
      "mode" in data
    ) {
      reflections++;
      // Stringification inside the classified append also throws; exercise its escape contract.
      throw Object.assign(Object.create(null), { secret: "SENSITIVE_THROW_PAYLOAD" });
    }
    return append(type, data);
  };
  const h = await loadPerkSession({ cwd, sessionManager: manager, env: runnerPacket });
  try {
    assert.equal(reflections, 1);
    assert.equal(h.workflowState().mode, undefined);
    assert.ok(h.workflowState().run_id, "normal mint remains intact");
    assert.equal(h.sentinel()?.source, "mint", "remaining startup work reached the final sentinel");
    assert.ok(h.footerFactory());
    assert.equal(
      h.notifies.filter((message) =>
        message.includes(
          "could not persist child read-only restriction; in-memory restriction remains active",
        ),
      ).length,
      1,
    );
    assert.doesNotMatch(h.notifies.join("\n"), /SENSITIVE_THROW_PAYLOAD|linkage error/);
    assert.equal((await h.emitToolCall("foreign_mutator", {}))?.block, true);
    await noScratch(h, cwd);
  } finally {
    h.dispose();
  }
});

// --- lifecycle regressions through the real ports -------------------------------------------------

test("composition: an env-child adopts through the real ports — derived identity, inherited gating, no re-consume, no stage or claim impersonation, no capture", async () => {
  // THE regression (the /learn session-pointer shadowing defect): a subagent child inherits the
  // parent's PERK_RUN_ID via process env; its fresh session has no branch state, so pre-fix it
  // re-claimed the run — re-consuming the handoff and shadowing implementation/main.
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-only",
      stage: "plan",
      consumed: true,
      piSessionId: "parent.jsonl",
      // An adopted env-child must not inherit the parent handoff's node link either.
      extra: { objective_id: "7", node_id: "2.3" },
    },
  });
  const parentPointer: SessionPointer = {
    pi_session_id: "parent.jsonl",
    session_file: "/sessions/parent.jsonl",
    parent_pi_session_id: null,
    at: "2026-06-01T00:00:00Z",
  };
  recordSessionPointer(cwd, "01RID", "implementation", "main", parentPointer);
  const file = plantSession(cwd, [], { fileName: "child.jsonl" });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    // The child adopted a derived identity with truthful lineage — no stage or claim
    // impersonation, the handoff's mode inherited, the real version stamp.
    const state = h.workflowState();
    assert.equal(state.run_id, "01RID.1");
    assert.equal(state.predecessor, "01RID");
    assert.equal(state.stage, undefined);
    assert.equal(state.objective_node_claim, undefined);
    assert.equal(state.mode, "read-only");
    assert.equal(state.perk_version, perkVersion());
    assert.equal(h.sentinel()?.source, "env-child");
    assert.ok(existsSync(runScratchDir(cwd, "01RID.1")), "the child's scratch was isolated");
    // The parent's implementation/main pointer is untouched; the child captured nothing.
    assert.deepEqual(readSessionPointers(cwd, "01RID")?.implementation.main, parentPointer);
    assert.equal(readSessionPointers(cwd, "01RID.1"), null);
    // The handoff still records the TRUE claimer (never re-consumed).
    const handoff = JSON.parse(readFileSync(handoffPath(cwd, "01RID"), "utf8"));
    assert.equal(handoff.pi_session_id, "parent.jsonl");
    assert.equal(handoff.consumed, true);
    // The inherited read-only mode gates the child through the real wiring.
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some((m) => m.content === READ_ONLY_CONTEXT),
      "the read-only mode context is injected",
    );
  } finally {
    h.dispose();
  }
});

test("capture guard: a claimer's capture skips a pre-seeded foreign implementation.main", async () => {
  // Pins the preserveForeign wiring end-to-end: the interior capture is first-write-wins.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  const foreignPointer: SessionPointer = {
    pi_session_id: "foreign.jsonl",
    session_file: "/sessions/foreign.jsonl",
    parent_pi_session_id: null,
    at: "2026-06-01T00:00:00Z",
  };
  recordSessionPointer(cwd, "01RID", "implementation", "main", foreignPointer);
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.workflowState().run_id, "01RID", "the unconsumed handoff still claims");
    assert.deepEqual(
      readSessionPointers(cwd, "01RID")?.implementation.main,
      foreignPointer,
      "the foreign pointer was preserved (first-write-wins)",
    );
  } finally {
    h.dispose();
  }
});

test("regression: a corrupt handoff — cold, the loud unclaimed path with the gate OFF; after a claim, it cannot un-gate the kept read-only session on reload", async () => {
  // A truncated cold-launch blob: the intended mode is unknowable (it lives inside the unreadable
  // file), so the claim degrades to the §8.2 loud-unclaimed error — loud, non-fatal, gate OFF.
  const cold = scaffoldRepo(); // no handoff planted
  writeFileSync(handoffPath(cold, "01RID"), '{"run_id": "01RID", "consum', "utf8");
  const a = await loadPerkSession({ cwd: cold, env: { PERK_RUN_ID: "01RID" } });
  try {
    // No crash; the run stays unclaimed and the linkage error is reported.
    assert.equal(a.workflowState().run_id, undefined);
    assert.ok(
      a.notifies.some((m) => m.includes("handoff missing or mismatched")),
      `expected the loud-unclaimed linkage error, got ${JSON.stringify(a.notifies)}`,
    );
    // The sentinel proves the handler ran to completion past the gate sync.
    const s = a.sentinel();
    assert.equal(s?.source, "env");
    assert.equal(s?.run_id, null);
    // The decided posture, pinned: a failed cold claim keeps the gate OFF (we never lock a
    // corrupt read-write launch into a half-broken read-only session).
    const verdict = await a.emitToolCall("write", { path: "x", content: "y" });
    assert.equal(verdict?.block, undefined, "gate stays off on a failed cold claim");
  } finally {
    a.dispose();
  }

  // THE gate regression: the mode is knowable from session state alone, so a handoff corrupted
  // AFTER a successful claim must not disturb the read-only gate on reload. Pre-fix, the bare
  // JSON.parse threw inside resolveRunStage and the gate never engaged.
  const kept = scaffoldRepo();
  // No pi_session_id -> decideClaim's keep arm re-resolves the claimed run from session state.
  const file = plantSession(kept, [{ run_id: "01RID", mode: "read-only" }]);
  writeFileSync(handoffPath(kept, "01RID"), '{"run_id": "01RID", "consum', "utf8");
  const b = await loadPerkSession({ cwd: kept, sessionManager: SessionManager.open(file) });
  try {
    const verdict = await b.emitToolCall("write", { path: "x", content: "y" });
    assert.equal(
      verdict?.block,
      true,
      "write blocked — the gate engaged despite the corrupt handoff",
    );
    const injected = await b.emitBeforeAgentStart();
    assert.ok(
      injected.some((m) => m.content === READ_ONLY_CONTEXT),
      "the read-only mode context is injected",
    );
  } finally {
    b.dispose();
  }
});

// --- composition order through the real wiring (recording receiver) ------------------------------

function planRef(prId: string): PlanRef {
  return {
    provider: "github",
    pr_id: prId,
    url: `https://github.com/o/r/issues/${prId}`,
    labels: ["perk:plan"],
    objective_id: null,
  };
}

/**
 * A recording `HunkFeedbackReceiver`: the production interface, constructed once per activation
 * through the `feedbackReceiverFactory` option. Each sync records the args it was handed AND the
 * implementation pointer already on disk at that moment (the capture-before-receiver proof).
 */
function recordingReceiver(events: string[]) {
  const syncs: { args: ReceiverSyncArgs; pointer: SessionPointer | null }[] = [];
  let constructed = 0;
  const factory = (): HunkFeedbackReceiver => {
    constructed++;
    return {
      sync(ctx, args) {
        events.push("receiver");
        const pointer =
          typeof args.runId === "string"
            ? (readSessionPointers(ctx.cwd, args.runId)?.implementation.main ?? null)
            : null;
        syncs.push({ args, pointer });
      },
      close() {},
    };
  };
  return { factory, syncs, constructed: () => constructed };
}

/** Record every `perk:workflow-state` append (by its sorted field names) on a real manager. */
function recordAppends(manager: SessionManager, events: string[]): void {
  const append = manager.appendCustomEntry.bind(manager);
  manager.appendCustomEntry = (type, data) => {
    if (type === "perk:workflow-state" && typeof data === "object" && data !== null) {
      events.push(`append:${Object.keys(data).sort().join(",")}`);
    }
    return append(type, data);
  };
}

test("composition: a consuming cold start orders gate → verified linkage → capture → receiver sync", async (t) => {
  const events: string[] = [];
  const toolSets: string[][] = [];
  const original = AgentSession.prototype.setActiveToolsByName;
  t.mock.method(
    AgentSession.prototype,
    "setActiveToolsByName",
    function (this: AgentSession, names: string[]) {
      events.push("tools");
      toolSets.push([...names]);
      original.call(this, names);
    },
  );
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writePlanRef(cwd, planRef("42"));
  const manager = SessionManager.open(plantSession(cwd, []));
  recordAppends(manager, events);
  const receiver = recordingReceiver(events);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: manager,
    feedbackReceiverFactory: receiver.factory,
  });
  try {
    // The real effect sequence from the claim on: the ONE combined claim entry, the gate sync
    // (the stage-scoped tool set), the ONE verified link append, then the receiver — nothing
    // else touched workflow-state or the tool set in between. (Pi's own initial tool
    // installation precedes the handler; nothing of perk's does.)
    const claim = events.indexOf("append:mode,perk_version,pi_session_id,run_id,stage");
    assert.ok(claim >= 0, JSON.stringify(events));
    assert.ok(
      events.slice(0, claim).every((event) => event === "tools"),
      `no perk append or receiver sync before the claim: ${JSON.stringify(events)}`,
    );
    assert.deepEqual(events.slice(claim), [
      "append:mode,perk_version,pi_session_id,run_id,stage",
      "tools",
      "append:active_plan_ref",
      "receiver",
    ]);
    assert.ok(toolSets.at(-1)?.includes("submit"), "implement scoping installed before linkage");
    assert.equal(receiver.constructed(), 1, "one receiver per activation, like production");
    assert.equal(receiver.syncs.length, 1);
    const sync = receiver.syncs[0];
    assert.ok(sync);
    // At receiver sync the reconciled ref is the checkout binding just linked…
    assert.deepEqual(sync.args, {
      stage: "implement",
      adopted: false,
      runId: "01RID",
      piSessionId: "planted-parent.jsonl",
      activePlanRef: planRef("42"),
      mode: "print",
    });
    // …and the REAL implementation pointer was already written (capture before receiver).
    assert.equal(sync.pointer?.pi_session_id, "planted-parent.jsonl");
    assert.equal(sync.pointer?.parent_pi_session_id, null);
    assert.deepEqual(h.workflowState().active_plan_ref, planRef("42"));
    // The §8.3 exact-vintage stamp rides the claim entry: the harness loads from source, so
    // perkVersion() is the real repo version — a strict X.Y.Z string, never the sentinel.
    assert.equal(h.workflowState().perk_version, perkVersion());
    assert.match(h.workflowState().perk_version ?? "", /^\d+\.\d+\.\d+$/);
    assert.deepEqual(h.sentinel()?.active_plan_ref, planRef("42"));
    assert.equal(JSON.parse(readFileSync(handoffPath(cwd, "01RID"), "utf8")).consumed, true);
  } finally {
    h.dispose();
  }
});

test("composition: a post-gate branch-read failure leaves the gate applied and reaches no capture/receiver effect", async (t) => {
  // The throwing read is armed by the gate sync itself (the read-only tool set install), so the
  // FIRST branch read after the gate — the post-gate linked-state rebuild — throws. The
  // exception propagates to Pi's hook error boundary (the harness's onError channel), and the
  // handler's later effects (capture, receiver, sentinel) are never reached.
  const errors: string[] = [];
  t.mock.method(console, "error", (message: unknown) => errors.push(String(message)));
  let gateSynced = false;
  const original = AgentSession.prototype.setActiveToolsByName;
  t.mock.method(
    AgentSession.prototype,
    "setActiveToolsByName",
    function (this: AgentSession, names: string[]) {
      original.call(this, names);
      if (
        names.length === READ_ONLY_TOOLS.length &&
        names.every((name, i) => name === READ_ONLY_TOOLS[i])
      ) {
        gateSynced = true;
      }
    },
  );
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "implement" } });
  writePlanRef(cwd, planRef("42"));
  const manager = SessionManager.open(plantSession(cwd, []));
  const realGetBranch = manager.getBranch.bind(manager);
  let armed = true;
  manager.getBranch = () => {
    if (armed && gateSynced) throw new Error("unreadable session branch (induced)");
    return realGetBranch();
  };
  const receiver = recordingReceiver([]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: manager,
    feedbackReceiverFactory: receiver.factory,
  });
  armed = false; // heal for the observations below
  try {
    assert.ok(gateSynced, "the gate sync ran");
    assert.ok(
      errors.some(
        (line) =>
          line.includes("extension error in session_start") &&
          line.includes("unreadable session branch (induced)"),
      ),
      `the original exception reaches the harness error channel: ${JSON.stringify(errors)}`,
    );
    // The gate is applied (the identity claim + sync happened before the failing read)…
    assert.equal(h.workflowState().run_id, "01RID");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
    // …and nothing downstream ran from guessed facts: no linkage, no capture, no receiver sync,
    // no sentinel.
    assert.equal(h.workflowState().active_plan_ref, undefined);
    assert.equal(readSessionPointers(cwd, "01RID"), null, "capture not reached");
    assert.equal(receiver.syncs.length, 0, "receiver sync not reached");
    assert.equal(h.sentinel(), null, "the handler aborted before its sentinel");
  } finally {
    h.dispose();
  }
});

test("composition: the loaded registry gates linkage — a `plan` claim never links the root selector", async () => {
  // Regression: the root `cache.plan-ref` *selector* must NOT leak into a fresh planning
  // session. The root `worktree: none` stages (plan/objective-plan/save) do not consume the ref
  // (registry `requires`/`reads`), so session_start must not reconcile it into active_plan_ref.
  // This pins that index.ts hands `resolveSessionStartFacts` the LOADED registry — a null
  // registry would have linked permissively here; which real stages consume is
  // `substrate/registry.test.ts`'s pin.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "plan" } });
  writePlanRef(cwd, planRef("42"));
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    // The run is still claimed (run_id linkage is independent of plan-ref reconciliation)…
    assert.equal(h.workflowState().run_id, "01RID");
    // …but the stale root selector never becomes active_plan_ref, on the state or the branch.
    assert.equal(h.workflowState().active_plan_ref ?? null, null);
    const links = h.session.sessionManager.getBranch().filter((entry) => {
      const e = entry as { type?: string; customType?: string; data?: Record<string, unknown> };
      return (
        e.type === "custom" &&
        e.customType === WORKFLOW_STATE_TYPE &&
        e.data?.active_plan_ref !== undefined
      );
    });
    assert.equal(links.length, 0, "no workflow-state entry carries active_plan_ref");
  } finally {
    h.dispose();
  }
});

test("composition: navigation syncs the gate before the receiver from ONE rebuilt state — no capture, no linkage", async (t) => {
  const events: string[] = [];
  const original = AgentSession.prototype.setActiveToolsByName;
  t.mock.method(
    AgentSession.prototype,
    "setActiveToolsByName",
    function (this: AgentSession, names: string[]) {
      events.push("tools");
      original.call(this, names);
    },
  );
  const cwd = scaffoldRepo();
  writePlanRef(cwd, planRef("42")); // present — navigation must never read it
  const manager = SessionManager.open(
    plantSession(cwd, [
      {
        run_id: "01RID",
        pi_session_id: "planted-parent.jsonl",
        mode: "read-write",
        stage: "implement",
        active_plan_ref: planRef("41"),
      },
    ]),
  );
  recordAppends(manager, events);
  const receiver = recordingReceiver(events);
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    feedbackReceiverFactory: receiver.factory,
  });
  try {
    // Startup here is a keep without a handoff: no launched stage, no linkage, no capture.
    assert.equal(readSessionPointers(cwd, "01RID"), null);
    events.length = 0;
    // Navigate to the planted state entry (the current leaf is a no-op for Pi; an earlier
    // entry re-selects a branch that still carries the same state).
    await h.navigateTo("c0");
    assert.deepEqual(events, ["tools", "receiver"], "gate first, then the receiver; no appends");
    assert.equal(h.sentinel()?.source, "tree");
    const sync = receiver.syncs.at(-1);
    assert.ok(sync);
    assert.deepEqual(sync.args, {
      stage: "implement",
      adopted: false,
      runId: "01RID",
      piSessionId: "planted-parent.jsonl",
      activePlanRef: planRef("41"), // the branch's own ref — the checkout #42 was never read
      mode: "print",
    });
    assert.equal(sync.pointer, null, "navigation never captures");
    assert.deepEqual(h.workflowState().active_plan_ref, planRef("41"));
  } finally {
    h.dispose();
  }
});
