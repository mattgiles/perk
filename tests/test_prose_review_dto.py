"""The Prose Review Workbench serialization edge: snapshot → wire DTOs."""

import hashlib
import json
from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import (
    Assembly,
    AssemblyLayer,
    Candidate,
    Fragment,
    RoutedUnit,
    Scenario,
)
from perk_dev.prose_review.assembly import (
    AssemblyLayerProblem,
    AssemblyRenderer,
    FailedAssemblyLayer,
    LayerPresence,
    LayerPresentation,
    PresentationControl,
    PresentationOverrides,
    RenderedAssembly,
    RenderedBoundaryLayer,
    RenderedContentPart,
    RenderedOwnedLayer,
    ResolvedPresentation,
)
from perk_dev.prose_review.catalog import CapabilityNode, CatalogSnapshot
from perk_dev.prose_review.comparison import (
    ComparisonChoice,
    ComparisonGroup,
    ComparisonOptions,
    ComparisonPlacement,
    comparison_options,
)
from perk_dev.prose_review.dto import (
    AssemblyOptionsOut,
    AssemblyRenderOut,
    CapabilityNodeOut,
    CapabilityTreeOut,
    CatalogSummaryOut,
    ComparisonOptionsOut,
    ComparisonPlacementOut,
    FragmentRefOut,
    SavedSourceOut,
    SearchOut,
    SessionShapeOut,
    SourceConflictOut,
    SourceDiagnosticOut,
    SourceFileOut,
    SourceRefusedOut,
    SourceSavedOut,
    SourceValidationFailedOut,
    SourceViewOut,
    SuggestedCheckOut,
    TreeUnitOut,
    UnitInspectOut,
    UnitSourceOut,
)
from perk_dev.prose_review.search import build_search_index, search
from perk_dev.prose_review.source_adapter import (
    FocusedSource,
    LoadedSource,
    SourceConflict,
    SourceDiagnostic,
    SourceRefused,
    SourceSaved,
    SourceValidationFailed,
    SuggestedCheck,
    WholeFileSource,
)
from perk_dev.prose_review.source_adapter.typescript import TypeScriptSourceAdapter

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
    assert shape_out.assembly == shape.assembly
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
    assert list(dumped.keys()) == ["id", "label", "delivery", "assembly", "layers"]
    assert list(dumped["layers"][0].keys()) == [
        "position",
        "optional",
        "label",
        "unit",
        "boundary",
    ]
    unit_layer = next(layer for layer in dumped["layers"] if layer["unit"] is not None)
    assert list(unit_layer["unit"].keys()) == ["id", "kind", "path", "fragments"]
    assert all(
        list(fragment.keys()) == ["id", "label"] for fragment in unit_layer["unit"]["fragments"]
    )


def test_tree_unit_fragments_match_snapshot_order(snapshot: CatalogSnapshot) -> None:
    unit = snapshot.get_unit("managed:repo-agents")
    assert unit is not None
    out = TreeUnitOut.from_domain(unit)
    assert [(fragment.id, fragment.label) for fragment in out.fragments] == [
        (routed.fragment.id, routed.fragment.label)
        for routed in snapshot.fragments_for_unit(unit.candidate.id)
    ]
    fragment = unit.candidate.fragments[0]
    assert FragmentRefOut.from_domain(fragment).model_dump(mode="json") == {
        "id": fragment.id,
        "label": fragment.label,
    }


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


