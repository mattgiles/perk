"""Tests for the machine-local stack-operation lock (``perk/delivery/oplock.py``).

Real ``flock`` behavior — no fakes: contention between two acquisitions (two open file
descriptions conflict even in one process), main/linked-worktree anchoring on ONE file, and
reacquisition after release. The delivery operations' *mapping* of a busy lock to the typed
``operation_in_progress`` refusal is pinned in the sync/recover suites.
"""

import subprocess
from pathlib import Path

import pytest

from perk.delivery import oplock

pytestmark = pytest.mark.skipif(
    oplock.fcntl is None, reason="the lock degrades to a no-op without fcntl (non-POSIX)"
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    identity = ("-c", "user.email=t@t", "-c", "user.name=t")
    _git(repo, *identity, "commit", "-q", "--allow-empty", "-m", "seed")
    return repo


def test_contention_and_reacquisition_after_release(tmp_path):
    repo = _repo(tmp_path)
    with oplock.stack_operation_lock(repo):
        # A second acquisition (its own open file description) is refused immediately.
        with pytest.raises(oplock.OperationLockBusy) as excinfo, oplock.stack_operation_lock(repo):
            pass
        assert "another stack operation holds the machine-local lock" in str(excinfo.value)
    # Released: the next acquisition succeeds (and releases cleanly again).
    with oplock.stack_operation_lock(repo):
        pass


def test_linked_worktree_contends_on_the_main_checkout_lock(tmp_path):
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", str(linked), "HEAD")
    # One anchor: both roots resolve to the MAIN checkout's lock file.
    assert oplock.lock_path(linked) == oplock.lock_path(repo)
    assert oplock.lock_path(repo) == repo / ".perk/workflow/stack-operation.lock"
    # Holding from the main checkout blocks an acquisition from the linked worktree.
    with (
        oplock.stack_operation_lock(repo),
        pytest.raises(oplock.OperationLockBusy),
        oplock.stack_operation_lock(linked),
    ):
        pass
    # And the reverse direction contends on the same file too.
    with (
        oplock.stack_operation_lock(linked),
        pytest.raises(oplock.OperationLockBusy),
        oplock.stack_operation_lock(repo),
    ):
        pass
