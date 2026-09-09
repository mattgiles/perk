import assert from "node:assert/strict";
import { existsSync, rmSync, statSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { loadPerkSession, plantSession, scaffoldRepo } from "../testing/harness.ts";
import {
  AGENT_SCRATCH_CONTEXT_TYPE,
  type AgentScratchContext,
  createAgentScratchProvisioner,
  registerAgentScratch,
  renderAgentScratchBlock,
} from "./agentScratch.ts";
import { agentScratchDir, ensureRunScratch } from "./cache.ts";

/** A structural hook ctx: the full branch (run identity) + Pi's projection (dedup). */
function fakeCtx(
  cwd: string,
  entries: unknown[],
  projection: () => unknown[] = () => [],
): AgentScratchContext & { sessionManager: { buildContextEntries(): unknown[] } } {
  return {
    cwd,
    hasUI: false,
    ui: { notify: () => {} },
    sessionManager: { getBranch: () => entries, buildContextEntries: projection },
  };
}

type ScratchHook = (
  event: { prompt?: string; messages?: { customType?: string; content?: unknown }[] },
  ctx: ExtensionContext,
) => Promise<{ messages?: unknown[]; message?: { content?: unknown } } | undefined>;

/** Register the scratch hooks through a `pi.on` recorder with a scripted provisioner. */
function scratchHooks(resolve: () => ReturnType<typeof renderAgentScratchBlock> | null): {
  hooks: Map<string, ScratchHook>;
  provisions: () => number;
} {
  const hooks = new Map<string, ScratchHook>();
  let provisions = 0;
  registerAgentScratch(
    {
      on: (name: string, hook: ScratchHook) => {
        hooks.set(name, hook);
      },
    } as unknown as ExtensionAPI,
    {
      resolve: () => {
        provisions++;
        return resolve();
      },
    },
    () => true,
  );
  return { hooks, provisions: () => provisions };
}

function scratchMessages(messages: { customType?: string; content?: unknown }[]) {
  return messages.filter((message) => message.customType === AGENT_SCRATCH_CONTEXT_TYPE);
}

test("rendering names the repository-relative current-run path and non-authoritative posture", () => {
  const block = renderAgentScratchBlock("/repo", "RID.2");
  assert.equal(block.path, ".perk/workflow/scratch/runs/RID.2/agent");
  assert.match(block.marker, /run=RID\.2/);
  assert.ok(block.content.startsWith(block.marker));
  assert.match(block.content, /instead of shared `\/tmp`/);
  assert.match(block.content, /descriptive, non-colliding names/);
  assert.match(block.content, /non-authoritative/);
  assert.match(block.content, /re-read canonical repository or backend sources/);
});

test("the provisioner is silent without identity and suppresses/retries warnings per run", () => {
  const cwd = scaffoldRepo();
  let attempts = 0;
  const warnings: string[] = [];
  const provisioner = createAgentScratchProvisioner({
    ensure: () => {
      attempts += 1;
      if (attempts !== 3) throw new Error(`failure ${attempts}`);
      return "/unused";
    },
    warn: (_ctx, runId, error) => warnings.push(`${runId}: ${String(error)}`),
  });

  assert.equal(provisioner.resolve(fakeCtx(cwd, [])), null);
  assert.equal(attempts, 0);

  const ctx = fakeCtx(cwd, [
    { type: "custom", customType: "perk:workflow-state", data: { run_id: "RID" } },
  ]);
  assert.equal(provisioner.resolve(ctx), null);
  assert.equal(provisioner.resolve(ctx), null);
  assert.equal(warnings.length, 1, "repeat failure in one activation is suppressed");
  assert.ok(provisioner.resolve(ctx) !== null, "a later retry succeeds");
  assert.equal(provisioner.resolve(ctx), null);
  assert.equal(warnings.length, 2, "success clears suppression for a later failure");
});

test("a write-capable turn provisions 0700 scratch before injecting one hidden block", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-write" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined, PI_SUBAGENT_CHILD_AGENT: undefined },
  });
  try {
    assert.equal(existsSync(agentScratchDir(cwd, "RID")), false);
    const injected = await h.emitBeforeAgentStart();
    assert.equal(scratchMessages(injected).length, 1);
    assert.equal(statSync(agentScratchDir(cwd, "RID")).mode & 0o777, 0o700);
  } finally {
    h.dispose();
  }
});

