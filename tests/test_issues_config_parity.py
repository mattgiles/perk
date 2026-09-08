"""Cross-plane parity for the `[issues]` routing keys (contracts §8.23).

The TS save-destination fence reads `[issues] backend`/`team` through the extension's TOML
subset reader (`extension/substrate/config.ts::resolveIssueDestination`); the Python save
resolves the same two keys through `tomllib`. `shared/fixtures/issues-table.json` pairs TOML
documents — every string spelling TOML allows for a scalar — with the values BOTH planes must
read, so a spelling the subset reader cannot see (which would silently fence the wrong
destination) fails here as well as in `config.test.ts`.
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
    """The fixture's extraction rule: the `[issues]` table's string value, else ``None``."""
    table = document.get("issues")
    if not isinstance(table, dict):
        return None
    value = table.get(key)
    return value if isinstance(value, str) else None


def test_fixture_case_names_are_unique() -> None:
    names = [case["name"] for case in _cases()]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_tomllib_reads_the_expected_issues_destination(case: dict) -> None:
    document = tomllib.loads(case["toml"])
    assert {
        "backend": _issues_key(document, "backend"),
        "team": _issues_key(document, "team"),
    } == case["expected"]
