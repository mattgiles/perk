// The tool catalog's pure policy: stage families, derived Pi metadata, registration-time
// validation, the eligibility formula and the derived views. Fakes are recorded straight into
// this process's catalog (node --test isolates each file in its own process), so nothing here
// leaks into the census/parity/fixture suites.

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadRegistry } from "./registry.ts";
import {
  AUTHORING_STAGES,
  BORROWED_TOOLS,
  BUILTIN_TOOL_POLICY,
  carveOutWritersFor,
  derivePiMetadata,
  dietUniverse,
  FOREIGN_TOOL_POLICY,
  GIST_STAGES,
  gatedToolsFor,
  isEligible,
  isPerkTool,
  LINEAR_MUTATING_TOOLS,
  normalizeStage,
  OBJECTIVE_STAGES,
  PLAN_FAMILY_STAGES,
  PLANNOTATOR_PHASE_TOOLS,
  perkToolNames,
  perkToolPolicy,
  REGISTRY_STAGE_IDS,
  recordPerkTool,
  SUBAGENT_CHILD_TOOLS,
  SUBAGENT_TOOLS,
  stageToolsFor,
  type ToolPolicy,
  toolMatrix,
  validateToolPolicy,
  WORKTREE_STAGES,
} from "./toolPolicy.ts";

const REGISTRY_IDS = loadRegistry().stages.map((s) => s.id);

test("stage families: every member is a registry id; the worktree family is the five plan-ref consumers", () => {
  assert.deepEqual(REGISTRY_STAGE_IDS, REGISTRY_IDS);
  for (const family of [
    WORKTREE_STAGES,
    PLAN_FAMILY_STAGES,
    OBJECTIVE_STAGES,
    AUTHORING_STAGES,
    GIST_STAGES,
  ]) {
    for (const id of family) assert.ok(REGISTRY_IDS.includes(id), `not a registry stage: ${id}`);
  }
  assert.deepEqual([...WORKTREE_STAGES].sort(), [
    "address",
    "implement",
    "land",
    "learn",
    "submit",
  ]);
});

test("derivePiMetadata: terminal/interactive/orchestration are model-only; readOnlyHint iff not blocked", () => {
  const base = { stages: [] } as const;
  for (const kind of ["terminal", "interactive", "orchestration"] as const) {
    assert.deepEqual(derivePiMetadata({ ...base, kind, gated: "blocked" }), {
      exposure: "model-only",
    });
  }
  for (const kind of ["query", "action"] as const) {
    assert.deepEqual(derivePiMetadata({ ...base, kind, gated: "blocked" }), { exposure: "direct" });
    assert.deepEqual(derivePiMetadata({ ...base, kind, gated: "blocked", declared: "deferred" }), {
      exposure: "deferred",
    });
  }
  assert.deepEqual(derivePiMetadata({ ...base, kind: "action", gated: "allowed" }), {
    exposure: "direct",
    annotations: { readOnlyHint: true },
  });
  assert.deepEqual(
    derivePiMetadata({ ...base, kind: "orchestration", gated: { carveOut: "one file" } }),
    { exposure: "model-only", annotations: { readOnlyHint: true } },
  );
});

test("validateToolPolicy: refuses unknown stages, deferred model-only kinds, policy-owned fields and divergent re-registration", () => {
  const ok: ToolPolicy = { stages: ["plan"], gated: "allowed", kind: "query" };
  validateToolPolicy("vp_ok", { name: "vp_ok" }, ok, REGISTRY_IDS);
  assert.throws(
    () => validateToolPolicy("vp_bad", {}, { ...ok, stages: ["nope"] }, REGISTRY_IDS),
    /perk tool policy: vp_bad — unknown stage id "nope"/,
  );
  for (const kind of ["terminal", "interactive", "orchestration"] as const) {
    assert.throws(
      () => validateToolPolicy("vp_def", {}, { ...ok, kind, declared: "deferred" }, REGISTRY_IDS),
      /perk tool policy: vp_def — declared: "deferred" requires kind query or action/,
    );
  }
  for (const field of ["exposure", "annotations", "defaultActive", "prepareLoadout"]) {
    assert.throws(
      () => validateToolPolicy("vp_field", { [field]: undefined }, ok, REGISTRY_IDS),
      new RegExp(`must not set \`${field}\``),
    );
  }
  assert.throws(
    () => validateToolPolicy("vp_carve", {}, { ...ok, gated: { carveOut: " " } }, REGISTRY_IDS),
    /a carve-out must name its bounded write/,
  );
  recordPerkTool("vp_dup", ok);
  validateToolPolicy(
    "vp_dup",
    {},
    { ...ok, modeOverStage: false, declared: "always" },
    REGISTRY_IDS,
  );
  assert.throws(
    () => validateToolPolicy("vp_dup", {}, { ...ok, kind: "action" }, REGISTRY_IDS),
    /re-registered with a divergent policy/,
  );
  assert.throws(() => recordPerkTool("vp_dup", { ...ok, gated: "blocked" }), /divergent policy/);
  recordPerkTool("vp_dup", { ...ok });
  assert.equal(perkToolNames().filter((n) => n === "vp_dup").length, 1);
});

