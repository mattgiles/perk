---
title: "How to recover a dirty worktree"
description: "Get unblocked when uncommitted changes block a submit or a worktree wipe, with the right recovery move for each."
sidebar:
  order: 2110
sidebarGroup: "Core workflow"
---

# How to recover a dirty worktree

Get unblocked when uncommitted changes are in the way. A dirty worktree blocks you in two concrete
places:

- **Submitting** — `perk pr submit` refuses with `dirty_tree`: *"Commit your changes before
  submitting — uncommitted work isn't pushed."* Nothing local is pushed, so an uncommitted change
  would silently not ship.
- **Wiping** — `perk worktree wipe` removes only merged plan worktrees. A merged-PR dirty
  worktree is skipped with *"uncommitted changes (use --force)"*; an unmerged worktree is skipped
  as *"PR is …, not merged"*, and a run that cannot reach the issue backend skips PR-gated
  candidates as *"could not determine PR state (…)."*

perk commits as it implements, so a dirty tree usually means an in-progress edit you can finish or
set aside.

Both frictions trace to one boundary: uncommitted changes are **outside perk's cross-machine
durability contract**. Durable state is the saved plan plus pushed branches; committing (and
submitting/pushing) is what promotes local WIP into the durable tier. See
[How perk thinks → stages and doors](../explanation/how-perk-thinks.md#stages-and-doors-how-you-move-through-the-workflow)
for the boundary definition.

## Steps

1. **See what's there.** Inspect the worktree with `git status` and `git diff` so you know whether
   the changes are worth keeping.
2. **To keep the work — commit or stash it.** Commit the changes as a coherent unit (then
   `/submit` / `perk pr submit` will proceed), or set them aside with `git stash` to restore later.
3. **To discard the work — confirm the refusal, then force removal.** First run
   [`perk worktree remove NAME`](../reference/cli/remote-and-utility.md#perk-worktree-remove-name-alias-rm). A dirty
   worktree refuses with `git worktree remove failed: … use --force`; that is your last checkpoint
   to confirm the changes are expendable. Then run `perk worktree remove NAME --force` to remove
   that worktree, or [`perk worktree wipe --force`](../reference/cli/remote-and-utility.md#perk-worktree-wipe) to clean
   up all merged plan worktrees.

## Recover a retained submit-conflict lock

Both `resolve_submit_conflicts` and retained resolution inside `objective_stack_sync` report the
exact `perk-submit-conflict.lock` path inside the target's per-worktree Git directory (for retained
mode, the retained worktree — never the parent's checkout). A busy lock excludes every other
participating resolver even when it is old, empty, malformed or records a dead PID. A retained lock
means termination was uncertain. Reload, process exit, a counter reset or clearing an
authorization never unlock it.

Recovery is **human-only**: quiesce every session that can use the worktree and prove the writer
**and its subprocesses** stopped (PID death is not enough); inspect the exact reported path and the
worktree's rebase/index/HEAD state (cancellation never rolled back a finished rebase or push);
remove that exact regular file, nothing else; then decide repair, canonical `/submit` (PR mode) or
a separately approved `objective_stack_sync {continue:true}` (retained mode).

The stacked `<manifest>.resolver-lock` **session claim** is different — reclaimable under its own
policy, and never a bypass of the execution lock.

A follow-up **delivery is unconfirmed** diagnostic preserves the settled result (receipt, lock
disposition, untrusted report JSON) after rendering or sending failed; stop for human direction.

## Watch out

- `--force` is **destructive** — it removes the worktree (and its uncommitted changes) for good.
  Make sure anything you care about is committed or stashed first.
- `perk worktree wipe` only ever removes **merged** `plan-<N>` worktrees. The `--force` flag bypasses
  the *dirty/pending-learn* safety guards; it does **not** relax the merged requirement, so an
  unmerged worktree is never wiped, even with `--force`. One carve-out: **residue dirs** —
  unregistered `plan-*` dirs with no `.git` gitlink, i.e. not worktrees at all — are swept
  regardless of PR state; the merged requirement continues to govern every real worktree and
  every branch deletion (including stranded local `plan-*` branches, which wipe deletes only
  when their PR is merged).
- `wipe` deletes each wiped worktree's local branch **and** its remote branch on `origin`
  (best-effort — an already-deleted remote branch is tolerated, and an offline run just skips the
  remote step). `perk worktree remove NAME` only removes the single worktree's checkout.

## Related

- **Do:** [How to diagnose a perk repo](diagnose-a-perk-repo.md) — the health check to run when
  the snag is not just uncommitted changes.
- **Look up:** [Remote and utility commands](../reference/cli/remote-and-utility.md) — exact
  `perk worktree remove` and `perk worktree wipe` syntax, guards, and sweeps.
- **Understand:** [How perk thinks](../explanation/how-perk-thinks.md) — the durability boundary
  that makes uncommitted work local-only.
