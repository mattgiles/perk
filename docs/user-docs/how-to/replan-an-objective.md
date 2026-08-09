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

1. **Replan it.** Run [`perk objective replan 42`](../reference/cli.md#perk-objective-replan-number),
   where `42` is the open objective's id. perk materializes the old objective's prose + its
   unfinished nodes and launches a read-only authoring session.
2. **Re-investigate.** Explore the current codebase — what shipped, what changed, what each
   unfinished node should become now. The materialized scratch also surfaces the objective's (and
   its node-issues') **human comments and description edits** as untrusted DATA.
3. **Author the net-new objective.** Draft the prose + structured roadmap carrying forward only the
   unfinished work; reference the completed phases in prose. On Linear, set each carried node's
   `adopt_issue` to its existing node-issue ref to move it across.
4. **Answer the delivery question again.** A replan re-asks the delivery choice (incremental
   recommended); a stacked successor reuses the predecessor's train lineage automatically.
5. **Review and save.** On approval, the save **closes the old objective** and creates the
   superseding one automatically — the `supersedes` link rides the run handoff; you never pass it by
   hand. The new objective's header carries `supersedes`, the old one gets `superseded_by`.
6. **Preview without launching (optional).** Add `--dry-run` to materialize the old objective and
   print the seed without opening a session: `perk objective replan 42 --dry-run`.

> **Don't churn.** If re-investigation finds nothing material changed, don't save — a replan that
> just re-states the old objective is not worth a new objective (and would needlessly close the old
> one).

---

← Back to the [how-to router](index.md).
