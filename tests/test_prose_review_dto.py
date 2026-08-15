"""The Prose Review Workbench serialization edge: snapshot → wire DTOs."""

import json
from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_review.catalog import CapabilityNode, CatalogSnapshot
from perk_dev.prose_review.dto import (
    CapabilityNodeOut,
    CapabilityTreeOut,
    CatalogSummaryOut,
    SearchOut,
    SessionShapeOut,
    UnitInspectOut,
    UnitSourceOut,
)
from perk_dev.prose_review.search import build_search_index, search
from perk_dev.prose_review.source_adapter import WholeFileSource

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def snapshot() -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(build_catalog(ROOT))


@pytest.fixture(scope="module")
def summary(snapshot: CatalogSnapshot) -> CatalogSummaryOut:
    return CatalogSummaryOut.from_domain(snapshot)


def test_counts_match_the_snapshot_tuples(
    snapshot: CatalogSnapshot, summary: CatalogSummaryOut
) -> None:
    assert summary.units == len(snapshot.units)
    assert summary.fragments == len(snapshot.fragments)
    assert summary.session_shapes == len(snapshot.session_shapes)
    assert summary.assemblies == len(snapshot.assemblies)
    assert summary.scenarios == len(snapshot.scenarios)
    assert summary.concerns == len(snapshot.concerns)
    assert summary.lineage_rules == len(snapshot.lineage)


def test_capabilities_are_the_fixed_order_top_level_ids_and_labels(
    summary: CatalogSummaryOut,
) -> None:
    assert [(capability.id, capability.label) for capability in summary.capabilities] == [
        ("foundation", "Foundation"),
        ("intent", "Intent"),
        ("planning", "Planning"),
        ("delivery", "Delivery"),
        ("review", "Review"),
        ("knowledge", "Knowledge"),
        ("extension", "Extension & utilities"),
    ]


def test_json_dump_is_serializable_with_declared_key_order(summary: CatalogSummaryOut) -> None:
    dumped = summary.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert list(dumped.keys()) == [
        "units",
        "fragments",
        "session_shapes",
        "assemblies",
        "scenarios",
        "concerns",
        "lineage_rules",
        "capabilities",
    ]
    assert dumped["capabilities"][0] == {
        "id": summary.capabilities[0].id,
        "label": "Foundation",
    }


@pytest.fixture(scope="module")
def tree(snapshot: CatalogSnapshot) -> CapabilityTreeOut:
    return CapabilityTreeOut.from_domain(snapshot)


def test_tree_top_level_is_the_seven_fixed_capabilities(tree: CapabilityTreeOut) -> None:
    assert [(node.id, node.label) for node in tree.capabilities] == [
        ("foundation", "Foundation"),
        ("intent", "Intent"),
        ("planning", "Planning"),
        ("delivery", "Delivery"),
        ("review", "Review"),
        ("knowledge", "Knowledge"),
        ("extension", "Extension & utilities"),
    ]


def test_tree_recursive_node_count_matches_the_snapshot(
    snapshot: CatalogSnapshot, tree: CapabilityTreeOut
) -> None:
    def count_out(node: CapabilityNodeOut) -> int:
        return 1 + sum(count_out(child) for child in node.children)

    def count_domain(node: CapabilityNode) -> int:
        return 1 + sum(count_domain(child) for child in node.children)

    assert sum(count_out(node) for node in tree.capabilities) == sum(
        count_domain(node) for node in snapshot.capability_tree
    )


def _shape_out(tree: CapabilityTreeOut, shape_id: str) -> SessionShapeOut | None:
    def walk(nodes: tuple[CapabilityNodeOut, ...]) -> SessionShapeOut | None:
        for node in nodes:
            for shape in node.session_shapes:
                if shape.id == shape_id:
                    return shape
            found = walk(node.children)
            if found is not None:
                return found
        return None

    return walk(tree.capabilities)


