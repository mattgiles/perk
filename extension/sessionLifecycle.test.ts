// Live session-lifecycle tests. These drive a REAL bound AgentSession through
// the harness and prove the perk:workflow-state wiring end-to-end, OFFLINE (no LLM, no
// network). Each case has a pure-function twin in workflowState.test.ts; here we prove the wiring.

import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { AgentSession, SessionManager } from "@earendil-works/pi-coding-agent";
import { AGENT_SCRATCH_CONTEXT_TYPE } from "./substrate/agentScratch.ts";
import { agentScratchDir, handoffPath, runScratchDir, workflowDir } from "./substrate/cache.ts";
import { perkVersion } from "./substrate/resources.ts";
import {
  readSessionPointers,
  recordSessionPointer,
  type SessionPointer,
} from "./substrate/sessionPointers.ts";
import { READ_ONLY_CONTEXT, READ_ONLY_TOOLS } from "./substrate/toolGating.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";

const runnerPacket = {
  PI_SUBAGENT_CHILD: "1",
  PI_SUBAGENT_EXTENSION_BINDINGS: '{"perk.parent-restrictions/1":{"readOnly":true}}',
};
const reportPrompt = '<active_agent name="perk.pr-reviewer"/>\n\nReport rubric';
const writerPrompt = '<active_agent name="perk.conflict-resolver"/>\n\nWriter rubric';

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

test("startup captures the original prefix before gate tool rebuild; reload recaptures the loader prompt", async (t) => {
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
        this.agent.state.systemPrompt = writerPrompt;
      }
    },
  );
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-write" }, { mode: "read-only" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    systemPrompt: reportPrompt,
  });
  try {
    assert.equal(
      h.session.systemPrompt,
      writerPrompt,
      "the tool rebuild deliberately changed the live prompt",
    );
    await h.navigateTo("c0");
    assert.equal((await h.emitToolCall("write", {}))?.block, undefined);
    await noScratch(h, cwd);
    h.session.agent.state.systemPrompt = writerPrompt;
    await h.reload();
    assert.ok(h.session.systemPrompt.startsWith(reportPrompt));
    await noScratch(h, cwd);
  } finally {
    h.dispose();
  }
});

test("runner floor survives tree/compaction and original-packet reload over a read-write branch", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-write" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    systemPrompt: writerPrompt,
    env: runnerPacket,
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    delete process.env.PI_SUBAGENT_CHILD;
    process.env.PI_SUBAGENT_EXTENSION_BINDINGS =
      '{"perk.parent-restrictions/1":{"readOnly":false}}';
    await h.navigateTo("c0");
    assert.equal(h.workflowState().mode, "read-write");
    await h.emitLifecycle({ type: "session_compact" });
    assert.equal((await h.emitToolCall("foreign_mutator", {}))?.block, true);
    await noScratch(h, cwd);
    await h.reload(runnerPacket);
    assert.equal(h.workflowState().mode, "read-only", "original packet reflects again on reload");
    assert.equal((await h.emitToolCall("write", {}))?.block, true);
    await noScratch(h, cwd);
  } finally {
    h.dispose();
  }
});

test("existing branch read-only survives reload without a restriction packet", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-only" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    systemPrompt: writerPrompt,
    env: { PI_SUBAGENT_CHILD: "1" },
  });
  try {
    await h.reload();
    assert.equal(h.workflowState().mode, "read-only");
    assert.equal((await h.emitToolCall("submit", {}))?.block, true);
    assert.equal(
      h.notifies.some((message) => message.includes("child restriction")),
      false,
      "legacy absence is silent",
    );
  } finally {
    h.dispose();
  }
});