def test_comparison_out_matches_projection_with_exact_nested_key_order(
    snapshot: CatalogSnapshot,
) -> None:
    options = comparison_options(
        snapshot,
        "markdown:skills/perk-plan/SKILL.md",
        shape_id="plan.warm",
        position=3,
    )
    assert options is not None
    dumped = ComparisonOptionsOut.from_domain(options).model_dump(mode="json")
    json.dumps(dumped)

    assert list(dumped) == ["origin", "groups"]
    assert list(dumped["origin"]) == [
        "unit",
        "breadcrumb",
        "shape",
        "assembly",
        "position",
        "label",
    ]
    assert list(dumped["origin"]["unit"]) == ["id", "kind", "path"]
    assert list(dumped["origin"]["breadcrumb"][0]) == ["id", "label"]
    assert list(dumped["origin"]["shape"]) == ["id", "label", "delivery"]
    assert [group["relation"] for group in dumped["groups"]] == [
        "delivery-sibling",
        "adjacent-layer",
        "alias-consumer",
        "concern-relative",
        "capability-parent-child",
    ]
    assert all(list(group) == ["relation", "label", "choices"] for group in dumped["groups"])
    assert all(group["choices"] for group in dumped["groups"])
    for group in dumped["groups"]:
        assert all(list(choice) == ["label", "detail", "target"] for choice in group["choices"])
        assert all(choice["detail"] is not None for choice in group["choices"])


def test_comparison_placement_out_supports_exactly_the_three_domain_variants(
    snapshot: CatalogSnapshot,
) -> None:
    unit = snapshot.get_unit("markdown:skills/perk-plan/SKILL.md")
    shape = snapshot.get_session_shape("plan.warm")
    assert unit is not None
    assert shape is not None
    breadcrumb = snapshot.capability_breadcrumb(unit.capability)
    placements = (
        ComparisonPlacement(
            unit=unit,
            breadcrumb=breadcrumb,
            shape=None,
            assembly=None,
            position=None,
            label=unit.candidate.id,
        ),
        ComparisonPlacement(
            unit=unit,
            breadcrumb=breadcrumb,
            shape=None,
            assembly="unshaped-assembly",
            position=2,
            label="Unshaped layer",
        ),
        ComparisonPlacement(
            unit=unit,
            breadcrumb=breadcrumb,
            shape=shape,
            assembly="plan-authoring",
            position=3,
            label="Bound plan skill",
        ),
    )

    dumped = [
        ComparisonPlacementOut.from_domain(item).model_dump(mode="json") for item in placements
    ]
    assert [(item["shape"], item["assembly"], item["position"]) for item in dumped] == [
        (None, None, None),
        (None, "unshaped-assembly", 2),
        (
            {
                "id": "plan.warm",
                "label": "Plan authoring — warm door",
                "delivery": "warm",
            },
            "plan-authoring",
            3,
        ),
    ]


def test_comparison_out_allows_an_empty_top_level_group_list(
    snapshot: CatalogSnapshot,
) -> None:
    unit = snapshot.get_unit("markdown:skills/perk-plan/SKILL.md")
    assert unit is not None
    origin = ComparisonPlacement(
        unit=unit,
        breadcrumb=snapshot.capability_breadcrumb(unit.capability),
        shape=None,
        assembly=None,
        position=None,
        label=unit.candidate.id,
    )
    assert ComparisonOptionsOut.from_domain(ComparisonOptions(origin=origin, groups=())).model_dump(
        mode="json"
    ) == {
        "origin": ComparisonPlacementOut.from_domain(origin).model_dump(mode="json"),
        "groups": [],
    }

    with pytest.raises(ValueError, match="require a label and choices"):
        ComparisonGroup(relation="alias-consumer", label="Alias consumers", choices=())
    with pytest.raises(ValueError, match="require labels and details"):
        ComparisonChoice(label="", detail="detail", target=origin)


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


