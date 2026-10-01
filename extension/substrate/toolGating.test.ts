// The tool-gating primitive: pure policy matrix + a live read-only round-trip driven
// through a REAL bound AgentSession via the harness (fully offline). See toolGating.ts.

import assert from "node:assert/strict";
import { before, test } from "node:test";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import {
  LAZY_TOOL_LOADERS,
  lazyLoaderRefusalReason,
  readOnlyContext,
  registerToolGating,
  renderReadOnlyContext,
} from "./toolGating.ts";
import {
  BORROWED_TOOLS,
  FFF_SEARCH_TOOLS,
  gatedToolsFor,
  LINEAR_MUTATING_TOOLS,
  LINEAR_READ_TOOLS,
  REGISTRY_STAGE_IDS,
  SUBAGENT_CHILD_TOOLS,
  stageToolsFor,
  WEB_RESEARCH_TOOLS,
} from "./toolPolicy.ts";

// The derived views read the catalog: fill it the way production does before any test runs.
before(ensureToolCatalog);

type Hook = (
  event: { toolName?: string; input?: Record<string, unknown>; messages?: unknown[] },
  ctx: ExtensionContext,
) => Promise<{ block?: boolean; message?: { content: string }; messages?: unknown[] } | undefined>;

/** The fake host's default active (and registered) set — no lazy loader, so no lazy-owned tool. */
const FIXTURE_ACTIVE: readonly string[] = ["read", "write", "plan_save"];

/**
 * The installed gate-ON set: the allowlist minus the tools of every REGISTERED loader that the
 * owner does not currently have active.
 */
function expectedGated(list: readonly string[], active: readonly string[], registered = active) {
  const lazyOwned = new Set(
    registered.flatMap((name) =>
      Object.hasOwn(LAZY_TOOL_LOADERS, name) ? [...(LAZY_TOOL_LOADERS[name] ?? [])] : [],
    ),
  );
  return list.filter((name) => !lazyOwned.has(name) || active.includes(name));
}

/**
 * The gate's fake host. `initial` is the live active set; `registered` (default: the same names)
 * is the registry census — independent, so an owner can hide a registered tool before perk's
 * first engagement.
 */
function gateFixture(
  floor: () => boolean,
  initial: readonly string[] = FIXTURE_ACTIVE,
  registered: readonly string[] = initial,
) {
  const hooks = new Map<string, Hook>();
  // The host's live active set as the owners see it (installs are recorded, not applied, so a
  // test moves it explicitly to model an owner's toggle between reconciliations).
  let active: readonly string[] = initial;
  let fail: "snapshot" | "census" | "toolset" | "append" | undefined;
  const appends: unknown[] = [];
  const installed: string[][] = [];
  const pi = {
    on: (name: string, hook: Hook) => {
      hooks.set(name, hook);
    },
    getActiveTools: () => {
      if (fail === "snapshot") throw new Error("snapshot");
      return [...active];
    },
    getAllTools: () => {
      if (fail === "census") throw new Error("census");
      return registered.map((name) => ({ name }));
    },
    setActiveTools: (names: string[]) => {
      if (fail === "toolset") throw new Error("toolset");
      installed.push(names);
    },
    appendEntry: (_type: string, data: unknown) => {
      if (fail === "append") throw new Error("append");
      appends.push(data);
    },
  } as ExtensionAPI;
  const gate = registerToolGating(pi, floor);
  const sessionManager = SessionManager.inMemory("/repo");
  sessionManager.getBranch = () => {
    throw new Error("branch unavailable");
  };
  const context: Pick<ExtensionContext, "sessionManager"> = { sessionManager };
  const ctx = context as ExtensionContext;
  return {
    gate,
    appends,
    installed,
    fail: (value: typeof fail) => {
      fail = value;
    },
    setActive: (names: readonly string[]) => {
      active = names;
    },
    call: (name: string, event: Parameters<Hook>[0] = {}) => hooks.get(name)?.(event, ctx),
  };
}

