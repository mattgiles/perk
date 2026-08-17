"""Tests for ``perk objective stack recover`` (``commands/objective/stack/recover_cmd.py``).

CLI-level via ``CliRunner`` over the full ``cli`` in an isolated repo, with the operation
façade (``Delivery.recover``) monkeypatched — the operation itself is pinned in
``test_delivery_recover.py``; here the envelope, flag matrix, confirmation discipline,
resolution parity, exit codes, and the stdout/stderr split are the contract.
"""

import json
import subprocess

import click
import pytest
from click.testing import CliRunner

from perk import plan
from perk.cli.cli import cli
from perk.cli.commands.objective.stack import recover_cmd
from perk.cli.ensure import UserFacingCliError
from perk.delivery import DeliveryError, RecoverRequest, RecoverResult, landing
from perk.state import cache

_URL = "https://github.com/o/r/issues/1431"


def _row(**overrides) -> RecoverResult.Operation:
    values: dict = {
        "operation_id": "01JOPAAAAAAAAAAAAAAAAAAAAA",
        "kind": "sync",
        "prepared_created": "2026-01-01T00:00:00Z",
        "classification": "all_after",
        "action": "rolled_forward",
        "detail": "every recorded ref verified at its prepared after state",
    }
    values.update(overrides)
    return RecoverResult.Operation(**values)


def _result(**overrides) -> RecoverResult:
    values: dict = {
        "kind": "operation_conclusion",
        "objective_id": "1431",
        "objective_url": _URL,
        "redirected_from": None,
        "dry_run": False,
        "selection_required": False,
        "operations": (_row(),),
        "swept_worktrees": (),
        "swept_refs": (),
        "sweep_failures": (),
        "sweep_skipped": None,
    }
    values.update(overrides)
    return RecoverResult(**values)


def _invoke(args, *, monkeypatch, result=None):
    """Invoke the CLI with one recording delivery façade."""
    calls: list[dict] = []
    resolved: dict[str, object] = {}

    class _Service:
        def recover(self, request: RecoverRequest, *, consent):
            calls.append(
                {"repo_root": resolved["repo_root"], "request": request, "consent": consent}
            )
            if isinstance(result, Exception):
                raise result
            assert result is not None, "Delivery.recover must not be reached"
            return result

    def resolve(repo_root):
        resolved["repo_root"] = repo_root
        return _Service()

    monkeypatch.setattr(recover_cmd, "resolve_delivery", resolve)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        outcome = runner.invoke(cli, args)
    return outcome, calls


# ----------------------------------------------------------------- envelope + exit codes


