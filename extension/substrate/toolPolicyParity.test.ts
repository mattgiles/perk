// The migration bridge from the hand-maintained tool lists to the derived views (contracts.md
// §8.40): the pre-migration lists are frozen here as test data, and every derived view must equal
// them EXCEPT for the four enumerated deltas below — (a) the per-stage gate-ON narrowing, (b) the
// borrowed-stage gate-OFF additions, (c) the mode-over-stage set, (d) the unscoped refinement
// writer. Set equality, never order: nothing in perk depends on the declaration order Pi receives.
// Retired once the foreign rows become provenance-derived.

import assert from "node:assert/strict";
import { before, test } from "node:test";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import {
  FFF_SEARCH_TOOLS,
  gatedToolsFor,
  LINEAR_READ_TOOLS,
  perkToolNames,
  perkToolPolicy,
  REGISTRY_STAGE_IDS,
  SUBAGENT_CHILD_TOOLS,
  SUBAGENT_TOOLS,
  stageToolsFor,
  WEB_RESEARCH_TOOLS,
} from "./toolPolicy.ts";

before(ensureToolCatalog);

// --- the frozen pre-migration lists (names copied from the deleted hand lists) ------------------

const OLD_READ_ONLY_TOOLS: readonly string[] = [
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
  ...WEB_RESEARCH_TOOLS,
  ...LINEAR_READ_TOOLS,
  ...FFF_SEARCH_TOOLS,
  ...SUBAGENT_TOOLS,
  "explore_objective_node",
  "run_scout_wave",
  "run_librarian",
  ...SUBAGENT_CHILD_TOOLS,
  "push_annotations",
  "start_draft_review_wave",
  "collect_draft_review_wave",
  "run_audit_wave",
  "run_harvest_wave",
  "run_dream_wave",
];

const OLD_REFINEMENT_READ_ONLY_TOOLS: readonly string[] = [
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
];

const OLD_PERK_TOOLS: readonly string[] = [
  "plan_review",
  "plan_save",
  "plan_draft",
  "objective_save",
  "objective_node",
  "reconcile_objective",
  "add_objective_node",
  "objective_draft",
  "gist_draft",
  "gist_save",
  "objective_refinement_draft",
  "learn",
  "run_learn_wave",
  "run_audit_wave",
  "run_harvest_wave",
  "run_dream_wave",
  "land",
  "post_pr_review",
  "ready",
  "classify_review_feedback",
  "finalize_address",
  "explore_objective_node",
  "run_scout_wave",
  "run_librarian",
  "run_pr_review_wave",
  "submit_pr_review",
  "start_review_wave",
  "collect_review_wave",
  "push_annotations",
  "start_draft_review_wave",
  "collect_draft_review_wave",
  "run_ci",
  "submit",
  "resolve_submit_conflicts",
  "open_stack_review",
  "objective_stack_status",
  "objective_stack_sync",
  "objective_stack_adopt",
  "objective_stack_recover",
  "objective_stack_land",
];

const OLD_RESEARCH_TOOLS: readonly string[] = [
  ...WEB_RESEARCH_TOOLS,
  ...LINEAR_READ_TOOLS,
  ...FFF_SEARCH_TOOLS,
];

const OLD_WORKTREE_STAGE_TOOLS: readonly string[] = [
  "ask_user_question",
  "submit",
  "resolve_submit_conflicts",
  "ready",
  "run_ci",
  "land",
  "learn",
  "run_learn_wave",
  "classify_review_feedback",
  "finalize_address",
  "post_pr_review",
  "run_pr_review_wave",
  "submit_pr_review",
  "start_review_wave",
  "collect_review_wave",
  "push_annotations",
  "reconcile_objective",
  "add_objective_node",
  "objective_node",
  "objective_stack_status",
  "objective_stack_sync",
  "objective_stack_adopt",
  "objective_stack_recover",
  "objective_stack_land",
  "run_librarian",
  ...OLD_RESEARCH_TOOLS,
  ...SUBAGENT_TOOLS,
  "todo",
];