async function assertBackstop(h: ReturnType<typeof gateFixture>) {
  assert.equal(h.gate.isActive(), true);
  for (const toolName of ["edit", "write", "plan_save", "submit", "foreign_mutator"]) {
    assert.equal((await h.call("tool_call", { toolName, input: {} }))?.block, true, toolName);
  }
  assert.equal(
    (await h.call("tool_call", { toolName: "bash", input: { command: "touch x" } }))?.block,
    true,
  );
  for (const toolName of ["read", ...SUBAGENT_CHILD_TOOLS]) {
    assert.equal(await h.call("tool_call", { toolName, input: {} }), undefined, toolName);
  }
  assert.equal(
    await h.call("tool_call", { toolName: "bash", input: { command: "git status" } }),
    undefined,
  );
  assert.equal((await h.call("before_agent_start"))?.message?.content, readOnlyContext());
  assert.equal(
    await h.call("context", { messages: [{ customType: "perk:mode-context" }] }),
    undefined,
  );
}

test("floor enforces all observations before sync, despite snapshot/census/toolset/append failures", async () => {
  for (const mode of [undefined, "read-write"]) {
    for (const failure of ["snapshot", "census", "toolset", "append"] as const) {
      const h = gateFixture(() => true);
      await assertBackstop(h);
      h.fail(failure);
      assert.throws(() =>
        failure === "append" ? h.gate.enter() : h.gate.syncFromState(mode, undefined),
      );
      await assertBackstop(h);
      h.fail(undefined);
      h.gate.exit();
      assert.deepEqual(h.appends, [], "floor exit never appends read-write");
      h.gate.syncFromState("read-write", undefined);
      assert.deepEqual(h.installed.at(-1), gatedToolsFor(null));
      await assertBackstop(h);
    }
  }
});

test("false cannot clear inherited read-only; ordinary parents use the same backstop; read-write is unaffected", async () => {
  const h = gateFixture(() => false);
  h.gate.syncFromState("read-only", undefined);
  await assertBackstop(h);
  h.fail("toolset");
  assert.throws(() => h.gate.syncFromState("read-write", undefined));
  await assertBackstop(h);
  h.fail(undefined);
  h.gate.exit();
  assert.equal(h.gate.isActive(), false);
  assert.deepEqual(h.appends, [{ mode: "read-write" }]);
  for (const toolName of ["write", "foreign_mutator", "plan_save", "submit", "bash"]) {
    assert.equal(await h.call("tool_call", { toolName, input: { command: "touch x" } }), undefined);
  }
});

test("a census-read failure on a cold read-only sync stays closed, records no half engagement, and the startup re-apply retakes it", async () => {
  // No floor: the ordinary cold read-only sync (a `mode: read-only` handoff) whose first
  // engagement read throws AFTER the snapshot read — the one path where the in-memory gate had
  // never been engaged, so fail-closed must come from `apply()` itself, not from a prior state.
  const h = gateFixture(() => false);
  h.fail("census");
  assert.throws(() => h.gate.syncFromState("read-only", undefined));
  await assertBackstop(h);
  assert.deepEqual(h.installed, [], "a half-taken engagement installs nothing");
  // The `resources_discover` re-apply (Pi reports the throw) does not open the gate either.
  await assert.rejects(() => h.call("resources_discover") ?? Promise.resolve());
  await assertBackstop(h);
  assert.deepEqual(h.installed, []);
  // The failed read recorded nothing: once it succeeds, the same re-apply takes a FRESH
  // snapshot + census and installs the gated set; the exit then restores that fresh snapshot.
  h.fail(undefined);
  await h.call("resources_discover");
  assert.deepEqual(h.installed, [gatedToolsFor(null)]);
  await assertBackstop(h);
  h.gate.exit();
  assert.equal(h.gate.isActive(), false);
  assert.deepEqual(h.installed.at(-1), ["read", "write", "plan_save"]);
  assert.deepEqual(h.appends, [{ mode: "read-write" }]);
});

test("a throwing supplier and malformed bash inputs never open the gate", async () => {
  const h = gateFixture(() => {
    throw new Error("floor read failed");
  });
  h.gate.syncFromState(undefined, undefined);
  await assertBackstop(h);
  h.gate.exit();
  assert.deepEqual(h.appends, []);
  assert.equal(
    (await h.call("tool_call", { toolName: "bash", input: { command: Object.create(null) } }))
      ?.block,
    true,
  );
});

