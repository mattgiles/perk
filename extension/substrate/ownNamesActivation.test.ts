// Own-names-only activation, the provenance-posture table and the `perk_stage` loadout host
// (contracts.md §8.40), driven through REAL bound AgentSessions (fully offline). Two fixture modes
// (`extension/testing/harness.ts`): Mode A binds perk as the inline factory from this file's own
// module graph (so test-only perk tools register into the same catalog); Mode B loads perk by
// path beside fake npm packages installed into the user-scope package directory, so every foreign
// tool carries real package provenance — Mode B cases assert only through the live session.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { before, test } from "node:test";
import {
  createCodemodeExtension,
  type ExtensionAPI,
  type InlineExtension,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { registerPerkTool } from "../pi/perkTool.ts";
import {
  fakeNpmPackage,
  loadAt,
  PERK_EXTENSION_PATH,
  type PerkSession,
  plantSession,
  recordingRuntime,
  recordPerkInstalls,
  registerFakeTool,
  scaffoldRepo,
  staged,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { sideSessionTools } from "../vendor/btw/core.ts";
import {
  gatedToolsFor,
  isPerkTool,
  LOADOUT_HOST_NAME,
  perkToolsFor,
  stageToolsFor,
  WORKTREE_STAGES,
} from "./toolPolicy.ts";

// The perk-subset assertions read the catalog: fill it the way production does first.
before(ensureToolCatalog);

/** The ESM source of a fake package registering load-time no-op tools. */
function loadTimeTools(names: readonly string[]): string {
  return `export default function (pi) {
  for (const name of ${JSON.stringify(names)}) {
    pi.registerTool({
      name,
      label: name,
      description: "fake package tool " + name + " (test)",
      parameters: { type: "object", properties: {} },
      async execute() { return { content: [{ type: "text", text: "ok" }], details: {} }; },
    });
  }
}
`;
}

const PROMPT_RUNTIME = "pi-subagents:prompt-runtime";

// --- 0. the spike: the fixture's provenance + order preconditions (a failure here stops the work) -

test("spike (B): a fake package's tool carries its verbatim spec as provenance, and path-loaded perk loads before every package", async () => {
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, {
    packages: [
      fakeNpmPackage("npm:fake-research@1.0.0", loadTimeTools(["fake_research_query"])),
      fakeNpmPackage("npm:@fake-scope/fake-other@2.3.4", loadTimeTools(["fake_other_query"])),
    ],
  });
  try {
    const info = h.session.getAllTools().find((t) => t.name === "fake_research_query");
    assert.ok(info !== undefined, "the fake package's tool registered");
    assert.equal(info.sourceInfo.source, "npm:fake-research@1.0.0");
    assert.equal(info.sourceInfo.origin, "package");
    const scoped = h.session.getAllTools().find((t) => t.name === "fake_other_query");
    assert.equal(scoped?.sourceInfo.source, "npm:@fake-scope/fake-other@2.3.4");
    // perk itself registered (the path load worked) …
    assert.ok(h.session.getAllTools().some((t) => t.name === "plan_draft"));
    // … and loaded before every fake package (CLI paths precede settings packages).
    const paths = h.session.resourceLoader.getExtensions().extensions.map((e) => e.path);
    const perkAt = paths.indexOf(PERK_EXTENSION_PATH);
    assert.ok(perkAt !== -1, `perk's path is loaded: ${paths.join(", ")}`);
    const packageAts = paths
      .map((path, i) => ({ path, i }))
      .filter(({ path }) => path.includes(`${"npm"}/node_modules/`))
      .map(({ i }) => i);
    assert.equal(packageAts.length, 2, `both fake packages loaded: ${paths.join(", ")}`);
    for (const at of packageAts) assert.ok(perkAt < at, "perk precedes every package");
  } finally {
    h.dispose();
  }
});

test("spike (A): a named inline factory's tool carries its exact synthetic path", async () => {
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, {
    extraExtensions: [
      {
        name: PROMPT_RUNTIME,
        factory: (pi: ExtensionAPI) => registerFakeTool(pi, "structured_output"),
      },
    ],
  });
  try {
    const info = h.session.getAllTools().find((t) => t.name === "structured_output");
    assert.equal(info?.sourceInfo.path, `<inline:${PROMPT_RUNTIME}>`);
    assert.equal(info?.sourceInfo.source, "inline");
  } finally {
    h.dispose();
  }
});

// --- shared fixture pieces ------------------------------------------------------------------------

const foreignActive = (h: PerkSession): string[] =>
  h.session.getActiveToolNames().filter((n) => !isPerkTool(n));

/** The session's active perk names vs. the registered subset of a perk view (both sorted). */
function assertPerkSubset(h: PerkSession, view: readonly string[], when: string): void {
  const registered = new Set(h.session.getAllTools().map((t) => t.name));
  assert.deepEqual(
    h.session.getActiveToolNames().filter(isPerkTool).sort(),
    view.filter((n) => registered.has(n)).sort(),
    `perk's active subset ${when}`,
  );
}