def test_success_envelope_pins(monkeypatch):
    outcome, calls = _invoke(
        ["objective", "stack", "recover", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_result(
            swept_worktrees=("/wt/sync-01X",),
            swept_refs=("refs/perk/sync/01X/plan-1457",),
            sweep_failures=(
                RecoverResult.SweepFailure(target="refs/perk/sync/01Y/x", error="boom"),
            ),
        ),
    )
    assert outcome.exit_code == 0
    payload = json.loads(outcome.stdout)
    assert list(payload) == [
        "success",
        "objective",
        "dry_run",
        "selection_required",
        "operations",
        "swept_worktrees",
        "swept_refs",
        "sweep_failures",
        "sweep_skipped",
        "landed_layers",
        "objective_closed",
        "reconcile_evidence",
        "notes",
    ]
    assert payload["success"] is True
    assert payload["objective"] == {"id": "1431", "url": _URL, "redirected_from": None}
    assert payload["operations"] == [
        {
            "operation_id": "01JOPAAAAAAAAAAAAAAAAAAAAA",
            "kind": "sync",
            "prepared_created": "2026-01-01T00:00:00Z",
            "classification": "all_after",
            "action": "rolled_forward",
            "detail": "every recorded ref verified at its prepared after state",
            "merged_layers": [],
            "remainder": [],
        }
    ]
    assert payload["landed_layers"] == []
    assert payload["objective_closed"] is False
    assert payload["reconcile_evidence"] is None
    assert payload["notes"] == []
    assert payload["swept_worktrees"] == ["/wt/sync-01X"]
    assert payload["swept_refs"] == ["refs/perk/sync/01X/plan-1457"]
    assert payload["sweep_failures"] == [{"target": "refs/perk/sync/01Y/x", "error": "boom"}]
    assert payload["sweep_skipped"] is None
    (call,) = calls
    assert call["request"] == RecoverRequest(kind="operation_conclusion", objective_id="1431")
    assert callable(call["consent"])
    assert "run_id" not in call and "worktree_root" not in call


def test_flags_thread_through(monkeypatch):
    _, calls = _invoke(
        [
            "objective",
            "stack",
            "recover",
            "1431",
            "--operation",
            "01JOPAAAAAAAAAAAAAAAAAAAAA",
            "--abandon",
            "--yes",
            "--json",
        ],
        monkeypatch=monkeypatch,
        result=_result(operations=(_row(classification="all_before", action="abandoned"),)),
    )
    (call,) = calls
    assert call["request"] == RecoverRequest(
        kind="operation_conclusion",
        objective_id="1431",
        action="abandon",
        operation_id="01JOPAAAAAAAAAAAAAAAAAAAAA",
    )
    assert callable(call["consent"])


def test_blank_operation_reaches_service_and_returns_typed_not_found(monkeypatch):
    outcome, calls = _invoke(
        ["objective", "stack", "recover", "1431", "--operation", "", "--json"],
        monkeypatch=monkeypatch,
        result=DeliveryError("operation  is not unresolved", error_type="operation_not_found"),
    )

    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "operation_not_found"
    assert calls[0]["request"].operation_id == ""
    assert "Traceback" not in outcome.output


def test_dry_run_with_abandon_is_invalid_input(monkeypatch):
    def forbidden_config(_ctx):
        raise AssertionError("flag validation must precede config validation")

    monkeypatch.setattr(recover_cmd, "require_config", forbidden_config)
    outcome, calls = _invoke(
        ["objective", "stack", "recover", "1431", "--dry-run", "--abandon", "--json"],
        monkeypatch=monkeypatch,
    )
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "invalid_input"
    assert calls == []  # refused before any observation


def test_eager_config_failure_precedes_objective_and_delivery_resolution(monkeypatch):
    def invalid_config(_ctx):
        raise UserFacingCliError(
            "malformed config: worktree.root must be a string",
            error_type="invalid_input",
        )

    monkeypatch.setattr(recover_cmd, "require_config", invalid_config)
    outcome, calls = _invoke(
        ["objective", "stack", "recover", "1431", "--json"],
        monkeypatch=monkeypatch,
    )

    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout) == {
        "success": False,
        "error_type": "invalid_input",
        "message": "malformed config: worktree.root must be a string",
    }
    assert calls == []


def test_no_run_id_flag_exists():
    runner = CliRunner()
    outcome = runner.invoke(cli, ["objective", "stack", "recover", "--help"])
    assert outcome.exit_code == 0
    assert "--run-id" not in outcome.output
    for flag in ("--dry-run", "--operation", "--abandon", "--yes", "--json"):
        assert flag in outcome.output


def test_typed_refusals_exit_one_verbatim(monkeypatch):
    for error_type in (
        "operation_ambiguous",
        "operation_not_found",
        "abandon_blocked",
        "unsupported_operation_kind",
        "operation_in_progress",
        "not_stacked",
    ):
        outcome, _ = _invoke(
            ["objective", "stack", "recover", "1431", "--json"],
            monkeypatch=monkeypatch,
            result=DeliveryError("nope", error_type=error_type),
        )
        assert outcome.exit_code == 1, error_type
        assert json.loads(outcome.stdout)["error_type"] == error_type


def test_roll_forward_sync_errors_pass_through(monkeypatch):
    # The roll-forward tail raises sync's §8.49 arms — they pass through verbatim.
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=DeliveryError("drifted", error_type="sync_drift"),
    )
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "sync_drift"


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (DeliveryError("authority fetch unavailable", error_type="git_error"), "git_error"),
        (
            DeliveryError("authority PR read unavailable", error_type="github_error"),
            "github_error",
        ),
    ],
)
def test_classification_authority_read_failure_maps_to_the_typed_cli_error(
    monkeypatch, failure, error_type
):
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=failure,
    )
    assert outcome.exit_code == 1
    payload = json.loads(outcome.stdout)
    assert payload["error_type"] == error_type
    assert "authority" in payload["message"]


