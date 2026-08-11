"""Tests for the shared stacked-selection seam (``commands/objective/shared.py``, §8.46).

The ONE readiness-derived classification the plan door, ``objective next``, and the run
supervisor consume — pinned here once; the three consumers stub it at their module boundaries.
``observe.reconstruct_repo_train`` is monkeypatched (no network).
"""

from pathlib import Path

import pytest

from perk import github, objective
from perk.backends.issue_backend import PlanState
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


def _train(
    readiness: train_mod.BuildReadiness,
    *,
    layers: tuple[train_mod.TrainLayer, ...] = (),
    findings: tuple[train_mod.TrainFinding, ...] = (),
    unresolved: tuple[train_mod.UnresolvedOperationFacts, ...] = (),
) -> train_mod.DeliveryTrain:
    return train_mod.DeliveryTrain(
        objective_id="10",
        objective_url="u/10",
        delivery_lineage=_LINEAGE,
        base="main",
        redirected_from=None,
        layers=layers,
        published_prefix_len=sum(
            layer.publication is train_mod.LayerPublication.PUBLISHED for layer in layers
        ),
        unresolved_operation=unresolved[0] if unresolved else None,
        findings=findings,
        build_readiness=readiness,
        unresolved_operations=unresolved,
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


def _selection(
    train: train_mod.DeliveryTrain,
    *,
    kind: str = "no_candidate",
    reason: str | None = "all layers published",
    node: objective.ObjectiveNode | None = None,
) -> shared.StackedSelection:
    return shared.StackedSelection(
        kind=kind,
        node=node,
        ready=kind in {"plannable", "in_flight"},
        reason=reason,
        train=train,
    )


def _finding(code: str, message: str = "boom") -> train_mod.TrainFinding:
    return train_mod.TrainFinding(
        kind=train_mod.FindingKind.BLOCKER,
        code=code,
        message=message,
    )


def test_stacked_veto_precedence_and_remedies():
    operation = train_mod.UnresolvedOperationFacts("01OP", "sync", "t0")
    train = _train(
        train_mod.BuildReadiness(None, False, "all layers published"),
        findings=(_finding("missing_plan", "plan vanished"), _finding("checkpoint_drift")),
        unresolved=(operation,),
    )
    structural = shared.classify_stacked_veto(_selection(train), "10")
    assert structural == shared.StackedVeto(
        "build_blocked",
        "[missing_plan] plan vanished",
        "perk objective stack status 10",
    )

    unresolved_train = _train(
        train_mod.BuildReadiness(None, False, "all layers published"),
        unresolved=(operation,),
    )
    unresolved_veto = shared.classify_stacked_veto(_selection(unresolved_train), "10")
    assert unresolved_veto == shared.StackedVeto(
        "repair_required",
        "operation 01OP (sync, prepared t0)",
        "perk objective stack recover 10",
    )

    drift_train = _train(
        train_mod.BuildReadiness(_ready("1.2").next_node_id, False, "veto"),
        findings=(_finding("checkpoint_drift", "remote moved"),),
    )
    drift = shared.classify_stacked_veto(_selection(drift_train), "10")
    assert drift == shared.StackedVeto(
        "repair_required",
        "[checkpoint_drift] remote moved",
        "perk objective stack status 10",
    )


def test_stacked_veto_covers_no_candidate_unresolved_regression():
    operation = train_mod.UnresolvedOperationFacts("01OP", "publish", "t0")
    train = _train(
        train_mod.BuildReadiness(None, False, "all layers published"),
        unresolved=(operation,),
    )
    veto = shared.classify_stacked_veto(_selection(train, kind="no_candidate"), "10")
    assert veto is not None and veto.action == "repair_required"


def test_selection_level_build_blocked_reasons_have_no_train_veto():
    clean = _train(train_mod.BuildReadiness("1.2", True, None))
    blocked = _node("1.2", N.BLOCKED)
    status_selection = _selection(
        clean,
        kind="build_blocked",
        reason="the next build-ready layer 1.2 is blocked — not plannable",
        node=blocked,
    )
    missing_selection = _selection(
        clean,
        kind="build_blocked",
        reason="the readiness candidate 1.2 is not on the roadmap",
    )
    assert shared.classify_stacked_veto(status_selection, "10") is None
    assert shared.classify_stacked_veto(missing_selection, "10") is None
    assert status_selection.reason is not None and "blocked" in status_selection.reason
    assert missing_selection.reason is not None and "not on the roadmap" in missing_selection.reason


def _published_layer(node_id: str, plan_id: str, pr_number: int) -> train_mod.TrainLayer:
    return train_mod.TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=f"plan-{plan_id}",
        pr_number=pr_number,
        intent=train_mod.LayerIntent.PLANNED,
        publication=train_mod.LayerPublication.PUBLISHED,
        git=train_mod.LayerGit.SYNCED,
        pr=train_mod.LayerPr.READY,
        membership=train_mod.LayerMembership.EXACT,
        writer=train_mod.LayerWriter.FREE,
        finalization=train_mod.LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha="p" * 40,
        published_head_sha="h" * 40,
        observed_remote_head_sha="h" * 40,
        observed_pr_base="main",
        expected_pr_base="main",
    )


