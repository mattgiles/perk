"""`perk-dev publish-check` regression tests.

No real checks, builds, or network: publish-check is a pure composition of existing seams
(`release.check_release`, `gh auth`, `release.probe_remote_tag`, `build.run_build`), so the
seams are monkeypatched with a shared recorder and the tests pin the orchestration — the
fail-fast order, the `--allow-dirty` → `for_publish` wiring, and the tri-state incident
preflight's warn-only semantics.
"""

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev import build, changelog, release
from perk_dev.cli import cli

from perk.github import GitHubError
from perk.github import auth as gh_auth

_ERROR_FINDING = changelog.Finding("error", "dirty_tree", None, "the worktree is dirty")


class _Seams:
    """All four publish-check seams patched green, recording call order + kwargs."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        findings: tuple[changelog.Finding, ...] = (),
        auth_status: gh_auth.AuthStatus | None = None,
        auth_raises: bool = False,
        probe: tuple[bool | None, str | None] = (False, None),
        build_raises: bool = False,
    ) -> None:
        self.order: list[str] = []
        self.check_release_kwargs: dict[str, bool] = {}
        self.probe_args: tuple[Path, str] | None = None

        def check_release(root: Path, *, for_publish: bool) -> release.ReleaseCheck:
            self.order.append("check_release")
            self.check_release_kwargs["for_publish"] = for_publish
            return release.ReleaseCheck(findings)

        def check_auth() -> gh_auth.AuthStatus:
            self.order.append("check_auth")
            if auth_raises:
                raise GitHubError("gh not found")
            if auth_status is not None:
                return auth_status
            return gh_auth.AuthStatus(ok=True, user="octocat", scopes=(), error=None)

        def probe_remote_tag(root: Path, tag_name: str) -> tuple[bool | None, str | None]:
            self.order.append("probe_remote_tag")
            self.probe_args = (root, tag_name)
            return probe

        def run_build(root: Path) -> None:
            self.order.append("run_build")
            if build_raises:
                raise build.BuildError("uv_build_failed", "uv build exploded")

        monkeypatch.setattr(release, "check_release", check_release)
        monkeypatch.setattr(gh_auth, "check_auth", check_auth)
        monkeypatch.setattr(release, "probe_remote_tag", probe_remote_tag)
        monkeypatch.setattr(build, "run_build", run_build)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal git repo cwd with the pyproject version SSOT publish-check reads."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_happy_path_order_and_summary(repo, monkeypatch):
    seams = _Seams(monkeypatch)
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 0, result.output
    assert "publish-check OK" in result.stderr
    assert seams.order == ["check_release", "check_auth", "probe_remote_tag", "run_build"]
    assert seams.probe_args is not None and seams.probe_args[1] == "v1.2.3"


def test_default_requires_clean_tree(repo, monkeypatch):
    seams = _Seams(monkeypatch)
    assert CliRunner().invoke(cli, ["publish-check"]).exit_code == 0
    assert seams.check_release_kwargs == {"for_publish": True}


def test_allow_dirty_skips_clean_tree(repo, monkeypatch):
    seams = _Seams(monkeypatch)
    assert CliRunner().invoke(cli, ["publish-check", "--allow-dirty"]).exit_code == 0
    assert seams.check_release_kwargs == {"for_publish": False}


def test_check_release_errors_fail_before_build(repo, monkeypatch):
    seams = _Seams(monkeypatch, findings=(_ERROR_FINDING,))
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 1
    assert "dirty_tree" in result.stderr
    assert seams.order == ["check_release"]


def test_auth_not_ok_fails_with_login_hint(repo, monkeypatch):
    seams = _Seams(
        monkeypatch,
        auth_status=gh_auth.AuthStatus(ok=False, user=None, scopes=(), error="no token"),
    )
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 1
    assert "gh auth login" in result.stderr
    assert "run_build" not in seams.order


def test_auth_github_error_fails(repo, monkeypatch):
    seams = _Seams(monkeypatch, auth_raises=True)
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 1
    assert "gh auth login" in result.stderr
    assert "run_build" not in seams.order


def test_tag_on_origin_warns_but_passes(repo, monkeypatch):
    _Seams(monkeypatch, probe=(True, "a" * 40))
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 0, result.output
    assert "already exists on origin" in result.stderr
    assert "Incident handling" in result.stderr


def test_probe_unknown_notes_and_passes(repo, monkeypatch):
    _Seams(monkeypatch, probe=(None, None))
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 0, result.output
    assert "state unknown" in result.stderr
    assert "Incident handling" not in result.stderr


def test_probe_absent_is_silent(repo, monkeypatch):
    _Seams(monkeypatch, probe=(False, None))
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 0, result.output
    assert "already exists on origin" not in result.stderr
    assert "state unknown" not in result.stderr


def test_build_failure_fails(repo, monkeypatch):
    seams = _Seams(monkeypatch, build_raises=True)
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 1
    assert "Error: " in result.stderr
    assert seams.order[-1] == "run_build"


def test_not_a_repo_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr("perk_dev.cli.repo_root", lambda _cwd: None)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["publish-check"])
    assert result.exit_code == 2
    assert "not inside a git repository" in result.stderr


def test_command_registered():
    assert "publish-check" in cli.commands
