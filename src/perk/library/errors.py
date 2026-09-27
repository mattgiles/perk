"""The library's typed refusals and its one expected-failure translation boundary.

Every worker maps a :class:`LibraryError` to the ``--json`` failure envelope by its stable
``error_type`` (contracts.md §8.74(g)). :func:`translating_io` is the single place an expected
filesystem or git failure becomes a ``LibraryError`` — so a worker never emits a traceback
where an envelope is promised, and nothing broader than the named failure set is caught.
"""

import contextlib
from collections.abc import Iterator

from perk.substrate import git


class LibraryError(Exception):
    """A domain refusal or operation failure, carrying the stable ``error_type`` code."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


class LibraryLockBusy(LibraryError):
    """Another librarian operation holds the machine-local library lock."""

    def __init__(self, message: str) -> None:
        super().__init__("library_busy", message)


@contextlib.contextmanager
def translating_io(label: str) -> Iterator[None]:
    """Translate an expected ``OSError`` (the whole family) or ``GitError`` into
    ``LibraryError("io_error")`` prefixed with ``label``.

    A ``LibraryError`` raised inside passes through unchanged (it is neither family), so the
    finer-grained classified refusals raised first always win; any other exception is a bug
    and propagates untouched.
    """
    try:
        yield
    except OSError as exc:
        raise LibraryError("io_error", f"{label}: {exc}") from exc
    except git.GitError as exc:
        raise LibraryError("io_error", f"{label}: {exc}") from exc
