// The tool-gating primitive: own-names-only activation and the read-only backstop over a fake
// host that records (and applies) every install, plus a live read-only round-trip driven through
// a REAL bound AgentSession via the harness (fully offline). See toolGating.ts.

import assert from "node:assert/strict";
import { before, test } from "node:test";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
  type ToolLoadout,
} from "@earendil-works/pi-coding-agent";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { readOnlyContext, registerToolGating, renderReadOnlyContext } from "./toolGating.ts";
import {
  discoveryFamily,
  gatedToolsFor,
  isEligible,
  isPerkTool,
  LOADOUT_HOST_NAME,
  type Mode,
  perkToolNames,
  perkToolsFor,
  REGISTRY_STAGE_IDS,
  WORKTREE_STAGES,
} from "./toolPolicy.ts";

// The derived views read the catalog: fill it the way production does before any test runs.
before(ensureToolCatalog);

type Hook = (
  event: { toolName?: string; input?: Record<string, unknown>; messages?: unknown[] },
  ctx: ExtensionContext,
) => Promise<
  | { block?: boolean; reason?: string; message?: { content: string }; messages?: unknown[] }
  | undefined
>;

/** One registered tool as the fake host reports it (`ToolInfo.sourceInfo`'s two load-bearing fields). */
type FakeTool = { name: string; source: string; path: string };

const builtin = (name: string): FakeTool => ({ name, source: "builtin", path: `builtin:${name}` });
const perkTool = (name: string): FakeTool => ({ name, source: "inline", path: "<inline:perk>" });
const engine = (name: string): FakeTool => ({
  name,
  source: "inline",
  path: "<inline:pi-subagents:prompt-runtime>",
});
const subagents = (name: string): FakeTool => ({
  name,
  source: "npm:pi-subagents@0.73.1",
  path: "/agent/npm/node_modules/pi-subagents/src/extension/index.js",
});

/** The fake host's foreign registrants: delegation, the child engine, and an unknown inline. */
const FOREIGN: readonly FakeTool[] = [
  subagents("subagent"),
  engine("structured_output"),
  engine("contact_supervisor"),
  { name: "foreign_mutator", source: "inline", path: "<inline:3>" },
];

/** The default registry: Pi's core tools, every catalogued perk tool, and the foreign set. */
function defaultRegistry(): FakeTool[] {
  return [
    ...["read", "bash", "edit", "write", "grep", "find", "ls"].map(builtin),
    ...perkToolNames().map(perkTool),
    ...FOREIGN,
  ];
}

/**
 * The default live active set: a bare session's — Pi's defaults plus every registrant's tools (a
 * discovery-family member registers direct, so it is active on registration like any perk tool).
 */
function defaultActive(registry: readonly FakeTool[]): string[] {
  return registry.map((t) => t.name).filter((name) => !["grep", "find", "ls"].includes(name));
}

/** One recorded install: the names, the live foreign set it replaced, and the host's hidden set. */
type Install = { names: string[]; liveForeign: string[]; hidden: string[] };

/**
 * The gate's fake host. Installs are recorded AND applied (the live active set follows), and
 * every install runs the gating's `prepareLoadout` the way Pi runs an active host's hook inside
 * `setActiveTools` — so each record carries what the host hid at that install. `setActive`
 * models a foreign owner's own toggle between reconciliations; `register` a late registrant.
 */
