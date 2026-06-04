---
title: plan-ref lifecycle and stage-gating
read_when: You are debugging plan-ref linkage, adding a new worktree stage, extending the PlanRef/PlanHeader schema, or implementing on-land secondary bookkeeping.
---

# plan-ref lifecycle and stage-gating

## Two-role duality of `plan-ref.json`

The same `plan-ref.json` file plays **two roles keyed on cwd**:

- **Repo root** — a mutable *selector*: "the plan a no-arg cold `perk implement` consumes next."
- **`plan-<N>` worktree** — a durable *binding*: "this worktree IS implementing plan #N."

The bug this insight resolved was the extension reconciling the root selector into a fresh planning
session. The fix is **gating only — no clearing** (clearing at `plan` would break no-arg
implement-resumes-last-save; the selector self-heals at the next `save`).

## `stageConsumesPlanRef` logic

`stageConsumesPlanRef(registry, stageId)` checks if `requires ∪ reads` lists `cache.plan-ref`.
Worktree-binding stages (implement/submit/address/land/learn) consume it; root `worktree: none`
stages (plan/objective-plan/save) do not. **Registry-missing = permissive** (fail-open) — chosen
deliberately to preserve implement linkage if the bundled registry ever fails to load.

## `resolveRunStage` recovery from handoff blob

The launched stage is recovered from the run's handoff blob (`handoff.stage`) via
`resolveRunStage(decision, cwd)`. Only `claim` (cold) and `keep` (reload) decisions have a settled
run with a handoff; **`fork`/`none` carry no launched stage** and must rely on the per-field LWW
rebuild (never re-read the cache file). This is the seam that gates `session_start` reconciliation.

## Fail-open on-land secondary bookkeeping pattern

Any "secondary bookkeeping after a merge" must copy this shape:

```
_consume_learn_on_land / _reconcile_objective_on_land shape:
  - Read the ref field
  - NEVER raise after merge — the merge already succeeded
  - Log loud-but-non-fatal to stderr on error
  - Capture a skipped_reason (not a raised exception)
  - Run only in the non-dry-run branch, after set_marker(PENDING_LEARN)
  - Set an inert update on dry-run
```

The merge must never be blocked by secondary bookkeeping.

## Schema extension gotcha: exact-dict assertions ripple

Adding a field to `PlanRef` / `PlanHeader.to_data()` **ripples into exact-equality assertions**
across the test suite. When `consumed_learn` was added, it broke three existing tests that assert
the full plan-ref dict (`test_implement_cmd`, `test_plan_save`, `test_resume`). Rules:

1. **Grep and update exact-dict assertions in the same turn** as the schema extension.
2. Thread the new field through `resume.reconstruct_plan_ref` so a fresh-clone resume still carries
   it.

## Cross-references

- `docs/learned/workflow/plan-factories.md` — how factories avoid consuming the plan-ref
- `shared/contracts.md` — cross-plane state contracts