test("gated views: every stage keeps the research families and the mode-over-stage set; never a mutating Linear tool", () => {
  for (const stage of [null, ...REGISTRY_STAGE_IDS]) {
    const view = gatedToolsFor(stage);
    for (const tool of [
      "read",
      "grep",
      "find",
      "ls",
      "bash",
      "ask_user_question",
      ...WEB_RESEARCH_TOOLS,
      ...LINEAR_READ_TOOLS,
      ...FFF_SEARCH_TOOLS,
      // The /plan flow is completable wherever the toggle lands (mode over stage).
      "plan_draft",
      "plan_review",
      "start_draft_review_wave",
      "collect_draft_review_wave",
      "push_annotations",
    ]) {
      assert.ok(view.includes(tool), `${String(stage)}: missing ${tool}`);
    }
    for (const tool of [...LINEAR_MUTATING_TOOLS, "edit", "write", "todo"]) {
      assert.ok(!view.includes(tool), `${String(stage)}: ${tool} in the gated view`);
    }
  }
});

test("gated views: each stage's carve-ins follow its own tools", () => {
  const has = (stage: string | null, tool: string) => gatedToolsFor(stage).includes(tool);
  // The gated learn-harvest / learn-dream sessions borrow objective-author.
  assert.ok(
    has("objective-author", "run_harvest_wave") && has("objective-author", "run_dream_wave"),
  );
  assert.ok(has("audit", "run_audit_wave") && !has("audit", "run_harvest_wave"));
  // The draft writers ride their own stages only.
  assert.ok(has("objective-author", "objective_draft") && !has("plan", "objective_draft"));
  assert.ok(has("gist-author", "gist_draft") && !has("objective-author", "gist_draft"));
  // The gated factory's node-transition door (the claim carrier is written only through it).
  assert.ok(
    has("objective-plan", "objective_node") && has("objective-plan", "explore_objective_node"),
  );
  assert.ok(has("implement", "objective_node") && !has("plan", "objective_node"));
  // Delegation: the worktree family + stack-review only; child-side tools everywhere but refine.
  assert.ok(
    has("implement", "subagent") && has("stack-review", "subagent") && !has("plan", "subagent"),
  );
  for (const stage of [null, ...REGISTRY_STAGE_IDS]) {
    for (const tool of SUBAGENT_CHILD_TOOLS) {
      assert.equal(has(stage, tool), stage !== "objective-refine", `${String(stage)}: ${tool}`);
    }
  }
  // Blocked tools never ride a gated view, even unscoped.
  for (const tool of ["plan_save", "objective_save", "gist_save", "submit", "land", "run_ci"]) {
    assert.ok(!has(null, tool), tool);
  }
});

test("the read-only context names each stage's carve-out writers and steers GitHub reads", () => {
  const context = readOnlyContext();
  assert.ok(context.startsWith("[READ-ONLY MODE] (unscoped)\n"));
  assert.ok(context.includes("read-only `gh` subcommands"));
  assert.ok(context.includes("never raw curl/fetch against github.com"));
  assert.ok(context.includes("- edit/write are blocked; bash is restricted"));
  assert.ok(
    context.includes("- `plan_draft` is a sanctioned bounded write: the working-plan artifact"),
  );
  const implement = renderReadOnlyContext("implement");
  assert.ok(implement.startsWith("[READ-ONLY MODE] (stage implement)\n"));
  assert.ok(implement.includes("- `objective_node` is a sanctioned bounded write"));
  assert.ok(implement.includes("- `run_librarian` is a sanctioned bounded write"));
  assert.ok(!implement.includes("`objective_draft`"));
  // An unknown stage renders the unscoped flavor.
  assert.equal(renderReadOnlyContext("no-such-stage"), context);
});

test("the bash block message keeps its two-line head and appends the reason", async () => {
  const h = gateFixture(() => true);
  const result = (await h.call("tool_call", {
    toolName: "bash",
    input: { command: "cd x && python -c 1" },
  })) as { block?: boolean; reason?: string } | undefined;
  assert.equal(result?.block, true);
  assert.equal(
    result?.reason,
    "perk read-only mode: command blocked (not allowlisted).\nCommand: cd x && python -c 1\nReason: not allowlisted: python -c 1",
  );
});