def test_unit_source_out_has_nested_file_and_view_with_exact_field_order() -> None:
    content = "context\r\ncontent 😀\r\ntail"
    raw = content.encode("utf-8")
    file = WholeFileSource(
        unit_id="markdown:AGENTS.md",
        path="AGENTS.md",
        kind="markdown",
        content=raw,
        mode=0o6751,
        newline_style="crlf",
        load_hash=hashlib.sha256(raw).hexdigest(),
    )
    view = FocusedSource(
        unit_id="markdown:AGENTS.md",
        kind="markdown",
        fragment=Fragment(id="body", label="Document body", selector="file-body"),
        before="context\r\n",
        focus="content 😀\r\n",
        after="tail",
        editable=True,
        read_only_reason=None,
    )
    dumped = UnitSourceOut.from_domain(LoadedSource(file=file, view=view)).model_dump(mode="json")
    assert list(dumped) == ["file", "view"]
    assert list(dumped["file"]) == ["path", "mode", "newline_style", "load_hash"]
    assert list(dumped["view"]) == [
        "unit",
        "fragment",
        "kind",
        "before",
        "focus",
        "after",
        "editable",
        "read_only_reason",
    ]
    assert dumped == {
        "file": {
            "path": "AGENTS.md",
            "mode": 0o6751,
            "newline_style": "crlf",
            "load_hash": hashlib.sha256(raw).hexdigest(),
        },
        "view": {
            "unit": "markdown:AGENTS.md",
            "fragment": {"id": "body", "label": "Document body"},
            "kind": "markdown",
            "before": "context\r\n",
            "focus": "content 😀\r\n",
            "after": "tail",
            "editable": True,
            "read_only_reason": None,
        },
    }
    assert dumped["view"]["before"] + dumped["view"]["focus"] + dumped["view"]["after"] == content
    assert SourceFileOut.from_domain(file).model_dump(mode="json") == dumped["file"]
    assert SourceViewOut.from_domain(view).model_dump(mode="json") == dumped["view"]


def test_save_result_dtos_have_exact_tagged_shapes_and_reuse_lineage(
    snapshot: CatalogSnapshot,
) -> None:
    raw = "saved 😀\r\n".encode()
    source = WholeFileSource(
        unit_id="ambient:learned-routing",
        path="docs/learned/clusters.yaml",
        kind="ambient-routing",
        content=raw,
        mode=0o6751,
        newline_style="crlf",
        load_hash=hashlib.sha256(raw).hexdigest(),
    )
    lineage = snapshot.get_lineage("ambient-index")
    assert lineage is not None
    saved = SourceSaved(
        status="saved",
        source=source,
        materialized=(lineage,),
        checks=(
            SuggestedCheck(id="prose-map", command="perk-dev prose-map check"),
            SuggestedCheck(id="learned-docs", command="perk learn docs-check"),
        ),
        catalog_refreshed=False,
        refresh_detail="refresh failed",
    )
    dumped = SourceSavedOut.from_domain(saved).model_dump(mode="json")
    assert list(dumped) == [
        "status",
        "source",
        "materialized",
        "checks",
        "catalog_refreshed",
        "refresh_detail",
    ]
    assert list(dumped["source"]) == ["unit", "kind", "file"]
    assert list(dumped["source"]["file"]) == ["path", "mode", "newline_style", "load_hash"]
    assert list(dumped["materialized"][0]) == ["id", "relationship", "targets"]
    assert [list(check) for check in dumped["checks"]] == [
        ["id", "command"],
        ["id", "command"],
    ]
    assert SavedSourceOut.from_domain(source).model_dump(mode="json") == dumped["source"]
    assert SuggestedCheckOut.from_domain(saved.checks[0]).model_dump(mode="json") == {
        "id": "prose-map",
        "command": "perk-dev prose-map check",
    }

    diagnostic = SourceDiagnostic(
        code="selector-not-found",
        message="missing",
        selector="heading:missing",
        line=2,
        column=3,
    )
    validation = SourceValidationFailedOut.from_domain(
        SourceValidationFailed(status="validation-failed", diagnostics=(diagnostic,))
    ).model_dump(mode="json")
    assert list(validation) == ["status", "diagnostics"]
    assert list(validation["diagnostics"][0]) == [
        "code",
        "message",
        "selector",
        "line",
        "column",
    ]
    assert (
        SourceDiagnosticOut.from_domain(diagnostic).model_dump(mode="json")
        == validation["diagnostics"][0]
    )
    assert SourceConflictOut.from_domain(
        SourceConflict(status="conflict", detail="changed")
    ).model_dump(mode="json") == {"status": "conflict", "detail": "changed"}
    assert SourceRefusedOut.from_domain(
        SourceRefused(status="refused", reason="unsafe-path", detail="unsafe")
    ).model_dump(mode="json") == {
        "status": "refused",
        "reason": "unsafe-path",
        "detail": "unsafe",
    }