// The truth-table fakes (recorded once for the rest of the file).
recordPerkTool("tt_blocked", { stages: ["implement"], gated: "blocked", kind: "action" });
recordPerkTool("tt_allowed", { stages: ["plan"], gated: "allowed", kind: "query" });
recordPerkTool("tt_carve", {
  stages: ["plan", "objective-refine"],
  gated: { carveOut: "the carve artifact" },
  kind: "action",
});
recordPerkTool("tt_over", {
  stages: ["plan"],
  gated: "allowed",
  modeOverStage: true,
  kind: "action",
});
// A legal-but-unused combination: gate-blocked yet mode-over-stage.
recordPerkTool("tt_over_blocked", {
  stages: ["plan"],
  gated: "blocked",
  modeOverStage: true,
  kind: "action",
});
recordPerkTool("tt_deferred", {
  stages: ["plan"],
  gated: "allowed",
  kind: "query",
  declared: "deferred",
});
recordPerkTool("tt_unscoped", { stages: [], gated: "blocked", kind: "action" });

test("the formula: stage membership × mode posture, the mode-over-stage term, unscoped and unknown stages", () => {
  const rows: [string, string | null, "read-only" | "read-write", boolean][] = [
    // stage member, read-write → eligible whatever the posture
    ["tt_blocked", "implement", "read-write", true],
    ["tt_allowed", "plan", "read-write", true],
    // stage member, read-only → only when not blocked
    ["tt_blocked", "implement", "read-only", false],
    ["tt_allowed", "plan", "read-only", true],
    ["tt_carve", "objective-refine", "read-only", true],
    // stage non-member → never, save the mode-over-stage term under the gate
    ["tt_blocked", "plan", "read-write", false],
    ["tt_allowed", "implement", "read-only", false],
    ["tt_over", "implement", "read-only", true],
    ["tt_over", "implement", "read-write", false],
    // unscoped → every tool the mode allows
    ["tt_blocked", null, "read-write", true],
    ["tt_blocked", null, "read-only", false],
    ["tt_allowed", null, "read-only", true],
    ["tt_unscoped", null, "read-write", true],
    ["tt_unscoped", "plan", "read-write", false],
    // the mode-over-stage term scopes known stages only: unscoped is the mode rule alone
    ["tt_over_blocked", "implement", "read-only", true],
    ["tt_over_blocked", null, "read-only", false],
    ["tt_over_blocked", "no-such-stage", "read-only", false],
    ["tt_over_blocked", null, "read-write", true],
    ["tt_over", null, "read-only", true],
    // an unknown stage id (prototype keys included) is unscoped
    ["tt_blocked", "no-such-stage", "read-write", true],
    ["tt_allowed", "constructor", "read-only", true],
    // builtins: never stage-scoped; edit/write blocked under the gate, bash by verdict
    ["edit", "implement", "read-write", true],
    ["edit", "implement", "read-only", false],
    ["write", null, "read-only", false],
    ["bash", "plan", "read-only", true],
    ["read", "objective-refine", "read-only", true],
    // un-enumerated foreign names: read-write pass-through, blocked under the gate
    ["some_foreign_tool", "plan", "read-write", true],
    ["some_foreign_tool", null, "read-only", false],
    // deferred tools are eligible (the backstop must not block a host-activated one)
    ["tt_deferred", "plan", "read-only", true],
  ];
  for (const [name, stage, mode, expected] of rows) {
    assert.equal(isEligible(name, stage, mode), expected, `${name} @ ${stage} ${mode}`);
  }
  assert.equal(normalizeStage("constructor"), null);
  assert.equal(normalizeStage(undefined), null);
  assert.equal(normalizeStage("plan"), "plan");
});

test("deferred tools are never in an activation view; the diet is undefined when unscoped", () => {
  assert.ok(!gatedToolsFor("plan").includes("tt_deferred"));
  assert.ok(!(stageToolsFor("plan") ?? []).includes("tt_deferred"));
  assert.ok(gatedToolsFor("plan").includes("tt_over"));
  assert.equal(stageToolsFor(null), undefined);
  assert.equal(stageToolsFor("no-such-stage"), undefined);
  assert.equal(stageToolsFor("__proto__"), undefined);
  assert.deepEqual(gatedToolsFor("no-such-stage"), gatedToolsFor(null));
});

