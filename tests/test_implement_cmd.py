"""P1.T4c — `perk implement [PLAN]`: the dedicated implement cold door.

Covers Bug 2 (the optional plan positional + active-ref fallback) at the CLI boundary. The
priming prompt (Bug 1) is covered in test_launch.py. `github.get_plan` + `launch.launch_stage`
are stubbed (no GitHub, no `exec pi`), mirroring test_resume.py.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, launch
from perk.cli.cli import cli
from perk.state import cache

_PLAN_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
    "consumed_learn": [],
}


def _state() -> github.PlanState:
    return github.PlanState(number=7, url="https://gh/o/r/issues/7", title="T", header={}, pr=None)


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def test_implement_with_plan_writes_active_ref_and_launches(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_plan", lambda **k: _state())
    launched: dict[str, object] = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(stage=k["stage"].id))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "7"])
        assert result.exit_code == 0, result.output
        assert launched["stage"] == "implement"
        # #7 is now the active plan (mirrors resume): the ref is materialized at the repo root.
        assert cache.read_plan_ref(Path(d)) == _PLAN_REF


def test_implement_with_plan_dry_run_does_not_write_or_launch(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_plan", lambda **k: _state())

    def boom(**k):
        raise AssertionError("dry run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "7", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "plan-7" in result.output  # the resolved worktree name (stdout JSON + stderr human)
        assert not cache.plan_ref_path(Path(d)).exists()  # side-effect-free
        # The plan-id dry-run JSON carries the resolved base (null here: no remote on this repo).
        payload = json.loads(result.output.splitlines()[0])
        assert "base" in payload and payload["base"] is None


def test_implement_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_plan", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output


def test_implement_no_plan_uses_active_ref_without_github(monkeypatch):
    """No plan id: implement the active saved ref. No GitHub read, no auth needed."""

    def no_github(**k):
        raise AssertionError("implement of the active plan must not read GitHub")

    monkeypatch.setattr(github, "get_plan", no_github)
    launched: dict[str, object] = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(stage=k["stage"].id))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _PLAN_REF)
        result = runner.invoke(cli, ["implement"])
        assert result.exit_code == 0, result.output
        assert launched["stage"] == "implement"
