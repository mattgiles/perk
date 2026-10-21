// The golden stage×tool matrix (`shared/fixtures/tool-matrix.json`): derived from the catalog +
// the posture rows by `toolMatrix()`, committed, and drift-guarded here byte-for-byte. Both
// planes' prompt guards read it (the Python half reads only the file). Regenerate with
//   PERK_UPDATE_TOOL_MATRIX=1 node --test extension/substrate/toolMatrix.test.ts

import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { before, test } from "node:test";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { sharedDir } from "./resources.ts";
import {
  BUILTIN_TOOL_POLICY,
  gatedToolsFor,
  nestedPostureFor,
  PACKAGE_TOOL_POLICY,
  PLANNING_READ_STAGES,
  perkToolNames,
  postureFor,
  READ_ONLY_STAGES,
  REGISTRY_STAGE_IDS,
  SYNTHETIC_PATH_TOOL_POLICY,
  stageToolsFor,
  toolMatrix,
  UNSCOPED_MATRIX_KEY,
  WORKTREE_STAGES,
} from "./toolPolicy.ts";

const FIXTURE = join(sharedDir(), "fixtures", "tool-matrix.json");

before(ensureToolCatalog);

/** Keys sorted at every depth, 2-space indent, trailing newline (arrays keep their order). */
function canonicalJson(value: unknown): string {
  const sortKeys = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sortKeys);
    if (v !== null && typeof v === "object") {
      return Object.fromEntries(
        Object.keys(v)
          .sort()
          .map((key) => [key, sortKeys((v as Record<string, unknown>)[key])]),
      );
    }
    return v;
  };
  return `${JSON.stringify(sortKeys(value), null, 2)}\n`;
}

test("the committed matrix equals the derived one byte-for-byte (regenerate on purpose)", () => {
  const derived = canonicalJson(toolMatrix());
  if (process.env.PERK_UPDATE_TOOL_MATRIX === "1") writeFileSync(FIXTURE, derived, "utf8");
  assert.equal(
    readFileSync(FIXTURE, "utf8"),
    derived,
    "shared/fixtures/tool-matrix.json drifted — regenerate with PERK_UPDATE_TOOL_MATRIX=1",
  );
});

test("toolMatrix() is the derived views: perk + builtin rows, the posture table, eligibility = the views", () => {
  const matrix = toolMatrix();
  const builtins = Object.keys(BUILTIN_TOOL_POLICY);
  assert.deepEqual(Object.keys(matrix.tools).sort(), [...builtins, ...perkToolNames()].sort());
  for (const name of perkToolNames()) assert.equal(matrix.tools[name]?.owner, "perk", name);
  assert.deepEqual(
    Object.keys(matrix.postures.packages).sort(),
    Object.keys(PACKAGE_TOOL_POLICY).sort(),
  );
  assert.deepEqual(Object.keys(matrix.postures.paths), Object.keys(SYNTHETIC_PATH_TOOL_POLICY));
  const gatedBuiltins = builtins.filter((n) => BUILTIN_TOOL_POLICY[n]?.gated !== "blocked");
  for (const stage of REGISTRY_STAGE_IDS) {
    const row = matrix.eligible[stage];
    assert.ok(row !== undefined, stage);
    assert.deepEqual(
      row["read-only"],
      [...gatedToolsFor(stage), ...gatedBuiltins].sort(),
      `${stage} read-only`,
    );
    assert.deepEqual(
      row["read-write"],
      [...(stageToolsFor(stage) ?? []), ...builtins].sort(),
      `${stage} read-write`,
    );
  }
  const unscoped = matrix.eligible[UNSCOPED_MATRIX_KEY];
  assert.deepEqual(unscoped?.["read-only"], [...gatedToolsFor(null), ...gatedBuiltins].sort());
  assert.deepEqual(unscoped?.["read-write"], Object.keys(matrix.tools).sort());
  // The nested arm: every row's `nested` is the derived nested posture, and every landing's
  // `nested` list is its `read-only` list filtered through the rows not blocked nested.
  for (const [name, row] of Object.entries(matrix.tools)) {
    const provenance =
      row.owner === "builtin" ? { path: `builtin:${name}`, source: "builtin" } : undefined;
    assert.equal(row.nested, nestedPostureFor(postureFor(name, provenance)), `${name} nested`);
  }
  for (const [landing, row] of Object.entries(matrix.eligible)) {
    assert.deepEqual(
      row.nested,
      row["read-only"].filter((name) => matrix.tools[name]?.nested !== "blocked"),
      `${landing} nested`,
    );
  }
});

