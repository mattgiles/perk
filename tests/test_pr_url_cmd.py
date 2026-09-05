import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github, plan
from perk.cli.cli import cli
from perk.state import cache

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _open_pr(base_ref="topic/predecessor"):
    return github.PullRequest(
        number=42,
        url="https://gh/o/r/pull/42",
        is_draft=False,
        state="OPEN",
        existed=True,
        base_ref=base_ref,
    )


@pytest.mark.parametrize("plan_base", [None, "main"])
def test_url_success_json(monkeypatch, plan_base):
    calls = []

    def find_pr(**kwargs):
        calls.append(kwargs)
        return _open_pr()

    monkeypatch.setattr(github, "find_pr_for_branch", find_pr)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(
            Path(d), plan.PlanRefModel.model_validate({**_REF, "base": plan_base}).to_domain()
        )
        result = runner.invoke(cli, ["pr", "url", "--json"])
        assert calls == [{"branch": "plan-7", "repo_root": Path(d).resolve()}]
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["error_type"] is None
    assert data["pr"] == {
        "number": 42,
        "url": "https://gh/o/r/pull/42",
        "base_ref": "topic/predecessor",
    }


@pytest.mark.parametrize("base_ref", ["", " \t\n"])
def test_url_missing_base_refuses(monkeypatch, base_ref):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr(base_ref))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["success"] is False
    assert data["error_type"] == "github_error"
    assert "#42" in data["message"]
    assert "missing its base branch" in data["message"]


def test_url_github_error(monkeypatch):
    def find_pr(**kwargs):
        raise github.GitHubError("offline")

    monkeypatch.setattr(github, "find_pr_for_branch", find_pr)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "github_error"
    assert "offline" in data["message"]


def test_url_human_output_unchanged(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "url"])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == "PR url #42 (plan-7): https://gh/o/r/pull/42\n"


def test_url_no_plan_ref_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_url_no_pr_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_url_corrupt_plan_ref_presents_clean_error(monkeypatch):
    """A torn/corrupt plan-ref.json presents as a clean CLI error (no traceback), naming the
    file and the move-aside remediation."""
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        path = cache.plan_ref_path(Path(d))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"provider": "github"}\n"perk:plan"]}\n', encoding="utf-8")
        result = runner.invoke(cli, ["pr", "url"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)  # no traceback
    assert "Error:" in result.stderr
    assert "plan-ref.json" in result.stderr
    assert "move the file aside" in result.stderr


def test_url_corrupt_plan_ref_json_envelope(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        path = cache.plan_ref_path(Path(d))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"trunc', encoding="utf-8")
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["success"] is False
    assert data["error_type"] == "cache_invalid"
    assert "plan-ref.json" in data["message"]


def test_url_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