def _plan(plan_id: str, pr: github.PullRequest) -> PlanState:
    return PlanState(
        id=plan_id,
        url=f"u/{plan_id}",
        title="Plan",
        header={},
        pr=pr,
        state="OPEN",
    )


def test_lower_attention_returns_bottommost_address_and_skips_review_waits(tmp_path: Path):
    layers = (
        _published_layer("1.1", "101", 201),
        _published_layer("1.2", "102", 202),
        _published_layer("1.3", "103", 203),
    )
    train = _train(train_mod.BuildReadiness(None, False, "all layers published"), layers=layers)
    state = _state(
        (
            _node("1.1", N.IN_PROGRESS, "#101"),
            # Train projection owns the corroborated plan identity; stale roadmap prose must not
            # make the caller re-key the already-validated plan read.
            _node("1.2", N.IN_PROGRESS, "#999"),
            _node("1.3", N.IN_PROGRESS, "#103"),
        )
    )
    plans = {
        "101": _plan("101", github.PullRequest(201, "u", True, "OPEN", True)),
        "102": _plan("102", github.PullRequest(202, "u", False, "OPEN", True)),
        "103": _plan("103", github.PullRequest(203, "u", False, "OPEN", True)),
    }
    feedback_calls: list[int] = []

    def feedback(number: int) -> github.PrFeedback:
        feedback_calls.append(number)
        unresolved = number in {202, 203}
        return github.PrFeedback(
            pr_number=number,
            review_threads=(github.ReviewThread("T", False, False, None, None, ()),)
            if unresolved
            else (),
            discussion_comments=(),
            reviews=(),
        )

    hit = shared.stacked_lower_attention(
        tmp_path,
        train,
        state,
        get_plan=plans.get,
        get_feedback=feedback,
        has_pending_learn=False,
    )
    assert hit is not None and hit.node.id == "1.2" and hit.plan.id == "102"
    assert feedback_calls == [202]  # draft 201 skipped; lower actionable wins before 203


def test_lower_attention_missing_plan_fails_closed(tmp_path: Path):
    layer = _published_layer("1.1", "101", 201)
    train = _train(train_mod.BuildReadiness(None, False, "all layers published"), layers=(layer,))
    with pytest.raises(UserFacingCliError) as excinfo:
        shared.stacked_lower_attention(
            tmp_path,
            train,
            _state((_node("1.1", N.IN_PROGRESS, "#101"),)),
            get_plan=lambda plan_id: None,
            get_feedback=lambda number: pytest.fail("feedback must not be fetched"),
            has_pending_learn=False,
        )
    assert excinfo.value.error_type == "github_error"
    assert "read returned missing" in str(excinfo.value)


def test_authority_read_failures_map_to_the_stable_github_error(monkeypatch, tmp_path: Path):
    # The reconstruction can raise the backend/persistence read errors too (a broken journal
    # carrier, an issue-backend failure) — the shared boundary translates them so every
    # consumer keeps its stable error/JSON surface instead of a traceback.
    from perk.delivery.persistence import TrainPersistenceError

    def _boom(*_a):
        raise TrainPersistenceError("journal carrier missing")

    monkeypatch.setattr(observe, "reconstruct_repo_train", _boom)
    with pytest.raises(UserFacingCliError) as excinfo:
        shared.stacked_selection(tmp_path, _state((_node("1.2", N.PENDING),)))
    assert excinfo.value.error_type == "github_error"
    assert "journal carrier missing" in str(excinfo.value)
