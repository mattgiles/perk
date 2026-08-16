from dataclasses import replace
from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import Catalog, Finding
from perk_dev.prose_review import catalog as review_catalog
from perk_dev.prose_review.catalog import (
    CatalogQueryError,
    CatalogSnapshot,
    load_catalog,
)

ROOT = Path(__file__).parents[1]
_PLAN_SKILL = "markdown:skills/perk-plan/SKILL.md"
_PLAN_CONTEXT = "markdown:prompts/contexts/plan-authoring.md"
_PLAN_REVIEW_TOOL = "typescript-tool:plan_review"


@pytest.fixture(scope="module")
def repository_catalog() -> Catalog:
    return build_catalog(ROOT)


@pytest.fixture(scope="module")
def snapshot(repository_catalog: Catalog) -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(repository_catalog)


def test_load_catalog_builds_once_then_queries_memory(
    repository_catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots: list[Path] = []

    def build_once(root: Path) -> Catalog:
        roots.append(root)
        return repository_catalog

    monkeypatch.setattr(review_catalog, "build_catalog", build_once)

    loaded = load_catalog(ROOT)
    loaded.get_unit(_PLAN_SKILL)
    loaded.get_assembly("plan-authoring")
    loaded.aliases_for_unit(_PLAN_SKILL)
    loaded.lineage_for_unit(_PLAN_SKILL)

    assert roots == [ROOT]


def test_snapshot_requires_a_clean_validated_catalog(repository_catalog: Catalog) -> None:
    invalid = replace(
        repository_catalog,
        findings=(Finding(code="fixture", message="deliberately invalid"),),
    )

    with pytest.raises(CatalogQueryError, match="fixture: deliberately invalid"):
        CatalogSnapshot.from_catalog(invalid)


def test_snapshot_covers_the_complete_real_catalog(
    repository_catalog: Catalog, snapshot: CatalogSnapshot
) -> None:
    assert snapshot.units == repository_catalog.units
    assert len(snapshot.fragments) == sum(
        len(unit.candidate.fragments) for unit in repository_catalog.units
    )
    assert snapshot.session_shapes == repository_catalog.graph.session_shapes
    assert [view.assembly for view in snapshot.assemblies] == list(
        repository_catalog.graph.assemblies
    )
    assert snapshot.scenarios == repository_catalog.graph.scenarios
    assert [view.concern for view in snapshot.concerns] == list(repository_catalog.graph.concerns)
    assert [view.lineage for view in snapshot.lineage] == list(repository_catalog.graph.lineage)


def test_capability_tree_has_fixed_roots_and_typed_hierarchy(snapshot: CatalogSnapshot) -> None:
    assert [node.capability.label for node in snapshot.capability_tree] == [
        "Foundation",
        "Intent",
        "Planning",
        "Delivery",
        "Review",
        "Knowledge",
        "Extension & utilities",
    ]
    assert [capability.id for capability in snapshot.capability_breadcrumb("planning.plan")] == [
        "planning",
        "planning.plan",
    ]
    assert snapshot.capability_parent("planning.plan") == snapshot.get_capability("planning")
    assert [capability.id for capability in snapshot.capability_children("planning")] == [
        "planning.objective",
        "planning.plan",
        "planning.replan",
    ]
    assert snapshot.capability_parent("planning") is None
    assert snapshot.capability_breadcrumb("unknown") == ()

    planning = snapshot.capability_tree[2]
    plan_authoring = next(
        child for child in planning.children if child.capability.id == "planning.plan"
    )
    assert plan_authoring.breadcrumb == snapshot.capability_breadcrumb("planning.plan")
    assert plan_authoring.units == snapshot.units_for_capability("planning.plan")
    assert plan_authoring.session_shapes == snapshot.session_shapes_for_capability("planning.plan")


def test_units_for_path_is_a_linear_catalog_order_scan(snapshot: CatalogSnapshot) -> None:
    expected = tuple(unit for unit in snapshot.units if unit.candidate.path == "AGENTS.md")
    assert snapshot.units_for_path("AGENTS.md") == expected
    assert snapshot.units_for_path("missing.md") == ()
    assert "units_by_path" not in snapshot._indexes.__dataclass_fields__


def test_routed_units_and_fragments_have_canonical_identity(snapshot: CatalogSnapshot) -> None:
    unit = snapshot.get_unit(_PLAN_REVIEW_TOOL)
    assert unit is not None
    fragments = snapshot.fragments_for_unit(_PLAN_REVIEW_TOOL)
    assert [fragment.fragment for fragment in fragments] == list(unit.candidate.fragments)

    selected = snapshot.get_fragment(
        _PLAN_REVIEW_TOOL,
        "parameters.properties.plan.description",
    )
    assert selected is not None
    assert selected.unit is unit
    assert selected.fragment.selector == "tool:plan_review.parameters.properties.plan.description"
    assert snapshot.get_fragment(_PLAN_REVIEW_TOOL, "unknown") is None
    assert snapshot.fragments_for_unit("unknown") == ()


def test_assembly_views_preserve_layer_shape_and_scenario_order(
    snapshot: CatalogSnapshot,
) -> None:
    assembly = snapshot.get_assembly("plan-authoring")
    assert assembly is not None
    assert [layer.position for layer in assembly.layers] == [1, 2, 3, 4, 5, 6]
    assert [
        layer.unit.candidate.id if layer.unit is not None else layer.layer.boundary
        for layer in assembly.layers
    ] == [
        "pi-system",
        _PLAN_CONTEXT,
        _PLAN_SKILL,
        "typescript-tool:plan_draft",
        _PLAN_REVIEW_TOOL,
        "user-content",
    ]
    assert [shape.id for shape in assembly.session_shapes] == ["plan.cold", "plan.warm"]
    assert [scenario.id for scenario in assembly.scenarios] == [
        "plan-github-warm",
        "plan-linear-cold",
    ]
    assert assembly.scenarios == snapshot.scenarios_for_assembly("plan-authoring")
    assert snapshot.get_scenario("plan-github-warm") is assembly.scenarios[0]
    assert snapshot.get_assembly("unknown") is None


def test_consumers_and_aliases_distinguish_canonical_and_shape_placements(
    snapshot: CatalogSnapshot,
) -> None:
    unit = snapshot.get_unit(_PLAN_SKILL)
    assert unit is not None

    consumers = snapshot.consumers_for_unit(_PLAN_SKILL)
    assert [(item.assembly.assembly.id, item.layer.position) for item in consumers] == [
        ("plan-authoring", 3)
    ]
    assert consumers[0].layer.unit is unit

    aliases = snapshot.aliases_for_unit(_PLAN_SKILL)
    assert [item.session_shape.id for item in aliases] == ["plan.cold", "plan.warm"]
    assert [item.assembly.assembly.id for item in aliases] == [
        "plan-authoring",
        "plan-authoring",
    ]
    assert all(item.layer.unit is unit for item in aliases)
    assert [capability.label for capability in aliases[0].capability_breadcrumb] == [
        "Planning",
        "Plan authoring",
    ]
    assert snapshot.consumers_for_unit("unknown") == ()
    assert snapshot.aliases_for_unit("unknown") == ()


def test_delivery_siblings_share_capability_and_assembly(snapshot: CatalogSnapshot) -> None:
    assert snapshot.get_session_shape("plan.cold") is snapshot.session_shapes[0]
    assert [shape.id for shape in snapshot.session_shapes_for_capability("planning.plan")] == [
        "plan.cold",
        "plan.warm",
    ]
    assert [shape.id for shape in snapshot.delivery_siblings("plan.cold")] == ["plan.warm"]
    assert [shape.id for shape in snapshot.delivery_siblings("implement.cold")] == [
        "implement.headless"
    ]
    assert snapshot.delivery_siblings("pr-review.warm") == ()
    assert snapshot.delivery_siblings("unknown") == ()


def test_concern_queries_resolve_memberships_and_other_members(snapshot: CatalogSnapshot) -> None:
    concern = snapshot.get_concern("review-first-save")
    assert concern is not None
    assert [member.unit.candidate.id for member in concern.members] == [
        _PLAN_CONTEXT,
        _PLAN_SKILL,
        _PLAN_REVIEW_TOOL,
        "typescript-tool:plan_save",
    ]
    assert concern.members[0].canonical is True
    assert concern.members[0].relation is None
    assert concern.members[1].relation == "Detailed authoring and fallback policy."
    assert snapshot.concerns_for_unit(_PLAN_SKILL) == (concern,)

    canonical_relatives = snapshot.concern_relatives(_PLAN_CONTEXT)
    assert [relative.member.unit.candidate.id for relative in canonical_relatives] == [
        _PLAN_SKILL,
        _PLAN_REVIEW_TOOL,
        "typescript-tool:plan_save",
    ]
    skill_relatives = snapshot.concern_relatives(_PLAN_SKILL)
    assert [relative.member.unit.candidate.id for relative in skill_relatives] == [
        _PLAN_CONTEXT,
        _PLAN_REVIEW_TOOL,
        "typescript-tool:plan_save",
    ]
    assert all(relative.concern is concern.concern for relative in skill_relatives)
    assert snapshot.concerns_for_unit("unknown") == ()
    assert snapshot.concern_relatives("unknown") == ()


def test_lineage_queries_use_the_authored_source_patterns(snapshot: CatalogSnapshot) -> None:
    skill_lineage = snapshot.lineage_for_unit(_PLAN_SKILL)
    assert [view.lineage.id for view in skill_lineage] == ["delivered-skills"]
    assert _PLAN_SKILL in {unit.candidate.id for unit in skill_lineage[0].sources}

    prompt_lineage = snapshot.lineage_for_unit(_PLAN_CONTEXT)
    assert [view.lineage.id for view in prompt_lineage] == ["packaged-prompts"]

    ambient_lineage = snapshot.get_lineage("ambient-index")
    assert ambient_lineage is not None
    assert [unit.candidate.id for unit in ambient_lineage.sources] == ["ambient:learned-routing"]
    assert snapshot.lineage_for_unit("unknown") == ()
    assert snapshot.get_lineage("unknown") is None
