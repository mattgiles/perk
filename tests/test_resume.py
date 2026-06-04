import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import cache, github, launch, resume
from perk.cli.cli import cli


def _pr(state: str) -> github.PullRequest:
    return github.PullRequest(number=55, url="u/pr/55", is_draft=False, state=state, existed=True)


def _state(*, header: dict | None = None, pr: github.PullRequest | None = None) -> github.PlanState:
    return github.PlanState(
        number=7, url="https://gh/o/r/issues/7", title="T", header=header or {}, pr=pr
    )


# --- the pure resolution matrix (D5) ---------------------------------------------------


@pytest.mark.parametrize(
    ("state", "pending", "expected"),
    [
        (_state(header={"lifecycle_stage": "planned"}), False, "implement"),
        (_state(header={"lifecycle_stage": "impl"}), False, "implement"),  # impl, no PR yet
        (_state(pr=_pr("OPEN")), False, "submit"),
        (_state(pr=_pr("MERGED")), True, "learn"),
        (_state(pr=_pr("MERGED")), False, None),  # merged + learned -> nothing
    ],
)
def test_resolve_resume_stage_matrix(state, pending, expected):
    assert resume.resolve_resume_stage(state, has_pending_learn=pending) == expected


def test_reconstruct_plan_ref():
    ref = resume.reconstruct_plan_ref(_state(header={"objective_id": "O1"}))
    assert ref == {
        "provider": "github",
        "pr_id": "7",
        "url": "https://gh/o/r/issues/7",
        "labels": ["perk:plan"],
        "objective_id": "O1",
        "consumed_learn": [],
    }


# --- the CLI (CliRunner; get_plan + launch_stage stubbed) ------------------------------


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def test_dry_run_resolves_stage_without_launching(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(
        github, "get_plan", lambda **k: _state(header={"lifecycle_stage": "planned"})
    )

    def boom(**k):
        raise AssertionError("dry run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["resume", "42", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["resumed_stage"] == "implement" and data["worktree"] == "plan-7"
        assert data["plan_ref"]["pr_id"] == "7"
        # dry run writes no ref
        assert not cache.plan_ref_path(Path(d)).exists()


def test_real_resume_writes_ref_and_launches(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_plan", lambda **k: _state(pr=_pr("OPEN")))
    launched: dict[str, object] = {}

    def _launch(**k):
        launched["stage"] = k["stage"].id

    monkeypatch.setattr(launch, "launch_stage", _launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["resume", "7"])
        assert result.exit_code == 0
        assert launched["stage"] == "submit"  # PR open -> submit
        # the ref was materialized at the repo root for launch_stage to derive from
        assert cache.read_plan_ref(Path(d)) is not None


def test_nothing_to_resume_exits_0(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_plan", lambda **k: _state(pr=_pr("MERGED")))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["resume", "7", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["resumed_stage"] is None


def test_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_plan", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["resume", "999", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "plan_not_found"


def test_invalid_plan_id_exits_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["resume", "not-a-number", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "invalid_input"


def test_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["resume", "7", "--dry-run", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
