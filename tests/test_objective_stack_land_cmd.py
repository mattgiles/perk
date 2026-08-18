"""Tests for ``perk objective stack land`` (``commands/objective/stack/land_cmd.py``).

CLI-level via ``CliRunner`` over the migrated-command convention: a ``Delivery`` subclass
captures the exact ``LandRequest`` + consent callback and returns scripted ``LandResult``s
(or raises scripted ``DeliveryError``s) with ``resolve_delivery`` monkeypatched — the
readiness projection is pinned in ``test_delivery_land.py`` and the operation protocol in
``test_delivery_landing.py``; here the envelope (declared field order), request
reconstruction (objective id, run id), consent wiring, the in-band BLOCKED → ``land_blocked``
mapping, exit codes, and the human renders are the contract.
"""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.objective_store import ObjectiveState
from perk.cli.cli import cli
from perk.cli.commands.objective.stack import land_cmd, shared
from perk.delivery import Delivery, DeliveryError, LandRequest, LandResult, land, landing, train
from perk.delivery.finalize import LandFinalization, LearnConsumeUpdate, ObjectiveLandUpdate
from perk.state import cache

_URL = "https://github.com/o/r/issues/1431"
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _row(**overrides) -> land.LandLayerReadiness:
    values: dict = {
        "node_id": "1.1",
        "plan_id": "100",
        "pr_number": 500,
        "branch": "plan-100",
        "expected_base_ref": "main",
        "expected_head_sha": _SHA_B,
        "base_sha": _SHA_A,
        "assessed": True,
        "observed_state": "OPEN",
        "observed_is_draft": False,
        "observed_base_ref": "main",
        "observed_head_ref": "plan-100",
        "observed_head_sha": _SHA_B,
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "review_decision": "APPROVED",
        "required_checks_failed": (),
        "required_checks_pending": (),
        "optional_checks_failed": (),
        "unresolved_thread_count": 0,
    }
    values.update(overrides)
    return land.LandLayerReadiness(**values)


_RULES = land.MergeRulesView(squash_allowed=True, merge_queue_required=False)


def _readiness(
    *,
    disposition: land.LandDisposition = land.LandDisposition.READY,
    rules: land.MergeRulesView | None = _RULES,
    capability: bool | None = None,
    layers: tuple[land.LandLayerReadiness, ...] | None = None,
    findings: tuple[train.TrainFinding, ...] = (),
    plan_value: land.LandPlan | None = None,
) -> land.LandReadiness:
    return land.LandReadiness(
        objective_id="1431",
        objective_url=_URL,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        disposition=disposition,
        rules=rules,
        native_stack_capability=capability,
        layers=layers if layers is not None else (_row(),),
        findings=findings,
        plan=plan_value,
    )


def _ready_plan() -> land.LandPlan:
    return land.LandPlan(
        mode="singleton_squash",
        merge_method="squash",
        top_pr_number=500,
        top_head_sha=_SHA_B,
        layers=(
            land.LandPlanLayer(
                node_id="1.1", plan_id="100", pr_number=500, base_sha=_SHA_A, head_sha=_SHA_B
            ),
        ),
    )


def _dry_run_result(
    readiness: land.LandReadiness, *, redirected_from: str | None = None
) -> LandResult:
    return LandResult(
        kind="objective",
        objective=LandResult.Objective(
            readiness=readiness, redirected_from=redirected_from, dry_run=True
        ),
    )


def _blocked_result(readiness: land.LandReadiness) -> LandResult:
    """The in-band BLOCKED refusal detail (`outcome: None` on the mutation)."""
    return LandResult(
        kind="objective",
        objective=LandResult.Objective(readiness=readiness, redirected_from=None, dry_run=False),
    )


