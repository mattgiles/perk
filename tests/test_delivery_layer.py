"""Tests for ``LayerContext`` + the parent-preparation path (``perk/delivery/layer.py``).

Pure/injected: the derive/require gates run over hand-built ``DeliveryTrain`` projections and
``prepare_layer_start`` over injected fake probes — hermetic, no subprocess/network (the
``capability.py`` injectable-probe precedent).
"""

import pytest

from perk.delivery import layer as layer_mod
from perk.delivery import train as train_mod
from perk.substrate.git import GitError

_LINEAGE = "01JB0000000000000000000000"
_SHA = "a" * 40


def _layer(
    node_id: str, plan_id: str | None, branch: str | None, **overrides
) -> train_mod.TrainLayer:
    values: dict = {
        "node_id": node_id,
        "plan_id": plan_id,
        "branch": branch,
        "pr_number": None,
        "intent": train_mod.LayerIntent.PLANNED
        if plan_id is not None
        else train_mod.LayerIntent.UNPLANNED,
        "publication": train_mod.LayerPublication.UNPUBLISHED,
        "git": train_mod.LayerGit.ABSENT,
        "pr": train_mod.LayerPr.ABSENT,
        "membership": train_mod.LayerMembership.NOT_APPLICABLE,
        "writer": train_mod.LayerWriter.FREE,
        "finalization": train_mod.LayerFinalization.NOT_MERGED,
        "parent_checkpoint_sha": None,
        "published_head_sha": None,
        "observed_remote_head_sha": None,
        "observed_pr_base": None,
        "expected_pr_base": None,
    }
    values.update(overrides)
    return train_mod.TrainLayer(**values)


def _train(
    layers: tuple[train_mod.TrainLayer, ...],
    *,
    readiness: train_mod.BuildReadiness | None = None,
    base: str = "main",
    findings: tuple[train_mod.TrainFinding, ...] = (),
    unresolved_operations: tuple[train_mod.UnresolvedOperationFacts, ...] = (),
) -> train_mod.DeliveryTrain:
    return train_mod.DeliveryTrain(
        objective_id="10",
        objective_url="fake://objective/10",
        delivery_lineage=_LINEAGE,
        base=base,
        redirected_from=None,
        layers=layers,
        published_prefix_len=0,
        unresolved_operation=unresolved_operations[0] if unresolved_operations else None,
        findings=findings,
        build_readiness=readiness
        or train_mod.BuildReadiness(next_node_id=None, ready=False, reason="all layers published"),
        unresolved_operations=unresolved_operations,
    )


def _two_layer_train(**kwargs) -> train_mod.DeliveryTrain:
    return _train(
        (
            _layer("1.1", "101", "plan-101"),
            _layer("1.2", "102", "plan-102"),
        ),
        **kwargs,
    )


class TestDeriveLayerContext:
    def test_bottom_layer_parents_off_the_objective_base(self) -> None:
        ctx = layer_mod.derive_layer_context(_two_layer_train(), plan_id="101")
        assert ctx == layer_mod.LayerContext(
            objective_id="10",
            node_id="1.1",
            plan_id="101",
            delivery_lineage=_LINEAGE,
            predecessor_plan_id=None,
            base="main",
            parent_branch="main",
            branch="plan-101",
        )

    def test_child_layer_parents_off_the_predecessor_branch(self) -> None:
        ctx = layer_mod.derive_layer_context(_two_layer_train(), plan_id="#102")
        assert ctx.node_id == "1.2"
        assert ctx.parent_branch == "plan-101"
        assert ctx.predecessor_plan_id == "101"
        assert ctx.branch == "plan-102"
        assert ctx.base == "main"

    def test_current_layer_branch_is_canonical_even_with_a_header_branch(self) -> None:
        # The context describes the branch creation actually MAKES (`plan-<plan_id>`), never
        # an arbitrary plan-header branch; only the predecessor's parent_branch uses the
        # train's header-or-convention resolution.
        train = _train(
            (
                _layer("1.1", "101", "feature-x"),  # header-observed predecessor branch
                _layer("1.2", "102", "feature-y"),  # header branch must NOT leak into ctx
            )
        )
        ctx = layer_mod.derive_layer_context(train, plan_id="102")
        assert ctx.branch == "plan-102"  # canonical, not "feature-y"
        assert ctx.parent_branch == "feature-x"  # the predecessor keeps the train resolution

    def test_unknown_plan_is_a_typed_error(self) -> None:
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.derive_layer_context(_two_layer_train(), plan_id="404")
        assert excinfo.value.error_type == "unknown_layer"

    def test_unplanned_predecessor_is_a_typed_error(self) -> None:
        train = _train((_layer("1.1", None, None), _layer("1.2", "102", "plan-102")))
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.derive_layer_context(train, plan_id="102")
        assert excinfo.value.error_type == "stacked_predecessor_missing"


