"""Tests for ``perk workflow run list`` — the supervisor read surface."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.state import cache

_ULID_A = "01HZXW8T2M3N4P5Q6R7S8T9V0W"
_ULID_B = "01HZXW8T2M3N4P5Q6R7S8T9V1X"


@pytest.fixture(autouse=True)
def _no_remote_discovery(monkeypatch):
    """Run discovery shells `gh api`; default every test to an empty enumeration so refreshed
    invocations stay offline. Merge tests override ``github.list_workflow_runs`` themselves."""
    monkeypatch.setattr(github, "list_workflow_runs", lambda **_k: [])


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _record(run_id: str, *, dispatched_at: str, **over) -> cache.Dispatch:
    base = {
        "stage": "implement",
        "plan_ref": {
            "provider": "github",
            "pr_id": "42",
            "url": "u/issues/42",
            "labels": ["perk:plan"],
        },
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
    return cache.DispatchModel.model_validate({**base, "run_id": run_id}).to_domain()


# --- enumeration unit -----------------------------------------------------------------


def test_list_dispatch_records_newest_first(tmp_path: Path):
    cache.write_dispatch(tmp_path, "a", _record("a", dispatched_at="2026-06-07T10:00:00Z"))
    cache.write_dispatch(tmp_path, "b", _record("b", dispatched_at="2026-06-07T12:00:00Z"))
    cache.write_dispatch(tmp_path, "c", _record("c", dispatched_at="2026-06-07T11:00:00Z"))
    records = cache.list_dispatch_records(tmp_path)
    assert [r.run_id for r in records] == ["b", "c", "a"]


def test_list_dispatch_records_empty(tmp_path: Path):
    assert cache.list_dispatch_records(tmp_path) == []


def test_list_dispatch_records_skips_corrupt(tmp_path: Path):
    cache.write_dispatch(tmp_path, "good", _record("good", dispatched_at="2026-06-07T10:00:00Z"))
    bad = cache.dispatch_path(tmp_path, "bad")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json", encoding="utf-8")
    records = cache.list_dispatch_records(tmp_path)
    assert [r.run_id for r in records] == ["good"]


# --- command -------------------------------------------------------------------------


def _plan_with_pr() -> plans.PlanState:
    pr = github.PullRequest(number=51, url="u/pull/51", is_draft=True, state="OPEN", existed=True)
    return plans.PlanState(number=42, url="u/issues/42", title="t", header={}, pr=pr)


def _invoke_in_repo(args, *, records=None, git=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git:
            _git_init(d)
        for r in records or []:
            cache.write_dispatch(Path(d), r.run_id, r)
        return runner.invoke(cli, args)


def test_json_happy_path_refreshed(monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_with_pr())
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

    monkeypatch.setattr(plans, "get_plan", _boom)
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

    monkeypatch.setattr(plans, "get_plan", _raise_plan)
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


@pytest.mark.parametrize("bad_limit", ["0", "-1"])
def test_limit_rejects_non_positive(bad_limit):
    result = _invoke_in_repo(["workflow", "run", "list", "--json", "--limit", bad_limit])
    assert result.exit_code != 0
    assert "Invalid value" in result.output


def test_limit_one_succeeds():
    result = _invoke_in_repo(["workflow", "run", "list", "--json", "--limit", "1"], records=[])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True


def test_not_a_repo():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["workflow", "run", "list", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["success"] is False and payload["error_type"] == "not_a_repo"


def test_human_table_smoke(monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_with_pr())
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


# --- cancel / retry (control surface) ---------------------------------------

from perk.run import runner as _runner  # noqa: E402


def _noop_cancel(self, handle, *, repo_root):
    return None


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(ok=True, user="u", scopes=(), error=None)
    )


def _unauthed(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "check_auth",
        lambda: github.AuthStatus(ok=False, user=None, scopes=(), error="no auth"),
    )


def test_cancel_json_happy_path(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(_runner.GitHubActionsRunner, "cancel", _noop_cancel)
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "cancel", "01ok", "--json"], records=recs)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True and payload["action"] == "cancel"
    assert payload["run_id"] == "01ok" and payload["run_ref"] == "1234567"
    assert payload["runner"] == "" and payload["kind"] == "github-actions"
    assert payload["url"] == "u/actions/runs/1234567"
    assert "Cancelled run 01ok" in result.stderr


def test_retry_json_happy_path(monkeypatch):
    _authed(monkeypatch)
    seen = {}

    def _retry(self, handle, *, failed_only, repo_root):
        seen["failed_only"] = failed_only

    monkeypatch.setattr(_runner.GitHubActionsRunner, "retry", _retry)
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "retry", "01ok", "--json"], records=recs)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["action"] == "retry" and payload["failed_only"] is False
    assert seen["failed_only"] is False
    assert "Retried run 01ok" in result.stderr


def test_retry_failed_only(monkeypatch):
    _authed(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        _runner.GitHubActionsRunner,
        "retry",
        lambda self, handle, *, failed_only, repo_root: seen.update(failed_only=failed_only),
    )
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(
        ["workflow", "run", "retry", "01ok", "--failed", "--json"], records=recs
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["failed_only"] is True and seen["failed_only"] is True
    assert "Retried failed jobs of run 01ok" in result.stderr


def test_cancel_run_not_found(monkeypatch):
    _authed(monkeypatch)
    result = _invoke_in_repo(["workflow", "run", "cancel", "nope", "--json"], records=[])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False and payload["error_type"] == "run_not_found"


def test_cancel_run_not_dispatched(monkeypatch):
    _authed(monkeypatch)
    recs = [_record("01nh", dispatched_at="2026-06-07T12:00:00Z", run_handle=None)]
    result = _invoke_in_repo(["workflow", "run", "cancel", "01nh", "--json"], records=recs)
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "run_not_dispatched"


def test_cancel_requires_github(monkeypatch):
    _unauthed(monkeypatch)

    def _boom(self, handle, *, repo_root):
        raise AssertionError("runner op must not be called when unauthed")

    monkeypatch.setattr(_runner.GitHubActionsRunner, "cancel", _boom)
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "cancel", "01ok", "--json"], records=recs)
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "github_unauthed"


def test_cancel_runner_error_surfaces(monkeypatch):
    _authed(monkeypatch)

    def _boom(self, handle, *, repo_root):
        raise _runner.RunnerError("cannot cancel a completed run")

    monkeypatch.setattr(_runner.GitHubActionsRunner, "cancel", _boom)
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "cancel", "01ok", "--json"], records=recs)
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "cancel_failed"
    assert "cannot cancel a completed run" in payload["message"]


def test_retry_runner_error_surfaces(monkeypatch):
    _authed(monkeypatch)

    def _boom(self, handle, *, failed_only, repo_root):
        raise _runner.RunnerError("cannot rerun")

    monkeypatch.setattr(_runner.GitHubActionsRunner, "retry", _boom)
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "retry", "01ok", "--json"], records=recs)
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "retry_failed" and "cannot rerun" in payload["message"]


def test_not_a_repo_cancel():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["workflow", "run", "cancel", "01ok", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_not_a_repo_retry():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["workflow", "run", "retry", "01ok", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_human_output_smoke(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(_runner.GitHubActionsRunner, "cancel", _noop_cancel)
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "cancel", "01ok"], records=recs)
    assert result.exit_code == 0
    assert "Cancelled run 01ok" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args",
    [
        ["workflow", "run", "cancel", "01ok"],
        ["wf", "run", "cancel", "01ok"],
        ["workflow", "run", "retry", "01ok"],
    ],
)
def test_control_aliases_resolve(monkeypatch, args):
    _authed(monkeypatch)
    monkeypatch.setattr(_runner.GitHubActionsRunner, "cancel", _noop_cancel)
    monkeypatch.setattr(
        _runner.GitHubActionsRunner, "retry", lambda self, handle, *, failed_only, repo_root: None
    )
    recs = [_record("01ok", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo([*args, "--json"], records=recs)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["success"] is True


# --- canonical discovery merge (contracts.md §8.17) --------------------------


def _listing(run_ref, *, title, status="in_progress", conclusion=None, created=""):
    return github.WorkflowRunListing(
        run=github.WorkflowRun(
            id=run_ref, url=f"u/actions/runs/{run_ref}", status=status, conclusion=conclusion
        ),
        title=title,
        created_at=created,
    )


def test_discovered_only_rows_are_reconstructed(monkeypatch):
    """A fresh clone (zero local records) still lists runs — the discovery is the existence
    source; every field is reconstructed from the parsed run-name + the run's live state."""
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_with_pr())
    monkeypatch.setattr(
        github,
        "list_workflow_runs",
        lambda **_k: [
            _listing(
                "999",
                title=f"perk implement · plan #42 · {_ULID_A}",
                status="completed",
                conclusion="success",
                created="2026-06-07T12:00:00Z",
            )
        ],
    )
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=[])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 1
    row = payload["runs"][0]
    assert row["source"] == "discovered"
    assert row["run_id"] == _ULID_A and row["stage"] == "implement"
    assert row["runner"] == "" and row["kind"] == "github-actions"
    assert row["dispatch_status"] == "dispatched" and row["error"] is None
    assert row["dispatched_at"] == "2026-06-07T12:00:00Z"
    assert row["plan"] == {"pr_id": "42", "url": ""}
    assert row["pr"] == {"number": 51, "url": "u/pull/51", "state": "OPEN"}
    assert row["run"] == {
        "run_ref": "999",
        "url": "u/actions/runs/999",
        "status": "completed",
        "conclusion": "success",
    }


