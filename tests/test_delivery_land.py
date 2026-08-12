"""Tests for the pure landing-readiness projection (``perk/delivery/land.py``).

In-memory fakes for ``LandObservations`` + ``RemoteWriterProbe`` over directly-constructed
``DeliveryTrain`` values (the ``test_delivery_train.py`` pattern): the composition rule
(train blockers/operations/information pass through), the disposition semantics
(READY/BLOCKED/NOTHING_TO_LAND with blocker precedence), every land-only blocker arm's
fail-closed classification, and the exact ``LandPlan`` shape 5.3 consumes.
"""

import ast
import inspect
from dataclasses import replace

import pytest

from perk.delivery import land, train

_URL = "https://github.com/o/r/issues/1431"
_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40
_SHA_D = "d" * 40


def _layer(
    node_id: str = "1.1",
    plan_id: str | None = "100",
    pr_number: int | None = 500,
    *,
    parent_sha: str | None = _SHA_A,
    head_sha: str | None = _SHA_B,
    expected_base: str | None = "main",
    **overrides,
) -> train.TrainLayer:
    values: dict = {
        "node_id": node_id,
        "plan_id": plan_id,
        "branch": None if plan_id is None else f"plan-{plan_id}",
        "pr_number": pr_number,
        "intent": train.LayerIntent.PLANNED,
        "publication": train.LayerPublication.PUBLISHED,
        "git": train.LayerGit.SYNCED,
        "pr": train.LayerPr.READY,
        "membership": train.LayerMembership.EXACT,
        "writer": train.LayerWriter.FREE,
        "finalization": train.LayerFinalization.NOT_MERGED,
        "parent_checkpoint_sha": parent_sha,
        "published_head_sha": head_sha,
        "observed_remote_head_sha": head_sha,
        "observed_pr_base": expected_base,
        "expected_pr_base": expected_base,
    }
    values.update(overrides)
    return train.TrainLayer(**values)


def _two_layers() -> tuple[train.TrainLayer, train.TrainLayer]:
    bottom = _layer("1.1", "100", 500, parent_sha=_SHA_A, head_sha=_SHA_B)
    top = _layer("1.2", "101", 501, parent_sha=_SHA_B, head_sha=_SHA_C, expected_base="plan-100")
    return bottom, top


def _train(
    layers: tuple[train.TrainLayer, ...],
    *,
    findings: tuple[train.TrainFinding, ...] = (),
    unresolved_operations: tuple[train.UnresolvedOperationFacts, ...] = (),
    published_prefix_len: int | None = None,
) -> train.DeliveryTrain:
    return train.DeliveryTrain(
        objective_id="1431",
        objective_url=_URL,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        redirected_from=None,
        layers=layers,
        published_prefix_len=published_prefix_len
        if published_prefix_len is not None
        else len(layers),
        unresolved_operation=unresolved_operations[0] if unresolved_operations else None,
        findings=findings,
        build_readiness=train.BuildReadiness(
            next_node_id=None, ready=False, reason="all layers published"
        ),
        unresolved_operations=unresolved_operations,
    )


def _view_for(layer: train.TrainLayer, **overrides) -> land.PrLandView:
    values: dict = {
        "number": layer.pr_number,
        "state": "OPEN",
        "is_draft": False,
        "base_ref": layer.expected_pr_base,
        "head_ref": layer.branch,
        "head_sha": layer.published_head_sha,
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "review_decision": "APPROVED",
        "checks": (),
        "unresolved_thread_count": 0,
    }
    values.update(overrides)
    return land.PrLandView(**values)


