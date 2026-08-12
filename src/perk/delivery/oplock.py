"""The machine-local stack-operation lock (contracts.md §8.49/§8.51/§8.56).

One exclusive, non-blocking ``flock`` serializes the MUTATING stack operations on this
machine — sync (fresh/resume/continue/abort), recover (roll-forward/abandon/sweep), and
land (the journaled atomic merge). The
residue those operations touch (the isolated ``sync-*`` worktrees, the ``refs/perk/sync/*``
temp refs, the continuation manifests) is machine-local, so the lock only needs same-machine
scope: cross-machine serialization stays the journal's one-unresolved gate plus the exact
push leases. Status never acquires it — reads stay lock-free.

The lock file lives beside the continuation manifests at the MAIN checkout
(``.perk/workflow/stack-operation.lock``; ``main_worktree_root`` fallback ``repo_root``), so
a sync from a ``plan-<N>`` worktree and a recover from the main checkout contend on ONE file.
A busy lock raises :class:`OperationLockBusy`; the operations map it to the typed refusal
``operation_in_progress``.
"""

import contextlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

from perk.substrate import git as git_mod

fcntl: ModuleType | None
try:
    import fcntl as _fcntl

    fcntl = _fcntl
except ImportError:  # pragma: no cover - non-POSIX (perk dev platforms are macOS/Linux)
    fcntl = None

_LOCK_SUBPATH = Path(".perk/workflow/stack-operation.lock")


class OperationLockBusy(Exception):
    """The machine-local stack-operation lock is already held — another mutating stack
    operation is running on this machine. Mapped to the typed refusal
    ``operation_in_progress`` by the callers."""


def lock_path(repo_root: Path) -> Path:
    """Where the lock file lives (present or not), anchored at the MAIN checkout so every
    worktree contends on the same file."""
    main_root = git_mod.main_worktree_root(repo_root) or repo_root
    return main_root / _LOCK_SUBPATH


@contextlib.contextmanager
def stack_operation_lock(repo_root: Path) -> Iterator[None]:
    """Hold the exclusive machine-local stack-operation lock for the ``with`` body.

    Non-blocking: a held lock raises :class:`OperationLockBusy` immediately (the caller
    reports the typed refusal — never a silent wait). On a platform without ``fcntl`` the
    lock degrades to a no-op (perk dev platforms are macOS/Linux; the journal gate still
    serializes remote mutations).
    """
    path = lock_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise OperationLockBusy(
                    f"another stack operation holds the machine-local lock at {path} — wait "
                    "for it to finish and rerun"
                ) from exc
        try:
            yield
        finally:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
