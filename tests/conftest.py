import subprocess

import pytest


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway initialized git repo with one commit."""

    def g(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "perk tests")
    (tmp_path / "f.txt").write_text("hi\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "init")
    return tmp_path