test("dedup still provisions a current-run directory deleted outside the session", async () => {
  const cwd = scaffoldRepo();
  const block = renderAgentScratchBlock(cwd, "RID");
  const manager = SessionManager.inMemory(cwd);
  manager.appendCustomEntry("perk:workflow-state", { run_id: "RID", mode: "read-write" });
  manager.appendCustomMessageEntry(AGENT_SCRATCH_CONTEXT_TYPE, block.content, false);
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    rmSync(agentScratchDir(cwd, "RID"), { recursive: true, force: true });
    const injected = await h.emitBeforeAgentStart();
    assert.equal(scratchMessages(injected).length, 0, "the retained exact block deduplicates");
    assert.equal(existsSync(agentScratchDir(cwd, "RID")), true, "the directory is repaired first");
  } finally {
    h.dispose();
  }
});

test("a child run replaces inherited parent guidance and keeps only one exact live block", async () => {
  const cwd = scaffoldRepo();
  const parent = renderAgentScratchBlock(cwd, "PARENT");
  const child = renderAgentScratchBlock(cwd, "PARENT.1");
  const manager = SessionManager.inMemory(cwd);
  manager.appendCustomEntry("perk:workflow-state", {
    run_id: "PARENT.1",
    mode: "read-write",
  });
  manager.appendCustomMessageEntry(AGENT_SCRATCH_CONTEXT_TYPE, parent.content, false);
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.deepEqual(
      scratchMessages(injected).map((message) => message.content),
      [child.content],
    );

    const surviving = await h.emitContext([
      { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: parent.content },
      { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: child.content },
      { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: child.content },
      { role: "user", content: "normal" },
    ]);
    assert.deepEqual(
      surviving.filter((message) => message.customType === AGENT_SCRATCH_CONTEXT_TYPE),
      [{ customType: AGENT_SCRATCH_CONTEXT_TYPE, content: child.content }],
    );
    assert.equal(
      surviving.some((message) => message.content === "normal"),
      true,
    );
  } finally {
    h.dispose();
  }
});

test("compaction re-injects a dropped block but deduplicates a retained block", async () => {
  for (const retained of [false, true]) {
    const cwd = scaffoldRepo();
    const block = renderAgentScratchBlock(cwd, "RID");
    const manager = SessionManager.inMemory(cwd);
    manager.appendCustomEntry("perk:workflow-state", { run_id: "RID", mode: "read-write" });
    const blockId = manager.appendCustomMessageEntry(
      AGENT_SCRATCH_CONTEXT_TYPE,
      block.content,
      false,
    );
    const recentId = manager.appendCustomEntry("test:recent", {});
    manager.appendCompaction("summary", retained ? blockId : recentId, 100);
    const h = await loadPerkSession({
      cwd,
      sessionManager: manager,
      env: { PERK_RUN_ID: undefined },
    });
    try {
      const injected = await h.emitBeforeAgentStart();
      assert.equal(scratchMessages(injected).length, retained ? 0 : 1);
    } finally {
      h.dispose();
    }
  }
});