function gateFixture(
  floor: () => boolean,
  opts: { registry?: readonly FakeTool[]; active?: readonly string[] } = {},
) {
  const hooks = new Map<string, Hook>();
  let registry: FakeTool[] = [...(opts.registry ?? defaultRegistry())];
  let active: string[] = [...(opts.active ?? defaultActive(registry))];
  let fail: "snapshot" | "census" | "toolset" | "append" | undefined;
  const appends: unknown[] = [];
  const installs: Install[] = [];
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
      return registry.map((t) => ({
        name: t.name,
        sourceInfo: { source: t.source, path: t.path },
      }));
    },
    setActiveTools: (names: string[]) => {
      if (fail === "toolset") throw new Error("toolset");
      const liveForeign = active.filter((n) => !isPerkTool(n));
      active = [...names];
      const hidden = active.includes(LOADOUT_HOST_NAME) ? hiddenNow() : [];
      installs.push({ names: [...names], liveForeign, hidden });
    },
    appendEntry: (_type: string, data: unknown) => {
      if (fail === "append") throw new Error("append");
      appends.push(data);
    },
  } as unknown as ExtensionAPI;
  const gate = registerToolGating(pi, floor);
  const hiddenNow = (): string[] => {
    const declared = active.map((name) => ({ name }));
    const loadout = { declared } as unknown as ToolLoadout;
    return [...(gate.prepareLoadout(loadout).hiddenDeclarations ?? [])].sort();
  };
  const sessionManager = SessionManager.inMemory("/repo");
  sessionManager.getBranch = () => {
    throw new Error("branch unavailable");
  };
  const context: Pick<ExtensionContext, "sessionManager"> = { sessionManager };
  const ctx = context as ExtensionContext;
  return {
    gate,
    appends,
    installs,
    /** Every installed name list, in order. */
    installed: () => installs.map((i) => i.names),
    active: () => [...active],
    hidden: hiddenNow,
    fail: (value: typeof fail) => {
      fail = value;
    },
    setActive: (names: readonly string[]) => {
      active = [...names];
    },
    register: (tool: FakeTool, activate = true) => {
      registry = [...registry, tool];
      if (activate) active = [...active, tool.name];
    },
    call: (name: string, event: Parameters<Hook>[0] = {}) => hooks.get(name)?.(event, ctx),
  };
}

type Fixture = ReturnType<typeof gateFixture>;

/** The fixture's active perk names, sorted. */
function activePerk(h: Fixture): string[] {
  return h.active().filter(isPerkTool).sort();
}

/** The registered (default-registry) perk names of a view, sorted — what perk installs. */
function perkView(view: readonly string[], registry = defaultRegistry()): string[] {
  const registered = new Set(registry.map((t) => t.name));
  return view.filter((name) => registered.has(name)).sort();
}

/** Every recorded install left the live foreign active set exactly as it found it. */
function assertForeignInvariance(h: Fixture): void {
  for (const [i, install] of h.installs.entries()) {
    assert.deepEqual(
      install.names.filter((n) => !isPerkTool(n)).sort(),
      [...install.liveForeign].sort(),
      `install #${i} touched a foreign name`,
    );
  }
}

async function blockOf(h: Fixture, toolName: string, input: Record<string, unknown> = {}) {
  return h.call("tool_call", { toolName, input });
}

/**
 * The gated backstop's verdicts. `readable: false` = the registry read itself is broken: every
 * classification fails closed, so even the allowed tools are blocked.
 */
async function assertBackstop(h: Fixture, opts: { readable?: boolean } = {}) {
  assert.equal(h.gate.isActive(), true);
  for (const toolName of ["edit", "write", "plan_save", "submit", "foreign_mutator"]) {
    assert.equal((await blockOf(h, toolName))?.block, true, toolName);
  }
  assert.equal((await blockOf(h, "bash", { command: "touch x" }))?.block, true);
  for (const toolName of ["read", "structured_output", "contact_supervisor"]) {
    const verdict = await blockOf(h, toolName);
    if (opts.readable === false) assert.equal(verdict?.block, true, toolName);
    else assert.equal(verdict, undefined, toolName);
  }
  const gitStatus = await blockOf(h, "bash", { command: "git status" });
  if (opts.readable === false) assert.equal(gitStatus?.block, true);
  else assert.equal(gitStatus, undefined);
  assert.equal((await h.call("before_agent_start"))?.message?.content, readOnlyContext());
  assert.equal(
    await h.call("context", { messages: [{ customType: "perk:mode-context" }] }),
    undefined,
  );
}

/** Silence the before_agent_start reconciliation's expected error report for one block. */
async function quietly<T>(run: () => Promise<T>): Promise<T> {
  const original = console.error;
  console.error = () => {};
  try {
    return await run();
  } finally {
    console.error = original;
  }
}

