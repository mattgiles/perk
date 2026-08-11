import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def test_git_repo_factory_copies_are_isolated(tmp_path, git_repo_factory):
    left = git_repo_factory(tmp_path / "left")
    right = git_repo_factory(tmp_path / "right")
    original_sha = _git(right, "rev-parse", "HEAD")

    (left / "f.txt").write_text("left only\n", encoding="utf-8")
    _git(left, "add", ".")
    _git(left, "commit", "-qm", "left mutation")

    assert (right / "f.txt").read_text(encoding="utf-8") == "hi\n"
    assert _git(right, "rev-parse", "HEAD") == original_sha


def test_remote_git_repo_factory_keeps_origins_inside_each_copy(tmp_path, remote_git_repo_factory):
    left_clone, left_remote, advance_left = remote_git_repo_factory(tmp_path / "left")
    right_clone, right_remote, _advance_right = remote_git_repo_factory(tmp_path / "right")
    right_before = _git(right_remote, "rev-parse", "main")

    advanced_sha = advance_left()

    assert _git(left_clone, "remote", "get-url", "origin") == "../remote.git"
    assert _git(right_clone, "remote", "get-url", "origin") == "../remote.git"
    assert _git(left_remote, "rev-parse", "main") == advanced_sha
    assert _git(right_remote, "rev-parse", "main") == right_before
