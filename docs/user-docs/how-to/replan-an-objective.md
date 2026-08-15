---
title: "How to replan an objective"
description: "Re-author a drifted objective as a net-new objective that supersedes and closes the old one, linked bidirectionally."
sidebar:
  order: 2150
sidebarGroup: "Objectives & learnings"
---

# How to replan an objective

Re-author an existing objective whose roadmap has drifted — some phases shipped, the remaining work
needs reshaping — as a **net-new objective that supersedes and closes the old one**. Unlike
[replanning an open plan](./replan-an-open-plan.md) (which rewrites the plan body *in place*),
objective-replan is **close-old / create-new**: perk's objective store is not an upsert, so the new
objective is created fresh, the old one is closed, and the two are linked bidirectionally.

This runs in a **read-only** authoring session and is **local-only**.

## What carries forward

- **Only the unfinished work.** Nodes still `pending` / `planning` / `in_progress` / `blocked`
  carry forward (reshaped as you see fit). Already-`done` (and `skipped`) nodes stay as **history on
  the closed old objective** — reference the shipped phases in your new prose; don't re-list them as
  roadmap nodes.
- **Linear node-issue identity is preserved.** On the Linear project backend, a carried node maps to
  its existing node-**issue** (via the node's `adopt_issue` field), and that issue is **moved** into
  the new objective — its open PRs and discussion travel with it. Dropped (un-carried) open
  node-issues are **Canceled**; `done` ones are left untouched. On GitHub (a single-issue objective)
  carried nodes are simply authored as fresh roadmap rows.

## Steps

1. **Replan it.** Run [`perk objective replan 42`](../reference/cli/objective.md#perk-objective-replan-number),
   where `42` is the open objective's id. perk materializes the old objective's prose + its
   unfinished nodes and launches a read-only authoring session.
2. **Re-investigate.** Explore the current codebase — what shipped, what changed, what each
   unfinished node should become now. The materialized scratch also surfaces the objective's (and
   its node-issues') **human comments and description edits** as untrusted DATA.
3. **Author the net-new objective.** Draft the prose + structured roadmap carrying forward only the
   unfinished work; reference the completed phases in prose. On Linear, set each carried node's
   `adopt_issue` to its existing node-issue ref to move it across.
4. **Answer the delivery question again (pre-publication only).** While nothing is published, a
   replan re-asks the delivery choice (incremental recommended); a stacked successor reuses the
   predecessor's train lineage automatically. Once a stacked predecessor has **published**
   layers, the delivery policy is immutable — the session doesn't re-ask, and the successor
   stays stacked (see below).
5. **Review and save.** On approval, the save **closes the old objective** and creates the
   superseding one automatically — the `supersedes` link rides the run handoff; you never pass it by
   hand. The new objective's header carries `supersedes`, the old one gets `superseded_by`.
6. **Preview without launching (optional).** Add `--dry-run` to materialize the old objective and
   print the seed without opening a session: `perk objective replan 42 --dry-run`.

> **Don't churn.** If re-investigation finds nothing material changed, don't save — a replan that
> just re-states the old objective is not worth a new objective (and would needlessly close the old
> one).

## Replanning a stacked objective (the transfer)

When the old objective delivers via a **stacked PR train**, the save runs a **transfer
protocol** instead of the plain close-old/create-new mutation: carried plans keep their
identity and move to the new objective, the train's published state is preserved exactly, and
the old objective closes only after the successor verifies. The authoring session's scratch
file spells out the constraints (a `<stacked_delivery_facts>` block); the save **enforces**
them:

- **The published prefix is immutable.** The successor's first delivery-order nodes must carry
  the already-published plans in exactly their current order — each exactly once, none dropped.
  Node ids and descriptions may change freely; the plan identities may not. Post-publication
  the delivery policy stays `stacked`, the base is fixed, and the train lineage carries
  automatically.
- **Plans with open PRs are mandatory-carry** — dropping one refuses the save until its PR is
  closed. Below the published prefix, everything else may be reshaped, reordered, or dropped
  freely.
- **Policy conversion is pre-publication only.** Converting stacked↔incremental refuses while
  any carried plan has an open PR (an existing PR already makes the layer published).

The transfer is **interruption-safe**: it journals a durable transfer manifest on the old
objective before touching anything, successor creation converges on the same save identity, and
the old objective closes last. Linear has one narrow residual: a crash after creating the
successor Project but before attaching its discoverable sentinel header can strand an **inert,
non-perk Project**. Nothing on the predecessor has been touched at that point, so retry remains
safe; the undiscoverable Project may need manual cleanup.

If a transfer is interrupted (crash, network), re-saving the same replan rolls it forward. Across
sessions, run
[`perk objective stack recover <old-objective-id>`](../reference/cli/objective.md#perk-objective-stack-recover-objective)
against the **predecessor** id. The bare command classifies first: an `all_after` transfer rolls
forward automatically; an `all_before` transfer is reported and requires a second
`--abandon` invocation plus confirmation to conclude; a mixed or corrupt transfer remains
report-only until its state is repaired. The door and save both print this predecessor-id remedy
when an unresolved transfer blocks replan.

## Related

- **Do:** [How to replan an open plan](replan-an-open-plan.md) — the plan-level analog: rewrite one
  plan body in place.
- **Do:** [How to recover a stacked delivery train](recover-a-stacked-train.md) — conclude an
  interrupted transfer from its symptom.
- **Look up:** [Objectives — the roadmap model](../reference/objectives.md) — supersedes lineage,
  node statuses, and the transfer constraints.
