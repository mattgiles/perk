"""The `perk doctor workflow smoke-test` core logic (Node 3.3; contracts.md §8.19)."""

from pathlib import Path

from perk import github
from perk.github import GitHubError, WorkflowRun
from perk.run import runner
from perk.run import workflow_smoke as ws


def _wr(**kw) -> WorkflowRun:
    base = {"id": "555", "url": "u/runs/555", "status": "queued", "conclusion": None}
    base.update(kw)
    return WorkflowRun(**base)


# --- dispatch_smoke -------------------------------------------------------------------------


def test_dispatch_smoke_sends_smoke_inputs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github, "default_branch", lambda root: "trunk")
    captured = {}

    def fake_trigger(*, repo_root, workflow, inputs, ref, match_token, sleep):
        captured.update(inputs=inputs, workflow=workflow, ref=ref, token=match_token)
        return _wr(id="999", url="u/runs/999", status="in_progress")

    monkeypatch.setattr(github, "trigger_workflow", fake_trigger)
    result = ws.dispatch_smoke(tmp_path)
    assert isinstance(result, ws.SmokeDispatch)
    assert result.run_ref == "999"
    assert result.url == "u/runs/999"
    assert captured["workflow"] == runner.GITHUB_ACTIONS_WORKFLOW
    assert captured["inputs"]["smoke"] == "true"
    assert captured["inputs"]["stage"] == "smoke"
    assert captured["inputs"]["plan"] == "smoke"
    assert captured["inputs"]["base"] == "trunk"
    assert captured["ref"] == "trunk"
    # The run_id is minted, embedded in inputs, and used as the discovery token.
    assert captured["inputs"]["run_id"] == result.run_id == captured["token"]


def test_dispatch_smoke_falls_back_to_main_on_default_branch_error(monkeypatch, tmp_path: Path):
    def boom(root):
        raise GitHubError("no remote")

    monkeypatch.setattr(github, "default_branch", boom)
    seen = {}
    monkeypatch.setattr(
        github,
        "trigger_workflow",
        lambda **kw: (seen.update(kw), _wr())[1],
    )
    result = ws.dispatch_smoke(tmp_path)
    assert isinstance(result, ws.SmokeDispatch)
    assert seen["inputs"]["base"] == "main"
    assert seen["ref"] == "main"


def test_dispatch_smoke_maps_github_error_to_smoke_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github, "default_branch", lambda root: "main")

    def boom(**kw):
        raise GitHubError("run was skipped")

    monkeypatch.setattr(github, "trigger_workflow", boom)
    result = ws.dispatch_smoke(tmp_path)
    assert isinstance(result, ws.SmokeError)
    assert result.step == "dispatch"
    assert "skipped" in result.message


# --- poll_smoke -----------------------------------------------------------------------------


def test_poll_smoke_returns_conclusion_on_completion(monkeypatch, tmp_path: Path):
    seq = iter(
        [
            _wr(status="queued"),
            _wr(status="in_progress"),
            _wr(status="completed", conclusion="success", url="u/runs/555"),
        ]
    )
    monkeypatch.setattr(github, "get_workflow_run", lambda *, run_id, repo_root: next(seq))
    slept: list[float] = []
    result = ws.poll_smoke(tmp_path, "555", "u/orig", sleep=slept.append, now=lambda: 0.0)
    assert not result.timed_out
    assert result.conclusion == "success"
    assert result.url == "u/runs/555"
    assert slept == [ws.POLL_INTERVAL_S, ws.POLL_INTERVAL_S]


def test_poll_smoke_times_out(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        github, "get_workflow_run", lambda *, run_id, repo_root: _wr(status="in_progress")
    )
    # A monotonic clock that jumps past the timeout on the second read.
    clock = iter([0.0, 0.0, ws.POLL_TIMEOUT_S + 1])
    result = ws.poll_smoke(tmp_path, "555", "u/orig", sleep=lambda s: None, now=lambda: next(clock))
    assert result.timed_out
    assert result.conclusion is None
    assert result.url == "u/orig"


def test_poll_smoke_handles_missing_run(monkeypatch, tmp_path: Path):
    # `get_workflow_run` may return None transiently; the loop tolerates it then times out.
    monkeypatch.setattr(github, "get_workflow_run", lambda *, run_id, repo_root: None)
    clock = iter([0.0, ws.POLL_TIMEOUT_S + 1])
    result = ws.poll_smoke(tmp_path, "555", "u/orig", sleep=lambda s: None, now=lambda: next(clock))
    assert result.timed_out


# --- cancel_smoke ---------------------------------------------------------------------------


def test_cancel_smoke_swallows_github_error(monkeypatch, tmp_path: Path):
    def boom(*, run_id, repo_root):
        raise GitHubError("already done")

    monkeypatch.setattr(github, "cancel_workflow_run", boom)
    ws.cancel_smoke(tmp_path, "555")  # must not raise


def test_cancel_smoke_calls_gateway(monkeypatch, tmp_path: Path):
    seen = {}
    monkeypatch.setattr(
        github, "cancel_workflow_run", lambda *, run_id, repo_root: seen.update(run_id=run_id)
    )
    ws.cancel_smoke(tmp_path, "777")
    assert seen == {"run_id": "777"}
