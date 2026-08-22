---
title: "How to drive a change through the full spine"
description: "Walk one change plan all the way along perk's spine — plan, save, implement, submit, land, learn."
sidebar:
  order: 2010
sidebarGroup: "Core workflow"
---

# How to drive a change through the full spine

Walk one change plan all the way along perk's **spine** — *plan → save → implement → submit →
(address) → land → learn* — staying in-session where the warm door exists and stepping out to a
cold shell where it does not. This is the reliable step sequence for an operator who already knows
perk. (First time? The [Get started tutorial](../tutorials/get-started.md) *teaches* the same path
hands-on on a throwaway repo; this guide is the map, not the lesson.)

## The spine, end to end

1. **Author and save the plan.** Draft in a read-only authoring session — warm
   [`/plan`](../reference/in-session/workflow-commands.md#plan) from inside a running session, or cold
   [`perk plan`](../reference/cli/plan.md#perk-plan) for a fresh shell. Approve the plan to save it to
   the issue backend (the read-only → read-write boundary); the manual save failsafe is warm
   [`/plan-save`](../reference/in-session/workflow-commands.md#plan-save), and the cold save worker is
   [`perk plan save`](../reference/cli/plan.md#perk-plan-save). *Trivial change?* The lightweight
   alternative is [`/implement-here`](../reference/in-session/workflow-commands.md#implement-here) (also offered as
   a review verdict): exit plan mode **without** saving an issue and implement the reviewed draft
   right in the current session — skipping the rest of the spine (no issue, no worktree, no PR).
2. **Implement — cold only.** Run [`perk implement`](../reference/cli.md#perk-implement-plan-alias-impl)
   from your shell. This stage has **no warm door**: it must run in a *fresh* session and cannot
   inherit the planning conversation. That is deliberate context hygiene — see
   [How perk thinks → Stages and doors](../explanation/how-perk-thinks.md#stages-and-doors-how-you-move-through-the-workflow)
   for why implement is cold-only. perk creates the worktree, branches, and primes a clean session
   against the saved plan body.
3. **Submit the result.** From inside the implement session, run warm
   [`/submit`](../reference/in-session/workflow-commands.md#submit) once the work is committed — it pushes the
   branch and opens a draft PR. The cold worker is [`perk submit`](../reference/cli.md#perk-submit).
4. **Mark it ready.** Run warm [`/ready`](../reference/in-session/workflow-commands.md#ready) to move the draft PR
   to ready-for-review — the deliberate review gate. (Stacked layers differ: review happens on
   the draft, and `/ready` is the post-review handoff — see
   [How to review a stacked train](review-a-stacked-train.md).) It does not run CI — run
   [`/ci`](../reference/in-session/workflow-commands.md#ci) first.
5. **Address feedback (conditional).** If a reviewer leaves feedback, run warm
   [`/address`](../reference/in-session/workflow-commands.md#address). This step is optional — you only enter it
   when there is feedback to respond to. See
   [How to address review feedback on a PR](address-review-feedback.md).
6. **Land it.** Once approved, run warm [`/land`](../reference/in-session/workflow-commands.md#land) to merge the
   PR, reconcile, and set the pending-learn marker. Cold worker:
   [`perk land`](../reference/cli.md#perk-land).
7. **Capture the learning.** Run warm [`/learn`](../reference/in-session/workflow-commands.md#learn) to record
   durable learnings from the landed change (or skip it when nothing is durable — the skip is
   recorded on the plan too). Either outcome is canonical in the issue backend, so a merged
   plan's learned-vs-pending state survives machine switches and fresh clones.
   [`perk learn pending`](../reference/cli/learn-and-gist.md#perk-learn-pending) lists landed plans still
   awaiting this step. Cold worker: [`perk learn`](../reference/cli/learn-and-gist.md#perk-learn).

## Detours off the spine

Each of these has its own recipe — follow the link when you hit that situation:

- Re-entering an in-flight plan from a cold shell → [How to resume a plan at its current stage](resume-a-plan.md).
- Responding to reviewer feedback → [How to address review feedback on a PR](address-review-feedback.md).
- Rewriting a saved-but-unlanded plan against the current codebase → [How to replan an open plan](replan-an-open-plan.md).
- Running the project's configured checks in-session → [How to run CI checks in a session](run-ci-in-session.md).
- Getting unblocked when uncommitted changes are in the way → [How to recover a dirty worktree](recover-a-dirty-worktree.md).
- Tracking step-by-step implement progress → [How to track implement progress](track-implement-progress.md).

## Related

- **Learn:** [Get started with perk](../tutorials/get-started.md) — the hands-on first walk along this same path, on a throwaway repo.
- **Look up:** [Workflow commands](../reference/in-session/workflow-commands.md) — the exact semantics of every warm command on the spine.
- **Understand:** [How perk thinks](../explanation/how-perk-thinks.md) — why the stages exist and which doors are warm or cold.
