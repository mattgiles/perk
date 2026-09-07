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

`resolve_submit_conflicts` reports the exact `perk-submit-conflict.lock` path inside the canonical
**per-worktree Git directory** (`git rev-parse --absolute-git-dir`). A busy lock excludes another
participating submit/address resolver, even when it is old, empty, malformed, or records a dead
PID. A retained lock means termination was uncertain; an ownership/I/O error also requires
inspection. Reload, process exit, resetting an attempt counter, or clearing pending authorization
never unlocks it. Separate linked worktrees have separate locks.

Recovery is **human-only**, in this order:

1. Stop or quiesce **every session** capable of using this worktree. Establish that the native
   writer **and its subprocesses** are stopped. PID death alone is not enough; do not race a live
   owner or rely on elapsed time.
2. Inspect the exact reported path without following a symlink. Confirm it is the expected
   regular lock file, and inspect its device/inode identity and schema-1 owner metadata (PID,
   session/run/request ids, canonical worktree identity and creation time).
3. Inspect `git status`, the rebase-in-progress state, index and HEAD in that worktree. Preserve
   any valuable unresolved work. A cancellation may have happened after a rebase or push; it did
   not roll those operations back.
4. **Only after quiescence and inspection**, remove that exact regular lock file. Do not use
   recursive removal or replace it while a participant is active. If its identity changed, stop
   and investigate rather than removing the replacement.
5. Decide whether the worktree needs repair, verification, or canonical `/submit`. Lock cleanup
   itself is not permission to abort, rebase or push. If uncertainty remains, leave the lock.

There is no model-callable unlock, automatic stale cleanup or recovery CLI. This file coordinates
Perk's code-owned submit/address resolver launches only; it does not fence arbitrary manual Git
commands. The stacked retained-continuation session claim is a different mechanism and keeps its
own consent/continuation rules.

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