test("live round-trip: gate enforces read-only, then releases on mode=read-write", async () => {
  const cwd = scaffoldRepo();
  // Two mode entries: navigating across them flips the gate (per-field LWW rebuild + session_tree
  // re-sync). No run_id/pi_session_id -> session_start takes the warm-mint "none" path (mints a run_id).
  const file = plantSession(cwd, [{ mode: "read-only" }, { mode: "read-write" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    // The two planted mode entries lead the branch (later model/thinking entries are appended
    // by session setup); ids[0] = read-only, ids[1] = read-write.
    const ids = h.entryIds();
    const [readOnlyId, readWriteId] = ids as [string, string];

    // Full-branch rebuild = read-write (LWW last) -> gate starts OFF; writes allowed.
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);

    // Navigate to the read-only entry -> session_tree re-sync turns the gate ON.
    await h.navigateTo(readOnlyId);
    assert.equal(h.sentinel()?.mode, "read-only");

    const blockedWrite = await h.emitToolCall("write", { path: "x", content: "y" });
    assert.equal(blockedWrite?.block, true, "write blocked while read-only");
    const blockedEdit = await h.emitToolCall("edit", { path: "x" });
    assert.equal(blockedEdit?.block, true, "edit blocked while read-only");

    const blockedBash = await h.emitToolCall("bash", { command: "rm -rf build" });
    assert.equal(blockedBash?.block, true, "unsafe bash blocked while read-only");

    const safeBash = await h.emitToolCall("bash", { command: "git status" });
    assert.equal(safeBash?.block, undefined, "safe bash allowed while read-only");

    // an injection-shaped read (an exec-bearing prefix) is blocked; the safe pair still reads
    const injected = await h.emitToolCall("bash", {
      command: "GIT_EXTERNAL_DIFF=python git diff",
    });
    assert.equal(injected?.block, true, "exec-bearing environment blocked while read-only");
    const pinned = await h.emitToolCall("bash", {
      command: "GIT_OPTIONAL_LOCKS=0 git status",
    });
    assert.equal(pinned?.block, undefined, "a literal safe pair still reads");

    // Navigate back to the read-write entry -> gate turns OFF; writes allowed again.
    await h.navigateTo(readWriteId);
    assert.equal(h.sentinel()?.mode, "read-write");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);
  } finally {
    h.dispose();
  }
});

test("mode-context dedups against a prior copy on the branch (once-only per live copy)", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    { custom: { type: "perk:workflow-state", data: { run_id: "01RID", mode: "read-only" } } },
    {
      custom: {
        type: "perk:mode-context",
        data: { content: "[READ-ONLY MODE] (unscoped)\nprior copy" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === "perk:mode-context"),
      false,
      "prior unscoped copy on branch → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("mode-context is once-only per SELECTED BRANCH: a copy compaction summarized out of context does not re-inject", async () => {
  // The read-only guidance is history-scoped, not live-context-scoped: the full-branch scan is
  // the authority, so a hidden copy Pi has compacted away (it stays on the branch) still
  // suppresses. Enforcement (tool_call) never depended on the prose being readable.
  const cwd = scaffoldRepo();
  const manager = SessionManager.inMemory(cwd);
  manager.appendCustomEntry("perk:workflow-state", { run_id: "01RID", mode: "read-only" });
  manager.appendCustomMessageEntry(
    "perk:mode-context",
    "[READ-ONLY MODE] (unscoped)\nprior copy",
    false,
  );
  const kept = manager.appendMessage({
    role: "assistant",
    content: [{ type: "text", text: "recent work" }],
    api: "t",
    provider: "t",
    model: "t",
    usage: {},
    stopReason: "stop",
    timestamp: 1,
  } as never);
  manager.appendCompaction("a summary that never mentions the marker", kept, 100);
  assert.equal(
    manager
      .buildContextEntries()
      .some((entry) => entry.type === "custom_message" && entry.customType === "perk:mode-context"),
    false,
    "the copy is out of Pi's projected context",
  );
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === "perk:mode-context"),
      false,
      "the historical copy on the full branch still suppresses",
    );
    assert.equal(
      (await h.emitToolCall("write", { path: "x", content: "y" }))?.block,
      true,
      "enforcement holds regardless",
    );
  } finally {
    h.dispose();
  }
});

