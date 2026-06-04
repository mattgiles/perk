# Bug: Root plan-ref cache leaks stale plan context into fresh planning sessions

**Status:** resolved (#43 — TS-only stage-gated reconciliation; no clearing, no registry/Python change)
**Surfaced:** after PR #41 / plan #40, when a later `perk plan` appeared to resume stale context.
**Severity:** workflow confusion. A fresh read-only planning session can look bound to an old saved
plan.

## Symptom

Launching a new planning session from the main worktree with `perk plan` can inherit a stale
`active_plan_ref` from `.pi/workflow/plan-ref.json`.

Observed case: the main worktree cache still pointed at GitHub issue `#40`. A later `perk plan`
launched from that same worktree reconciled the cached ref into the session's `perk:workflow-state`,
so the session looked attached to plan `#40` instead of starting fresh.

This was noticed after PR #41, but the PR's code change only swept stale Pi lockfiles before exec.
The stale plan linkage is caused by older `cache.plan-ref` semantics.

## Root cause

`cache.plan-ref` currently carries two meanings:

1. **Root-worktree selector:** the plan that no-arg `perk implement` should consume.
2. **Session linkage source:** the file the extension reconciles into `active_plan_ref` on
   `session_start`.

Those meanings conflict for planning. Planning usually happens in the main worktree and is
read-only; implementation happens in dedicated `plan-<id>` worktrees. Multiple agents should be able
to plan concurrently from the main worktree without inheriting a previous implementation selector.

The extension currently reads `ctx.cwd/.pi/workflow/plan-ref.json` on every `session_start` and
appends `active_plan_ref` when the rebuilt branch state differs. It does not distinguish `plan` /
`objective-plan` / `save` sessions from implementation workflow sessions.

## Working model

GitHub is the canonical history of saved plans.

The root `.pi/workflow/plan-ref.json` should be treated as a mutable active selector, not canonical
history. It supports workflows like:

- `plan_save` saves plan `#N` and writes the root selector.
- `perk implement` with no plan id consumes the current root selector.
- `perk implement <N>` and `perk resume <N>` explicitly select a plan and rewrite the selector.
- Implementation launches materialize their own `plan-ref.json` into the dedicated `plan-<N>`
  worktree.

The implementation worktree's plan-ref is the workflow binding. The root plan-ref is only the
current selector.

## Resolution (#43)

Fixed **TS-only**, by stage-gating the extension's `session_start` reconciliation — **no clearing**,
no `registry.yaml` change, no Python change.

- The extension reconciles `cache.plan-ref` → `active_plan_ref` **only when the launched stage
  consumes the ref** (its registry `requires`/`reads` list `cache.plan-ref`). That is exactly the
  worktree binding stages (`implement`/`submit`/`address`/`land`/`learn`); the root `worktree: none`
  stages (`plan`/`objective-plan`/`save`) do not consume it and so never inherit the stale root
  selector.
- The launched stage is read from the run's **handoff** blob (`stage`): `claim`/`keep` sessions have
  a settled run; `fork`/`none` carry no launched stage and never re-read the file.
- Already-linked sessions, fork-inherited refs, and tree navigation are preserved via the LWW
  rebuild (the file is never re-read for those paths). Registry-missing stays permissive when a
  stage is present, to keep implement linkage working.
- **Why not clear the selector?** Gating alone fixes the symptom and satisfies all five regression
  items; clearing at `plan` would break no-arg `perk implement` resuming the last save. The selector
  self-heals at the next `save`.

Key code: `extension/registry.ts` (`stageConsumesPlanRef`), `extension/workflowState.ts`
(`resolveRunStage`), `extension/index.ts` (the stage-gated reconciliation block); contract amended in
`shared/contracts.md` §8.1 (selector/binding duality) + §8.3 (stage-gated reconciliation).

## Resolved open questions

- **`perk plan` clear vs skip reconciliation?** Skip reconciliation; leave the selector available for
  no-arg `perk implement`. No clearing.
- **Should cold `save` also clear stale refs?** No — `save` rewrites the selector anyway; gating is
  sufficient.
- **First-class "resume planning" flow?** Out of scope — a separate feature, not needed for this fix.
- **Rename/clarify `cache.plan-ref` as selector state?** A contract amendment (§8.1 duality) is
  enough; no rename.

## Regression test shape

- With a root `plan-ref.json` present, `perk plan` launches without producing `active_plan_ref`.
- `perk plan --dry-run` does not mutate the cache.
- `perk implement` with no plan id still consumes root `plan-ref.json`.
- `perk implement <id>` and `perk resume <id>` still rewrite/select the requested plan.
- A worktree-local implementation launch still reconciles its materialized plan-ref into
  `active_plan_ref`.