class FakeObservations:
    """In-memory ``LandObservations``: per-PR views (a view, ``None``, or an exception to
    raise), configurable rules, and call recording (the never-consulted assertions)."""

    def __init__(
        self,
        views: dict[int | None, object] | None = None,
        *,
        rules: object = None,
        capability: bool = True,
    ) -> None:
        self._views = views or {}
        self._rules = rules if rules is not None else land.MergeRulesView(True, False)
        self._capability = capability
        self.readiness_calls: list[int] = []
        self.rules_calls = 0
        self.capability_calls = 0

    def pr_readiness(self, number: int) -> land.PrLandView | None:
        self.readiness_calls.append(number)
        view = self._views.get(number)
        if isinstance(view, Exception):
            raise view
        assert view is None or isinstance(view, land.PrLandView)
        return view

    def base_merge_rules(self) -> land.MergeRulesView:
        self.rules_calls += 1
        if isinstance(self._rules, Exception):
            raise self._rules
        assert isinstance(self._rules, land.MergeRulesView)
        return self._rules

    def stack_capability(self) -> bool:
        self.capability_calls += 1
        return self._capability


class FakeWriters:
    def __init__(self, active: frozenset[str] = frozenset(), boom: Exception | None = None):
        self._active = active
        self._boom = boom
        self.calls: list[list[str]] = []

    def active_plan_ids(self, plan_ids) -> frozenset[str]:
        self.calls.append(list(plan_ids))
        if self._boom is not None:
            raise self._boom
        return self._active


def _happy(layers: tuple[train.TrainLayer, ...]) -> FakeObservations:
    return FakeObservations({layer.pr_number: _view_for(layer) for layer in layers})


def _assess(projection, observations=None, writers=None) -> land.LandReadiness:
    return land.assess_land_readiness(
        projection,
        observations=observations if observations is not None else _happy(projection.layers),
        remote_writers=writers if writers is not None else FakeWriters(),
    )


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


# ----------------------------------------------------------------- READY dispositions


def test_ready_multi_layer_builds_the_exact_stack_plan():
    layers = _two_layers()
    result = _assess(_train(layers))
    assert result.disposition is land.LandDisposition.READY
    assert result.blockers == ()
    assert result.plan == land.LandPlan(
        mode="stack_merge_async",
        merge_method="squash",
        top_pr_number=501,
        top_head_sha=_SHA_C,
        layers=(
            land.LandPlanLayer(
                node_id="1.1", plan_id="100", pr_number=500, base_sha=_SHA_A, head_sha=_SHA_B
            ),
            land.LandPlanLayer(
                node_id="1.2", plan_id="101", pr_number=501, base_sha=_SHA_B, head_sha=_SHA_C
            ),
        ),
    )
    assert result.native_stack_capability is True
    assert result.rules == land.MergeRulesView(squash_allowed=True, merge_queue_required=False)
    assert [row.assessed for row in result.layers] == [True, True]


def test_dynamic_singleton_lands_as_one_squash_without_stack_arms():
    layer = _layer(membership=train.LayerMembership.NOT_APPLICABLE)
    info = train.TrainFinding(
        kind=train.FindingKind.INFO, code="dynamic_singleton", message="one layer remains"
    )
    observations = _happy((layer,))
    result = _assess(_train((layer,), findings=(info,)), observations)
    assert result.disposition is land.LandDisposition.READY
    assert result.plan is not None and result.plan.mode == "singleton_squash"
    assert result.plan.top_pr_number == 500 and result.plan.top_head_sha == _SHA_B
    # The capability/composition arms are never consulted for the singleton.
    assert result.native_stack_capability is None
    assert observations.capability_calls == 0
    assert "dynamic_singleton" in _codes(result.information)


def test_information_only_outcomes_stay_ready():
    layers = _two_layers()
    checks = (land.CheckView(name="fuzz", is_required=False, outcome="failed"),)
    views: dict[int | None, object] = {
        500: _view_for(layers[0], checks=checks, unresolved_thread_count=2),
        501: _view_for(layers[1], merge_state_status="UNSTABLE", checks=checks),
    }
    active = _train((layers[0], replace(layers[1], writer=train.LayerWriter.ACTIVE)))
    result = _assess(active, FakeObservations(views))
    assert result.disposition is land.LandDisposition.READY
    assert result.plan is not None
    assert sorted(_codes(result.information)) == [
        "active_worktree",
        "optional_check_failed",
        "optional_check_failed",
        "unresolved_threads",
    ]
    assert result.layers[0].optional_checks_failed == ("fuzz",)
    assert result.layers[0].unresolved_thread_count == 2


