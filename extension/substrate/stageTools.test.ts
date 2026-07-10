// Stage-scoped active tools (contracts.md §8.40): the STAGE_TOOLS map hygiene + the live
// scoping behavior driven through a REAL bound AgentSession via the harness (fully offline).
// Sibling of toolGating.test.ts (which stays focused on the read-only gate itself).

import assert from "node:assert/strict";
import { test } from "node:test";
import { type ExtensionAPI, SessionManager } from "@earendil-works/pi-coding-agent";
import {
  loadPerkSession,
  type PerkSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import { loadRegistry } from "./registry.ts";
import { BORROWED_TOOLS, PERK_TOOLS, READ_ONLY_TOOLS, STAGE_TOOLS } from "./toolGating.ts";

/**
 * loadPerkSession with process.cwd() pointed at the scaffold for the load: provider vacating
 * (e.g. ask_user_question under a foreign `[providers] askuser`) resolves `process.cwd()` at
 * factory time, so running the suite from a repo with its own selections would otherwise leak
 * into what registers (the planMode.test.ts chdir pattern). Restores cwd before returning.
 */
async function loadAt(
  cwd: string,
  opts: Omit<Parameters<typeof loadPerkSession>[0], "cwd"> = {},
): Promise<PerkSession> {
  const savedCwd = process.cwd();
  process.chdir(cwd);
  try {
    return await loadPerkSession({ cwd, ...opts });
  } finally {
    process.chdir(savedCwd);
  }
}

/** The 8 authoring tools every worktree-stage session must scope off. */
const AUTHORING_TOOLS = [
  "plan_draft",
  "plan_review",
  "plan_save",
  "objective_draft",
  "objective_save",
  "objective_node",
  "reconcile_objective",
  "add_objective_node",
];

test("STAGE_TOOLS: keys set-equal the registry stage ids", () => {
  const registryIds = loadRegistry()
    .stages.map((s) => s.id)
    .sort();
  const mapKeys = Object.keys(STAGE_TOOLS).sort();
  assert.deepEqual(
    mapKeys,
    registryIds,
    "STAGE_TOOLS must carry exactly one entry per registry stage id",
  );
});

test("STAGE_TOOLS: every listed name is in the scoped universe, and ask_user_question is universal", () => {
  const scoped = new Set([...PERK_TOOLS, ...BORROWED_TOOLS]);
  for (const [stage, tools] of Object.entries(STAGE_TOOLS)) {
    for (const name of tools) {
      assert.ok(
        scoped.has(name),
        `${stage} lists a name outside PERK_TOOLS ∪ BORROWED_TOOLS: ${name}`,
      );
    }
    assert.ok(tools.includes("ask_user_question"), `${stage} must carry ask_user_question`);
  }
});

test("BORROWED_TOOLS: no duplicates and zero overlap with PERK_TOOLS (single governance)", () => {
  assert.equal(
    new Set(BORROWED_TOOLS).size,
    BORROWED_TOOLS.length,
    "BORROWED_TOOLS carries a duplicate name",
  );
  assert.deepEqual(
    BORROWED_TOOLS.filter((name) => PERK_TOOLS.includes(name)),
    [],
    "a name is governed ONCE — a shared name (e.g. ask_user_question) belongs to PERK_TOOLS only",
  );
});

test("PERK_TOOLS: set-equals the non-builtin tools a perk-only session registers", async () => {
  // The completeness drift guard: the harness binds ONLY perk with no [providers] config, so all
  // perk registrations are live and builtins are the only other source. A new perk tool must be
  // classified into PERK_TOOLS + STAGE_TOOLS before it can register.
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: undefined } });
  try {
    const registered = h.session
      .getAllTools()
      .filter((t) => t.sourceInfo.source !== "builtin")
      .map((t) => t.name)
      .sort();
    assert.deepEqual(
      registered,
      [...PERK_TOOLS].sort(),
      "a new perk tool must be classified into PERK_TOOLS and the STAGE_TOOLS map",
    );
  } finally {
    h.dispose();
  }
});