def test_reconstruction_failure_maps_verbatim(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=DeliveryError("gone", error_type="objective_not_found"),
    )
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "objective_not_found"


def test_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        outcome = runner.invoke(cli, ["objective", "stack", "recover", "1431", "--json"])
    assert outcome.exit_code == 2


def test_selection_required_report_is_success(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_result(
            selection_required=True,
            operations=(_row(action="reported"), _row(operation_id="01OPB", action="reported")),
        ),
    )
    assert outcome.exit_code == 0
    payload = json.loads(outcome.stdout)
    assert payload["selection_required"] is True


# ----------------------------------------------------------------- resolution parity


def test_objective_resolution_requires_an_objective(monkeypatch):
    outcome, calls = _invoke(["objective", "stack", "recover", "--json"], monkeypatch=monkeypatch)
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "no_objective"
    assert calls == []


def test_plan_ref_inference(monkeypatch):
    ref = plan.PlanRef(provider="github", pr_id="1474", url="u", labels=(), objective_id="1431")
    monkeypatch.setattr(cache, "read_plan_ref", lambda _root: ref)
    _, calls = _invoke(
        ["objective", "stack", "recover", "--json"], monkeypatch=monkeypatch, result=_result()
    )
    assert calls[0]["request"].objective_id == "1431"


# ----------------------------------------------------------------- confirmation discipline


class _FakeStdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _preview() -> RecoverResult.AbandonPreview:
    return RecoverResult.AbandonPreview(
        operation_id="01JOPAAAAAAAAAAAAAAAAAAAAA",
        kind="sync",
        prepared_created="2026-01-01T00:00:00Z",
        detail="every recorded ref verified at its prepared before state",
    )


def test_abandon_consent_callback_arms(monkeypatch, capsys):
    # --yes: renders exactly what it approved.
    approve = recover_cmd._make_consent(yes=True)
    assert approve(_preview()) is True
    err = capsys.readouterr().err
    assert "01JOPAAAAAAAAAAAAAAAAAAAAA" in err and "prepared before state" in err

    # Non-interactive without --yes: the typed refusal, before any prompt.
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=False))
    approve = recover_cmd._make_consent(yes=False)
    with pytest.raises(UserFacingCliError) as excinfo:
        approve(_preview())
    assert excinfo.value.error_type == "confirmation_required"

    # Interactive decline: the stderr-only confirm returns the human's answer.
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=True))
    confirms: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        click, "confirm", lambda text, err=False: confirms.append((text, err)) or False
    )
    approve = recover_cmd._make_consent(yes=False)
    assert approve(_preview()) is False
    assert confirms == [("Abandon it?", True)]


def test_json_stdout_purity_with_stderr_confirmation(monkeypatch):
    # The consent render goes to stderr even under --json — stdout stays the pure payload.
    class _Service:
        def recover(self, request: RecoverRequest, *, consent):
            assert request.action == "abandon"
            assert consent(_preview()) is True
            return _result(operations=(_row(classification="all_before", action="abandoned"),))

    monkeypatch.setattr(recover_cmd, "resolve_delivery", lambda repo_root: _Service())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        outcome = runner.invoke(
            cli, ["objective", "stack", "recover", "1431", "--abandon", "--yes", "--json"]
        )
    assert outcome.exit_code == 0
    payload = json.loads(outcome.stdout)  # stdout parses as exactly one JSON document
    assert payload["operations"][0]["action"] == "abandoned"
    assert "Abandon operation" in outcome.stderr


# ----------------------------------------------------------------- human rendering