test("missing/mismatched env handoff stays loudly unclaimed under true/invalid runner restrictions", async () => {
  for (const mismatch of [false, true]) {
    const cwd = scaffoldRepo();
    if (mismatch)
      writeFileSync(
        handoffPath(cwd, "MISSING"),
        JSON.stringify({ run_id: "WRONG", consumed: true, mode: "read-write" }),
      );
    const h = await loadPerkSession({
      cwd,
      systemPrompt: writerPrompt,
      env: {
        ...runnerPacket,
        PERK_RUN_ID: "MISSING",
        PI_SUBAGENT_EXTENSION_BINDINGS: mismatch
          ? "invalid"
          : runnerPacket.PI_SUBAGENT_EXTENSION_BINDINGS,
      },
    });
    try {
      assert.equal(h.workflowState().run_id, undefined, "failed claim must not mint");
      assert.equal(
        h.workflowState().mode,
        undefined,
        "no invented persisted restriction on unclaimed outcome",
      );
      assert.ok(
        h.notifies.some((message) =>
          message.includes("handoff missing or mismatched for run MISSING"),
        ),
      );
      assert.equal((await h.emitToolCall("plan_save", {}))?.block, true);
      assert.ok(h.footerFactory(), "startup continues after honest unclaimed outcome");
      await noScratch(h, cwd);
    } finally {
      h.dispose();
    }
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
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    systemPrompt: writerPrompt,
    env: runnerPacket,
  });
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

test("paired sessions cache identity/floor independently; forged prefixes change scratch only, not authority", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "PARENT", mode: "read-write", stage: "implement" },
  });
  const parent = await loadPerkSession({
    cwd,
    systemPrompt: reportPrompt,
    env: { PERK_RUN_ID: "PARENT" },
  });
  const handoff = readFileSync(handoffPath(cwd, "PARENT"), "utf8");
  const original = parent.workflowState();
  const child = await loadPerkSession({
    cwd,
    systemPrompt: writerPrompt,
    env: { ...runnerPacket, PERK_RUN_ID: "PARENT", PI_SUBAGENT_CHILD_AGENT: "perk.pr-reviewer" },
  });
  try {
    assert.equal(child.workflowState().predecessor, "PARENT");
    assert.equal(child.workflowState().stage, undefined);
    assert.equal(child.workflowState().mode, "read-only", "writer prefix is not a write grant");
    assert.equal((await parent.emitToolCall("write", {}))?.block, undefined);
    assert.equal((await child.emitToolCall("write", {}))?.block, true);
    parent.session.agent.state.systemPrompt = writerPrompt;
    await parent.emitLifecycle({ type: "session_compact" });
    await noScratch(parent, cwd);
    await noScratch(child, cwd);
    assert.deepEqual(parent.workflowState(), original);
    assert.equal(parent.workflowState().stage, "implement");
    assert.equal(readFileSync(handoffPath(cwd, "PARENT"), "utf8"), handoff);
  } finally {
    child.dispose();
    parent.dispose();
  }
});

test("claim: fresh session with PERK_RUN_ID + handoff claims the run", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const s = h.sentinel();
    assert.equal(s?.source, "env");
    assert.equal(s?.run_id, "01RID");
    assert.equal(h.workflowState().run_id, "01RID");
    // The exact-vintage stamp (§8.3): the harness loads from source, so perkVersion() is the
    // real repo version — a real strict-X.Y.Z string, never the sentinel.
    const stamp = h.workflowState().perk_version;
    assert.equal(stamp, perkVersion());
    assert.ok(stamp !== undefined);
    assert.match(stamp, /^\d+\.\d+\.\d+$/);
    // The `v<version> loaded` toast is retired — identity is a standing footer segment
    assert.ok(!h.notifies.some((m) => m.includes("loaded")));
    assert.ok(h.footerFactory() !== null, "the perk footer factory was installed");
    const footer = h.renderFooter(80);
    assert.equal(footer.length, 1);
    assert.ok((footer[0] as string).includes("perk v"), footer[0]);
    // D5 rescinded: perk never touches the working indicator
    assert.equal(h.workingIndicators.length, 0);
    // handoff was consumed (establish-before-consume)
    const handoff = JSON.parse(
      readFileSync(join(workflowDir(cwd), "handoff", "01RID.json"), "utf8"),
    );
    assert.equal(handoff.consumed, true);
  } finally {
    h.dispose();
  }
});

test("claim: an objective-plan handoff's node link persists objective_node_claim", async () => {
  // The cold objective-plan door stashes objective_id/node_id in handoff_extra; the cold claim
  // persists them as the objective_node_claim so the implement-here exits are structurally
  // suppressed in cold factory sessions too (the warm `objective_node` tool never runs there).
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-only",
      stage: "objective-plan",
      extra: { objective_id: "7", node_id: "2.3" },
    },
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(h.workflowState().objective_node_claim, { objective: "7", node: "2.3" });
  } finally {
    h.dispose();
  }
});