test("gatedToolsFor: canonical order — builtins, foreign rows in table order, perk tools in catalog order", () => {
  const view = gatedToolsFor("plan");
  assert.deepEqual(view.slice(0, 5), ["read", "grep", "find", "ls", "bash"]);
  const foreignOrder = FOREIGN_TOOL_POLICY.flatMap((r) => r.names).filter((n) => view.includes(n));
  const perkOrder = perkToolNames().filter((n) => view.includes(n));
  assert.deepEqual(view, ["read", "grep", "find", "ls", "bash", ...foreignOrder, ...perkOrder]);
});

test("foreign rows: exactly the borrowed census plus the child-side tools, each name once", () => {
  const names = FOREIGN_TOOL_POLICY.flatMap((r) => r.names);
  assert.equal(new Set(names).size, names.length, "a foreign name governed twice");
  assert.deepEqual(
    [...names].sort(),
    [...new Set([...BORROWED_TOOLS, ...SUBAGENT_CHILD_TOOLS])].sort(),
  );
  for (const row of FOREIGN_TOOL_POLICY) {
    for (const id of row.stages) assert.ok(REGISTRY_IDS.includes(id), `row stage ${id}`);
  }
  // The diet universe is the borrowed census + the catalog — child-side tools pass through.
  for (const name of SUBAGENT_CHILD_TOOLS) assert.ok(!dietUniverse().includes(name));
  for (const name of BORROWED_TOOLS) assert.ok(dietUniverse().includes(name));
  // Spot postures.
  for (const name of [...LINEAR_MUTATING_TOOLS, ...PLANNOTATOR_PHASE_TOOLS]) {
    for (const stage of REGISTRY_IDS) assert.equal(isEligible(name, stage, "read-write"), false);
    assert.equal(isEligible(name, null, "read-write"), true);
    assert.equal(isEligible(name, null, "read-only"), false);
  }
  for (const name of SUBAGENT_CHILD_TOOLS) {
    assert.equal(isEligible(name, "objective-refine", "read-only"), false);
    assert.equal(isEligible(name, "plan", "read-only"), true);
  }
  for (const name of SUBAGENT_TOOLS) {
    assert.equal(isEligible(name, "stack-review", "read-only"), true);
    assert.equal(isEligible(name, "plan", "read-only"), false);
    assert.equal(isEligible(name, "plan", "read-write"), false);
  }
  assert.equal(isEligible("todo", "implement", "read-write"), true);
  assert.equal(isEligible("todo", "implement", "read-only"), false);
  assert.equal(isEligible("ask_user_question", "objective-refine", "read-only"), true);
  assert.deepEqual(Object.keys(BUILTIN_TOOL_POLICY), [
    "read",
    "grep",
    "find",
    "ls",
    "bash",
    "edit",
    "write",
  ]);
});

test("carveOutWritersFor: the eligible carve-out writers in catalog order, with their prose", () => {
  assert.deepEqual(carveOutWritersFor("objective-refine"), [
    { name: "tt_carve", carveOut: "the carve artifact" },
  ]);
  assert.deepEqual(carveOutWritersFor("implement"), []);
  assert.deepEqual(
    carveOutWritersFor(null).map((w) => w.name),
    perkToolNames().filter((n) => typeof perkToolPolicy(n)?.gated === "object"),
  );
});

test("catalog: records are frozen copies; lookups are name-exact", () => {
  const policy = perkToolPolicy("tt_carve");
  assert.ok(policy !== undefined && Object.isFrozen(policy) && Object.isFrozen(policy.stages));
  assert.equal(isPerkTool("tt_carve"), true);
  assert.equal(isPerkTool("toString"), false);
  assert.equal(perkToolPolicy("constructor"), undefined);
});

test("toolMatrix: owner rows, registry-ordered stages, sorted eligibility, and the unscoped key", () => {
  const m = toolMatrix();
  assert.deepEqual(m.stages, REGISTRY_IDS);
  assert.deepEqual(m.tools.tt_carve, {
    owner: "perk",
    kind: "action",
    stages: ["objective-refine", "plan"].sort(
      (a, b) => REGISTRY_IDS.indexOf(a) - REGISTRY_IDS.indexOf(b),
    ),
    gated: "carve-out",
    mode_over_stage: false,
    declared: "always",
    exposure: "direct",
  });
  assert.deepEqual(m.tools.web_search, { owner: "foreign", stages: "all", gated: "allowed" });
  assert.deepEqual(m.tools.structured_output, {
    owner: "foreign",
    stages: REGISTRY_IDS.filter((id) => id !== "objective-refine"),
    gated: "allowed",
  });
  assert.deepEqual(m.tools.bash, { owner: "builtin", gated: "verdict" });
  for (const stage of REGISTRY_IDS) {
    const row = m.eligible[stage];
    assert.ok(row !== undefined);
    assert.deepEqual(row["read-only"], [...gatedToolsFor(stage)].sort());
    assert.ok(
      row["read-write"].includes("edit") && row["read-write"].includes("structured_output"),
    );
  }
  assert.deepEqual(m.eligible.unscoped?.["read-write"], Object.keys(m.tools).sort());
});
