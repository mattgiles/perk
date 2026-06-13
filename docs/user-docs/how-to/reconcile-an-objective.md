# How to reconcile an objective manually

Re-sync an objective's roadmap **prose** to what actually landed — for the off-spine case where the
automatic `/land`-driven reconcile didn't run, or needs a redo.

## Steps

1. **Reconcile in a session (warm).** Inside a `pi` session, run
   [`/objective-reconcile [N]`](../reference/in-session.md#objective-reconcile) (omit `N` to use the
   active objective). The agent rewrites **only** the Reconcilable prose region via the
   `reconcile_objective` tool.
2. **Or reconcile from the shell (cold).** Run
   [`perk objective reconcile N --body @FILE`](../reference/cli.md#perk-objective-reconcile-number-alias-rec)
   (alias `perk objective rec`), supplying the replacement prose in a file; `--dry-run` composes
   without writing.

> **Only the prose moves.** Reconcile rewrites the marker-bounded **Reconcilable** region wholesale.
> The roadmap **table** and any **Immutable** notes are structurally never touched. See
> [Objectives — the roadmap model](../reference/objectives.md) for which region is reconcilable.

> **Usually automatic.** When a merged plan is linked to an objective node,
> [`/land`](../reference/in-session.md#land) auto-drives `/objective-reconcile` — so this manual
> path is for the off-spine or re-run case.

---

← Back to the [how-to router](index.md).