def _merged_result(
    readiness: land.LandReadiness | None = None,
    *,
    outcome: landing.LandOutcomeKind = "merged",
    notes: tuple[str, ...] = (),
    finalized: bool = True,
) -> LandResult:
    fin = (
        LandFinalization(
            learn_state="pending",
            plan_issue_closed=True,
            objective=ObjectiveLandUpdate("1431", ("1.1",), None),
            learn=LearnConsumeUpdate((), "no_consumed_learn"),
        )
        if finalized
        else None
    )
    layers = (
        (
            landing.LandedLayer(
                node_id="1.1",
                plan_id="100",
                pr_number=500,
                merge_commit_sha="c" * 40,
                finalization=fin,
                base_sha="a" * 40,
                head_sha="b" * 40,
            ),
        )
        if outcome == "merged"
        else ()
    )
    return LandResult(
        kind="objective",
        objective=LandResult.Objective(
            readiness=readiness if readiness is not None else _readiness(plan_value=_ready_plan()),
            redirected_from=None,
            dry_run=False,
            outcome=outcome,
            operation_id="01OPERATION" if outcome not in ("declined",) else None,
            merge_async_uuid=None,
            landed_layers=layers,
            objective_closed=outcome == "merged",
            notes=notes,
        ),
    )


def _invoke(
    args,
    *,
    monkeypatch,
    result: LandResult | None = None,
    error: Exception | None = None,
    git_init=True,
    setup=None,
    header_run_id="01HEADERRUN",
    authed=True,
):
    """Invoke the CLI in an isolated repo with ``resolve_delivery`` monkeypatched to a
    ``Delivery`` subclass that records the exact request + consent callback, raises the
    scripted ``error``, or returns the scripted ``result`` (driving the consent callback
    like the real operation: consent fires on every non-BLOCKED mutation; declining maps
    onto the declined outcome)."""
    calls: list[dict] = []

    class _FakeDelivery(Delivery):
        def __init__(self) -> None:  # no aggregate authorities — every call is scripted
            pass

        def land(self, request: LandRequest, *, consent=None) -> LandResult:
            calls.append({"request": request, "consent": consent})
            if error is not None:
                raise error
            assert result is not None, "Delivery.land must not be reached"
            detail = result.objective
            assert detail is not None
            if (
                not request.dry_run
                and consent is not None
                and detail.outcome is not None
                and not consent(detail.readiness)
            ):
                return LandResult(
                    kind="objective",
                    objective=replace(
                        detail,
                        outcome="declined",
                        operation_id=None,
                        merge_async_uuid=None,
                        landed_layers=(),
                        objective_closed=False,
                        notes=(),
                        reconcile_evidence=None,
                    ),
                )
            return result

    class _Store:
        def get_objective(self, *, objective_id: str):
            header = {"run_id": header_run_id} if header_run_id else {}
            return ObjectiveState(id=objective_id, url=_URL, title="T", header=header, nodes=())

    monkeypatch.setattr(land_cmd, "resolve_delivery", lambda _root: _FakeDelivery())
    monkeypatch.setattr(shared, "resolve_objective_store", lambda root: _Store())
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(authed, "octocat", ("repo",), None)
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git_init:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        if setup is not None:
            setup(Path(d))
        outcome = runner.invoke(cli, args)
    return outcome, calls


def test_bare_land_drives_the_mutation_with_yes(monkeypatch):
    result, calls = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_merged_result(),
    )
    assert result.exit_code == 0
    (call,) = calls
    request = call["request"]
    # The exact reconstructed caller intent (the run-id header fallback) + a live consent.
    assert request == LandRequest(
        kind="objective", objective_id="1431", run_id="01HEADERRUN", dry_run=False
    )
    assert call["consent"] is not None
    payload = json.loads(result.stdout)
    # The mutation envelope's declared field order is load-bearing (trailing growth only).
    assert list(payload) == [
        "success",
        "error_type",
        "objective",
        "dry_run",
        "disposition",
        "base",
        "delivery_lineage",
        "rules",
        "native_stack_capability",
        "layers",
        "blockers",
        "information",
        "plan",
        "outcome",
        "operation_id",
        "merge_async_uuid",
        "landed_layers",
        "objective_closed",
        "notes",
        "reconcile_evidence",
    ]
    assert payload["success"] is True and payload["dry_run"] is False
    assert payload["outcome"] == "merged"
    assert payload["operation_id"] == "01OPERATION"
    assert payload["objective_closed"] is True
    assert payload["landed_layers"] == [
        {
            "node_id": "1.1",
            "plan_id": "100",
            "pr_number": 500,
            "merge_commit_sha": "c" * 40,
            "learn_state": "pending",
            "plan_issue_closed": True,
            "nodes_marked": ["1.1"],
            "finalized": True,
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
        }
    ]
    # --yes still rendered what it approved (the consent preview, stderr).
    assert "land 1 layer(s) atomically" in result.stderr