# ----------------------------------------------------------------- zero-layer dispositions


def test_all_skipped_clean_is_nothing_to_land_with_no_enrichment_reads():
    info = train.TrainFinding(
        kind=train.FindingKind.INFO, code="all_skipped", message="every node projects skipped"
    )
    observations = FakeObservations()
    writers = FakeWriters()
    result = _assess(_train((), findings=(info,)), observations, writers)
    assert result.disposition is land.LandDisposition.NOTHING_TO_LAND
    assert result.plan is None and result.layers == ()
    assert result.rules is None and result.native_stack_capability is None
    # No enrichment call of any kind was made.
    assert observations.rules_calls == 0 and observations.capability_calls == 0
    assert observations.readiness_calls == [] and writers.calls == []
    assert "all_skipped" in _codes(result.information)


def test_zero_layers_with_a_train_blocker_is_blocked_never_nothing_to_land():
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER, code="missing_lineage", message="no lineage recorded"
    )
    result = _assess(_train((), findings=(blocker,)))
    assert result.disposition is land.LandDisposition.BLOCKED
    assert _codes(result.blockers) == ["missing_lineage"]
    assert result.plan is None


def test_zero_layers_with_an_unresolved_operation_is_blocked():
    operation = train.UnresolvedOperationFacts(
        operation_id="01OP", kind="publish", prepared_created="2026-01-01T00:00:00Z"
    )
    result = _assess(_train((), unresolved_operations=(operation,)))
    assert result.disposition is land.LandDisposition.BLOCKED
    assert _codes(result.blockers) == ["unresolved_operation"]


# ----------------------------------------------------------------- train-state composition


def test_train_blocker_passes_through_as_is_and_vetoes_ready():
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER,
        code="checkpoint_drift",
        message="recorded b… observed d…",
        node_id="1.2",
        plan_id="101",
    )
    layers = _two_layers()
    result = _assess(_train(layers, findings=(blocker,)))
    assert result.disposition is land.LandDisposition.BLOCKED
    assert blocker in result.blockers  # composed verbatim (the §8.44 passthrough class)
    assert result.plan is None


@pytest.mark.parametrize("kind", ["sync", "publish", "land"])
def test_any_unresolved_operation_kind_blocks(kind):
    operation = train.UnresolvedOperationFacts(
        operation_id="01OP", kind=kind, prepared_created="2026-01-01T00:00:00Z"
    )
    result = _assess(_train(_two_layers(), unresolved_operations=(operation,)))
    assert result.disposition is land.LandDisposition.BLOCKED
    blocker = next(f for f in result.blockers if f.code == "unresolved_operation")
    assert "01OP" in blocker.message and kind in blocker.message
    assert "2026-01-01T00:00:00Z" in blocker.message


# ----------------------------------------------------------------- publication + assessment


def test_partially_published_train_assesses_the_published_siblings():
    bottom, top = _two_layers()
    unpublished = replace(
        top,
        publication=train.LayerPublication.UNPUBLISHED,
        pr_number=None,
        parent_checkpoint_sha=None,
        published_head_sha=None,
        observed_remote_head_sha=None,
    )
    observations = _happy((bottom,))
    writers = FakeWriters()
    result = _assess(_train((bottom, unpublished), published_prefix_len=1), observations, writers)
    assert result.disposition is land.LandDisposition.BLOCKED
    assert _codes(result.blockers) == ["incomplete_publication"]
    # The published sibling is still fully assessed.
    assert observations.readiness_calls == [500]
    assert result.layers[0].assessed is True
    row = result.layers[1]
    assert row.assessed is False
    assert row.observed_state is None and row.observed_head_sha is None
    assert row.unresolved_thread_count is None
    # The writer probe receives exactly the non-null plan ids (planned-but-unpublished too).
    assert writers.calls == [["100", "101"]]


