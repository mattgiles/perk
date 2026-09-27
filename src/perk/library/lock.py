"""The machine-local library lock (contracts.md §8.74(c)).

One exclusive, non-blocking ``flock`` serializes every catalog read-modify-write and entry
directory mutation on this machine; ``list`` and the crawl-into-staging phase stay lock-free.
The lock file lives in the MAIN checkout's workflow cache (``.perk/workflow/library.lock``), so
every worktree contends on one file.

This is the twin of ``perk.delivery.oplock`` (the same guarded-``fcntl`` shape); a shared
non-blocking flock primitive under ``perk.substrate`` is a deferred extraction. Unlike the
oplock, acquisition failures other than contention are translated to ``io_error``.
"""

import contextlib
import errno
from collections.abc import Iterator
from io import TextIOWrapper
from pathlib import Path
from types import ModuleType

from perk.library.errors import LibraryError, LibraryLockBusy, translating_io
from perk.state import cache
from perk.substrate import git

fcntl: ModuleType | None
try:
    import fcntl as _fcntl

    fcntl = _fcntl
except ImportError:  # pragma: no cover - non-POSIX (perk dev platforms are macOS/Linux)
    fcntl = None

LIBRARY_LOCK_FILENAME = "library.lock"

# flock(LOCK_NB) reports contention as EWOULDBLOCK (== EAGAIN on macOS/Linux).
_CONTENTION_ERRNOS = frozenset({errno.EWOULDBLOCK, errno.EAGAIN})


def lock_path(repo_root: Path) -> Path:
    """Where the lock file lives (present or not), anchored at the MAIN checkout."""
    main_root = git.main_worktree_root(repo_root) or repo_root
    return cache.workflow_dir(main_root) / LIBRARY_LOCK_FILENAME


def lock_rel() -> str:
    """The lock file's path relative to a checkout root, POSIX (the ignore-probe form)."""
    return (cache.workflow_dir(Path()) / LIBRARY_LOCK_FILENAME).as_posix()


@contextlib.contextmanager
def library_lock(repo_root: Path) -> Iterator[None]:
    """Hold the exclusive machine-local library lock for the ``with`` body.

    Non-blocking: a held lock raises :class:`LibraryLockBusy` immediately (never a silent
    wait). Creating the lock file's parent or opening it failing is ``io_error``. On a platform
    without ``fcntl`` the lock degrades to a no-op.
    """
    path = lock_path(repo_root)
    with translating_io("library lock"):
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a")
    with handle:
        _acquire(handle, path)
        try:
            yield
        finally:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _acquire(handle: TextIOWrapper, path: Path) -> None:
    if fcntl is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _CONTENTION_ERRNOS:
            raise LibraryLockBusy(
                "another perk librarian operation holds the machine-local library lock at "
                f"{path} — wait for it to finish and rerun"
            ) from exc
        raise LibraryError("io_error", f"library lock: {exc}") from exc
