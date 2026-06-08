"""Tests for the runner-agnostic dispatch contract (Node 2.1; contracts.md §8.13)."""

import json
import subprocess
from pathlib import Path

import pytest

from perk import cache, github, runner

ROOT = Path("/repo")

_PLAN_REF = {"provider": "github", "pr_id": "42", "url": "u/42", "labels": ["perk:plan"]}


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _gh_dispatch_fake(*, runs_payload, dispatch_rc=0, dispatch_stderr=""):
    """A subprocess.run fake for the full dispatch path: default_branch + workflow run + the
    discovery poll. ``runs_payload`` is a list of run dicts (the `.workflow_runs` jq result)."""
    calls = []

    def fake_run(args, **_):
        calls.append(args)
        sub = args[1]
        if sub == "repo":  # default_branch
            return _Proc(0, "main\n")
        if sub == "workflow":  # gh workflow run …
            return _Proc(dispatch_rc, "", dispatch_stderr)
        if sub == "api":  # the discovery poll (.../runs)
            return _Proc(0, json.dumps(runs_payload))
        return _Proc(1)

    return fake_run, calls


# --- value-type round-trips -----------------------------------------------------------


def test_run_handle_round_trip():
    h = runner.RunHandle(runner="ci", kind="github-actions", run_ref="7", url="u")
    assert runner.RunHandle.from_data(h.to_data()) == h


def test_dispatch_record_round_trip():
    rec = runner.DispatchRecord(
        run_id="01ABC",
        stage="implement",
        plan_ref=_PLAN_REF,
        runner="ci",
        kind="github-actions",
        status="dispatched",
        dispatched_at="2026-01-01T00:00:00+00:00",
        run_handle={"run_ref": "7"},
        error=None,
    )
    assert runner.DispatchRecord.from_data(rec.to_data()) == rec


# --- GitHubActionsRunner.dispatch -----------------------------------------------------


def test_dispatch_builds_argv_and_returns_discovered_handle(monkeypatch):
    runs = [{"id": 99, "html_url": "https://gh/run/99", "status": "queued", "display_title": "x"}]
    runs[0]["display_title"] = "perk implement (01TOKEN)"
    fake, calls = _gh_dispatch_fake(runs_payload=runs)
    monkeypatch.setattr(subprocess, "run", fake)
    gha = runner.GitHubActionsRunner("ci-large")
    handle = gha.dispatch(
        stage="implement", plan_ref=_PLAN_REF, run_id="01TOKEN", base="main", repo_root=ROOT
    )
    assert handle.run_ref == "99" and handle.url == "https://gh/run/99"
    assert handle.runner == "ci-large" and handle.kind == "github-actions"
    workflow_call = next(c for c in calls if c[1] == "workflow")
    assert "perk-run.yml" in workflow_call
    assert "run_id=01TOKEN" in workflow_call and "stage=implement" in workflow_call
    assert "plan=42" in workflow_call and "base=main" in workflow_call


def test_dispatch_wraps_github_error_as_runner_error(monkeypatch):
    # A trigger/discovery failure (e.g. workflow not found until Node 2.2) surfaces as RunnerError.
    def boom(**_k):
        raise github.GitHubError("workflow perk-run.yml not found")

    monkeypatch.setattr(runner.github, "trigger_workflow", boom)
    monkeypatch.setattr(runner.github, "default_branch", lambda _r: "main")
    gha = runner.GitHubActionsRunner("")
    with pytest.raises(runner.RunnerError):
        gha.dispatch(
            stage="implement", plan_ref=_PLAN_REF, run_id="01TOKEN", base="main", repo_root=ROOT
        )


def test_dispatch_raises_on_cancelled_match(monkeypatch):
    runs = [{"id": 5, "display_title": "x (01TOKEN)", "conclusion": "cancelled"}]
    fake, _ = _gh_dispatch_fake(runs_payload=runs)
    monkeypatch.setattr(subprocess, "run", fake)
    gha = runner.GitHubActionsRunner("")
    with pytest.raises(runner.RunnerError):
        gha.dispatch(
            stage="implement", plan_ref=_PLAN_REF, run_id="01TOKEN", base="main", repo_root=ROOT
        )


# --- observe / cancel -----------------------------------------------------------------


def test_observe_maps_gh_run_view(monkeypatch):
    payload = {"databaseId": 42, "url": "u", "status": "completed", "conclusion": "success"}
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(0, json.dumps(payload)))
    gha = runner.GitHubActionsRunner("")
    obs = gha.observe(
        runner.RunHandle(runner="", kind="github-actions", run_ref="42", url="u"), repo_root=ROOT
    )
    assert obs.status == "completed" and obs.conclusion == "success"


def test_cancel_shells_gh_run_cancel(monkeypatch):
    seen = []

    def fake_run(args, **_):
        seen.append(args)
        return _Proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    gha = runner.GitHubActionsRunner("")
    gha.cancel(
        runner.RunHandle(runner="", kind="github-actions", run_ref="42", url="u"), repo_root=ROOT
    )
    assert seen[0][1:4] == ["run", "cancel", "42"]


# --- select_runner --------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["", "ci-large"])
def test_select_runner_carries_ref(ref):
    r = runner.select_runner(ref)
    assert isinstance(r, runner.GitHubActionsRunner) and r.ref == ref
    assert r.kind == "github-actions"


# --- cache dispatch record round-trip -------------------------------------------------


def test_write_then_read_dispatch_round_trips_and_forces_run_id(tmp_path):
    cache.write_dispatch(tmp_path, "01RID", {"run_id": "WRONG", "stage": "implement"})
    back = cache.read_dispatch(tmp_path, "01RID")
    assert back is not None and back["run_id"] == "01RID" and back["stage"] == "implement"


def test_read_dispatch_absent_is_none(tmp_path):
    assert cache.read_dispatch(tmp_path, "nope") is None
