"""Tests for ``perk objective stack land`` (``commands/objective/stack/land_cmd.py``).

CLI-level via ``CliRunner`` with the seams monkeypatched: the reconstruction seam
(``train.reconstruct_train``) and the assessment seam (``land.assess_land_readiness``) for
the unchanged ``--dry-run`` preview, and the operation seam (``landing.land_train``) for the
bare mutating path — the readiness projection is pinned in ``test_delivery_land.py`` and the
operation protocol in ``test_delivery_landing.py``; here the envelope (declared field
order), consent wiring, run-id resolution, exit codes, and the human renders are the
contract.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.objective_store import ObjectiveState
from perk.cli.cli import cli
from perk.cli.commands.objective.stack import land_cmd, shared
from perk.delivery import land, landing, observe, train
from perk.delivery.finalize import LandFinalization, LearnConsumeUpdate, ObjectiveLandUpdate
from perk.state import cache

_URL = "https://github.com/o/r/issues/1431"
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _no_train() -> train.NoDeliveryTrain:
    return train.NoDeliveryTrain(
        objective_id="1431",
        objective_url=_URL,
        redirected_from=None,
        reason=train.NO_TRAIN_INCREMENTAL_REASON,
    )


def _layer() -> train.TrainLayer:
    return train.TrainLayer(
        node_id="1.1",
        plan_id="100",
        branch="plan-100",
        pr_number=500,
        intent=train.LayerIntent.PLANNED,
        publication=train.LayerPublication.PUBLISHED,
        git=train.LayerGit.SYNCED,
        pr=train.LayerPr.READY,
        membership=train.LayerMembership.NOT_APPLICABLE,
        writer=train.LayerWriter.FREE,
        finalization=train.LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=_SHA_A,
        published_head_sha=_SHA_B,
        observed_remote_head_sha=_SHA_B,
        observed_pr_base="main",
        expected_pr_base="main",
    )


def _train(redirected_from: str | None = None) -> train.DeliveryTrain:
    return train.DeliveryTrain(
        objective_id="1431",
        objective_url=_URL,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        redirected_from=redirected_from,
        layers=(_layer(),),
        published_prefix_len=1,
        unresolved_operation=None,
        findings=(),
        build_readiness=train.BuildReadiness(
            next_node_id=None, ready=False, reason="all layers published"
        ),
    )


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


def _merged_outcome(
    readiness: land.LandReadiness | None = None,
    *,
    outcome: landing.LandOutcomeKind = "merged",
    notes: tuple[str, ...] = (),
    finalized: bool = True,
) -> landing.LandOutcome:
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
            ),
        )
        if outcome == "merged"
        else ()
    )
    return landing.LandOutcome(
        outcome=outcome,
        readiness=readiness if readiness is not None else _readiness(plan_value=_ready_plan()),
        operation_id="01OPERATION" if outcome not in ("declined",) else None,
        merge_async_uuid=None,
        landed_layers=layers,
        objective_closed=outcome == "merged",
        notes=notes,
    )


def _invoke(
    args,
    *,
    monkeypatch,
    reconstruct=None,
    readiness=None,
    git_init=True,
    setup=None,
    land_result=None,
    land_error=None,
    header_run_id="01HEADERRUN",
    authed=True,
):
    """Invoke the CLI in an isolated repo with the seams faked: ``reconstruct`` is the
    ``train.reconstruct_train`` return (or raise), ``readiness`` the assessment's (the
    dry-run path), ``land_result``/``land_error`` the ``landing.land_train`` outcome (the
    mutating path — the fake drives the CLI's ``approve`` callback like the real operation);
    records the objective ids asked for, the assessment's call kwargs, and the land calls."""
    asked: list[str] = []
    assessed: list[dict] = []
    landed: list[dict] = []

    def fake_reconstruct(objective_id, **_kwargs):
        asked.append(objective_id)
        if isinstance(reconstruct, Exception):
            raise reconstruct
        assert reconstruct is not None, "reconstruct_train must not be reached"
        return reconstruct

    def fake_assess(projection, *, observations, remote_writers):
        assessed.append(
            {
                "projection": projection,
                "observations": observations,
                "remote_writers": remote_writers,
            }
        )
        assert readiness is not None, "assess_land_readiness must not be reached"
        return readiness

    def fake_land(repo_root, *, objective_id, run_id, approve, remote_writers, **_kwargs):
        landed.append(
            {
                "objective_id": objective_id,
                "run_id": run_id,
                "remote_writers": remote_writers,
            }
        )
        if isinstance(land_error, Exception):
            raise land_error
        assert land_result is not None, "land_train must not be reached"
        if approve is not None and not approve(land_result.readiness):
            return landing.LandOutcome(
                outcome="declined",
                readiness=land_result.readiness,
                operation_id=None,
                merge_async_uuid=None,
                landed_layers=(),
                objective_closed=False,
                notes=(),
            )
        return land_result

    class _Store:
        def get_objective(self, *, objective_id: str):
            header = {"run_id": header_run_id} if header_run_id else {}
            return ObjectiveState(id=objective_id, url=_URL, title="T", header=header, nodes=())

    monkeypatch.setattr(train, "reconstruct_train", fake_reconstruct)
    monkeypatch.setattr(land, "assess_land_readiness", fake_assess)
    monkeypatch.setattr(landing, "land_train", fake_land)
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
    return outcome, asked, assessed, landed


def test_bare_land_drives_the_mutation_with_yes(monkeypatch):
    # Bare land is no longer the `land_unimplemented` refusal — it routes to land_train.
    result, _, _, landed = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        land_result=_merged_outcome(),
    )
    assert result.exit_code == 0
    (call,) = landed
    assert call["objective_id"] == "1431"
    assert call["run_id"] == "01HEADERRUN"  # the active-header fallback
    assert isinstance(call["remote_writers"], land_cmd.GhaRemoteWriterProbe)
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
        }
    ]
    # --yes still rendered what it approved (the consent preview, stderr).
    assert "land 1 layer(s) atomically" in result.stderr