def test_both_row_uses_discovery_run_block_without_observe(monkeypatch):
    """A locally-known run that also appears in discovery takes its run block from the single
    enumeration — the per-record `gh run view` observe must not happen."""

    def _no_observe(**_k):
        raise AssertionError("observe (gh run view) must not be called for a discovered run")

    monkeypatch.setattr(github, "get_workflow_run", _no_observe)
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_with_pr())
    monkeypatch.setattr(
        github,
        "list_workflow_runs",
        lambda **_k: [
            _listing(
                "999",
                title=f"perk implement · plan #42 · {_ULID_A}",
                status="in_progress",
                created="2026-06-07T12:00:30Z",
            )
        ],
    )
    recs = [_record(_ULID_A, dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=recs)
    assert result.exit_code == 0
    row = json.loads(result.stdout)["runs"][0]
    assert row["source"] == "both"
    # Record fields win for provenance (plan url, precise dispatch time)…
    assert row["dispatched_at"] == "2026-06-07T12:00:00Z"
    assert row["plan"] == {"pr_id": "42", "url": "u/issues/42"}
    # …while the run block comes from the discovery (run_ref included).
    assert row["run"] == {
        "run_ref": "999",
        "url": "u/actions/runs/999",
        "status": "in_progress",
        "conclusion": None,
    }


def test_local_only_rows_keep_source_and_error_line(monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_with_pr())
    recs = [
        _record(
            "01fail",
            dispatched_at="2026-06-07T11:00:00Z",
            status="failed",
            run_handle=None,
            error="boom",
        )
    ]
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=recs)
    assert result.exit_code == 0
    row = json.loads(result.stdout)["runs"][0]
    assert row["source"] == "local" and row["error"] == "boom"
    assert "error: boom" in result.stderr