def _assembly_presentation(
    position: int = 1,
    *,
    label: str | None = "Layer",
    presence: LayerPresence = "always",
    presence_label: str | None = None,
    visibility_control: PresentationControl | None = None,
) -> LayerPresentation:
    return LayerPresentation(
        position=position,
        label=label,
        presence=presence,
        presence_label=presence_label,
        visibility_control=visibility_control,
    )


def _assembly_unit() -> RoutedUnit:
    return RoutedUnit(
        candidate=Candidate(
            id="typescript-tool:demo",
            kind="typescript-tool",
            path="ext/demo.ts",
            selector="tool:demo",
            fragments=(),
        ),
        capability="cap",
        audience="both",
        role="tool-contract",
    )


def test_assembly_options_out_serves_full_scenarios_with_object_shaped_variables(
    snapshot: CatalogSnapshot,
) -> None:
    view = snapshot.get_assembly("plan-authoring")
    assert view is not None
    options = AssemblyOptionsOut.from_domain(view)
    dumped = options.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert list(dumped.keys()) == ["assembly", "scenarios"]
    assert dumped["assembly"] == "plan-authoring"
    assert [scenario["id"] for scenario in dumped["scenarios"]] == [
        scenario.id for scenario in view.scenarios
    ]
    first = dumped["scenarios"][0]
    assert list(first.keys()) == [
        "id",
        "label",
        "variables",
        "include_ambient",
        "include_tools",
    ]
    domain_first = view.scenarios[0]
    # A JSON object inserted from the domain's sorted pairs, not an array of pairs.
    assert isinstance(first["variables"], dict)
    assert first["variables"] == dict(domain_first.variables)
    assert list(first["variables"].keys()) == sorted(first["variables"].keys())
    assert first["label"] == domain_first.label
    assert first["include_ambient"] is domain_first.include_ambient
    assert first["include_tools"] is domain_first.include_tools