def test_bare_land_explicit_run_id_wins(monkeypatch):
    _, _, _, landed = _invoke(
        ["objective", "stack", "land", "1431", "--run-id", "01EXPLICIT", "--yes", "--json"],
        monkeypatch=monkeypatch,
        land_result=_merged_outcome(),
    )
    assert landed[0]["run_id"] == "01EXPLICIT"


def test_bare_land_missing_run_id_is_invalid_input(monkeypatch):
    result, _, _, landed = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        header_run_id="",
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"
    assert landed == []  # refused before the operation


def test_bare_land_non_interactive_without_yes_is_confirmation_required(monkeypatch):
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--json"],
        monkeypatch=monkeypatch,
        land_result=_merged_outcome(),
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "confirmation_required"


def test_bare_land_unauthed_refuses(monkeypatch):
    result, _, _, landed = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        authed=False,
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_unauthed"
    assert landed == []


def test_land_blocked_fail_envelope_carries_the_readiness_extra(monkeypatch):
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER, code="pr_behind", message="PR #500 is BEHIND"
    )
    blocked = _readiness(
        disposition=land.LandDisposition.BLOCKED,
        layers=(_row(merge_state_status="BEHIND"),),
        findings=(blocker,),
    )
    error = landing.LandError(
        "objective 1431 is not ready to land: [pr_behind] PR #500 is BEHIND",
        error_type="land_blocked",
        readiness=blocked,
    )
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        land_error=error,
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False and payload["error_type"] == "land_blocked"
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
    error = landing.LandError("not ready", error_type="land_blocked", readiness=blocked)
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        land_error=error,
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "landing readiness — BLOCKED" in result.stderr
    assert "[pr_behind] PR #500 is BEHIND" in result.stderr
    assert "Error: not ready" in result.stderr


def test_typed_land_errors_map_to_the_fail_envelope(monkeypatch):
    error = landing.LandError("endpoint missing", error_type="merge_async_unavailable")
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        land_error=error,
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "success": False,
        "error_type": "merge_async_unavailable",
        "message": "endpoint missing",
    }


def test_pending_outcome_is_an_honest_exit_zero(monkeypatch):
    pending = _merged_outcome(outcome="pending", notes=("the LAND operation is unresolved",))
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes", "--json"],
        monkeypatch=monkeypatch,
        land_result=pending,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True and payload["outcome"] == "pending"
    assert payload["landed_layers"] == [] and payload["objective_closed"] is False
    assert payload["notes"] == ["the LAND operation is unresolved"]


