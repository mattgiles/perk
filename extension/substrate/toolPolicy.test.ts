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
  gatedToolsFor,
  gateSuspends,
  hiddenDeclarationsFor,
  isDiscoveryHost,
  isEligible,
  isPerkTool,
  LOADOUT_HOST_NAME,
  type Mode,
  normalizePackageSpec,
  normalizeStage,
  OBJECTIVE_STAGES,
  PACKAGE_TOOL_POLICY,
  PLAN_FAMILY_STAGES,
  POSTURE_ROWS,
  type Provenance,
  perkToolNames,
  perkToolPolicy,
  perkToolsFor,
  postureFor,
  REGISTRY_STAGE_IDS,
  reconcileTarget,
  recordPerkTool,
  SYNTHETIC_PATH_TOOL_POLICY,
  sameNames,
  stageToolsFor,
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
    () => validateToolPolicy("vp_carve", {}, { ...ok, gated: { carveOut: " " } }, REGISTRY_IDS),
    /a carve-out must name its bounded write/,
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
  });
  assert.deepEqual(postureFor("mcp_query", BUILTIN("mcp")), { owner: "unknown" });
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
    mode_over_stage: false,
    declared: "always",
    exposure: "direct",
  });
  assert.deepEqual(m.tools.bash, { owner: "builtin", gated: "verdict", registrar: "core" });
  assert.deepEqual(m.tools.codemode, {
    owner: "builtin",
    gated: "blocked",
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
  }
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