def test_bare_land_explicit_run_id_wins(monkeypatch):
    _, calls = _invoke(
        ["objective", "stack", "land", "1431", "--run-id", "01EXPLICIT", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_merged_result(),
    )
    assert calls[0]["request"].run_id == "01EXPLICIT"


def test_bare_land_missing_run_id_is_invalid_input(monkeypatch):
    result, calls = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        header_run_id="",
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"
    assert calls == []  # refused before the operation


def test_bare_land_non_interactive_without_yes_is_confirmation_required(monkeypatch):
    # The consent callback runs against the scripted readiness: non-interactive without
    # --yes raises the typed refusal BEFORE any prompt, propagating through the façade.
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_merged_result(),
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "confirmation_required"


def test_bare_land_unauthed_refuses(monkeypatch):
    result, calls = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        authed=False,
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_unauthed"
    assert calls == []


def test_land_blocked_fail_envelope_carries_the_readiness_extra(monkeypatch):
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER, code="pr_behind", message="PR #500 is BEHIND"
    )
    blocked = _readiness(
        disposition=land.LandDisposition.BLOCKED,
        layers=(_row(merge_state_status="BEHIND"),),
        findings=(blocker,),
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=_blocked_result(blocked),
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False and payload["error_type"] == "land_blocked"
    # The blocked message bytes are pinned (the format string moved verbatim from the
    # engine into the CLI mapping).
    assert payload["message"] == (
        "objective 1431 is not ready to land: [pr_behind] PR #500 is BEHIND"
    )
    readiness_extra = payload["readiness"]
    assert readiness_extra["disposition"] == "blocked"
    assert readiness_extra["dry_run"] is False
    assert readiness_extra["blockers"][0]["code"] == "pr_behind"
    assert list(readiness_extra)[:13] == [
        "success",
        "error_type",
        "objective",
        "dry_run",
        "disposition",
        "base",
        "delivery_lineage",
        "rules",
        "native_stack_capability",
        "layers",
        "blockers",
        "information",
        "plan",
    ]


def test_land_blocked_human_renders_the_readiness_report(monkeypatch):
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER, code="pr_behind", message="PR #500 is BEHIND"
    )
    blocked = _readiness(disposition=land.LandDisposition.BLOCKED, findings=(blocker,))
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        result=_blocked_result(blocked),
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "landing readiness — BLOCKED" in result.stderr
    assert "[pr_behind] PR #500 is BEHIND" in result.stderr
    assert "Error: objective 1431 is not ready to land: [pr_behind] PR #500" in result.stderr


def test_typed_land_errors_map_to_the_fail_envelope(monkeypatch):
    error = DeliveryError(
        "endpoint missing",
        error_type="merge_async_unavailable",
        phase="land",
        origin="domain",
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        error=error,
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "success": False,
        "error_type": "merge_async_unavailable",
        "message": "endpoint missing",
    }


def test_pending_outcome_is_an_honest_exit_zero(monkeypatch):
    pending = _merged_result(outcome="pending", notes=("the LAND operation is unresolved",))
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=pending,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True and payload["outcome"] == "pending"
    assert payload["landed_layers"] == [] and payload["objective_closed"] is False
    assert payload["notes"] == ["the LAND operation is unresolved"]


def test_pending_human_render_carries_the_unresolved_guidance(monkeypatch):
    pending = _merged_result(outcome="pending", notes=("submission stayed ambiguous",))
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        result=pending,
    )
    assert result.exit_code == 0
    assert "note: submission stayed ambiguous" in result.stderr
    assert "the LAND operation is unresolved" in result.stderr
    assert "landing is blocked until it concludes" in result.stderr