test("floor enforces all observations before sync, despite snapshot/census/toolset/append failures", async () => {
  for (const mode of [undefined, "read-write"]) {
    for (const failure of ["snapshot", "census", "toolset", "append"] as const) {
      const h = gateFixture(() => true);
      await assertBackstop(h);
      // A foreign `setActiveTools` re-activated perk's gate-blocked tools, so the sync must install.
      h.setActive(defaultActive(defaultRegistry()));
      h.fail(failure);
      assert.throws(() =>
        failure === "append" ? h.gate.enter() : h.gate.syncFromState(mode, undefined),
      );
      await quietly(() => assertBackstop(h, { readable: failure !== "census" }));
      h.fail(undefined);
      h.gate.exit();
      assert.deepEqual(h.appends, [], "floor exit never appends read-write");
      h.gate.syncFromState("read-write", undefined);
      assert.deepEqual(activePerk(h), perkView(gatedToolsFor(null)));
      await assertBackstop(h);
      assertForeignInvariance(h);
    }
  }
});

test("false cannot clear inherited read-only; ordinary parents use the same backstop; read-write is unaffected", async () => {
  const h = gateFixture(() => false);
  h.gate.syncFromState("read-only", undefined);
  await assertBackstop(h);
  h.fail("toolset");
  assert.throws(() => h.gate.syncFromState("read-write", undefined));
  // Immediately after the failed release — before any later point could repair it — the host
  // still presents the gate: the writers stay hidden while enforcement holds.
  for (const name of ["edit", "write", "foreign_mutator"])
    assert.ok(h.hidden().includes(name), `${name} still hidden after the failed release`);
  await quietly(() => assertBackstop(h));
  h.fail(undefined);
  h.gate.exit();
  assert.equal(h.gate.isActive(), false);
  assert.deepEqual(h.appends, [{ mode: "read-write" }]);
  for (const toolName of ["write", "foreign_mutator", "plan_save", "submit", "bash"]) {
    assert.equal(await blockOf(h, toolName, { command: "touch x" }), undefined);
  }
  // A failed install never leaves the presentation open: the host kept presenting the gate.
  assert.equal(h.installs.at(-1)?.hidden.includes("edit"), false, "the exit presents edit again");
  assertForeignInvariance(h);
});

test("a census-read failure on a cold read-only sync stays closed, installs nothing, and the startup re-apply retakes it", async () => {
  // No floor: the ordinary cold read-only sync (a `mode: read-only` handoff) whose registry read
  // throws inside `apply()` — the in-memory gate latched before the read, so it stays closed.
  const h = gateFixture(() => false);
  const before = h.active();
  h.fail("census");
  assert.throws(() => h.gate.syncFromState("read-only", undefined));
  await quietly(() => assertBackstop(h, { readable: false }));
  assert.deepEqual(h.installs, [], "a failed read installs nothing");
  // The `resources_discover` re-apply (Pi reports the throw) does not open the gate either.
  await assert.rejects(() => h.call("resources_discover") ?? Promise.resolve());
  assert.deepEqual(h.installs, []);
  // Once the read succeeds, the same re-apply installs the gated perk subset.
  h.fail(undefined);
  await h.call("resources_discover");
  assert.equal(h.installs.length, 1);
  assert.deepEqual(activePerk(h), perkView(gatedToolsFor(null)));
  await assertBackstop(h);
  h.gate.exit();
  assert.equal(h.gate.isActive(), false);
  assert.deepEqual([...h.active()].sort(), [...before].sort(), "the exit restores the bare set");
  assert.deepEqual(h.appends, [{ mode: "read-write" }]);
  assertForeignInvariance(h);
});

test("a throwing supplier and malformed bash inputs never open the gate", async () => {
  const h = gateFixture(() => {
    throw new Error("floor read failed");
  });
  h.gate.syncFromState(undefined, undefined);
  await assertBackstop(h);
  h.gate.exit();
  assert.deepEqual(h.appends, []);
  assert.equal((await blockOf(h, "bash", { command: Object.create(null) }))?.block, true);
});

