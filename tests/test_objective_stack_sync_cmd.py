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
from perk.delivery import sync, train
from perk.delivery.journal import JournalCorruptionError, mint_operation_id
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
        result=_result(notes=("cleanup left residue",)),
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
        "notes",
        "dry_run",
        "adopted_node",
        "continued",
        "aborted",
    ]
    assert payload["success"] is True
    assert payload["dry_run"] is False and payload["adopted_node"] is None
    assert payload["continued"] is False and payload["aborted"] is False
    assert payload["notes"] == ["cleanup left residue"]
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


def test_reconstruction_failure_maps_to_its_typed_envelope(monkeypatch):
    # TrainReconstructionError's bounded vocabulary passes through verbatim (the
    # stack-status convention) — a transient fetch failure is a typed exit-1 envelope,
    # never an escaped traceback.
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=train.TrainReconstructionError("git fetch failed: boom", error_type="git_error"),
    )
    assert outcome.exit_code == 1
    payload = json.loads(outcome.stdout)
    assert payload == {
        "success": False,
        "error_type": "git_error",
        "message": "git fetch failed: boom",
    }


def test_journal_corruption_maps_to_its_typed_envelope(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=JournalCorruptionError("conflicting prepared events for operation 01X"),
    )
    assert outcome.exit_code == 1
    payload = json.loads(outcome.stdout)
    assert payload["success"] is False
    assert payload["error_type"] == "journal_corruption"


def test_run_id_fallback_follows_supersession_to_the_active_objective(monkeypatch):
    # Syncing through a superseded objective must journal the ACTIVE objective's run
    # identity, never the predecessor's.
    class _Store:
        def get_objective(self, *, objective_id: str):
            if objective_id == "1431":
                return ObjectiveState(
                    id="1431",
                    url=_URL,
                    title="old",
                    header={"run_id": "01OLDRUN", "superseded_by": "1500"},
                    nodes=(),
                )
            assert objective_id == "1500"
            return ObjectiveState(
                id="1500", url=_URL, title="active", header={"run_id": "01ACTIVERUN"}, nodes=()
            )

    monkeypatch.setattr(sync_cmd, "resolve_objective_store", lambda root: _Store())
    _, calls = _invoke(
        ["objective", "stack", "sync", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_result(),
    )
    assert calls[0]["run_id"] == "01ACTIVERUN"


# ----------------------------------------------------------------- the control surface (§8.49)


def _invoke_modes(args, *, monkeypatch, result=None, abort_result=None, continue_result=None):
    """Invoke with ALL THREE operation seams recorded — the flag matrix must route to
    exactly one (or none, on a refusal)."""
    calls: dict[str, list[dict]] = {"sync": [], "continue": [], "abort": []}

    def fake_sync(repo_root, **kwargs):
        calls["sync"].append(kwargs)
        if isinstance(result, Exception):
            raise result
        assert result is not None
        return result

    def fake_continue(repo_root, **kwargs):
        calls["continue"].append(kwargs)
        if isinstance(continue_result, Exception):
            raise continue_result
        assert continue_result is not None
        return continue_result

    def fake_abort(repo_root, **kwargs):
        calls["abort"].append(kwargs)
        if isinstance(abort_result, Exception):
            raise abort_result
        assert abort_result is not None
        return abort_result

    monkeypatch.setattr(sync, "synchronize_train", fake_sync)
    monkeypatch.setattr(sync, "continue_train_sync", fake_continue)
    monkeypatch.setattr(sync, "abort_train_sync", fake_abort)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        outcome = runner.invoke(cli, args)
    return outcome, calls


def test_flag_matrix_refusals(monkeypatch):
    bad = [
        ["--continue", "--abort"],
        ["--continue", "--base"],
        ["--continue", "--dry-run"],
        ["--continue", "--adopt", "1.2"],
        ["--abort", "--base"],
        ["--abort", "--dry-run"],
        ["--abort", "--adopt", "1.2"],
        ["--adopt", "1.2", "--base"],
    ]
    for extra in bad:
        outcome, calls = _invoke_modes(
            ["objective", "stack", "sync", "1431", "--yes", "--json", *extra],
            monkeypatch=monkeypatch,
        )
        assert outcome.exit_code == 1, extra
        assert json.loads(outcome.stdout)["error_type"] == "invalid_input", extra
        assert calls == {"sync": [], "continue": [], "abort": []}, extra  # refused FIRST


def test_dry_run_and_adopt_flags_thread_and_ride_the_envelope(monkeypatch):
    outcome, calls = _invoke_modes(
        [
            "objective",
            "stack",
            "sync",
            "1431",
            "--dry-run",
            "--adopt",
            "1.2",
            "--run-id",
            "01RUN",
            "--json",
        ],
        monkeypatch=monkeypatch,
        result=_result(dry_run=True, adopted_node="1.2", operation_id=None),
    )
    assert outcome.exit_code == 0
    (call,) = calls["sync"]
    assert call["dry_run"] is True and call["adopt_node"] == "1.2"
    payload = json.loads(outcome.stdout)
    assert payload["dry_run"] is True and payload["adopted_node"] == "1.2"


def test_dry_run_is_allowed_non_interactive_without_yes(monkeypatch):
    # The preview stops before the approval boundary, so no confirmation is required —
    # CliRunner stdin is never a tty and --yes is absent.
    outcome, calls = _invoke_modes(
        ["objective", "stack", "sync", "1431", "--dry-run", "--run-id", "01RUN", "--json"],
        monkeypatch=monkeypatch,
        result=_result(dry_run=True, operation_id=None),
    )
    assert outcome.exit_code == 0
    assert calls["sync"][0]["dry_run"] is True


def test_continue_routes_without_consulting_run_id(monkeypatch):
    outcome, calls = _invoke_modes(
        ["objective", "stack", "sync", "1431", "--continue", "--yes", "--json"],
        monkeypatch=monkeypatch,
        continue_result=_result(continued=True),
    )
    assert outcome.exit_code == 0
    assert calls["sync"] == [] and calls["abort"] == []
    (call,) = calls["continue"]
    assert "run_id" not in call  # the manifest's captured run identity is authoritative
    assert isinstance(call["remote_writers"], sync_cmd.GhaRemoteWriterProbe)
    payload = json.loads(outcome.stdout)
    assert payload["continued"] is True and payload["success"] is True


def test_abort_routes_and_rides_the_envelope(monkeypatch):
    outcome, calls = _invoke_modes(
        ["objective", "stack", "sync", "1431", "--abort", "--yes", "--json"],
        monkeypatch=monkeypatch,
        abort_result=_result(aborted=True, operation_id=None, affected=()),
    )
    assert outcome.exit_code == 0
    assert calls["sync"] == [] and calls["continue"] == []
    (call,) = calls["abort"]
    assert "run_id" not in call and "remote_writers" not in call  # abort journals nothing
    payload = json.loads(outcome.stdout)
    assert payload["aborted"] is True and payload["declined"] is False


def _abort_preview(**overrides) -> sync.AbortPreview:
    values: dict = {
        "manifest_path": Path("/main/.perk/workflow/sync-continuations/01L.json"),
        "parseable": True,
        "contained": True,
        "operation_id": "01JOPAAAAAAAAAAAAAAAAAAAAA",
        "conflict_node_id": "1.3",
        "worktree_path": "/wt/sync-01JOPAAAAAAAAAAAAAAAAAAAAA",
    }
    values.update(overrides)
    return sync.AbortPreview(**values)


def test_abort_approve_callback_arms(monkeypatch, capsys):
    # --yes: renders exactly what it approved (worktree, conflict node, operation id).
    approve = sync_cmd._make_abort_approve(yes=True)
    assert approve(_abort_preview()) is True
    err = capsys.readouterr().err
    assert "01JOPAAAAAAAAAAAAAAAAAAAAA" in err and "1.3" in err
    assert "/wt/sync-01JOPAAAAAAAAAAAAAAAAAAAAA" in err

    # Non-interactive without --yes: the typed refusal, before any prompt.
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=False))
    approve = sync_cmd._make_abort_approve(yes=False)
    with pytest.raises(UserFacingCliError) as excinfo:
        approve(_abort_preview())
    assert excinfo.value.error_type == "confirmation_required"

    # Interactive decline: the stderr-only confirm returns the human's answer.
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=True))
    confirms: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        click, "confirm", lambda text, err=False: confirms.append((text, err)) or False
    )
    approve = sync_cmd._make_abort_approve(yes=False)
    assert approve(_abort_preview()) is False
    assert confirms == [("Discard it?", True)]

    # The invalid/unparseable previews name the manifest-only deletion.
    capsys.readouterr()
    approve = sync_cmd._make_abort_approve(yes=True)
    approve(_abort_preview(contained=False))
    assert "ONLY the manifest file" in capsys.readouterr().err
    approve(_abort_preview(parseable=False, operation_id=None))
    assert "UNPARSEABLE" in capsys.readouterr().err


