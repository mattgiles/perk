// Stage-scoped active tools (contracts.md §8.40): the STAGE_TOOLS map hygiene + the live
// scoping behavior driven through a REAL bound AgentSession via the harness (fully offline).
// Sibling of toolGating.test.ts (which stays focused on the read-only gate itself).

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import {
  loadPerkSession,
  type PerkSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import { loadRegistry } from "./registry.ts";
import { PERK_TOOLS, READ_ONLY_TOOLS, STAGE_TOOLS } from "./toolGating.ts";

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

test("STAGE_TOOLS: every listed name is a perk tool, and ask_user_question is universal", () => {
  for (const [stage, tools] of Object.entries(STAGE_TOOLS)) {
    for (const name of tools) {
      assert.ok(PERK_TOOLS.includes(name), `${stage} lists non-perk tool ${name}`);
    }
    assert.ok(tools.includes("ask_user_question"), `${stage} must carry ask_user_question`);
  }
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
