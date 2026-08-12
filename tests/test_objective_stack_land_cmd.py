"""Tests for ``perk objective stack land`` (``commands/objective/stack/land_cmd.py``).

CLI-level via ``CliRunner`` with the reconstruction seam (``train.reconstruct_train``) and the
assessment seam (``land.assess_land_readiness``) monkeypatched — the readiness projection
itself is pinned in ``test_delivery_land.py``; here the ``land_unimplemented`` refusal, the
envelope (declared field order), resolution, exit codes, and the human render are the
contract.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import plan
from perk.cli.cli import cli
from perk.cli.commands.objective.stack import land_cmd
from perk.delivery import land, observe, train
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


def _invoke(
    args,
    *,
    monkeypatch,
    reconstruct=None,
    readiness=None,
    git_init=True,
    setup=None,
):
    """Invoke the CLI in an isolated repo with the two seams faked: ``reconstruct`` is the
    ``train.reconstruct_train`` return (or raise), ``readiness`` the assessment's; records
    the objective ids asked for and the assessment's call kwargs."""
    asked: list[str] = []
    assessed: list[dict] = []

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

    monkeypatch.setattr(train, "reconstruct_train", fake_reconstruct)
    monkeypatch.setattr(land, "assess_land_readiness", fake_assess)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git_init:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        if setup is not None:
            setup(Path(d))
        outcome = runner.invoke(cli, args)
    return outcome, asked, assessed


def test_bare_land_refuses_typed_json(monkeypatch):
    result, asked, assessed = _invoke(
        ["objective", "stack", "land", "1431", "--json"], monkeypatch=monkeypatch
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error_type"] == "land_unimplemented"
    assert "--dry-run" in payload["message"]
    assert asked == [] and assessed == []  # refused before any read


def test_bare_land_refuses_typed_human(monkeypatch):
    result, _, _ = _invoke(["objective", "stack", "land", "1431"], monkeypatch=monkeypatch)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "--dry-run" in result.stderr and "not implemented" in result.stderr


def test_dry_run_ready_envelope(monkeypatch):
    readiness = _readiness(plan_value=_ready_plan())
    result, asked, assessed = _invoke(
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
    # The declared envelope field order is load-bearing.
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
    ]
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
    result, _, _ = _invoke(
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
    result, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=readiness,
    )
    layer = json.loads(result.stdout)["layers"][0]
    assert layer["assessed"] is False
    assert layer["observed_state"] is None and layer["unresolved_thread_count"] is None


def test_incremental_objective_is_not_stacked(monkeypatch):
    result, _, assessed = _invoke(
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
    result, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=error,
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "objective_not_found"


def test_no_objective_is_a_typed_failure(monkeypatch):
    result, asked, _ = _invoke(
        ["objective", "stack", "land", "--dry-run", "--json"], monkeypatch=monkeypatch
    )
    assert result.exit_code == 1
    assert asked == []
    assert json.loads(result.stdout)["error_type"] == "no_objective"


def test_plan_ref_inference(monkeypatch):
    ref = plan.PlanRef(provider="github", pr_id="1474", url="u", labels=(), objective_id="1431")
    monkeypatch.setattr(cache, "read_plan_ref", lambda _root: ref)
    _, asked, _ = _invoke(
        ["objective", "stack", "land", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(),
        readiness=_readiness(plan_value=_ready_plan()),
    )
    assert asked == ["1431"]


def test_not_a_repo_exits_two(monkeypatch):
    result, _, _ = _invoke(
        ["objective", "stack", "land", "1431", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        git_init=False,
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_redirected_from_rides_the_envelope(monkeypatch):
    result, _, _ = _invoke(
        ["objective", "stack", "land", "9", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        reconstruct=_train(redirected_from="9"),
        readiness=_readiness(plan_value=_ready_plan()),
    )
    assert json.loads(result.stdout)["objective"]["redirected_from"] == "9"


def test_human_render_ready(monkeypatch):
    readiness = _readiness(capability=True, plan_value=_ready_plan())
    result, _, _ = _invoke(
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
    assert "1. 1.1 plan #100 pr #500 OPEN ready base main head bbbbbbbbbbbb" in result.stderr
    assert "MERGEABLE/CLEAN review APPROVED" in result.stderr
    assert "plan: singleton_squash via squash — top pr #500 at bbbbbbbbbbbb" in result.stderr
    assert "no findings" in result.stderr


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
    result, _, _ = _invoke(
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