async function blocked(h: PerkSession, name: string): Promise<string | undefined> {
  const verdict = await h.emitToolCall(name, {});
  return verdict?.block === true ? verdict.reason : undefined;
}

/** pi-subagents' engine factory, by its exact synthetic path (the child-engine posture row). */
function promptRuntime(names: readonly string[]): InlineExtension {
  return {
    name: PROMPT_RUNTIME,
    factory: (pi) => {
      for (const n of names) registerFakeTool(pi, n);
    },
  };
}

/** A bare factory: positional `<inline:N>` path — unknown provenance. */
function bareFactory(names: readonly string[]): (pi: ExtensionAPI) => void {
  return (pi) => {
    for (const n of names) registerFakeTool(pi, n);
  };
}

const codemode = (mode: "on" | "only"): InlineExtension => ({
  name: "codemode",
  factory: createCodemodeExtension({ mode }),
  builtin: true,
});

/** Test-only deferred perk tools (this file's process only — the matrix suite never sees them). */
const DEFERRED_WORKTREE = "fixture_deferred_worktree_query";
const DEFERRED_PLAN = "fixture_deferred_plan_query";
const deferredFixtures: InlineExtension = {
  name: "perk-deferred-fixtures",
  factory: (pi) => {
    const def = (name: string, description: string) => ({
      name,
      label: name,
      description,
      parameters: { type: "object", additionalProperties: false, properties: {} } as never,
      async execute() {
        return { content: [{ type: "text" as const, text: "ok" }], details: {} };
      },
    });
    registerPerkTool(pi, def(DEFERRED_WORKTREE, "Look up the worktree ledger."), {
      stages: WORKTREE_STAGES,
      gated: "allowed",
      kind: "query",
      declared: "deferred",
      result: { properties: {} },
    });
    registerPerkTool(pi, def(DEFERRED_PLAN, "Look up the planning almanac."), {
      stages: ["plan"],
      gated: "allowed",
      kind: "query",
      declared: "deferred",
      result: { properties: {} },
    });
  },
};

const runnerEnv = {
  PI_SUBAGENT_CHILD: "1",
  PI_SUBAGENT_EXTENSION_BINDINGS: '{"perk.parent-restrictions/1":{"readOnly":true}}',
};

// --- 1. search-then-reconcile ---------------------------------------------------------------------

test("search-then-reconcile (A): an eligible tool_search activation survives every point; an ineligible one is hidden at once and deactivated when the next prompt starts", async () => {
  {
    const rt = await recordingRuntime();
    const h = await staged("implement", "read-write", {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
      extraExtensions: [toolSearch(), deferredFixtures],
    });
    try {
      h.session.setActiveToolsByName([...h.session.getActiveToolNames(), "tool_search"]);
      rt.callThenStop("tool_search", { query: "worktree ledger" });
      await h.session.prompt("find the ledger tool");
      assert.ok(rt.last().tools.includes(DEFERRED_WORKTREE), "declared on the next request");
      assert.ok(h.session.getActiveToolNames().includes(DEFERRED_WORKTREE));
      await h.session.extensionRunner.emitResourcesDiscover(
        h.session.sessionManager.getCwd(),
        "reload",
      );
      await h.emitSessionStart();
      await h.invokeCommand("plan");
      assert.ok(h.session.getActiveToolNames().includes(DEFERRED_WORKTREE), "kept under the gate");
      await h.invokeCommand("plan");
      rt.census();
      await h.session.prompt("census");
      assert.ok(rt.last().tools.includes(DEFERRED_WORKTREE), "declared after every point");
      assert.ok(!rt.last().tools.includes(DEFERRED_PLAN), "the unsearched one never activates");
    } finally {
      h.dispose();
    }
  }
  {
    const rt = await recordingRuntime();
    const h = await staged("plan", "read-write", {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
      extraExtensions: [toolSearch(), deferredFixtures],
    });
    try {
      h.session.setActiveToolsByName([...h.session.getActiveToolNames(), "tool_search"]);
      rt.callThenStop("tool_search", { query: "worktree ledger" });
      await h.session.prompt("find the ledger tool");
      assert.ok(
        h.session.getActiveToolNames().includes(DEFERRED_WORKTREE),
        "the search activated it; it stays active for the rest of this prompt",
      );
      assert.ok(!rt.last().tools.includes(DEFERRED_WORKTREE), "hidden on the very next request");
      rt.census();
      await h.session.prompt("census");
      assert.ok(
        !h.session.getActiveToolNames().includes(DEFERRED_WORKTREE),
        "deactivated when the next prompt started",
      );
      assert.ok(!rt.last().tools.includes(DEFERRED_WORKTREE));
      await h.invokeCommand("plan");
      assert.equal(
        await blocked(h, DEFERRED_WORKTREE),
        `perk read-only mode: ${DEFERRED_WORKTREE} is blocked (tool not allowlisted).`,
      );
    } finally {
      h.dispose();
    }
  }
});

