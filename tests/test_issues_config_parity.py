"""Cross-plane parity for the `[issues]` routing keys (contracts §8.23).

The TS save-destination fence reads `[issues] backend`/`team` through the extension's TOML
subset reader (`extension/substrate/config.ts::resolveIssueRouting`); the Python save resolves
the same two keys through `tomllib` behind the ``StrippedStr`` boundary. `shared/fixtures/
issues-table.json` pairs TOML documents with the subset reader's reading (`expected`), whether
the reader can vouch for it (`provable`) and — when the planes diverge — `tomllib`'s reading.
The invariant pinned here is the fence's safety property: **whenever tomllib reads a different
destination than the subset reader, the case is unproven**, so the fence widens to the whole
document instead of trusting keys the authoritative parser may not share.
"""

import json
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "shared" / "fixtures" / "issues-table.json"


def _cases() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _issues_key(document: dict, key: str) -> str | None:
    """The fixture's extraction rule: the `[issues]` table's string value through the
    ``StrippedStr`` boundary (stripped, blank → ``None``), else ``None``."""
    table = document.get("issues")
    if not isinstance(table, dict):
        return None
    value = table.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _tomllib_reading(case: dict) -> dict[str, str | None]:
    document = tomllib.loads(case["toml"])
    return {"backend": _issues_key(document, "backend"), "team": _issues_key(document, "team")}


def test_fixture_case_names_are_unique() -> None:
    names = [case["name"] for case in _cases()]
    assert len(set(names)) == len(names)


def test_fixture_covers_every_divergent_spelling() -> None:
    """The spellings the subset reader cannot see must stay on record as unproven cases."""
    names = " | ".join(case["name"] for case in _cases())
    for needle in ("dotted keys", "inline table", "quoted header", "trailing comment", "escape"):
        assert needle in names, f"a case for {needle!r} exists"


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_tomllib_reads_the_recorded_issues_destination(case: dict) -> None:
    assert _tomllib_reading(case) == case.get("tomllib", case["expected"])


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_a_divergent_reading_is_never_proven(case: dict) -> None:
    """The fence trusts the subset reader's keys only where tomllib provably agrees."""
    assert isinstance(case["provable"], bool)
    if _tomllib_reading(case) != case["expected"]:
        assert case["provable"] is False, "tomllib disagrees, so the fence must widen"
    if "tomllib" in case:
        assert case["tomllib"] != case["expected"], "`tomllib` is recorded only on divergence"
        assert case["provable"] is False