class TestRequireReadyLayer:
    def test_ready_candidate_passes(self) -> None:
        train = _two_layer_train(
            readiness=train_mod.BuildReadiness(next_node_id="1.1", ready=True, reason=None)
        )
        ctx = layer_mod.require_ready_layer(train, plan_id="101")
        assert ctx.node_id == "1.1"

    def test_not_ready_carries_the_exact_veto(self) -> None:
        train = _two_layer_train(
            readiness=train_mod.BuildReadiness(
                next_node_id="1.1", ready=False, reason="the train has blocker findings: [x] y"
            )
        )
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.require_ready_layer(train, plan_id="101")
        assert excinfo.value.error_type == "node_not_build_ready"
        assert "[x] y" in str(excinfo.value)

    def test_wrong_candidate_names_the_ready_layer(self) -> None:
        train = _two_layer_train(
            readiness=train_mod.BuildReadiness(next_node_id="1.1", ready=True, reason=None)
        )
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.require_ready_layer(train, plan_id="102")
        assert excinfo.value.error_type == "node_not_build_ready"
        assert "1.1" in str(excinfo.value)


def _ctx(parent_branch: str = "plan-101") -> layer_mod.LayerContext:
    return layer_mod.LayerContext(
        objective_id="10",
        node_id="1.2",
        plan_id="102",
        delivery_lineage=_LINEAGE,
        predecessor_plan_id="101",
        base="main",
        parent_branch=parent_branch,
        branch="plan-102",
    )


