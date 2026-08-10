"""Tests for ``LayerContext`` + the parent-preparation path (``perk/delivery/layer.py``).

Pure/injected: the derive/require gates run over hand-built ``DeliveryTrain`` projections and
``prepare_layer_start`` over injected fake probes — hermetic, no subprocess/network (the
``capability.py`` injectable-probe precedent).
"""

from pathlib import Path

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
) -> train_mod.DeliveryTrain:
    return train_mod.DeliveryTrain(
        objective_id="10",
        objective_url="fake://objective/10",
        delivery_lineage=_LINEAGE,
        base=base,
        redirected_from=None,
        layers=layers,
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=readiness
        or train_mod.BuildReadiness(next_node_id=None, ready=False, reason="all layers published"),
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


class TestPrepareLayerStart:
    def test_happy_path_fetches_exactly_the_parent_and_verifies(self, tmp_path: Path) -> None:
        fetched: list[list[str]] = []
        prepared = layer_mod.prepare_layer_start(
            tmp_path,
            _ctx(),
            fetch=lambda _repo, refspecs: fetched.append(refspecs),
            remote_head=lambda _repo, branch: _SHA if branch == "plan-101" else None,
            resolve_commit=lambda _repo, ref: ref,
        )
        assert fetched == [["plan-101"]]
        assert prepared.parent_sha == _SHA
        assert prepared.context == _ctx()

    def test_absent_remote_parent_names_the_expected_ref(self, tmp_path: Path) -> None:
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.prepare_layer_start(
                tmp_path,
                _ctx(),
                fetch=lambda _repo, _refspecs: None,
                remote_head=lambda _repo, _branch: None,
                resolve_commit=lambda _repo, ref: ref,
            )
        assert excinfo.value.error_type == "parent_missing"
        assert "refs/heads/plan-101" in str(excinfo.value)

    def test_unresolvable_head_after_fetch_is_typed(self, tmp_path: Path) -> None:
        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.prepare_layer_start(
                tmp_path,
                _ctx(),
                fetch=lambda _repo, _refspecs: None,
                remote_head=lambda _repo, _branch: _SHA,
                resolve_commit=lambda _repo, _ref: None,
            )
        assert excinfo.value.error_type == "parent_unverified"
        assert _SHA in str(excinfo.value)

    def test_git_infra_failure_is_typed(self, tmp_path: Path) -> None:
        def _boom(_repo: Path, _refspecs: list[str]) -> None:
            raise GitError("network down")

        with pytest.raises(layer_mod.LayerError) as excinfo:
            layer_mod.prepare_layer_start(tmp_path, _ctx(), fetch=_boom)
        assert excinfo.value.error_type == "git_error"
        assert "network down" in str(excinfo.value)
