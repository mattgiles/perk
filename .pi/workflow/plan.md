I've verified the bug doc against the code. Every claim holds: `git.push` (`perk/git.py:59`) is plain with no force; `_pr_submit_impl` (`perk/cli/commands/pr_submit_cmd.py`) calls `git.push(repo_root, branch)` unconditionally; `find_pr_for_branch`/`create_pr` are idempotent; there's **no** `is_dirty`/`status`/`fetch` helper anywhere in `perk/`. One correction to fold in: the bug doc's fix #5 calls for `scripts/verify-*.sh`, but `AGENTS.md` now mandates pytest/node:test for regression coverage (no bespoke verify scripts; `scripts/` doesn't even exist).

Here is the finalized plan.

---

# Plan: fix re-`/submit` on rewritten history (force-with-lease re-push + commit-first guard)

## Problem & status (verified)

Re-`/submit` works only for *appended* commits. When the plan branch's history is **rewritten** (amend / squash / rebase) — the common case after addressing feedback, and the *guaranteed* case once the stale-base bug is fixed by rebasing onto `origin/main` — the push is rejected non-fast-forward and `perk pr-submit` dies with a raw `GitError`. Secondarily, a dirty worktree silently fails to update the PR (only the committed ref is pushed).

Verified against current code:
- `perk/git.py` — `push(cwd, branch, *, set_upstream=True)` runs `git push [-u] origin <branch>` with **no force, no divergence handling**. There is **no `fetch`, no `status`/`is_dirty`, no `PushRejectedError`** in this module.
- `perk/cli/commands/pr_submit_cmd.py` — `_pr_submit_impl` calls `git.push(repo_root, branch)` unconditionally; the top-level handler maps `git.GitError` → `error_type="git_error"` with `message="git push failed\n{exc}"` (raw stderr). No dirty-tree check.
- `perk/github.py` — `find_pr_for_branch` (`:829`, `state=all`, prefers open) + `create_pr` are idempotent, so PR detection/reuse already works. `default_branch` (`:818`) resolves the base. **These are not the bug** and must not change.
- `extension/submit.ts` — `submitPr` delegates to `perk pr-submit --json`, never reimplements GitHub writes (D1). It surfaces `error`/`error_type` from the worker JSON. The guard must live in the worker, not be duplicated here.

## Key design insight (resolves the open `--force-with-lease` question)

The bug doc flags an open question: `--force-with-lease` can fail in worktrees where the remote-tracking ref is stale, "may need a `git fetch` first." **This does not apply to perk's submit path, and no fetch is needed**, because:

- perk plan branches (`plan-<n>`) are **perk-owned and single-author** — one worktree implements one plan.
- The **first** submit pushes with `git push -u origin <branch>`, which sets the remote-tracking ref `refs/remotes/origin/<branch>` to exactly what we pushed.
- On a later re-submit after a local rewrite, `--force-with-lease` (implicit, no explicit value) compares origin against that remote-tracking ref. Since only this worktree pushes this branch, the ref still reflects current origin → the lease **passes for our own rewrite** and correctly **rejects if origin moved unexpectedly** (the safety we want) — with **no fetch**.
- `--force-with-lease` on a brand-new branch (no remote ref yet) is a **no-op** — the push creates the ref normally. So it is safe to apply uniformly on the submit push.