class TestRequireReviewableLayer:
    def test_published_target_passes(self) -> None:
        target = _layer(
            "1.1",
            "101",
            "plan-101",
            publication=train_mod.LayerPublication.PUBLISHED,
            git=train_mod.LayerGit.SYNCED,
            pr=train_mod.LayerPr.DRAFT,
            parent_checkpoint_sha="p" * 40,
            published_head_sha=_SHA,
        )
        assert (
            layer_mod.require_reviewable_layer(_train((target,)), plan_id="#101", mutating=True)
            is target
        )

    def test_unpublished_target_carries_axes_and_findings(self) -> None:
        finding = train_mod.TrainFinding(
            kind=train_mod.FindingKind.BLOCKER,
            code="checkpoint_drift",
            message="expected abc, observed def",
            node_id="1.1",
            plan_id="101",
        )
        train = _train((_layer("1.1", "101", "plan-101"),), findings=(finding,))
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.require_reviewable_layer(train, plan_id="101", mutating=True)
        assert excinfo.value.error_type == "layer_not_published"
        assert "publication=unpublished" in str(excinfo.value)
        assert "[checkpoint_drift] expected abc, observed def" in str(excinfo.value)

    def test_mutating_refuses_unresolved_operation(self) -> None:
        target = _layer("1.1", "101", "plan-101", publication=train_mod.LayerPublication.PUBLISHED)
        operation = train_mod.UnresolvedOperationFacts(
            operation_id="01OP", kind="sync", prepared_created="t0"
        )
        train = _train((target,), unresolved_operations=(operation,))
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.require_reviewable_layer(train, plan_id="101", mutating=True)
        assert excinfo.value.error_type == "unresolved_operation"
        assert "01OP (sync, prepared t0)" in str(excinfo.value)

    def test_mutating_refuses_complete_structural_set_including_missing_lineage(self) -> None:
        target = _layer("1.1", "101", "plan-101", publication=train_mod.LayerPublication.PUBLISHED)
        finding = train_mod.TrainFinding(
            kind=train_mod.FindingKind.BLOCKER,
            code="missing_lineage",
            message="lineage absent",
        )
        train = _train((target,), findings=(finding,))
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.require_reviewable_layer(train, plan_id="101", mutating=True)
        assert excinfo.value.error_type == "structural_blockers"
        assert "[missing_lineage] lineage absent" in str(excinfo.value)

    def test_nonmutating_ignores_global_vetoes(self) -> None:
        target = _layer("1.1", "101", "plan-101", publication=train_mod.LayerPublication.PUBLISHED)
        finding = train_mod.TrainFinding(
            kind=train_mod.FindingKind.BLOCKER,
            code="missing_plan",
            message="other layer missing",
            node_id="1.2",
        )
        operation = train_mod.UnresolvedOperationFacts("01OP", "sync", "t0")
        train = _train((target,), findings=(finding,), unresolved_operations=(operation,))
        assert layer_mod.require_reviewable_layer(train, plan_id="101", mutating=False) is target

    def test_operational_drift_on_other_layer_never_blocks(self) -> None:
        target = _layer("1.1", "101", "plan-101", publication=train_mod.LayerPublication.PUBLISHED)
        finding = train_mod.TrainFinding(
            kind=train_mod.FindingKind.BLOCKER,
            code="checkpoint_drift",
            message="other layer drift",
            node_id="1.2",
            plan_id="102",
        )
        train = _train((target, _layer("1.2", "102", "plan-102")), findings=(finding,))
        assert layer_mod.require_reviewable_layer(train, plan_id="101", mutating=True) is target


class TestPrepareLayerStart:
    def test_happy_path_fetches_exactly_the_parent_and_verifies(self) -> None:
        fetched: list[tuple[str, ...]] = []
        prepared = layer_mod.prepare_layer_start(
            _ctx(),
            fetch=fetched.append,
            remote_head=lambda branch: _SHA if branch == "plan-101" else None,
            resolve_commit=lambda ref: ref,
        )
        assert fetched == [("plan-101",)]
        assert prepared.parent_sha == _SHA
        assert prepared.context == _ctx()

    def test_absent_remote_parent_names_the_expected_ref(self) -> None:
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.prepare_layer_start(
                _ctx(),
                fetch=lambda _refspecs: None,
                remote_head=lambda _branch: None,
                resolve_commit=lambda ref: ref,
            )
        assert excinfo.value.error_type == "parent_missing"
        assert "refs/heads/plan-101" in str(excinfo.value)

    def test_unresolvable_head_after_fetch_is_typed(self) -> None:
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.prepare_layer_start(
                _ctx(),
                fetch=lambda _refspecs: None,
                remote_head=lambda _branch: _SHA,
                resolve_commit=lambda _ref: None,
            )
        assert excinfo.value.error_type == "parent_unverified"
        assert _SHA in str(excinfo.value)

    def test_git_infra_failure_is_typed(self) -> None:
        def _boom(_refspecs: tuple[str, ...]) -> None:
            raise GitError("network down")

        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.prepare_layer_start(
                _ctx(),
                fetch=_boom,
                remote_head=lambda _branch: _SHA,
                resolve_commit=lambda ref: ref,
            )
        assert excinfo.value.error_type == "git_error"
        assert "network down" in str(excinfo.value)