def test_short_published_prefix_with_all_layers_published_is_blocked():
    # The inconsistent projection: every layer reads PUBLISHED yet the contiguous prefix is
    # short — the completeness invariant is checked on BOTH axes, fail-closed.
    layers = _two_layers()
    result = _assess(_train(layers, published_prefix_len=1))
    assert result.disposition is land.LandDisposition.BLOCKED
    blocker = next(f for f in result.blockers if f.code == "incomplete_publication")
    assert "1/2" in blocker.message
    assert result.plan is None


def test_published_layer_missing_identity_is_incomplete_publication():
    # Contradicts the §8.46 published-layer definition — classified back, never trusted.
    broken = _layer(head_sha=None)
    result = _assess(_train((broken,)), FakeObservations())
    assert result.disposition is land.LandDisposition.BLOCKED
    assert "incomplete_publication" in _codes(result.blockers)
    assert "missing identity/checkpoint" in result.blockers[0].message


# ----------------------------------------------------------------- writer arms


def test_dirty_worktree_blocks():
    layers = (_layer(writer=train.LayerWriter.DIRTY),)
    result = _assess(_train(layers))
    assert "dirty_worktree" in _codes(result.blockers)


def test_active_clean_worktree_is_information_only():
    layers = (_layer(writer=train.LayerWriter.ACTIVE),)
    result = _assess(_train(layers))
    assert result.disposition is land.LandDisposition.READY
    assert "active_worktree" in _codes(result.information)


def test_active_remote_writer_blocks_naming_the_plans():
    result = _assess(_train(_two_layers()), writers=FakeWriters(active=frozenset({"101"})))
    blocker = next(f for f in result.blockers if f.code == "active_writer")
    assert "#101" in blocker.message


def test_writer_observation_failure_is_fail_closed():
    layers = _two_layers()
    writers = FakeWriters(boom=land.WriterObservationError("gh api down"))
    observations = _happy(layers)
    result = _assess(_train(layers), observations, writers)
    blocker = next(f for f in result.blockers if f.code == "writer_observation_unavailable")
    assert "gh api down" in blocker.message
    assert result.disposition is land.LandDisposition.BLOCKED
    # The enrichment failure localizes — per-PR assessment still ran for every layer.
    assert [row.assessed for row in result.layers] == [True, True]
    assert observations.readiness_calls == [500, 501]


# ----------------------------------------------------------------- rules + capability arms


def test_merge_rules_failure_is_merge_rules_unobserved_with_null_rules():
    layers = _two_layers()
    observations = FakeObservations(
        {layer.pr_number: _view_for(layer) for layer in layers},
        rules=land.LandObservationError("HTTP 500"),
    )
    result = _assess(_train(layers), observations)
    assert result.rules is None
    blocker = next(f for f in result.blockers if f.code == "merge_rules_unobserved")
    assert "HTTP 500" in blocker.message and "main" in blocker.message
    # The enrichment failure localizes — per-PR assessment still ran for every layer.
    assert [row.assessed for row in result.layers] == [True, True]
    assert observations.readiness_calls == [500, 501]


def test_squash_forbidden_blocks():
    layers = _two_layers()
    observations = FakeObservations(
        {layer.pr_number: _view_for(layer) for layer in layers},
        rules=land.MergeRulesView(squash_allowed=False, merge_queue_required=False),
    )
    result = _assess(_train(layers), observations)
    assert "squash_forbidden" in _codes(result.blockers)
    assert result.rules is not None and result.rules.squash_allowed is False