def test_sampled_shape_layers_mirror_the_assembly_view_order(
    snapshot: CatalogSnapshot, tree: CapabilityTreeOut
) -> None:
    shape_out = _shape_out(tree, "plan.warm")
    assert shape_out is not None
    shape = snapshot.get_session_shape("plan.warm")
    assert shape is not None
    assembly = snapshot.get_assembly(shape.assembly)
    assert assembly is not None
    assert [layer.position for layer in shape_out.layers] == list(
        range(1, len(assembly.layers) + 1)
    )
    assert [
        (layer.position, layer.label, None if layer.unit is None else layer.unit.id)
        for layer in shape_out.layers
    ] == [
        (
            view.position,
            view.layer.label,
            None if view.unit is None else view.unit.candidate.id,
        )
        for view in assembly.layers
    ]


def test_boundary_layer_serializes_with_no_unit_and_its_kind(tree: CapabilityTreeOut) -> None:
    shape_out = _shape_out(tree, "plan.warm")
    assert shape_out is not None
    first = shape_out.layers[0]
    assert first.unit is None
    assert first.boundary == "pi-system"
    unit_layers = [layer for layer in shape_out.layers if layer.unit is not None]
    assert unit_layers, "sampled shape has no unit layers"
    assert all(layer.boundary is None for layer in unit_layers)


def test_tree_json_dump_is_serializable_with_declared_key_order(tree: CapabilityTreeOut) -> None:
    dumped = tree.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert list(dumped.keys()) == ["capabilities"]
    node = dumped["capabilities"][0]
    assert list(node.keys()) == ["id", "label", "units", "session_shapes", "children"]
    child = node["children"][0]
    assert list(child.keys()) == ["id", "label", "units", "session_shapes", "children"]


def test_shape_and_layer_key_order_matches_declaration(tree: CapabilityTreeOut) -> None:
    shape_out = _shape_out(tree, "plan.warm")
    assert shape_out is not None
    dumped = shape_out.model_dump(mode="json")
    assert list(dumped.keys()) == ["id", "label", "delivery", "layers"]
    assert list(dumped["layers"][0].keys()) == [
        "position",
        "optional",
        "label",
        "unit",
        "boundary",
    ]


@pytest.fixture(scope="module")
def inspect_out(snapshot: CatalogSnapshot) -> UnitInspectOut:
    unit = snapshot.get_unit("typescript-tool:plan_review")
    assert unit is not None
    return UnitInspectOut.from_domain(snapshot, unit)


def test_unit_inspect_out_identity_matches_the_routed_unit(
    snapshot: CatalogSnapshot, inspect_out: UnitInspectOut
) -> None:
    unit = snapshot.get_unit("typescript-tool:plan_review")
    assert unit is not None
    assert inspect_out.id == unit.candidate.id
    assert inspect_out.kind == unit.candidate.kind
    assert inspect_out.path == unit.candidate.path
    assert inspect_out.selector == unit.candidate.selector
    assert inspect_out.audience == unit.audience
    assert inspect_out.role == unit.role
    assert [c.id for c in inspect_out.breadcrumb] == [
        c.id for c in snapshot.capability_breadcrumb(unit.capability)
    ]
    assert inspect_out.breadcrumb, "breadcrumb must reach the assigned capability"


