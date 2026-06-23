"""pi's git-package extension-clone lifecycle: status, lock, and in-place materialize."""

import contextlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Literal

from perk.convergence.init.settings import GIT_PACKAGE
from perk.substrate import git

fcntl: ModuleType | None
try:
    import fcntl as _fcntl

    fcntl = _fcntl
except ImportError:  # pragma: no cover - non-POSIX (perk dev platforms are macOS/Linux)
    fcntl = None


def consumer_git_clone_root(repo_root: Path) -> Path:
    """The root of pi's git-package clone for perk, derived from ``GIT_PACKAGE``.

    pi clones a ``git:`` package to ``.pi/git/<host>/<path>`` (docs/packages.md). Deriving the
    path from ``GIT_PACKAGE`` (rather than hardcoding segments) keeps every consumer of the clone
    location — the run-worker entrypoint resolver — in lockstep with the package URL, so a URL
    change cannot silently desync them.
    """
    remainder = GIT_PACKAGE.removeprefix("git:")
    clone = repo_root / ".pi" / "git"
    for segment in remainder.split("/"):
        clone = clone / segment
    return clone


ExtensionCloneStatus = Literal["self", "absent", "fresh", "stale", "unverifiable"]


def extension_clone_status(repo_root: Path, *, self_repo: bool) -> tuple[ExtensionCloneStatus, str]:
    """Classify the freshness of pi's git-package clone for perk + a human detail string.

    pi loads perk's extension from ``consumer_git_clone_root(repo_root)`` but never
    self-advances a present project-scoped ``git:`` clone (verified in pi's
    ``resolvePackageSources``), so a clone first created at an old commit stays frozen. perk
    owns the freshness check:

    - ``self`` — the self-repo uses the local ``..`` package, so there is no clone.
    - ``absent`` — the clone dir does not exist; pi re-clones fresh at ``main`` on the next launch.
    - ``fresh`` / ``stale`` — the clone ``HEAD`` equals / differs from ``origin/main``.
    - ``unverifiable`` — HEAD or the remote tip is unreadable (offline / broken clone); never a
      silent pass.
    """
    if self_repo:
        return "self", "self-repo uses the local '..' package — no git clone"
    clone = consumer_git_clone_root(repo_root)
    if not clone.is_dir():
        return "absent", "pi clones fresh at main on next launch"
    # perk always pins its own package at `@main` (`_desired_packages` writes
    # `f"{GIT_PACKAGE}@main"`), so `origin/main` is the correct freshness comparison ref.
    local = git.head_sha(clone)
    remote = git.ls_remote_sha(clone, "refs/heads/main")
    if local is None or remote is None:
        return "unverifiable", "clone HEAD or origin/main tip unreadable — offline?"
    if local == remote:
        return "fresh", local
    return "stale", f"clone HEAD {local[:8]} != origin/main {remote[:8]}"


def _extension_clone_url() -> str:
    """The HTTPS URL pi clones perk's extension from, derived from ``GIT_PACKAGE``.

    pi turns a ``git:github.com/<path>`` package spec into ``https://github.com/<path>`` for the
    clone (verified against the consumer clone reflog's ``clone: from https://github.com/...``
    line). Deriving it from ``GIT_PACKAGE`` keeps the URL single-sourced (no second hardcode).
    """
    return "https://" + GIT_PACKAGE.removeprefix("git:")