def test_queue_required_base_blocks():
    layers = _two_layers()
    observations = FakeObservations(
        {layer.pr_number: _view_for(layer) for layer in layers},
        rules=land.MergeRulesView(squash_allowed=True, merge_queue_required=True),
    )
    result = _assess(_train(layers), observations)
    assert "queue_required_base" in _codes(result.blockers)


def test_missing_capability_blocks_the_multi_layer_train():
    layers = _two_layers()
    observations = FakeObservations(
        {layer.pr_number: _view_for(layer) for layer in layers}, capability=False
    )
    result = _assess(_train(layers), observations)
    assert result.native_stack_capability is False
    assert "stack_capability_unavailable" in _codes(result.blockers)
    # The enrichment failure localizes — per-PR assessment still ran for every layer.
    assert [row.assessed for row in result.layers] == [True, True]
    assert observations.readiness_calls == [500, 501]


@pytest.mark.parametrize(
    "membership",
    [
        train.LayerMembership.UNKNOWN,
        train.LayerMembership.DIVERGENT,
        train.LayerMembership.ABSENT,
        train.LayerMembership.NOT_APPLICABLE,
    ],
)
def test_non_exact_membership_blocks_composition(membership):
    bottom, top = _two_layers()
    drifted = replace(top, membership=membership)
    result = _assess(_train((bottom, drifted)))
    blocker = next(f for f in result.blockers if f.code == "composition_divergent")
    assert membership.value in blocker.message
    assert blocker.node_id == "1.2"


# ----------------------------------------------------------------- per-PR readiness arms


def test_readiness_read_failure_localizes_and_siblings_still_assess():
    layers = _two_layers()
    observations = FakeObservations(
        {500: land.LandObservationError("HTTP 502"), 501: _view_for(layers[1])}
    )
    result = _assess(_train(layers), observations)
    blocker = next(f for f in result.blockers if f.code == "readiness_unobserved")
    assert "HTTP 502" in blocker.message and blocker.node_id == "1.1"
    assert result.layers[0].assessed is False
    assert result.layers[1].assessed is True  # the sibling was still read
    assert observations.readiness_calls == [500, 501]


def test_vanished_pr_is_pr_missing():
    layers = (_layer(),)
    result = _assess(_train(layers), FakeObservations({500: None}))
    assert "pr_missing" in _codes(result.blockers)
    assert result.layers[0].assessed is False


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"state": "MERGED"}, "pr_not_open"),
        ({"state": "CLOSED"}, "pr_not_open"),
        ({"is_draft": True}, "pr_draft"),
        ({"base_ref": "other"}, "wrong_base"),
        ({"head_ref": "other-branch"}, "wrong_head_ref"),
        ({"head_sha": _SHA_D}, "head_moved"),
        ({"mergeable": "CONFLICTING"}, "pr_conflicting"),
        ({"mergeable": "UNKNOWN"}, "mergeability_unknown"),
        ({"merge_state_status": "BEHIND"}, "pr_behind"),
        ({"merge_state_status": "BLOCKED"}, "pr_blocked"),
        ({"merge_state_status": "UNKNOWN"}, "merge_state_unknown"),
        ({"review_decision": "CHANGES_REQUESTED"}, "changes_requested"),
        ({"review_decision": "REVIEW_REQUIRED"}, "review_required"),
    ],
)
def test_per_pr_blocker_arms(overrides, code):
    layer = _layer()
    result = _assess(_train((layer,)), FakeObservations({500: _view_for(layer, **overrides)}))
    assert code in _codes(result.blockers)
    assert result.disposition is land.LandDisposition.BLOCKED
    assert result.plan is None  # BLOCKED never carries a plan
    assert result.layers[0].assessed is True  # the observation was made and recorded


