"""Drift guard for source-derived fact tables in the operator reference.

Only marker-bounded Markdown tables are machine-owned. The surrounding prose remains free for
human editing while provider, objective-model, and JSON Schema inventories stay synchronized with
their executable sources.
"""

import re
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest
from _schemas import SCHEMAS

from perk.objective._models import NodeStatus, StructuredRoadmapNode
from perk.substrate.providers import load_providers

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "docs" / "user-docs" / "reference"


def _reference_facts_region(path: Path, key: str) -> str:
    """Return one validated reference-facts region and reject ambiguous marker structure."""
    text = path.read_text(encoding="utf-8")
    matches = list(
        re.finditer(
            r"<!-- perk:reference-facts:(?P<key>[a-z0-9-]+):(?P<edge>start|end) -->",
            text,
        )
    )
    by_key: dict[str, list[re.Match[str]]] = {}
    for match in matches:
        by_key.setdefault(match.group("key"), []).append(match)

    assert key in by_key, f"{path}: missing reference-facts marker pair for {key!r}"

    intervals: list[tuple[int, int, str]] = []
    for marker_key, marker_matches in by_key.items():
        starts = [match for match in marker_matches if match.group("edge") == "start"]
        ends = [match for match in marker_matches if match.group("edge") == "end"]
        assert len(starts) <= 1 and len(ends) <= 1, (
            f"{path}: duplicate reference-facts marker for {marker_key!r} "
            f"(starts={len(starts)}, ends={len(ends)})"
        )
        assert starts, f"{path}: closing reference-facts marker without opening for {marker_key!r}"
        assert ends, f"{path}: unclosed reference-facts marker for {marker_key!r}"
        assert starts[0].start() < ends[0].start(), (
            f"{path}: reversed reference-facts markers for {marker_key!r}"
        )
        intervals.append((starts[0].start(), ends[0].end(), marker_key))

    intervals.sort()
    for previous, current in pairwise(intervals):
        assert previous[1] <= current[0], (
            f"{path}: overlapping reference-facts marker pairs {previous[2]!r} and {current[2]!r}"
        )

    target_matches = by_key[key]
    start = next(match for match in target_matches if match.group("edge") == "start")
    end = next(match for match in target_matches if match.group("edge") == "end")
    return text[start.end() : end.start()]


def _table_rows(region: str, *, label: str) -> list[list[str]]:
    """Parse the single simple Markdown table inside a marker-bounded region."""
    table_lines = [line.strip() for line in region.splitlines() if line.strip().startswith("|")]
    assert len(table_lines) >= 3, f"{label}: expected a Markdown table with at least one data row"
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in table_lines]
    assert all(re.fullmatch(r":?-+:?", cell) for cell in rows[1]), (
        f"{label}: second table row is not a Markdown separator: {rows[1]}"
    )
    width = len(rows[0])
    assert all(len(row) == width for row in rows), f"{label}: inconsistent table row widths: {rows}"
    return rows[2:]


def _code_cell(cell: str, *, label: str) -> str:
    assert len(cell) >= 2 and cell.startswith("`") and cell.endswith("`"), (
        f"{label}: expected a backtick-delimited fact cell, got {cell!r}"
    )
    return cell[1:-1]


def _assert_ordered_equal[T](
    label: str, expected: tuple[T, ...], documented: tuple[T, ...]
) -> None:
    missing = [item for item in expected if item not in documented]
    unexpected = [item for item in documented if item not in expected]
    assert documented == expected, (
        f"{label} reference-facts drift: missing={missing!r}, unexpected={unexpected!r}, "
        f"expected_order={expected!r}, documented_order={documented!r}"
    )


def _assert_set_equal(label: str, expected: set[str], documented: list[str]) -> None:
    counts = Counter(documented)
    duplicates = sorted(item for item, count in counts.items() if count > 1)
    documented_set = set(documented)
    assert documented_set == expected and not duplicates, (
        f"{label} reference-facts drift: missing={sorted(expected - documented_set)!r}, "
        f"unexpected={sorted(documented_set - expected)!r}, duplicates={duplicates!r}"
    )


