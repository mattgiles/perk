# Phase 3 · Turn 2 — the objective authoring loop

GitHub plan **#58**. Objective *creation* was cold-only and non-interactive: the single path was
`perk objective create --body @FILE`, where you hand-authored the markdown (and any roadmap YAML)
outside Pi, then shelled the CLI. Plans, by contrast, had the full in-session loop (`perk plan`
read-only session → `/plan` toggle + authoring context → `plan_save`). This turn mirrors that loop
for objectives, so an objective is drafted *and* saved from inside a session — and the agent never
hand-writes roadmap YAML.

## Decisions (locked)

- **A — mirror the plan loop, don't special-case.** Two new registry stages, the exact mirror of
  `plan`/`save`: `objective-author` (read-only authoring) → `objective-save` (the read-only →
  read-write boundary). New single-initial graph:
  `objective-author -> objective-save -> objective-plan -> plan -> save -> implement -> submit ->
  address -> land -> learn`. `objective-plan`'s predecessors flip from `[]` to `[objective-save]`;
  exactly one initial, one terminal, symmetric edges preserved.
- **`perk objective-author` is a dedicated seeded cold door** (like `objective-plan`, in
  `DEDICATED_STAGES`) — it takes no objective number and needs no GitHub up front (it *creates* the
  objective; the later `objective_save` write is the first mutation). `perk objective-save` is the
  generic registry launcher (parity with `perk save`).
- **`objective_save` = the warm twin of `plan_save`** (`extension/objectiveSave.ts`, mirror of
  `planSave.ts`): a terminating tool + `/objective-save` command that **delegate** the write to
  `perk objective create` (canonical mutation in Python), then link the live session
  (`active_objective` + a fresh `perk:objective-budget` marker, mirroring `/objective <id>`).
- **Never hand-write roadmap YAML** (erk's loudest tripwire). The tool takes `prose` + a
  **structured** `roadmap` (JSON array of nodes); `create_objective_issue` gains optional
  `roadmap_nodes`; `perk objective create` gains `--roadmap <json>` (+ `--run-id` for idempotent
  re-save). `objective.parse_structured_roadmap` defaults a missing per-node `status` to `pending`
  (id + description are the only required fields) and reuses the shared `validate_roadmap`.
- **Break one real coupling — the `stage` field.** `planMode.ts` injected plan-authoring context on
  *any* read-only gate. An `objective-author` session is also read-only, so a new `stage` field on
  `perk:workflow-state` (persisted at cold **claim** from the handoff) lets plan mode **defer** when
  `stage === "objective-author"`, and `extension/objectiveAuthor.ts` injects its own
  `perk:objective-author-context` instead. Exactly one authoring context is present.
- **Judgment in a skill.** New `skills/perk-objective-author/SKILL.md`: clarify the goal → explore
  read-only → structure the roadmap → save via the tool. Added to `PERK_SKILLS` + the manifest
  fragment.

## Findings (verified)

- **Discoveries.** `launch_stage(prompt_override=…)` is the seam the seeded cold door reuses (same
  as `objective_plan_cmd`). The read-only tool gate hides custom tools, so the model must exit
  read-only (`/plan` off) before calling `objective_save` — documented in the skill, mirroring the
  perk-plan flow. The handoff blob already carried `stage`; `resolveRunStage` read it transiently,
  but the claim path did not persist it into `perk:workflow-state` — so the `stage` field is the
  minimal new persisted state.
- **Corrections.** `validate_roadmap` requires `status` per node, which contradicted the tool's
  "status optional, defaults pending" — fixed by defaulting in `parse_structured_roadmap` (not by
  loosening the shared validator, which the YAML path also relies on).
- **Codebase evidence.** Registry validator (`perk/registry.py`) enforces single-initial /
  symmetric-edges, so the graph rewrite is checked by `test_real_registry_is_valid` +
  `test_objective_author_is_the_single_initial`. `stageConsumesPlanRef` is unaffected (the two new
  `worktree: none` stages don't list `cache.plan-ref`), so no plan-ref selector leaks into authoring
  sessions.

## Outcomes

Built as planned. Files: `shared/registry.yaml` (+2 stages, rewired edges); `perk/objective.py`
(`parse_structured_roadmap`); `perk/github.py` (`create_objective_issue` `roadmap_nodes`);
`perk/cli/commands/objective_cmd.py` (`--roadmap` + `--run-id`); new
`perk/cli/commands/objective_author_cmd.py`; `perk/cli/stages.py` + `perk/cli/cli.py` registration;
`perk/init.py` (PERK_SKILLS) + the manifest fragment. TS: `extension/workflowState.ts` +
`extension/cache.ts` (`stage`), `extension/index.ts` (record `stage` at claim + register the two new
modules), `extension/planMode.ts` (defer on objective-author), new `extension/objectiveAuthor.ts` +
`extension/objectiveSave.ts`. New skill `skills/perk-objective-author/SKILL.md`. Contracts §8.3
(`stage` row + the P3.T2 authoring-loop paragraph). Tests: Python (`test_registry`, `test_cli_stages`,
`test_objective`, `test_objective_cmd`) + TS (`objectiveSave.test.ts`, `objectiveAuthor.test.ts`).

Deferred / non-goals: no in-place upsert of an objective on re-save (idempotency returns the existing
issue without PATCHing — unlike `plan_save`'s `update_plan_issue`); no warm `/objective-author`
toggle (the cold door + `/plan` gate toggle suffice); no objective-author checkpoints (authoring is
prose, like `plan`).