test("gated views (perk-only): every stage keeps the host and the mode-over-stage set; never a gate-blocked perk tool", () => {
  for (const stage of [null, ...REGISTRY_STAGE_IDS]) {
    const view = gatedToolsFor(stage);
    for (const tool of [
      LOADOUT_HOST_NAME,
      // The /plan flow is completable wherever the toggle lands (mode over stage).
      "plan_draft",
      "plan_review",
      "start_draft_review_wave",
      "collect_draft_review_wave",
      "push_annotations",
    ]) {
      assert.ok(view.includes(tool), `${String(stage)}: missing ${tool}`);
    }
    for (const tool of view) assert.ok(isPerkTool(tool), `${String(stage)}: ${tool} is not perk's`);
    for (const tool of ["plan_save", "objective_save", "gist_save", "submit", "land", "run_ci"]) {
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
  for (const tool of [LOADOUT_HOST_NAME, "plan_review", "objective_refinement_draft"]) {
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
  assert.deepEqual(activePerk(h), perkView(gatedToolsFor("plan")));
  const planContext = renderReadOnlyContext("plan");
  assert.equal((await h.call("before_agent_start"))?.message?.content, planContext);
  assert.deepEqual(await blockOf(h, "objective_refinement_draft"), {
    block: true,
    reason: "perk read-only mode: objective_refinement_draft is blocked (tool not allowlisted).",
  });
  assert.equal(await blockOf(h, "plan_draft"), undefined);

  h.gate.syncFromState("read-only", "objective-refine");
  assert.deepEqual(activePerk(h), perkView(gatedToolsFor("objective-refine")));
  for (const toolName of ["objective_refinement_draft", "plan_review", "read", "structured_output"])
    assert.equal(await blockOf(h, toolName), undefined, toolName);
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
      (await blockOf(h, toolName))?.block,
      true,
      `${toolName} blocked in the gated refinement stage (late-activation backstop)`,
    );
  }
  assert.equal(
    (await blockOf(h, "bash", { command: "touch x" }))?.block,
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
  assertForeignInvariance(h);
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
// Recorded-install proofs (contracts.md §8.40): perk installs only when its own names must change,
// never touches a foreign name, and its host hides exactly the ineligible declarations.
// ---------------------------------------------------------------------------

test("bare session: zero installs across every reconciliation point", async () => {
  const h = gateFixture(() => false);
  h.gate.syncFromState(undefined, undefined);
  await h.call("resources_discover");
  assert.equal(await h.call("before_agent_start"), undefined, "no mode context ungated");
  h.gate.syncFromState("read-write", undefined);
  assert.deepEqual(h.installs, []);
  // The host presents the bare landing by hiding only itself.
  assert.deepEqual(h.hidden(), [LOADOUT_HOST_NAME]);
});

test("foreign invariance: owner deactivation, initially inactive and late registration survive every point", async () => {
  // `subagent` registered but initially inactive (its owner's choice).
  const registry = defaultRegistry();
  const h = gateFixture(() => false, {
    registry,
    active: defaultActive(registry).filter((n) => n !== "subagent"),
  });
  const points = async (stage: string | undefined) => {
    h.gate.syncFromState("read-write", stage);
    h.gate.enter();
    await h.call("resources_discover");
    await h.call("before_agent_start");
    h.gate.exit();
    await h.call("before_agent_start");
  };
  await points("implement");
  assert.ok(!h.active().includes("subagent"), "never activated by perk");
  // The owner activates it, then deactivates its unknown sibling.
  h.setActive([...h.active().filter((n) => n !== "foreign_mutator"), "subagent"]);
  await points("plan");
  assert.ok(h.active().includes("subagent"), "an ineligible foreign tool is never deactivated");
  assert.ok(!h.active().includes("foreign_mutator"), "nor is a deactivated one restored");
  // A late registrant (after perk's sync) meets the landing at resources_discover — untouched.
  h.register({ name: "subagent_supervisor", source: "npm:pi-subagents@0.73.1", path: "/x" });
  await points("objective-plan");
  assert.ok(h.active().includes("subagent_supervisor"));
  assert.ok(h.installs.length > 0, "the stage changes installed perk's names");
  assertForeignInvariance(h);
});

test("the backstop: child-engine names pass under the gate; another inline path, a never-known name and an unregistered perk name are blocked", async () => {
  const registry = defaultRegistry()
    .filter((t) => t.name !== "plan_draft")
    .concat({ name: "other_inline", source: "inline", path: "<inline:other>" });
  const h = gateFixture(() => false, { registry });
  h.gate.syncFromState("read-only", "implement");
  for (const name of ["structured_output", "contact_supervisor"])
    assert.equal(await blockOf(h, name), undefined, name);
  assert.deepEqual(await blockOf(h, "other_inline"), {
    block: true,
    reason: "perk read-only mode: other_inline is blocked (tool not allowlisted).",
  });
  // plan_draft is gate-eligible (mode over stage) but this host never registered it.
  for (const name of ["never_known_tool", "plan_draft"]) {
    assert.deepEqual(await blockOf(h, name), {
      block: true,
      reason: `perk read-only mode: ${name} is blocked (tool not registered).`,
    });
  }
  assert.ok(!h.active().includes("plan_draft"), "an unregistered perk name is never installed");
});

/**
 * The declarations the host must hide for the default registry in a landing, by posture (after
 * the install every active perk name is eligible, so none is hidden).
 */
function expectedHidden(stage: string | null, mode: Mode): string[] {
  const hidden = [LOADOUT_HOST_NAME];
  if (mode === "read-only") hidden.push("edit", "write", "foreign_mutator");
  if (stage !== null && ![...WORKTREE_STAGES, "stack-review"].includes(stage)) {
    hidden.push("subagent");
  }
  return hidden.sort();
}

test("prepareLoadout: the host hides exactly the ineligible declarations per landing", () => {
  for (const [stage, mode] of [
    [null, "read-only"],
    ["implement", "read-write"],
    ["implement", "read-only"],
    ["plan", "read-write"],
    ["plan", "read-only"],
  ] as const) {
    const h = gateFixture(() => false);
    h.gate.syncFromState(mode, stage ?? undefined);
    // After the install, the live set holds only eligible perk names; the declared set is it.
    assert.deepEqual(h.hidden(), expectedHidden(stage, mode), `${String(stage)} ${mode}`);
  }
});

test("prepareLoadout sees the settled mode inside the install: a gate exit presents edit/write again in the same install", () => {
  const h = gateFixture(() => false);
  h.gate.syncFromState("read-write", "implement");
  h.gate.enter();
  const entry = h.installs.at(-1);
  assert.ok(
    entry?.hidden.includes("edit") && entry.hidden.includes("write"),
    "hidden under the gate",
  );
  h.gate.exit();
  const exit = h.installs.at(-1);
  assert.ok(exit !== entry, "the exit installed");
  assert.equal(exit?.hidden.includes("edit"), false, "edit presented in the exit's own install");
  assert.equal(exit?.hidden.includes("write"), false);
  assertForeignInvariance(h);
});

test("a mode flip that changes no perk name reinstalls the live set under an active host — and never without one", () => {
  // Only mode-over-stage perk names registered: the gated and read-write perk sets coincide.
  const flipOnly = (withHost: boolean): Fixture => {
    const registry = [
      ...["read", "bash", "edit", "write"].map(builtin),
      perkTool("plan_draft"),
      ...(withHost ? [perkTool(LOADOUT_HOST_NAME)] : []),
    ];
    return gateFixture(() => false, { registry });
  };
  const hosted = flipOnly(true);
  const live = hosted.active();
  hosted.gate.enter();
  assert.deepEqual(hosted.installed(), [live], "the gate entry re-presents the same set");
  assert.ok(hosted.installs[0]?.hidden.includes("edit"));
  hosted.gate.exit();
  assert.equal(hosted.installs.length, 2);
  assert.equal(hosted.installs[1]?.hidden.includes("edit"), false);
  // Without a registered host there is nothing to present: no install at all.
  const bare = flipOnly(false);
  bare.gate.enter();
  bare.gate.exit();
  assert.deepEqual(bare.installs, []);
});

test("codemode is suspended under the gate and restored at release; a never-active or foreign codemode is untouched", () => {
  const codemode: FakeTool = { name: "codemode", source: "builtin", path: "builtin:codemode" };
  const registry = [...defaultRegistry(), codemode];
  const h = gateFixture(() => false, {
    registry,
    active: [...defaultActive(defaultRegistry()), "codemode"],
  });
  h.gate.syncFromState("read-write", "implement");
  assert.ok(h.active().includes("codemode"), "read-write leaves it as the user had it");
  h.gate.enter();
  assert.ok(!h.active().includes("codemode"), "switched off under the gate");
  // A failed release keeps it off and the memo intact.
  h.fail("toolset");
  assert.throws(() => h.gate.exit());
  h.fail(undefined);
  assert.ok(!h.active().includes("codemode"));
  h.gate.exit();
  assert.ok(h.active().includes("codemode"), "switched back on at release");
  h.gate.exit();
  assert.equal(h.active().filter((n) => n === "codemode").length, 1, "restored once");

  // Registered but never active: the gate has nothing to suspend or restore.
  const idle = gateFixture(() => false, { registry, active: defaultActive(defaultRegistry()) });
  idle.gate.enter();
  idle.gate.exit();
  assert.ok(!idle.active().includes("codemode"));

  // A foreign tool named codemode is governed by its provenance, never suspended.
  const namesake: FakeTool = { name: "codemode", source: "npm:fake-codemode@1.0.0", path: "/x" };
  const foreign = gateFixture(() => false, {
    registry: [...defaultRegistry(), namesake],
    active: [...defaultActive(defaultRegistry()), "codemode"],
  });
  foreign.gate.enter();
  assert.ok(foreign.active().includes("codemode"));
  assertForeignInvariance(foreign);
});

// --- the discovery cohort ---------------------------------------------------------------------------

test("the cohort join: applied by the next reconciliation as ONE install (the family deactivated once); idempotent; nonparticipants keep the family", async () => {
  const family = discoveryFamily();
  assert.ok(family.length > 0, "the pilot family is catalogued");
  const outside = gateFixture(() => false);
  outside.gate.syncFromState("read-write", "implement");
  assert.deepEqual(outside.gate.discovery(), { cohort: false, family: [] });
  for (const name of family.filter((n) => isEligible(n, undefined, "implement", "read-write")))
    assert.ok(outside.active().includes(name), `a nonparticipant keeps ${name}`);

  const h = gateFixture(() => false);
  h.gate.joinDiscoveryCohort(family);
  assert.deepEqual(h.installs, [], "the join installs nothing itself");
  assert.deepEqual(h.gate.discovery(), { cohort: true, family });
  h.gate.syncFromState("read-write", "implement");
  assert.equal(h.installs.length, 1, "one install at the first sync");
  for (const name of family) assert.ok(!h.active().includes(name), `${name} deactivated`);
  assert.deepEqual(activePerk(h), perkView(perkToolsFor("implement", "read-write", true)));
  assertForeignInvariance(h);
  // A second join and every later point change nothing.
  h.gate.joinDiscoveryCohort(family);
  await h.call("resources_discover");
  await h.call("before_agent_start");
  h.gate.syncFromState("read-write", "implement");
  assert.equal(h.installs.length, 1, "no further install");
});

test("primeDeferred: a no-op outside the cohort; inside it activates the registered eligible inactive family members named, in catalog order, and they survive the points while eligible", async () => {
  const outside = gateFixture(() => false);
  outside.gate.syncFromState("read-write", "implement");
  const before = outside.installs.length;
  assert.deepEqual(outside.gate.primeDeferred(["collect_review_wave", "push_annotations"]), []);
  assert.equal(outside.installs.length, before, "no install outside the cohort");

  const h = gateFixture(() => false);
  h.gate.joinDiscoveryCohort(discoveryFamily());
  h.gate.syncFromState("read-write", "implement");
  const live = h.active();
  // Catalog order, whatever the caller's order; a non-family name is never primed.
  const expected = discoveryFamily().filter((n) =>
    ["push_annotations", "collect_review_wave"].includes(n),
  );
  assert.deepEqual(
    h.gate.primeDeferred(["push_annotations", "submit", "collect_review_wave"]),
    expected,
  );
  assert.deepEqual(h.installed().at(-1), [...live, ...expected], "one install: live + targets");
  // Already active → nothing to do, no install.
  const installs = h.installs.length;
  assert.deepEqual(h.gate.primeDeferred(["collect_review_wave"]), []);
  assert.equal(h.installs.length, installs);
  // Kept through every reconciliation point while eligible…
  h.gate.enter();
  await h.call("resources_discover");
  await h.call("before_agent_start");
  assert.ok(h.active().includes("push_annotations"), "push_annotations is gate-allowed");
  assert.ok(!h.active().includes("collect_review_wave"), "gate-blocked under the gate");
  h.gate.exit();
  assert.ok(h.active().includes("push_annotations"), "kept across the gate exit");
  // …and dropped where it is ineligible (no gist stage carries the annotation tool).
  assert.equal(isEligible("push_annotations", undefined, "gist-author", "read-write"), false);
  h.gate.syncFromState("read-write", "gist-author");
  assert.ok(!h.active().includes("push_annotations"), "dropped in gist-author");
  // Returning to an eligible landing does not bring it back: only priming or the host activates.
  h.gate.syncFromState("read-write", "implement");
  assert.ok(!h.active().includes("push_annotations"), "never re-activated by reconciliation");
  assertForeignInvariance(h);
});

test("primeDeferred skips an unregistered or ineligible name and never throws", async () => {
  const registry = defaultRegistry().filter((t) => t.name !== "push_annotations");
  const h = gateFixture(() => false, { registry });
  h.gate.joinDiscoveryCohort(discoveryFamily());
  h.gate.syncFromState("read-write", "plan");
  const installs = h.installs.length;
  assert.deepEqual(h.gate.primeDeferred(["push_annotations"]), [], "unregistered");
  assert.deepEqual(h.gate.primeDeferred(["collect_review_wave"]), [], "ineligible in plan");
  assert.equal(h.installs.length, installs);
  h.fail("toolset");
  await quietly(async () => {
    assert.deepEqual(h.gate.primeDeferred(["collect_draft_review_wave"]), [], "a failed install");
  });
  h.fail(undefined);
  assert.deepEqual(h.gate.primeDeferred(["collect_draft_review_wave"]), [
    "collect_draft_review_wave",
  ]);
});

test("a throwing install keeps the cohort deferral pending for the next point", async () => {
  const family = discoveryFamily();
  const h = gateFixture(() => false);
  h.gate.joinDiscoveryCohort(family);
  h.fail("toolset");
  assert.throws(() => h.gate.syncFromState("read-write", "implement"), /toolset/);
  for (const name of family.filter((n) => isEligible(n, undefined, "implement", "read-write")))
    assert.ok(h.active().includes(name), `${name} still active after the failed install`);
  h.fail(undefined);
  await h.call("resources_discover");
  for (const name of family) assert.ok(!h.active().includes(name), `${name} deactivated now`);
  assert.equal(h.installs.length, 1);
});

test("a member whose deferred re-registration failed stays always-declared: dropped under the gate, restored at its exit", () => {
  // deferDiscoveryFamily omits a member it could not re-register; it is still `direct`, so
  // tool_search cannot find it and only reconciliation can bring it back.
  const joined = discoveryFamily().filter((name) => name !== "objective_stack_status");
  const h = gateFixture(() => false);
  h.gate.joinDiscoveryCohort(joined);
  h.gate.syncFromState("read-write", "implement");
  assert.ok(h.active().includes("objective_stack_status"), "never deferred, so kept at the join");
  h.gate.enter();
  assert.ok(!h.active().includes("objective_stack_status"), "gate-blocked under the gate");
  h.gate.exit();
  assert.ok(h.active().includes("objective_stack_status"), "restored at the gate exit");
  assert.deepEqual(h.gate.discovery(), { cohort: true, family: joined }, "reports what deferred");
  assert.deepEqual(h.gate.primeDeferred(["objective_stack_status"]), [], "not a deferred member");
});
