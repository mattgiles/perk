---
title: "How to address review feedback on a PR"
description: "Classify reviewer feedback on a plan's PR, fix the actionable items, and resolve the threads — then re-ready and land."
sidebar:
  order: 2030
sidebarGroup: "Core workflow"
---

# How to address review feedback on a PR

Classify reviewer feedback on a plan's PR, fix the actionable items, and resolve the threads —
then re-ready and land. Use this when a reviewer has left comments on the draft/ready PR.

**Prerequisite:** a PR with reviewer feedback to respond to. (`address` is the conditional step on
the spine — you only enter it when there is feedback.)

## Steps

1. **Open the session.** Stay in the submit/implement session if it is still live, or open a fresh
   one with cold [`perk address [PLAN]`](../reference/cli.md#perk-address-plan) (the stage
   launcher). From the repository root, `perk address 1699` selects the plan explicitly (id,
   `#id`, or the pasted issue URL) — no need to `cd` anywhere first: a missing `plan-<id>`
   worktree is restored from the plan's remote branch automatically. Omit the id inside a plan
   worktree to address that worktree's own plan. Arguments for `pi` go after a bare `--`, e.g.
   `perk address 1699 -- --model provider/model`.
2. **Run the address door.** Run warm [`/address`](../reference/in-session.md#address). perk
   classifies the feedback in an isolated child session, then the parent fixes the actionable
   items and batch-resolves the threads.
3. **Classify only, take no action (optional).** Run `/address --preview` to see the classification
   without fixing or resolving anything — useful to triage before committing to changes.
4. **Review and let perk resolve.** Confirm the classification, let perk apply the fixes and resolve
   the addressed threads.
5. **Re-ready and land.** Once the feedback is addressed and committed, run warm
   [`/ready`](../reference/in-session.md#ready) to put the PR back in front of the reviewer, then
   warm [`/land`](../reference/in-session.md#land) once it is approved.

> **On a stacked plan?** Feedback on a lower layer of a stacked PR train is addressed exactly the
> same way — `/address` fixes it, and the automatic cascade rewrites the published layers above the
> fix. See [How to review a stacked PR train](./review-a-stacked-train.md).

## Related

- **Do:** [How to drive a change through the full spine](drive-the-full-spine.md) — where the address step sits on the way to landing.
- **Do:** [How to review a stacked PR train](review-a-stacked-train.md) — addressing feedback on a layer of a stacked train.
- **Look up:** [In-session commands & tools](../reference/in-session.md) — the exact `/address` semantics and preview mode.