def test_merged_human_render(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        result=_merged_result(),
    )
    assert result.exit_code == 0
    assert "landed 1 layer(s) atomically (operation 01OPERATION)" in result.stderr
    assert "1.1 plan #100 (pr #500): merged as cccccccccccc" in result.stderr
    assert "objective #1431 complete — closed" in result.stderr


def test_finalize_failure_renders_loudly(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        result=_merged_result(finalized=False, notes=("finalize failed for plan #100",)),
    )
    assert "FINALIZE FAILED" in result.stderr
    assert "note: finalize failed for plan #100" in result.stderr


def _evidence() -> landing.LandEvidence:
    return landing.LandEvidence(
        layers=(
            landing.LandEvidenceLayer(
                node_id="1.1",
                plan_id="100",
                pr_number=500,
                base_sha="a" * 40,
                head_sha="b" * 40,
                merge_commit_sha="c" * 40,
            ),
        ),
        final_base_sha="c" * 40,
        partial=False,
        notes=(),
    )


def _with_evidence(result: LandResult) -> LandResult:
    detail = result.objective
    assert detail is not None
    return LandResult(kind="objective", objective=replace(detail, reconcile_evidence=_evidence()))


def test_merged_close_carries_reconcile_evidence(monkeypatch):
    outcome = _with_evidence(_merged_result())
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        result=outcome,
    )
    payload = json.loads(result.stdout)
    assert payload["reconcile_evidence"] == {
        "layers": [
            {
                "node_id": "1.1",
                "plan_id": "100",
                "pr_number": 500,
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "merge_commit_sha": "c" * 40,
            }
        ],
        "final_base_sha": "c" * 40,
        "partial": False,
        "notes": [],
    }
    # The human render prints the evidence summary + the reconcile hint.
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        result=outcome,
    )
    assert "reconcile evidence: 1 layer(s), final base cccccccccccc" in result.stderr
    assert "reconcile objective #1431 with /objective-reconcile" in result.stderr


def test_nothing_to_land_render_is_honest_about_a_skipped_close(monkeypatch):
    # completed_without_merge with objective_closed=False (already closed, or the close
    # was deferred) must never announce a close — and still renders any evidence summary.
    detail = LandResult.Objective(
        readiness=_readiness(
            disposition=land.LandDisposition.NOTHING_TO_LAND, layers=(), plan_value=None
        ),
        redirected_from=None,
        dry_run=False,
        outcome="completed_without_merge",
        operation_id=None,
        merge_async_uuid=None,
        landed_layers=(),
        objective_closed=False,
        notes=(),
        reconcile_evidence=_evidence(),
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        result=LandResult(kind="objective", objective=detail),
    )
    assert result.exit_code == 0
    assert "nothing to merge — objective #1431 was NOT closed (see notes)" in result.stderr
    assert "closed as complete" not in result.stderr
    assert "reconcile objective #1431 with /objective-reconcile" in result.stderr


def test_nothing_to_land_preview_names_the_landed_arm(monkeypatch):
    # The consent preview for a plan-less readiness covers the all-LANDED train too.
    detail = LandResult.Objective(
        readiness=_readiness(
            disposition=land.LandDisposition.NOTHING_TO_LAND, layers=(), plan_value=None
        ),
        redirected_from=None,
        dry_run=False,
        outcome="completed_without_merge",
        operation_id=None,
        merge_async_uuid=None,
        landed_layers=(),
        objective_closed=True,
        notes=(),
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        result=LandResult(kind="objective", objective=detail),
    )
    assert result.exit_code == 0
    assert "every layer is skipped or already landed" in result.stderr
    assert "nothing to merge — objective #1431 closed as complete" in result.stderr


