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


def review_patch_path(checkout_path: Path) -> Path:
    """The stack checkout's combined-patch sibling: ``<checkout>.patch`` beside the checkout.

    A pure function of the checkout path — the ``<checkout>.patch`` convention both planes
    derive (the TS twin is ``patchPathFor``), so nothing carries the path and it can never
    disagree with the checkout. It lives BESIDE the checkout (never inside the untrusted
    checkout, never in a run-scoped scratch dir) and outside ``worktree wipe``'s ``plan-*``
    filter; the shared :func:`remove_review_worktree` removes it with the checkout.
    """
    return checkout_path.with_name(f"{checkout_path.name}.patch")


def remove_review_worktree(repo_root: Path, path: Path) -> bool:
    """Remove the review worktree at ``path`` and its ``<checkout>.patch`` sibling — the one
    removal implementation the checkout refresh, ``cleanup`` and the stale reaper share.

    A **registered** worktree goes through ``git.worktree_remove(force=True)`` (force: the
    checkout is disposable investigation material by construction — nothing legitimate writes
    there); an unregistered leftover dir falls to ``shutil.rmtree``. Always finishes with
    ``git.worktree_prune`` (the removal-fallback contract: a rmtree fallback leaves a stale
    admin entry behind). Returns True iff the worktree OR the patch was removed.
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
    patch = review_patch_path(path)
    if patch.exists():
        patch.unlink(missing_ok=True)
        removed = True
    return removed
