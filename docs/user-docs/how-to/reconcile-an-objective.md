---
title: "How to reconcile an objective manually"
description: "Re-sync an objective's roadmap prose to what actually landed when the automatic reconcile did not run or needs a redo."
sidebar:
  order: 2170
sidebarGroup: "Objectives & learnings"
---

# How to reconcile an objective manually

Re-sync an objective's roadmap **prose** to what actually landed — for the off-spine case where the
automatic `/land`-driven reconcile didn't run, or needs a redo.

## Steps

1. **Reconcile in a session (warm).** Inside a `pi` session, run
   [`/objective-reconcile [N]`](../reference/in-session/workflow-commands.md#objective-reconcile) (omit `N` to use the
   active objective). The agent rewrites **only** the Reconcilable prose region via the
   `reconcile_objective` tool.
2. **Or reconcile from the shell (cold).** Run
   [`perk objective reconcile N --body @FILE`](../reference/cli/objective.md#perk-objective-reconcile-number-alias-rec)
   (alias `perk objective rec`), supplying the replacement prose in a file; `--dry-run` composes
   without writing.

> **A genuinely-new node** can also be added during reconcile — via the `add_objective_node` tool
> (warm) or [`perk objective node-add`](../reference/cli/objective.md#perk-objective-node-add-number) (cold).
> Use it **sparingly**: only when the PR revealed a real new unit of work that the roadmap is
> missing — a deferred follow-up the plan/PR flagged, an uncovered defect or gap, a missing
> prerequisite for a later node, or human-requested work from the engagement block — never to
> restate or re-scope an existing node. Inserting into a **just-closed** objective is fine — and a
> **non-terminal** insertion **reopens the objective automatically** (roadmap incomplete ⇒ open,
> the mirror of land's close-on-complete). A **superseded** objective is the one exemption: dead
> lineage stays closed (`node-add` says so and skips the reopen).

> **Weighs human engagement too.** The warm pass auto-reads **human comments + description edits**
> on the objective and its node-issues (via
> [`perk objective engagement N`](../reference/cli/objective.md#perk-objective-engagement-number)) and folds
> that untrusted-DATA block into what may be stale — not only the merged diff. Humans may flag stale
> scope/naming/decisions in a comment or edit, not only in code. It is harmless/empty when there is
> no engagement.

> **Only the prose moves.** Reconcile rewrites the marker-bounded **Reconcilable** region wholesale.
> The roadmap **table** and any **Immutable** notes are structurally never touched. See
> [Objectives — the roadmap model](../reference/objectives.md) for which region is reconcilable.

> **Usually automatic.** When a merged plan is linked to an objective node,
> [`/land`](../reference/in-session/workflow-commands.md#land) auto-drives `/objective-reconcile` — so this manual
> path is for the off-spine or re-run case.

## Related

- **Do:** [How to advance or skip roadmap nodes manually](advance-or-skip-nodes.md) — fix a node's
  status itself, not the prose.
- **Do:** [How to check an objective for drift](check-an-objective-for-drift.md) — detect structural
  divergence beyond stale prose.
- **Look up:** [Objectives — the roadmap model](../reference/objectives.md) — which region is
  reconcilable and which is immutable.