Therefore: **always use `--force-with-lease` on the submit push, no fetch, no escalation logic.** This keeps first-push behavior (decision #2), fixes rewrites (decision #1), and preserves teammate safety.

Out of scope / noted: a *fresh-clone resume* (branch exists on origin but this worktree never pushed it, so its remote-tracking ref is absent/stale) could hit a `stale info` lease failure. Contracts already place remote-branch resume in **Phase 2** ("recreating one from a remote branch on a fresh clone is Phase 2"). When that lands it can add a targeted `git fetch origin <branch>` before the lease. Mention this in the contract amendment; do not build it now.

Coupling: this fix is **independent of and lands before/independently of** the stale-base/rebase fix (`implement-branches-off-stale-local.md`). It is correct on its own; the stale-base fix merely makes divergent re-submits routine.

## Changes

### 1. `perk/git.py` — add `force` to `push`, add a `PushRejectedError`

- Add an exception subclass next to `GitError`:
  ```python
  class PushRejectedError(GitError):
      """A push was rejected as non-fast-forward / failed the --force-with-lease check."""
  ```
- Add `force: bool = False` to `push`:
  ```python
  def push(cwd: Path, branch: str, *, set_upstream: bool = True, force: bool = False) -> None:
      args = ["push"]
      if force:
          args.append("--force-with-lease")
      if set_upstream:
          args += ["-u", "origin", branch]
      else:
          args += ["origin", branch]
      _run(args, cwd=cwd)
  ```
- Make `push` translate a rejection into `PushRejectedError` instead of a bare `GitError`. Because `_run` raises `GitError` on non-zero, wrap the call in `push` (not in `_run`, which is shared): catch `GitError`, and if its message matches a rejection signature, re-raise as `PushRejectedError`. Match case-insensitively on any of: `non-fast-forward`, `[rejected]`, `stale info`, `failed to push some refs`. Otherwise re-raise the original `GitError`.

  ```python
  _REJECT_MARKERS = ("non-fast-forward", "[rejected]", "stale info", "failed to push some refs")
  ...
  try:
      _run(args, cwd=cwd)
  except GitError as exc:
      msg = str(exc).lower()
      if any(m in msg for m in _REJECT_MARKERS):
          raise PushRejectedError(str(exc)) from exc
      raise
  ```

### 2. `perk/git.py` — add a dirty-tree probe

Add a helper used by the commit-first guard (no such helper exists today):
```python
def is_dirty(cwd: Path) -> bool:
    """True if the worktree at ``cwd`` has uncommitted changes (tracked or untracked)."""
    return bool(_run(["status", "--porcelain"], cwd=cwd).strip())
```
(Matches the contracts' `git status --porcelain` dirty-check idiom referenced for `session_before_fork`.)

### 3. `perk/cli/commands/pr_submit_cmd.py` — guard, force, and map rejection

In `_pr_submit_impl`, **before** `git.push`:
- **Commit-first guard.** After resolving `branch`/`issue` and confirming not-dry-run, check `git.is_dirty(repo_root)`; if dirty, raise:
  ```python
  raise UserFacingCliError(
      "Uncommitted changes in this worktree\n"
      "Commit your changes before submitting — uncommitted work isn't pushed.",
      error_type="dirty_tree",
  )
  ```
  (`UserFacingCliError` is already imported and already routed to exit 1 with its `error_type`.)
- **Force the re-push.** Change the call to:
  ```python
  git.push(repo_root, branch, force=True)
  ```
  (Auto-force is safe and correct per the design insight — perk-owned plan branch, `--force-with-lease`, no-op on first push.)

In the top-level `pr_submit` handler's `except` chain:
- Add an `except git.PushRejectedError as exc:` arm **before** the existing `except git.GitError`, mapping to a stable, actionable error:
  ```python
  except git.PushRejectedError as exc:
      _fail(
          ctx, as_json=as_json, error_type="push_rejected",
          message=(
              "Push rejected — the remote branch moved unexpectedly.\n"
              "Fetch/rebase onto the latest origin and re-submit.\n" + str(exc)
          ),
      )
      return
  ```
  Keep the existing `except git.GitError` arm (`error_type="git_error"`) as the fallback for non-rejection git failures.

`extension/submit.ts` needs **no change** — it already forwards `error`/`error_type` from the worker JSON; `dirty_tree` and `push_rejected` flow through `details.error_type` and the user-facing message automatically.

### 4. Update tool guidelines wording (optional, low-risk)

In `extension/submit.ts`, the `TOOL_GUIDELINES` already say "Call submit only after the implementation is committed." The worker now *enforces* this; no edit required, but the existing guideline is now accurate (leave as-is).

## Tests (the gate — pytest, per AGENTS.md, **not** `scripts/verify-*.sh`)

> Correction to the bug doc: fix #5 proposed `scripts/verify-*.sh` with a fake-git harness. `AGENTS.md` now mandates regression coverage live in the pytest / node:test suites run by `just test` / gated by `just ci`; `scripts/` does not exist. Use real-git tests (strongest, matches the empirical repro) and existing monkeypatch stubs.

### `tests/test_git.py` — real bare-remote rewrite repro (new tests)

Use a local **bare** repo as `origin` (no network). Pattern:
- Build a fixture: init a work repo with one commit, `git init --bare` a remote dir, `git remote add origin <bare>`, then `git.push(work, "plan-x")` (first push, plain — succeeds, sets upstream).
- **Test first push is plain & succeeds:** assert `git.push(work, branch)` (default `force=False`) succeeds against a fresh bare remote.
- **Test rewrite + plain push is rejected:** `git commit --amend`, then `git.push(work, branch, force=False)` raises `git.PushRejectedError` (the empirical repro).
- **Test rewrite + force-with-lease succeeds:** after the same amend, `git.push(work, branch, force=True)` succeeds and the bare remote's `plan-x` now points at the amended commit (assert via `git --git-dir=<bare> rev-parse plan-x`).
- **Test `is_dirty`:** clean tree → `False`; create/modify an unstaged file → `True`.

### `tests/test_pr_submit.py` — guard, push args, rejection mapping (extend existing)

The existing `_stub_gh` stubs `git.push` as a recorder. Extend:
- **Dirty-tree refusal:** monkeypatch `git.is_dirty` → `True`; run `pr-submit --json`; assert exit 1 and `error_type == "dirty_tree"`, and that `calls["pushed"]` is `False` (guard fires before push). (Default the existing happy-path stubs to `git.is_dirty` → `False`.)
- **Submit force-pushes:** change `_push` stub to capture kwargs; assert the worker calls `git.push(..., force=True)` on the normal submit path.
- **`push_rejected` mapping:** monkeypatch `git.push` to raise `git.PushRejectedError("... non-fast-forward ...")`; run; assert exit 1 and `error_type == "push_rejected"` with the actionable message (not raw `git_error`).
- Keep existing tests green (they only assert `pushed is True` / header / body — add `git.is_dirty` → `False` to the shared stub so they don't trip the new guard).

## Contract amendment (same turn)

Amend `shared/contracts.md` in the **submit section** (around the P2.T8a submit block, near lines 595–630 / the `pr-submit` narrative at ~700–748):
- State that `perk pr-submit` **force-pushes the perk-owned plan branch with `--force-with-lease`** (auto-force; no-op on first push), because plan branches are single-author and expected to diverge after amend/squash/rebase.
- State the **commit-first guard**: submit refuses on a dirty worktree (`error_type: dirty_tree`) — uncommitted work isn't pushed.
- State the new stable `error_type: push_rejected` mapping for non-fast-forward / lease failures (actionable message, not raw git stderr).
- Note the **Phase-2 caveat**: a fresh-clone resume (remote branch with no local remote-tracking ref) may need a `git fetch origin <branch>` before the lease; deferred with remote-resume.

## Out of scope / explicitly deferred
- The stale-base/rebase fix (`implement-branches-off-stale-local.md`) and `git.fetch` — separate bug; this fix is correct without it.
- Fresh-clone remote-resume lease handling — Phase 2.
- Any change to `find_pr_for_branch` / `create_pr` (already idempotent) or to the warm `extension/submit.ts` delegation.

## Execution order
1. `perk/git.py`: `PushRejectedError`, `force` param + rejection mapping, `is_dirty`.
2. `tests/test_git.py`: bare-remote repro tests.
3. `perk/cli/commands/pr_submit_cmd.py`: dirty guard, `force=True`, `push_rejected` arm.
4. `tests/test_pr_submit.py`: guard / force-args / rejection-mapping tests + stub `is_dirty=False`.
5. `shared/contracts.md`: submit-section amendment.
6. `just ci` green.

---

Note: I'm in read-only mode and the `plan_save` tool / `/plan off` aren't available to me here — toggle plan mode off and invoke `plan_save` with the markdown above (or tell me and I'll proceed once the tool is available).