test("the refinement gated view: the formula keeps the least-privilege selection plus the mode-over-stage set", () => {
  const view = gatedToolsFor("objective-refine");
  for (const tool of [
    "read",
    "grep",
    "find",
    "ls",
    "bash",
    "ask_user_question",
    "plan_review",
    "objective_refinement_draft",
    ...WEB_RESEARCH_TOOLS,
    ...LINEAR_READ_TOOLS,
    ...FFF_SEARCH_TOOLS,
  ]) {
    assert.ok(view.includes(tool), `missing ${tool}`);
  }
  for (const forbidden of [
    "objective_node",
    "objective_draft",
    "gist_draft",
    "plan_save",
    "objective_save",
    "gist_save",
    "explore_objective_node",
    "run_scout_wave",
    "run_librarian",
    "subagent",
    "subagents_enable",
    ...SUBAGENT_CHILD_TOOLS,
    "edit",
    "write",
  ]) {
    assert.equal(view.includes(forbidden), false, forbidden);
  }
  // No other registry stage gains the refinement draft (the unscoped view does — inert there).
  for (const stage of REGISTRY_STAGE_IDS.filter((id) => id !== "objective-refine")) {
    assert.equal(gatedToolsFor(stage).includes("objective_refinement_draft"), false, stage);
  }
  assert.ok(gatedToolsFor(null).includes("objective_refinement_draft"));
  assert.deepEqual(gatedToolsFor("bogus"), gatedToolsFor(null));
});

test("gate ON in the refinement stage: the active set, the tool_call backstop and the mode flavor follow the stage", async () => {
  const h = gateFixture(() => false);
  // An already-gated session scoped to another stage that then enters refinement.
  h.gate.syncFromState("read-only", "plan");
  assert.deepEqual(h.installed.at(-1), gatedToolsFor("plan"));
  const planContext = renderReadOnlyContext("plan");
  assert.equal((await h.call("before_agent_start"))?.message?.content, planContext);
  assert.equal(
    (await h.call("tool_call", { toolName: "objective_refinement_draft", input: {} }))?.block,
    true,
    "the refinement draft is NOT eligible outside the refinement stage",
  );
  assert.equal(await h.call("tool_call", { toolName: "plan_draft", input: {} }), undefined);

  h.gate.syncFromState("read-only", "objective-refine");
  assert.deepEqual(h.installed.at(-1), gatedToolsFor("objective-refine"));
  assert.equal(
    await h.call("tool_call", { toolName: "objective_refinement_draft", input: {} }),
    undefined,
  );
  assert.equal(await h.call("tool_call", { toolName: "plan_review", input: {} }), undefined);
  assert.equal(await h.call("tool_call", { toolName: "read", input: {} }), undefined);
  for (const toolName of [
    "objective_node",
    "objective_draft",
    "gist_draft",
    "plan_save",
    "objective_save",
    "gist_save",
    "run_scout_wave",
    "subagent",
    "edit",
    "write",
    "foreign_mutator",
  ]) {
    assert.equal(
      (await h.call("tool_call", { toolName, input: {} }))?.block,
      true,
      `${toolName} blocked in the gated refinement stage (late-activation backstop)`,
    );
  }
  assert.equal(
    (await h.call("tool_call", { toolName: "bash", input: { command: "touch x" } }))?.block,
    true,
    "no new bash allowance",
  );
  // The flavor: its own marker (no flavor is a prefix of another) naming the stage's writers.
  const injected = (await h.call("before_agent_start"))?.message?.content;
  const refineContext = renderReadOnlyContext("objective-refine");
  assert.equal(injected, refineContext);
  assert.ok(injected?.startsWith("[READ-ONLY MODE] (stage objective-refine)\n"));
  assert.ok(
    injected?.includes(
      "- `objective_refinement_draft` is a sanctioned bounded write: the working-refinement artifact",
    ),
  );
  assert.equal(refineContext.includes("[READ-ONLY MODE] (stage plan)"), false);
  assert.equal(planContext.includes("objective_refinement_draft"), false);

  // Gate ON: only the current flavor survives in model context — the stale plan-stage block is
  // dropped; user content and marker-less mode entries are untouched.
  const stale = { customType: "perk:mode-context", content: planContext };
  const current = { customType: "perk:mode-context", content: refineContext };
  const user = { role: "user", content: "please [READ-ONLY MODE] keep me" };
  const bare = { customType: "perk:mode-context" };
  assert.deepEqual(await h.call("context", { messages: [stale, current, user, bare] }), {
    messages: [current, user, bare],
  });
  assert.equal(await h.call("context", { messages: [current, user, bare] }), undefined);

  // Gate OFF: every flavor strips (the injected type wholesale + the marker-bearing user echoes).
  h.gate.exit();
  const off = await h.call("context", {
    messages: [stale, current, { role: "user", content: "[READ-ONLY REFINEMENT MODE] echo" }, user],
  });
  assert.deepEqual(off, { messages: [] });
});