test("the nested arm: the one query is the only perk row admitted nested; writers, actions and tool_search are not", () => {
  const matrix = toolMatrix();
  const nestedPerk = Object.entries(matrix.tools)
    .filter(([, row]) => row.owner === "perk" && row.nested === "allowed")
    .map(([name]) => name);
  assert.deepEqual(nestedPerk, ["objective_stack_status"]);
  const plan = matrix.eligible.plan;
  assert.ok(plan !== undefined);
  assert.deepEqual(plan.nested, ["bash", "find", "grep", "ls", "objective_stack_status", "read"]);
  for (const name of ["plan_draft", "push_annotations"]) {
    assert.ok(plan["read-only"].includes(name), `${name} stays gate-eligible in plan`);
    assert.ok(!plan.nested.includes(name), `${name} is never nested-eligible`);
  }
  assert.equal(matrix.tools.plan_draft?.nested, "blocked");
  assert.equal(matrix.tools.tool_search?.nested, "blocked");
  assert.equal(matrix.tools.bash?.nested, "verdict");
  assert.equal(matrix.tools.read?.nested, "allowed");
});

test("the one query is gate-allowed in the worktree family and the planning/refinement stages", () => {
  const matrix = toolMatrix();
  const queries = Object.entries(matrix.tools)
    .filter(([, row]) => row.owner === "perk" && row.kind === "query")
    .map(([name]) => name);
  assert.deepEqual(queries, ["objective_stack_status"]);
  const row = matrix.tools.objective_stack_status;
  assert.ok(row?.owner === "perk");
  assert.deepEqual(
    {
      gated: row.gated,
      declared: row.declared,
      exposure: row.exposure,
      stages: row.stages,
    },
    {
      gated: "allowed",
      declared: "deferred",
      exposure: "direct",
      stages: REGISTRY_STAGE_IDS.filter((id) =>
        [...WORKTREE_STAGES, ...PLANNING_READ_STAGES].includes(id),
      ),
    },
  );
  for (const stage of ["plan", "objective-plan", "objective-refine", "implement"]) {
    assert.ok(
      matrix.eligible[stage]?.["read-only"].includes("objective_stack_status"),
      `${stage} read-only admits it`,
    );
  }
  for (const stage of [
    "objective-author",
    "gist-author",
    "save",
    "objective-save",
    "audit",
    "stack-review",
  ]) {
    assert.ok(
      !matrix.eligible[stage]?.["read-only"].includes("objective_stack_status"),
      `${stage} read-only excludes it`,
    );
  }
});

test("the codemode lift: lifted in the read-only stages; `only` strands the two mode-over-stage actions for a nonparticipant and nothing in the cohort; the writers are model-only", () => {
  const matrix = toolMatrix();
  const row = matrix.tools.codemode;
  assert.ok(row?.owner === "builtin" && row.suspended !== undefined);
  assert.deepEqual(row.suspended.lifted_in, READ_ONLY_STAGES);
  for (const stage of READ_ONLY_STAGES) {
    assert.deepEqual(
      row.suspended.stranded_writers.nonparticipant[stage],
      ["collect_draft_review_wave", "push_annotations"],
      `${stage} nonparticipant`,
    );
    assert.deepEqual(row.suspended.stranded_writers.cohort[stage], [], `${stage} cohort`);
  }
  assert.deepEqual(
    Object.keys(row.suspended.stranded_writers.nonparticipant).sort(),
    [...READ_ONLY_STAGES].sort(),
  );
  // The five action carve-outs (the bounded writers) are model-only and never nested grants.
  const writers = Object.entries(matrix.tools)
    .filter(([, t]) => t.owner === "perk" && t.gated === "carve-out" && t.kind === "action")
    .map(([name]) => name);
  assert.deepEqual(writers.sort(), [
    "gist_draft",
    "objective_draft",
    "objective_node",
    "objective_refinement_draft",
    "plan_draft",
  ]);
  for (const [name, t] of Object.entries(matrix.tools)) {
    if (t.owner !== "perk" || t.gated !== "carve-out") continue;
    assert.equal(t.exposure, "model-only", `${name} exposure`);
    assert.equal(t.nested, "blocked", `${name} nested`);
  }
  // The unconditional eligibility view is unchanged: codemode never appears under the gate.
  for (const [landing, eligible] of Object.entries(matrix.eligible)) {
    assert.ok(!eligible["read-only"].includes("codemode"), `${landing} read-only`);
    assert.ok(eligible["read-write"].includes("codemode"), `${landing} read-write`);
  }
});
