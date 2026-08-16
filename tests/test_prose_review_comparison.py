"""Whole-unit comparison semantics projected from the immutable catalog snapshot."""

from dataclasses import replace
from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import (
    Candidate,
    Capability,
    Catalog,
    Concern,
    ConcernRelation,
    ProseMap,
    RoutedUnit,
)
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.comparison import (
    ComparisonGroup,
    ComparisonOptions,
    comparison_options,
)

ROOT = Path(__file__).parents[1]
_PLAN_CONTEXT = "markdown:prompts/contexts/plan-authoring.md"
_PLAN_SKILL = "markdown:skills/perk-plan/SKILL.md"
_PLAN_DRAFT = "typescript-tool:plan_draft"
_PLAN_REVIEW = "typescript-tool:plan_review"


@pytest.fixture(scope="module")
def repository_catalog() -> Catalog:
    return build_catalog(ROOT)


@pytest.fixture(scope="module")
def snapshot(repository_catalog: Catalog) -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(repository_catalog)


def _options(
    snapshot: CatalogSnapshot,
    unit_id: str,
    *,
    shape_id: str | None = None,
    position: int | None = None,
) -> ComparisonOptions:
    options = comparison_options(
        snapshot,
        unit_id,
        shape_id=shape_id,
        position=position,
    )
    assert options is not None
    return options


def _group(options: ComparisonOptions, relation: str) -> ComparisonGroup:
    return next(group for group in options.groups if group.relation == relation)


def test_unplaced_origin_is_canonical_and_groups_have_fixed_order_and_labels(
    snapshot: CatalogSnapshot,
) -> None:
    options = _options(snapshot, _PLAN_SKILL)

    assert options.origin.locator() == (_PLAN_SKILL, None, None, None)
    assert [capability.id for capability in options.origin.breadcrumb] == [
        "planning",
        "planning.plan",
    ]
    assert options.origin.label == _PLAN_SKILL
    assert [(group.relation, group.label) for group in options.groups] == [
        ("delivery-sibling", "Delivery siblings"),
        ("adjacent-layer", "Adjacent assembly layers"),
        ("alias-consumer", "Alias consumers"),
        ("concern-relative", "Concern relatives"),
        ("capability-parent-child", "Capability parent / child"),
    ]
    assert all(group.choices for group in options.groups)


def test_delivery_siblings_keep_distinct_placements_for_one_canonical_unit(
    snapshot: CatalogSnapshot,
) -> None:
    options = _options(snapshot, _PLAN_SKILL, shape_id="plan.warm", position=3)
    group = _group(options, "delivery-sibling")

    assert options.origin.locator() == (
        _PLAN_SKILL,
        "plan.warm",
        "plan-authoring",
        3,
    )
    assert options.origin.label == "Bound plan skill"
    assert [(choice.label, choice.detail, choice.target.locator()) for choice in group.choices] == [
        (
            "Plan authoring — cold door",
            "plan-authoring #3 · Bound plan skill",
            (_PLAN_SKILL, "plan.cold", "plan-authoring", 3),
        )
    ]
    assert group.choices[0].target.unit is options.origin.unit
    assert group.choices[0].target.breadcrumb == options.origin.breadcrumb


def test_adjacency_preserves_authored_direction_and_does_not_skip_boundaries(
    snapshot: CatalogSnapshot,
) -> None:
    middle = _options(snapshot, _PLAN_SKILL, shape_id="plan.warm", position=3)
    choices = _group(middle, "adjacent-layer").choices
    assert [(choice.label, choice.target.locator()) for choice in choices] == [
        (
            "Previous layer · Plan-authoring flow",
            (_PLAN_CONTEXT, "plan.warm", "plan-authoring", 2),
        ),
        (
            "Next layer · Working draft contract",
            (_PLAN_DRAFT, "plan.warm", "plan-authoring", 4),
        ),
    ]
    assert choices[0].detail == (
        "From Plan authoring — warm door · plan-authoring #3 · Bound plan skill "
        "to Plan authoring — warm door · plan-authoring #2 · Plan-authoring flow"
    )

    next_to_boundary = _options(
        snapshot,
        _PLAN_CONTEXT,
        shape_id="plan.warm",
        position=2,
    )
    boundary_choices = _group(next_to_boundary, "adjacent-layer").choices
    assert [choice.label for choice in boundary_choices] == ["Next layer · Bound plan skill"]
    assert all(choice.target.position != 1 for choice in boundary_choices)

    before_boundary = _options(snapshot, _PLAN_REVIEW, shape_id="plan.warm", position=5)
    assert [choice.label for choice in _group(before_boundary, "adjacent-layer").choices] == [
        "Previous layer · Working draft contract"
    ]


