import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import cache, github
from perk.cli.cli import cli

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_land(monkeypatch, *, draft: bool, merged: bool = False) -> dict[str, object]:
    calls: dict[str, object] = {"readied": False, "merged": False}
    state = "MERGED" if merged else "OPEN"
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=draft, state=state, existed=True
        ),
    )

    def _ready(**k):
        calls["readied"] = True

    def _merge(**k):
        calls["merged"] = True
        return github.PullRequest(
            number=42, url="u/pr/42", is_draft=False, state="MERGED", existed=True
        )

    monkeypatch.setattr(github, "mark_pr_ready", _ready)
    monkeypatch.setattr(github, "merge_pr", _merge)
    return calls


def _run(args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        return runner.invoke(cli, args)


def test_dry_run_is_offline_and_sets_no_marker():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr-land", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True and data["dry_run"] is True
        assert data["branch"] == "plan-7" and data["pending_learn"] is False
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_no_plan_ref_exits_1():
    result = _run(["pr-land", "--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr-land", "--dry-run", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_real_land_draft_marks_ready_merges_and_sets_marker(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        calls = _stub_land(monkeypatch, draft=True)
        result = runner.invoke(cli, ["pr-land", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["pr"]["state"] == "MERGED" and data["pending_learn"] is True
        assert calls["readied"] is True and calls["merged"] is True
        assert cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_real_land_ready_pr_skips_mark_ready(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        calls = _stub_land(monkeypatch, draft=False)
        result = runner.invoke(cli, ["pr-land", "--json"])
        assert result.exit_code == 0
        assert calls["readied"] is False and calls["merged"] is True


def test_real_land_already_merged_is_idempotent(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        calls = _stub_land(monkeypatch, draft=False, merged=True)
        result = runner.invoke(cli, ["pr-land", "--json"])
        assert result.exit_code == 0
        # already MERGED -> no mark-ready, no merge call, but the marker is still set
        assert calls["readied"] is False and calls["merged"] is False
        assert json.loads(result.output)["pending_learn"] is True
        assert cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_real_land_no_pr_exits_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
        result = runner.invoke(cli, ["pr-land", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "no_pr"