test("implement claim: PR-loop family active, the 8 authoring tools scoped off", async () => {
  const runId = "01STAGETOOLIMPL";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId } });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["submit", "ready", "run_ci", "land", "learn", "resolve_review_threads"]) {
      assert.ok(active.includes(name), `PR-loop tool must stay active: ${name}`);
    }
    for (const name of ["read", "bash", "edit", "write"]) {
      assert.ok(active.includes(name), `builtin must pass through untouched: ${name}`);
    }
    for (const name of AUTHORING_TOOLS) {
      assert.ok(!active.includes(name), `authoring tool must be scoped off: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

test("gated stage: gate ON keeps exactly the READ_ONLY_TOOLS-available subset (no stage filter)", async () => {
  const runId = "01STAGETOOLOBJP";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-only", stage: "objective-plan" } });
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId } });
  try {
    const active = [...h.session.getActiveToolNames()].sort();
    // The gate-on set is byte-for-byte today's: the registered subset of READ_ONLY_TOOLS,
    // including the carve-outs a strict stage intersection would have broken.
    const expected = h.session
      .getAllTools()
      .map((t) => t.name)
      .filter((name) => READ_ONLY_TOOLS.includes(name))
      .sort();
    assert.deepEqual(active, expected);
    for (const name of ["objective_node", "plan_draft", "plan_review"]) {
      assert.ok(active.includes(name), `gated carve-out must stay active: ${name}`);
    }
    for (const name of ["edit", "write"]) {
      assert.ok(!active.includes(name), `${name} must be inactive while gated`);
    }
  } finally {
    h.dispose();
  }
});

test("unknown stage id: fail-open (no filtering — version-skew safety)", async () => {
  const runId = "01STAGETOOLFUTR";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "future-stage" } });
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId } });
  try {
    const active = h.session.getActiveToolNames();
    assert.ok(active.includes("plan_draft"), "an unknown stage id must not filter anything");
    assert.ok(active.includes("submit"));
    assert.ok(active.includes("edit"));
  } finally {
    h.dispose();
  }
});

test("bare session: no stage → zero perk intervention (pi's default active set survives)", async () => {
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: undefined } });
  try {
    const active = new Set(h.session.getActiveToolNames());
    // Nothing filtered: every perk tool and the default-active builtins stay active.
    for (const name of [...PERK_TOOLS, "read", "bash", "edit", "write"]) {
      assert.ok(active.has(name), `must stay active in an unscoped session: ${name}`);
    }
    // Nothing widened: pi registers grep/find/ls but leaves them INACTIVE by default — an
    // accidental setActiveTools (e.g. a restore via the getAllTools fallback) would activate
    // them. Their staying inactive is the sharp zero-setActiveTools canary (this pins pi's
    // current default; update if pi ever activates these by default).
    for (const name of ["grep", "find", "ls"]) {
      assert.ok(!active.has(name), `pi default-inactive builtin must stay untouched: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

test("tree navigation: gate/stage recompute across mode entries", async () => {
  const cwd = scaffoldRepo();
  // stage=plan rides the branch (per-field LWW); the two mode entries flip the gate across it.
  const file = plantSession(cwd, [{ stage: "plan", mode: "read-only" }, { mode: "read-write" }]);
  const h = await loadAt(cwd, {
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const ids = h.entryIds();
    const [readOnlyId, readWriteId] = ids as [string, string];

    // Navigate to the read-only entry → gate ON → exactly the READ_ONLY_TOOLS-available subset.
    await h.navigateTo(readOnlyId);
    const gated = [...h.session.getActiveToolNames()].sort();
    const expectedGated = h.session
      .getAllTools()
      .map((t) => t.name)
      .filter((name) => READ_ONLY_TOOLS.includes(name))
      .sort();
    assert.deepEqual(gated, expectedGated);

    // Navigate to the read-write entry → gate OFF + stage plan → the stage-filtered set.
    await h.navigateTo(readWriteId);
    const scoped = h.session.getActiveToolNames();
    assert.ok(scoped.includes("plan_save"), "plan-stage tool active once the gate is off");
    assert.ok(!scoped.includes("submit"), "PR-loop tool scoped off in a plan-stage session");
    assert.ok(scoped.includes("edit"), "builtins restored once the gate is off");
    assert.ok(scoped.includes("write"));
  } finally {
    h.dispose();
  }
});

// --- borrowed-package scoping (the fake-borrowed-package idiom, mirroring fakePlannotator) -------

/**
 * A fake borrowed-package extension registering LOAD-TIME tools with the given names (the
 * pi-subagents / rpiv-todo / pi-web-access / pi-mono-linear / plannotator registration shape).
 * Bound after perk via extraExtensions, so the tools exist before perk's session_start sync.
 */
function fakeBorrowedPackage(names: readonly string[]): (pi: ExtensionAPI) => void {
  return (pi) => {
    for (const name of names) {
      pi.registerTool({
        name,
        label: name,
        description: `fake borrowed tool ${name} (test)`,
        parameters: { type: "object", properties: {} },
        async execute() {
          return { content: [{ type: "text", text: "ok" }], details: {} };
        },
      });
    }
  };
}

/** The census cross-section the fake package registers (+ one un-enumerated foreign name). */
const FAKE_BORROWED_NAMES = [
  "subagent",
  "wait",
  "todo",
  "web_search",
  "linear_get_issue",
  "linear_create_issue",
  "plannotator_submit_plan",
  "some_foreign_tool",
];

test("implement claim: borrowed tools follow the matrix (research/delegation/todo stay; mutating/submit drop)", async () => {
  const runId = "01STAGETOOLBRWI";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const h = await loadAt(cwd, {
    env: { PERK_RUN_ID: runId },
    extraExtensions: [fakeBorrowedPackage(FAKE_BORROWED_NAMES)],
  });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["subagent", "wait", "todo", "web_search", "linear_get_issue"]) {
      assert.ok(active.includes(name), `worktree-stage borrowed tool must stay active: ${name}`);
    }
    assert.ok(
      active.includes("some_foreign_tool"),
      "an un-enumerated foreign name passes through untouched (fail-open)",
    );
    for (const name of ["linear_create_issue", "plannotator_submit_plan"]) {
      assert.ok(!active.includes(name), `census tool in no stage list must be scoped off: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

test("plan stage (read-write): delegation + todo scoped off; research passes", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ stage: "plan", mode: "read-write" }]);
  const h = await loadAt(cwd, {
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
    extraExtensions: [fakeBorrowedPackage(FAKE_BORROWED_NAMES)],
  });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["subagent", "wait", "todo"]) {
      assert.ok(!active.includes(name), `worktree-only borrowed tool must drop in plan: ${name}`);
    }
    for (const name of ["web_search", "linear_get_issue"]) {
      assert.ok(active.includes(name), `research tool must stay active in plan: ${name}`);
    }
    assert.ok(active.includes("some_foreign_tool"), "un-enumerated foreign name passes through");
  } finally {
    h.dispose();
  }
});

test("late registration leaks past rebuild-point filtering (the accepted supervisor-pair leak)", async () => {
  // Mirrors pi-subagents' parent intercom pair: registered inside its own session_start handler,
  // bound AFTER perk (the real load order — perk is the first `packages` entry), so registration
  // lands after perk's sync. Pi activation semantics: a tool registered after a setActiveTools
  // call becomes active — the pair leaks at launch (accepted + documented in BORROWED_TOOLS; a
  // later tree-navigation re-apply filters over the original snapshot and drops it).
  const runId = "01STAGETOOLLEAK";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const lateRegistrar = (pi: ExtensionAPI): void => {
    pi.on("session_start", async () => {
      pi.registerTool({
        name: "subagent_supervisor",
        label: "subagent_supervisor",
        description: "fake late-registered parent intercom (test)",
        parameters: { type: "object", properties: {} },
        async execute() {
          return { content: [{ type: "text", text: "ok" }], details: {} };
        },
      });
    });
  };
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId }, extraExtensions: [lateRegistrar] });
  try {
    assert.ok(
      h.session.getActiveToolNames().includes("subagent_supervisor"),
      "a tool registered after perk's sync stays active (the documented launch leak)",
    );
  } finally {
    h.dispose();
  }
});
