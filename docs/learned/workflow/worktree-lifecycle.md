---
title: Worktree filesystem lifecycle — batch ops over plan-<N> checkouts
read_when: You are writing a worktree-batch CLI command, matching git worktree paths, or your worktree test is unexpectedly dirty.
---

# Worktree filesystem lifecycle

perk worktrees are filesystem checkouts (`plan-<N>/`) created per worktree stage. Batch operations over
them — like `perk worktree wipe` (`perk/cli/commands/worktree_cmd.py`) — are a distinct concern from a
worktree's plan-ref *binding* role (see `plan-ref-lifecycle.md`). The mechanics below generalize to any
worktree-batch command.

## Worktree-candidate identification

Filter `git.worktree_list()` by **both**:

- `wt.path.parent.resolve() == worktree_root.resolve()`, **and**
- name matching `^plan-(\d+)$`.

**`.resolve()` on BOTH sides is mandatory** — git porcelain returns absolute paths and macOS
`/var`→`/private/var` symlinks otherwise mismatch. This filter naturally excludes the main repo
worktree (not under `worktree_root`) and any hand-created / non-numeric worktrees.

## Uncertainty ⇒ skip, never delete

Per-worktree PR-state lookup goes through `github.get_plan(number=...)`. Any `GitHubError`,
`state is None`, or `pr is None` **skips** that worktree. Consequence: the command does **not** call
`require_github`, so a fully-offline run is a safe no-op that skips everything — no hard auth gate.

## `--force` semantics are split

`--force` bypasses only the *local* safety guards (dirty tree / pending-learn not cleared); it
**never** relaxes the MERGED requirement. When forcing, `git.worktree_remove(..., force=True)` is
required so git itself doesn't refuse a dirty tree.

The pure `_classify_worktree(...) -> WipeDecision` helper encodes all of this and is unit-testable with
no I/O. **Push the decision into a pure classifier, keep I/O in the loop.**

## Branch deletion is best-effort

`git.delete_branch(repo, name, *, force=False)` uses `git branch -d` (safe; refuses unmerged) / `-D`
via the shared `_run` wrapper, so failures raise `GitError`. In the wipe loop a kept branch is
*reported*, never fatal.

## Exterior-only — no `shared/` change

Worktree lifecycle lives entirely in the Python plane. `wipe` is a plain CLI subcommand (not a stage),
emits plain text (no `--json`), and matches the rest of the `wt` family — so no
`contracts.md`/`registry.yaml` edit is needed (cli-vs-pi §2.2).

## Test-harness gotcha: `.pi/` makes a bare test repo dirty

`cache.set_marker(wt, cache.PENDING_LEARN)` writes into `.pi/workflow/markers/`, which makes the
worktree *dirty* in a bare test repo (where `.pi/` isn't gitignored). The dirty guard then fires
*before* the pending-learn guard and masks the intended assertion. **Fix in the test:** write `.pi/`
into the repo's `.git/info/exclude` to mirror what `perk init` gitignores in real repos, so the marker
is the sole signal under test.

## Cross-references

- `perk/cli/commands/worktree_cmd.py` — `wipe_worktrees`, `_classify_worktree`, `WipeDecision`, `_wipe_impl`
- `perk/git.py` — `delete_branch`, `worktree_remove`, `worktree_list`
- `docs/learned/workflow/plan-ref-lifecycle.md` — the plan-ref *binding* role of a worktree (distinct from filesystem batch ops)
