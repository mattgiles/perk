"""Tests for ``perk workflow run list`` — the supervisor read surface (Node 3.1)."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import cache, github
from perk.cli.cli import cli


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _record(run_id: str, *, dispatched_at: str, **over) -> dict:
    base = {
        "stage": "implement",
        "plan_ref": {"provider": "github", "pr_id": "42", "url": "u/issues/42"},
        "runner": "",
        "kind": "github-actions",
        "status": "dispatched",
        "dispatched_at": dispatched_at,
        "run_handle": {
            "runner": "",
            "kind": "github-actions",
            "run_ref": "1234567",
            "url": "u/actions/runs/1234567",
        },
        "error": None,
    }
    base.update(over)
    return {**base, "run_id": run_id}


# --- enumeration unit -----------------------------------------------------------------


def test_list_dispatch_records_newest_first(tmp_path: Path):
    cache.write_dispatch(tmp_path, "a", _record("a", dispatched_at="2026-06-07T10:00:00Z"))
    cache.write_dispatch(tmp_path, "b", _record("b", dispatched_at="2026-06-07T12:00:00Z"))
    cache.write_dispatch(tmp_path, "c", _record("c", dispatched_at="2026-06-07T11:00:00Z"))
    records = cache.list_dispatch_records(tmp_path)
    assert [r["run_id"] for r in records] == ["b", "c", "a"]


def test_list_dispatch_records_empty(tmp_path: Path):
    assert cache.list_dispatch_records(tmp_path) == []


def test_list_dispatch_records_skips_corrupt(tmp_path: Path):
    cache.write_dispatch(tmp_path, "good", _record("good", dispatched_at="2026-06-07T10:00:00Z"))
    bad = cache.dispatch_path(tmp_path, "bad")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json", encoding="utf-8")
    records = cache.list_dispatch_records(tmp_path)
    assert [r["run_id"] for r in records] == ["good"]


# --- command -------------------------------------------------------------------------


def _plan_with_pr() -> github.PlanState:
    pr = github.PullRequest(number=51, url="u/pull/51", is_draft=True, state="OPEN", existed=True)
    return github.PlanState(number=42, url="u/issues/42", title="t", header={}, pr=pr)


def _invoke_in_repo(args, *, records=None, git=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git:
            _git_init(d)
        for r in records or []:
            cache.write_dispatch(Path(d), r["run_id"], r)
        return runner.invoke(cli, args)


def test_json_happy_path_refreshed(monkeypatch):
    monkeypatch.setattr(github, "get_plan", lambda *, number, repo_root: _plan_with_pr())
    monkeypatch.setattr(
        github,
        "get_workflow_run",
        lambda *, run_id, repo_root: github.WorkflowRun(
            id=run_id, url="u/actions/runs/1234567", status="completed", conclusion="success"
        ),
    )
    recs = [
        _record("01ok", dispatched_at="2026-06-07T12:00:00Z"),
        _record(
            "01fail",
            dispatched_at="2026-06-07T11:00:00Z",
            status="failed",
            run_handle=None,
            error="boom",
        ),
    ]
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=recs)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["refreshed"] is True
    assert payload["count"] == 2
    by_id = {r["run_id"]: r for r in payload["runs"]}
    ok = by_id["01ok"]
    assert ok["plan"] == {"pr_id": "42", "url": "u/issues/42"}
    assert ok["pr"] == {"number": 51, "url": "u/pull/51", "state": "OPEN"}
    assert ok["run"]["status"] == "completed" and ok["run"]["conclusion"] == "success"
    failed = by_id["01fail"]
    assert failed["dispatch_status"] == "failed"
    assert failed["error"] == "boom"
    assert failed["run"] is None


def test_no_refresh_skips_github(monkeypatch):
    def _boom(**_):
        raise AssertionError("must not be called under --no-refresh")

    monkeypatch.setattr(github, "get_plan", _boom)
    monkeypatch.setattr(github, "get_workflow_run", _boom)
    recs = [_record("01x", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "list", "--json", "--no-refresh"], records=recs)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["refreshed"] is False
    run = payload["runs"][0]
    assert run["pr"] is None and run["run"] is None
    assert run["plan"]["pr_id"] == "42"


def test_fail_soft_overlay(monkeypatch):
    def _raise_plan(*, number, repo_root):
        raise github.GitHubError("nope")

    def _raise_run(*, run_id, repo_root):
        raise github.GitHubError("nope")

    monkeypatch.setattr(github, "get_plan", _raise_plan)
    monkeypatch.setattr(github, "get_workflow_run", _raise_run)
    recs = [_record("01x", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=recs)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    run = payload["runs"][0]
    assert run["pr"] is None and run["run"] is None


def test_empty_state():
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=[])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 0 and payload["runs"] == []
    assert "No dispatched runs found" in result.stderr


def test_not_a_repo():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["workflow", "run", "list", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["success"] is False and payload["error_type"] == "not_a_repo"


def test_human_table_smoke(monkeypatch):
    monkeypatch.setattr(github, "get_plan", lambda *, number, repo_root: _plan_with_pr())
    monkeypatch.setattr(
        github,
        "get_workflow_run",
        lambda *, run_id, repo_root: github.WorkflowRun(
            id=run_id, url="u", status="completed", conclusion="success"
        ),
    )
    recs = [_record("01ABCDEF", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "list"], records=recs)
    assert result.exit_code == 0
    assert "RUN_ID" in result.stderr and "CONCLUSION" in result.stderr
    assert "01ABCDEF" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args",
    [
        ["workflow", "run", "list"],
        ["workflow", "run", "ls"],
        ["wf", "run", "list"],
    ],
)
def test_aliases_resolve(args):
    result = _invoke_in_repo([*args, "--json"], records=[])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["success"] is True