def test_discovery_error_degrades_to_local_view(monkeypatch):
    def _boom(**_k):
        raise github.GitHubError("api down")

    monkeypatch.setattr(github, "list_workflow_runs", _boom)
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_with_pr())
    monkeypatch.setattr(
        github,
        "get_workflow_run",
        lambda *, run_id, repo_root: github.WorkflowRun(
            id=run_id, url="u", status="completed", conclusion="success"
        ),
    )
    recs = [_record("01x", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=recs)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    row = payload["runs"][0]
    assert row["source"] == "local"
    assert row["run"]["status"] == "completed"  # the per-record observe overlay still applies
    assert "run discovery unavailable" in result.stderr


def test_no_refresh_is_cache_only(monkeypatch):
    def _boom(**_k):
        raise AssertionError("must not enumerate GitHub under --no-refresh")

    monkeypatch.setattr(github, "list_workflow_runs", _boom)
    recs = [_record("01x", dispatched_at="2026-06-07T12:00:00Z")]
    result = _invoke_in_repo(["workflow", "run", "list", "--json", "--no-refresh"], records=recs)
    assert result.exit_code == 0
    row = json.loads(result.stdout)["runs"][0]
    assert row["source"] == "local" and row["run"] is None


def test_merged_ordering_is_newest_first(monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_with_pr())
    monkeypatch.setattr(
        github,
        "get_workflow_run",
        lambda *, run_id, repo_root: github.WorkflowRun(
            id=run_id, url="u", status="completed", conclusion="success"
        ),
    )
    monkeypatch.setattr(
        github,
        "list_workflow_runs",
        lambda **_k: [
            _listing(
                "999",
                title=f"perk implement · plan #42 · {_ULID_A}",
                created="2026-06-07T13:00:00Z",
            ),
            _listing(
                "998",
                title=f"perk address · plan #42 · {_ULID_B}",
                created="2026-06-07T11:00:00Z",
            ),
        ],
    )
    recs = [
        _record(_ULID_B, dispatched_at="2026-06-07T11:00:00Z"),  # both (middle)
        _record("01local", dispatched_at="2026-06-07T12:00:00Z"),  # local-only (in between)
        _record("01old", dispatched_at="not-a-timestamp"),  # unparseable — sorts last
    ]
    result = _invoke_in_repo(["workflow", "run", "list", "--json"], records=recs)
    assert result.exit_code == 0
    runs = json.loads(result.stdout)["runs"]
    assert [(r["run_id"], r["source"]) for r in runs] == [
        (_ULID_A, "discovered"),
        ("01local", "local"),
        (_ULID_B, "both"),
        ("01old", "local"),
    ]