test("claim: blank or half-specified handoff node links persist no claim", async () => {
  for (const extra of [
    {},
    { objective_id: "7" },
    { node_id: "2.3" },
    { objective_id: "  ", node_id: "2.3" },
    { objective_id: "7", node_id: "" },
    { objective_id: 7, node_id: 2.3 },
  ]) {
    const cwd = scaffoldRepo({
      handoff: { runId: "01RID", mode: "read-only", stage: "objective-plan", extra },
    });
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
    try {
      assert.equal(
        h.workflowState().objective_node_claim,
        undefined,
        `no claim for extra ${JSON.stringify(extra)}`,
      );
    } finally {
      h.dispose();
    }
  }
});

for (const footerId of ["pi-bar-footer", "pi-status-footer", "pi-default"]) {
  test(`footer seam: a foreign [providers] footer = "${footerId}" selection vacates installPerkFooter`, async () => {
    // Install-site (runtime) vacating: under a non-`perk-footer` selection perk does NOT install
    // its own footer (no factory captured), leaving the foreign footer (or pi's stock footer, for
    // `pi-default`) as the sole surface. The default-repo case (factory installed) is proven by
    // the `claim` test above.
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
    mkdirSync(join(cwd, ".perk"), { recursive: true });
    writeFileSync(
      join(cwd, ".perk", "config.toml"),
      `[providers]\nfooter = "${footerId}"\n`,
      "utf8",
    );
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
    try {
      assert.equal(
        h.footerFactory(),
        null,
        "perk installed no footer under a foreign footer selection",
      );
    } finally {
      h.dispose();
    }
  });
}

test("footer install: a same-activation session_start re-emit reinstalls the footer", async () => {
  // Install-per-headful-session_start (pi ≥ 0.84's explicit dispose-on-replace contract): a
  // second `session_start` on the SAME activation installs a fresh factory. Discriminating:
  // the retired once-only `footerInstalled` guard recorded exactly one install here — a
  // `reload()`-based probe cannot tell the difference (reload re-runs the extension factory,
  // resetting any module-level guard).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.equal(h.footerInstallCount(), 1, "bind installs the footer once");
    await h.emitSessionStart();
    assert.equal(h.footerInstallCount(), 2, "a same-activation session_start reinstalls");
    const footer = h.renderFooter(80);
    assert.equal(footer.length, 1, "FOOTER_MAX_LINES holds after the reinstall");
  } finally {
    h.dispose();
  }
});

test("keep: reload() re-emits session_start and preserves the run", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.equal(h.sentinel()?.source, "env");
    // reload with PERK_RUN_ID unset: the run must come from session state, not the env
    await h.reload({ PERK_RUN_ID: undefined });
    const s = h.sentinel();
    assert.equal(s?.source, "session");
    assert.equal(s?.run_id, "01RID");
    assert.equal(s?.predecessor, null);
  } finally {
    h.dispose();
  }
});

test("keep: a legacy pre-stamp session is never backfilled with perk_version", async () => {
  // The no-backfill posture (§8.3): the stamp is written only when run identity is ESTABLISHED
  // (claim/fork/adopt/mint); the keep arm appends nothing, so a pre-stamp session stays honestly
  // timestamp-estimated — an LWW backfill would mis-stamp an old session with today's version.
  const cwd = scaffoldRepo();
  // No pi_session_id -> decideClaim's keep arm re-resolves the claimed run from session state.
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.sentinel()?.source, "session");
    assert.equal(h.workflowState().run_id, "01RID");
    assert.equal(h.workflowState().perk_version, undefined);
    await h.reload({ PERK_RUN_ID: undefined });
    assert.equal(h.workflowState().run_id, "01RID");
    assert.equal(h.workflowState().perk_version, undefined);
  } finally {
    h.dispose();
  }
});

