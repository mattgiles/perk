"""A thin ``git``-shelling gateway — the repo + worktree operations T4 needs.

One implementation per plane (cli-vs-pi §3); shells ``git`` via subprocess, never with
``shell=True``. Failures raise ``GitError``; the command layer translates them to
``UserFacingCliError``. LBYL: "is this a repo?" is answered by running ``rev-parse`` and
returning ``None`` on failure (the operation is the authoritative test).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Worktree:
    """One entry from ``git worktree list``."""

    path: Path
    branch: str | None
    head: str | None


class GitError(Exception):
    """A git command exited non-zero (translated to ``UserFacingCliError`` at the boundary)."""


class PushRejectedError(GitError):
    """A push was rejected as non-fast-forward / failed the ``--force-with-lease`` check."""


_REJECT_MARKERS = ("non-fast-forward", "[rejected]", "stale info", "failed to push some refs")


def _run(args: list[str], *, cwd: Path | None = None) -> str:
    # check=False: we inspect returncode ourselves to raise a domain GitError with stderr.
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def repo_root(cwd: Path) -> Path | None:
    """The repository root containing ``cwd``, or ``None`` if it is not a git repo."""
    try:
        out = _run(["rev-parse", "--show-toplevel"], cwd=cwd)
    except GitError:
        return None
    return Path(out.strip())


def current_branch(repo: Path) -> str | None:
    """The current branch name, or ``None`` if detached."""
    try:
        out = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    except GitError:
        return None
    branch = out.strip()
    return None if branch == "HEAD" else branch


def push(cwd: Path, branch: str, *, set_upstream: bool = True, force: bool = False) -> None:
    """Push ``branch`` to ``origin`` from ``cwd`` (the worktree).

    With ``force`` the push uses ``--force-with-lease`` (a no-op on a brand-new branch; it
    replaces a rewritten history safely on a perk-owned single-author plan branch). A
    non-fast-forward / lease rejection raises ``PushRejectedError``; other git failures raise
    ``GitError``.
    """
    args = ["push"]
    if force:
        args.append("--force-with-lease")
    if set_upstream:
        args += ["-u", "origin", branch]
    else:
        args += ["origin", branch]
    try:
        _run(args, cwd=cwd)
    except GitError as exc:
        msg = str(exc).lower()
        if any(marker in msg for marker in _REJECT_MARKERS):
            raise PushRejectedError(str(exc)) from exc
        raise


def is_dirty(cwd: Path) -> bool:
    """True if the worktree at ``cwd`` has uncommitted changes (tracked or untracked)."""
    return bool(_run(["status", "--porcelain"], cwd=cwd).strip())


def worktree_add(repo: Path, path: Path, *, branch: str, create_branch: bool) -> None:
    """Add a worktree at ``path``; create ``branch`` off HEAD when ``create_branch``."""
    if create_branch:
        _run(["worktree", "add", "-b", branch, str(path)], cwd=repo)
    else:
        _run(["worktree", "add", str(path), branch], cwd=repo)


def worktree_list(repo: Path) -> list[Worktree]:
    """All worktrees of ``repo`` (parsed from ``--porcelain``)."""
    return _parse_worktrees(_run(["worktree", "list", "--porcelain"], cwd=repo))


def worktree_remove(repo: Path, path: Path, *, force: bool) -> None:
    """Remove the worktree at ``path``."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    _run(args, cwd=repo)


def _parse_worktrees(porcelain: str) -> list[Worktree]:
    worktrees: list[Worktree] = []
    path: Path | None = None
    branch: str | None = None
    head: str | None = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line.startswith("HEAD "):
            head = line.removeprefix("HEAD ")
        elif line.startswith("branch "):
            branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        elif line == "" and path is not None:
            worktrees.append(Worktree(path, branch, head))
            path, branch, head = None, None, None
    if path is not None:
        worktrees.append(Worktree(path, branch, head))
    return worktrees
