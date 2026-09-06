import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
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
  isAgentScratchEligible,
  REPORT_ONLY_CHILD_AGENTS,
  registerAgentScratch,
  renderAgentScratchBlock,
} from "./agentScratch.ts";
import { agentScratchDir, ensureRunScratch } from "./cache.ts";
import type { ChildIdentity, ChildIdentitySnapshot } from "./childIdentity.ts";

function fakeCtx(cwd: string, entries: unknown[]): AgentScratchContext {
  return {
    cwd,
    hasUI: false,
    ui: { notify: () => {} },
    sessionManager: { getBranch: () => entries },
  };
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

test("registered scratch hooks implement the ten-report and unavailable fallback matrix, gate first", async () => {
  const names = [
    ...REPORT_ONLY_CHILD_AGENTS,
    "perk.conflict-resolver",
    "perk-dev.analyst",
    "custom.reporter",
    "reader",
    "PERK.PR-REVIEWER",
  ];
  const identities: ChildIdentity[] = [
    ...names.map((name) => ({
      status: "available" as const,
      name,
      provenance: "native-system-prompt-prefix" as const,
    })),
    ...(["absent", "malformed", "unreadable", "stale"] as const).map((reason) => ({
      status: "unavailable" as const,
      reason,
      provenance: "native-system-prompt-prefix" as const,
    })),
  ];
  type Hook = (
    event: { messages: { customType?: string; content?: unknown }[] },
    ctx: ExtensionContext,
  ) => Promise<{ messages?: unknown[]; message?: unknown } | undefined>;
  const block = renderAgentScratchBlock("/repo", "RID");
  for (const identity of identities)
    for (const runner of [false, true])
      for (const readOnly of [false, true]) {
        const hooks = new Map<string, Hook>();
        let provisions = 0;
        let lookups = 0;
        const snapshot: ChildIdentitySnapshot = { identity, runner };
        const expected =
          !readOnly &&
          (identity.status === "available"
            ? !REPORT_ONLY_CHILD_AGENTS.some((name) => name === identity.name)
            : !runner);
        assert.equal(isAgentScratchEligible(readOnly, snapshot), expected);
        registerAgentScratch(
          {
            on: (name: string, hook: Hook) => {
              hooks.set(name, hook);
            },
          } as ExtensionAPI,
          {
            resolve: () => {
              provisions++;
              return block;
            },
          },
          () => {
            lookups++;
            return snapshot;
          },
          () => readOnly,
        );
        const ctx = fakeCtx("/repo", []) as ExtensionContext;
        const before = await hooks.get("before_agent_start")?.({ messages: [] }, ctx);
        assert.equal(
          provisions,
          expected ? 1 : 0,
          `before hook ${JSON.stringify(snapshot)} gated=${readOnly}`,
        );
        assert.equal(before?.message !== undefined, expected);
        const context = await hooks.get("context")?.(
          { messages: [{ customType: AGENT_SCRATCH_CONTEXT_TYPE, content: block.content }] },
          ctx,
        );
        assert.equal(
          provisions,
          expected ? 2 : 0,
          "context hook must not provision ineligible turns",
        );
        assert.equal(context?.messages?.length, expected ? 1 : 0);
        assert.equal(lookups, readOnly ? 0 : 2, "effective gate is consulted before identity");
      }
});

test("legacy-only and bindings-only names are ignored; unavailable foreground is not an enforcement claim", async () => {
  for (const runner of [false, true]) {
    const cwd = scaffoldRepo();
    const h = await loadPerkSession({
      cwd,
      systemPrompt: "No native prefix here.",
      env: {
        PI_SUBAGENT_CHILD: runner ? "1" : undefined,
        PI_SUBAGENT_CHILD_AGENT: "perk.conflict-resolver",
        PI_SUBAGENT_EXTENSION_BINDINGS: '{"unrelated.identity/1":{"name":"perk.pr-reviewer"}}',
      },
    });
    try {
      assert.equal(scratchMessages(await h.emitBeforeAgentStart()).length, runner ? 0 : 1);
      assert.equal(h.workflowState().mode, undefined, "neither name claim grants authority");
      assert.equal(
        h.notifies.filter((message) => message.includes("child identity")).length,
        runner ? 1 : 0,
      );
    } finally {
      h.dispose();
    }
  }
});

test("the report-only classification is pinned to every canonical agents/*.md definition", () => {
  const agentDir = join(import.meta.dirname, "..", "..", "agents");
  const files = readdirSync(agentDir)
    .filter((name) => name.endsWith(".md"))
    .sort();
  const reportOnlyNames = REPORT_ONLY_CHILD_AGENTS.filter((name) => name.startsWith("perk."))
    .map((name) => name.slice("perk.".length))
    .sort();
  const auditor = readFileSync(
    join(agentDir, "..", ".pi", "agents", "perk-dev", "session-auditor.md"),
    "utf8",
  );
  assert.ok(REPORT_ONLY_CHILD_AGENTS.includes("perk-dev.session-auditor"));
  assert.match(auditor, /^name: session-auditor$/m);
  assert.match(auditor, /^package: perk-dev$/m);
  assert.match(auditor, /^tools: read, grep, find, ls, bash$/m);
  assert.deepEqual(
    files,
    [...reportOnlyNames, "conflict-resolver"].sort().map((name) => `${name}.md`),
    "a canonical agent was added or removed without an explicit scratch-eligibility decision",
  );

  for (const file of files) {
    const source = readFileSync(join(agentDir, file), "utf8");
    const tools = source.match(/^tools: (.+)$/m)?.[1];
    const name = file.slice(0, -".md".length);
    assert.equal(
      tools,
      name === "conflict-resolver"
        ? "read, grep, find, ls, bash, edit, write"
        : "read, grep, find, ls, bash",
      `${name} changed tool posture without revisiting scratch eligibility`,
    );
  }
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

test("read-only/report-only contexts strip guidance; a gate exit and unknown child enable it", async () => {
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

  const reportCwd = scaffoldRepo();
  const reportFile = plantSession(reportCwd, [{ run_id: "RID", mode: "read-write" }]);
  const report = await loadPerkSession({
    cwd: reportCwd,
    sessionManager: SessionManager.open(reportFile),
    systemPrompt: '<active_agent name="perk.review-classifier"/>\n\nReport rubric',
  });
  try {
    assert.equal(scratchMessages(await report.emitBeforeAgentStart()).length, 0);
  } finally {
    report.dispose();
  }

  const customCwd = scaffoldRepo();
  const customFile = plantSession(customCwd, [{ run_id: "RID", mode: "read-write" }]);
  const custom = await loadPerkSession({
    cwd: customCwd,
    sessionManager: SessionManager.open(customFile),
    systemPrompt: '<active_agent name="custom.agent"/>\n\nCustom rubric',
  });
  try {
    assert.equal(scratchMessages(await custom.emitBeforeAgentStart()).length, 1);
  } finally {
    custom.dispose();
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
