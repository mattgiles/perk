---
title: "How to advance or skip roadmap nodes manually"
description: "Change a roadmap node's status by hand — skip, done, blocked, or back to pending — outside the automatic on-land path."
sidebar:
  order: 2160
sidebarGroup: "Objectives & learnings"
---

# How to advance or skip roadmap nodes manually

Change a roadmap node's status by hand — skip an obsolete node, mark one `done` or `blocked`, or
reset it to `pending` — outside the automatic on-land path that advances nodes for you.

This is **local-only** (a deterministic objective-storage write).

## Steps

1. **Find the node id.** Run
   [`perk objective show N --json`](../reference/cli.md#perk-objective-show-number-alias-s)
   and read the `nodes` array to find the node's id (the human-readable output prints only the
   status summary and next actionable node).
2. **Set the status.** Run
   [`perk objective node N --node <id> --status skipped`](../reference/cli.md#perk-objective-node-number)
   — substitute `done`, `blocked`, `pending`, `planning`, or `in_progress` for any status verbatim.
   Add `--pr "#456"` to set the plan backlink (or `--pr ""` to clear it); `--dry-run` validates
   without writing.
3. **Confirm.** Re-run `perk objective show N` to verify the new status.

> **Status is explicit-only.** A node's `status` is **never** inferred from its `--pr` backlink —
> setting `--pr` does not change the status, and vice versa.

> **Skip unblocks dependents.** `done` and `skipped` are the **terminal** statuses; skipping a node
> satisfies it as a dependency, so nodes waiting on it become plannable.

> **The warm tool gates `done`.** The in-session `objective_node` tool requires a completion
> `audit` when setting `status:"done"` and refuses without one; the cold `perk objective node` CLI
> has **no** such gate. See [Objectives — the roadmap model](../reference/objectives.md) for the
> full status model.

## Related

- **Do:** [How to reconcile an objective manually](reconcile-an-objective.md) — re-sync the roadmap
  prose after the status change.
- **Do:** [How to advance an objective with the run supervisor](advance-an-objective-headlessly.md)
  — the supervised one-safe-step path instead of a hand edit.
- **Look up:** [Objectives — the roadmap model](../reference/objectives.md) — the full status model
  and terminal semantics.
