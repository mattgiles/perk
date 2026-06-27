import json
import subprocess
from pathlib import Path

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


def _open_pr():
    return github.PullRequest(
        number=42, url="https://gh/o/r/pull/42", is_draft=False, state="OPEN", existed=True
    )


def test_url_success_json(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["error_type"] is None
    assert data["pr"]["number"] == 42
    assert data["pr"]["url"] == "https://gh/o/r/pull/42"


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


def test_url_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "url", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