@pytest.mark.parametrize(
    ("content", "key", "message"),
    [
        pytest.param("no markers", "target", "missing", id="missing"),
        pytest.param(
            "\n".join(
                [
                    "<!-- perk:reference-facts:target:start -->",
                    "<!-- perk:reference-facts:target:start -->",
                    "<!-- perk:reference-facts:target:end -->",
                ]
            ),
            "target",
            "duplicate",
            id="duplicate",
        ),
        pytest.param(
            "\n".join(
                [
                    "<!-- perk:reference-facts:target:end -->",
                    "<!-- perk:reference-facts:target:start -->",
                ]
            ),
            "target",
            "reversed",
            id="reversed",
        ),
        pytest.param(
            "<!-- perk:reference-facts:target:start -->",
            "target",
            "unclosed",
            id="unclosed",
        ),
        pytest.param(
            "\n".join(
                [
                    "<!-- perk:reference-facts:first:start -->",
                    "<!-- perk:reference-facts:second:start -->",
                    "<!-- perk:reference-facts:first:end -->",
                    "<!-- perk:reference-facts:second:end -->",
                ]
            ),
            "first",
            "overlapping",
            id="overlapping",
        ),
    ],
)
def test_reference_facts_marker_parser_rejects_malformed_pairs(
    tmp_path: Path, content: str, key: str, message: str
) -> None:
    path = tmp_path / "reference.md"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(AssertionError, match=message):
        _reference_facts_region(path, key)


def test_documented_provider_ids_match_supported_set_order() -> None:
    path = REFERENCE_DIR / "providers-and-backends.md"
    rows = _table_rows(
        _reference_facts_region(path, "providers"),
        label="providers",
    )
    documented = tuple(_code_cell(row[0], label="providers") for row in rows)
    expected = tuple(
        provider.id
        for provider in load_providers(REPO_ROOT / "shared" / "providers.yaml").providers
    )
    _assert_ordered_equal("providers", expected, documented)


def test_documented_objective_fields_match_structured_node_model() -> None:
    path = REFERENCE_DIR / "objectives.md"
    rows = _table_rows(
        _reference_facts_region(path, "objective-fields"),
        label="objective fields",
    )
    documented = [_code_cell(row[0], label="objective fields") for row in rows]
    _assert_set_equal("objective fields", set(StructuredRoadmapNode.model_fields), documented)


def test_documented_objective_statuses_match_enum_order() -> None:
    path = REFERENCE_DIR / "objectives.md"
    rows = _table_rows(
        _reference_facts_region(path, "objective-statuses"),
        label="objective statuses",
    )
    documented = tuple(_code_cell(row[0], label="objective statuses") for row in rows)
    expected = tuple(status.value for status in NodeStatus)
    _assert_ordered_equal("objective statuses", expected, documented)


@pytest.mark.parametrize("category", ["contracts", "inputs", "outputs"])
def test_documented_schema_inventory_matches_registry(category: str) -> None:
    path = REFERENCE_DIR / "json-schemas.md"
    rows = _table_rows(
        _reference_facts_region(path, f"schemas-{category}"),
        label=f"schemas/{category}",
    )
    documented = tuple(
        (
            _code_cell(row[0], label=f"schemas/{category} path"),
            _code_cell(row[1], label=f"schemas/{category} model"),
            _code_cell(row[2], label=f"schemas/{category} mode"),
        )
        for row in rows
    )
    expected = tuple(
        (entry.path.split("/", 1)[1], entry.model.__name__, entry.mode)
        for entry in SCHEMAS
        if entry.path.startswith(f"{category}/")
    )
    _assert_ordered_equal(f"schemas/{category}", expected, documented)
