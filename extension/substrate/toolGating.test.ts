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
  type LoadoutPresentation,
  type Mode,
  perkToolNames,
  perkToolsFor,
  READ_ONLY_STAGES,
  REGISTRY_STAGE_IDS,
  WORKTREE_STAGES,
} from "./toolPolicy.ts";

// The derived views read the catalog: fill it the way production does before any test runs.
before(ensureToolCatalog);

type Hook = (
  event: {
    toolName?: string;
    input?: Record<string, unknown>;
    parentToolCallId?: string;
    messages?: unknown[];
    reason?: string;
  },
  ctx: ExtensionContext,
) => Promise<
  | { block?: boolean; reason?: string; message?: { content: string }; messages?: unknown[] }
  | undefined
>;

/**
 * One registered tool as the fake host reports it (`ToolInfo.sourceInfo`'s two load-bearing
 * fields, plus the tool's own `annotations` when it declares any).
 */
type FakeTool = {
  name: string;
  source: string;
  path: string;
  annotations?: { readOnlyHint?: boolean };
  /** The registered exposure `getAllTools` reports; default `direct`. */
  exposure?: "direct" | "deferred";
};

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
 * The default live active set: a bare session's — Pi's defaults plus every registrant's tools,
 * except a tool registered `deferred` (Pi never activates one on registration: a cohort session's
 * discovery family, a nonparticipant member whose `direct` re-declaration failed).
 */
function defaultActive(registry: readonly FakeTool[]): string[] {
  return registry
    .filter((t) => t.exposure !== "deferred")
    .map((t) => t.name)
    .filter((name) => !["grep", "find", "ls"].includes(name));
}

