"""The Prose Review Workbench serialization edge: snapshot → CatalogSummaryOut."""

import json
from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.dto import CatalogSummaryOut

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


def test_capabilities_are_the_fixed_order_top_level_labels(summary: CatalogSummaryOut) -> None:
    assert [capability.label for capability in summary.capabilities] == [
        "Foundation",
        "Intent",
        "Planning",
        "Delivery",
        "Review",
        "Knowledge",
        "Extension & utilities",
    ]
    assert all(capability.id for capability in summary.capabilities)


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