def test_unit_inspect_out_relationships_mirror_the_snapshot_queries(
    snapshot: CatalogSnapshot, inspect_out: UnitInspectOut
) -> None:
    unit_id = "typescript-tool:plan_review"
    consumers = snapshot.consumers_for_unit(unit_id)
    assert [(c.assembly, c.position, c.label, c.optional) for c in inspect_out.consumers] == [
        (c.assembly.assembly.id, c.layer.position, c.layer.layer.label, c.layer.layer.optional)
        for c in consumers
    ]
    assert inspect_out.consumers, "sampled unit has no consumers"

    # One shape entry per consuming shape (aliases deduped by shape id), each
    # carrying that shape's delivery siblings.
    alias_shape_ids = []
    for alias in snapshot.aliases_for_unit(unit_id):
        if alias.session_shape.id not in alias_shape_ids:
            alias_shape_ids.append(alias.session_shape.id)
    assert [shape.id for shape in inspect_out.shapes] == alias_shape_ids
    assert inspect_out.shapes, "sampled unit is consumed by no shape"
    for shape_out in inspect_out.shapes:
        assert [s.id for s in shape_out.siblings] == [
            s.id for s in snapshot.delivery_siblings(shape_out.id)
        ]

    views = snapshot.concerns_for_unit(unit_id)
    assert [concern.id for concern in inspect_out.concerns] == [view.concern.id for view in views]
    assert inspect_out.concerns, "sampled unit belongs to no concern"
    for concern_out, view in zip(inspect_out.concerns, views, strict=True):
        selected = next(m for m in view.members if m.unit.candidate.id == unit_id)
        assert concern_out.canonical == selected.canonical
        assert concern_out.relation == selected.relation
        assert [member.unit.id for member in concern_out.members] == [
            m.unit.candidate.id for m in view.members if m.unit.candidate.id != unit_id
        ]


def test_unit_inspect_out_json_key_order_of_every_new_model(
    inspect_out: UnitInspectOut,
) -> None:
    dumped = inspect_out.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert list(dumped.keys()) == [
        "id",
        "kind",
        "path",
        "selector",
        "audience",
        "role",
        "breadcrumb",
        "capability_children",
        "consumers",
        "shapes",
        "concerns",
        "lineage",
    ]
    assert list(dumped["breadcrumb"][0].keys()) == ["id", "label"]
    assert list(dumped["consumers"][0].keys()) == ["assembly", "position", "label", "optional"]
    shape = dumped["shapes"][0]
    assert list(shape.keys()) == ["id", "label", "delivery", "breadcrumb", "siblings"]
    assert list(shape["siblings"][0].keys()) == ["id", "label", "delivery"]
    concern = dumped["concerns"][0]
    assert list(concern.keys()) == [
        "id",
        "label",
        "summary",
        "canonical",
        "relation",
        "members",
    ]
    assert list(concern["members"][0].keys()) == ["unit", "relation", "canonical"]


def test_lineage_out_shape_for_a_lineage_bearing_unit(snapshot: CatalogSnapshot) -> None:
    view = next(view for view in snapshot.lineage if view.sources)
    unit = view.sources[0]
    dumped = UnitInspectOut.from_domain(snapshot, unit).model_dump(mode="json")
    assert dumped["lineage"], "discovered unit lost its lineage rule"
    rule = dumped["lineage"][0]
    assert list(rule.keys()) == ["id", "relationship", "targets"]
    assert rule["relationship"] in ("generated-from", "materializes-to", "bundled-as")
    assert rule["targets"], "authored lineage rules always carry targets"


def test_search_out_key_order_from_real_hits(snapshot: CatalogSnapshot) -> None:
    index = build_search_index(snapshot)
    results = search(index, "plan_review")
    out = SearchOut.from_domain(results)
    assert out.total == results.total
    dumped = out.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert list(dumped.keys()) == ["total", "results"]
    result = dumped["results"][0]
    assert list(result.keys()) == ["kind", "id", "label", "breadcrumb", "unit", "matched"]
    assert list(result["breadcrumb"][0].keys()) == ["id", "label"]
    unit_result = next(entry for entry in dumped["results"] if entry["unit"] is not None)
    assert list(unit_result["unit"].keys()) == ["id", "kind", "path"]


def test_unit_source_out_field_order() -> None:
    source = WholeFileSource(
        unit_id="markdown:AGENTS.md",
        path="AGENTS.md",
        kind="markdown",
        text="content\n",
    )
    dumped = UnitSourceOut.from_domain(source).model_dump(mode="json")
    assert list(dumped.keys()) == ["unit", "path", "kind", "content"]
    assert dumped == {
        "unit": "markdown:AGENTS.md",
        "path": "AGENTS.md",
        "kind": "markdown",
        "content": "content\n",
    }
