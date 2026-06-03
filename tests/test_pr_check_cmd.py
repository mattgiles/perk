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


def _stub_pr(monkeypatch, *, body: str) -> None:
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=True
        ),
    )
    monkeypatch.setattr(github, "get_pr_body", lambda **k: body)


def _run(monkeypatch, args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        return runner.invoke(cli, args)


def test_pr_check_valid_exits_0(monkeypatch):
    _authed(monkeypatch)
    _stub_pr(monkeypatch, body="Closes #7\n\n`gh pr checkout 42`\n")
    result = _run(monkeypatch, ["pr-check", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["success"] is True


def test_pr_check_invalid_footer_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_pr(monkeypatch, body="Closes #7\n\n`gh pr checkout 7`\n")  # issue number, not PR
    result = _run(monkeypatch, ["pr-check", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["success"] is False and data["error_type"] == "pr_check_failed"


def test_pr_check_no_pr_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    result = _run(monkeypatch, ["pr-check", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_pr_check_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["pr-check", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
