# Bug: `implement` branches off stale local HEAD — never fetches/bases on `origin`

**Status:** confirmed, unfixed
**Surfaced:** during dogfooding — `perk implement` starts work in a dedicated worktree branched off
whatever is checked out locally, even when `origin/main` has moved ahead.
**Severity:** real correctness/workflow bug. In any flow where `origin` advances between plans
(i.e. always, on a team or across multiple PRs), implementation starts from superseded code.

## Symptom

When `perk implement` materializes the dedicated worktree, it creates the new branch off the local
repo's current `HEAD`. It does **not** `git fetch`, does **not** base the branch on `origin/<trunk>`,
and does **not** pull/rebase. If your local `main` is behind `origin/main`, the implementation
worktree is born stale — you build on old code, and only discover the divergence at submit/land time.

## Root cause

The worktree-creation primitive bases the branch off local `HEAD` with no remote sync:

```python
# perk/git.py:69-72
def worktree_add(repo: Path, path: Path, *, branch: str, create_branch: bool) -> None:
    """Add a worktree at ``path``; create ``branch`` off HEAD when ``create_branch``."""
    if create_branch:
        _run(["worktree", "add", "-b", branch, str(path)], cwd=repo)
```

`git worktree add -b <branch> <path>` creates `<branch>` from the repo's **current local HEAD**.
It is called from the implement/launch path:

```python
# perk/launch.py:124-130 (resolve_worktree)
if stage.worktree == "create":
    if path.exists():
        pass  # D4: idempotent reuse (resume)
    elif materialize:
        git.worktree_add(repo_root, path, branch=name, create_branch=True)
```

There is **no `git fetch` anywhere in perk.** `perk/git.py` has `push` but no `fetch`; nothing in the
codebase references `origin/main`, `merge-base`, `rebase`, or a trunk/default branch. So the base of
every implementation branch is purely whatever the local checkout happens to be — there is no
mechanism to even *detect* that the local base is stale.

## Consequences

- **Builds on superseded code.** Work starts from an old tree; can re-introduce already-fixed bugs or
  duplicate work that landed since the local checkout.
- **Deferred conflict pain.** Divergence surfaces only at `/submit` or `/land` (squash-merge), far
  from where it could be cheaply resolved.
- **Misleading diffs/CI.** Review and CI compare the PR against a stale base, so the diff includes (or
  conflicts with) changes already on trunk.
- **Worse the longer `origin` has moved** — exactly the team / multi-plan / objective-driven flow perk
  is built for.

## Comparison with erk

erk is origin-aware when it places worktrees (`src/erk/cli/commands/wt/create_cmd.py`):
- it **detects the trunk branch** (`detect_trunk_branch`) and refuses to make a worktree *for* trunk
  (trunk stays in the root worktree),
- when a branch exists on the remote it **creates a local tracking branch off `origin/<branch>`**
  (`create_tracking_branch(..., f"origin/{branch}")`),
- it accounts for repo state like mid-rebase before proceeding.

perk ported the worktree mechanic but dropped all of the origin-awareness — it never fetches and
always bases off local HEAD.

## Fix sketch (decisions pending)

The core change: on **create** (not reuse), fetch and base the new branch on the up-to-date trunk.

1. **Add `git.fetch` + trunk detection.** `perk/git.py` gains a `fetch(repo, remote="origin")` and a
   default-branch resolver (e.g. `git symbolic-ref refs/remotes/origin/HEAD`, or config). perk has
   neither today.
2. **Base the implement branch off `origin/<trunk>`.** Extend `worktree_add` (or `resolve_worktree`)
   so create-branch does `git worktree add -b <branch> <path> origin/<trunk>` after a fetch — instead
   of bare `-b` off HEAD.
3. **Create-only, never reuse.** The fetch/rebase must run only on the `materialize` create path
   (`launch.py:127`); the idempotent reuse/resume path (`path.exists()` → D4) must **not** rebase an
   in-progress worktree under the user.
4. **Remote branch already exists (remote/resumed plans).** If the plan's branch is already on
   `origin` (e.g. a remote implement), base off `origin/<branch>` as a tracking branch (erk's
   behavior), not off trunk.
5. **Offline / network-failure handling.** `fetch` is a network op. Decide the contract: best-effort
   fetch that **warns loudly and falls back to local** when offline (so airplane-mode still works),
   vs. hard-failing. Given perk's offline-gate discipline, best-effort-with-a-loud-warning is the
   likely answer — but the warning must be *visible*, because silent-off-local is precisely this bug.
   (Note: the cold worker stays offline-testable via `--dry-run` / a faked git; the live fetch is a
   dogfood/manual concern.)
6. **Contract + gate.** Amend `shared/contracts.md` (the implement/worktree section) to state the base
   is `origin/<trunk>` after fetch; add `scripts/verify-*.sh` coverage (a fake-git harness asserting
   create does fetch + bases off `origin/<trunk>`, and reuse does not fetch).

**Open questions:**
- **Trunk detection** — perk has no notion of a default branch yet; `origin/HEAD` symbolic-ref vs.
  `.pi/perk.toml` config vs. `git remote show`.
- **Rebase vs. fresh base.** For a brand-new branch, basing off `origin/<trunk>` *is* the fresh start
  (no rebase needed). A separate "my worktree fell behind mid-implementation" sync is a distinct,
  later feature — don't conflate it with create-time basing.
- **Stacked work.** If a user deliberately wants to branch off local (stacking on an unlanded
  branch), basing off trunk would break that — likely a `--base` escape hatch, defaulting to
  `origin/<trunk>`.

## References

- perk: `perk/git.py:69-72` (`worktree_add` — off local HEAD), `perk/launch.py:124-130`
  (`resolve_worktree` create path), `perk/cli/commands/implement_cmd.py` (the implement launcher);
  no `fetch` / `origin/<trunk>` / `merge-base` anywhere in `perk/`.
- erk: `src/erk/cli/commands/wt/create_cmd.py` (trunk detection, `origin/<branch>` tracking branch,
  mid-rebase handling).