def test_new_sync_error_arms_pass_through_verbatim(monkeypatch):
    for error_type in (
        "operation_in_progress",
        "adopt_blocked",
        "no_continuation",
        "continuation_stale",
        "continuation_invalid",
        "rebase_in_progress",
    ):
        outcome, _ = _invoke(
            ["objective", "stack", "sync", "1431", "--run-id", "01RUN", "--yes", "--json"],
            monkeypatch=monkeypatch,
            result=sync.SyncError("nope", error_type=error_type),
        )
        assert outcome.exit_code == 1
        assert json.loads(outcome.stdout)["error_type"] == error_type


def test_human_dry_run_render(monkeypatch):
    outcome, _ = _invoke_modes(
        ["objective", "stack", "sync", "1431", "--dry-run", "--run-id", "01RUN"],
        monkeypatch=monkeypatch,
        result=_result(dry_run=True, operation_id=None),
    )
    assert "dry run: a real sync would cascade 1 layer(s)" in outcome.stderr
    assert "nothing was journaled, pushed, or retained" in outcome.stderr


def test_human_continued_and_aborted_renders(monkeypatch):
    outcome, _ = _invoke_modes(
        ["objective", "stack", "sync", "1431", "--continue", "--yes"],
        monkeypatch=monkeypatch,
        continue_result=_result(continued=True, notes=("could not retire the manifest",)),
    )
    assert "continued 1 layer(s)" in outcome.stderr
    assert "note: could not retire the manifest" in outcome.stderr

    outcome, _ = _invoke_modes(
        ["objective", "stack", "sync", "1431", "--abort", "--yes"],
        monkeypatch=monkeypatch,
        abort_result=_result(aborted=True, operation_id=None, affected=()),
    )
    assert "retained continuation discarded" in outcome.stderr

    outcome, _ = _invoke_modes(
        ["objective", "stack", "sync", "1431", "--abort", "--yes"],
        monkeypatch=monkeypatch,
        abort_result=_result(aborted=False, declined=True, operation_id=None, affected=()),
    )
    assert "abort declined; everything stays retained" in outcome.stderr
