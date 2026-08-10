"""Tests for ``perk objective stack sync`` (``commands/objective/stack/sync_cmd.py``).

CLI-level via ``CliRunner`` over the full ``cli`` in an isolated repo, with the operation seam
(``sync.synchronize_train``) monkeypatched — the operation itself is pinned in
``test_delivery_sync.py``; here the envelope, confirmation discipline, resolution order, the
remote-writer wiring, exit codes, and the stdout/stderr split are the contract.
"""

import json
import subprocess
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from perk.backends.objective_store import ObjectiveState
from perk.cli.cli import cli
from perk.cli.commands.objective.stack import sync_cmd
from perk.cli.ensure import UserFacingCliError
from perk.delivery import sync
from perk.delivery.journal import mint_operation_id
from perk.github import GitHubError
from perk.github.workflows import WorkflowRun, WorkflowRunListing, _workflow_runs_args
from perk.run import discovery

_URL = "https://github.com/o/r/issues/1431"
B1 = "1" * 40
A1 = "a" * 40


def _synced_layer() -> sync.SyncedLayer:
    return sync.SyncedLayer(
        node_id="1.2",
        plan_id="1457",
        branch="plan-1457",
        pr_number=1465,
        before_sha=B1,
        after_sha=A1,
    )


def _result(**overrides) -> sync.SyncResult:
    values: dict = {
        "objective_id": "1431",
        "objective_url": _URL,
        "redirected_from": None,
        "operation_id": "01JOPAAAAAAAAAAAAAAAAAAAAA",
        "abandoned_operation_id": None,
        "no_op": False,
        "declined": False,
        "resumed": False,
        "base_cascaded": False,
        "base_advanced": False,
        "affected": (_synced_layer(),),
    }
    values.update(overrides)
    return sync.SyncResult(**values)


def _cascade() -> sync.SyncCascade:
    return sync.SyncCascade(
        objective_id="1431",
        base_branch="main",
        include_base=False,
        base_before=None,
        base_after=None,
        layers=(_synced_layer(),),
    )


def _invoke(args, *, monkeypatch, result=None, call_approve=False):
    """Invoke the CLI in an isolated repo with ``synchronize_train`` returning (or raising)
    ``result``; records the call's kwargs. ``call_approve`` drives the injected approval
    callback with a fabricated cascade (declined → the declined result)."""
    calls: list[dict] = []

    def fake_synchronize(repo_root, **kwargs):
        calls.append({"repo_root": repo_root, **kwargs})
        if call_approve and not kwargs["approve"](_cascade()):
            return _result(declined=True, operation_id=None, affected=())
        if isinstance(result, Exception):
            raise result
        assert result is not None, "synchronize_train must not be reached"
        return result

    monkeypatch.setattr(sync, "synchronize_train", fake_synchronize)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        outcome = runner.invoke(cli, args)
    return outcome, calls


# ----------------------------------------------------------------- envelope + exit codes


def test_success_envelope_pins(monkeypatch):
    outcome, calls = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_result(),
    )
    assert outcome.exit_code == 0
    payload = json.loads(outcome.stdout)
    assert list(payload) == [
        "success",
        "objective",
        "operation_id",
        "abandoned_operation_id",
        "no_op",
        "declined",
        "resumed",
        "base_cascaded",
        "base_advanced",
        "affected",
    ]
    assert payload["success"] is True
    assert payload["objective"] == {"id": "1431", "url": _URL, "redirected_from": None}
    assert payload["operation_id"] == "01JOPAAAAAAAAAAAAAAAAAAAAA"
    assert payload["affected"] == [
        {
            "node_id": "1.2",
            "plan_id": "1457",
            "branch": "plan-1457",
            "pr_number": 1465,
            "before_sha": B1,
            "after_sha": A1,
        }
    ]
    (call,) = calls
    assert call["objective_id"] == "1431" and call["run_id"] == "01RUN"
    assert call["include_base"] is False
    assert isinstance(call["worktree_root"], Path)
    assert call["worktree_root"].name == ".worktrees"
    assert isinstance(call["remote_writers"], sync_cmd.GhaRemoteWriterProbe)


def test_typed_failure_envelope_and_exit(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=sync.SyncError("branch drifted", error_type="remote_drift"),
    )
    assert outcome.exit_code == 1
    payload = json.loads(outcome.stdout)
    assert payload == {
        "success": False,
        "error_type": "remote_drift",
        "message": "branch drifted",
    }


def test_include_base_flag_is_threaded(monkeypatch):
    _, calls = _invoke(
        ["objective", "stack", "sync", "1431", "--base", "--run-id", "01RUN", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_result(base_cascaded=True),
    )
    assert calls[0]["include_base"] is True


def test_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        outcome = runner.invoke(
            cli, ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--json"]
        )
    assert outcome.exit_code == 2


# ----------------------------------------------------------------- confirmation discipline


def test_non_interactive_without_yes_is_a_typed_refusal(monkeypatch):
    # CliRunner stdin is never a tty: without --yes the approval callback refuses BEFORE any
    # prompt — never a hang, never a silent push.
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--json"],
        monkeypatch=monkeypatch,
        call_approve=True,
    )
    assert outcome.exit_code == 1
    payload = json.loads(outcome.stdout)
    assert payload["error_type"] == "confirmation_required"


def test_yes_auto_approves_and_renders_the_cascade_to_stderr(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_result(),
        call_approve=True,
    )
    assert outcome.exit_code == 0
    json.loads(outcome.stdout)  # stdout is EXACTLY the machine payload
    assert "plan-1457" in outcome.stderr  # the cascade render went to stderr
    assert f"{B1} → {A1}" in outcome.stderr


