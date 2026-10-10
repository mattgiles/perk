"""Host-floor loader + validator tests (the fourth parsed shared/ contract, contracts.md §8.76).

The real bundled `host-floor.yaml` must load + validate and carry the pinned floors (the same
literals `extension/substrate/hostFloor.test.ts` pins — the cross-plane drift alarm). Negative
fixtures use a GOOD constant + per-test single-line mutation (mirroring test_providers.py):
structural problems raise ``HostFloorError``; content problems are ``validate()`` findings.
"""

from pathlib import Path

import pytest

from perk.substrate.host_floor import (
    HostFloor,
    HostFloorError,
    load_host_floor,
    required_node_version,
    required_pi_version,
    validate,
)
from perk.substrate.registry import FindingSeverity
from perk.substrate.semver import Semver

GOOD = """\
schema_version: 1
pi:
  min_version: "1.0.0"
node:
  min_version: "22.19.0"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "host-floor.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _messages(tmp_path: Path, text: str) -> str:
    issues = validate(load_host_floor(_write(tmp_path, text)))
    assert all(i.severity is FindingSeverity.ERROR for i in issues), issues
    return " | ".join(i.message for i in issues)


# --- the real bundled file -------------------------------------------------------------------


def test_real_host_floor_loads_validates_and_pins_the_floors() -> None:
    floor = load_host_floor()
    assert validate(floor) == []
    assert floor.schema_version == 1
    assert floor.pi_min_version == "1.1.0"
    assert floor.node_min_version == "22.19.0"
    assert required_pi_version(floor) == Semver(1, 1, 0)
    assert required_node_version(floor) == Semver(22, 19, 0)


def test_good_fixture_is_valid(tmp_path: Path) -> None:
    assert _messages(tmp_path, GOOD) == ""


# --- structural failures ---------------------------------------------------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(HostFloorError, match="not found"):
        load_host_floor(tmp_path / "absent.yaml")


@pytest.mark.parametrize(
    "replacement",
    ["", "schema_version: null\n", "schema_version: 2\n", "schema_version: true\n"],
)
def test_bad_schema_version_raises(tmp_path: Path, replacement: str) -> None:
    text = GOOD.replace("schema_version: 1\n", replacement)
    with pytest.raises(HostFloorError, match="schema_version"):
        load_host_floor(_write(tmp_path, text))


def test_top_level_not_a_mapping_raises(tmp_path: Path) -> None:
    with pytest.raises(HostFloorError, match="mapping"):
        load_host_floor(_write(tmp_path, "- 1.0.0\n"))


def test_unparseable_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(HostFloorError, match="YAML"):
        load_host_floor(_write(tmp_path, GOOD.replace('"1.0.0"', '"1.0.0')))


def test_wrong_typed_present_field_raises(tmp_path: Path) -> None:
    # pydantic's lax mode does not coerce an int into a str field: a structural error.
    with pytest.raises(HostFloorError):
        load_host_floor(_write(tmp_path, GOOD.replace('min_version: "1.0.0"', "min_version: 1")))


# --- content findings ------------------------------------------------------------------------


def test_null_min_version_is_a_finding(tmp_path: Path) -> None:
    text = GOOD.replace('min_version: "1.0.0"', "min_version: null")
    assert "`pi.min_version` is missing" in _messages(tmp_path, text)


def test_missing_host_entry_is_a_finding(tmp_path: Path) -> None:
    text = GOOD.replace('node:\n  min_version: "22.19.0"\n', "")
    assert "`node.min_version` is missing" in _messages(tmp_path, text)


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ('"1.0.0-rc.1"', "plain release version"),
        ('"1.0.0+build.1"', "plain release version"),
        ('"v1.0.0"', "plain release version"),
        ('"not-a-version"', "is not a semver version"),
    ],
)
def test_non_release_floor_is_a_finding(tmp_path: Path, value: str, fragment: str) -> None:
    text = GOOD.replace('"1.0.0"', value)
    messages = _messages(tmp_path, text)
    assert "`pi.min_version`" in messages
    assert fragment in messages


# --- consumer accessors ----------------------------------------------------------------------


def test_required_pi_version_on_a_corrupt_floor_raises() -> None:
    corrupt = HostFloor(schema_version=1, pi_min_version="1.0.0-rc.1", node_min_version="")
    with pytest.raises(HostFloorError, match="reinstall perk"):
        required_pi_version(corrupt)
    with pytest.raises(HostFloorError, match="reinstall perk"):
        required_node_version(corrupt)