@contextlib.contextmanager
def _extension_clone_lock(repo_root: Path) -> Iterator[None]:
    """Hold an exclusive cross-process lock while materializing perk's extension clone.

    Acquires ``fcntl.flock(LOCK_EX)`` on ``<repo_root>/.pi/git/.perk-extension-clone.lock``. The
    lock file lives in the clone's **parent** (``.pi/git/``, already gitignored) so a reclone /
    ``rm -rf`` of the clone dir never removes the lock. On a platform without ``fcntl`` (non-POSIX),
    degrades to a no-op lock (best-effort; perk's supported dev platforms are macOS/Linux).
    """
    git_dir = repo_root / ".pi" / "git"
    git_dir.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover - non-POSIX
        yield
        return
    lock_path = git_dir / ".perk-extension-clone.lock"
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _clone_extension_fresh(clone: Path, url: str) -> None:
    """Materialize a fresh clone at ``clone`` (no ``npm install`` — zero runtime deps).

    Creates the clone's parent dir, ``git clone <url> <clone>``, then checks out ``main`` for
    parity with the ``@main`` pin (idempotent — a fresh clone already checks out the default
    branch). Raises ``GitError`` on any git failure (callers swallow it as best-effort).
    """
    clone.parent.mkdir(parents=True, exist_ok=True)
    git.clone(url, clone)
    git.reset_hard(clone, "main")


def _freshen_extension(clone: Path) -> None:
    """In-place freshen of an existing clone: ``fetch origin`` then ``reset --hard origin/main``.

    No ``npm install`` (zero runtime deps). Raises ``GitError`` (callers swallow it).
    """
    git.fetch(clone, remote="origin")
    git.reset_hard(clone, "origin/main")


def materialize_extension_clone(repo_root: Path, *, self_repo: bool) -> str | None:
    """Materialize pi's git-package clone for perk **in place**, under a cross-process lock.

    The full version used by init/doctor: re-checks ``extension_clone_status`` under the lock and
    converges the clone forward — clone-if-absent, ``fetch``+``reset``-if-stale, no-op otherwise.
    Best-effort + **non-fatal**: a ``GitError`` (flaky network) is swallowed and reported in the
    returned message, never raised — init/doctor and especially a launch must not fail on it.
    Returns a human-readable change line **only when it actually changed something** (absent →
    cloned, stale → freshened, or a swallowed error worth surfacing); ``None`` for a genuine no-op
    (``self`` / ``fresh`` / offline ``unverifiable``) so a converged re-run reports no change.
    """
    if self_repo:
        return None
    clone = consumer_git_clone_root(repo_root)
    rel = clone.relative_to(repo_root)
    with _extension_clone_lock(repo_root):
        status, _detail = extension_clone_status(repo_root, self_repo=self_repo)
        try:
            if status == "absent":
                _clone_extension_fresh(clone, _extension_clone_url())
                return f"{rel}: cloned fresh main (perk-owned, no npm install)"
            if status == "stale":
                _freshen_extension(clone)
                return f"{rel}: freshened to origin/main in place (no npm install)"
            # fresh / unverifiable (offline): leave a present clone for pi to load (nothing to do
            # if absent + offline) — a genuine no-op, reported as no change.
            return None
        except git.GitError as exc:
            return f"{rel}: clone materialize failed (non-fatal): {exc}"


def ensure_extension_clone_present(repo_root: Path, *, self_repo: bool) -> str | None:
    """Cheap launch hot-path guarantee that perk's extension clone **exists** (no freshness).

    ``self_repo`` → ``None``. If the clone dir already exists → ``None`` fast (**no network, no
    ``ls-remote``**) — the norm after init/doctor. Else, under the lock, **re-check** ``is_dir()``
    (double-checked locking so concurrent launches clone exactly once) and clone fresh if still
    absent. A ``GitError`` is swallowed (returns ``None``, non-fatal). Returns a change line only
    when it actually cloned. Shares the lock + clone primitive with ``materialize_extension_clone``.
    """
    if self_repo:
        return None
    clone = consumer_git_clone_root(repo_root)
    if clone.is_dir():
        return None
    rel = clone.relative_to(repo_root)
    with _extension_clone_lock(repo_root):
        if clone.is_dir():  # double-checked: a racing launch already cloned it
            return None
        try:
            _clone_extension_fresh(clone, _extension_clone_url())
        except git.GitError:
            return None
        return f"{rel}: cloned fresh main pre-launch (perk-owned, no npm install)"