test("quoted compaction prose may retain an old path but is not live scratch guidance", async () => {
  const cwd = scaffoldRepo();
  const parent = renderAgentScratchBlock(cwd, "PARENT");
  const child = renderAgentScratchBlock(cwd, "PARENT.1");
  const quotedSummary = `Earlier context included:\n${parent.content}`;
  const manager = SessionManager.inMemory(cwd);
  const stateId = manager.appendCustomEntry("perk:workflow-state", {
    run_id: "PARENT.1",
    mode: "read-write",
  });
  manager.appendCompaction(quotedSummary, stateId, 100);
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.deepEqual(
      scratchMessages(injected).map((message) => message.content),
      [child.content],
      "quoted summary prose does not deduplicate the current direct block",
    );

    const surviving = await h.emitContext([
      { role: "compactionSummary", content: quotedSummary },
      { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: parent.content },
      { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: child.content },
    ]);
    assert.deepEqual(surviving, [
      { role: "compactionSummary", content: quotedSummary },
      { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: child.content },
    ]);
  } finally {
    h.dispose();
  }
});

test("read-only contexts strip guidance; a gate exit enables it", async () => {
  const cwd = scaffoldRepo();
  const block = renderAgentScratchBlock(cwd, "RID");
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-only" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined, PI_SUBAGENT_CHILD_AGENT: undefined },
  });
  try {
    assert.equal(scratchMessages(await h.emitBeforeAgentStart()).length, 0);
    assert.equal(existsSync(agentScratchDir(cwd, "RID")), false);
    const quoted = { role: "compactionSummary", content: `Quoted scratch: ${block.content}` };
    assert.deepEqual(
      await h.emitContext([
        { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: block.content },
        { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: block.content },
        { customType: AGENT_SCRATCH_CONTEXT_TYPE, content: "stale" },
        quoted,
      ]),
      [quoted],
      "ineligible cleanup is direct-only, including current, duplicate and stale blocks",
    );

    const entry = h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      mode: "read-write",
    });
    await h.navigateTo("c0");
    await h.navigateTo(entry);
    assert.equal(
      (await h.emitToolCall("write", {}))?.block,
      undefined,
      "tree rebuild releases the gate",
    );
    assert.equal(scratchMessages(await h.emitBeforeAgentStart()).length, 1, "gate exit enables it");
  } finally {
    h.dispose();
  }
});

test("a runner child provisions no scratch even without a floor", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-write" }]);
  const runner = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PI_SUBAGENT_CHILD: "1" },
  });
  try {
    assert.equal((await runner.emitToolCall("write", {}))?.block, undefined, "no packet, no floor");
    assert.equal(scratchMessages(await runner.emitBeforeAgentStart()).length, 0);
    assert.deepEqual(
      await runner.emitContext([{ customType: AGENT_SCRATCH_CONTEXT_TYPE, content: "stale" }]),
      [],
    );
    assert.equal(existsSync(agentScratchDir(cwd, "RID")), false);
  } finally {
    runner.dispose();
  }

  const parent = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(scratchMessages(await parent.emitBeforeAgentStart()).length, 1);
  } finally {
    parent.dispose();
  }
});

test("a filesystem failure warns and continues, then a later turn recovers", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-write" }]);
  ensureRunScratch(cwd, "RID");
  writeFileSync(agentScratchDir(cwd, "RID"), "blocker");
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const first = await h.emitBeforeAgentStart();
    assert.equal(scratchMessages(first).length, 0);
    assert.equal(
      h.notifyEvents.filter((event) => event.message.includes("agent scratch")).length,
      1,
    );

    rmSync(agentScratchDir(cwd, "RID"));
    const recovered = await h.emitBeforeAgentStart();
    assert.equal(scratchMessages(recovered).length, 1);
    assert.equal(existsSync(agentScratchDir(cwd, "RID")), true);
  } finally {
    h.dispose();
  }
});

