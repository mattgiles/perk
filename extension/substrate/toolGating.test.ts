// The tool-gating primitive: pure policy matrix + a live read-only round-trip driven
// through a REAL bound AgentSession via the harness (fully offline). See toolGating.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
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
import {
  BORROWED_TOOLS,
  FFF_SEARCH_TOOLS,
  gatedToolsFor,
  LAZY_TOOL_LOADERS,
  LINEAR_READ_TOOLS,
  lazyLoaderRefusalReason,
  READ_ONLY_CONTEXT,
  READ_ONLY_TOOLS,
  REFINEMENT_READ_ONLY_CONTEXT,
  REFINEMENT_READ_ONLY_TOOLS,
  registerToolGating,
  STAGE_TOOLS,
  SUBAGENT_CHILD_TOOLS,
  WEB_RESEARCH_TOOLS,
} from "./toolGating.ts";

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
  assert.equal((await h.call("before_agent_start"))?.message?.content, READ_ONLY_CONTEXT);
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
      assert.deepEqual(h.installed.at(-1), READ_ONLY_TOOLS);
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
  assert.deepEqual(h.installed, [READ_ONLY_TOOLS]);
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

test("READ_ONLY_TOOLS: the exact recomposed set + order", () => {
  // The family-constant recomposition is STRUCTURAL: set and order stay byte-identical to the
  // pre-extraction literals (+ the deliberate delegation carve-in at the tail). An exact
  // deepEqual guards both.
  assert.deepEqual(READ_ONLY_TOOLS, [
    "read",
    "grep",
    "find",
    "ls",
    "bash",
    "ask_user_question",
    "plan_review",
    "plan_draft",
    "objective_draft",
    "gist_draft",
    "objective_node",
    "web_search",
    "code_search",
    "fetch_content",
    "get_search_content",
    "source_check",
    "web_enable",
    "ollama_web_search",
    "ollama_web_fetch",
    "web_fetch",
    "linear_whoami",
    "linear_workspace_metadata",
    "linear_list_teams",
    "linear_get_team",
    "linear_list_users",
    "linear_get_user",
    "linear_list_issues",
    "linear_get_issue",
    "linear_search_issues",
    "linear_list_my_issues",
    "linear_list_projects",
    "linear_get_project",
    "linear_list_issue_statuses",
    "linear_get_issue_status",
    "linear_list_labels",
    "linear_list_cycles",
    "linear_list_documents",
    "linear_get_document",
    "linear_list_comments",
    // FFF local search (both mode name-sets; the override names find/grep are above).
    "fffind",
    "ffgrep",
    "fff-multi-grep",
    "multi_grep",
    // The delegation carve-in (the gated flows' spawn surface) + pi-subagents' lazy loader.
    "subagent",
    "subagents_enable",
    "wait",
    "subagent_supervisor",
    "intercom",
    // The explorer-wave carve-in (the gated objective-plan explore tool).
    "explore_objective_node",
    // The scout-wave carve-in (the authoring sessions' launcher; read-only perk.scout lanes over
    // the delegation family, no worktree writes).
    "run_scout_wave",
    // The library-writer carve-in (the parent stays gated; only the perk.librarian child writes,
    // only the gitignored library, proven by the end-state bracket).
    "run_librarian",
    // The child-side carve-in (gated adopt-children keep the engine's injected tools — perk's
    // own waves spawn bridge-off so `contact_supervisor` is absent there, but an ad-hoc gated
    // child with an active bridge must keep its supervisor door).
    "structured_output",
    "contact_supervisor",
    // The draft-review-door carve-in (plan-authoring sessions run gated; the
    // /plan-review-browser companions must stay reachable).
    "push_annotations",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    // The audit-wave carve-in (the gated audit-judge session's wave call; write target bound
    // to the cold door's workflow-state audit_bundle_dir — no caller-supplied path exists).
    "run_audit_wave",
    // The harvest-wave carve-in (the gated learn-harvest session's wave call; the manifest
    // read is bound to the claimed run-scoped scratch path — any other path refused).
    "run_harvest_wave",
    // The dream-wave carve-in (the gated learn-dream session's wave call; NO parameters — the
    // manifest read AND the fixed-name bundle write are both derived from the claimed run's
    // manifest path, the no-aimable-writer posture on both sides).
    "run_dream_wave",
  ]);
});

test("READ_ONLY_TOOLS: contains run_harvest_wave (the gated learn-harvest session's wave call)", () => {
  // The seeded `perk learn harvest` session runs GATED (the read-only objective-author borrow),
  // so the wave must be reachable while read-only. Safe in every gated session: the tool's
  // manifest read is structurally bound to the session's claimed run-scoped scratch path (a
  // relayed param naming any other path is refused — the run_audit_wave no-aimable-writer
  // posture, read-side), it spawns only the read-only perk.harvest-analyst, and it writes
  // nothing to the worktree.
  assert.ok(READ_ONLY_TOOLS.includes("run_harvest_wave"));
});