// --- 2. search-then-tree/resume/fork (host behaviour bounds perk's) -----------------------------

test("search-then-tree/resume/fork (A): a resume or fork from the eligible searched leaf starts without it and perk never re-activates it; /tree restores it and perk keeps it (or drops it in an ineligible stage)", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ stage: "implement", mode: "read-write" }]);
  const rt = await recordingRuntime();
  const opts = {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch(), deferredFixtures],
    env: { PERK_RUN_ID: undefined },
  };
  const searched = await loadAt(cwd, { ...opts, sessionManager: SessionManager.open(file) });
  let leaf: string;
  try {
    searched.session.setActiveToolsByName([
      ...searched.session.getActiveToolNames(),
      "tool_search",
    ]);
    rt.callThenStop("tool_search", { query: "worktree ledger" });
    await searched.session.prompt("find the ledger tool");
    assert.ok(searched.session.getActiveToolNames().includes(DEFERRED_WORKTREE));
    const id = searched.session.sessionManager.getLeafId();
    assert.ok(id !== null);
    leaf = id;
  } finally {
    searched.dispose();
  }
  assert.ok(existsSync(file) && readFileSync(file, "utf8").includes(DEFERRED_WORKTREE));

  // Resume and fork land on the searched leaf, in implement — where the tool is ELIGIBLE, so
  // perk would keep it had the host restored it: its absence is the host's, not perk's filter.
  for (const manager of [SessionManager.open(file), SessionManager.forkFrom(file, cwd)]) {
    installs.length = 0;
    const resumed = await loadAt(cwd, { ...opts, sessionManager: manager });
    try {
      assert.equal(resumed.workflowState().stage, "implement");
      assert.ok(!resumed.session.getActiveToolNames().includes(DEFERRED_WORKTREE));
      rt.census();
      await resumed.session.prompt("census");
      assert.ok(!resumed.session.getActiveToolNames().includes(DEFERRED_WORKTREE));
      assert.ok(installs.length > 0, "the recorder sees perk's startup install (non-vacuous)");
      assert.deepEqual(
        installs.filter((names) => names.includes(DEFERRED_WORKTREE)),
        [],
        "perk never installs it",
      );
    } finally {
      resumed.dispose();
    }
  }

  // /tree navigation is where the host restores the declared loadout.
  const h = await loadAt(cwd, { ...opts, sessionManager: SessionManager.open(file) });
  try {
    const [planted] = h.entryIds() as [string];
    await h.navigateTo(planted);
    await h.navigateTo(leaf);
    assert.ok(h.session.getActiveToolNames().includes(DEFERRED_WORKTREE), "restored and kept");
    // A branch whose stage makes it ineligible: Pi restores the declared loadout, perk drops it.
    const toPlan = h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      stage: "plan",
    });
    await h.navigateTo(planted);
    await h.navigateTo(toPlan);
    assert.equal(h.workflowState().stage, "plan");
    assert.ok(!h.session.getActiveToolNames().includes(DEFERRED_WORKTREE), "dropped in plan");
  } finally {
    h.dispose();
  }
});

// --- 4. gate entry/exit + snippets ----------------------------------------------------------------

const EDIT_SNIPPET = "Make precise file edits";
const WRITE_SNIPPET = "Create or overwrite files";

test("gate entry/exit (A): edit/write stay active but undeclared, snippet-less and blocked; exit restores perk's tools, the foreign set exactly, and the snippets", async () => {
  const rt = await recordingRuntime();
  const h = await staged("implement", "read-write", {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
  });
  try {
    const foreignBefore = foreignActive(h);
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only");
    const active = h.session.getActiveToolNames();
    for (const name of ["edit", "write", LOADOUT_HOST_NAME]) assert.ok(active.includes(name), name);
    assert.ok(!active.includes("submit"), "a gate-blocked perk tool is deactivated");
    assert.ok(active.includes("plan_draft"), "a mode-over-stage perk tool is activated");
    for (const name of ["edit", "write"]) {
      assert.match((await blocked(h, name)) ?? "", /file modifications disabled/);
    }
    rt.census();
    await h.session.prompt("census");
    const gated = rt.last();
    for (const name of ["edit", "write", LOADOUT_HOST_NAME]) assert.ok(!gated.tools.includes(name));
    assert.ok(!gated.prompt.includes(EDIT_SNIPPET) && !gated.prompt.includes(WRITE_SNIPPET));

    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write");
    assertPerkSubset(h, stageToolsFor("implement") ?? [], "after the gate exit");
    assert.deepEqual(foreignActive(h), foreignBefore, "the foreign set is exactly as before");
    rt.census();
    await h.session.prompt("census");
    const open = rt.last();
    for (const name of ["edit", "write"]) assert.ok(open.tools.includes(name), name);
    assert.ok(open.prompt.includes(EDIT_SNIPPET) && open.prompt.includes(WRITE_SNIPPET));
    assert.ok(!open.tools.includes(LOADOUT_HOST_NAME), "the host is never declared");
  } finally {
    h.dispose();
  }
});