def test_human_render_rows_and_sweep(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431"],
        monkeypatch=monkeypatch,
        result=_result(
            swept_worktrees=("/wt/sync-01X",),
            swept_refs=("refs/perk/sync/01X/plan-1457",),
        ),
    )
    assert outcome.exit_code == 0 and outcome.stdout == ""
    assert "all_after → rolled_forward" in outcome.stderr
    assert "swept 1 orphaned worktree(s) and 1 orphaned ref(s)" in outcome.stderr


def test_human_dry_run_and_skipped_sweep_renders(monkeypatch):
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431", "--dry-run"],
        monkeypatch=monkeypatch,
        result=_result(dry_run=True, swept_refs=("refs/perk/sync/01X/plan-1457",)),
    )
    assert "dry run: nothing was concluded, journaled, or swept" in outcome.stderr
    assert "would sweep 0 orphaned worktree(s) and 1 orphaned ref(s)" in outcome.stderr

    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431"],
        monkeypatch=monkeypatch,
        result=_result(operations=(), sweep_skipped="unparseable manifest(s) present"),
    )
    assert "no unresolved operations" in outcome.stderr
    assert "sweep skipped: unparseable manifest(s) present" in outcome.stderr


# ----------------------------------------------------------------- the LAND surface (§8.51)


def _accept_preview() -> RecoverResult.AcceptPrefixPreview:
    return RecoverResult.AcceptPrefixPreview(
        operation_id="01JOPAAAAAAAAAAAAAAAAAAAAA",
        prepared_created="2026-01-01T00:00:00Z",
        merged_layers=(
            RecoverResult.MergedPrefix(node_id="1.1", pr_number=201, merge_commit_sha="d" * 40),
        ),
        remainder=(RecoverResult.RemainderPr(pr_number=202, state="OPEN", head_sha="b" * 40),),
        detail="an externally merged contiguous prefix",
    )


def test_accept_prefix_threads_through(monkeypatch):
    _, calls = _invoke(
        ["objective", "stack", "recover", "1431", "--accept-prefix", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_result(
            operations=(_row(classification="external_prefix", action="accepted_prefix"),)
        ),
    )
    (call,) = calls
    assert call["request"].action == "accept_prefix"
    assert callable(call["consent"])


def test_accept_prefix_flag_matrix_refusals(monkeypatch):
    outcome, calls = _invoke(
        ["objective", "stack", "recover", "1431", "--dry-run", "--accept-prefix", "--json"],
        monkeypatch=monkeypatch,
    )
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "invalid_input"
    assert calls == []

    outcome, calls = _invoke(
        ["objective", "stack", "recover", "1431", "--abandon", "--accept-prefix", "--json"],
        monkeypatch=monkeypatch,
    )
    assert outcome.exit_code == 1
    assert json.loads(outcome.stdout)["error_type"] == "invalid_input"
    assert calls == []


def test_accept_consent_callback_arms(monkeypatch, capsys):
    # --yes: renders exactly what it accepts (merged prefix + remainder proof).
    approve = recover_cmd._make_consent(yes=True)
    assert approve(_accept_preview()) is True
    err = capsys.readouterr().err
    assert "degraded-atomicity breach" in err
    assert "merged: 1.1 pr #201" in err and "remainder: pr #202 OPEN" in err

    # Non-interactive without --yes: the typed refusal, before any prompt.
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=False))
    approve = recover_cmd._make_consent(yes=False)
    with pytest.raises(UserFacingCliError) as excinfo:
        approve(_accept_preview())
    assert excinfo.value.error_type == "confirmation_required"

    # Interactive decline: the stderr-only confirm returns the human's answer.
    monkeypatch.setattr(click, "get_text_stream", lambda name: _FakeStdin(tty=True))
    confirms: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        click, "confirm", lambda text, err=False: confirms.append((text, err)) or False
    )
    approve = recover_cmd._make_consent(yes=False)
    assert approve(_accept_preview()) is False
    assert confirms == [("Accept it?", True)]