/** A registry whose discovery-family members are registered deferred (a cohort session's). */
function cohortRegistry(registry: readonly FakeTool[]): FakeTool[] {
  const family = new Set(discoveryFamily());
  return registry.map((t) => (family.has(t.name) ? { ...t, exposure: "deferred" } : t));
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
  opts: {
    registry?: readonly FakeTool[];
    active?: readonly string[];
    /** Pi's merged settings (`getSettings`); default `{}` — codemode mode `on`; null = no API. */
    settings?: { codemode?: { mode?: string } } | null;
    /**
     * A discovery-cohort session: the family is registered deferred (so inactive by default — Pi
     * never activated it). Default false: a nonparticipant, whose family is `direct` and active
     * like any perk tool.
     */
    cohort?: boolean;
  } = {},
) {
  const hooks = new Map<string, Hook>();
  const base = opts.registry ?? defaultRegistry();
  let registry: FakeTool[] = opts.cohort === true ? cohortRegistry(base) : [...base];
  let active: string[] = [...(opts.active ?? defaultActive(registry))];
  const settings = opts.settings === undefined ? {} : opts.settings;
  // `append` throws before recording; `append-after` records THEN throws (Pi's non-transactional
  // append: the entry reaches the branch before the persistence that fails).
  let fail:
    | "snapshot"
    | "census"
    | "toolset"
    | "append"
    | "append-after"
    | "settings"
    | "projection"
    | undefined;
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
        exposure: t.exposure ?? "direct",
        sourceInfo: { source: t.source, path: t.path },
        ...(t.annotations !== undefined ? { annotations: t.annotations } : {}),
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
      if (fail === "append-after") throw new Error("append-after");
    },
    ...(settings === null
      ? {}
      : {
          getSettings: () => {
            if (fail === "settings") throw new Error("settings");
            return settings;
          },
        }),
  } as unknown as ExtensionAPI;
  const gate = registerToolGating(pi, floor);
  const hiddenNow = (): string[] => {
    const declared = active.map((name) => ({ name }));
    const loadout = { declared } as unknown as ToolLoadout;
    return [...gate.prepareLoadout(loadout).hiddenDeclarations].sort();
  };
  const sessionManager = SessionManager.inMemory("/repo");
  sessionManager.getBranch = () => {
    throw new Error("branch unavailable");
  };
  // The branch projection Pi's restore reads (resume/fork/`/tree`): empty (no recorded loadout)
  // until `restore`; `fail("projection")` makes it unreadable.
  let projected: unknown[] = [];
  sessionManager.buildSessionProjection = () => {
    if (fail === "projection") throw new Error("projection");
    return { messages: projected } as unknown as ReturnType<
      SessionManager["buildSessionProjection"]
    >;
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
    /**
     * Pi's restore of a branch that records a loadout: the live set becomes `names` and the branch
     * projection now carries a system message. Fire `session_tree` after it (a `/tree` restore),
     * or a `session_start` (a resumed or forked session's constructor restore).
     */
    restore: (names: readonly string[]) => {
      active = [...names];
      projected = [{ role: "system", content: "", timestamp: 1 }];
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
function assertForeignInvariance(h: Fixture, exempt: readonly string[] = []): void {
  const foreign = (n: string) => !isPerkTool(n) && !exempt.includes(n);
  for (const [i, install] of h.installs.entries()) {
    assert.deepEqual(
      install.names.filter(foreign).sort(),
      install.liveForeign.filter(foreign).sort(),
      `install #${i} touched a foreign name`,
    );
  }
}

/** The backstop's verdict on one call; `parentToolCallId` marks it nested (another tool issued it). */
async function blockOf(
  h: Fixture,
  toolName: string,
  input: Record<string, unknown> = {},
  parentToolCallId?: string,
) {
  return h.call("tool_call", {
    toolName,
    input,
    ...(parentToolCallId !== undefined ? { parentToolCallId } : {}),
  });
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
      assert.deepEqual(
        failure === "append" ? h.gate.enter() : h.gate.syncFromState(mode, undefined),
        {
          status: "failed",
          requested: failure === "append" ? "read-only" : "read-write",
          access: "read-only",
          step: failure === "append" ? "persist" : "install",
          error: failure,
        },
      );
      await quietly(() => assertBackstop(h, { readable: failure !== "census" }));
      h.fail(undefined);
      assert.deepEqual(h.gate.exit(), {
        status: "restricted",
        requested: "read-write",
        access: "read-only",
      });
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
  assert.deepEqual(h.gate.syncFromState("read-write", undefined), {
    status: "failed",
    requested: "read-write",
    access: "read-only",
    step: "install",
    error: "toolset",
  });
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
  assert.deepEqual(h.gate.syncFromState("read-only", undefined), {
    status: "failed",
    requested: "read-only",
    access: "read-only",
    step: "install",
    error: "census",
  });
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

// --- the transition result (contracts.md §8.40) ------------------------------------------------

const APPLIED_ON = { status: "applied", requested: "read-only", access: "read-only" } as const;
const APPLIED_OFF = { status: "applied", requested: "read-write", access: "read-write" } as const;
const RESTRICTED = { status: "restricted", requested: "read-write", access: "read-only" } as const;

async function assertWritesClosed(h: Fixture): Promise<void> {
  assert.equal(h.gate.isActive(), true);
  for (const toolName of ["edit", "write"]) {
    assert.equal((await blockOf(h, toolName))?.block, true, `${toolName} blocked`);
  }
}

test("the transition result without a floor: every transition applies with matching requested/access", () => {
  const h = gateFixture(() => false);
  assert.deepEqual(h.gate.enter(), APPLIED_ON);
  assert.deepEqual(h.gate.enter(), APPLIED_ON, "a repeated enter still applies");
  assert.deepEqual(h.gate.exit(), APPLIED_OFF);
  assert.deepEqual(h.appends, [
    { mode: "read-only" },
    { mode: "read-only" },
    { mode: "read-write" },
  ]);
  assert.deepEqual(h.gate.syncFromState("read-only", undefined), APPLIED_ON);
  assert.deepEqual(h.gate.syncFromState("read-write", undefined), APPLIED_OFF);
  assert.deepEqual(h.gate.syncFromState("read-only", "plan"), APPLIED_ON);
  assert.deepEqual(h.gate.syncFromState(undefined, undefined), APPLIED_OFF);
  assert.equal(h.appends.length, 3, "a sync never appends");
});

test("the transition result under a floor: a release is restricted (no append), a restriction applies", () => {
  const suppliers: (() => boolean)[] = [
    () => true,
    () => {
      throw new Error("supplier");
    },
  ];
  for (const floor of suppliers) {
    const h = gateFixture(floor);
    assert.deepEqual(h.gate.exit(), RESTRICTED);
    assert.deepEqual(h.gate.syncFromState("read-write", undefined), RESTRICTED);
    assert.deepEqual(h.gate.syncFromState(undefined, undefined), RESTRICTED);
    assert.deepEqual(h.gate.enter(), APPLIED_ON);
    assert.deepEqual(h.gate.syncFromState("read-only", undefined), APPLIED_ON);
    assert.deepEqual(h.gate.exit(), RESTRICTED);
    assert.deepEqual(h.appends, [{ mode: "read-only" }], "only the enter appended");
  }
});

test("a persist-failed enter is latched closed whether or not the branch took the entry; no install", async () => {
  for (const failure of ["append", "append-after"] as const) {
    const h = gateFixture(() => false);
    h.fail(failure);
    assert.deepEqual(h.gate.enter(), {
      status: "failed",
      requested: "read-only",
      access: "read-only",
      step: "persist",
      error: failure,
    });
    assert.deepEqual(h.appends, failure === "append" ? [] : [{ mode: "read-only" }], failure);
    assert.deepEqual(h.installs, [], "no install after a failed persist");
    await assertWritesClosed(h);
  }
});

test("a persist-failed exit never opens the gate; the next rebuild follows what the branch carries", async () => {
  for (const failure of ["append", "append-after"] as const) {
    const h = gateFixture(() => false);
    assert.deepEqual(h.gate.enter(), APPLIED_ON);
    h.appends.splice(0);
    h.fail(failure);
    assert.deepEqual(h.gate.exit(), {
      status: "failed",
      requested: "read-write",
      access: "read-only",
      step: "persist",
      error: failure,
    });
    assert.deepEqual(h.appends, failure === "append" ? [] : [{ mode: "read-write" }], failure);
    await assertWritesClosed(h);
    for (const name of ["edit", "write"])
      assert.ok(h.hidden().includes(name), `${name} still hidden after the held release`);
    if (failure === "append-after") {
      // The rebuild point reads the branch, which took the read-write entry: the gate opens.
      h.fail(undefined);
      assert.deepEqual(h.gate.syncFromState("read-write", undefined), APPLIED_OFF);
      assert.equal(h.gate.isActive(), false);
      assert.equal(await blockOf(h, "write"), undefined);
    }
  }
});

test("an install-failed enter/exit is fail-closed with the mode entry appended; a clean exit then applies", async () => {
  const h = gateFixture(() => false);
  h.fail("toolset");
  assert.deepEqual(h.gate.enter(), {
    status: "failed",
    requested: "read-only",
    access: "read-only",
    step: "install",
    error: "toolset",
  });
  assert.deepEqual(h.appends, [{ mode: "read-only" }]);
  await quietly(() => assertWritesClosed(h));
  h.fail(undefined);
  assert.deepEqual(h.gate.syncFromState("read-only", undefined), APPLIED_ON);
  h.fail("toolset");
  assert.deepEqual(h.gate.exit(), {
    status: "failed",
    requested: "read-write",
    access: "read-only",
    step: "install",
    error: "toolset",
  });
  assert.deepEqual(h.appends.at(-1), { mode: "read-write" });
  for (const name of ["edit", "write"])
    assert.ok(h.hidden().includes(name), `${name} still hidden after the failed release`);
  await quietly(() => assertWritesClosed(h));
  h.fail(undefined);
  assert.deepEqual(h.gate.exit(), APPLIED_OFF);
  assert.equal(h.gate.isActive(), false);

  // Under a floor a throwing reapply on exit is `failed` (something broke), never an append.
  const f = gateFixture(() => true);
  f.fail("toolset");
  assert.deepEqual(f.gate.exit(), {
    status: "failed",
    requested: "read-write",
    access: "read-only",
    step: "install",
    error: "toolset",
  });
  assert.deepEqual(f.appends, []);
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
 * The names the host must hide for the default registry in a landing: itself plus every
 * REGISTERED tool ineligible there, by posture — by name, declared or not (an ineligible perk
 * name the install removed included), so the hiding never depends on the declared list.
 */
function expectedHidden(stage: string | null, mode: Mode): string[] {
  const eligiblePerk = new Set(perkToolsFor(stage, mode));
  const hidden = [
    LOADOUT_HOST_NAME,
    ...perkToolNames().filter((name) => name !== LOADOUT_HOST_NAME && !eligiblePerk.has(name)),
  ];
  if (mode === "read-only") hidden.push("edit", "write", "foreign_mutator");
  if (stage !== null && ![...WORKTREE_STAGES, "stack-review"].includes(stage)) {
    hidden.push("subagent");
  }
  return hidden.sort();
}

test("prepareLoadout: the host hides every ineligible registered name per landing", () => {
  for (const [stage, mode] of [
    [null, "read-only"],
    ["implement", "read-write"],
    ["implement", "read-only"],
    ["plan", "read-write"],
    ["plan", "read-only"],
  ] as const) {
    const h = gateFixture(() => false);
    h.gate.syncFromState(mode, stage ?? undefined);
    // After the install the declared set holds only eligible perk names; the removed ineligible
    // ones are hidden by name all the same (contracts.md §8.40 presentation).
    assert.deepEqual(h.hidden(), expectedHidden(stage, mode), `${String(stage)} ${mode}`);
  }
});

test("prepareLoadout presents hidden declarations only — both arms", async () => {
  const h = gateFixture(() => false);
  h.gate.syncFromState("read-only", "implement");
  const loadout = { declared: h.active().map((name) => ({ name })) } as unknown as ToolLoadout;
  assert.deepEqual(Object.keys(h.gate.prepareLoadout(loadout)), ["hiddenDeclarations"]);
  // A census failure inside the hook takes the catch arm: it still only hides (the host itself).
  h.fail("census");
  const failed = await quietly(async () => h.gate.prepareLoadout(loadout));
  assert.deepEqual(failed, { hiddenDeclarations: [LOADOUT_HOST_NAME] });
});

test("compile-time: a loadout presentation can never carry a description rewrite", () => {
  // @ts-expect-error — `descriptions` is forbidden: the host hides, it never rewrites a description.
  const rewriting: LoadoutPresentation = { hiddenDeclarations: [], descriptions: {} };
  void rewriting;
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
  assert.equal(h.gate.exit().status, "failed");
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

// --- the codemode lift (contracts.md §8.40) --------------------------------------------------------
//
// In a registry read-only stage a user-enabled codemode stays on under the gate when Pi's codemode
// mode is `on`, or is `only` with no stranded writer (a registered, gate-eligible, direct,
// nested-blocked perk tool — today the two mode-over-stage actions while they are not deferred).

const CODEMODE_TOOL: FakeTool = builtin("codemode");

/** A session with Pi's builtin codemode registered and active, under the given settings. */
function withCodemode(
  opts: {
    floor?: () => boolean;
    mode?: "on" | "only";
    registry?: readonly FakeTool[];
    cohort?: boolean;
  } = {},
): Fixture {
  const registry = [...(opts.registry ?? defaultRegistry()), CODEMODE_TOOL];
  return gateFixture(opts.floor ?? (() => false), {
    registry,
    settings: opts.mode === undefined ? {} : { codemode: { mode: opts.mode } },
    ...(opts.cohort === true ? { cohort: true } : {}),
  });
}

/** Codemode lifted: active, declared, a direct call admitted, a nested one still refused. */
async function assertLifted(h: Fixture, label: string): Promise<void> {
  assert.ok(h.active().includes("codemode"), `${label}: codemode kept active`);
  assert.equal(h.hidden().includes("codemode"), false, `${label}: codemode declared`);
  assert.equal(await blockOf(h, "codemode"), undefined, `${label}: a direct call admitted`);
  assert.deepEqual(
    await blockOf(h, "codemode", {}, PARENT_ID),
    nestedDenial("codemode", "an extension builtin"),
    `${label}: a nested call still refused`,
  );
}

/** Codemode suspended: switched off, hidden, a direct call `tool not allowlisted`. */
async function assertSuspended(h: Fixture, label: string): Promise<void> {
  assert.ok(!h.active().includes("codemode"), `${label}: codemode switched off`);
  assert.ok(h.hidden().includes("codemode"), `${label}: codemode hidden`);
  assert.deepEqual(
    await blockOf(h, "codemode"),
    {
      block: true,
      reason: "perk read-only mode: codemode is blocked (tool not allowlisted).",
    },
    `${label}: a direct call refused`,
  );
}

test("the codemode lift: mode on keeps a user-enabled codemode active, declared and directly callable in every registry read-only stage; nested still refused", async () => {
  for (const stage of READ_ONLY_STAGES) {
    const h = withCodemode({ mode: "on" });
    h.gate.syncFromState("read-only", stage);
    await assertLifted(h, stage);
    // The rest of the gate stands: edit/write and the unknown inline stay refused.
    for (const name of ["edit", "write", "foreign_mutator"])
      assert.equal((await blockOf(h, name))?.block, true, `${stage}: ${name}`);
    assertForeignInvariance(h);
  }
  // The default settings (no codemode key) read as `on`.
  const defaulted = withCodemode();
  defaulted.gate.syncFromState("read-only", "plan");
  await assertLifted(defaulted, "default settings");
  // A worktree stage, an unknown stage and an unscoped gate never lift.
  for (const stage of ["implement", "bogus", undefined]) {
    const h = withCodemode({ mode: "on" });
    h.gate.syncFromState("read-only", stage);
    await assertSuspended(h, `${stage}`);
  }
});

test("the codemode lift under mode only: lifted in a cohort session; a nonparticipant keeps it suspended (its mode-over-stage actions stay direct) unless its registry lacks them", async () => {
  // The family is registered deferred there, so neither action is a direct path to strand.
  const cohort = withCodemode({ mode: "only", cohort: true });
  cohort.gate.joinDiscoveryCohort();
  cohort.gate.syncFromState("read-only", "plan");
  await assertLifted(cohort, "cohort plan");

  for (const stage of ["plan", "audit"]) {
    const outside = withCodemode({ mode: "only" });
    outside.gate.syncFromState("read-only", stage);
    await assertSuspended(outside, `nonparticipant ${stage}`);
    // Both actions are gate-eligible (mode-over-stage) and direct here: they would be stranded.
    for (const name of ["push_annotations", "collect_draft_review_wave"])
      assert.ok(outside.active().includes(name), `${stage}: ${name} declared and direct`);
  }

  // Pi's registry filter left both out: nothing strands, so `only` lifts.
  const filtered = withCodemode({
    mode: "only",
    registry: defaultRegistry().filter(
      (t) => !["push_annotations", "collect_draft_review_wave"].includes(t.name),
    ),
  });
  filtered.gate.syncFromState("read-only", "plan");
  await assertLifted(filtered, "nonparticipant without the actions");
});

test("the codemode lift fails closed: an unreadable setting, a child floor in an unscoped session", async () => {
  const unreadable = withCodemode({ mode: "on" });
  unreadable.fail("settings");
  unreadable.gate.syncFromState("read-only", "plan");
  await assertSuspended(unreadable, "a throwing settings read");
  // A host without `getSettings` at all is the same unread mode.
  const registry = [...defaultRegistry(), CODEMODE_TOOL];
  const bare = gateFixture(() => false, {
    registry,
    active: defaultActive(registry),
    settings: null,
  });
  bare.gate.syncFromState("read-only", "plan");
  await assertSuspended(bare, "no getSettings");

  // A child floor: children are unscoped, so the floor never lifts.
  const child = withCodemode({ mode: "on", floor: () => true });
  child.gate.syncFromState(undefined, undefined);
  await assertSuspended(child, "child floor");
  // A /plan toggle in a read-write stage never lifts.
  const toggled = withCodemode({ mode: "on" });
  toggled.gate.syncFromState("read-write", "implement");
  toggled.gate.enter();
  await assertSuspended(toggled, "a /plan toggle in implement");
});

test("the codemode lift follows the stage: plan → implement → plan suspends with the memo, then restores; exit from either state leaves exactly one codemode", async () => {
  const h = withCodemode({ mode: "on" });
  h.gate.syncFromState("read-only", "plan");
  await assertLifted(h, "plan");
  h.gate.syncFromState("read-only", "implement");
  await assertSuspended(h, "implement");
  h.gate.syncFromState("read-only", "plan");
  await assertLifted(h, "plan again");
  assert.equal(h.active().filter((n) => n === "codemode").length, 1, "restored once");
  h.gate.exit();
  assert.equal(h.active().filter((n) => n === "codemode").length, 1, "exit from a lifted landing");

  const g = withCodemode({ mode: "on" });
  g.gate.syncFromState("read-only", "plan");
  g.gate.syncFromState("read-only", "implement");
  await assertSuspended(g, "implement");
  g.gate.exit();
  assert.equal(g.active().filter((n) => n === "codemode").length, 1, "exit from a suspension");
  assertForeignInvariance(h, ["codemode"]);
  assertForeignInvariance(g, ["codemode"]);
});

// --- the discovery cohort ---------------------------------------------------------------------------
//
// The family registers deferred; a cohort session keeps that registration (the fixture's `cohort`),
// a nonparticipant re-declared it `direct` at session_start (the default fixture). "Deferred" is
// read from the registry's reported exposure at every point.

test("a cohort session: the family is registered deferred and inactive; the first sync's one install is the diet and never names a family member; discovery() reads the family from the registry; a nonparticipant (direct) keeps it", async () => {
  const family = discoveryFamily();
  assert.ok(family.length > 0, "the pilot family is catalogued");
  const outside = gateFixture(() => false);
  outside.gate.syncFromState("read-write", "implement");
  assert.deepEqual(outside.gate.discovery(), { cohort: false, family: [] });
  for (const name of family.filter((n) => isEligible(n, undefined, "implement", "read-write")))
    assert.ok(outside.active().includes(name), `a nonparticipant keeps ${name}`);

  const h = gateFixture(() => false, { cohort: true });
  for (const name of family) assert.ok(!h.active().includes(name), `${name} inactive at startup`);
  h.gate.joinDiscoveryCohort();
  assert.equal(h.installs.length, 0, "the join installs nothing itself");
  assert.deepEqual(h.gate.discovery(), { cohort: true, family });
  h.gate.syncFromState("read-write", "implement");
  assert.equal(h.installs.length, 1, "one install at the first sync (the diet)");
  for (const name of family)
    assert.ok(!h.installs[0]?.names.includes(name), `the install never names ${name}`);
  assert.deepEqual(activePerk(h), perkView(perkToolsFor("implement", "read-write", true)));
  assertForeignInvariance(h);
  // A second join and every later point change nothing.
  h.gate.joinDiscoveryCohort();
  await h.call("resources_discover");
  await h.call("before_agent_start");
  h.gate.syncFromState("read-write", "implement");
  assert.equal(h.installs.length, 1, "no further install");
  assert.deepEqual(h.gate.discovery(), { cohort: true, family });
});

test("primeDeferred: finds nothing where the family is direct; in a cohort it activates the registered-deferred eligible inactive members named, in catalog order, and they survive the points while eligible", async () => {
  const outside = gateFixture(() => false);
  outside.gate.syncFromState("read-write", "implement");
  const before = outside.installs.length;
  assert.deepEqual(outside.gate.primeDeferred(["collect_review_wave", "push_annotations"]), []);
  assert.equal(outside.installs.length, before, "no install where nothing is deferred");

  const h = gateFixture(() => false, { cohort: true });
  h.gate.joinDiscoveryCohort();
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
  const h = gateFixture(() => false, { registry, cohort: true });
  h.gate.joinDiscoveryCohort();
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

test("a nonparticipant member still registered deferred (a failed re-declaration): inactive, primable, kept while active and eligible, reported by discovery() with cohort false", async () => {
  const stuck = "objective_stack_status";
  const registry = defaultRegistry().map(
    (t): FakeTool => (t.name === stuck ? { ...t, exposure: "deferred" } : t),
  );
  const h = gateFixture(() => false, { registry });
  assert.ok(!h.active().includes(stuck), "Pi never activated it");
  h.gate.syncFromState("read-write", "implement");
  assert.ok(!h.active().includes(stuck), "reconciliation never activates it");
  assert.ok(h.hidden().includes(stuck), "hidden while undeclared");
  assert.deepEqual(h.gate.discovery(), { cohort: false, family: [stuck] });
  // The rest of the family is direct: always-declared like any perk tool, never primed.
  const direct = discoveryFamily().filter(
    (n) => n !== stuck && isEligible(n, undefined, "implement", "read-write"),
  );
  for (const name of direct) assert.ok(h.active().includes(name), `${name} always-declared`);
  assert.deepEqual(h.gate.primeDeferred([stuck, ...direct]), [stuck], "only the deferred member");
  assert.equal(h.hidden().includes(stuck), false, "declared once primed");
  h.gate.enter();
  assert.ok(h.active().includes(stuck), "gate-allowed, so kept under the gate");
  h.gate.exit();
  assert.ok(h.active().includes(stuck), "kept at the gate exit");
  assert.equal(isEligible(stuck, undefined, "gist-author", "read-write"), false);
  h.gate.syncFromState("read-write", "gist-author");
  assert.ok(!h.active().includes(stuck), "dropped where ineligible");
  h.gate.syncFromState("read-write", "implement");
  assert.ok(!h.active().includes(stuck), "never re-activated by reconciliation");
  assertForeignInvariance(h);
});

// --- the restoration window (contracts.md §8.40) ---------------------------------------------------
//
// Pi drops its pending restored tools on any deactivating `setActiveTools`, so between a window
// opener — a `reload` session_start, a session_start whose branch projection records a loadout (a
// resumed or forked session Pi restored in its constructor), or a session_tree — and the next
// agent_start every perk install only adds; the removals land at agent_start. The fake host models
// a fresh post-restore activation: every registration-activated tool is active (Pi's restore and
// reload re-activate them) and a new gating closure runs; a cohort's deferred family stays inactive
// unless the transcript recorded it.

const CODEMODE: FakeTool = { name: "codemode", source: "builtin", path: "builtin:codemode" };

/** A fresh activation whose live set carries every registrant's tools (codemode too when given). */
function reloaded(opts: { codemode?: boolean; cohort?: boolean; active?: string[] } = {}): Fixture {
  const registry = [...defaultRegistry(), ...(opts.codemode === true ? [CODEMODE] : [])];
  const cohort = opts.cohort === true;
  return gateFixture(() => false, {
    registry,
    active: [
      ...defaultActive(cohort ? cohortRegistry(registry) : registry),
      ...(opts.active ?? []),
    ],
    ...(cohort ? { cohort: true } : {}),
  });
}

const OPENERS = [
  ["a reload session_start", (h: Fixture) => h.call("session_start", { reason: "reload" })],
  [
    "a resumed session_start that records a loadout",
    (h: Fixture) => {
      h.restore(h.active());
      return h.call("session_start", { reason: "resume" });
    },
  ],
  ["a session_tree", (h: Fixture) => h.call("session_tree")],
] as const;

/**
 * The registered perk names ineligible in a landing that the window keeps live but hidden. A
 * deferred family member is never live in a cohort session, so it is not a window removal.
 */
function ineligibleOwn(stage: string | null, mode: Mode): string[] {
  const eligible = new Set(perkToolsFor(stage, mode));
  const family = new Set(discoveryFamily());
  return perkToolNames().filter(
    (name) => name !== LOADOUT_HOST_NAME && !eligible.has(name) && !family.has(name),
  );
}

/** Every install since `from` kept the live set it found (only additions). */
function assertOnlyAdds(h: Fixture, from: number, before: readonly string[], label: string): void {
  const installs = h.installs.slice(from);
  assert.equal(installs.length, 1, `${label}: exactly one install`);
  const names = new Set(installs[0]?.names);
  for (const name of before) assert.ok(names.has(name), `${label}: ${name} kept (no removal)`);
}

test("the restoration window: each opener opens it — a stage sync that drops own tools and a gate entry that suspends codemode each make one install that only adds; a cohort's deferred family contributes no removal", async () => {
  const family = discoveryFamily();
  for (const [label, open] of OPENERS) {
    // A cohort startup: the family was never live, so the diet's removals are the window's only
    // ones; nothing to add, so the install is the identical live set and never names the family.
    const joined = reloaded({ cohort: true });
    await open(joined);
    joined.gate.joinDiscoveryCohort();
    let before = joined.active();
    joined.gate.syncFromState("read-write", "implement");
    assertOnlyAdds(joined, 0, before, `${label}: cohort startup`);
    assert.deepEqual(joined.installs[0]?.names, before, `${label}: identical when nothing added`);
    for (const name of family)
      assert.ok(!joined.active().includes(name), `${label}: ${name} stays inactive`);

    // A stage sync that drops implement's own tools: plan's additions land, the drops wait.
    const staged = reloaded();
    staged.gate.syncFromState("read-write", "implement");
    await open(staged);
    before = staged.active();
    const from = staged.installs.length;
    staged.gate.syncFromState("read-write", "plan");
    assertOnlyAdds(staged, from, before, `${label}: stage sync`);
    for (const name of perkView(perkToolsFor("plan", "read-write")))
      assert.ok(staged.active().includes(name), `${label}: ${name} added at once`);
    assert.ok(staged.active().includes("submit"), `${label}: implement's submit not yet removed`);

    // A gate entry with an active builtin codemode: enforcement is immediate, the switch-off waits.
    const gated = reloaded({ codemode: true });
    gated.gate.syncFromState("read-write", "implement");
    await open(gated);
    before = gated.active();
    const at = gated.installs.length;
    gated.gate.enter();
    assertOnlyAdds(gated, at, before, `${label}: gate entry`);
    assert.ok(gated.active().includes("codemode"), `${label}: codemode still active`);
    assert.equal(gated.gate.isActive(), true, `${label}: the gate is on at once`);
    for (const name of ["codemode", "edit", "submit"])
      assert.equal((await blockOf(gated, name))?.block, true, `${label}: ${name} blocked at once`);
    assertForeignInvariance(joined);
    assertForeignInvariance(staged);
    assertForeignInvariance(gated, ["codemode"]);
  }
});

test("the restoration window's presentation: inside it the host hides the still-active ineligible names by eligibility and every inactive deferred member; the closing install hides every name it removed; an activation unmasks a member", async () => {
  const family = discoveryFamily();
  const h = reloaded({ codemode: true, cohort: true });
  await h.call("session_start", { reason: "reload" });
  h.gate.joinDiscoveryCohort();
  h.gate.syncFromState("read-write", "implement");
  const inWindow = h.installs.at(-1);
  assert.ok(inWindow !== undefined, "the window install re-ran the host's hook");
  for (const name of ineligibleOwn("implement", "read-write")) {
    assert.ok(h.active().includes(name), `${name} still active`);
    assert.ok(inWindow.hidden.includes(name), `${name} hidden by eligibility`);
  }
  for (const name of family) {
    assert.ok(!h.active().includes(name), `${name} never live`);
    assert.ok(inWindow.hidden.includes(name), `${name} (deferred, undeclared) hidden`);
  }
  h.gate.enter();
  const gated = h.installs.at(-1);
  assert.ok(gated?.hidden.includes("codemode"), "the gate-blocked codemode hidden while active");
  assert.ok(h.active().includes("codemode"));

  // The close: the install lands the removals; the hook run inside it hides every removed name.
  const before = h.active();
  await h.call("agent_start");
  const closing = h.installs.at(-1);
  assert.ok(closing !== undefined && closing !== gated, "agent_start installed");
  const removed = before.filter((name) => !closing.names.includes(name));
  for (const name of ["codemode", "submit"])
    assert.ok(removed.includes(name), `${name} removed at the close`);
  for (const name of removed) assert.ok(closing.hidden.includes(name), `${name} hidden by name`);
  for (const name of family)
    assert.ok(!closing.names.includes(name), `${name} never installed by the close`);

  // An activation unmasks a member: a prime (push_annotations is gate-allowed) and an additive
  // owner toggle (a tool_search hit) both stop hiding the member they activate.
  assert.deepEqual(h.gate.primeDeferred(["push_annotations"]), ["push_annotations"]);
  assert.equal(h.installs.at(-1)?.hidden.includes("push_annotations"), false, "primed: shown");
  assert.ok(h.hidden().includes("collect_draft_review_wave"), "an inactive member stays hidden");
  h.setActive([...h.active(), "collect_draft_review_wave"]);
  assert.equal(h.hidden().includes("collect_draft_review_wave"), false, "searched: shown");
  // The gate's one non-perk exception is codemode's suspension; nothing else foreign moved.
  assertForeignInvariance(h, ["codemode"]);
});

test("the restoration window's close: agent_start installs the pre-change target and clears the memos; before_agent_start inside the window removes nothing; a prime inside it survives the close", async () => {
  const h = reloaded({ codemode: true, cohort: true });
  await h.call("session_tree");
  h.gate.joinDiscoveryCohort();
  h.gate.syncFromState("read-only", "implement");
  const before = h.active();
  const from = h.installs.length;
  await h.call("before_agent_start");
  assertOnlyAdds(h, from, before, "before_agent_start");
  assert.deepEqual(h.gate.primeDeferred(["push_annotations"]), ["push_annotations"]);
  assert.deepEqual(h.installs.at(-1)?.names, [...before, "push_annotations"], "additive prime");

  await h.call("agent_start");
  const gatedView = perkView(perkToolsFor("implement", "read-only", true));
  assert.deepEqual(
    activePerk(h),
    [...gatedView, "push_annotations"].sort(),
    "the pre-change target",
  );
  assert.ok(!h.active().includes("codemode"), "codemode switched off at the close");
  // The memos completed: a second close and every later point install nothing…
  const installs = h.installs.length;
  await h.call("agent_start");
  await h.call("before_agent_start");
  await h.call("resources_discover");
  assert.equal(h.installs.length, installs, "idempotent after the close");
  // …and the suspension memo was kept: the gate exit restores codemode.
  h.gate.exit();
  assert.ok(h.active().includes("codemode"), "restored at release");
  assertForeignInvariance(h, ["codemode"]);
});

test("the restoration window after /reload: a member the reload kept live survives the close; a /tree restore of a recorded member survives it too; the rest of the family stays inactive", async () => {
  const family = discoveryFamily();
  const opened = async (active: string[] = []): Promise<Fixture> => {
    const h = reloaded({ cohort: true, active });
    await h.call("session_start", { reason: "reload" });
    h.gate.joinDiscoveryCohort();
    h.gate.syncFromState("read-write", "implement");
    return h;
  };
  // A navigation without a restore: Pi restores nothing, the reload's live set stands.
  const unrestored = await opened();
  for (const name of family)
    assert.ok(!unrestored.active().includes(name), `${name} inactive after /reload`);
  await unrestored.call("session_tree");
  unrestored.gate.syncFromState("read-write", "implement");
  await unrestored.call("agent_start");
  for (const name of family)
    assert.ok(!unrestored.active().includes(name), `${name} stays inactive through the close`);

  // A member primed before the reload: Pi's reload kept the live set, perk keeps it.
  const kept = await opened(["push_annotations"]);
  await kept.call("agent_start");
  assert.ok(kept.active().includes("push_annotations"), "the reload-kept member survives");
  assert.equal(kept.installs.at(-1)?.hidden.includes("push_annotations"), false, "declared");

  // A branch whose transcript carried an activated objective_stack_status (a past search or prime).
  const h = await opened();
  h.restore([...h.active(), "objective_stack_status"]);
  await h.call("session_tree");
  const from = h.installs.length;
  h.gate.syncFromState("read-write", "implement");
  await h.call("agent_start");
  assert.ok(
    h.active().includes("objective_stack_status"),
    "the restored member survives the close",
  );
  assert.equal(
    h.installs.at(-1)?.hidden.includes("objective_stack_status"),
    false,
    "and stays declared",
  );
  for (const install of h.installs.slice(from))
    assert.ok(install.names.includes("objective_stack_status"), "no install dropped it");
  for (const name of family.filter((n) => n !== "objective_stack_status"))
    assert.ok(!h.active().includes(name), `${name} stays off`);
  for (const f of [unrestored, kept, h]) assertForeignInvariance(f);
});

test("a prime inside the restoration window survives the close and stays declared; the rest of the family stays inactive", async () => {
  const family = discoveryFamily();
  const h = reloaded({ cohort: true });
  await h.call("session_start", { reason: "reload" });
  h.gate.joinDiscoveryCohort();
  h.gate.syncFromState("read-write", "implement");
  const live = h.active();
  assert.deepEqual(h.gate.primeDeferred(["push_annotations"]), ["push_annotations"]);
  assert.deepEqual(h.installs.at(-1)?.names, [...live, "push_annotations"], "one additive install");
  await h.call("agent_start");
  assert.ok(h.active().includes("push_annotations"), "the primed member survives the close");
  assert.equal(h.installs.at(-1)?.hidden.includes("push_annotations"), false, "and stays declared");
  for (const name of family.filter((n) => n !== "push_annotations"))
    assert.ok(!h.active().includes(name), `${name} stays inactive`);

  // After a /tree restore left one member active: priming another.
  const t = reloaded({ cohort: true });
  await t.call("session_start", { reason: "reload" });
  t.gate.joinDiscoveryCohort();
  t.gate.syncFromState("read-write", "implement");
  t.restore([...t.active(), "objective_stack_status"]);
  await t.call("session_tree");
  t.gate.syncFromState("read-write", "implement");
  assert.deepEqual(t.gate.primeDeferred(["push_annotations"]), ["push_annotations"]);
  await t.call("agent_start");
  for (const name of ["objective_stack_status", "push_annotations"]) {
    assert.ok(t.active().includes(name), `${name} survives the close`);
    assert.equal(t.installs.at(-1)?.hidden.includes(name), false, `${name} stays declared`);
  }
  assertForeignInvariance(h);
  assertForeignInvariance(t);
});

test("the restoration window stays shut at a session_start that records no loadout (startup, resume, fork, new): the diet lands at once; a bare session's agent_start installs nothing", async () => {
  const family = discoveryFamily();
  for (const reason of ["startup", "resume", "fork", "new"]) {
    const h = reloaded({ cohort: true });
    await h.call("session_start", { reason });
    h.gate.joinDiscoveryCohort();
    h.gate.syncFromState("read-write", "implement");
    assert.equal(h.installs.length, 1, `${reason}: ONE install at startup`);
    assert.deepEqual(
      activePerk(h),
      perkView(perkToolsFor("implement", "read-write", true)),
      `${reason}: the diet landed at once`,
    );
    for (const name of family)
      assert.ok(!h.installs[0]?.names.includes(name), `${reason}: ${name} never installed`);
    await h.call("agent_start");
    assert.equal(h.installs.length, 1, `${reason}: the close finds nothing to land`);
    assertForeignInvariance(h);
  }

  const bare = gateFixture(() => false);
  bare.gate.syncFromState(undefined, undefined);
  await bare.call("agent_start");
  await bare.call("session_start", { reason: "reload" });
  bare.gate.syncFromState(undefined, undefined);
  await bare.call("agent_start");
  assert.deepEqual(bare.installs, [], "zero installs, window or not");
});

test("a session_start whose branch projection records a loadout opens the window (every reason): a gated startup's codemode suspension and a stage change's diet only add until agent_start, where they land; an unreadable projection on a non-reload reason leaves it shut, and reload opens it regardless", async () => {
  for (const reason of ["startup", "resume", "fork", "new", "reload"]) {
    // A restored gated startup: Pi's constructor restore recorded the loadout before any handler.
    const h = reloaded({ codemode: true, cohort: true });
    h.restore(h.active());
    await h.call("session_start", { reason });
    h.gate.joinDiscoveryCohort();
    const before = h.active();
    h.gate.syncFromState("read-only", "implement");
    assertOnlyAdds(h, 0, before, `${reason}: the restored gated startup`);
    assert.ok(h.active().includes("codemode"), `${reason}: the suspension waits`);
    assert.ok(h.active().includes("submit"), `${reason}: the diet waits`);
    assert.equal((await blockOf(h, "codemode"))?.block, true, `${reason}: enforcement at once`);
    await h.call("agent_start");
    assert.ok(!h.active().includes("codemode"), `${reason}: suspended at the close`);
    assert.deepEqual(
      activePerk(h),
      perkView(perkToolsFor("implement", "read-only", true)),
      `${reason}: the diet landed at the close`,
    );
    assertForeignInvariance(h, ["codemode"]);

    // A stage change inside the window: the diet only adds until the close.
    const s = reloaded({ cohort: true });
    s.restore(s.active());
    await s.call("session_start", { reason });
    s.gate.syncFromState("read-write", "implement");
    const live = s.active();
    const from = s.installs.length;
    s.gate.syncFromState("read-write", "plan");
    assertOnlyAdds(s, from, live, `${reason}: the stage change`);
    assert.ok(s.active().includes("submit"), `${reason}: implement's submit not yet removed`);
    await s.call("agent_start");
    assert.ok(!s.active().includes("submit"), `${reason}: removed at the close`);
    assertForeignInvariance(s);
  }
  // An unreadable projection reads as no restore: a non-reload reason leaves the window shut.
  for (const reason of ["startup", "resume", "fork", "new"]) {
    const u = reloaded({ cohort: true });
    u.fail("projection");
    await u.call("session_start", { reason });
    u.gate.syncFromState("read-write", "implement");
    assert.deepEqual(
      activePerk(u),
      perkView(perkToolsFor("implement", "read-write", true)),
      `${reason}: unreadable projection — the diet landed at once`,
    );
  }
  const r = reloaded({ cohort: true });
  r.fail("projection");
  await r.call("session_start", { reason: "reload" });
  const before = r.active();
  r.gate.syncFromState("read-write", "implement");
  assertOnlyAdds(r, 0, before, "reload with an unreadable projection");
  assert.ok(r.active().includes("submit"), "the reload window holds the diet's removal");
});

test("a throwing closing install leaves the window's removals for the next point", async () => {
  const h = reloaded({ cohort: true });
  await h.call("session_start", { reason: "reload" });
  h.gate.joinDiscoveryCohort();
  h.gate.syncFromState("read-write", "plan");
  assert.ok(h.active().includes("submit"), "the diet's removal waits in the window");
  h.fail("toolset");
  await quietly(async () => {
    await h.call("agent_start");
  });
  assert.ok(h.active().includes("submit"), "still active after the failed close");
  h.fail(undefined);
  await h.call("before_agent_start");
  assert.ok(!h.active().includes("submit"), "removed at the next point");
});

test("the codemode lift in the restoration window: a reload in a gated plan landing removes nothing; a /tree restore landing in implement waits for the close to suspend", async () => {
  for (const [label, open] of OPENERS) {
    const h = reloaded({ codemode: true });
    await open(h);
    h.gate.syncFromState("read-only", "plan");
    assert.ok(h.active().includes("codemode"), `${label}: kept in the window`);
    await h.call("agent_start");
    assert.ok(h.active().includes("codemode"), `${label}: kept through the close`);
    for (const [i, install] of h.installs.entries())
      assert.ok(install.names.includes("codemode"), `${label}: install #${i} kept codemode`);
    assert.equal(h.hidden().includes("codemode"), false, `${label}: declared`);
  }

  // Lifted in plan; a /tree restore opens the window and the landing moves to implement.
  const t = reloaded({ codemode: true });
  t.gate.syncFromState("read-only", "plan");
  assert.ok(t.active().includes("codemode"));
  t.restore(t.active());
  await t.call("session_tree");
  const before = t.active();
  const from = t.installs.length;
  t.gate.syncFromState("read-only", "implement");
  assertOnlyAdds(t, from, before, "the stage sync");
  assert.ok(t.active().includes("codemode"), "the suspension waits for the close");
  assert.equal((await blockOf(t, "codemode"))?.block, true, "enforcement is immediate");
  await t.call("agent_start");
  assert.ok(!t.active().includes("codemode"), "suspended at the close");
  t.gate.exit();
  assert.equal(t.active().filter((n) => n === "codemode").length, 1, "the memo restores it");
  assertForeignInvariance(t, ["codemode"]);
});

test("the codemode lift consumes the suspension memo: a lift's restore inside the window lands at once, the close consumes the memo, and a later deactivation is never undone", async () => {
  // Suspended and remembered in gated implement; the window opens; a sync to gated plan.
  const viaSync = async (opener: (h: Fixture) => unknown): Promise<Fixture> => {
    const h = reloaded({ codemode: true });
    h.gate.syncFromState("read-only", "implement");
    assert.ok(!h.active().includes("codemode"), "suspended in implement");
    await opener(h);
    return h;
  };
  for (const [label, open] of OPENERS) {
    const h = await viaSync(open);
    const before = h.active();
    const from = h.installs.length;
    h.gate.syncFromState("read-only", "plan");
    // The stage removals (implement's objective_node) wait; codemode's restore lands at once.
    assert.ok(perkToolsFor("implement", "read-only").includes("objective_node"));
    assert.ok(!perkToolsFor("plan", "read-only").includes("objective_node"));
    assertOnlyAdds(h, from, before, `${label}: the in-window sync`);
    assert.ok(h.active().includes("codemode"), `${label}: restored at once`);
    assert.ok(h.active().includes("objective_node"), `${label}: the removal waits`);
    await h.call("agent_start");
    assert.ok(!h.active().includes("objective_node"), `${label}: the removal landed`);
    assert.ok(h.active().includes("codemode"), `${label}: codemode active after the close`);
    await assertNeverUndone(h, label);
  }

  // The same through Pi's /tree restore of a loadout that already carries codemode.
  const t = reloaded({ codemode: true });
  t.gate.syncFromState("read-only", "implement");
  assert.ok(!t.active().includes("codemode"));
  t.restore([...t.active(), "codemode"]);
  await t.call("session_tree");
  const before = t.active();
  const from = t.installs.length;
  t.gate.syncFromState("read-only", "plan");
  assertOnlyAdds(t, from, before, "tree restore: the in-window sync");
  await t.call("agent_start");
  assert.ok(t.active().includes("codemode"), "tree restore: kept through the close");
  await assertNeverUndone(t, "tree restore");
});

/** The user (or host) switches codemode off: no later point, nor the gate exit, brings it back. */
async function assertNeverUndone(h: Fixture, label: string): Promise<void> {
  h.setActive(h.active().filter((n) => n !== "codemode"));
  await h.call("before_agent_start");
  await h.call("resources_discover");
  await h.call("agent_start");
  assert.ok(!h.active().includes("codemode"), `${label}: never re-added under the gate`);
  h.gate.exit();
  assert.ok(!h.active().includes("codemode"), `${label}: the exit adds nothing`);
  assertForeignInvariance(h, ["codemode"]);
}

// --- the nested policy (contracts.md §8.40) --------------------------------------------------------
//
// A call carrying `parentToolCallId` (another tool issued it through `ctx.executeTool`) is narrowed
// further under the gate: only a gate-eligible perk query, a core builtin read (`bash` by verdict)
// and a foreign tool by its gate posture run. Every nested denial is pinned beside its admitted
// direct twin, so each pin discriminates the nested branch. A bounded writer (and every model-only
// kind) never reaches this hook nested in a real session — Pi refuses it first (a script's
// `tools.<name> does not exist.`, agent-core's `Tool <name> not found`); the fake host fabricates
// the event to pin the defense-in-depth arm behind both.

const PARENT_ID = "toolu_parent";

/** The nested refusal, verbatim. */
function nestedDenial(name: string, kind: string) {
  return {
    block: true,
    reason: `perk read-only mode: ${name} is blocked (nested call — ${kind} is never a nested grant; only gate-eligible queries and builtin reads run through another tool).`,
  };
}

/** A name admitted direct and refused nested with `kind` in the refusal. */
async function assertNestedOnlyDenied(h: Fixture, name: string, kind: string, label = "") {
  assert.equal(await blockOf(h, name), undefined, `${label}${name} direct`);
  assert.deepEqual(
    await blockOf(h, name, {}, PARENT_ID),
    nestedDenial(name, kind),
    `${label}${name} nested`,
  );
}

/** A call admitted direct and nested alike. */
async function assertAdmittedBothWays(
  h: Fixture,
  name: string,
  input: Record<string, unknown> = {},
  label = "",
) {
  assert.equal(await blockOf(h, name, input), undefined, `${label}${name} direct`);
  assert.equal(await blockOf(h, name, input, PARENT_ID), undefined, `${label}${name} nested`);
}

test("the nested policy: under the gate a nested call reaches only a gate-eligible query, a core builtin read and a foreign tool by its posture", async () => {
  const h = gateFixture(() => false, {
    registry: [...defaultRegistry(), builtin("tool_search")],
  });
  h.gate.syncFromState("read-only", "plan");
  await assertAdmittedBothWays(h, "objective_stack_status");
  await assertAdmittedBothWays(h, "read");
  await assertAdmittedBothWays(h, "bash", { command: "git status" });
  await assertAdmittedBothWays(h, "structured_output");
  for (const [name, kind] of [
    ["plan_draft", "a bounded writer"],
    ["push_annotations", "an action tool"],
    ["plan_review", "a terminal tool"],
    ["run_scout_wave", "an orchestration tool"],
    [LOADOUT_HOST_NAME, "a host tool"],
    ["tool_search", "an extension builtin"],
  ] as const) {
    await assertNestedOnlyDenied(h, name, kind);
  }
  // The earlier arms keep their wordings for a nested call.
  assert.deepEqual(await blockOf(h, "edit", {}, PARENT_ID), {
    block: true,
    reason: "perk read-only mode: edit is blocked (file modifications disabled).",
  });
  for (const name of ["foreign_mutator", "subagent"]) {
    assert.deepEqual(await blockOf(h, name, {}, PARENT_ID), {
      block: true,
      reason: `perk read-only mode: ${name} is blocked (tool not allowlisted).`,
    });
  }
  assert.deepEqual(await blockOf(h, "never_known_tool", {}, PARENT_ID), {
    block: true,
    reason: "perk read-only mode: never_known_tool is blocked (tool not registered).",
  });
  const touch = await blockOf(h, "bash", { command: "touch x" });
  assert.ok(
    touch?.reason?.startsWith(
      "perk read-only mode: command blocked (not allowlisted).\nCommand: touch x\nReason: ",
    ),
  );
  assert.deepEqual(await blockOf(h, "bash", { command: "touch x" }, PARENT_ID), touch);
  assertForeignInvariance(h);
});

test("the nested policy follows the landing: delegation by posture, the refinement writer's defense-in-depth arm, an unknown stage, the gate exit", async () => {
  const h = gateFixture(() => false);
  h.gate.syncFromState("read-only", "implement");
  await assertAdmittedBothWays(h, "subagent", {}, "implement: ");
  await assertNestedOnlyDenied(h, "plan_draft", "a bounded writer", "implement: ");

  h.gate.syncFromState("read-only", "objective-refine");
  await assertNestedOnlyDenied(h, "objective_refinement_draft", "a bounded writer", "refine: ");
  await assertAdmittedBothWays(h, "objective_stack_status", {}, "refine: ");

  // An unknown stage id is unscoped: the gate's eligibility, the nested narrowing on top.
  h.gate.syncFromState("read-only", "bogus");
  await assertAdmittedBothWays(h, "objective_stack_status", {}, "bogus: ");
  await assertNestedOnlyDenied(h, "plan_draft", "a bounded writer", "bogus: ");

  // Read-write: no call-time backstop, nested or not.
  h.gate.exit();
  for (const name of ["plan_draft", "write", "push_annotations", "foreign_mutator"])
    assert.equal(await blockOf(h, name, {}, PARENT_ID), undefined, `released: ${name}`);
  assert.equal(await blockOf(h, "bash", { command: "touch x" }, PARENT_ID), undefined);
  assertForeignInvariance(h);
});

test("the nested policy holds under a child floor and inside the restoration window", async () => {
  const pair = async (h: Fixture, label: string) => {
    await assertAdmittedBothWays(h, "objective_stack_status", {}, `${label}: `);
    await assertNestedOnlyDenied(h, "plan_draft", "a bounded writer", `${label}: `);
  };
  // A child floor (no sync yet — unscoped): the same narrowing.
  const floor = gateFixture(() => true);
  await pair(floor, "floor");

  // A reload: enforcement never waits for agent_start.
  const reload = reloaded();
  await reload.call("session_start", { reason: "reload" });
  reload.gate.syncFromState("read-only", "plan");
  await pair(reload, "reload window");
  await reload.call("agent_start");
  await pair(reload, "reload closed");

  // A /tree restore likewise.
  const tree = reloaded();
  tree.restore(tree.active());
  await tree.call("session_tree");
  tree.gate.syncFromState("read-only", "plan");
  await pair(tree, "tree window");
  await tree.call("agent_start");
  await pair(tree, "tree closed");
  for (const h of [floor, reload, tree]) assertForeignInvariance(h);
});

test("a tool's own readOnlyHint never authorizes: an unknown-provenance tool stays blocked direct and nested", async () => {
  const hinted: FakeTool = {
    name: "hinted_inline",
    source: "inline",
    path: "<inline:hinted>",
    annotations: { readOnlyHint: true },
  };
  const h = gateFixture(() => false, { registry: [...defaultRegistry(), hinted] });
  h.gate.syncFromState("read-only", "plan");
  const refusal = {
    block: true,
    reason: "perk read-only mode: hinted_inline is blocked (tool not allowlisted).",
  };
  assert.deepEqual(await blockOf(h, "hinted_inline"), refusal);
  assert.deepEqual(await blockOf(h, "hinted_inline", {}, PARENT_ID), refusal);
  assertForeignInvariance(h);
});