test("fork: an inherited pi_session_id derives a child run_id", async () => {
  const cwd = scaffoldRepo();
  // Planted state carries a pi_session_id that won't match this file's basename -> fork.
  const file = plantSession(cwd, [
    { run_id: "01RID", pi_session_id: "OTHER-SESSION", mode: "read-write" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const s = h.sentinel();
    assert.equal(s?.source, "fork");
    assert.equal(s?.run_id, "01RID.1");
    assert.equal(s?.predecessor, "01RID");
    assert.equal(h.workflowState().perk_version, perkVersion());
    // the child's scratch dir was isolated
    assert.ok(existsSync(runScratchDir(cwd, "01RID.1")));
  } finally {
    h.dispose();
  }
});

test("fork: the parent's node claim is inherited via LWW, never written by the fork arm", async () => {
  // Deliberate semantics (mirrors stage/mode inheritance): a fork of a planning session is
  // still that node's planning session, so the parent's `objective_node_claim` stays visible
  // through the per-field LWW rebuild and keeps the implement-here exits suppressed there —
  // clearing it on fork would reopen the no-save-exit gap in forks of positioned sessions.
  // The fork arm itself writes NO claim field (its entry carries only the derived identity).
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [
    {
      run_id: "01RID",
      pi_session_id: "OTHER-SESSION",
      mode: "read-only",
      stage: "objective-plan",
      objective_node_claim: { objective: "7", node: "2.3" },
    },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.sentinel()?.source, "fork");
    const state = h.workflowState();
    assert.equal(state.run_id, "01RID.1");
    assert.deepEqual(state.objective_node_claim, { objective: "7", node: "2.3" });
    // The fork entry itself carries no claim — the visibility above is pure LWW inheritance.
    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: Record<string, unknown>;
    }[];
    const forkEntry = entries.find(
      (entry) => entry.customType === "perk:workflow-state" && entry.data?.run_id === "01RID.1",
    );
    assert.ok(forkEntry, "the fork arm appended its identity entry");
    assert.ok(
      !("objective_node_claim" in (forkEntry.data ?? {})),
      "the fork arm writes no claim of its own",
    );
  } finally {
    h.dispose();
  }
});

test("fork: a refused child scratch redirect warns but still settles derived identity", async () => {
  const cwd = scaffoldRepo();
  const childRun = "01RID.1";
  const outside = join(cwd, "fork-redirect-target");
  mkdirSync(outside);
  mkdirSync(join(runScratchDir(cwd, childRun), ".."), { recursive: true });
  symlinkSync(outside, runScratchDir(cwd, childRun), "dir");
  const file = plantSession(cwd, [
    { run_id: "01RID", pi_session_id: "OTHER-SESSION", mode: "read-write" },
  ]);

  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().run_id, childRun);
    assert.equal(h.workflowState().predecessor, "01RID");
    assert.ok(
      h.notifyEvents.some((event) =>
        event.message.includes(`could not create fork run root for ${childRun}`),
      ),
      "scratch refusal was not reported",
    );
    assert.deepEqual(readdirSync(outside), [], "fork startup followed the child redirect");
  } finally {
    h.dispose();
  }
});

test("implement session_start records the implementation/main session pointer", async () => {
  // A cold-claimed implement run self-keys its current session file into implementation.main.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  const file = plantSession(cwd, []); // file-backed so getSessionFile() yields a real path
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    const record = readSessionPointers(cwd, "01RID");
    assert.ok(record !== null, "a session-pointers record was written");
    assert.equal(record.implementation.main?.pi_session_id, "planted-parent.jsonl");
    assert.ok((record.implementation.main?.session_file ?? "").length > 0);
    assert.equal(record.implementation.main?.parent_pi_session_id, null);
    // Self-keyed: an implement run fills only the implementation slots.
    assert.equal(record.planning.main, null);
  } finally {
    h.dispose();
  }
});

test("a non-implement stage does NOT record an implementation pointer", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    // The implementation/main capture is gated on stage === "implement"; a plan run writes none
    // here (planning.main is savePlan's job, not session_start's).
    assert.equal(readSessionPointers(cwd, "01RID"), null);
  } finally {
    h.dispose();
  }
});

