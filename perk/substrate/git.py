"""A thin ``git``-shelling gateway — the repo + worktree operations T4 needs.

One implementation per plane (cli-vs-pi §3); shells ``git`` via subprocess, never with
``shell=True``. Failures raise ``GitError``; the command layer translates them to
``UserFacingCliError``. LBYL: "is this a repo?" is answered by running ``rev-parse`` and
returning ``None`` on failure (the operation is the authoritative test).
"""

import os
import re
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

# `git branch -D|-d` writes `Deleted branch <name> (was <sha>).` per removed branch to stdout.
_DELETED_BRANCH_RE = re.compile(r"^Deleted branch (\S+)", re.MULTILINE)
# `git push <remote> --delete` writes ` - [deleted]         <branch>` per removed ref to stderr.
_DELETED_REMOTE_RE = re.compile(r"\[deleted\]\s+(\S+)")


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 30) -> str:
    # check=False: we inspect returncode ourselves to raise a domain GitError with stderr.
    # GIT_TERMINAL_PROMPT=0: credential prompts fail fast instead of hanging to the timeout.
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _run_capture(
    args: list[str], *, cwd: Path | None = None, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` best-effort: returns the completed process **without raising** on a
    non-zero exit so callers can parse stdout/stderr on partial failure.

    The sanctioned primitive for best-effort batch ops (``delete_branches`` /
    ``delete_remote_branches``); ``_run`` (which raises ``GitError``) remains the default for
    single ops. A ``TimeoutExpired`` is still exceptional and raises ``GitError``.
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out") from exc


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


def tracked_paths(repo: Path, pathspecs: list[str]) -> list[str]:
    """The tracked paths under ``pathspecs`` (relative to ``repo``); ``[]`` when clean.

    One ``git ls-files -- <pathspecs…>`` probe (sibling of ``is_tracked``, which takes a single
    path and swallows failures). Propagates ``GitError`` — callers decide how a failed probe
    degrades (no silent pass).
    """
    out = _run(["ls-files", "--", *pathspecs], cwd=repo)
    return [line for line in out.splitlines() if line]


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


def delete_branches(repo: Path, names: list[str], *, force: bool = False) -> list[str]:
    """Batched local branch delete: ``git branch -D|-d <names…>`` (one subprocess).

    Best-effort — never raises on a per-branch failure (a branch git refused or couldn't find
    simply won't appear in the returned list). Returns the branch names git confirmed deleted,
    parsed from the ``Deleted branch <name>`` stdout lines. Empty ``names`` is a no-op → ``[]``
    (no subprocess).
    """
    if not names:
        return []
    flag = "-D" if force else "-d"
    proc = _run_capture(["branch", flag, *names], cwd=repo)
    return _DELETED_BRANCH_RE.findall(proc.stdout)


def has_remote(repo: Path, name: str = "origin") -> bool:
    """Whether ``name`` is a configured remote of ``repo`` (``git remote``). Local, never raises."""
    proc = _run_capture(["remote"], cwd=repo)
    return name in proc.stdout.split()


def delete_remote_branches(
    repo: Path, names: list[str], *, remote: str = "origin", timeout: int = 120
) -> list[str]:
    """Batched remote branch delete: ``git push <remote> --delete <survivors…>`` (best-effort).

    ``git push --delete`` aborts the **whole** batch client-side if *any* ref is missing
    (``remote ref does not exist``) — and an already-gone ref is the common case (GitHub's
    auto-delete-on-merge). So we probe ``git ls-remote --heads`` once and delete only the refs
    that still exist (the already-gone ones are silently treated as success). Never raises: a
    total failure (offline / no perms / all refs already gone) yields ``[]``. Returns the branch
    names confirmed deleted, parsed from the ``[deleted]`` lines git writes to stderr. Empty
    ``names`` is a no-op → ``[]``. Callers should guard with ``has_remote`` so a remote-less repo
    is a clean no-op (uses a network ``timeout`` like ``fetch``).
    """
    if not names:
        return []
    probe = _run_capture(["ls-remote", "--heads", remote, *names], cwd=repo, timeout=timeout)
    existing = {
        line.split("refs/heads/", 1)[1]
        for line in probe.stdout.splitlines()
        if "refs/heads/" in line
    }
    survivors = [n for n in names if n in existing]
    if not survivors:
        return []
    proc = _run_capture(["push", remote, "--delete", *survivors], cwd=repo, timeout=timeout)
    return _DELETED_REMOTE_RE.findall(proc.stderr)


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
