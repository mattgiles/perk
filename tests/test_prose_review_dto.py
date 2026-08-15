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
    SessionShapeOut,
    UnitSourceOut,
)
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
