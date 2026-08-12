---
title: "How to resume a plan at its current stage"
description: "Re-enter an in-flight plan from a cold shell at whatever lifecycle stage it left off."
sidebar:
  order: 2020
sidebarGroup: "Core workflow"
---

# How to resume a plan at its current stage

Re-enter an in-flight plan from a cold shell, picking it back up at whatever lifecycle stage it
left off — with **fresh context**, not a kept-alive session. Use this after a break, on a different
machine, or any time you want a clean session against an existing plan.

## Steps

1. **Find the plan id.** A plan is a GitHub issue; its id is what you resume by. List candidates
   with `gh issue list` (or inspect the local cache with
   [`perk state show`](../reference/cli.md#perk-state-show-alias-s)). The id may be a bare number
   (`42`), a hash form (`#42`), or a backend key like `ENG-123`.
2. **Resume it.** Run [`perk plan resume 42`](../reference/cli.md#perk-plan-resume-plan). perk
   resolves the plan's current stage, positions the right worktree, and launches a fresh `pi`
   session primed to continue from there. What resume resolves to:

   | Plan state | Resume does |
   | --- | --- |
   | No PR yet | Launches `implement`. |
   | PR open with actionable review feedback | Launches `address`. |
   | PR merged, learn pending | Launches `learn`. |
   | PR open as a **draft** | Reports the gate: mark it ready, then `/land`. |
   | PR open, clean | Reports the gate: awaiting human review. |
   | PR closed unmerged | Reports the gate: needs your attention (reopen or replan). |
   | PR merged and learned | Reports done — nothing to resume. |

   The gate rows are **named, not launched** — when the next step is yours (a review, a land, a
   decision about a closed PR), resume tells you so instead of opening a session at the wrong
   stage.

   When a **local** resume relaunches `implement` into a plan worktree that already exists (for
   example after an earlier session was interrupted), prior work — committed or uncommitted —
   *may* already be present there. The launched session is explicitly advised of that and told to
   check `git log`/`git status` and reconcile its checklist before starting — you don't need to
   brief it yourself. A `--remote` resume (step 4) never carries the advisory.
3. **Preview without launching (optional).** Add `--dry-run` to print the resolved outcome without
   opening a session — handy to confirm *where* a plan will resume before committing to it:
   `perk plan resume 42 --dry-run`.
4. **Dispatch to CI (optional).** Add `--remote` to run the resumed stage on a CI runner instead of
   locally: `perk plan resume 42 --remote`. Only the unattended stages (`implement`, `address`) are
   remotely runnable. For the
   fuller recipe, see [How to dispatch a stage to a remote runner](dispatch-a-stage-to-ci.md).

Why fresh context rather than a continued conversation? Because the plan is canonical in GitHub and
every stage is re-enterable through its cold door. That includes a **merged** plan's learn step:
whether learning is still pending (or was captured/skipped) is read from the plan itself, so resume
resolves it correctly from any machine or a fresh clone — see
[How perk thinks → Stages and doors](../explanation/how-perk-thinks.md#stages-and-doors-how-you-move-through-the-workflow).

> **Resume vs. replan.** `resume` *continues* the plan at its current stage. To rewrite the plan
> body itself before it lands, use [How to replan an open plan](replan-an-open-plan.md) instead.

---

← Back to the [how-to router](index.md).