def test_alias_consumers_cover_every_anchor_and_exclude_only_exact_placed_origin(
    snapshot: CatalogSnapshot,
) -> None:
    unplaced = _options(snapshot, _PLAN_SKILL)
    unplaced_choices = _group(unplaced, "alias-consumer").choices
    assert [choice.target.locator() for choice in unplaced_choices] == [
        (_PLAN_SKILL, "plan.cold", "plan-authoring", 3),
        (_PLAN_SKILL, "plan.warm", "plan-authoring", 3),
    ]
    assert all(choice.target.unit is unplaced.origin.unit for choice in unplaced_choices)

    placed = _options(snapshot, _PLAN_SKILL, shape_id="plan.warm", position=3)
    placed_choices = _group(placed, "alias-consumer").choices
    assert [choice.target.locator() for choice in placed_choices] == [
        (_PLAN_SKILL, "plan.cold", "plan-authoring", 3)
    ]
    assert placed_choices[0].detail == (
        "Plan authoring — cold door · plan-authoring #3 · Bound plan skill"
    )


def test_concern_relatives_preserve_member_order_standing_and_copy(
    snapshot: CatalogSnapshot,
) -> None:
    choices = _group(_options(snapshot, _PLAN_SKILL), "concern-relative").choices

    assert [(choice.label, choice.detail) for choice in choices] == [
        (_PLAN_CONTEXT, "Review-first save · canonical"),
        (
            _PLAN_REVIEW,
            "Review-first save · Model-visible review and auto-save contract.",
        ),
        (
            "typescript-tool:plan_save",
            "Review-first save · Mechanical persistence surface.",
        ),
    ]
    assert all(choice.target.shape is None for choice in choices)
    assert all(choice.target.assembly is None for choice in choices)


def test_capability_projection_is_parent_first_preorder_and_canonical_only(
    snapshot: CatalogSnapshot,
) -> None:
    options = _options(snapshot, _PLAN_REVIEW)
    choices = _group(options, "capability-parent-child").choices

    expected: list[tuple[str, str]] = []
    parent = snapshot.capability_parent("review.drafts")
    assert parent is not None
    parent_label = parent.label

    def visit(capability_id: str) -> None:
        expected.extend(
            (unit.candidate.id, f"Parent capability · {parent_label}")
            for unit in snapshot.units_for_capability(capability_id)
            if unit.candidate.id != _PLAN_REVIEW
        )
        for child in snapshot.capability_children(capability_id):
            visit(child.id)

    visit(parent.id)
    assert [(choice.label, choice.detail) for choice in choices] == expected
    assert all(choice.target.shape is None for choice in choices)
    assert all(choice.target.assembly is None for choice in choices)
    assert _PLAN_SKILL not in [choice.target.unit.candidate.id for choice in choices]


def test_placement_relations_collapse_exact_duplicate_producers_to_the_first(
    repository_catalog: Catalog,
) -> None:
    cold = next(
        shape for shape in repository_catalog.graph.session_shapes if shape.id == "plan.cold"
    )
    duplicate_cold = replace(cold, label="Duplicate cold must lose")
    graph = replace(
        repository_catalog.graph,
        session_shapes=(*repository_catalog.graph.session_shapes, duplicate_cold),
    )
    collision_snapshot = CatalogSnapshot.from_catalog(replace(repository_catalog, graph=graph))

    placed = _options(collision_snapshot, _PLAN_SKILL, shape_id="plan.warm", position=3)
    delivery = _group(placed, "delivery-sibling").choices
    assert [(choice.label, choice.target.locator()) for choice in delivery] == [
        (
            "Plan authoring — cold door",
            (_PLAN_SKILL, "plan.cold", "plan-authoring", 3),
        )
    ]

    aliases = _group(_options(collision_snapshot, _PLAN_SKILL), "alias-consumer").choices
    assert [(choice.detail, choice.target.locator()) for choice in aliases] == [
        (
            "Plan authoring — cold door · plan-authoring #3 · Bound plan skill",
            (_PLAN_SKILL, "plan.cold", "plan-authoring", 3),
        ),
        (
            "Plan authoring — warm door · plan-authoring #3 · Bound plan skill",
            (_PLAN_SKILL, "plan.warm", "plan-authoring", 3),
        ),
    ]


def test_adjacency_keeps_distinct_origins_and_directions_in_authored_order(
    repository_catalog: Catalog,
) -> None:
    cold = next(
        shape for shape in repository_catalog.graph.session_shapes if shape.id == "plan.cold"
    )
    graph = replace(
        repository_catalog.graph,
        session_shapes=(
            *repository_catalog.graph.session_shapes,
            replace(cold, label="Duplicate cold must lose"),
        ),
    )
    collision_snapshot = CatalogSnapshot.from_catalog(replace(repository_catalog, graph=graph))

    adjacency = _group(
        _options(collision_snapshot, _PLAN_SKILL),
        "adjacent-layer",
    ).choices
    assert [(choice.label, choice.target.locator()) for choice in adjacency] == [
        (
            "Previous layer · Plan-authoring flow",
            (_PLAN_CONTEXT, "plan.cold", "plan-authoring", 2),
        ),
        (
            "Next layer · Working draft contract",
            (_PLAN_DRAFT, "plan.cold", "plan-authoring", 4),
        ),
        (
            "Previous layer · Plan-authoring flow",
            (_PLAN_CONTEXT, "plan.warm", "plan-authoring", 2),
        ),
        (
            "Next layer · Working draft contract",
            (_PLAN_DRAFT, "plan.warm", "plan-authoring", 4),
        ),
    ]
    assert all("Duplicate cold must lose" not in choice.detail for choice in adjacency)


