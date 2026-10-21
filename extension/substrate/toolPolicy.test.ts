// The tool catalog's pure policy: stage families, derived Pi metadata, registration-time
// validation, the eligibility formula, the provenance-posture table, own-names-only
// reconciliation, the loadout host's hidden set and the derived views. Fakes are recorded straight
// into this process's catalog (node --test isolates each file in its own process), so nothing
// here leaks into the census/fixture suites.

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadRegistry } from "./registry.ts";
import {
  AUTHORING_STAGES,
  BUILTIN_TOOL_POLICY,
  carveOutWritersFor,
  deriveOutputSchema,
  derivePiMetadata,
  discoveryFamily,
  GIST_STAGES,
  type GateLanding,
  gatedToolsFor,
  gateSuspends,
  hiddenDeclarationsFor,
  isDiscoveryHost,
  isEligible,
  isPerkTool,
  LOADOUT_HOST_NAME,
  type Mode,
  nestedPostureFor,
  normalizePackageSpec,
  normalizeStage,
  OBJECTIVE_STAGES,
  PACKAGE_TOOL_POLICY,
  PLAN_FAMILY_STAGES,
  PLANNING_READ_STAGES,
  POSTURE_ROWS,
  type Provenance,
  perkToolNames,
  perkToolPolicy,
  perkToolsFor,
  postureFor,
  READ_ONLY_STAGES,
  REGISTRY_STAGE_IDS,
  reconcileTarget,
  recordPerkTool,
  SYNTHETIC_PATH_TOOL_POLICY,
  sameNames,
  stageToolsFor,
  strandedWriters,
  suspensionStep,
  type ToolPolicy,
  toolMatrix,
  validateToolPolicy,
  WORKTREE_STAGES,
} from "./toolPolicy.ts";

const REGISTRY_IDS = loadRegistry().stages.map((s) => s.id);

/** Provenance fixtures, shaped exactly as Pi reports them. */
const pkg = (source: string): Provenance => ({
  path: `/agent/npm/node_modules/x/index.js`,
  source,
});
const BUILTIN = (name: string): Provenance => ({ path: `builtin:${name}`, source: "builtin" });
/** A tool Pi's MCP builtin registers (`mcp__<server>__<tool>`). */
const MCP_TOOL = "mcp__docs__search";
const ENGINE: Provenance = { path: "<inline:pi-subagents:prompt-runtime>", source: "inline" };
const OTHER_INLINE: Provenance = { path: "<inline:other>", source: "inline" };
const SUBAGENTS = pkg("npm:pi-subagents@0.73.1");