// --- Mode B: provenance-real foreign packages -----------------------------------------------------

/** The ESM tool-registration prelude every fake package source shares. */
const PRELUDE = `
const ok = () => ({ content: [{ type: "text", text: "ok" }], details: {} });
const tool = (pi, name, extra = {}) =>
  pi.registerTool({
    name,
    label: name,
    description: "fake package tool " + name + " (test)",
    promptSnippet: "fake " + name + " snippet",
    parameters: { type: "object", properties: {} },
    async execute() { return ok(); },
    ...extra,
  });
`;

/**
 * pi-subagents 0.73.1's activation shape (`extension/tool-activation.js`): `subagent` + its loader
 * at load; on session_start/session_tree the recorded selection is replayed (a message-less branch
 * hides `subagent`); the loader re-adds itself on every before_agent_start; plus the late
 * `subagent_supervisor` registered inside its own session_start.
 */
const FAKE_SUBAGENTS = `${PRELUDE}
const LOADER = "subagents_enable";
const SUBAGENT = "subagent";
export default function (pi) {
  const setSelection = (include) => {
    const active = pi.getActiveTools();
    const next = include ? [...active, SUBAGENT] : active.filter((n) => n !== SUBAGENT);
    if (!next.includes(LOADER)) next.push(LOADER);
    pi.setActiveTools([...new Set(next)]);
  };
  const applyRecordedSelection = (ctx) => {
    const messages = ctx.sessionManager.buildSessionContext().messages;
    const declared = messages.some((m) => m.role === "system" && (Object.hasOwn(m, "toolsAdded") || Object.hasOwn(m, "toolsRemoved")));
    if (declared) {
      let selected = false;
      for (const m of messages) {
        if (m.role !== "system") continue;
        if (m.toolsRemoved?.some((t) => t.name === SUBAGENT)) selected = false;
        if (m.toolsAdded?.some((t) => t.name === SUBAGENT)) selected = true;
      }
      setSelection(selected);
      return;
    }
    setSelection(messages.length > 0 && pi.getActiveTools().includes(SUBAGENT));
  };
  tool(pi, SUBAGENT);
  tool(pi, LOADER, { async execute() { setSelection(true); return ok(); } });
  pi.on("session_start", (_event, ctx) => {
    applyRecordedSelection(ctx);
    tool(pi, "subagent_supervisor");
  });
  pi.on("session_tree", (_event, ctx) => applyRecordedSelection(ctx));
  pi.on("before_agent_start", (event) => {
    const selectedTools = (event.systemPromptOptions.selectedTools ??= [...pi.getActiveTools()]);
    if (!selectedTools.includes(LOADER)) selectedTools.push(LOADER);
    if (!pi.getActiveTools().includes(LOADER)) pi.setActiveTools([...pi.getActiveTools(), LOADER]);
  });
}
`;

const loadTime = (names: readonly string[]) =>
  `${PRELUDE}\nexport default function (pi) { for (const n of ${JSON.stringify(names)}) tool(pi, n); }\n`;

/** The questionnaire's headless strip, in its own before_agent_start. */
const FAKE_QUESTIONNAIRE = `${PRELUDE}
export default function (pi) {
  tool(pi, "ask_user_question");
  pi.on("before_agent_start", (_event, ctx) => {
    if (!ctx.hasUI) pi.setActiveTools(pi.getActiveTools().filter((n) => n !== "ask_user_question"));
  });
}
`;

const FAKE_DORMANT = `${PRELUDE}
export default function (pi) { tool(pi, "dormant_tool", { defaultActive: false }); }
`;

/** The installed cross-section, one fake per posture (+ an unknown package and a dormant tool). */
function foreignPackages() {
  return [
    fakeNpmPackage("npm:pi-subagents@0.73.1", FAKE_SUBAGENTS),
    fakeNpmPackage("npm:pi-web-access@1.0.0", loadTime(["web_search"])),
    fakeNpmPackage(
      "npm:@plannotator/pi-extension@1.0.0",
      loadTime(["plannotator_submit_plan", "plannotator_mark_done", "plannotator_future_tool"]),
    ),
    fakeNpmPackage("npm:@juicesharp/rpiv-ask-user-question@1.0.0", FAKE_QUESTIONNAIRE),
    fakeNpmPackage("npm:@juicesharp/rpiv-todo@1.0.0", loadTime(["todo"])),
    fakeNpmPackage("npm:some-mcp-bridge@1.0.0", loadTime(["bridge_query"])),
    fakeNpmPackage("npm:fake-dormant@1.0.0", FAKE_DORMANT),
  ];
}