test("fork: a forked implement session threads the parent session as fork provenance", async () => {
  const cwd = scaffoldRepo();
  // Planted state: an implement run forked (pi_session_id won't match this file's basename).
  const file = plantSession(cwd, [
    { run_id: "01RID", pi_session_id: "OTHER-SESSION", mode: "read-write", stage: "implement" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    // The child run id is 01RID.1; the capture inherits the parent's launched stage + threads the
    // inherited parent session id as parent_pi_session_id.
    const record = readSessionPointers(cwd, "01RID.1");
    assert.ok(record !== null);
    assert.equal(record.implementation.main?.parent_pi_session_id, "OTHER-SESSION");
  } finally {
    h.dispose();
  }
});

test("env-child: a consumed handoff makes an env-inherited session adopt, not re-claim", async () => {
  // THE regression (the /learn session-pointer shadowing defect): a subagent child inherits the
  // parent's PERK_RUN_ID via process env; its fresh session has no branch state, so pre-fix it
  // re-claimed the run — re-consuming the handoff and shadowing implementation/main.
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-write",
      stage: "implement",
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
    // The child adopted a derived identity with truthful lineage — no stage impersonation.
    const state = h.workflowState();
    assert.equal(state.run_id, "01RID.1");
    assert.equal(state.predecessor, "01RID");
    assert.equal(state.stage, undefined);
    assert.equal(state.objective_node_claim, undefined); // adopt never impersonates the claim
    assert.equal(state.perk_version, perkVersion());
    assert.equal(h.sentinel()?.source, "env-child");
    assert.ok(existsSync(runScratchDir(cwd, "01RID.1")), "the child's scratch was isolated");
    // The parent's implementation/main pointer is untouched; the child captured nothing.
    assert.deepEqual(readSessionPointers(cwd, "01RID")?.implementation.main, parentPointer);
    assert.equal(readSessionPointers(cwd, "01RID.1"), null);
    // The handoff still records the TRUE claimer (never re-consumed).
    const handoff = JSON.parse(readFileSync(handoffPath(cwd, "01RID"), "utf8"));
    assert.equal(handoff.pi_session_id, "parent.jsonl");
  } finally {
    h.dispose();
  }
});

test("env-child: a refused adopted scratch redirect warns but still settles identity", async () => {
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-write",
      stage: "implement",
      consumed: true,
      piSessionId: "parent.jsonl",
    },
  });
  const childRun = "01RID.1";
  const outside = join(cwd, "adopt-redirect-target");
  mkdirSync(outside);
  mkdirSync(join(runScratchDir(cwd, childRun), ".."), { recursive: true });
  symlinkSync(outside, runScratchDir(cwd, childRun), "dir");
  const file = plantSession(cwd, [], { fileName: "child.jsonl" });

  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.workflowState().run_id, childRun);
    assert.equal(h.workflowState().predecessor, "01RID");
    assert.ok(
      h.notifyEvents.some((event) =>
        event.message.includes(`could not create adopted run root for ${childRun}`),
      ),
      "scratch refusal was not reported",
    );
    assert.deepEqual(readdirSync(outside), [], "adopt startup followed the child redirect");
  } finally {
    h.dispose();
  }
});

test("env-child: the adopted child inherits the parent's read-only mode (gating preserved)", async () => {
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-only",
      stage: "plan",
      consumed: true,
      piSessionId: "parent.jsonl",
    },
  });
  const file = plantSession(cwd, [], { fileName: "child.jsonl" });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    const verdict = await h.emitToolCall("write", { path: "x", content: "y" });
    assert.equal(verdict?.block, true, "the adopted child blocks write");
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

test("mint: a plain warm session mints its own run_id", async () => {
  const cwd = scaffoldRepo(); // no handoff, no PERK_RUN_ID -> decideClaim's `none` arm
  // File-backed session (no planted state) so pi_session_id is recorded with the mint.
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.open(file),
  });
  try {
    const ULID_RE = /^[0-9A-HJKMNP-TV-Z]{26}$/;
    const minted = h.workflowState().run_id;
    assert.ok(minted !== undefined, "a run_id was minted");
    assert.match(minted, ULID_RE);
    assert.equal(h.workflowState().pi_session_id, "planted-parent.jsonl");
    assert.equal(h.workflowState().perk_version, perkVersion());
    const s = h.sentinel();
    assert.equal(s?.source, "mint");
    assert.equal(s?.run_id, minted);
    assert.equal(s?.predecessor, null);
    // Reload: the recorded pi_session_id matches the session file -> keep arm, no re-mint.
    await h.reload({ PERK_RUN_ID: undefined });
    assert.equal(h.sentinel()?.source, "session");
    assert.equal(h.workflowState().run_id, minted);
  } finally {
    h.dispose();
  }
});

