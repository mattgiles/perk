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


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 30) -> str:
    # check=False: we inspect returncode ourselves to raise a domain GitError with stderr.
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
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


def is_tracked(repo: Path, path: Path | str) -> bool:
    """Whether ``path`` (relative to ``repo``) is tracked in the index. Offline; never raises."""
    try:
        out = _run(["ls-files", "--", str(path)], cwd=repo)
    except GitError:
        return False
    return bool(out.strip())


def rm_cached(repo: Path, path: Path | str) -> None:
    """Stop tracking ``path`` without deleting the working-tree file (``git rm --cached``)."""
    _run(["rm", "--cached", "--quiet", "--", str(path)], cwd=repo)


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


def fetch(repo: Path, *, remote: str = "origin") -> None:
    """Fetch ``remote`` into ``repo`` (a **network** op; ``GitError`` on failure).

    Callers that need offline tolerance should treat the failure as best-effort. A longer
    ``timeout`` than the default is used because the network can be slow.
    """
    _run(["fetch", remote], cwd=repo, timeout=120)


def detect_trunk_branch(repo: Path, *, remote: str = "origin") -> str:
    """The repository's trunk branch name (mirrors erk's ``detect_trunk_branch``).

    (1) ``git symbolic-ref refs/remotes/<remote>/HEAD`` → strip the ``refs/remotes/<remote>/``
    prefix; (2) fallback — the first of ``main``/``master`` that exists as a local head;
    (3) final fallback ``"main"``. Each probe is local-only (no network) and a missing ref is
    swallowed rather than raised.
    """
    prefix = f"refs/remotes/{remote}/"
    try:
        out = _run(["symbolic-ref", f"{prefix}HEAD"], cwd=repo).strip()
        if out.startswith(prefix):
            return out.removeprefix(prefix)
    except GitError:
        pass
    for candidate in ("main", "master"):
        try:
            _run(["show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], cwd=repo)
            return candidate
        except GitError:
            continue
    return "main"


def remote_ref_exists(repo: Path, ref: str) -> bool:
    """Whether ``ref`` (e.g. ``origin/main``) resolves locally. Reads local refs only (no
    network) so it is offline-safe and dry-run-safe."""
    try:
        _run(["rev-parse", "--verify", "--quiet", ref], cwd=repo)
    except GitError:
        return False
    return True


def worktree_add(
    repo: Path, path: Path, *, branch: str, create_branch: bool, base: str | None = None
) -> None:
    """Add a worktree at ``path``; create ``branch`` when ``create_branch``.

    When ``create_branch`` and ``base`` is given, the new branch starts at ``base`` (a
    start-point ref, e.g. ``origin/main``); otherwise it starts at the repo's current HEAD.
    """
    if create_branch:
        args = ["worktree", "add", "-b", branch, str(path)]
        if base is not None:
            args.append(base)
        _run(args, cwd=repo)
    else:
        _run(["worktree", "add", str(path), branch], cwd=repo)


def delete_branch(repo: Path, name: str, *, force: bool = False) -> None:
    """Delete local branch ``name``. ``-d`` (safe: refuses an unmerged branch) unless ``force``."""
    flag = "-D" if force else "-d"
    _run(["branch", flag, name], cwd=repo)


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