def test_dry_run_ready_envelope(monkeypatch):
    readiness = _readiness(plan_value=_ready_plan())
    result, calls = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(readiness),
    )
    assert result.exit_code == 0
    # One façade call: the dry-run request carries no run id and no consent callback.
    (call,) = calls
    assert call["request"] == LandRequest(kind="objective", objective_id="1431", dry_run=True)
    assert call["consent"] is None
    payload = json.loads(result.stdout)
    # The declared envelope field order is load-bearing — the §8.56 mutation fields grow
    # strictly at the tail (nulls/empties on the dry-run path).
    assert list(payload) == [
        "success",
        "error_type",
        "objective",
        "dry_run",
        "disposition",
        "base",
        "delivery_lineage",
        "rules",
        "native_stack_capability",
        "layers",
        "blockers",
        "information",
        "plan",
        "outcome",
        "operation_id",
        "merge_async_uuid",
        "landed_layers",
        "objective_closed",
        "notes",
        "reconcile_evidence",
    ]
    assert payload["outcome"] is None and payload["operation_id"] is None
    assert payload["merge_async_uuid"] is None
    assert payload["landed_layers"] == [] and payload["notes"] == []
    assert payload["objective_closed"] is False
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["objective"] == {"id": "1431", "url": _URL, "redirected_from": None}
    assert payload["dry_run"] is True
    assert payload["disposition"] == "ready"
    assert payload["base"] == "main"
    assert payload["rules"] == {"squash_allowed": True, "merge_queue_required": False}
    assert payload["native_stack_capability"] is None
    assert list(payload["layers"][0]) == [
        "node_id",
        "plan_id",
        "pr_number",
        "branch",
        "expected_base_ref",
        "expected_head_sha",
        "base_sha",
        "assessed",
        "observed_state",
        "observed_is_draft",
        "observed_base_ref",
        "observed_head_ref",
        "observed_head_sha",
        "mergeable",
        "merge_state_status",
        "review_decision",
        "required_checks_failed",
        "required_checks_pending",
        "optional_checks_failed",
        "unresolved_thread_count",
        "landed",
    ]
    assert payload["blockers"] == [] and payload["information"] == []
    assert payload["plan"] == {
        "mode": "singleton_squash",
        "merge_method": "squash",
        "top_pr_number": 500,
        "top_head_sha": _SHA_B,
        "layers": [
            {
                "node_id": "1.1",
                "plan_id": "100",
                "pr_number": 500,
                "base_sha": _SHA_A,
                "head_sha": _SHA_B,
            }
        ],
    }
    assert result.stderr == ""


def test_dry_run_blocked_envelope_still_exits_zero(monkeypatch):
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER,
        code="pr_behind",
        message="PR #500 is BEHIND its base (update it)",
        node_id="1.1",
        plan_id="100",
    )
    readiness = _readiness(
        disposition=land.LandDisposition.BLOCKED,
        layers=(_row(merge_state_status="BEHIND"),),
        findings=(blocker,),
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(readiness),
    )
    assert result.exit_code == 0  # a blocked verdict is a successful DETECTION
    payload = json.loads(result.stdout)
    assert payload["disposition"] == "blocked"
    assert payload["plan"] is None
    assert payload["blockers"] == [
        {
            "code": "pr_behind",
            "message": "PR #500 is BEHIND its base (update it)",
            "node_id": "1.1",
            "plan_id": "100",
        }
    ]


def test_unassessed_row_serializes_its_nulls(monkeypatch):
    row = _row(
        assessed=False,
        pr_number=None,
        observed_state=None,
        observed_is_draft=None,
        observed_base_ref=None,
        observed_head_ref=None,
        observed_head_sha=None,
        mergeable=None,
        merge_state_status=None,
        review_decision=None,
        unresolved_thread_count=None,
    )
    readiness = _readiness(disposition=land.LandDisposition.BLOCKED, layers=(row,))
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(readiness),
    )
    layer = json.loads(result.stdout)["layers"][0]
    assert layer["assessed"] is False
    assert layer["observed_state"] is None and layer["unresolved_thread_count"] is None


