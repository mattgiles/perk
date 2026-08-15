"""The Prose Review Workbench search semantics, pinned against the real catalog."""

from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_review.catalog import CapabilityNode, CatalogSnapshot
from perk_dev.prose_review.search import (
    SearchEntry,
    SearchHit,
    build_search_index,
    search,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def snapshot() -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(build_catalog(ROOT))


@pytest.fixture(scope="module")
def index(snapshot: CatalogSnapshot) -> tuple[SearchEntry, ...]:
    return build_search_index(snapshot)


def _entries_of(index: tuple[SearchEntry, ...], kind: str) -> list[SearchEntry]:
    return [entry for entry in index if entry.kind == kind]


def test_index_kind_order_is_fixed(index: tuple[SearchEntry, ...]) -> None:
    kind_order = ["capability", "session-shape", "unit", "fragment", "concern"]
    seen = [entry.kind for entry in index]
    assert sorted(seen, key=kind_order.index) == seen
    assert set(seen) == set(kind_order)


def test_within_kind_order_matches_the_snapshot(
    snapshot: CatalogSnapshot, index: tuple[SearchEntry, ...]
) -> None:
    def tree_ids(nodes: tuple[CapabilityNode, ...]) -> list[str]:
        ids: list[str] = []
        for node in nodes:
            ids.append(node.capability.id)
            ids.extend(tree_ids(node.children))
        return ids

    assert [e.entity_id for e in _entries_of(index, "capability")] == tree_ids(
        snapshot.capability_tree
    )
    assert [e.entity_id for e in _entries_of(index, "session-shape")] == [
        shape.id for shape in snapshot.session_shapes
    ]
    assert [e.entity_id for e in _entries_of(index, "unit")] == [
        unit.candidate.id for unit in snapshot.units
    ]
    assert [e.entity_id for e in _entries_of(index, "fragment")] == [
        routed.fragment.id for routed in snapshot.fragments
    ]
    assert [e.entity_id for e in _entries_of(index, "concern")] == [
        view.concern.id for view in snapshot.concerns
    ]


def _unit_hits(hits: tuple[SearchHit, ...], entity_id: str) -> list[SearchHit]:
    return [hit for hit in hits if hit.entry.entity_id == entity_id]


def test_tool_query_matches_unit_id_and_tool_name(index: tuple[SearchEntry, ...]) -> None:
    results = search(index, "plan_review")
    hits = _unit_hits(results.hits, "typescript-tool:plan_review")
    assert len(hits) == 1
    assert "unit-id" in hits[0].matched
    assert "tool-name" in hits[0].matched


def test_path_query_matches_source_path(index: tuple[SearchEntry, ...]) -> None:
    results = search(index, "factories/planReview.ts")
    hits = _unit_hits(results.hits, "typescript-tool:plan_review")
    assert len(hits) == 1
    assert hits[0].matched == ("source-path",)


def test_matching_is_case_insensitive(index: tuple[SearchEntry, ...]) -> None:
    lower = search(index, "plan_review")
    upper = search(index, "PLAN_REVIEW")
    assert upper.total == lower.total
    assert [hit.entry.entity_id for hit in upper.hits] == [
        hit.entry.entity_id for hit in lower.hits
    ]
    assert upper.total > 0


def test_every_entry_kind_is_reachable_by_a_real_query(
    snapshot: CatalogSnapshot, index: tuple[SearchEntry, ...]
) -> None:
    samples = {
        "capability": snapshot.capability_tree[0].capability.label,
        "session-shape": snapshot.session_shapes[0].label,
        "unit": snapshot.units[0].candidate.id,
        "fragment": snapshot.fragments[0].fragment.label,
        "concern": snapshot.concerns[0].concern.label,
    }
    for kind, query in samples.items():
        results = search(index, query)
        assert any(hit.entry.kind == kind for hit in results.hits), (kind, query)


def test_kind_filter_returns_only_unit_backed_entries_of_that_kind(
    index: tuple[SearchEntry, ...],
) -> None:
    results = search(index, "", kind="typescript-tool")
    assert results.total > 0
    for hit in results.hits:
        assert hit.entry.kind in ("unit", "fragment")
        assert hit.entry.unit is not None
        assert hit.entry.unit.candidate.kind == "typescript-tool"


def test_active_filter_excludes_capability_shape_and_concern_entries(
    snapshot: CatalogSnapshot, index: tuple[SearchEntry, ...]
) -> None:
    # These queries match a capability, shape, and concern label without a filter...
    capability_label = snapshot.capability_tree[0].capability.label
    unfiltered = search(index, capability_label)
    assert any(hit.entry.kind == "capability" for hit in unfiltered.hits)
    # ...but any active filter restricts the corpus to unit/fragment entries.
    filtered = search(index, capability_label, role="tool-contract")
    assert all(hit.entry.kind in ("unit", "fragment") for hit in filtered.hits)


def test_audience_filter_is_exact_authored_value(
    snapshot: CatalogSnapshot, index: tuple[SearchEntry, ...]
) -> None:
    both_unit = next(unit for unit in snapshot.units if unit.audience == "both")
    shipped = search(index, both_unit.candidate.id, audience="shipped")
    assert not _unit_hits(shipped.hits, both_unit.candidate.id)
    both = search(index, both_unit.candidate.id, audience="both")
    assert _unit_hits(both.hits, both_unit.candidate.id)


def test_empty_query_matches_everything_capped_at_100(index: tuple[SearchEntry, ...]) -> None:
    results = search(index, "   ")
    assert results.total == len(index)
    assert len(results.hits) == 100
    assert all(hit.matched == () for hit in results.hits)
    assert [hit.entry for hit in results.hits] == list(index[:100])


def test_every_index_entry_carries_a_non_empty_breadcrumb(
    index: tuple[SearchEntry, ...],
) -> None:
    for entry in index:
        assert entry.breadcrumb, entry.entity_id