test("version parity: a divergent PERK_CLI_VERSION emits the soft drift warning", async () => {
  // The harness loads the extension from source, so perkVersion() is the real repo
  // package.json version; a fake PERK_CLI_VERSION guarantees a mismatch -> the warning fires.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_CLI_VERSION: "9.9.9-not-real" },
  });
  try {
    assert.ok(
      h.notifies.some((m) => /version parity/.test(m)),
      `expected a version-parity warning, got ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});

test("version parity: no PERK_CLI_VERSION emits no drift warning", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.ok(
      !h.notifies.some((m) => /version parity/.test(m)),
      `expected no version-parity warning, got ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});

test("session_tree: navigateTree fires the tree-rebuild handler", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const ids = h.entryIds();
    assert.ok(ids.length > 0, "expected at least one branch entry to navigate to");
    await h.navigateTo(ids[0] as string);
    assert.equal(h.sentinel()?.source, "tree");
  } finally {
    h.dispose();
  }
});

test("command: an extension command runs to completion offline", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd });
  try {
    assert.ok(h.registeredCommands().includes("perk-selfcheck"));
    await h.invokeCommand("perk-selfcheck"); // must not throw, no model turn
  } finally {
    h.dispose();
  }
});

test("cold claim: a corrupt handoff collapses into the loud-unclaimed path (gate stays off)", async () => {
  // A truncated cold-launch blob: the intended mode is unknowable (it lives inside the unreadable
  // file), so the claim degrades to the §8.2 loud-unclaimed error — loud, non-fatal, gate OFF.
  const cwd = scaffoldRepo(); // no handoff planted
  writeFileSync(handoffPath(cwd, "01RID"), '{"run_id": "01RID", "consum', "utf8");
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    // No crash; the run stays unclaimed and the linkage error is reported.
    assert.equal(h.workflowState().run_id, undefined);
    assert.ok(
      h.notifies.some((m) => m.includes("handoff missing or mismatched")),
      `expected the loud-unclaimed linkage error, got ${JSON.stringify(h.notifies)}`,
    );
    // The sentinel proves the handler ran to completion past the gate sync.
    const s = h.sentinel();
    assert.equal(s?.source, "env");
    assert.equal(s?.run_id, null);
    // The decided posture, pinned: a failed cold claim keeps the gate OFF (we never lock a
    // corrupt read-write launch into a half-broken read-only session).
    const verdict = await h.emitToolCall("write", { path: "x", content: "y" });
    assert.equal(verdict?.block, undefined, "gate stays off on a failed cold claim");
  } finally {
    h.dispose();
  }
});

test("keep: a corrupt handoff cannot un-gate a claimed read-only session on reload", async () => {
  // THE gate regression: the mode is knowable from session state alone, so a handoff corrupted
  // AFTER a successful claim must not disturb the read-only gate on reload. Pre-fix, the bare
  // JSON.parse threw inside resolveRunStage and the gate never engaged.
  const cwd = scaffoldRepo();
  // No pi_session_id -> decideClaim's keep arm re-resolves the claimed run from session state.
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  writeFileSync(handoffPath(cwd, "01RID"), '{"run_id": "01RID", "consum', "utf8");
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const verdict = await h.emitToolCall("write", { path: "x", content: "y" });
    assert.equal(
      verdict?.block,
      true,
      "write blocked — the gate engaged despite the corrupt handoff",
    );
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some((m) => m.content === READ_ONLY_CONTEXT),
      "the read-only mode context is injected",
    );
  } finally {
    h.dispose();
  }
});

test("headless fail-safe: a missing handoff is reported, not thrown", async () => {
  const cwd = scaffoldRepo(); // no handoff planted
  // headless => ctx.hasUI === false; PERK_RUN_ID set but handoff absent -> linkage error path
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01MISS" }, headful: false });
  try {
    // loaded unclaimed, no crash, and no UI notifications in headless mode
    assert.equal(h.workflowState().run_id, undefined);
    assert.equal(h.notifies.length, 0);
    assert.equal(h.sentinel()?.source, "env"); // decision was a claim attempt that failed to verify
    // Headless installs no footer and never touches the working indicator
    assert.equal(h.footerFactory(), null);
    assert.equal(h.workingIndicators.length, 0);
  } finally {
    h.dispose();
  }
});