test("READ_ONLY_TOOLS: contains the pi-subagents child-side tools (gated adopt-children keep the engine-injected structured_output)", () => {
  // The read-only gate is inherited by adopted children (§8.3 adopt arm); stripping the
  // engine-injected structured_output made an outputSchema child fail with
  // structuredOutputFailed after completing its whole exploration.
  for (const tool of SUBAGENT_CHILD_TOOLS) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
});

test("READ_ONLY_TOOLS: contains plan_review (the review door is callable in plan mode)", () => {
  assert.ok(READ_ONLY_TOOLS.includes("plan_review"));
});

test("READ_ONLY_TOOLS: contains plan_draft (the session-data carve-out)", () => {
  assert.ok(READ_ONLY_TOOLS.includes("plan_draft"));
});

test("READ_ONLY_TOOLS: contains objective_draft (the twin of the carve-out)", () => {
  assert.ok(READ_ONLY_TOOLS.includes("objective_draft"));
});

test("READ_ONLY_TOOLS: contains objective_node (the gated factory's node-transition door)", () => {
  // Both objective-plan factory paths run gated; the `objective_node_claim` carrier can only be
  // written by calling the tool inside the gated session — excluding it saves plans unlinked.
  assert.ok(READ_ONLY_TOOLS.includes("objective_node"));
});

test("READ_ONLY_TOOLS: contains the UNION of all web-seam providers' research tools", () => {
  // perk does not normalize names — the allowlist carries every known web provider's tool names
  // (pi-web-access + @ollama/pi-web-search + @juicesharp/rpiv-web-tools), inert when absent.
  for (const tool of [
    "web_search",
    "code_search",
    "fetch_content",
    "get_search_content",
    "source_check",
    "web_enable",
    "ollama_web_search",
    "ollama_web_fetch",
    "web_fetch",
  ]) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
});

test("READ_ONLY_TOOLS: contains the FFF search tools", () => {
  // Both pi-fff mode name-sets are enumerated (tools-and-ui + override's multi_grep), static
  // and inert when the package is absent; local search belongs in read-only exploration.
  for (const tool of FFF_SEARCH_TOOLS) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
});