const NEVER_ACTIVATED = ["dormant_tool"];

test("stage change, late registration, initially inactive and unknown provenance (B): perk's subset follows the stage, the foreign set only ever moves by its owners, and each posture presents as tabled", async () => {
  const cwd = scaffoldRepo();
  // e0 bare read-write → e1 implement → e2 objective-plan → e3 objective-plan gated.
  const file = plantSession(cwd, [
    { mode: "read-write" },
    { stage: "implement" },
    { stage: "objective-plan" },
    { mode: "read-only" },
  ]);
  const rt = await recordingRuntime();
  const h = await loadAt(cwd, {
    packages: foreignPackages(),
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const [bare, implement, objectivePlan, gated] = h.entryIds() as [
      string,
      string,
      string,
      string,
    ];
    // Startup lands gated in objective-plan; the late supervisor registered after perk's sync.
    const tools = h.session.getAllTools();
    const supervisor = tools.find((t) => t.name === "subagent_supervisor");
    assert.equal(supervisor?.sourceInfo.source, "npm:pi-subagents@0.73.1");
    for (const name of ["subagent_supervisor", "bridge_query", "plannotator_future_tool"])
      assert.ok(h.session.getActiveToolNames().includes(name), `${name} active (its owner's)`);
    assert.ok(!h.session.getActiveToolNames().includes("subagent"), "the owner hid subagent");

    const landing = async (entry: string, view: readonly string[], label: string) => {
      const foreignBefore = foreignActive(h);
      await h.navigateTo(entry);
      assertPerkSubset(h, view, label);
      // The only foreign moves at a navigation are the subagents owner's replay of its own
      // selection on a message-less branch (subagent hidden, loader kept).
      assert.deepEqual(
        foreignActive(h).filter((n) => n !== "subagent"),
        foreignBefore.filter((n) => n !== "subagent"),
        `${label}: perk moved no foreign name`,
      );
      for (const name of NEVER_ACTIVATED) assert.ok(!h.session.getActiveToolNames().includes(name));
      rt.census();
      await h.session.prompt("census");
      return rt.last().tools;
    };

    const atImplement = await landing(implement, stageToolsFor("implement") ?? [], "implement");
    for (const name of ["subagent_supervisor", "subagents_enable", "todo", "web_search"])
      assert.ok(atImplement.includes(name), `implement declares ${name}`);
    assert.ok(atImplement.includes("bridge_query"), "an unknown tool passes every diet");
    for (const name of ["plannotator_submit_plan", "plannotator_future_tool", LOADOUT_HOST_NAME])
      assert.ok(!atImplement.includes(name), `implement hides ${name}`);
    assert.equal(await blocked(h, "bridge_query"), undefined, "callable read-write");
    // The questionnaire stripped itself headless in its before_agent_start; perk never restores it.
    assert.ok(!h.session.getActiveToolNames().includes("ask_user_question"));

    const atPlan = await landing(
      objectivePlan,
      stageToolsFor("objective-plan") ?? [],
      "objective-plan",
    );
    for (const name of [
      "subagent_supervisor",
      "subagents_enable",
      "todo",
      "plannotator_future_tool",
    ])
      assert.ok(!atPlan.includes(name), `objective-plan hides ${name}`);
    assert.ok(
      h.session.getActiveToolNames().includes("subagent_supervisor"),
      "hidden, not removed",
    );
    assert.ok(atPlan.includes("web_search") && atPlan.includes("bridge_query"));
    assert.ok(!h.session.getActiveToolNames().includes("ask_user_question"));

    const atGated = await landing(gated, gatedToolsFor("objective-plan"), "gated objective-plan");
    assert.ok(!atGated.includes("bridge_query"), "an unknown tool is hidden under the gate…");
    assert.match((await blocked(h, "bridge_query")) ?? "", /tool not allowlisted/, "…and blocked");
    assert.ok(atGated.includes("web_search"), "research rides the gate");

    const atBare = await landing(bare, perkToolsFor(null, "read-write"), "bare");
    for (const name of ["plannotator_future_tool", "subagent_supervisor", "todo", "bridge_query"])
      assert.ok(atBare.includes(name), `a bare session presents ${name}`);
    assert.deepEqual(
      atBare.filter((n) => !isPerkTool(n)).sort(),
      foreignActive(h).sort(),
      "a bare session hides no foreign tool",
    );
  } finally {
    h.dispose();
  }
});

test("owner deactivation + re-advertisement (B): perk never re-activates the owner-hidden subagent nor deactivates the loader-enabled one; in plan both stay active but hidden, through the owner's per-turn re-advertisement", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ stage: "implement", mode: "read-write" }]);
  const rt = await recordingRuntime();
  const h = await loadAt(cwd, {
    packages: [fakeNpmPackage("npm:pi-subagents@0.73.1", FAKE_SUBAGENTS)],
    extraExtensions: [codemode("only")],
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  const perkPoints = async () => {
    await h.invokeCommand("plan");
    await h.invokeCommand("plan");
    await h.session.extensionRunner.emitResourcesDiscover(cwd, "reload");
    rt.census();
    await h.session.prompt("census");
    return rt.last().tools;
  };
  try {
    const [planted] = h.entryIds() as [string];
    assert.ok(!h.session.getActiveToolNames().includes("subagent"), "the owner hid it");
    const hiddenByOwner = await perkPoints();
    assert.ok(!h.session.getActiveToolNames().includes("subagent"), "perk never re-activates it");
    assert.ok(!hiddenByOwner.includes("subagent") && hiddenByOwner.includes("subagents_enable"));

    await h.invokeTool("subagents_enable", {});
    assert.ok(h.session.getActiveToolNames().includes("subagent"), "the loader enabled it");
    const enabled = await perkPoints();
    assert.ok(h.session.getActiveToolNames().includes("subagent"), "perk never deactivates it");
    assert.ok(enabled.includes("subagent"), "declared in implement");

    // Into plan: the owner replays its recorded selection; perk leaves both active and hides them.
    const toPlan = h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      stage: "plan",
    });
    await h.navigateTo(planted);
    await h.navigateTo(toPlan);
    assert.equal(h.workflowState().stage, "plan");
    for (const name of ["subagent", "subagents_enable"])
      assert.ok(h.session.getActiveToolNames().includes(name), `${name} stays active in plan`);
    for (let turn = 0; turn < 2; turn++) {
      rt.census();
      await h.session.prompt("census");
      for (const name of ["subagent", "subagents_enable"])
        assert.ok(!rt.last().tools.includes(name), `turn ${turn}: ${name} hidden in plan`);
    }
    assert.ok(h.session.getActiveToolNames().includes("subagents_enable"));

    // The accepted composition limit: codemode (read-write, so not hidden) builds its description
    // from the unfiltered callable set — it names the diet-hidden subagent.
    h.session.setActiveToolsByName([...h.session.getActiveToolNames(), "codemode"]);
    rt.census();
    await h.session.prompt("census");
    const declared = rt.last().declared as { name: string; description?: string }[];
    const codemodeTool = declared.find((t) => t.name === "codemode");
    assert.ok(codemodeTool !== undefined, "codemode is declared read-write");
    assert.match(codemodeTool.description ?? "", /\bsubagent\b/);
    assert.ok(!rt.last().tools.includes("subagent"), "the declaration itself stays hidden");
  } finally {
    h.dispose();
  }
});

