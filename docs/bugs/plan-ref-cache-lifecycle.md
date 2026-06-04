# Bug: Root plan-ref cache leaks stale plan context into fresh planning sessions

**Status:** confirmed, design pending
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

## Proposed direction

Fresh main-worktree planning stages should not inherit stale root `cache.plan-ref`.

A likely fix:

- On real cold launches for stages that do not read `cache.plan-ref` and run in the main worktree,
  clear the root selector before `exec pi`. This includes `plan`, `objective-plan`, and likely
  `save`.
- Do not clear the selector on dry run.
- Do not clear the selector for `implement`, `submit`, `address`, `land`, or `learn`.
- Gate extension `session_start` reconciliation so it only imports `cache.plan-ref` when the
  launched stage actually requires or reads `cache.plan-ref`.
- Preserve LWW rebuild behavior for already-linked sessions and tree navigation.

## Open questions

- Should `perk plan` always clear root `plan-ref.json`, or should it only skip reconciliation while
  leaving the selector available for no-arg `perk implement`?
- Is clearing at `plan` enough, or should cold `save` also clear stale refs before a new plan is
  saved?
- Do we need a first-class "resume planning" flow for an existing saved plan, distinct from
  `perk resume <plan>` routing to the next implementation stage?
- Should the contract rename or further clarify `cache.plan-ref` as selector state, or is a contract
  amendment enough?

## Regression test shape

- With a root `plan-ref.json` present, `perk plan` launches without producing `active_plan_ref`.
- `perk plan --dry-run` does not mutate the cache.
- `perk implement` with no plan id still consumes root `plan-ref.json`.
- `perk implement <id>` and `perk resume <id>` still rewrite/select the requested plan.
- A worktree-local implementation launch still reconciles its materialized plan-ref into
  `active_plan_ref`.

