"""Tests for the runner-agnostic dispatch contract (contracts.md §8.13)."""

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from perk import github, plan
from perk.run import runner
from perk.state import cache

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
    assert runner.RunHandleModel.from_domain(h).to_domain() == h
    assert (
        runner.RunHandleModel.model_validate(
            runner.RunHandleModel.from_domain(h).model_dump(mode="json")
        ).to_domain()
        == h
    )


def test_run_handle_is_frozen():
    h = runner.RunHandle(runner="ci", kind="github-actions", run_ref="7", url="u")
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.run_ref = "8"  # ty: ignore[invalid-assignment]


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
    # A trigger/discovery failure (e.g. workflow not found) surfaces as RunnerError.
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


def test_retry_shells_gh_run_rerun(monkeypatch):
    seen = []

    def fake_run(args, **_):
        seen.append(args)
        return _Proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    gha = runner.GitHubActionsRunner("")
    gha.retry(
        runner.RunHandle(runner="", kind="github-actions", run_ref="42", url="u"),
        failed_only=False,
        repo_root=ROOT,
    )
    assert seen[0][1:4] == ["run", "rerun", "42"]
    assert "--failed" not in seen[0]


def test_retry_failed_only_appends_flag(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda args, **_: seen.append(args) or _Proc(0))
    runner.GitHubActionsRunner("").retry(
        runner.RunHandle(runner="", kind="github-actions", run_ref="42", url="u"),
        failed_only=True,
        repo_root=ROOT,
    )
    assert seen[0][1:4] == ["run", "rerun", "42"] and "--failed" in seen[0]


def test_retry_wraps_github_error_as_runner_error(monkeypatch):
    def boom(**_k):
        raise github.GitHubError("cannot rerun a run in progress")

    monkeypatch.setattr(runner.github, "rerun_workflow_run", boom)
    gha = runner.GitHubActionsRunner("")
    with pytest.raises(runner.RunnerError):
        gha.retry(
            runner.RunHandle(runner="", kind="github-actions", run_ref="42", url="u"),
            failed_only=False,
            repo_root=ROOT,
        )


# --- select_runner --------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["", "ci-large"])
def test_select_runner_carries_ref(ref):
    r = runner.select_runner(ref)
    assert isinstance(r, runner.GitHubActionsRunner) and r.ref == ref
    assert r.kind == "github-actions"


# --- cache dispatch record round-trip -------------------------------------------------


def test_write_then_read_dispatch_round_trips_and_forces_run_id(tmp_path):
    cache.write_dispatch(
        tmp_path,
        "01RID",
        cache.Dispatch(
            run_id="WRONG",
            stage="implement",
            plan_ref=plan.PlanRef(provider="github", pr_id="7", url="u/7", labels=()),
            runner="",
            kind="github-actions",
            status="dispatched",
            dispatched_at="2024-01-01T00:00:00Z",
        ),
    )
    back = cache.read_dispatch(tmp_path, "01RID")
    assert back is not None and back.run_id == "01RID" and back.stage == "implement"
    assert back.plan_ref.pr_id == "7"


def test_read_dispatch_absent_is_none(tmp_path):
    assert cache.read_dispatch(tmp_path, "nope") is None


# --- parse_run_name (the canonical run-name token; contracts.md §8.13) -----------------

_ULID = "01HZXW8T2M3N4P5Q6R7S8T9V0W"


@pytest.mark.parametrize(
    ("title", "stage", "plan_id"),
    [
        (f"perk implement · plan #42 · {_ULID}", "implement", "42"),
        (f"perk address · plan #42 · {_ULID}", "address", "42"),
        (f"perk implement · plan #ENG-123 · {_ULID}", "implement", "ENG-123"),
        (f"perk smoke · plan #smoke · {_ULID}", "smoke", "smoke"),
    ],
)
def test_parse_run_name_round_trip(title, stage, plan_id):
    parsed = runner.parse_run_name(title)
    assert parsed == runner.ParsedRunName(stage=stage, plan_id=plan_id, run_id=_ULID)


@pytest.mark.parametrize(
    "title",
    [
        "",
        "CI",
        "Deploy to prod",
        f"perk implement plan #42 {_ULID}",  # missing the · separators
        f"perk implement · plan 42 · {_ULID}",  # missing the # sigil
        "perk implement · plan #42 · not-a-ulid",  # bad token
        f"prefix perk implement · plan #42 · {_ULID}",  # not anchored
    ],
)
def test_parse_run_name_rejects_foreign_titles(title):
    assert runner.parse_run_name(title) is None


# --- GitHubActionsRunner.discover ------------------------------------------------------


def _listing(
    run_id, *, title, status="in_progress", conclusion=None, created="2026-06-07T12:00:00Z"
):
    return github.WorkflowRunListing(
        run=github.WorkflowRun(id=run_id, url=f"u/{run_id}", status=status, conclusion=conclusion),
        title=title,
        created_at=created,
    )


def test_discover_maps_listings_and_filters(monkeypatch):
    listings = [
        _listing(
            "9",
            title=f"perk implement · plan #42 · {_ULID}",
            status="completed",
            conclusion="success",
        ),
        _listing("8", title=f"perk smoke · plan #smoke · {_ULID}"),  # smoke — filtered
        _listing("7", title="some unrelated workflow run"),  # unparseable — skipped
        _listing("6", title=f"perk address · plan #ENG-9 · {_ULID}"),
    ]
    seen = {}

    def _list(*, workflow, repo_root, limit):
        seen.update(workflow=workflow, limit=limit)
        return listings

    monkeypatch.setattr(runner.github, "list_workflow_runs", _list)
    got = runner.GitHubActionsRunner("ci-large").discover(repo_root=ROOT, limit=50)
    assert seen == {"workflow": "perk-run.yml", "limit": 50}
    assert [d.handle.run_ref for d in got] == ["9", "6"]  # order preserved, newest-first
    first = got[0]
    assert first.run_id == _ULID and first.stage == "implement" and first.plan_id == "42"
    assert first.status == "completed" and first.conclusion == "success"
    assert first.dispatched_at == "2026-06-07T12:00:00Z"
    assert first.handle == runner.RunHandle(
        runner="ci-large", kind="github-actions", run_ref="9", url="u/9"
    )
    assert got[1].plan_id == "ENG-9" and got[1].stage == "address"


def test_discover_wraps_github_error_as_runner_error(monkeypatch):
    def _boom(**_k):
        raise github.GitHubError("no api")

    monkeypatch.setattr(runner.github, "list_workflow_runs", _boom)
    with pytest.raises(runner.RunnerError):
        runner.GitHubActionsRunner("").discover(repo_root=ROOT, limit=10)