// --- 7. initially inactive / deactivated perk tools ---------------------------------------------

test("initially inactive (A): a defaultTools `-name` does not deactivate an extension tool on this host; a perk tool a foreign extension deactivates is re-activated at the next point", async (t) => {
  const installs = recordPerkInstalls(t);
  // The host fact: `defaultTools` only shapes the startup set over Pi's own tools — every
  // extension tool joins regardless — so the bare session needs no perk install at all.
  const bare = await loadAt(scaffoldRepo(), {
    env: { PERK_RUN_ID: undefined },
    settings: { defaultTools: ["-plan_draft", "-web_probe"] },
    extraExtensions: [bareFactory(["web_probe"])],
  });
  try {
    for (const name of ["plan_draft", "web_probe"])
      assert.ok(bare.session.getActiveToolNames().includes(name), `${name} active`);
    assert.deepEqual(installs, [], "perk installed nothing");
  } finally {
    bare.dispose();
  }
  // A foreign extension's own session_start deactivation of a perk tool (after perk's sync):
  // the resources_discover re-apply re-activates it — perk's own activation is policy-owned.
  const deactivated: boolean[] = [];
  const h = await staged("implement", "read-write", {
    extraExtensions: [
      (pi: ExtensionAPI) => {
        pi.on("session_start", async () => {
          pi.setActiveTools(pi.getActiveTools().filter((n) => n !== "submit"));
          deactivated.push(!pi.getActiveTools().includes("submit"));
        });
      },
    ],
  });
  try {
    assert.deepEqual(deactivated, [true], "the foreign deactivation took effect");
    assert.ok(h.session.getActiveToolNames().includes("submit"), "re-activated by perk");
    assertPerkSubset(h, stageToolsFor("implement") ?? [], "after startup");
  } finally {
    h.dispose();
  }
});

// --- 8. the child engine ------------------------------------------------------------------------