def test_incremental_objective_is_not_stacked(monkeypatch):
    # The engine's dry-run message shape for a train-less objective, mapped straight
    # through the DeliveryError ladder.
    error = DeliveryError(
        f"Objective #1431: {train.NO_TRAIN_INCREMENTAL_REASON}",
        error_type="not_stacked",
        phase="land",
        origin="domain",
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        error=error,
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "not_stacked"
    assert train.NO_TRAIN_INCREMENTAL_REASON in payload["message"]


def test_reconstruction_failure_maps_error_type(monkeypatch):
    # The façade boundary keeps the reconstruction code (recover precedent) — the CLI
    # envelope preserves it byte-for-byte.
    error = DeliveryError(
        "no such objective", error_type="objective_not_found", phase="land", origin="domain"
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        error=error,
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "objective_not_found"


def test_no_objective_is_a_typed_failure(monkeypatch):
    result, calls = _invoke(
        ["objective", "stack", "land", "--dry-run", "--json"], monkeypatch=monkeypatch
    )
    assert result.exit_code == 1
    assert calls == []
    assert json.loads(result.stdout)["error_type"] == "no_objective"


def test_plan_ref_inference(monkeypatch):
    ref = plan.PlanRef(provider="github", pr_id="1474", url="u", labels=(), objective_id="1431")
    monkeypatch.setattr(cache, "read_plan_ref", lambda _root: ref)
    _, calls = _invoke(
        ["objective", "stack", "land", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(_readiness(plan_value=_ready_plan())),
    )
    assert calls[0]["request"].objective_id == "1431"


def test_not_a_repo_exits_two(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        git_init=False,
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_redirected_from_rides_the_envelope(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "land", "9", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(_readiness(plan_value=_ready_plan()), redirected_from="9"),
    )
    assert json.loads(result.stdout)["objective"]["redirected_from"] == "9"


def test_human_render_ready(monkeypatch):
    readiness = _readiness(capability=True, plan_value=_ready_plan())
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(readiness),
    )
    assert result.exit_code == 0
    assert result.stdout == ""  # human render is stderr-only
    assert "landing readiness (dry run) — READY" in result.stderr
    assert "base main: squash allowed, merge queue not required" in result.stderr
    assert "native stack API surface: present" in result.stderr
    assert (
        "1. 1.1 plan #100 pr #500 OPEN ready base main head-ref plan-100 head bbbbbbbbbbbb"
        in result.stderr
    )
    assert "MERGEABLE/CLEAN review APPROVED" in result.stderr
    assert "plan: singleton_squash via squash — top pr #500 at bbbbbbbbbbbb" in result.stderr
    assert "no findings" in result.stderr


def test_human_render_shows_the_head_ref_mismatch(monkeypatch):
    readiness = _readiness(
        disposition=land.LandDisposition.BLOCKED,
        layers=(_row(observed_head_ref="other-branch"),),
        findings=(
            train.TrainFinding(kind=train.FindingKind.BLOCKER, code="wrong_head_ref", message="m"),
        ),
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(readiness),
    )
    assert "head-ref other-branch (expected plan-100)" in result.stderr


def test_human_render_blocked_with_unobserved_rules_and_unassessed_row(monkeypatch):
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER,
        code="merge_rules_unobserved",
        message="could not read merge rules for base 'main': HTTP 500",
    )
    info = train.TrainFinding(
        kind=train.FindingKind.INFO, code="unresolved_threads", message="2 unresolved"
    )
    readiness = _readiness(
        disposition=land.LandDisposition.BLOCKED,
        rules=None,
        layers=(
            _row(),
            _row(node_id="1.2", assessed=False, pr_number=None),
        ),
        findings=(blocker, info),
    )
    result, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run"],
        monkeypatch=monkeypatch,
        result=_dry_run_result(readiness),
    )
    assert result.exit_code == 0
    assert "landing readiness (dry run) — BLOCKED" in result.stderr
    assert "base main: merge rules unobserved" in result.stderr
    assert "2. 1.2 plan #100 no pr not assessed" in result.stderr
    assert "blockers:" in result.stderr
    assert "[merge_rules_unobserved] could not read merge rules" in result.stderr
    assert "information:" in result.stderr
    assert "[unresolved_threads] 2 unresolved" in result.stderr
