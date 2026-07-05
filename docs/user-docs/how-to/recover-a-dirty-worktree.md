# How to recover a dirty worktree

Get unblocked when uncommitted changes are in the way. A dirty worktree blocks you in two concrete
places:

- **Submitting** — `perk pr submit` refuses with `dirty_tree`: *"Commit your changes before
  submitting — uncommitted work isn't pushed."* Nothing local is pushed, so an uncommitted change
  would silently not ship.
- **Wiping** — `perk worktree wipe` skips a dirty worktree with *"uncommitted changes (use
  --force)."*

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
3. **To discard the work — remove the worktree with `--force`.** Remove one worktree with
   [`perk worktree remove NAME --force`](../reference/cli.md#perk-worktree-remove-name-alias-rm), or
   clean up all merged plan worktrees with
   [`perk worktree wipe --force`](../reference/cli.md#perk-worktree-wipe).

## Watch out

- `--force` is **destructive** — it removes the worktree (and its uncommitted changes) for good.
  Make sure anything you care about is committed or stashed first.
- `perk worktree wipe` only ever removes **merged** `plan-<N>` worktrees. The `--force` flag bypasses
  the *dirty/pending-learn* safety guards; it does **not** relax the merged requirement, so an
  unmerged worktree is never wiped, even with `--force`.
- `wipe` deletes each wiped worktree's local branch **and** its remote branch on `origin`
  (best-effort — an already-deleted remote branch is tolerated, and an offline run just skips the
  remote step). `perk worktree remove NAME` only removes the single worktree's checkout.

---

← Back to the [how-to router](index.md).