test("a resumed pre-migration refinement block is dropped while gated, never masks the current flavor, and strips on gate exit", async () => {
  const legacy = "[READ-ONLY REFINEMENT MODE]\nYou are in perk read-only mode — legacy block";
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    { custom: { type: "perk:workflow-state", data: { run_id: "01RID", mode: "read-only" } } },
    { customMessage: { type: "perk:mode-context", content: legacy } },
    { custom: { type: "perk:workflow-state", data: { stage: "objective-refine" } } },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  const modeContexts = (messages: { customType?: string; content?: unknown }[]) =>
    messages.filter((m) => m.customType === "perk:mode-context");
  try {
    const refineContext = renderReadOnlyContext("objective-refine");
    const legacyMessage = { customType: "perk:mode-context", content: legacy };
    // Gated in objective-refine: the legacy block never masks the current flavor's injection…
    const first = modeContexts(await h.emitBeforeAgentStart());
    assert.deepEqual(
      first.map((m) => m.content),
      [refineContext],
    );
    // …and the context hook drops it from model context.
    const currentMessage = { customType: "perk:mode-context", content: refineContext };
    assert.deepEqual(await h.emitContext([legacyMessage, currentMessage]), [currentMessage]);
    // Once delivered on the branch, it is never re-injected.
    h.session.sessionManager.appendCustomMessageEntry("perk:mode-context", refineContext, false);
    // A plain state entry after it is the navigation target (Pi re-selects a message entry's
    // parent when navigating to it).
    const delivered = h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      stage: "objective-refine",
    });
    assert.deepEqual(modeContexts(await h.emitBeforeAgentStart()), []);
    // A stage-less branch (gated unscoped) gets its own flavor; navigating back keeps a single
    // current block.
    const [, legacyId] = h.entryIds() as [string, string];
    await h.navigateTo(legacyId);
    assert.deepEqual(
      modeContexts(await h.emitBeforeAgentStart()).map((m) => m.content),
      [readOnlyContext()],
    );
    await h.navigateTo(delivered);
    assert.deepEqual(modeContexts(await h.emitBeforeAgentStart()), []);
    assert.deepEqual(await h.emitContext([legacyMessage, currentMessage]), [currentMessage]);
    // Gate exit strips the legacy custom and a legacy marker-bearing user echo.
    const exit = h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      mode: "read-write",
    });
    // (Appending moved the leaf onto it: navigate away and back so session_tree re-syncs.)
    await h.navigateTo(legacyId);
    await h.navigateTo(exit);
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);
    const plain = { role: "user", content: "a normal message" };
    assert.deepEqual(
      await h.emitContext([
        legacyMessage,
        { role: "user", content: "[READ-ONLY REFINEMENT MODE] echo" },
        plain,
      ]),
      [plain],
    );
  } finally {
    h.dispose();
  }
});

// ---------------------------------------------------------------------------
// Lazy-owned tools and their loaders (contracts.md §8.40): membership follows the owner's live
// selection; a loader has exactly its tools' eligibility and is refused outside it.
// ---------------------------------------------------------------------------

test("gate ON: the allowlist is a ceiling — a lazy-owned tool installs only while its owner has it selected", () => {
  const withSubagent = [...FIXTURE_ACTIVE, "subagent", "subagents_enable", "web_enable"];
  const h = gateFixture(() => false, withSubagent);
  h.gate.syncFromState("read-only", "implement");
  const installed = h.installed.at(-1) ?? [];
  assert.deepEqual(installed, expectedGated(gatedToolsFor("implement"), withSubagent));
  assert.ok(installed.includes("subagent"), "the owner-selected lazy tool is kept");
  for (const hidden of ["web_search", "source_check", "fetch_content", "get_search_content"]) {
    assert.ok(
      !installed.includes(hidden),
      `the owner-hidden lazy tool is not installed: ${hidden}`,
    );
  }
  for (const loader of Object.keys(LAZY_TOOL_LOADERS)) {
    assert.ok(installed.includes(loader), `loaders are ordinary allowlisted names: ${loader}`);
  }
});