def test_dirty_merge_state_blocks_even_when_mergeable_says_mergeable():
    layer = _layer()
    view = _view_for(layer, mergeable="MERGEABLE", merge_state_status="DIRTY")
    result = _assess(_train((layer,)), FakeObservations({500: view}))
    assert "pr_conflicting" in _codes(result.blockers)


def test_draft_merge_state_blocks_even_when_is_draft_is_false():
    layer = _layer()
    view = _view_for(layer, is_draft=False, merge_state_status="DRAFT")
    result = _assess(_train((layer,)), FakeObservations({500: view}))
    assert "pr_draft" in _codes(result.blockers)


def test_agreeing_conflict_facts_emit_one_blocker_row():
    # The routine agreeing observation (CONFLICTING scalar + DIRTY aggregate) is ONE
    # established fact — one blocker row, never a duplicate.
    layer = _layer()
    view = _view_for(layer, mergeable="CONFLICTING", merge_state_status="DIRTY")
    result = _assess(_train((layer,)), FakeObservations({500: view}))
    assert _codes(result.blockers).count("pr_conflicting") == 1


def test_agreeing_draft_facts_emit_one_blocker_row():
    layer = _layer()
    view = _view_for(layer, is_draft=True, merge_state_status="DRAFT")
    result = _assess(_train((layer,)), FakeObservations({500: view}))
    assert _codes(result.blockers).count("pr_draft") == 1


def test_required_check_classification():
    layer = _layer()
    checks = (
        land.CheckView(name="ci", is_required=True, outcome="failed"),
        land.CheckView(name="slow", is_required=True, outcome="pending"),
        land.CheckView(name="fuzz", is_required=False, outcome="failed"),
        land.CheckView(name="lint", is_required=True, outcome="passed"),
    )
    result = _assess(_train((layer,)), FakeObservations({500: _view_for(layer, checks=checks)}))
    codes = _codes(result.blockers)
    assert "required_check_failed" in codes and "required_check_pending" in codes
    failed = next(f for f in result.blockers if f.code == "required_check_failed")
    assert "ci" in failed.message
    assert "optional_check_failed" in _codes(result.information)
    row = result.layers[0]
    assert row.required_checks_failed == ("ci",)
    assert row.required_checks_pending == ("slow",)
    assert row.optional_checks_failed == ("fuzz",)


def test_null_review_decision_passes():
    # The one deliberate nullable-pass: null positively means the base requires no review.
    layer = _layer()
    result = _assess(
        _train((layer,)),
        FakeObservations({500: _view_for(layer, review_decision=None)}),
    )
    assert result.disposition is land.LandDisposition.READY


def test_rows_carry_expected_and_observed_values_for_the_renderer():
    # The result value is renderer-complete: expected vs observed refs/SHAs ride the row,
    # never scraped out of finding messages.
    layer = _layer()
    view = _view_for(layer, head_sha=_SHA_D, base_ref="other")
    result = _assess(_train((layer,)), FakeObservations({500: view}))
    row = result.layers[0]
    assert row.expected_base_ref == "main" and row.observed_base_ref == "other"
    assert row.expected_head_sha == _SHA_B and row.observed_head_sha == _SHA_D
    assert row.base_sha == _SHA_A
    assert row.branch == "plan-100" and row.observed_head_ref == "plan-100"


def test_land_never_imports_sync_or_observe():
    # The cycle-neutral import rule: observe → land → {writers, train} — land importing
    # sync (which imports observe) or observe itself would close a cycle.
    tree = ast.parse(inspect.getsource(land))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    assert not any(
        module in {"perk.delivery.sync", "perk.delivery.observe"} for module in imported
    ), imported


def test_declared_vocabulary_sets_stay_disjoint_from_train_codes():
    # The §8.55 bound: the land-only enumeration never collides with a §8.44 code it also
    # composes (one code, one meaning).
    assert "checkpoint_drift" not in land.LAND_BLOCKER_CODES
    assert land.LAND_BLOCKER_CODES.isdisjoint(land.LAND_INFO_CODES)
