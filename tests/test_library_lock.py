"""The machine-local library lock (``perk/library/lock.py``) — real ``flock``, no fakes.

Mirrors the stack-operation lock's suite: contention within one process (two open file
descriptions conflict), main/linked-worktree anchoring on ONE file, reacquisition, plus the
library-specific translation of an unwritable lock parent to ``io_error``.
"""

import os
import subprocess
from pathlib import Path

import pytest

from perk.library import lock
from perk.library.errors import LibraryError, LibraryLockBusy

pytestmark = pytest.mark.skipif(
    lock.fcntl is None, reason="the lock degrades to a no-op without fcntl (non-POSIX)"
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "s",
    )
    return repo


def test_contention_and_reacquisition_after_release(tmp_path):
    repo = _repo(tmp_path)
    with lock.library_lock(repo):
        with pytest.raises(LibraryLockBusy) as excinfo, lock.library_lock(repo):
            pass
        assert excinfo.value.error_type == "library_busy"
        assert "another perk librarian operation holds the machine-local library lock" in str(
            excinfo.value
        )
        assert str(lock.lock_path(repo)) in str(excinfo.value)
    with lock.library_lock(repo):
        pass


def test_linked_worktree_contends_on_the_main_checkout_lock(tmp_path):
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", str(linked), "HEAD")
    assert lock.lock_path(linked) == lock.lock_path(repo)
    assert lock.lock_path(repo).resolve() == (repo / ".perk/workflow/library.lock").resolve()
    assert lock.lock_rel() == ".perk/workflow/library.lock"
    with lock.library_lock(repo), pytest.raises(LibraryLockBusy), lock.library_lock(linked):
        pass


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unwritable_lock_parent_is_io_error_not_a_raw_oserror(tmp_path):
    repo = _repo(tmp_path)
    perk_dir = repo / ".perk"
    perk_dir.mkdir()
    perk_dir.chmod(0o500)
    try:
        with pytest.raises(LibraryError) as excinfo, lock.library_lock(repo):
            pass
    finally:
        perk_dir.chmod(0o700)
    assert excinfo.value.error_type == "io_error"
    assert not isinstance(excinfo.value, OSError)
    assert str(excinfo.value).startswith("library lock:")