const OLD_STAGE_TOOLS: Readonly<Record<string, readonly string[]>> = {
  "objective-refine": [
    "ask_user_question",
    "objective_refinement_draft",
    "plan_review",
    ...OLD_RESEARCH_TOOLS,
  ],
  "gist-author": ["ask_user_question", "gist_draft", "gist_save", ...OLD_RESEARCH_TOOLS],
  "gist-save": ["ask_user_question", "gist_draft", "gist_save", ...OLD_RESEARCH_TOOLS],
  "objective-author": [
    "ask_user_question",
    "objective_draft",
    "objective_save",
    "reconcile_objective",
    "add_objective_node",
    "objective_node",
    "run_scout_wave",
    "run_librarian",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    "plan_review",
    ...OLD_RESEARCH_TOOLS,
  ],
  "objective-save": [
    "ask_user_question",
    "objective_draft",
    "objective_save",
    "reconcile_objective",
    "add_objective_node",
    "objective_node",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    "plan_review",
    ...OLD_RESEARCH_TOOLS,
  ],
  "objective-plan": [
    "ask_user_question",
    "plan_draft",
    "plan_review",
    "plan_save",
    "objective_node",
    "explore_objective_node",
    "run_scout_wave",
    "run_librarian",
    "reconcile_objective",
    "add_objective_node",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    ...OLD_RESEARCH_TOOLS,
  ],
  plan: [
    "ask_user_question",
    "plan_draft",
    "plan_review",
    "plan_save",
    "run_scout_wave",
    "run_librarian",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    ...OLD_RESEARCH_TOOLS,
  ],
  save: [
    "ask_user_question",
    "plan_draft",
    "plan_review",
    "plan_save",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    ...OLD_RESEARCH_TOOLS,
  ],
  implement: OLD_WORKTREE_STAGE_TOOLS,
  submit: OLD_WORKTREE_STAGE_TOOLS,
  address: OLD_WORKTREE_STAGE_TOOLS,
  land: OLD_WORKTREE_STAGE_TOOLS,
  learn: OLD_WORKTREE_STAGE_TOOLS,
  audit: ["ask_user_question", "run_audit_wave", ...OLD_RESEARCH_TOOLS],
  "stack-review": [
    "ask_user_question",
    "open_stack_review",
    "start_review_wave",
    "collect_review_wave",
    "push_annotations",
    "submit_pr_review",
    ...SUBAGENT_TOOLS,
    ...OLD_RESEARCH_TOOLS,
  ],
};

/** The pre-migration gate-ON selection: refinement's own, else the one stage-blind list. */
function oldGated(stage: string | null): readonly string[] {
  return stage === "objective-refine" ? OLD_REFINEMENT_READ_ONLY_TOOLS : OLD_READ_ONLY_TOOLS;
}

// --- the enumerated deltas ----------------------------------------------------------------------

const LEARN_WAVES = ["run_audit_wave", "run_harvest_wave", "run_dream_wave"];
const WORKTREE = ["implement", "submit", "address", "land", "learn"];

/** Delta (a): names a stage's gated view no longer carries (it sees only its own stage's tools). */
const DELTA_A: Readonly<Record<string, readonly string[]>> = {
  ...Object.fromEntries(
    ["gist-author", "gist-save"].map((stage) => [
      stage,
      [
        "objective_draft",
        "objective_node",
        ...SUBAGENT_TOOLS,
        "explore_objective_node",
        "run_scout_wave",
        "run_librarian",
        ...LEARN_WAVES,
      ],
    ]),
  ),
  "objective-author": ["gist_draft", ...SUBAGENT_TOOLS, "explore_objective_node", "run_audit_wave"],
  "objective-save": [
    "gist_draft",
    ...SUBAGENT_TOOLS,
    "explore_objective_node",
    "run_scout_wave",
    "run_librarian",
    ...LEARN_WAVES,
  ],
  "objective-plan": ["objective_draft", "gist_draft", ...SUBAGENT_TOOLS, ...LEARN_WAVES],
  plan: [
    "objective_draft",
    "gist_draft",
    "objective_node",
    ...SUBAGENT_TOOLS,
    "explore_objective_node",
    ...LEARN_WAVES,
  ],
  save: [
    "objective_draft",
    "gist_draft",
    "objective_node",
    ...SUBAGENT_TOOLS,
    "explore_objective_node",
    "run_scout_wave",
    "run_librarian",
    ...LEARN_WAVES,
  ],
  ...Object.fromEntries(
    WORKTREE.map((stage) => [
      stage,
      ["objective_draft", "gist_draft", "explore_objective_node", "run_scout_wave", ...LEARN_WAVES],
    ]),
  ),
  audit: [
    "objective_draft",
    "gist_draft",
    "objective_node",
    ...SUBAGENT_TOOLS,
    "explore_objective_node",
    "run_scout_wave",
    "run_librarian",
    "run_harvest_wave",
    "run_dream_wave",
  ],
  "stack-review": [
    "objective_draft",
    "gist_draft",
    "objective_node",
    "explore_objective_node",
    "run_scout_wave",
    "run_librarian",
    ...LEARN_WAVES,
  ],
};

