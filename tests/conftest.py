import subprocess

import pytest

from perk import env as env_mod
from perk import github as gh_mod


@pytest.fixture
def stub_env(monkeypatch):
    """Make `perk init`'s external verification pass without a real/authed toolchain.

    init.py references `env`/`github` as modules, so patching the module attributes is seen
    at call time. GitHub is stubbed *unauthed* (non-fatal) to keep the path realistic.
    """
    monkeypatch.setattr(
        env_mod,
        "check_environment",
        lambda: [
            env_mod.EnvCheck("git", True, "ok", ""),
            env_mod.EnvCheck("gh", True, "ok", ""),
            env_mod.EnvCheck("node", True, "v22.19.0", ""),
            env_mod.EnvCheck("pi", True, "ok", ""),
        ],
    )
    monkeypatch.setattr(
        gh_mod, "check_auth", lambda: gh_mod.AuthStatus(False, None, (), "stub: not authed")
    )
    monkeypatch.setattr(gh_mod, "check_repo_access", lambda root: gh_mod.RepoAccess.skipped())


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
