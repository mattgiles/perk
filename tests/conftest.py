import subprocess

import pytest

from perk import env as env_mod
from perk import github as gh_mod
from perk import init as init_mod


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
    # The `skills init`/`skills sync` shells are external like env/github; stub them so verified
    # inits in tests never clone over the network.
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: None)


@pytest.fixture
def converge_skills_workspace():
    """Plant a healthy skills-delivery substrate: `.agents/manifest.yaml` + every PERK_SKILLS
    SKILL.md under `.agents/skills/` (what a successful `skills init` + `skills update --sync`
    leaves behind, minus the symlink indirection)."""

    def converge(root):
        manifest = root / ".agents" / "manifest.yaml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("sources: {}\nskills: []\n", encoding="utf-8")
        for name in init_mod.PERK_SKILLS:
            skill = root / ".agents" / "skills" / name / "SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text("# skill\n", encoding="utf-8")

    return converge


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


@pytest.fixture
def git_repo_with_remote(tmp_path):
    """A clone with a local **bare** remote (``origin``), offline-testable.

    Returns ``(clone, remote, advance_origin)`` where ``advance_origin()`` pushes a fresh
    commit to ``origin/<trunk>`` from a side checkout so the clone falls behind until it
    fetches. The clone has ``origin/HEAD`` set so ``detect_trunk_branch`` resolves the trunk.
    """
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"

    def g(cwd, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout

    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    # Seed the remote's main with one commit.
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, capture_output=True)
    g(seed, "config", "user.email", "t@example.com")
    g(seed, "config", "user.name", "perk tests")
    (seed / "f.txt").write_text("hi\n", encoding="utf-8")
    g(seed, "add", ".")
    g(seed, "commit", "-qm", "init")
    g(seed, "remote", "add", "origin", str(remote))
    g(seed, "push", "-q", "-u", "origin", "main")

    # Clone it (origin + origin/HEAD set automatically).
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    g(clone, "config", "user.email", "t@example.com")
    g(clone, "config", "user.name", "perk tests")

    def advance_origin() -> str:
        """Push a new commit to origin/main (from the seed checkout); returns its sha."""
        g(seed, "pull", "-q", "origin", "main")
        (seed / "f.txt").write_text("advanced\n", encoding="utf-8")
        g(seed, "add", ".")
        g(seed, "commit", "-qm", "advance")
        g(seed, "push", "-q", "origin", "main")
        return g(seed, "rev-parse", "HEAD").strip()

    return clone, remote, advance_origin
