"""Cross-verb helpers for the ``perk pr review`` group."""

import shutil
from pathlib import Path

from perk.substrate import git


def review_worktree_name(pr_number: int) -> str:
    """The review checkout's worktree dir name (outside the ``plan-<N>`` namespace, so
    ``worktree wipe``'s ``^plan-(\\d+)$`` filter never sees it)."""
    return f"review-{pr_number}"


def review_temp_ref(pr_number: int) -> str:
    """The temp ref the head fetch pins into (``FETCH_HEAD`` is racy — a concurrent stage
    launch's best-effort fetch can clobber it between fetch and rev-parse)."""
    return f"refs/perk/review/{pr_number}"


def remove_review_worktree(repo_root: Path, path: Path) -> bool:
    """Remove the review worktree at ``path`` — the one removal implementation both verbs share.

    A **registered** worktree goes through ``git.worktree_remove(force=True)`` (force: the
    checkout is disposable investigation material by construction — nothing legitimate writes
    there); an unregistered leftover dir falls to ``shutil.rmtree``. Always finishes with
    ``git.worktree_prune`` (the removal-fallback contract: a rmtree fallback leaves a stale
    admin entry behind). Returns True iff anything was removed.
    """
    registered = any(w.path.resolve() == path.resolve() for w in git.worktree_list(repo_root))
    removed = False
    if registered:
        git.worktree_remove(repo_root, path, force=True)
        removed = True
    elif path.exists():
        shutil.rmtree(path)
        removed = True
    git.worktree_prune(repo_root)
    return removed
