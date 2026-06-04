# Bug: re-`/submit` fails on rewritten history — `git push` is plain (no force/divergence handling)

**Status:** confirmed (empirically reproduced), unfixed
**Surfaced:** during dogfooding — `/submit` a PR, make local changes, `/submit` again to update the
PR.
**Severity:** real workflow bug. Re-submit works only for *appended* commits; it **fails** whenever
the branch history was rewritten (amend / squash / rebase), which is the common case after addressing
feedback — and becomes routine once the stale-base bug
([`implement-branches-off-stale-local.md`](./implement-branches-off-stale-local.md)) is fixed by
rebasing onto fresh `origin/main`.

## What was expected

After a first `/submit`, make changes in-session, then `/submit` again: it should detect the existing
PR and push the new code so the PR is updated.

## What was confirmed (the precise behavior)

The premise needs refining — part of this **already works**, and the real defect is narrower:

- **Existing-PR detection works.** `find_pr_for_branch` (`perk/github.py:815`) queries
  `head=<owner>:<branch>` with `state=all` and prefers an open PR, so `create_pr`
  (`perk/github.py:855-860`) idempotently **returns the existing PR** — no duplicate, no GitHub 422.
  The warm path even reports it (`extension/submit.ts:87` → "Found existing draft PR #N").
- **The push is unconditional.** `_pr_submit_impl` always calls `git.push(repo_root, branch)`
  (`perk/cli/commands/pr_submit_cmd.py`), so **newly-appended commits do update the PR**. For the
  simple "added more commits" case, re-`/submit` works.

So the bug is **not** "submit doesn't detect the PR / doesn't push." The bug is:

- **The push is plain and non-force.** `git.push` runs `git push -u origin <branch>` with no
  `--force-with-lease` and no divergence handling (`perk/git.py:59-67`). When the branch history was
  **rewritten** — `git commit --amend`, an interactive squash, or a rebase onto fresh `origin/main` —
  the push is **rejected (non-fast-forward)** and `perk pr-submit` dies with a raw `GitError`. The PR
  is never updated, and the failure is opaque.

### Empirical reproduction

```
# branch pushed once, then history rewritten (amend) — like addressing review / rebasing:
$ git commit --amend -m "impl v1+v2"
$ git push -u origin plan-5            # exactly what perk git.push does (no --force)
 ! [rejected]        plan-5 -> plan-5 (non-fast-forward)
error: failed to push some refs to 'origin'
# exit code: 1  →  perk pr-submit raises GitError, submit fails
```

### Secondary sharp edge

Uncommitted changes are never pushed (the branch ref is what's pushed). A re-`/submit` with
uncommitted work silently does **not** update the PR — the user must commit first. The submit tool's
guideline says "call only after the implementation is committed," but nothing enforces it on the
`/submit` path, so "I made changes and submitted but the PR didn't update" is a real confusion.

## Why it bites now (and will bite more)

- **Addressing review** routinely amends/squashes/rebases → re-submit rejected.
- **Rebasing onto fresh trunk** (the right fix for the stale-base bug) **always** rewrites the
  branch relative to what was pushed → *every* re-submit after a rebase would be rejected. The two
  bugs are coupled: fixing stale-base without fixing the push makes re-submit fail more, not less.

## Comparison with erk

erk's submit pipeline expects plan branches to diverge and **auto-forces** the push
(`src/erk/cli/commands/pr/submit_pipeline.py`):

```python
# Auto-force for plan implementations (branches always diverge from remote).
effective_force = state.force or is_plan_impl
...
push(state.cwd, "origin", state.branch_name, set_upstream=True, force=state.force)
```

It also detects divergence (`divergence.behind > 0`, `divergence.is_diverged`) and surfaces a clear
"use `erk pr submit -f`" path. perk ported the push but dropped force support, divergence detection,
and the plan-impl auto-force.

## Fix sketch (decisions pending)

1. **Force-push plan-impl branches safely.** Add `force` to `git.push` and use
   **`--force-with-lease`** (not bare `--force`) for the submit re-push so a teammate's concurrent
   push isn't clobbered. The submit path knows it's a perk plan branch, so it can force by default
   (erk's `is_plan_impl` auto-force) — these branches are perk-owned and expected to diverge.
2. **Keep first-push behavior.** A brand-new branch push needs no force; `--force-with-lease` is a
   no-op when there's nothing to overwrite, so it's safe to use uniformly, or gate force on "the
   branch already exists on origin."
3. **Commit-first guard.** On `/submit` (warm) and the worker, fail clearly when the worktree is
   dirty ("commit your changes before submitting — uncommitted work isn't pushed") instead of
   silently pushing only the committed ref. (Mirrors the lifecycle-gate dirty-tree discipline.)
4. **Surface divergence, don't dump a raw GitError.** Map a non-fast-forward rejection to a stable
   `error_type` (e.g. `push_rejected`) with an actionable message, rather than the raw git stderr.
5. **Contract + gate.** Amend `shared/contracts.md` (the submit section) to state the re-push uses
   `--force-with-lease` for the plan branch; add `scripts/verify-*.sh` coverage with a fake-git
   harness asserting: first submit pushes plain; a divergent re-submit force-pushes (with-lease);
   dirty tree refuses.

**Open questions:**
- **`--force-with-lease` vs `--force`.** Lease is safer (rejects if origin moved unexpectedly) but
  can itself fail in worktree setups where the remote-tracking ref is stale — may need a `git fetch`
  first (ties into the stale-base fix) so the lease is evaluated against current `origin`.
- **Default-force scope.** Auto-force only the perk-owned `plan-*` branch (safe), never an arbitrary
  branch.
- **Coupling.** Land this together with (or right after) the stale-base/rebase fix, since that fix is
  what makes divergent re-submits the norm.

## References

- perk: `perk/git.py:59-67` (`push` — plain, no force), `perk/github.py:815-842`
  (`find_pr_for_branch`, `state=all`), `perk/github.py:855-860` (`create_pr` idempotent),
  `perk/cli/commands/pr_submit_cmd.py` (`_pr_submit_impl` — unconditional `git.push`),
  `extension/submit.ts` (warm `/submit` delegates; reports `existed`).
- erk: `src/erk/cli/commands/pr/submit_pipeline.py:275-329,446-466` (auto-force for plan impls,
  divergence detection, `-f`).