/** Delta (b): the borrowed-stage gate-OFF additions (the harvest/dream doors borrow the stage). */
const DELTA_B: Readonly<Record<string, readonly string[]>> = {
  "objective-author": ["run_harvest_wave", "run_dream_wave"],
};

/** Delta (c): the mode-over-stage set — the `/plan` flow, completable wherever the toggle lands. */
const DELTA_C: readonly string[] = [
  "plan_draft",
  "plan_review",
  "start_draft_review_wave",
  "collect_draft_review_wave",
  "push_annotations",
];

/** Delta (d): the unscoped formula declares the (inert there) refinement writer. */
function deltaD(stage: string | null): readonly string[] {
  return stage === null ? ["objective_refinement_draft"] : [];
}

const sorted = (names: Iterable<string>): string[] => [...new Set(names)].sort();

// --- the assertions -----------------------------------------------------------------------------

test("parity 1: the catalog is exactly the old PERK_TOOLS (no delta)", () => {
  assert.deepEqual(sorted(perkToolNames()), sorted(OLD_PERK_TOOLS));
});

test("parity 2: every stage's gate-OFF diet = the old STAGE_TOOLS row ∪ delta (b)", () => {
  assert.deepEqual(sorted(Object.keys(OLD_STAGE_TOOLS)), sorted(REGISTRY_STAGE_IDS));
  for (const stage of REGISTRY_STAGE_IDS) {
    assert.deepEqual(
      sorted(stageToolsFor(stage) ?? []),
      sorted([...(OLD_STAGE_TOOLS[stage] ?? []), ...(DELTA_B[stage] ?? [])]),
      stage,
    );
  }
  assert.equal(stageToolsFor(null), undefined, "unscoped: no diet");
});

test("parity 3: every gated view = (old − delta (a)) ∪ delta (c) ∪ delta (d), unscoped included", () => {
  for (const stage of [...REGISTRY_STAGE_IDS, null]) {
    const removed = new Set(stage === null ? [] : (DELTA_A[stage] ?? []));
    for (const name of removed) {
      assert.ok(oldGated(stage).includes(name), `delta (a) ${stage}: ${name} was never gated`);
      assert.ok(!DELTA_C.includes(name), `delta (a) ${stage}: ${name} is mode-over-stage`);
    }
    const expected = [
      ...oldGated(stage).filter((name) => !removed.has(name)),
      ...DELTA_C,
      ...deltaD(stage),
    ];
    assert.deepEqual(sorted(gatedToolsFor(stage)), sorted(expected), String(stage));
  }
  assert.deepEqual(gatedToolsFor("not-a-stage"), gatedToolsFor(null), "unknown = unscoped");
});

test("parity 4: the mode-over-stage set is exactly delta (c)", () => {
  assert.deepEqual(
    sorted(perkToolNames().filter((name) => perkToolPolicy(name)?.modeOverStage === true)),
    sorted(DELTA_C),
  );
});

test("delta (c)'s only additive effect is the gated refinement view", () => {
  for (const stage of [...REGISTRY_STAGE_IDS, null]) {
    const added = DELTA_C.filter((name) => !oldGated(stage).includes(name));
    assert.deepEqual(
      sorted(added),
      stage === "objective-refine"
        ? sorted([
            "plan_draft",
            "start_draft_review_wave",
            "collect_draft_review_wave",
            "push_annotations",
          ])
        : [],
      String(stage),
    );
  }
});