test("no registered loader: an eager owner's tools are ordinary names — the gate restores what a stage stripped", () => {
  // An older pi-subagents (or the current one's host-probe fallback) registers `subagent`
  // eagerly and no `subagents_enable`: nothing could re-enable a stripped tool, so the gate-ON
  // view installs it by name exactly as before lazy ownership existed.
  const eager = [...FIXTURE_ACTIVE, "subagent", "web_search"];
  const h = gateFixture(() => false, eager);
  h.gate.syncFromState("read-only", undefined);
  assert.deepEqual(h.installed.at(-1), expectedGated(gatedToolsFor(null), eager));
  // Gate exit into plan strips subagent (the stage excludes delegation); unscoped re-entry
  // restores it.
  h.gate.syncFromState("read-write", "plan");
  const stripped = h.installed.at(-1) ?? [];
  assert.ok(!stripped.includes("subagent") && stripped.includes("web_search"));
  h.setActive(stripped);
  h.gate.syncFromState("read-only", undefined);
  assert.ok((h.installed.at(-1) ?? []).includes("subagent"), "re-entry restores the eager tool");
  // The same sequence with the loader registered: the stripped lazy tool stays with its owner.
  const lazy = [...eager, "subagents_enable"];
  const owned = gateFixture(() => false, lazy);
  owned.gate.syncFromState("read-write", "plan");
  owned.setActive(owned.installed.at(-1) ?? []);
  owned.gate.syncFromState("read-only", undefined);
  assert.ok(!(owned.installed.at(-1) ?? []).includes("subagent"), "a lazy tool is never restored");
});

test("gate OFF baseline: a lazy-owned snapshot member the owner hid is dropped; one it enabled later is kept; the stage filter still applies", () => {
  const start = [...FIXTURE_ACTIVE, "subagent", "web_search", "subagents_enable", "web_enable"];
  // source_check is REGISTERED from the start but hidden by its owner, so the census saw it:
  // it is never admitted, and only the live lazy-owned selection can keep it once enabled.
  const h = gateFixture(() => false, start, [...start, "source_check"]);
  h.gate.syncFromState("read-write", "implement");
  assert.deepEqual(
    h.installed.at(-1),
    start.filter((name) => name !== "plan_save"),
    "the first engagement keeps the owner's selection (the implement filter drops plan_save)",
  );
  // Between reconciliations the web owner hides web_search and the model enables source_check.
  const next = [...FIXTURE_ACTIVE, "subagent", "subagents_enable", "web_enable", "source_check"];
  h.setActive(next);
  h.gate.syncFromState("read-write", "implement");
  const implement = h.installed.at(-1) ?? [];
  assert.ok(!implement.includes("web_search"), "never restored from the snapshot once hidden");
  assert.ok(implement.includes("source_check"), "an owner-enabled lazy tool is kept");
  assert.ok(implement.includes("subagent"));
  // Stage eligibility is perk's: gist-save excludes the delegation family (loader included).
  h.gate.syncFromState("read-write", "gist-save");
  const gist = h.installed.at(-1) ?? [];
  assert.ok(!gist.includes("subagent"), "an owner-enabled lazy tool is stripped by the stage");
  assert.ok(!gist.includes("subagents_enable"), "its loader is stripped with it");
  assert.ok(gist.includes("source_check") && gist.includes("web_enable"));
  // Leaving every concern restores the baseline under the same owner-selected rule.
  h.gate.syncFromState("read-write", undefined);
  assert.deepEqual(h.installed.at(-1), next);
});

test("warm gate: a registered tool its owner hid before perk engaged, enabled by its loader, survives gate exit and a perk-only toggle", () => {
  // Bare session: the owner hid `subagent` in its own session_start, before perk's first
  // engagement (the warm /plan toggle) — absent from the snapshot, never admitted (the census
  // saw it).
  const registered = [...FIXTURE_ACTIVE, "subagent", "subagents_enable"];
  const hidden = [...FIXTURE_ACTIVE, "subagents_enable"];
  const h = gateFixture(() => false, hidden, registered);
  h.gate.enter();
  assert.ok(!(h.installed.at(-1) ?? []).includes("subagent"), "the gate honors the owner's hiding");
  const enabled = [...hidden, "subagent"];
  h.setActive(enabled);
  h.gate.exit();
  assert.deepEqual(h.installed.at(-1), enabled, "the gate exit keeps the loader-enabled tool");
  h.gate.enter();
  assert.ok((h.installed.at(-1) ?? []).includes("subagent"), "kept under the gate's ceiling");
  h.gate.exit();
  assert.deepEqual(h.installed.at(-1), enabled, "and again after a perk-only toggle");
});