test("child-engine (A): a floored child keeps the engine's tools active, declared and callable; a bare-factory tool is hidden and blocked; a never-registered name is blocked", async () => {
  const rt = await recordingRuntime();
  const h = await loadAt(scaffoldRepo(), {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: undefined, ...runnerEnv },
    extraExtensions: [
      promptRuntime(["structured_output", "contact_supervisor", "wait"]),
      bareFactory(["bare_tool"]),
    ],
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    rt.census();
    await h.session.prompt("census");
    for (const name of ["structured_output", "contact_supervisor", "wait"]) {
      assert.ok(h.session.getActiveToolNames().includes(name), `${name} active`);
      assert.ok(rt.last().tools.includes(name), `${name} declared`);
      assert.equal(await blocked(h, name), undefined, `${name} callable`);
    }
    assert.ok(h.session.getActiveToolNames().includes("bare_tool"), "never deactivated…");
    assert.ok(!rt.last().tools.includes("bare_tool"), "…but hidden");
    assert.match((await blocked(h, "bare_tool")) ?? "", /tool not allowlisted/);
    assert.match((await blocked(h, "never_registered")) ?? "", /tool not registered/);
    // The host is active in the floored child and never declared.
    assert.ok(h.session.getActiveToolNames().includes(LOADOUT_HOST_NAME));
    assert.ok(!rt.last().tools.includes(LOADOUT_HOST_NAME));
  } finally {
    h.dispose();
  }
});

// --- 10. the bare session -------------------------------------------------------------------------