def test_pending_human_render_carries_the_unresolved_guidance(monkeypatch):
    pending = _merged_outcome(outcome="pending", notes=("submission stayed ambiguous",))
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        land_result=pending,
    )
    assert result.exit_code == 0
    assert "note: submission stayed ambiguous" in result.stderr
    assert "the LAND operation is unresolved" in result.stderr
    assert "landing is blocked until it concludes" in result.stderr


def test_merged_human_render(monkeypatch):
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        land_result=_merged_outcome(),
    )
    assert result.exit_code == 0
    assert "landed 1 layer(s) atomically (operation 01OPERATION)" in result.stderr
    assert "1.1 plan #100 (pr #500): merged as cccccccccccc" in result.stderr
    assert "objective #1431 complete — closed" in result.stderr


def test_finalize_failure_renders_loudly(monkeypatch):
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--yes"],
        monkeypatch=monkeypatch,
        land_result=_merged_outcome(finalized=False, notes=("finalize failed for plan #100",)),
    )
    assert "FINALIZE FAILED" in result.stderr
    assert "note: finalize failed for plan #100" in result.stderr


def test_dry_run_ready_envelope(monkeypatch):
    readiness = _readiness(plan_value=_ready_plan())
    result, asked, assessed, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=readiness,
    )
    assert result.exit_code == 0
    assert asked == ["1431"]
    # The production wiring reached the assessment with the projection + real seams.
    (call,) = assessed
    assert call["projection"] is not None and call["projection"].objective_id == "1431"
    assert isinstance(call["observations"], observe.GatewayLandObservations)
    assert isinstance(call["remote_writers"], land_cmd.GhaRemoteWriterProbe)
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
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=readiness,
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
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=readiness,
    )
    layer = json.loads(result.stdout)["layers"][0]
    assert layer["assessed"] is False
    assert layer["observed_state"] is None and layer["unresolved_thread_count"] is None


def test_incremental_objective_is_not_stacked(monkeypatch):
    result, _, assessed, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_no_train(),
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "not_stacked"
    assert train.NO_TRAIN_INCREMENTAL_REASON in payload["message"]
    assert assessed == []


def test_reconstruction_failure_maps_error_type(monkeypatch):
    error = train.TrainReconstructionError("no such objective", error_type="objective_not_found")
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=error,
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "objective_not_found"


def test_no_objective_is_a_typed_failure(monkeypatch):
    result, asked, _, _ = _invoke(
        ["objective", "stack", "land", "--dry-run", "--json"], monkeypatch=monkeypatch
    )
    assert result.exit_code == 1
    assert asked == []
    assert json.loads(result.stdout)["error_type"] == "no_objective"


def test_plan_ref_inference(monkeypatch):
    ref = plan.PlanRef(provider="github", pr_id="1474", url="u", labels=(), objective_id="1431")
    monkeypatch.setattr(cache, "read_plan_ref", lambda _root: ref)
    _, asked, _, _ = _invoke(
        ["objective", "stack", "land", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=_readiness(plan_value=_ready_plan()),
    )
    assert asked == ["1431"]


def test_not_a_repo_exits_two(monkeypatch):
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        git_init=False,
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_redirected_from_rides_the_envelope(monkeypatch):
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "9", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(redirected_from="9"),
        readiness=_readiness(plan_value=_ready_plan()),
    )
    assert json.loads(result.stdout)["objective"]["redirected_from"] == "9"


def test_human_render_ready(monkeypatch):
    readiness = _readiness(capability=True, plan_value=_ready_plan())
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=readiness,
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
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=readiness,
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
    result, _, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=readiness,
    )
    assert result.exit_code == 0
    assert "landing readiness (dry run) — BLOCKED" in result.stderr
    assert "base main: merge rules unobserved" in result.stderr
    assert "2. 1.2 plan #100 no pr not assessed" in result.stderr
    assert "blockers:" in result.stderr
    assert "[merge_rules_unobserved] could not read merge rules" in result.stderr
    assert "information:" in result.stderr
    assert "[unresolved_threads] 2 unresolved" in result.stderr