test("the loader refusal: stage-naming reasons under the gate and under stage scoping", async () => {
  const subagentsGated =
    "perk read-only mode: subagents_enable is blocked (its tools — subagent — are not allowlisted in the gated objective-refine session).";
  const subagentsStage =
    "perk stage scoping: subagents_enable is blocked (its tools — subagent — are not available in the gist-save stage).";
  const call = async (h: ReturnType<typeof gateFixture>, toolName: string) =>
    (await h.call("tool_call", { toolName, input: {} })) as
      | { block?: boolean; reason?: string }
      | undefined;

  // Gate ON, refinement: the delegation loader is refused by name; the web loader passes.
  const refine = gateFixture(() => false);
  refine.gate.syncFromState("read-only", "objective-refine");
  assert.deepEqual(await call(refine, "subagents_enable"), {
    block: true,
    reason: subagentsGated,
  });
  assert.equal(await call(refine, "web_enable"), undefined);

  // Gate ON in a worktree stage and unscoped: the gated view carries both loaders.
  for (const stage of ["implement", undefined]) {
    const gated = gateFixture(() => false);
    gated.gate.syncFromState("read-only", stage);
    for (const loader of Object.keys(LAZY_TOOL_LOADERS)) {
      assert.equal(await call(gated, loader), undefined, `${loader} passes gated in ${stage}`);
    }
  }

  // Gate OFF, gist-save: stage scoping refuses the delegation loader; the web loader passes.
  const gist = gateFixture(() => false);
  gist.gate.syncFromState("read-write", "gist-save");
  assert.deepEqual(await call(gist, "subagents_enable"), { block: true, reason: subagentsStage });
  assert.equal(await call(gist, "web_enable"), undefined);
  assert.equal(await call(gist, "constructor"), undefined, "a prototype key is never a loader");

  // Gate OFF, no stage or an unknown stage: never refused (fail-open).
  for (const stage of [undefined, "future-stage", "constructor"]) {
    const open = gateFixture(() => false);
    open.gate.syncFromState("read-write", stage);
    for (const loader of Object.keys(LAZY_TOOL_LOADERS)) {
      assert.equal(await call(open, loader), undefined, `${loader} passes in ${stage}`);
    }
  }

  // The unscoped gated wording is unreachable by today's loaders — pinned through the format.
  assert.equal(
    lazyLoaderRefusalReason("web_enable", { kind: "gated", stage: null }),
    "perk read-only mode: web_enable is blocked (its tools — web_search, source_check, fetch_content, get_search_content — are not allowlisted in this gated session).",
  );
  assert.equal(
    lazyLoaderRefusalReason("subagents_enable", { kind: "gated", stage: "objective-refine" }),
    subagentsGated,
  );
  assert.equal(
    lazyLoaderRefusalReason("subagents_enable", { kind: "stage", stage: "gist-save" }),
    subagentsStage,
  );
});

test("LAZY_TOOL_LOADERS: each loader and its tools are borrowed, and a loader's eligibility equals its tools' everywhere", () => {
  const lists: [string, readonly string[]][] = [
    ["gatedToolsFor(null)", gatedToolsFor(null)],
    ...REGISTRY_STAGE_IDS.flatMap((stage): [string, readonly string[]][] => [
      [`gatedToolsFor(${stage})`, gatedToolsFor(stage)],
      [`stageToolsFor(${stage})`, stageToolsFor(stage) ?? []],
    ]),
  ];
  assert.ok(Object.keys(LAZY_TOOL_LOADERS).length > 0);
  for (const [loader, tools] of Object.entries(LAZY_TOOL_LOADERS)) {
    assert.ok(tools.length > 0, `${loader} enables at least one tool`);
    for (const name of [loader, ...tools]) {
      assert.ok(BORROWED_TOOLS.includes(name), `${name} must be in BORROWED_TOOLS`);
    }
    for (const [label, list] of lists) {
      assert.equal(
        list.includes(loader),
        tools.every((tool) => list.includes(tool)),
        `${label}: ${loader} must be eligible exactly where ${tools.join(", ")} are`,
      );
    }
  }
});