test("bare session (A): perk installs nothing across startup and a prompt turn; the model sees the host's default set plus every perk tool, minus the host", async (t) => {
  const installs = recordPerkInstalls(t);
  const rt = await recordingRuntime();
  const h = await loadAt(scaffoldRepo(), {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    await h.session.extensionRunner.emitResourcesDiscover(
      h.session.sessionManager.getCwd(),
      "reload",
    );
    rt.census();
    await h.session.prompt("census");
    assert.deepEqual(installs, [], "zero perk installs");
    const active = h.session.getActiveToolNames();
    assert.ok(active.includes(LOADOUT_HOST_NAME));
    assert.deepEqual(
      [...rt.last().tools].sort(),
      active.filter((n) => n !== LOADOUT_HOST_NAME).sort(),
    );
    assert.deepEqual(
      active.filter((n) => !isPerkTool(n)).sort(),
      ["bash", "edit", "read", "write"],
      "Pi's default set",
    );
  } finally {
    h.dispose();
  }
});

// --- 11. registry filters and the absent host -----------------------------------------------------

test("registry filters (A): an allowlisted child registers no perk tool and gets no install; an excluded host means no presentation; an excluded perk tool is never installed and blocked as unregistered", async (t) => {
  const installs = recordPerkInstalls(t);
  const allowlist = ["read", "grep", "find", "ls", "bash", "structured_output"];
  {
    const rt = await recordingRuntime();
    const child = await loadAt(scaffoldRepo(), {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
      env: { PERK_RUN_ID: undefined, ...runnerEnv },
      tools: allowlist,
      extraExtensions: [promptRuntime(["structured_output", "contact_supervisor"])],
    });
    try {
      assert.deepEqual(
        child.session.getAllTools().filter((t) => isPerkTool(t.name)),
        [],
      );
      rt.census();
      await child.session.prompt("census");
      assert.deepEqual(installs, [], "nothing of perk's to install");
      assert.deepEqual([...rt.last().tools].sort(), [...allowlist].sort());
      for (const name of ["edit", "write", "contact_supervisor", "plan_draft"])
        assert.match((await blocked(child, name)) ?? "", /blocked/, name);
      for (const name of ["read", "structured_output"])
        assert.equal(await blocked(child, name), undefined, name);
    } finally {
      child.dispose();
    }
  }
  {
    const rt = await recordingRuntime();
    const h = await staged("implement", "read-only", {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
      excludeTools: [LOADOUT_HOST_NAME],
    });
    try {
      assert.ok(!h.session.getAllTools().some((t) => t.name === LOADOUT_HOST_NAME));
      assertPerkSubset(h, gatedToolsFor("implement"), "gated without a host");
      assert.match((await blocked(h, "edit")) ?? "", /file modifications disabled/);
      rt.census();
      await h.session.prompt("census");
      assert.ok(rt.last().tools.includes("edit"), "no presentation: edit stays declared");
    } finally {
      h.dispose();
    }
  }
  {
    const h = await staged("implement", "read-only", { excludeTools: ["plan_draft"] });
    try {
      assert.ok(!h.session.getAllTools().some((t) => t.name === "plan_draft"));
      assert.ok(!h.session.getActiveToolNames().includes("plan_draft"));
      assert.equal(
        await blocked(h, "plan_draft"),
        "perk read-only mode: plan_draft is blocked (tool not registered).",
      );
    } finally {
      h.dispose();
    }
  }
});

// --- 12. codemode under the gate + real nested execution ------------------------------------------

test("codemode (A): the gate suspends it — its edit-bearing description never reaches a gated request and the direct tools stay declared — and restores it at release", async () => {
  const rt = await recordingRuntime();
  const h = await staged("implement", "read-only", {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [codemode("only")],
  });
  try {
    h.session.setActiveToolsByName([...h.session.getActiveToolNames(), "codemode"]);
    assert.ok(h.session.getActiveToolNames().includes("codemode"));
    rt.census();
    await h.session.prompt("census");
    assert.ok(!h.session.getActiveToolNames().includes("codemode"), "suspended under the gate");
    const gated = rt.last();
    assert.ok(!gated.tools.includes("codemode"));
    assert.ok(!JSON.stringify(gated.declared).includes("oldText"), "no edit schema declared");
    for (const name of ["read", "bash", "plan_draft"])
      assert.ok(gated.tools.includes(name), `${name} stays declared under the gate`);
    assert.match((await blocked(h, "codemode")) ?? "", /tool not allowlisted/);

    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write");
    assert.ok(h.session.getActiveToolNames().includes("codemode"), "restored at release");
    rt.census();
    await h.session.prompt("census");
    assert.ok(rt.last().tools.includes("codemode"), "declared again read-write");
  } finally {
    h.dispose();
  }
});

/** A gate-allowed test perk tool that writes `target` through Pi's nested-execution API. */
function nestedWriter(
  target: string,
  outcomes: { isError: boolean; text: string }[],
): InlineExtension {
  return {
    name: "perk-nested-writer",
    factory: (pi) => {
      registerPerkTool(
        pi,
        {
          name: NESTED_WRITER,
          label: NESTED_WRITER,
          description: "Write the fixture file through a nested call.",
          parameters: { type: "object", additionalProperties: false, properties: {} } as never,
          async execute(_id, _params, _signal, _onUpdate, ctx) {
            const outcome = await ctx.executeTool("write", { path: target, content: "nested\n" });
            const result = outcome.result as { content: { type: string; text?: string }[] };
            const text = result.content.map((c) => c.text ?? "").join("");
            outcomes.push({ isError: outcome.isError, text });
            return { content: [{ type: "text" as const, text: "probed" }], details: {} };
          },
        },
        { stages: ["implement"], gated: "allowed", kind: "action" },
      );
    },
  };
}

const NESTED_WRITER = "fixture_nested_writer";

test("nested execution (A): a write reached through ctx.executeTool meets the read-only backstop with its parent call id; read-write, the same write lands", async () => {
  const rt = await recordingRuntime();
  const outcomes: { isError: boolean; text: string }[] = [];
  const runId = "01OWNNESTED";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-only", stage: "implement" } });
  const target = join(cwd, "nested-target.txt");
  const h = await loadAt(cwd, {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: runId },
    extraExtensions: [nestedWriter(target, outcomes)],
  });
  const runner = h.session.extensionRunner;
  const seen: { toolName: string; parentToolCallId?: string; block?: boolean }[] = [];
  const emit = runner.emitToolCall.bind(runner);
  runner.emitToolCall = async (event) => {
    const result = await emit(event);
    seen.push({
      toolName: event.toolName,
      parentToolCallId: (event as { parentToolCallId?: string }).parentToolCallId,
      block: (result as { block?: boolean } | undefined)?.block,
    });
    return result;
  };
  try {
    rt.callThenStop(NESTED_WRITER, {});
    await h.session.prompt("write through the probe");
    assert.equal(outcomes.length, 1, "the probe ran (it is gate-allowed)");
    assert.equal(outcomes[0]?.isError, true);
    assert.match(
      outcomes[0]?.text ?? "",
      /perk read-only mode: write is blocked \(file modifications disabled\)/,
    );
    assert.deepEqual(
      seen.filter((e) => e.toolName === "write"),
      [{ toolName: "write", parentToolCallId: `call-${NESTED_WRITER}`, block: true }],
    );
    assert.equal(existsSync(target), false, "nothing written under the gate");

    // The read-write control: the same nested write executes once the gate is released.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write");
    rt.callThenStop(NESTED_WRITER, {});
    await h.session.prompt("write through the probe again");
    assert.equal(outcomes[1]?.isError, false, outcomes[1]?.text);
    assert.equal(readFileSync(target, "utf8"), "nested\n");
  } finally {
    h.dispose();
  }
});

// --- 13. the hidden host --------------------------------------------------------------------------

test("hidden host: active in every landing where registered and never declared; /btw's side session never carries the extension builtins", async () => {
  for (const [stage, mode] of [
    ["plan", "read-write"],
    ["objective-refine", "read-only"],
  ] as const) {
    const rt = await recordingRuntime();
    const h = await staged(stage, mode, {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
    });
    try {
      assert.ok(h.session.getActiveToolNames().includes(LOADOUT_HOST_NAME), `${stage} ${mode}`);
      rt.census();
      await h.session.prompt("census");
      assert.ok(!rt.last().tools.includes(LOADOUT_HOST_NAME), `${stage} ${mode}`);
    } finally {
      h.dispose();
    }
  }
  for (const readOnly of [true, false]) {
    const tools = sideSessionTools(readOnly);
    assert.ok(!tools.includes("codemode") && !tools.includes("tool_search"), String(readOnly));
  }
});