def test_assembly_render_out_pins_the_exact_nested_schema_and_discriminants() -> None:
    unit = _assembly_unit()
    fragment = Fragment(id="description", label="Description", selector="tool:demo.description")
    scenario = Scenario(
        id="scenario",
        assembly="demo",
        label="Demo scenario",
        variables=(("marker", "[X]"), ("provider", "github")),
        include_ambient=True,
        include_tools=True,
    )
    rendered = RenderedAssembly(
        assembly=Assembly(
            id="demo",
            layers=(
                AssemblyLayer(unit=None, boundary="pi-system", label="Pi", optional=False),
                AssemblyLayer(unit=unit.candidate.id, boundary=None, label="Tool", optional=True),
                AssemblyLayer(
                    unit=unit.candidate.id, boundary=None, label="Broken", optional=False
                ),
            ),
        ),
        scenario=scenario,
        presentation=ResolvedPresentation(include_ambient=True, include_tools=False),
        layers=(
            RenderedBoundaryLayer(
                presentation=_assembly_presentation(1, label="Pi"),
                boundary="pi-system",
                owner="pi",
            ),
            RenderedOwnedLayer(
                presentation=_assembly_presentation(
                    2,
                    label="Tool",
                    presence="varies",
                    presence_label="Presence varies by session shape or runtime.",
                    visibility_control="tools",
                ),
                unit=unit,
                content_kind="source-fragments",
                parts=(
                    RenderedContentPart(fragment=fragment, text='"first"'),
                    RenderedContentPart(fragment=None, text="whole text"),
                ),
            ),
            FailedAssemblyLayer(
                presentation=_assembly_presentation(3, label="Broken"),
                unit=unit,
                problems=(
                    AssemblyLayerProblem(
                        fragment=fragment,
                        reason="selector-not-found",
                        detail="A catalog fragment no longer resolves in the current source.",
                    ),
                    AssemblyLayerProblem(
                        fragment=None,
                        reason="invalid-source",
                        detail="The current source is not syntactically valid for its adapter.",
                    ),
                ),
            ),
        ),
    )

    out = AssemblyRenderOut.from_domain(rendered)
    dumped = out.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert list(dumped.keys()) == ["assembly", "scenario", "presentation", "layers"]
    assert dumped["assembly"] == "demo"
    assert list(dumped["scenario"].keys()) == [
        "id",
        "label",
        "variables",
        "include_ambient",
        "include_tools",
    ]
    assert dumped["scenario"]["variables"] == {"marker": "[X]", "provider": "github"}
    assert dumped["presentation"] == {"include_ambient": True, "include_tools": False}

    boundary, owned, failure = dumped["layers"]
    assert list(boundary.keys()) == ["type", "presentation", "boundary", "owner"]
    assert boundary["type"] == "boundary"
    assert boundary["boundary"] == "pi-system"
    assert boundary["owner"] == "pi"
    assert list(boundary["presentation"].keys()) == [
        "position",
        "label",
        "presence",
        "presence_label",
        "visibility_control",
    ]
    assert boundary["presentation"] == {
        "position": 1,
        "label": "Pi",
        "presence": "always",
        "presence_label": None,
        "visibility_control": None,
    }

    assert list(owned.keys()) == ["type", "presentation", "unit", "content_kind", "parts"]
    assert owned["type"] == "owned"
    assert owned["content_kind"] == "source-fragments"
    assert owned["unit"] == {
        "id": "typescript-tool:demo",
        "kind": "typescript-tool",
        "path": "ext/demo.ts",
    }
    assert owned["presentation"]["presence"] == "varies"
    assert owned["presentation"]["presence_label"] == (
        "Presence varies by session shape or runtime."
    )
    assert owned["presentation"]["visibility_control"] == "tools"
    assert [list(part.keys()) for part in owned["parts"]] == [
        ["fragment", "text"],
        ["fragment", "text"],
    ]
    # Fragment provenance is nullable and carries only id/label — never the selector.
    assert owned["parts"][0]["fragment"] == {"id": "description", "label": "Description"}
    assert owned["parts"][0]["text"] == '"first"'
    assert owned["parts"][1]["fragment"] is None

    assert list(failure.keys()) == ["type", "presentation", "unit", "problems"]
    assert failure["type"] == "failure"
    assert [list(problem.keys()) for problem in failure["problems"]] == [
        ["fragment", "reason", "detail"],
        ["fragment", "reason", "detail"],
    ]
    assert failure["problems"][0] == {
        "fragment": {"id": "description", "label": "Description"},
        "reason": "selector-not-found",
        "detail": "A catalog fragment no longer resolves in the current source.",
    }
    assert failure["problems"][1]["fragment"] is None
    assert failure["problems"][1]["reason"] == "invalid-source"

    flattened = json.dumps(dumped)
    assert '"selector"' not in flattened  # no internal selector/range/resolution leaks
    assert '"source_range"' not in flattened
    assert '"resolution"' not in flattened
    assert "tool:demo" not in flattened.replace("typescript-tool:demo", "")


def test_assembly_render_out_from_real_render_is_json_serializable(
    snapshot: CatalogSnapshot,
) -> None:
    renderer = AssemblyRenderer(ROOT, TypeScriptSourceAdapter(ROOT))
    rendered = renderer.render(
        snapshot,
        assembly_id="learn",
        scenario_id="learn-landed",
        presentation=PresentationOverrides(include_ambient=None, include_tools=None),
        workspace_buffers=(),
    )
    dumped = AssemblyRenderOut.from_domain(rendered).model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert dumped["assembly"] == "learn"
    assert dumped["scenario"]["id"] == "learn-landed"
    assert {layer["type"] for layer in dumped["layers"]} <= {"owned", "boundary", "failure"}
    assert [layer["presentation"]["position"] for layer in dumped["layers"]] == list(
        range(1, len(dumped["layers"]) + 1)
    )
