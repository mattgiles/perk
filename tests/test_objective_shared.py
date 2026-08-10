"""Tests for the shared stacked-selection seam (``commands/objective/shared.py``, §8.46).

The ONE readiness-derived classification the plan door, ``objective next``, and the run
supervisor consume — pinned here once; the three consumers stub it at their module boundaries.
``observe.reconstruct_repo_train`` is monkeypatched (no network).
"""

from pathlib import Path

import pytest

from perk import objective
from perk.backends.objective_store import ObjectiveState
from perk.cli.commands.objective import shared
from perk.cli.ensure import UserFacingCliError
from perk.delivery import observe
from perk.delivery import train as train_mod

N = objective.NodeStatus
_LINEAGE = "01JB0000000000000000000000"


def _state(nodes, *, header=None) -> ObjectiveState:
    return ObjectiveState(
        id="10",
        url="u/10",
        title="Obj",
        header=header
        if header is not None
        else {"delivery": "stacked", "delivery_lineage": _LINEAGE},
        nodes=tuple(nodes),
    )


def _node(node_id: str, status: N, pr: str | None = None) -> objective.ObjectiveNode:
    return objective.ObjectiveNode(id=node_id, description="d", status=status, pr=pr)


def _train(readiness: train_mod.BuildReadiness) -> train_mod.DeliveryTrain:
    return train_mod.DeliveryTrain(
        objective_id="10",
        objective_url="u/10",
        delivery_lineage=_LINEAGE,
        base="main",
        redirected_from=None,
        layers=(),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=readiness,
    )


def _ready(node_id: str) -> train_mod.BuildReadiness:
    return train_mod.BuildReadiness(next_node_id=node_id, ready=True, reason=None)


def test_incremental_objective_returns_none_without_reconstructing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        observe,
        "reconstruct_repo_train",
        lambda *_a: pytest.fail("incremental must not reconstruct"),
    )
    assert shared.stacked_selection(tmp_path, _state((), header={})) is None


def test_junk_delivery_policy_fails_closed(tmp_path: Path):
    with pytest.raises(UserFacingCliError) as excinfo:
        shared.stacked_selection(tmp_path, _state((), header={"delivery": "yolo"}))
    assert excinfo.value.error_type == "invalid_delivery_policy"


def test_pending_candidate_is_plannable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(observe, "reconstruct_repo_train", lambda *_a: _train(_ready("1.2")))
    selection = shared.stacked_selection(
        tmp_path, _state((_node("1.1", N.IN_PROGRESS, "#101"), _node("1.2", N.PENDING)))
    )
    assert selection is not None
    assert selection.kind == "plannable"
    assert selection.node is not None and selection.node.id == "1.2"
    assert selection.ready is True and selection.reason is None


def test_planning_claim_without_a_plan_is_plannable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(observe, "reconstruct_repo_train", lambda *_a: _train(_ready("1.2")))
    selection = shared.stacked_selection(
        tmp_path, _state((_node("1.1", N.IN_PROGRESS, "#101"), _node("1.2", N.PLANNING)))
    )
    assert selection is not None and selection.kind == "plannable"


def test_committed_plan_is_in_flight(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(observe, "reconstruct_repo_train", lambda *_a: _train(_ready("1.2")))
    selection = shared.stacked_selection(
        tmp_path, _state((_node("1.1", N.DONE, "#101"), _node("1.2", N.IN_PROGRESS, "#102")))
    )
    assert selection is not None
    assert selection.kind == "in_flight"
    assert selection.node is not None and selection.node.id == "1.2"


def test_readiness_veto_is_build_blocked_with_the_reason(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        observe,
        "reconstruct_repo_train",
        lambda *_a: _train(
            train_mod.BuildReadiness(next_node_id="1.2", ready=False, reason="[x] y")
        ),
    )
    selection = shared.stacked_selection(tmp_path, _state((_node("1.2", N.PENDING),)))
    assert selection is not None
    assert selection.kind == "build_blocked"
    assert selection.reason == "[x] y"


def test_all_published_is_no_candidate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        observe,
        "reconstruct_repo_train",
        lambda *_a: _train(
            train_mod.BuildReadiness(next_node_id=None, ready=False, reason="all layers published")
        ),
    )
    selection = shared.stacked_selection(tmp_path, _state((_node("1.1", N.IN_PROGRESS, "#101"),)))
    assert selection is not None
    assert selection.kind == "no_candidate"
    assert selection.node is None


def test_blocked_status_candidate_fails_closed(monkeypatch, tmp_path: Path):
    # A candidate in a non-plannable, non-in-flight status (an explicitly blocked node) is an
    # honest build_blocked, never waved through.
    monkeypatch.setattr(observe, "reconstruct_repo_train", lambda *_a: _train(_ready("1.2")))
    selection = shared.stacked_selection(tmp_path, _state((_node("1.2", N.BLOCKED),)))
    assert selection is not None
    assert selection.kind == "build_blocked"
    assert selection.reason is not None and "blocked" in selection.reason


def test_reconstruction_error_maps_to_a_typed_cli_error(monkeypatch, tmp_path: Path):
    def _boom(*_a):
        raise train_mod.TrainReconstructionError("no order", error_type="invalid_train")

    monkeypatch.setattr(observe, "reconstruct_repo_train", _boom)
    with pytest.raises(UserFacingCliError) as excinfo:
        shared.stacked_selection(tmp_path, _state((_node("1.2", N.PENDING),)))
    assert excinfo.value.error_type == "invalid_train"
