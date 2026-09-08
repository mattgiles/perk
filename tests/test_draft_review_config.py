"""Cross-plane evidence for the draft-review routing-config projection (contracts §8.23).

The TS plane fingerprints a small set of Perk TOML routing inputs (`[issues] backend/team`,
`[workflow] base`, `[linear] api_key`) as EXACT decoded strings, while the Python plane —
authoritative for the save — reads the same fields through its existing config readers, which
normalize (strip, blank → ``None``) and validate. The shared fixture
`shared/fixtures/draft-review-config.json` carries both expectations per TOML document; this
suite exercises the real Python readers against it (never a competing resolver), so the two
planes' readings of one document stay reconciled where they legitimately differ.
"""

import base64
import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from perk.substrate import paths
from perk.substrate.config import (
    ConfigError,
    load_committed_issues_backend,
    load_committed_issues_team,
    load_config,
    load_local_linear_api_key,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "shared" / "fixtures" / "draft-review-config.json"
FIELDS = ("issues.backend", "issues.team", "workflow.base", "linear.api_key")
RAISES = {
    "ConfigError": ConfigError,
    "TOMLDecodeError": tomllib.TOMLDecodeError,
    "UnicodeDecodeError": UnicodeDecodeError,
}


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _bytes(case: dict) -> bytes | None:
    if "bytes_base64" in case:
        return base64.b64decode(case["bytes_base64"])
    toml = case.get("toml")
    return None if toml is None else toml.encode("utf-8")


def _readers(root: Path) -> dict[str, Callable[[], object]]:
    # The four existing readers, keyed by the fixture's field names. Committed readers anchor to
    # the main checkout (falling back to the given root outside a git repo — tmp_path here).
    return {
        "issues.backend": lambda: load_committed_issues_backend(root),
        "issues.team": lambda: load_committed_issues_team(root),
        "workflow.base": lambda: load_config(root).workflow_base,
        "linear.api_key": lambda: load_local_linear_api_key(root),
    }


def _expectation(case: dict, field: str) -> str | None | type[Exception]:
    """The fixture's Python expectation: a ``str``/``None`` value, or the exception class raised."""
    overrides = case.get("python", {})
    values = case.get("values", {})
    if field in overrides:
        expected = overrides[field]
    elif field in values:
        expected = values[field]
    else:
        pytest.fail(f"fixture case {case['name']!r} carries no Python expectation for {field}")
    if isinstance(expected, dict):
        raises = expected["raises"]
        assert isinstance(raises, str), case["name"]
        return RAISES[raises]
    assert expected is None or isinstance(expected, str), case["name"]
    return expected


def test_fixture_shape_matches_the_ts_consumer():
    doc = _fixture()
    assert doc["fields"] == list(FIELDS)
    names = [case["name"] for case in doc["cases"]]
    assert len(names) == len(set(names))
    assert doc["fake_credential"].startswith("lin_api_FAKE")
    for case in doc["cases"]:
        assert ("toml" in case) != ("bytes_base64" in case), case["name"]
        refuse = case.get("refuse", {})
        if "*" in refuse:
            # A whole-document refusal must still spell out every Python reader's behavior.
            assert set(case["python"]) == set(FIELDS), case["name"]


@pytest.mark.parametrize("case", _fixture()["cases"], ids=lambda case: case["name"])
def test_python_readers_agree_with_fixture(case: dict, tmp_path: Path):
    payload = _bytes(case)
    if payload is not None:
        # The same document serves both files so each reader (committed-only vs local-only)
        # observes it; the readers themselves decide which file they consult.
        for target in (paths.config_file(tmp_path), paths.local_config_file(tmp_path)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    for field, read in _readers(tmp_path).items():
        expected = _expectation(case, field)
        if isinstance(expected, type):
            with pytest.raises(expected):
                read()
        else:
            assert read() == expected, f"{case['name']}: {field}"


def test_python_normalizes_where_ts_keeps_exact_bytes():
    # The documented divergence: TS binds `" linear "` / `""` / `"  "` exactly (so a change to
    # any of them is a conservative routing change), while Python strips and blanks → None.
    doc = _fixture()
    case = next(c for c in doc["cases"] if c["name"] == "whitespace-and-empty-strings-preserved")
    assert case["values"] == {
        "issues.backend": " linear ",
        "issues.team": "",
        "workflow.base": "  ",
        "linear.api_key": "",
    }
    assert case["python"] == {
        "issues.backend": "linear",
        "issues.team": None,
        "workflow.base": None,
        "linear.api_key": None,
    }


def test_toml_1_1_syntax_is_a_save_time_cli_failure_not_routing_drift(tmp_path: Path):
    # The dialect boundary (contracts §8.23): the TS fingerprint's vendored parser accepts TOML 1.1
    # syntax (a trailing inline-table comma, a `\x` escape) that Python 3.13's `tomllib` rejects.
    # Such an edit is NOT routing drift — the TS projection is unchanged (or decodes a value) — and
    # surfaces instead when the save CLI refuses the whole configuration file, so it can fail a
    # save but never misroute one. Both readings are pinned; a dialect move in either parser trips
    # this test or its TS twin.
    doc = _fixture()
    dialect = [c for c in doc["cases"] if c.get("dialect") == "toml-1.1"]
    assert [c["name"] for c in dialect] == [
        "toml-1.1-trailing-comma-in-unrelated-inline-table",
        "toml-1.1-hex-escape-in-selected-value",
    ]
    for case in dialect:
        assert "refuse" not in case, case["name"]
        for field in ("issues.backend", "issues.team", "workflow.base"):
            assert case["python"][field] == {"raises": "TOMLDecodeError"}, case["name"]
        # Python's reader rejects the WHOLE document (`load_config` is what every CLI command,
        # including the save, loads first) — not merely the offending field.
        target = paths.config_file(tmp_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(case["toml"], encoding="utf-8")
        with pytest.raises(tomllib.TOMLDecodeError):
            load_config(tmp_path)
    trailing_comma, hex_escape = dialect
    assert trailing_comma["equivalent_to"] == "basic-strings"
    assert "\\x67" in hex_escape["toml"] and hex_escape["values"]["issues.backend"] == "github"


def test_unrelated_config_is_invisible_to_both_planes(tmp_path: Path):
    # The incident shape: a `[compaction]` edit (plus other unselected tables) leaves every
    # routing reader's answer unchanged — the fixture's `values` for this case are the whole
    # projection, and the Python readers agree without touching the compaction table.
    doc = _fixture()
    case = next(c for c in doc["cases"] if c["name"] == "unrelated-tables-and-large-integers")
    assert "compaction" in case["toml"]
    assert case["values"] == {
        "issues.backend": "github",
        "issues.team": None,
        "workflow.base": None,
        "linear.api_key": None,
    }
    paths.config_file(tmp_path).parent.mkdir(parents=True)
    paths.config_file(tmp_path).write_text(case["toml"], encoding="utf-8")
    assert load_committed_issues_backend(tmp_path) == "github"
    paths.config_file(tmp_path).write_text(
        case["toml"].replace("reserve_tokens = 99999999999999999999", "reserve_tokens = 65536"),
        encoding="utf-8",
    )
    assert load_committed_issues_backend(tmp_path) == "github"
