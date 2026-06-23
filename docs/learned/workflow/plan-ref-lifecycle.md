---
title: plan-ref lifecycle and stage-gating
read_when: You are debugging plan-ref linkage, adding a new worktree stage, extending the PlanRef/PlanHeader schema, threading a non-default `base` branch (the resolve-once-then-pin model, base≠--base, the `--worktree NAME` returned-field-as-scratch clobber), or implementing on-land secondary bookkeeping.
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

**An always-emitted `to_data` field widens the ripple to the conformance fakes too.** A new field
that is *always* present (`base`, emitted as `base: null` when unset) broke three exact-dict-equality
assertions (`test_plan_save`, `test_objective_stores`, `test_implement_cmd`) AND the **ty-enforced
conformance fakes** (`_FakeObjectiveStore` etc. need the new kwarg or ty fails the whole suite). Add
`PLAN_HEADER_FIELDS`/`OBJECTIVE_HEADER_FIELDS` so the `update_*_header` unknown-key LBYL still
passes. Note: **"byte-identical" claims in such plans are about behavior, not bytes** — issue bodies
gain a `base: null` YAML line; safe because idempotency is `run_id`-keyed, not body-byte-compared.
**Per-backend persistence needs per-backend tests** — a plan changing both Linear `create_objective`
impls but only testing GitHub would let a dropped `base=base` ship green (caught in review). And
**fail-soft ≠ silent** — a fail-open resolver must still `print(..., file=sys.stderr)` (keeps `--json`
stdout clean).

## The cross-backend plan-ref clobber hazard (#621)

Running an objective-linked **`perk plan save --objective-id <uuid> --node-id <id>` inside an active
worktree** **overwrites that worktree's `.pi/workflow/plan-ref.json`** with the Linear node-issue ref
(e.g. `provider:linear, pr_id:PER-15`), silently replacing the worktree's own GitHub plan-ref. A
subsequent `/submit` then fails with a numeric-id error (`GitHub issue ids are numeric; got 'PER-15'`).
Because `plan-ref.json` is **gitignored** there is **no `git restore`** — reconstruct it via the cache
writer (the `objective_id` comes from the roadmap node's `pr:` backlink). **Lesson: never run a
cross-backend `plan save` inside an active worktree — it hijacks the active plan-ref.**

## Non-default `base` branch — resolve-once-then-pin (#636)

- **Part 1 needed no code.** "Default = the repo's GitHub default" already resolves via
  `github.default_branch` (PR base) and `detect_trunk_branch`
  (`git symbolic-ref refs/remotes/origin/HEAD`, worktree start-point). The only `"main"` literals
  were unreachable-remote fallbacks. The change was purely the additive **override**.
- **Resolve-once-then-pin.** `perk plan save` resolves the effective base a **single time** (linked
  objective's own `objective-header.base` → `[workflow] base` config → `None`) and writes it to
  BOTH `plan-header.base` (GitHub canonical) AND `cache.plan-ref.base` (local). **Pinning at save
  means a later config change never retargets an existing plan.** Three consumers READ the pinned
  value: `create_pr` (PR merge target), `launch.resolve_base` (worktree start-point:
  `trunk = plan_base or detect_trunk_branch`), and the `/submit` merge-conflict probe.
  `reconstruct_plan_ref` carries `base` from the canonical header so resume/remote recover it.
- **`base` (stored) ≠ `--base` (flag).** The stored `base` is the PR target + default trunk source;
  the pre-existing `implement`/`run-worker` `--base` flag is a one-off git start-point override for
  stacking that still wins the start-point VERBATIM (`base_override` short-circuits `resolve_base`
  before `plan_base`). Deliberately **no `--base` flag on `plan save`** — base is *derived*, never a
  free param, to avoid colliding with `implement --base`.
- **The regression caught by adversarial review, NOT tests (the headline).** `resolve_worktree`'s
  new explicit-`--worktree NAME` branch assigned `cache.read_plan_ref(repo_root)` to the
  **returned** `plan_ref` (previously `None`). Downstream `launch_stage` writes the returned ref
  into the named worktree, so a reuse-stage run (`submit`/`address`/`land`/`learn`) with
  `--worktree NAME` from the repo root would **clobber that worktree's own `cache.plan-ref`** with
  the active repo-root ref (and the `--dry-run --json` preview gained a stray `plan_ref` key). Fix:
  recover the base into a **separate local variable** (`base_ref`/`plan_base`), keep the returned
  `plan_ref = None`. **Lesson: when threading a new read through a shared resolver, never reuse the
  returned struct's field as scratch — use a dedicated local.** (Same clobber **family** as the
  cross-backend `plan save` hazard below — cross-linked.)
- **Residual cleanup flagged.** Three `review-*.md` files (`review-correctness.md`,
  `review-tests.md`, `review-maintainability-docs.md`) leaked onto `main` because adversarial
  reviewers were spawned with `output:` paths into the worktree root and a later `git add -A` swept
  them in. **Lesson: subagent `output:` paths land in the worktree and `git add -A` commits them —
  write reviewer artifacts to a tmp/gitignored path, or `git add` explicit paths, when a review runs
  mid-implementation.** (Follow-up: those three files were deleted from the repo in this change.)

## Cross-references

- `docs/learned/workflow/plan-factories.md` — how factories avoid consuming the plan-ref
- `shared/contracts.md` — cross-plane state contracts