test("stage families: every member is a registry id; the worktree family is the five plan-ref consumers", () => {
  assert.deepEqual(REGISTRY_STAGE_IDS, REGISTRY_IDS);
  for (const family of [
    WORKTREE_STAGES,
    PLAN_FAMILY_STAGES,
    OBJECTIVE_STAGES,
    AUTHORING_STAGES,
    GIST_STAGES,
    PLANNING_READ_STAGES,
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
  // The read-only planning/refinement stages: registry read-only landings, disjoint from the
  // worktree family, never the objective-authoring stage (no objective exists yet).
  assert.deepEqual(PLANNING_READ_STAGES, ["plan", "objective-plan", "objective-refine"]);
  const modes = new Map(loadRegistry().stages.map((s) => [s.id, s.mode]));
  for (const id of PLANNING_READ_STAGES) assert.equal(modes.get(id), "read-only", id);
  for (const id of PLANNING_READ_STAGES) assert.ok(!WORKTREE_STAGES.includes(id), id);
  assert.ok(!PLANNING_READ_STAGES.includes("objective-author"));
  // The lift family: every registry read-only stage, registry order — the planning family inside.
  assert.deepEqual(
    READ_ONLY_STAGES,
    loadRegistry()
      .stages.filter((s) => s.mode === "read-only")
      .map((s) => s.id),
  );
  assert.deepEqual(READ_ONLY_STAGES, [
    "gist-author",
    "objective-author",
    "objective-plan",
    "plan",
    "audit",
    "objective-refine",
  ]);
  for (const id of PLANNING_READ_STAGES) assert.ok(READ_ONLY_STAGES.includes(id), id);
  for (const id of READ_ONLY_STAGES) assert.ok(!WORKTREE_STAGES.includes(id), id);
});

test("derivePiMetadata: terminal/interactive/orchestration/host are model-only; readOnlyHint iff not blocked", () => {
  const base = { stages: [] } as const;
  for (const kind of ["terminal", "interactive", "orchestration", "host"] as const) {
    assert.deepEqual(derivePiMetadata({ ...base, kind, gated: "blocked" }), {
      exposure: "model-only",
    });
  }
  assert.deepEqual(derivePiMetadata({ ...base, kind: "host", gated: "allowed" }), {
    exposure: "model-only",
    annotations: { readOnlyHint: true },
  });
  for (const kind of ["terminal", "interactive", "orchestration", "host"] as const) {
    assert.deepEqual(derivePiMetadata({ ...base, kind, gated: "blocked" }, { cohort: true }), {
      exposure: "model-only",
    });
  }
  for (const kind of ["query", "action"] as const) {
    assert.deepEqual(derivePiMetadata({ ...base, kind, gated: "blocked" }), { exposure: "direct" });
    assert.deepEqual(derivePiMetadata({ ...base, kind, gated: "blocked" }, { cohort: true }), {
      exposure: "direct",
    });
    // A family member registers direct; only the cohort re-registration derives `deferred`.
    const member = { ...base, kind, gated: "blocked", declared: "deferred" } as const;
    assert.deepEqual(derivePiMetadata(member), { exposure: "direct" });
    assert.deepEqual(derivePiMetadata(member, { cohort: false }), { exposure: "direct" });
    assert.deepEqual(derivePiMetadata(member, { cohort: true }), { exposure: "deferred" });
    assert.deepEqual(derivePiMetadata({ ...member, declared: "always" }, { cohort: true }), {
      exposure: "direct",
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
  // A bounded writer (an action carve-out) is model-only: declared, never script-callable — in
  // and out of the cohort alike.
  for (const options of [{}, { cohort: true }, { cohort: false }]) {
    assert.deepEqual(
      derivePiMetadata({ ...base, kind: "action", gated: { carveOut: "one file" } }, options),
      { exposure: "model-only", annotations: { readOnlyHint: true } },
      JSON.stringify(options),
    );
  }
});

test("derivePiMetadata: a query with declared success details gets the ok-discriminated outputSchema envelope", () => {
  const result = {
    properties: { objective: { type: "string" }, n: { type: "number" } },
    required: ["objective"],
  };
  const envelope = {
    anyOf: [
      {
        type: "object",
        properties: { ok: { const: true }, objective: { type: "string" }, n: { type: "number" } },
        required: ["ok", "objective"],
        additionalProperties: false,
      },
      {
        type: "object",
        properties: {
          ok: { const: false },
          error: { type: "string" },
          error_type: { type: "string" },
        },
        required: ["ok", "error", "error_type"],
        additionalProperties: true,
      },
    ],
  };
  assert.deepEqual(derivePiMetadata({ stages: [], gated: "blocked", kind: "query", result }), {
    exposure: "direct",
    outputSchema: envelope,
  });
  assert.deepEqual(deriveOutputSchema(result), envelope);
  // A gate-allowed deferred query: readOnlyHint derived beside the schema; the cohort
  // re-registration alone flips the exposure.
  const allowedQuery = {
    stages: PLANNING_READ_STAGES,
    gated: "allowed",
    kind: "query",
    declared: "deferred",
    result,
  } as const;
  assert.deepEqual(derivePiMetadata(allowedQuery), {
    exposure: "direct",
    annotations: { readOnlyHint: true },
    outputSchema: envelope,
  });
  assert.deepEqual(derivePiMetadata(allowedQuery, { cohort: true }), {
    exposure: "deferred",
    annotations: { readOnlyHint: true },
    outputSchema: envelope,
  });
  // `required` defaults to just the discriminant.
  assert.deepEqual(
    (deriveOutputSchema({ properties: {} }) as { anyOf: { required: string[] }[] }).anyOf[0]
      ?.required,
    ["ok"],
  );
  // Every other kind never gets an outputSchema, whatever the policy carries.
  for (const kind of ["terminal", "interactive", "orchestration", "host", "action"] as const) {
    assert.equal(
      "outputSchema" in derivePiMetadata({ stages: [], gated: "allowed", kind, result }),
      false,
      kind,
    );
  }
});

test("validateToolPolicy: the result descriptor — required on query, refused elsewhere, no ok, required ⊆ properties, divergence", () => {
  const query: ToolPolicy = {
    stages: ["plan"],
    gated: "allowed",
    kind: "query",
    result: { properties: { a: { type: "string" } }, required: ["a"] },
  };
  validateToolPolicy("vr_ok", {}, query, REGISTRY_IDS);
  assert.throws(
    () =>
      validateToolPolicy(
        "vr_missing",
        {},
        { stages: [], gated: "allowed", kind: "query" },
        REGISTRY_IDS,
      ),
    /perk tool policy: vr_missing — a query tool must declare its success details \(result\)/,
  );
  for (const kind of ["action", "terminal", "interactive", "orchestration"] as const) {
    assert.throws(
      () => validateToolPolicy("vr_kind", {}, { ...query, kind }, REGISTRY_IDS),
      new RegExp(
        `perk tool policy: vr_kind — \`result\` is declared by query tools only — a ${kind} tool is never a script API`,
      ),
    );
  }
  assert.throws(
    () =>
      validateToolPolicy(
        "vr_ok_prop",
        {},
        { ...query, result: { properties: { ok: { type: "boolean" } } } },
        REGISTRY_IDS,
      ),
    /must not declare `ok`/,
  );
  assert.throws(
    () =>
      validateToolPolicy(
        "vr_required",
        {},
        { ...query, result: { properties: {}, required: ["ghost"] } },
        REGISTRY_IDS,
      ),
    /`result.required` names "ghost"/,
  );
  assert.throws(
    () => validateToolPolicy("vr_field", { outputSchema: {} }, query, REGISTRY_IDS),
    /must not set `outputSchema`/,
  );
  // An identical result re-records as a no-op; a changed one diverges.
  recordPerkTool("vr_dup", query);
  recordPerkTool("vr_dup", {
    ...query,
    result: { properties: { a: { type: "string" } }, required: ["a"] },
  });
  assert.throws(
    () =>
      validateToolPolicy(
        "vr_dup",
        {},
        { ...query, result: { properties: { a: { type: "number" } }, required: ["a"] } },
        REGISTRY_IDS,
      ),
    /re-registered with a divergent policy/,
  );
  assert.throws(
    () => recordPerkTool("vr_dup", { ...query, result: { properties: {} } }),
    /divergent policy/,
  );
  assert.equal(perkToolNames().filter((n) => n === "vr_dup").length, 1);
});

test("validateToolPolicy: refuses the host kind, unknown stages, deferred model-only kinds, policy-owned fields and divergent re-registration", () => {
  const ok: ToolPolicy = {
    stages: ["plan"],
    gated: "allowed",
    kind: "query",
    result: { properties: {} },
  };
  validateToolPolicy("vp_ok", { name: "vp_ok" }, ok, REGISTRY_IDS);
  assert.throws(
    () => validateToolPolicy("vp_host", {}, { ...ok, kind: "host" }, REGISTRY_IDS),
    /perk tool policy: vp_host — the loadout host registers through registerLoadoutHost/,
  );
  assert.throws(
    () => validateToolPolicy("vp_bad", {}, { ...ok, stages: ["nope"] }, REGISTRY_IDS),
    /perk tool policy: vp_bad — unknown stage id "nope"/,
  );
  for (const kind of ["terminal", "interactive", "orchestration"] as const) {
    assert.throws(
      () =>
        validateToolPolicy(
          "vp_def",
          {},
          { stages: ["plan"], gated: "allowed", kind, declared: "deferred" },
          REGISTRY_IDS,
        ),
      /perk tool policy: vp_def — declared: "deferred" requires kind query or action/,
    );
  }
  for (const field of [
    "exposure",
    "annotations",
    "defaultActive",
    "prepareLoadout",
    "outputSchema",
  ]) {
    assert.throws(
      () => validateToolPolicy("vp_field", { [field]: undefined }, ok, REGISTRY_IDS),
      new RegExp(`must not set \`${field}\``),
    );
  }
  assert.throws(
    () =>
      validateToolPolicy(
        "vp_carve",
        {},
        { ...ok, kind: "action", result: undefined, gated: { carveOut: " " } },
        REGISTRY_IDS,
      ),
    /a carve-out must name its bounded write/,
  );
  // A query is a pure read: a carve-out on one is refused; an action carve-out registers.
  assert.throws(
    () =>
      validateToolPolicy(
        "vp_query_carve",
        {},
        { ...ok, gated: { carveOut: "one file" } },
        REGISTRY_IDS,
      ),
    /perk tool policy: vp_query_carve — a query never writes — gated must be allowed or blocked/,
  );
  validateToolPolicy(
    "vp_action_carve",
    {},
    { ...ok, kind: "action", result: undefined, gated: { carveOut: "one file" } },
    REGISTRY_IDS,
  );
  // A deferred carve-out writer would be named by the read-only context while undeclared.
  assert.throws(
    () =>
      validateToolPolicy(
        "vp_def_carve",
        {},
        {
          ...ok,
          kind: "action",
          result: undefined,
          gated: { carveOut: "one file" },
          declared: "deferred",
        },
        REGISTRY_IDS,
      ),
    /perk tool policy: vp_def_carve — declared: "deferred" requires gated allowed or blocked — the read-only context names carve-out writers, and an undeclared writer would dead-end/,
  );
  for (const gated of ["allowed", "blocked"] as const) {
    validateToolPolicy("vp_def_ok", {}, { ...ok, gated, declared: "deferred" }, REGISTRY_IDS);
  }
  recordPerkTool("vp_dup", ok);
  validateToolPolicy(
    "vp_dup",
    {},
    { ...ok, modeOverStage: false, declared: "always" },
    REGISTRY_IDS,
  );
  assert.throws(
    () =>
      validateToolPolicy(
        "vp_dup",
        {},
        { stages: ["plan"], gated: "allowed", kind: "action" },
        REGISTRY_IDS,
      ),
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
recordPerkTool("tt_allowed_wide", {
  stages: [...WORKTREE_STAGES, ...PLANNING_READ_STAGES],
  gated: "allowed",
  kind: "query",
  result: { properties: {} },
});
// A model-only kind that is gate-allowed (an orchestration launcher's shape).
recordPerkTool("tt_model_only", { stages: ["plan"], gated: "allowed", kind: "orchestration" });

test("nestedPostureFor: only a gate-allowed perk query and the core builtin reads run nested; foreign keeps its gate posture; unknown is blocked", () => {
  const perk: [string, "allowed" | "blocked"][] = [
    ["tt_allowed", "allowed"],
    ["tt_allowed_wide", "allowed"],
    ["tt_deferred", "allowed"],
    // a carve-out writer, an action (gate-allowed or not) and a model-only kind
    ["tt_carve", "blocked"],
    ["tt_over", "blocked"],
    ["tt_blocked", "blocked"],
    ["tt_model_only", "blocked"],
  ];
  for (const [name, expected] of perk) {
    assert.equal(nestedPostureFor(postureFor(name, undefined)), expected, name);
    // The catalog wins over any provenance, nested too.
    assert.equal(nestedPostureFor(postureFor(name, BUILTIN(name))), expected, `${name} builtin`);
  }
  // A gate-blocked query is no nested grant either.
  assert.equal(
    nestedPostureFor({
      owner: "perk",
      policy: { stages: ["plan"], gated: "blocked", kind: "query" },
    }),
    "blocked",
  );
  const builtins: Record<string, "allowed" | "blocked" | "verdict"> = {
    read: "allowed",
    grep: "allowed",
    find: "allowed",
    ls: "allowed",
    bash: "verdict",
    edit: "blocked",
    write: "blocked",
    tool_search: "blocked",
    codemode: "blocked",
  };
  assert.deepEqual(Object.keys(builtins), Object.keys(BUILTIN_TOOL_POLICY));
  for (const [name, expected] of Object.entries(builtins)) {
    assert.equal(nestedPostureFor(postureFor(name, BUILTIN(name))), expected, name);
  }
  // A non-builtin namesake classifies by its package, never by the builtin row.
  assert.equal(nestedPostureFor(postureFor("tool_search", pkg("npm:pi-web-access"))), "allowed");
  assert.equal(nestedPostureFor(postureFor("tool_search", OTHER_INLINE)), "blocked");
  for (const [posture, row] of Object.entries(POSTURE_ROWS)) {
    assert.equal(
      nestedPostureFor({
        owner: "foreign",
        posture: posture as keyof typeof POSTURE_ROWS,
        key: "k",
      }),
      row.gated,
      posture,
    );
  }
  assert.equal(nestedPostureFor(postureFor("subagent", SUBAGENTS)), "allowed");
  assert.equal(nestedPostureFor(postureFor("structured_output", ENGINE)), "allowed");
  assert.equal(nestedPostureFor(postureFor("p", pkg("npm:@plannotator/pi-extension"))), "blocked");
  assert.equal(nestedPostureFor({ owner: "unknown" }), "blocked");
  assert.equal(nestedPostureFor(postureFor(MCP_TOOL, BUILTIN("mcp"))), "blocked");
  assert.equal(nestedPostureFor(postureFor("x", undefined)), "blocked");
});

test("the formula: stage membership × mode posture, the mode-over-stage term, unscoped and unknown stages", () => {
  const rows: [string, Provenance | undefined, string | null, Mode, boolean][] = [
    // stage member, read-write → eligible whatever the posture
    ["tt_blocked", undefined, "implement", "read-write", true],
    ["tt_allowed", undefined, "plan", "read-write", true],
    // stage member, read-only → only when not blocked
    ["tt_blocked", undefined, "implement", "read-only", false],
    ["tt_allowed", undefined, "plan", "read-only", true],
    ["tt_carve", undefined, "objective-refine", "read-only", true],
    // stage non-member → never, save the mode-over-stage term under the gate
    ["tt_blocked", undefined, "plan", "read-write", false],
    ["tt_allowed", undefined, "implement", "read-only", false],
    ["tt_over", undefined, "implement", "read-only", true],
    ["tt_over", undefined, "implement", "read-write", false],
    // unscoped → every tool the mode allows
    ["tt_blocked", undefined, null, "read-write", true],
    ["tt_blocked", undefined, null, "read-only", false],
    ["tt_allowed", undefined, null, "read-only", true],
    ["tt_unscoped", undefined, null, "read-write", true],
    ["tt_unscoped", undefined, "plan", "read-write", false],
    // the mode-over-stage term scopes known stages only: unscoped is the mode rule alone
    ["tt_over_blocked", undefined, "implement", "read-only", true],
    ["tt_over_blocked", undefined, null, "read-only", false],
    ["tt_over_blocked", undefined, "no-such-stage", "read-only", false],
    ["tt_over_blocked", undefined, null, "read-write", true],
    ["tt_over", undefined, null, "read-only", true],
    // an unknown stage id (prototype keys included) is unscoped
    ["tt_blocked", undefined, "no-such-stage", "read-write", true],
    ["tt_allowed", undefined, "constructor", "read-only", true],
    // a perk name is classified by the catalog whatever its provenance
    ["tt_blocked", OTHER_INLINE, "implement", "read-write", true],
    ["tt_allowed", BUILTIN("tt_allowed"), "implement", "read-only", false],
    // builtins: never stage-scoped; edit/write/codemode blocked under the gate, bash by verdict
    ["edit", BUILTIN("edit"), "implement", "read-write", true],
    ["edit", BUILTIN("edit"), "implement", "read-only", false],
    ["write", BUILTIN("write"), null, "read-only", false],
    ["bash", BUILTIN("bash"), "plan", "read-only", true],
    ["read", BUILTIN("read"), "objective-refine", "read-only", true],
    ["tool_search", BUILTIN("tool_search"), "plan", "read-only", true],
    ["codemode", BUILTIN("codemode"), "plan", "read-only", false],
    ["codemode", BUILTIN("codemode"), "plan", "read-write", true],
    // unknown provenance: read-write pass-through (every diet), blocked under the gate
    ["some_foreign_tool", undefined, "plan", "read-write", true],
    ["some_foreign_tool", undefined, null, "read-only", false],
    ["some_foreign_tool", OTHER_INLINE, "implement", "read-only", false],
    // deferred tools are eligible (the backstop must not block a host-activated one)
    ["tt_deferred", undefined, "plan", "read-only", true],
    // a gate-allowed query staged in the worktree family + the planning/refinement stages
    ["tt_allowed_wide", undefined, "plan", "read-only", true],
    ["tt_allowed_wide", undefined, "objective-plan", "read-only", true],
    ["tt_allowed_wide", undefined, "objective-refine", "read-only", true],
    ["tt_allowed_wide", undefined, "implement", "read-only", true],
    ["tt_allowed_wide", undefined, "objective-author", "read-only", false],
    ["tt_allowed_wide", undefined, "save", "read-only", false],
    ["tt_allowed_wide", undefined, "stack-review", "read-only", false],
    ["tt_allowed_wide", undefined, "objective-author", "read-write", false],
  ];
  for (const [name, provenance, stage, mode, expected] of rows) {
    assert.equal(
      isEligible(name, provenance, stage, mode),
      expected,
      `${name} (${provenance?.path ?? "no provenance"}) @ ${stage} ${mode}`,
    );
  }
  assert.equal(normalizeStage("constructor"), null);
  assert.equal(normalizeStage(undefined), null);
  assert.equal(normalizeStage("plan"), "plan");
  // Pi's MCP builtin tool (`builtin:mcp`, a name outside the builtin rows): blocked under the
  // gate at every stage and unscoped, passed through read-write.
  for (const stage of [...REGISTRY_STAGE_IDS, null]) {
    assert.equal(isEligible(MCP_TOOL, BUILTIN("mcp"), stage, "read-only"), false, `${stage}`);
    assert.equal(isEligible(MCP_TOOL, BUILTIN("mcp"), stage, "read-write"), true, `${stage}`);
  }
});

test("normalizePackageSpec: npm specs lose their version or range, scoped-aware; other strings are returned unchanged", () => {
  const cases: [string, string][] = [
    ["npm:pi-subagents@0.73.1", "npm:pi-subagents"],
    ["npm:pi-subagents", "npm:pi-subagents"],
    ["npm:name@^1", "npm:name"],
    ["npm:@scope/name@1.2.3", "npm:@scope/name"],
    ["npm:@scope/name", "npm:@scope/name"],
    ["npm:@scope/name@>=1 <2", "npm:@scope/name"],
    ["builtin", "builtin"],
    ["inline", "inline"],
    ["git:github.com/x/y@v1", "git:github.com/x/y@v1"],
    ["..", ".."],
  ];
  for (const [input, expected] of cases) assert.equal(normalizePackageSpec(input), expected, input);
});

test("postureFor: catalog → exact synthetic path → builtin → package row (with its exception) → unknown", () => {
  // The catalog wins over any provenance.
  assert.equal(postureFor("tt_allowed", ENGINE).owner, "perk");
  assert.equal(postureFor("tt_allowed", undefined).owner, "perk");
  // The exact synthetic path; another inline path is unknown (never "all inline").
  assert.deepEqual(postureFor("structured_output", ENGINE), {
    owner: "foreign",
    posture: "child-engine",
    key: "<inline:pi-subagents:prompt-runtime>",
  });
  assert.deepEqual(postureFor("structured_output", OTHER_INLINE), { owner: "unknown" });
  // A builtin-sourced builtin name; an unknown name from the builtin source is unknown (an MCP
  // bridge registering through a builtin path), and a builtin NAME from a package is the package's.
  assert.deepEqual(postureFor("codemode", BUILTIN("codemode")), {
    owner: "builtin",
    gated: "blocked",
    registrar: "extension",
  });
  assert.deepEqual(postureFor("read", BUILTIN("read")), {
    owner: "builtin",
    gated: "allowed",
    registrar: "core",
  });
  assert.deepEqual(postureFor("mcp_query", BUILTIN("mcp")), { owner: "unknown" });
  // Pi's own MCP builtin: a server tool and a resource tool are builtin-sourced names outside the
  // builtin rows, and `builtin:mcp` is no synthetic-path row.
  assert.deepEqual(postureFor(MCP_TOOL, BUILTIN("mcp")), { owner: "unknown" });
  assert.deepEqual(postureFor("list_mcp_resources", BUILTIN("mcp")), { owner: "unknown" });
  assert.deepEqual(postureFor("read", SUBAGENTS), {
    owner: "foreign",
    posture: "delegation",
    key: "npm:pi-subagents",
  });
  // The package row, version-blind; the Linear row's one in-package exception.
  assert.deepEqual(postureFor("subagent", pkg("npm:pi-subagents@9.9.9")), {
    owner: "foreign",
    posture: "delegation",
    key: "npm:pi-subagents",
  });
  assert.equal(postureFor("linear_get_issue", pkg("npm:pi-mono-linear")).owner, "foreign");
  assert.deepEqual(postureFor("linear_get_issue", pkg("npm:pi-mono-linear@1.0.0")), {
    owner: "foreign",
    posture: "research",
    key: "npm:pi-mono-linear",
  });
  for (const name of PACKAGE_TOOL_POLICY["npm:pi-mono-linear"]?.except?.names ?? []) {
    assert.deepEqual(postureFor(name, pkg("npm:pi-mono-linear")), {
      owner: "foreign",
      posture: "never",
      key: "npm:pi-mono-linear",
    });
  }
  // Unrecognized or absent provenance.
  assert.deepEqual(postureFor("x", pkg("npm:some-mcp-bridge@1.0.0")), { owner: "unknown" });
  assert.deepEqual(postureFor("x", undefined), { owner: "unknown" });
  assert.deepEqual(postureFor("x", { path: "constructor", source: "constructor" }), {
    owner: "unknown",
  });
});

test("the posture table: rows, their packages, and per-posture eligibility", () => {
  const rows = Object.fromEntries(
    Object.entries(PACKAGE_TOOL_POLICY).map(([spec, row]) => [spec, row.posture]),
  );
  assert.deepEqual(rows, {
    "npm:pi-web-access": "research",
    "npm:@ollama/pi-web-search": "research",
    "npm:@juicesharp/rpiv-web-tools": "research",
    "npm:@plannotator/pi-extension": "never",
    "npm:@ff-labs/pi-fff": "research",
    "npm:@juicesharp/rpiv-ask-user-question": "universal",
    "npm:pi-subagents": "delegation",
    "npm:@juicesharp/rpiv-todo": "delegation",
    "npm:pi-mono-linear": "research",
  });
  for (const spec of Object.keys(PACKAGE_TOOL_POLICY))
    assert.equal(normalizePackageSpec(spec), spec, `${spec} is a normalized key`);
  assert.deepEqual(SYNTHETIC_PATH_TOOL_POLICY, {
    "<inline:pi-subagents:prompt-runtime>": "child-engine",
  });
  for (const row of Object.values(POSTURE_ROWS))
    for (const id of row.stages) assert.ok(REGISTRY_IDS.includes(id), `row stage ${id}`);

  const eligible = (provenance: Provenance, name: string, stage: string | null, mode: Mode) =>
    isEligible(name, provenance, stage, mode);
  const delegationHome = [...WORKTREE_STAGES, "stack-review"];
  for (const stage of REGISTRY_IDS) {
    for (const mode of ["read-only", "read-write"] as const) {
      const at = `${stage} ${mode}`;
      // research + universal: everywhere, under the gate too.
      assert.equal(eligible(pkg("npm:pi-web-access"), "web_search", stage, mode), true, at);
      assert.equal(
        eligible(pkg("npm:@juicesharp/rpiv-ask-user-question"), "ask_user_question", stage, mode),
        true,
        at,
      );
      // delegation: the worktree family + stack-review (gate-allowed there); todo rides it.
      assert.equal(eligible(SUBAGENTS, "subagent", stage, mode), delegationHome.includes(stage));
      assert.equal(
        eligible(pkg("npm:@juicesharp/rpiv-todo"), "todo", stage, mode),
        delegationHome.includes(stage),
        at,
      );
      // never: no stage; child-engine: every stage (stage-blind — refinement included).
      assert.equal(eligible(pkg("npm:@plannotator/pi-extension"), "p", stage, mode), false, at);
      assert.equal(eligible(pkg("npm:pi-mono-linear"), "linear_create_issue", stage, mode), false);
      assert.equal(eligible(ENGINE, "structured_output", stage, mode), true, at);
    }
  }
  // Unscoped: the mode rule alone — `never` passes read-write and is blocked under the gate.
  assert.equal(eligible(pkg("npm:@plannotator/pi-extension"), "p", null, "read-write"), true);
  assert.equal(eligible(pkg("npm:@plannotator/pi-extension"), "p", null, "read-only"), false);
  assert.equal(eligible(SUBAGENTS, "subagent", null, "read-only"), true);
  assert.deepEqual(Object.keys(BUILTIN_TOOL_POLICY), [
    "read",
    "grep",
    "find",
    "ls",
    "bash",
    "edit",
    "write",
    "tool_search",
    "codemode",
  ]);
});

test("a deferred tool rides every activation view outside the cohort and none inside it; the diet is undefined when unscoped", () => {
  assert.ok(gatedToolsFor("plan").includes("tt_deferred"));
  assert.ok((stageToolsFor("plan") ?? []).includes("tt_deferred"));
  for (const mode of ["read-only", "read-write"] as const) {
    assert.ok(perkToolsFor("plan", mode).includes("tt_deferred"), mode);
    assert.ok(perkToolsFor("plan", mode, false).includes("tt_deferred"), mode);
    assert.ok(!perkToolsFor("plan", mode, true).includes("tt_deferred"), mode);
    assert.deepEqual(
      perkToolsFor("plan", mode, true),
      perkToolsFor("plan", mode).filter((n) => n !== "tt_deferred"),
      `${mode}: the cohort view drops only the family`,
    );
  }
  assert.ok(gatedToolsFor("plan").includes("tt_over"));
  assert.equal(stageToolsFor(null), undefined);
  assert.equal(stageToolsFor("no-such-stage"), undefined);
  assert.equal(stageToolsFor("__proto__"), undefined);
  assert.deepEqual(gatedToolsFor("no-such-stage"), gatedToolsFor(null));
});

test("the activation views are perk-only, in catalog order", () => {
  for (const stage of [null, ...REGISTRY_IDS]) {
    for (const mode of ["read-only", "read-write"] as const) {
      const view = perkToolsFor(stage, mode);
      assert.deepEqual(
        view,
        perkToolNames().filter((n) => view.includes(n)),
      );
    }
  }
  assert.deepEqual(gatedToolsFor("plan"), perkToolsFor("plan", "read-only"));
  assert.deepEqual(stageToolsFor("plan"), perkToolsFor("plan", "read-write"));
  assert.ok(!gatedToolsFor(null).includes("read"));
});

test("reconcileTarget: null when nothing changes; foreign names keep their live order and membership; the deferred third term; unregistered perk names ignored", () => {
  const perkAll = perkToolsFor(null, "read-write");
  const registered = [...perkToolNames(), "read", "edit", "a", "b"];
  // A bare default registration: every always perk tool active → no install.
  assert.equal(
    reconcileTarget({ active: ["read", "edit", ...perkAll], registered }, null, "read-write"),
    null,
  );
  // Order-insensitive.
  assert.equal(
    reconcileTarget(
      { active: [...perkAll].reverse().concat("edit", "read"), registered },
      null,
      "read-write",
    ),
    null,
  );
  // Foreign invariance over arbitrary live sets, whatever the landing.
  for (const foreign of [[], ["b", "a"], ["edit", "zz_unregistered"], ["a"]]) {
    for (const [stage, mode] of [
      ["plan", "read-only"],
      ["implement", "read-write"],
      [null, "read-only"],
    ] as const) {
      const live = [...foreign, "tt_blocked"];
      // null = the live set already is the target.
      const target = reconcileTarget({ active: live, registered }, stage, mode) ?? live;
      assert.deepEqual(
        target.filter((n) => !isPerkTool(n)),
        foreign,
      );
      assert.deepEqual(
        target.filter(isPerkTool),
        perkToolsFor(stage, mode),
        `${stage} ${mode}: the eligible always-declared perk names, catalog order`,
      );
    }
  }
  // The deferred third term, for a name deferred in this session: kept only while live AND
  // eligible; never activated.
  const here = ["tt_deferred"];
  const planned = reconcileTarget(
    { active: ["tt_deferred"], registered },
    "plan",
    "read-write",
    here,
  );
  assert.ok(planned?.includes("tt_deferred"));
  const notLive = reconcileTarget({ active: [], registered }, "plan", "read-write", here);
  assert.ok(notLive !== null && !notLive.includes("tt_deferred"));
  const ineligible = reconcileTarget(
    { active: ["tt_deferred"], registered },
    "implement",
    "read-write",
    here,
  );
  assert.ok(ineligible !== null && !ineligible.includes("tt_deferred"));
  // A family member NOT deferred in this session (outside the cohort, or its re-registration
  // failed) is always-declared: installed whenever eligible, dropped where it is not.
  for (const deferred of [undefined, [], ["tt_allowed"]]) {
    const label = JSON.stringify(deferred ?? null);
    const outside = reconcileTarget({ active: [], registered }, "plan", "read-write", deferred);
    assert.ok(outside?.includes("tt_deferred"), label);
    const dropped = reconcileTarget(
      { active: ["tt_deferred"], registered },
      "implement",
      "read-write",
      deferred,
    );
    assert.ok(dropped !== null && !dropped.includes("tt_deferred"), label);
  }
  // A catalogued name the host never registered is never installed and never forces an install.
  const partial = ["read", "tt_allowed"];
  assert.equal(
    reconcileTarget({ active: partial, registered: partial }, "plan", "read-write"),
    null,
  );
  assert.deepEqual(
    reconcileTarget({ active: ["read"], registered: partial }, "plan", "read-only"),
    ["read", "tt_allowed"],
  );
});

test("hiddenDeclarationsFor: the host always; a bare landing hides nothing else; the gate and the diet hide by provenance", () => {
  const infos = new Map<string, Provenance>([
    ["read", BUILTIN("read")],
    ["edit", BUILTIN("edit")],
    ["write", BUILTIN("write")],
    ["codemode", BUILTIN("codemode")],
    ["tool_search", BUILTIN("tool_search")],
    ["subagent", SUBAGENTS],
    ["web_search", pkg("npm:pi-web-access")],
    ["plannotator_submit_plan", pkg("npm:@plannotator/pi-extension")],
    ["structured_output", ENGINE],
    ["bridge_tool", pkg("npm:some-mcp-bridge")],
    [LOADOUT_HOST_NAME, OTHER_INLINE],
  ]);
  const declared = [...infos.keys(), "tt_allowed", "tt_blocked"];
  assert.deepEqual(hiddenDeclarationsFor(declared, infos, null, "read-write"), [LOADOUT_HOST_NAME]);
  assert.deepEqual(hiddenDeclarationsFor([], infos, "plan", "read-only"), [LOADOUT_HOST_NAME]);
  assert.deepEqual(hiddenDeclarationsFor(declared, infos, null, "read-only").sort(), [
    "bridge_tool",
    "codemode",
    "edit",
    LOADOUT_HOST_NAME,
    "plannotator_submit_plan",
    "tt_blocked",
    "write",
  ]);
  // The plan diet: delegation and the `never` row hidden; research, the engine and the unknown
  // bridge (it passes every diet) declared.
  assert.deepEqual(hiddenDeclarationsFor(declared, infos, "plan", "read-write").sort(), [
    LOADOUT_HOST_NAME,
    "plannotator_submit_plan",
    "subagent",
    "tt_blocked",
  ]);
  assert.deepEqual(hiddenDeclarationsFor(declared, infos, "implement", "read-write").sort(), [
    LOADOUT_HOST_NAME,
    "plannotator_submit_plan",
    "tt_allowed",
  ]);
  // Pi's MCP builtin tool is hidden in every gated landing and declared in every open one.
  const mcp = new Map<string, Provenance>([[MCP_TOOL, BUILTIN("mcp")]]);
  for (const stage of [...REGISTRY_STAGE_IDS, null]) {
    assert.ok(hiddenDeclarationsFor([MCP_TOOL], mcp, stage, "read-only").includes(MCP_TOOL));
    assert.ok(!hiddenDeclarationsFor([MCP_TOOL], mcp, stage, "read-write").includes(MCP_TOOL));
  }
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

test("toolMatrix: perk + builtin rows, the postures section, sorted eligibility, and the unscoped key", () => {
  const m = toolMatrix();
  assert.deepEqual(m.stages, REGISTRY_IDS);
  assert.deepEqual(m.tools.tt_carve, {
    owner: "perk",
    kind: "action",
    stages: ["objective-refine", "plan"].sort(
      (a, b) => REGISTRY_IDS.indexOf(a) - REGISTRY_IDS.indexOf(b),
    ),
    gated: "carve-out",
    nested: "blocked",
    mode_over_stage: false,
    declared: "always",
    exposure: "model-only",
  });
  assert.equal(m.tools.tt_allowed?.nested, "allowed");
  assert.equal(m.tools.tt_model_only?.nested, "blocked");
  assert.deepEqual(m.tools.bash, {
    owner: "builtin",
    gated: "verdict",
    nested: "verdict",
    registrar: "core",
  });
  // The suspended row carries its lift: the read-only stages, and per stage the writers that keep
  // `only` suspended (the two mode-over-stage direct actions; the family is all queries here).
  const stranded = Object.fromEntries(
    READ_ONLY_STAGES.map((stage) => [stage, ["tt_over", "tt_over_blocked"]]),
  );
  assert.deepEqual(m.tools.codemode, {
    owner: "builtin",
    gated: "blocked",
    nested: "blocked",
    registrar: "extension",
    suspended: {
      lifted_in: [...READ_ONLY_STAGES],
      stranded_writers: { nonparticipant: stranded, cohort: stranded },
    },
  });
  for (const name of ["read", "edit", "tool_search"])
    assert.equal("suspended" in (m.tools[name] ?? {}), false, name);
  assert.deepEqual(m.tools.tool_search, {
    owner: "builtin",
    gated: "allowed",
    nested: "blocked",
    registrar: "extension",
  });
  assert.deepEqual(
    Object.values(m.tools)
      .map((t) => t.owner)
      .filter((o) => o !== "perk" && o !== "builtin"),
    [],
  );
  assert.deepEqual(m.postures.packages["npm:pi-subagents"], {
    posture: "delegation",
    stages: REGISTRY_IDS.filter((id) => [...WORKTREE_STAGES, "stack-review"].includes(id)),
    gated: "allowed",
  });
  assert.deepEqual(m.postures.packages["npm:pi-mono-linear"]?.except?.posture, "never");
  assert.deepEqual(m.postures.packages["npm:@plannotator/pi-extension"], {
    posture: "never",
    stages: [],
    gated: "blocked",
  });
  assert.deepEqual(m.postures.paths, {
    "<inline:pi-subagents:prompt-runtime>": {
      posture: "child-engine",
      stages: "all",
      gated: "allowed",
    },
  });
  assert.deepEqual(m.postures.unknown, { stages: "all", gated: "blocked" });
  for (const stage of REGISTRY_IDS) {
    const row = m.eligible[stage];
    assert.ok(row !== undefined);
    assert.deepEqual(
      row["read-only"],
      [...gatedToolsFor(stage), "read", "grep", "find", "ls", "bash", "tool_search"].sort(),
    );
    assert.ok(row["read-write"].includes("edit") && row["read-write"].includes("codemode"));
    // The nested view: the gate-eligible queries plus the core builtin reads (bash by verdict).
    assert.deepEqual(
      row.nested,
      [
        ...gatedToolsFor(stage).filter((n) => perkToolPolicy(n)?.kind === "query"),
        "read",
        "grep",
        "find",
        "ls",
        "bash",
      ].sort(),
      stage,
    );
  }
  assert.deepEqual(m.eligible.plan?.nested, [
    "bash",
    "find",
    "grep",
    "ls",
    "read",
    "tt_allowed",
    "tt_allowed_wide",
    "tt_deferred",
    // the validation tests' recorded plan-stage queries
    "vp_dup",
    "vr_dup",
  ]);
  assert.ok(m.eligible.plan?.["read-only"].includes("tt_carve"));
  assert.ok(m.eligible.plan?.["read-only"].includes("tt_model_only"));
  // Outside the cohort a family member is eligible like any tool; its row reads the registered
  // default (`direct`).
  assert.deepEqual(m.eligible.unscoped?.["read-write"], Object.keys(m.tools).sort());
  assert.equal(m.tools.tt_deferred?.owner, "perk");
  assert.deepEqual(
    m.tools.tt_deferred?.owner === "perk"
      ? [m.tools.tt_deferred.declared, m.tools.tt_deferred.exposure]
      : [],
    ["deferred", "direct"],
  );
});

test("discoveryFamily: the catalogued deferred names, in catalog order", () => {
  assert.deepEqual(
    discoveryFamily(),
    perkToolNames().filter((n) => perkToolPolicy(n)?.declared === "deferred"),
  );
  assert.ok(discoveryFamily().includes("tt_deferred"));
  assert.ok(!discoveryFamily().includes("tt_allowed"));
});

test("isDiscoveryHost: only Pi's builtin tool_search, registered and active", () => {
  const builtin = new Map<string, Provenance>([["tool_search", BUILTIN("tool_search")]]);
  assert.equal(isDiscoveryHost(builtin, ["read", "tool_search"]), true);
  assert.equal(isDiscoveryHost(builtin, ["read"]), false, "an inactive builtin");
  assert.equal(isDiscoveryHost(new Map(), ["tool_search"]), false, "an unregistered name");
  for (const foreign of [pkg("npm:some-search@1.0.0"), OTHER_INLINE]) {
    const namesake = new Map<string, Provenance>([["tool_search", foreign]]);
    assert.equal(isDiscoveryHost(namesake, ["tool_search"]), false, "a foreign namesake");
  }
});

test("gate suspension: only the builtin-sourced codemode; suspended while read-only, restored at release when still registered", () => {
  assert.equal(gateSuspends("codemode", BUILTIN("codemode")), true);
  assert.equal(gateSuspends("codemode", pkg("npm:some-codemode")), false, "a foreign namesake");
  assert.equal(gateSuspends("codemode", undefined), false);
  for (const name of ["edit", "write", "tool_search", "read"])
    assert.equal(gateSuspends(name, BUILTIN(name)), false, name);
  const infos = new Map<string, Provenance>([
    ["codemode", BUILTIN("codemode")],
    ["edit", BUILTIN("edit")],
  ]);
  // Read-only: switched off and remembered (a memo accumulates).
  assert.deepEqual(suspensionStep({ active: ["edit", "codemode"], infos }, "read-only", []), {
    active: ["edit"],
    suspended: ["codemode"],
  });
  assert.deepEqual(suspensionStep({ active: ["edit"], infos }, "read-only", ["codemode"]), {
    active: ["edit"],
    suspended: ["codemode"],
  });
  // Read-write: restored only from the memo, only while still registered, never duplicated.
  assert.deepEqual(suspensionStep({ active: ["edit"], infos }, "read-write", ["codemode"]), {
    active: ["edit", "codemode"],
    suspended: [],
  });
  assert.deepEqual(suspensionStep({ active: ["edit"], infos }, "read-write", []), {
    active: ["edit"],
    suspended: [],
  });
  assert.deepEqual(
    suspensionStep({ active: ["edit", "codemode"], infos }, "read-write", ["codemode"]),
    { active: ["edit", "codemode"], suspended: [] },
  );
  assert.deepEqual(
    suspensionStep({ active: ["edit"], infos: new Map() }, "read-write", ["codemode"]),
    { active: ["edit"], suspended: [] },
    "an unregistered codemode is not restored",
  );
  assert.equal(sameNames(["a", "b"], ["b", "a", "a"]), true);
  assert.equal(sameNames(["a"], ["a", "b"]), false);
});

// --- the codemode lift (contracts.md §8.40) -------------------------------------------------------
//

test("strandedWriters: a registered, gate-eligible, direct, nested-blocked perk tool — catalog order", () => {
  // Recorded inside the test (top-level records run before every test): a gate-allowed direct
  // action that is NOT mode-over-stage, stranded exactly where it is staged.
  recordPerkTool("tt_allowed_action", { stages: ["plan"], gated: "allowed", kind: "action" });
  const only = (names: readonly string[]) => ({ registered: names });
  // A registered gate-allowed direct action strands where it is gate-eligible…
  assert.deepEqual(strandedWriters("plan", only(["tt_allowed_action"])), ["tt_allowed_action"]);
  assert.deepEqual(strandedWriters("implement", only(["tt_allowed_action"])), []);
  // …but not when this activation deferred it, nor when the host never registered it.
  assert.deepEqual(
    strandedWriters("plan", { ...only(["tt_allowed_action"]), deferred: ["tt_allowed_action"] }),
    [],
  );
  assert.deepEqual(strandedWriters("plan", only([])), []);
  assert.deepEqual(strandedWriters("plan", only(["read", "codemode"])), []);
  // A carve-out (model-only), a gate-eligible query, a model-only kind and a gate-blocked action
  // never strand.
  for (const [name, stage] of [
    ["tt_carve", "plan"],
    ["tt_carve", "objective-refine"],
    ["tt_allowed", "plan"],
    ["tt_allowed_wide", "objective-plan"],
    ["tt_deferred", "plan"],
    ["tt_model_only", "plan"],
    ["tt_blocked", "implement"],
  ] as const) {
    assert.deepEqual(strandedWriters(stage, only([name])), [], `${name} @ ${stage}`);
  }
  // A mode-over-stage gate-allowed action strands in every known stage.
  for (const stage of REGISTRY_STAGE_IDS)
    assert.deepEqual(strandedWriters(stage, only(["tt_over"])), ["tt_over"], stage);
  // No `registered` fact → the whole catalog is a candidate, in catalog order.
  assert.deepEqual(
    strandedWriters("plan"),
    perkToolNames().filter((n) => ["tt_over", "tt_over_blocked", "tt_allowed_action"].includes(n)),
  );
  assert.deepEqual(strandedWriters("implement"), ["tt_over", "tt_over_blocked"]);
});

test("the codemode lift: eligible under the gate only in a read-only stage with mode on, or only without a stranded writer", () => {
  const codemode = BUILTIN("codemode");
  const noWriters = { registered: ["read", "bash", "codemode", "tt_allowed", "tt_carve"] };
  for (const stage of [...REGISTRY_STAGE_IDS, null, "no-such-stage"]) {
    const readOnlyStage = stage !== null && READ_ONLY_STAGES.includes(stage);
    const at = `${stage}`;
    // No landing (or no codemode fact): suspended everywhere, as before.
    assert.equal(isEligible("codemode", codemode, stage, "read-only"), false, at);
    assert.equal(isEligible("codemode", codemode, stage, "read-only", noWriters), false, at);
    // Mode on: lifted in exactly the read-only stages.
    assert.equal(
      isEligible("codemode", codemode, stage, "read-only", { codemode: "on" }),
      readOnlyStage,
      `${at} on`,
    );
    // Mode only: lifted there iff no stranded writer among the registered names.
    assert.equal(
      isEligible("codemode", codemode, stage, "read-only", { codemode: "only" }),
      false,
      `${at} only, the whole catalog (tt_over strands)`,
    );
    assert.equal(
      isEligible("codemode", codemode, stage, "read-only", { codemode: "only", ...noWriters }),
      readOnlyStage,
      `${at} only, no writer registered`,
    );
    assert.equal(
      isEligible("codemode", codemode, stage, "read-only", {
        codemode: "only",
        registered: [...noWriters.registered, "tt_over"],
      }),
      false,
      `${at} only, a stranded writer registered`,
    );
    // Read-write: eligible whatever the landing.
    assert.equal(isEligible("codemode", codemode, stage, "read-write"), true, at);
    // The other builtins ignore the landing; a foreign namesake never lifts.
    const landings: GateLanding[] = [{}, { codemode: "on" }, { codemode: "only", ...noWriters }];
    for (const landing of landings) {
      assert.equal(isEligible("read", BUILTIN("read"), stage, "read-only", landing), true);
      assert.equal(isEligible("edit", BUILTIN("edit"), stage, "read-only", landing), false);
      assert.equal(isEligible("write", BUILTIN("write"), stage, "read-only", landing), false);
      assert.equal(
        isEligible("tool_search", BUILTIN("tool_search"), stage, "read-only", landing),
        true,
      );
      assert.equal(
        isEligible("codemode", pkg("npm:some-codemode"), stage, "read-only", landing),
        false,
        `${at}: a foreign namesake`,
      );
    }
  }
  // An unscoped `only` lifts nowhere even with nothing stranded; the stage normalizes first.
  assert.equal(
    isEligible("codemode", codemode, "constructor", "read-only", { codemode: "on" }),
    false,
  );
  // The perk arms ignore the landing.
  for (const landing of [{}, { codemode: "on" as const }])
    assert.equal(isEligible("tt_blocked", undefined, "implement", "read-only", landing), false);
});

test("the codemode lift in the suspension step: a lifted landing suspends nothing and consumes the memo; a non-lifted one keeps today's rows", () => {
  const infos = new Map<string, Provenance>([
    ["codemode", BUILTIN("codemode")],
    ["edit", BUILTIN("edit")],
  ]);
  const on = { codemode: "on" as const };
  assert.equal(gateSuspends("codemode", BUILTIN("codemode"), "plan", on), false);
  assert.equal(gateSuspends("codemode", BUILTIN("codemode"), "plan"), true);
  assert.equal(gateSuspends("codemode", BUILTIN("codemode"), "implement", on), true);
  assert.equal(gateSuspends("codemode", BUILTIN("codemode"), null, on), true);
  assert.equal(gateSuspends("codemode", pkg("npm:some-codemode"), "plan", on), false);
  assert.equal(gateSuspends("edit", BUILTIN("edit"), "plan", on), false);
  // A lifted landing switches nothing off and remembers nothing.
  assert.deepEqual(
    suspensionStep({ active: ["edit", "codemode"], infos }, "read-only", [], "plan", on),
    { active: ["edit", "codemode"], suspended: [] },
  );
  // It restores an inactive remembered codemode exactly once and drops it from the memo…
  const restored = suspensionStep(
    { active: ["edit"], infos },
    "read-only",
    ["codemode"],
    "plan",
    on,
  );
  assert.deepEqual(restored, { active: ["edit", "codemode"], suspended: [] });
  assert.deepEqual(
    suspensionStep({ active: restored.active, infos }, "read-only", restored.suspended, "plan", on),
    { active: ["edit", "codemode"], suspended: [] },
    "never twice",
  );
  // …drops an already-active remembered codemode from the memo without changing the set…
  assert.deepEqual(
    suspensionStep({ active: ["edit", "codemode"], infos }, "read-only", ["codemode"], "plan", on),
    { active: ["edit", "codemode"], suspended: [] },
  );
  // …and once consumed, a later deactivation is never undone (eligibility alone activates nothing).
  assert.deepEqual(suspensionStep({ active: ["edit"], infos }, "read-only", [], "plan", on), {
    active: ["edit"],
    suspended: [],
  });
  // `only` lifts by the stranded-writer rule over the registered names.
  const onlyClear = { codemode: "only" as const, registered: ["edit", "codemode"] };
  assert.deepEqual(
    suspensionStep({ active: ["edit", "codemode"], infos }, "read-only", [], "audit", onlyClear),
    { active: ["edit", "codemode"], suspended: [] },
  );
  assert.deepEqual(
    suspensionStep({ active: ["edit", "codemode"], infos }, "read-only", [], "audit", {
      codemode: "only",
    }),
    { active: ["edit"], suspended: ["codemode"] },
    "the whole catalog strands tt_over",
  );
  // A non-lifted landing keeps today's rows: switched off and remembered.
  for (const [stage, landing] of [
    ["implement", on],
    [null, on],
    ["plan", {}],
  ] as const) {
    assert.deepEqual(
      suspensionStep({ active: ["edit", "codemode"], infos }, "read-only", [], stage, landing),
      { active: ["edit"], suspended: ["codemode"] },
      `${stage}`,
    );
  }
  // An unregistered remembered name is retained untouched.
  const bare = new Map<string, Provenance>([["edit", BUILTIN("edit")]]);
  assert.deepEqual(
    suspensionStep({ active: ["edit"], infos: bare }, "read-only", ["codemode"], "plan", on),
    { active: ["edit"], suspended: ["codemode"] },
  );
  // The read-write arm is unchanged by any landing.
  assert.deepEqual(
    suspensionStep({ active: ["edit"], infos }, "read-write", ["codemode"], "plan", on),
    { active: ["edit", "codemode"], suspended: [] },
  );
  assert.deepEqual(
    suspensionStep({ active: ["edit", "codemode"], infos }, "read-write", ["codemode"], "plan", on),
    { active: ["edit", "codemode"], suspended: [] },
  );
});

test("the codemode lift in presentation: hiddenDeclarationsFor declares a lifted codemode and hides it otherwise", () => {
  const infos = new Map<string, Provenance>([
    ["read", BUILTIN("read")],
    ["edit", BUILTIN("edit")],
    ["codemode", BUILTIN("codemode")],
  ]);
  const declared = [...infos.keys()];
  assert.deepEqual(
    hiddenDeclarationsFor(declared, infos, "plan", "read-only", { codemode: "on" }).sort(),
    ["edit", LOADOUT_HOST_NAME],
  );
  assert.deepEqual(hiddenDeclarationsFor(declared, infos, "plan", "read-only").sort(), [
    "codemode",
    "edit",
    LOADOUT_HOST_NAME,
  ]);
  assert.ok(
    hiddenDeclarationsFor(declared, infos, "implement", "read-only", { codemode: "on" }).includes(
      "codemode",
    ),
  );
});