test("dedup requires the exact owned custom string in Pi's projection — nothing looser", async () => {
  const cwd = "/repo";
  const block = renderAgentScratchBlock(cwd, "RID");
  const changed = renderAgentScratchBlock(cwd, "RID.1");
  const at = "2025-01-01T00:00:00.000Z";
  const customMessage = (content: unknown, customType = AGENT_SCRATCH_CONTEXT_TYPE) => ({
    type: "custom_message",
    id: "cm",
    parentId: null,
    timestamp: at,
    customType,
    content,
    display: false,
  });
  const userMessage = (content: unknown) => ({
    type: "message",
    id: "u",
    parentId: null,
    timestamp: at,
    message: { role: "user", content, timestamp: 1 },
  });
  const cases: { name: string; entries: unknown[]; dedups: boolean }[] = [
    { name: "owned exact string", entries: [customMessage(block.content)], dedups: true },
    {
      name: "same marker, changed bytes",
      entries: [customMessage(`${block.content} `)],
      dedups: false,
    },
    { name: "a parent run's block", entries: [customMessage(changed.content)], dedups: false },
    { name: "marker-only match", entries: [customMessage(block.marker)], dedups: false },
    {
      name: "the exact bytes as a text-part array",
      entries: [customMessage([{ type: "text", text: block.content }])],
      dedups: false,
    },
    { name: "an exact USER quote", entries: [userMessage(block.content)], dedups: false },
    {
      name: "the exact bytes under another customType",
      entries: [customMessage(block.content, "perk:other")],
      dedups: false,
    },
    {
      // Pi's `buildContextEntries()` returns custom STATE entries too; its converter projects
      // no message for them — `data.content` is state, never model delivery.
      name: "plain custom state (`data.content`) selected by Pi but never projected",
      entries: [
        {
          type: "custom",
          id: "st",
          parentId: null,
          timestamp: at,
          customType: AGENT_SCRATCH_CONTEXT_TYPE,
          data: { content: block.content },
        },
      ],
      dedups: false,
    },
  ];
  for (const { name, entries, dedups } of cases) {
    const { hooks } = scratchHooks(() => block);
    const ctx = fakeCtx(
      cwd,
      [
        { type: "custom", customType: "perk:workflow-state", data: { run_id: "RID" } },
        {
          type: "custom",
          customType: AGENT_SCRATCH_CONTEXT_TYPE,
          data: { content: block.content },
        },
      ],
      () => entries,
    ) as unknown as ExtensionContext;
    const result = await hooks.get("before_agent_start")?.({ prompt: "" }, ctx);
    assert.equal(result?.message === undefined, dedups, name);
    if (!dedups) assert.equal(result?.message?.content, block.content, name);
  }
});

test("provisioning runs before dedup AND before a projection read; a projection failure escapes the hook", async () => {
  const block = renderAgentScratchBlock("/repo", "RID");
  const order: string[] = [];
  const { hooks, provisions } = scratchHooks(() => {
    order.push("provision");
    return block;
  });
  const throwing = fakeCtx("/repo", [], () => {
    order.push("projection");
    throw new Error("adversarial projection read");
  }) as unknown as ExtensionContext;
  await assert.rejects(
    hooks.get("before_agent_start")?.({ prompt: "" }, throwing) ?? Promise.resolve(),
    /adversarial projection read/,
    "the read failure reaches the hook boundary — no guessed copy",
  );
  assert.deepEqual(order, ["provision", "projection"], "the directory is repaired first");
  assert.equal(provisions(), 1);

  // A provisioning failure (null block) settles the turn before any projection read.
  order.length = 0;
  const { hooks: failing } = scratchHooks(() => {
    order.push("provision");
    return null;
  });
  assert.equal(await failing.get("before_agent_start")?.({ prompt: "" }, throwing), undefined);
  assert.deepEqual(order, ["provision"], "no block → no projection read");

  // The context filter never reads the projection (it filters what Pi hands it).
  order.length = 0;
  const { hooks: filtering } = scratchHooks(() => {
    order.push("provision");
    return block;
  });
  const kept = await filtering.get("context")?.(
    { messages: [{ customType: AGENT_SCRATCH_CONTEXT_TYPE, content: block.content }] },
    throwing,
  );
  assert.equal(kept?.messages?.length, 1);
  assert.deepEqual(order, ["provision"], "the strip provisions but never projects");
});
