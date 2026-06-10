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


def _stub_pr(monkeypatch, *, is_draft: bool) -> dict[str, object]:
    calls: dict[str, object] = {"marked": False}
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=is_draft, state="OPEN", existed=True
        ),
    )

    def _mark(**k):
        calls["marked"] = True

    monkeypatch.setattr(github, "mark_pr_ready", _mark)
    return calls


def _run(monkeypatch, args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        return runner.invoke(cli, args)


def test_pr_ready_marks_draft(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_pr(monkeypatch, is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["was_draft"] is True
    assert calls["marked"] is True


def test_pr_ready_idempotent_already_ready(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_pr(monkeypatch, is_draft=False)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["was_draft"] is False
    assert calls["marked"] is False  # already-ready never re-marks


def test_pr_ready_no_pr_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_pr_ready_dry_run_offline(monkeypatch):
    result = _run(monkeypatch, ["pr", "ready", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True


def test_pr_ready_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "ready", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