def test_declined_is_a_success_envelope(monkeypatch):
    # The decline arm is driven through the fake operation (interactive "n" needs a tty; the
    # callback's tty arms are unit-tested below).
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--json"],
        monkeypatch=monkeypatch,
        result=_result(declined=True, operation_id=None, affected=()),
    )
    assert outcome.exit_code == 0
    payload = json.loads(outcome.stdout)
    assert payload["success"] is True and payload["declined"] is True
    assert payload["operation_id"] is None


class _FakeStdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_approve_callback_tty_confirms_on_stderr(monkeypatch, capsys):
    confirms: list[tuple[str, bool]] = []
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=True))
    monkeypatch.setattr(
        click, "confirm", lambda text, err=False: confirms.append((text, err)) or False
    )
    approve = sync_cmd._make_approve(yes=False)
    assert approve(_cascade()) is False
    assert confirms == [("Push this cascade?", True)]  # err=True: the prompt is stderr-only
    assert "plan-1457" in capsys.readouterr().err


def test_approve_callback_non_tty_refuses(monkeypatch):
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=False))
    approve = sync_cmd._make_approve(yes=False)
    with pytest.raises(UserFacingCliError) as excinfo:
        approve(_cascade())
    assert excinfo.value.error_type == "confirmation_required"


# ----------------------------------------------------------------- resolution


def test_objective_resolution_requires_an_objective(monkeypatch):
    outcome, calls = _invoke(
        ["objective", "stack", "sync", "--run-id", "01RUN", "--json"],
        monkeypatch=monkeypatch,
    )
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "no_objective"
    assert calls == []


def test_run_id_falls_back_to_the_objective_header(monkeypatch):
    class _Store:
        def get_objective(self, *, objective_id: str):
            assert objective_id == "1431"
            return ObjectiveState(
                id="1431", url=_URL, title="T", header={"run_id": "01HEADERRUN"}, nodes=()
            )

    monkeypatch.setattr(sync_cmd, "resolve_objective_store", lambda root: _Store())
    _, calls = _invoke(
        ["objective", "stack", "sync", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_result(),
    )
    assert calls[0]["run_id"] == "01HEADERRUN"


def test_missing_run_id_is_invalid_input(monkeypatch):
    class _Store:
        def get_objective(self, *, objective_id: str):
            return ObjectiveState(id="1431", url=_URL, title="T", header={}, nodes=())

    monkeypatch.setattr(sync_cmd, "resolve_objective_store", lambda root: _Store())
    outcome, calls = _invoke(
        ["objective", "stack", "sync", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
    )
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "invalid_input"
    assert calls == []


# ----------------------------------------------------------------- human rendering


def test_human_success_render(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes"],
        monkeypatch=monkeypatch,
        result=_result(),
    )
    assert outcome.exit_code == 0 and outcome.stdout == ""
    assert "synchronized 1 layer(s)" in outcome.stderr
    assert "deliberately stale" in outcome.stderr


def test_human_no_op_render_with_the_base_hint(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes"],
        monkeypatch=monkeypatch,
        result=_result(no_op=True, operation_id=None, affected=(), base_advanced=True),
    )
    assert "nothing to synchronize" in outcome.stderr
    assert "sync --base" in outcome.stderr


def test_human_declined_render(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN"],
        monkeypatch=monkeypatch,
        result=_result(declined=True, operation_id=None, affected=()),
    )
    assert "cascade declined; nothing pushed" in outcome.stderr


# ----------------------------------------------------------------- the remote-writer wiring


def _listing(title: str, status: str) -> WorkflowRunListing:
    return WorkflowRunListing(
        run=WorkflowRun(id="1", url="u", status=status, conclusion=None),
        title=title,
        created_at="2026-01-01T00:00:00Z",
    )


def test_active_writer_discovery_uses_the_server_side_status_filter(monkeypatch):
    # The pin: one call per active status — an active writer can never be displaced off a
    # newest-first page by completed runs, because completed runs are filtered SERVER-side.
    statuses: list[str | None] = []

    run_token = mint_operation_id()  # the run-name parser requires a real ULID token

    def fake_list(*, workflow, repo_root, limit=100, status=None):
        statuses.append(status)
        if status == "in_progress":
            return [_listing(f"perk implement · plan #1457 · {run_token}", status)]
        return [_listing("unrelated run", status or "queued")]

    monkeypatch.setattr(discovery.github, "list_workflow_runs", fake_list)
    active = discovery.active_writer_plan_ids(Path("/repo"), ["1457", "1458"])
    assert active == frozenset({"1457"})
    assert statuses == ["queued", "in_progress"]


def test_writer_probe_failure_raises_the_typed_error(monkeypatch):
    def boom(*, workflow, repo_root, limit=100, status=None):
        raise GitHubError("api down")

    monkeypatch.setattr(discovery.github, "list_workflow_runs", boom)
    probe = sync_cmd.GhaRemoteWriterProbe(Path("/repo"))
    with pytest.raises(sync.WriterObservationError, match="api down"):
        probe.active_plan_ids(["1457"])


def test_workflow_runs_args_carries_the_status_filter():
    args = _workflow_runs_args("perk-run.yml", per_page=100, status="queued")
    assert (
        args[1]
        == "repos/{owner}/{repo}/actions/workflows/perk-run.yml/runs?per_page=100&status=queued"
    )
    plain = _workflow_runs_args("perk-run.yml", per_page=50)
    assert plain[1] == "repos/{owner}/{repo}/actions/workflows/perk-run.yml/runs?per_page=50"
