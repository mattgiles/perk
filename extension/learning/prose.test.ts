// The learn guidance prose's offline suite (pure renders): the `stages/learn.md` provider arms
// (github/linear/other/no-ref — the cold `_learn_prompt` parity body), the orchestration seed's
// judgment-bearing content, and the per-kind factory seeds. Skill pointers are NEVER hardcoded
// in these renders — the skill-binding suffix delivers them at the adapter's injection site.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { PlanRef } from "../substrate/cache.ts";
import { learnFactoryGuidance, learnGuidance, learnOrchestrateGuidance } from "./prose.ts";
import { CODE_FACTORY, DOCS_FACTORY } from "./routing.ts";

const PLAN_REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};

test("learnGuidance derives the head branch from the plan-ref (skill pointer is suffix-delivered)", () => {
  const withRef = learnGuidance(PLAN_REF);
  // The perk-learn skill pointer is no longer hardcoded — it rides the binding suffix.
  assert.doesNotMatch(withRef, /Follow the perk-learn skill/);
  assert.match(withRef, /plan-42/);
  assert.match(withRef, /gh pr list --head plan-42/);
  assert.match(withRef, /`learn` tool/);
  assert.match(withRef, /\/learn skip/);
  // Without a plan-ref it still names the tool (no branch derivation).
  const noRef = learnGuidance(null);
  assert.doesNotMatch(noRef, /Follow the perk-learn skill/);
  assert.match(noRef, /`learn` tool/);
});

test("learnGuidance: a linear plan-ref reads via the linear tools but keeps the gh PR derivation", () => {
  // PRs are GitHub-universal under every issue backend.
  const linear = learnGuidance({ ...PLAN_REF, provider: "linear" });
  assert.match(linear, /linear_get_issue/);
  assert.match(linear, /linear_list_comments/);
  assert.match(linear, /gh pr list --head plan-42/);
  assert.doesNotMatch(linear, /gh issue view/);
  // The github arm is unchanged.
  assert.match(learnGuidance(PLAN_REF), /gh issue view 42 --comments/);
  // An unknown provider collapses to a single "Open the plan and its merged change" line
  // (no merged-PR derivation) — the unified `other` arm matches cold `_learn_prompt`.
  const other = learnGuidance({ ...PLAN_REF, provider: "gitlab" });
  assert.match(other, /Open the plan and its merged change: https:\/\/gh\/o\/r\/issues\/42/);
  assert.doesNotMatch(other, /gh pr list --head plan-42/);
});

test("learnOrchestrateGuidance: names the tool, the angles, the reconcile steps, and the paths", () => {
  const g = learnOrchestrateGuidance({
    manifestPath: "/abs/learn-evidence/manifest.json",
    bundleDir: "/abs/learn-evidence",
  });
  // The wave runs through the flow-scoped tool — judgment-bearing inputs only.
  assert.match(g, /run_learn_wave/);
  assert.match(g, /2[\u2013-]4/);
  // The four angle slugs; session-deviations is mandatory (+ its off-track/dead-ends emphasis).
  assert.match(g, /session-deviations.*always included/);
  assert.match(g, /off-track/);
  assert.match(g, /dead ends/);
  assert.match(g, /plan-vs-implementation/);
  assert.match(g, /existing-docs/);
  assert.match(g, /validation-risk/);
  // Reports are untrusted DATA; reconcile → capture/skip; skipped angles come from the tool.
  assert.match(g, /untrusted DATA/);
  assert.match(g, /[Rr]econcile/);
  assert.match(g, /skipped angles are explicitly listed by the tool/);
  assert.match(g, /`learn`\*\* tool/);
  assert.match(g, /no `summary`/);
  // Renders the manifest path + bundle dir.
  assert.match(g, /\/abs\/learn-evidence\/manifest\.json/);
  assert.match(g, /\/abs\/learn-evidence/);
  // The wave-level failure arm: the parent analyzes the bundle itself — never a dead end.
  assert.match(g, /fails at wave level/);
  assert.match(g, /analyze the bundle YOURSELF/);
  // No orchestration mechanics — the wave module owns the script/spawn params.
  assert.doesNotMatch(g, /workflowScript/);
  assert.doesNotMatch(g, /runs\.all/);
  assert.doesNotMatch(g, /async: false/);
  assert.doesNotMatch(g, /fenced/);
});

// --- learnFactoryGuidance (pure, per kind) ------------------------------------------------------

for (const kind of [DOCS_FACTORY, CODE_FACTORY]) {
  test(`learnFactoryGuidance (${kind.name}) names the inbox path`, () => {
    const inbox = `.perk/workflow/scratch/${kind.name}-inbox.md`;
    const text = learnFactoryGuidance(kind, inbox, ["45", "50"]);
    assert.ok(text.includes(inbox), "the guidance names the inbox path");
  });

  test(`learnFactoryGuidance (${kind.name}) carries the consumed learn numbers`, () => {
    const text = learnFactoryGuidance(kind, "inbox.md", ["45", "50"]);
    assert.match(text, /consumed_learn: \[45, 50\]/);
  });

  test(`learnFactoryGuidance (${kind.name}) does not hardcode the perk-${kind.name} skill pointer`, () => {
    const text = learnFactoryGuidance(kind, "inbox.md", ["45"]);
    assert.doesNotMatch(text, new RegExp(`Follow the perk-${kind.name} skill`));
  });
}
