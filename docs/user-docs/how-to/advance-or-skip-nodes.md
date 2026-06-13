# How to advance or skip roadmap nodes manually

Change a roadmap node's status by hand — skip an obsolete node, mark one `done` or `blocked`, or
reset it to `pending` — outside the automatic on-land path that advances nodes for you.

This is **local-only** (a deterministic objective-storage write).

## Steps

1. **Find the node id.** Run
   [`perk objective show N`](../reference/cli.md#perk-objective-show-number-alias-s) (alias
   `perk objective s N`), where `N` is the objective issue id, to list the nodes and their ids.
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

---

← Back to the [how-to router](index.md).