test("READ_ONLY_TOOLS: contains the read-only linear_* tools, never the mutating ones", () => {
  for (const tool of [
    "linear_get_issue",
    "linear_list_comments",
    "linear_list_issues",
    "linear_search_issues",
    "linear_whoami",
  ]) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
  for (const tool of [
    "linear_create_issue",
    "linear_update_issue",
    "linear_create_comment",
    "linear_upload_file",
    "linear_upload_file_to_issue_comment",
    "linear_configure_auth",
  ]) {
    assert.ok(!READ_ONLY_TOOLS.includes(tool), `mutating tool allowlisted: ${tool}`);
  }
  // The context steers GitHub reads to the allowlisted read-only `gh` subcommands.
  assert.ok(READ_ONLY_CONTEXT.includes("read-only `gh` subcommands"));
  assert.ok(READ_ONLY_CONTEXT.includes("never raw curl/fetch against github.com"));
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
    { custom: { type: "perk:mode-context", data: { content: "[READ-ONLY MODE]\nprior copy" } } },
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
      "prior [READ-ONLY MODE] copy on branch → no re-injection",
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
  manager.appendCustomMessageEntry("perk:mode-context", "[READ-ONLY MODE]\nprior copy", false);
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

test("REFINEMENT_READ_ONLY_TOOLS: the exact refinement gate-ON selection (no claim/other-draft/save/spawn)", () => {
  assert.deepEqual(REFINEMENT_READ_ONLY_TOOLS, [
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
  ]);
  // The web family carries pi-web-access's full default set and its lazy loader.
  for (const tool of ["source_check", "web_enable"]) {
    assert.ok(REFINEMENT_READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
  for (const forbidden of [
    "objective_node",
    "plan_draft",
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
    "edit",
    "write",
  ]) {
    assert.equal(REFINEMENT_READ_ONLY_TOOLS.includes(forbidden), false, forbidden);
  }
  // Existing stages never gain the refinement draft: it is absent from READ_ONLY_TOOLS.
  assert.equal(READ_ONLY_TOOLS.includes("objective_refinement_draft"), false);
  assert.equal(gatedToolsFor("objective-refine"), REFINEMENT_READ_ONLY_TOOLS);
  for (const stage of [null, "plan", "objective-plan", "objective-author", "gist-author", "bogus"])
    assert.equal(gatedToolsFor(stage), READ_ONLY_TOOLS, String(stage));
});

test("gate ON in the refinement stage: the active set, the tool_call backstop and the mode flavor follow the stage", async () => {
  const h = gateFixture(() => false);
  // An already-gated UNBOUND session (default flavor installed) that then enters refinement.
  h.gate.syncFromState("read-only", undefined);
  assert.deepEqual(h.installed.at(-1), READ_ONLY_TOOLS);
  assert.equal((await h.call("before_agent_start"))?.message?.content, READ_ONLY_CONTEXT);
  assert.equal(
    (await h.call("tool_call", { toolName: "objective_refinement_draft", input: {} }))?.block,
    true,
    "the refinement draft is NOT allowlisted outside the refinement stage",
  );
  assert.equal(await h.call("tool_call", { toolName: "objective_node", input: {} }), undefined);

  h.gate.syncFromState("read-only", "objective-refine");
  assert.deepEqual(h.installed.at(-1), REFINEMENT_READ_ONLY_TOOLS);
  assert.equal(
    await h.call("tool_call", { toolName: "objective_refinement_draft", input: {} }),
    undefined,
  );
  assert.equal(await h.call("tool_call", { toolName: "plan_review", input: {} }), undefined);
  assert.equal(await h.call("tool_call", { toolName: "read", input: {} }), undefined);
  for (const toolName of [
    "objective_node",
    "plan_draft",
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
  // The flavor: names the actual writer with a distinct marker; the default marker is not a
  // substring, so a prior default copy on the branch never masks the refinement flavor.
  const injected = (await h.call("before_agent_start"))?.message?.content;
  assert.equal(injected, REFINEMENT_READ_ONLY_CONTEXT);
  assert.ok(injected?.includes("[READ-ONLY REFINEMENT MODE]"));
  assert.ok(injected?.includes("objective_refinement_draft is the sole sanctioned write"));
  assert.equal(injected?.includes("plan_draft"), false);
  assert.equal(REFINEMENT_READ_ONLY_CONTEXT.includes("[READ-ONLY MODE]"), false);
  assert.ok(READ_ONLY_CONTEXT.includes("plan_draft is the sole sanctioned write"));

  // Gate ON: only the current flavor survives in model context — the stale plan_draft-only block
  // is dropped; user content and marker-less mode entries are untouched.
  const stale = { customType: "perk:mode-context", content: READ_ONLY_CONTEXT };
  const current = { customType: "perk:mode-context", content: REFINEMENT_READ_ONLY_CONTEXT };
  const user = { role: "user", content: "please [READ-ONLY MODE] keep me" };
  const bare = { customType: "perk:mode-context" };
  assert.deepEqual(await h.call("context", { messages: [stale, current, user, bare] }), {
    messages: [current, user, bare],
  });
  assert.equal(await h.call("context", { messages: [current, user, bare] }), undefined);

  // Gate OFF: both flavors strip (the injected type wholesale + the marker-bearing user echoes).
  h.gate.exit();
  const off = await h.call("context", {
    messages: [stale, current, { role: "user", content: "[READ-ONLY REFINEMENT MODE] echo" }, user],
  });
  assert.deepEqual(off, { messages: [] });
});

// ---------------------------------------------------------------------------
// Lazy-owned tools and their loaders (contracts.md §8.40): membership follows the owner's live
// selection; a loader has exactly its tools' eligibility and is refused outside it.
// ---------------------------------------------------------------------------

test("gate ON: the allowlist is a ceiling — a lazy-owned tool installs only while its owner has it selected", () => {
  const withSubagent = [...FIXTURE_ACTIVE, "subagent", "subagents_enable", "web_enable"];
  const h = gateFixture(() => false, withSubagent);
  h.gate.syncFromState("read-only", "plan");
  const installed = h.installed.at(-1) ?? [];
  assert.deepEqual(installed, expectedGated(READ_ONLY_TOOLS, withSubagent));
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
  // allowlist installs it by name exactly as before lazy ownership existed.
  const eager = [...FIXTURE_ACTIVE, "subagent", "web_search"];
  const h = gateFixture(() => false, eager);
  h.gate.syncFromState("read-only", "plan");
  assert.deepEqual(h.installed.at(-1), expectedGated(READ_ONLY_TOOLS, eager));
  // Gate exit into plan strips subagent (the stage excludes delegation); re-entry restores it.
  h.gate.syncFromState("read-write", "plan");
  const stripped = h.installed.at(-1) ?? [];
  assert.ok(!stripped.includes("subagent") && stripped.includes("web_search"));
  h.setActive(stripped);
  h.gate.syncFromState("read-only", "plan");
  assert.ok((h.installed.at(-1) ?? []).includes("subagent"), "re-entry restores the eager tool");
  // The same sequence with the loader registered: the stripped lazy tool stays with its owner.
  const lazy = [...eager, "subagents_enable"];
  const owned = gateFixture(() => false, lazy);
  owned.gate.syncFromState("read-write", "plan");
  owned.setActive(owned.installed.at(-1) ?? []);
  owned.gate.syncFromState("read-only", "plan");
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

  // Gate ON in plan and unscoped: READ_ONLY_TOOLS carries both loaders.
  for (const stage of ["plan", undefined]) {
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
    ["READ_ONLY_TOOLS", READ_ONLY_TOOLS],
    ["REFINEMENT_READ_ONLY_TOOLS", REFINEMENT_READ_ONLY_TOOLS],
    ...Object.entries(STAGE_TOOLS).map(([stage, list]): [string, readonly string[]] => [
      `STAGE_TOOLS.${stage}`,
      list,
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
