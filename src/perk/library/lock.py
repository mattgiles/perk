"""The machine-local library lock (contracts.md §8.75(c)).

One exclusive, non-blocking ``flock`` serializes every catalog read-modify-write and entry
directory mutation on this machine; ``list`` and the crawl-into-staging phase stay lock-free.
The lock file lives in the MAIN checkout's workflow cache (``.perk/workflow/library.lock``), so
every worktree contends on one file.

This is the twin of ``perk.delivery.oplock`` (the same guarded-``fcntl`` shape); a shared
non-blocking flock primitive under ``perk.substrate`` is a deferred extraction. Unlike the
oplock, the lock file is opened without following a symlink (the ignore probes evaluate its
pathname, not a link target), and acquisition failures other than contention are translated to
typed refusals.
"""

import contextlib
import errno
import os
import stat
from collections.abc import Iterator
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
# Never follow a symlinked lock path (the pre-open check's race backstop); O_NONBLOCK keeps a
# FIFO swapped in after the check from blocking the open (it is a no-op for a regular file).
_OPEN_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_APPEND
    | os.O_CLOEXEC
    | os.O_NONBLOCK
    | getattr(os, "O_NOFOLLOW", 0)
)


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
    wait). The lock file is opened without following a symlink, so acquisition can never create
    or touch a file outside the cache: a symlinked or non-regular lock path is
    ``library_lock_invalid``. Creating the parent or opening the file failing otherwise is
    ``io_error``. On a platform without ``fcntl`` the lock degrades to a no-op.
    """
    path = lock_path(repo_root)
    with translating_io("library lock"):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise _lock_invalid(path)
        fd = os.open(path, _OPEN_FLAGS, 0o644)
    try:
        with translating_io("library lock"):
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise _lock_invalid(path)
        _acquire(fd, path)
        try:
            yield
        finally:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _lock_invalid(path: Path) -> LibraryError:
    return LibraryError(
        "library_lock_invalid",
        f"{path} is a symlink or not a regular file — refusing to open the library lock through "
        "a redirected path; remove it and rerun",
    )


def _acquire(fd: int, path: Path) -> None:
    if fcntl is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _CONTENTION_ERRNOS:
            raise LibraryLockBusy(
                "another perk librarian operation holds the machine-local library lock at "
                f"{path} — wait for it to finish and rerun"
            ) from exc
        raise LibraryError("io_error", f"library lock: {exc}") from exc