def test_land_envelope_fields_serialize(monkeypatch):
    evidence = landing.LandEvidence(
        layers=(
            landing.LandEvidenceLayer(
                node_id="1.1",
                plan_id="101",
                pr_number=201,
                base_sha="9" * 40,
                head_sha="b" * 40,
                merge_commit_sha="d" * 40,
            ),
        ),
        final_base_sha="d" * 40,
        partial=False,
        notes=(),
    )
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_result(
            operations=(
                _row(
                    kind="land",
                    classification="external_prefix",
                    action="reported",
                    merged_layers=(
                        RecoverResult.MergedPrefix(
                            node_id="1.1", pr_number=201, merge_commit_sha="d" * 40
                        ),
                    ),
                    remainder=(
                        RecoverResult.RemainderPr(pr_number=202, state="OPEN", head_sha="b" * 40),
                    ),
                ),
            ),
            landed_layers=(
                RecoverResult.LandedLayer(
                    node_id="1.1",
                    plan_id="101",
                    pr_number=201,
                    merge_commit_sha="d" * 40,
                    base_sha="9" * 40,
                    head_sha="b" * 40,
                    finalized=True,
                ),
            ),
            objective_closed=True,
            reconcile_evidence=evidence,
            notes=("objective #1431 is open with every node terminal",),
        ),
    )
    assert outcome.exit_code == 0
    payload = json.loads(outcome.stdout)
    (row,) = payload["operations"]
    assert row["merged_layers"] == [
        {"node_id": "1.1", "pr_number": 201, "merge_commit_sha": "d" * 40}
    ]
    assert row["remainder"] == [{"pr_number": 202, "state": "OPEN", "head_sha": "b" * 40}]
    (landed,) = payload["landed_layers"]
    assert landed == {
        "node_id": "1.1",
        "plan_id": "101",
        "pr_number": 201,
        "merge_commit_sha": "d" * 40,
        "base_sha": "9" * 40,
        "head_sha": "b" * 40,
        "finalized": True,
    }
    assert payload["objective_closed"] is True
    assert payload["reconcile_evidence"] == {
        "layers": [
            {
                "node_id": "1.1",
                "plan_id": "101",
                "pr_number": 201,
                "base_sha": "9" * 40,
                "head_sha": "b" * 40,
                "merge_commit_sha": "d" * 40,
            }
        ],
        "final_base_sha": "d" * 40,
        "partial": False,
        "notes": [],
    }
    assert payload["notes"] == ["objective #1431 is open with every node terminal"]


def test_human_render_landed_layers_close_and_evidence(monkeypatch):
    evidence = landing.LandEvidence(
        layers=(
            landing.LandEvidenceLayer(
                node_id="1.1",
                plan_id="101",
                pr_number=201,
                base_sha="9" * 40,
                head_sha="b" * 40,
                merge_commit_sha="d" * 40,
            ),
        ),
        final_base_sha="d" * 40,
        partial=True,
        notes=("one record was undecodable",),
    )
    outcome, _ = _invoke(
        ["objective", "stack", "recover", "1431"],
        monkeypatch=monkeypatch,
        result=_result(
            operations=(_row(kind="land", action="rolled_forward"),),
            landed_layers=(
                RecoverResult.LandedLayer(
                    node_id="1.1",
                    plan_id="101",
                    pr_number=201,
                    merge_commit_sha="d" * 40,
                    base_sha="9" * 40,
                    head_sha="b" * 40,
                    finalized=False,
                ),
                RecoverResult.LandedLayer(
                    node_id="1.2",
                    plan_id="102",
                    pr_number=202,
                    merge_commit_sha="e" * 40,
                    base_sha="b" * 40,
                    head_sha="c" * 40,
                    finalized=None,
                ),
            ),
            objective_closed=True,
            reconcile_evidence=evidence,
            notes=("finalize failed for plan #101: boom",),
        ),
    )
    assert outcome.exit_code == 0 and outcome.stdout == ""
    err = outcome.stderr
    assert "note: finalize failed for plan #101: boom" in err
    assert "landed 1.1 plan #101 (pr #201" in err and "FINALIZE FAILED" in err
    assert "landed 1.2 plan #102" in err and "would finalize" in err
    assert "objective #1431 complete — closed" in err
    assert "reconcile evidence: 1 layer(s), final base dddddddddddd (PARTIAL — see notes)" in err
    assert "/objective-reconcile" in err