def test_concern_deduplication_uses_concern_id_and_keeps_first_member_copy(
    repository_catalog: Catalog,
) -> None:
    first = Concern(
        id="collision-first",
        label="Shared concern label",
        summary="First collision witness.",
        canonical_unit=_PLAN_SKILL,
        related=(
            ConcernRelation(unit=_PLAN_REVIEW, relation="first standing"),
            ConcernRelation(unit=_PLAN_REVIEW, relation="duplicate must lose"),
        ),
    )
    second = replace(first, id="collision-second", summary="Second collision witness.")
    graph = replace(repository_catalog.graph, concerns=(first, second))
    collision_snapshot = CatalogSnapshot.from_catalog(replace(repository_catalog, graph=graph))

    concerns = _group(
        _options(collision_snapshot, _PLAN_SKILL),
        "concern-relative",
    ).choices
    assert [(choice.label, choice.detail, choice.target.locator()) for choice in concerns] == [
        (
            _PLAN_REVIEW,
            "Shared concern label · first standing",
            (_PLAN_REVIEW, None, None, None),
        ),
        (
            _PLAN_REVIEW,
            "Shared concern label · first standing",
            (_PLAN_REVIEW, None, None, None),
        ),
    ]


def _synthetic_unit(unit_id: str, capability: str) -> RoutedUnit:
    return RoutedUnit(
        candidate=Candidate(
            id=unit_id,
            kind="markdown",
            path=f"{unit_id}.md",
            selector="whole-file",
            fragments=(),
        ),
        capability=capability,
        audience="shipped",
        role="context",
    )


def test_capability_deduplication_keeps_relationship_and_anchor_dimensions() -> None:
    target_id = "unit:target"
    target = _synthetic_unit(target_id, "root")
    origin = _synthetic_unit("unit:origin", "origin")
    target_in_child = replace(target, capability="child")
    graph = ProseMap(
        capabilities=(
            Capability(id="root", label="Root", summary="Root capability.", parent=None),
            Capability(id="origin", label="Origin", summary="Origin capability.", parent="root"),
            Capability(id="child", label="Child", summary="Child capability.", parent="origin"),
        ),
        routes=(),
        exclusions=(),
        session_shapes=(),
        assemblies=(),
        scenarios=(),
        concerns=(),
        lineage=(),
    )
    catalog = Catalog(
        graph=graph,
        units=(target, origin, target_in_child),
        excluded=(),
        findings=(),
        governed_tools=(),
    )
    collision_snapshot = CatalogSnapshot.from_catalog(catalog)

    capability = _group(
        _options(collision_snapshot, origin.candidate.id),
        "capability-parent-child",
    ).choices
    assert [
        (
            choice.label,
            choice.detail,
            tuple(item.id for item in choice.target.breadcrumb),
        )
        for choice in capability
    ] == [
        (target_id, "Parent capability · Root", ("root",)),
        (target_id, "Child capability · Child", ("root", "origin", "child")),
    ]


def test_minimal_snapshot_can_return_a_successful_empty_option_set(
    repository_catalog: Catalog,
) -> None:
    unit = repository_catalog.units[0]
    graph = replace(
        repository_catalog.graph,
        session_shapes=(),
        assemblies=(),
        scenarios=(),
        concerns=(),
        lineage=(),
    )
    minimal = CatalogSnapshot.from_catalog(replace(repository_catalog, graph=graph, units=(unit,)))

    options = _options(minimal, unit.candidate.id)
    assert options.origin.locator() == (unit.candidate.id, None, None, None)
    assert options.groups == ()


@pytest.mark.parametrize(
    ("unit_id", "shape_id", "position"),
    [
        ("unknown", None, None),
        (_PLAN_SKILL, "plan.warm", None),
        (_PLAN_SKILL, None, 3),
        (_PLAN_SKILL, "unknown", 3),
        (_PLAN_SKILL, "plan.warm", 0),
        (_PLAN_SKILL, "plan.warm", -1),
        (_PLAN_SKILL, "plan.warm", 99),
        (_PLAN_SKILL, "plan.warm", 1),
        (_PLAN_REVIEW, "plan.warm", 3),
    ],
)
def test_unknown_or_incoherent_subjects_return_none(
    snapshot: CatalogSnapshot,
    unit_id: str,
    shape_id: str | None,
    position: int | None,
) -> None:
    assert (
        comparison_options(
            snapshot,
            unit_id,
            shape_id=shape_id,
            position=position,
        )
        is None
    )
