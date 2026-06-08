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


def _context() -> github.PrReviewContext:
    return github.PrReviewContext(
        pr_number=42,
        base_ref="main",
        head_ref="plan-7",
        title="Add a thing",
        body="does the thing",
        diff="diff --git a/x b/x\n+new line\n",
        plan_body="# Plan\n\nbody",
    )


def _open_pr():
    return github.PullRequest(number=42, url="u", is_draft=False, state="OPEN", existed=True)


def test_context_success_json(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    monkeypatch.setattr(github, "get_pr_review_context", lambda **k: _context())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr-review-context", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["pr"] == 42 and data["branch"] == "plan-7"
    assert data["base_ref"] == "main" and data["head_ref"] == "plan-7"
    assert "new line" in data["diff"]
    assert data["plan_body"].startswith("# Plan")


def test_context_no_plan_ref_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr-review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_context_no_pr_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr-review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_context_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr-review-context", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_context_github_error_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())

    def _boom(**k):
        raise github.GitHubError("HTTP 500")

    monkeypatch.setattr(github, "get_pr_review_context", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr-review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"
