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
    describe_node_lines,
    engines_node_range,
    load_host_floor,
    node_line_floor,
    required_node_version,
    required_pi_version,
    supported_node_lines,
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

GOOD_LINES = (
    GOOD
    + """\
  line_floors:
    - "24.1.0"
    - "26.2.0"
"""
)


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
    assert floor.pi_min_version == "1.4.0"
    assert floor.node_min_version == "22.23.4"
    assert floor.node_line_floors == ("24.22.1", "26.12.1")
    assert required_pi_version(floor) == Semver(1, 4, 0)
    assert required_node_version(floor) == Semver(22, 23, 4)
    assert supported_node_lines(floor) == (Semver(22, 23, 4), Semver(24, 22, 1), Semver(26, 12, 1))


def test_good_fixture_is_valid(tmp_path: Path) -> None:
    assert _messages(tmp_path, GOOD) == ""


def test_good_fixture_with_line_floors_is_valid(tmp_path: Path) -> None:
    floor = load_host_floor(_write(tmp_path, GOOD_LINES))
    assert validate(floor) == []
    assert floor.node_line_floors == ("24.1.0", "26.2.0")
    assert supported_node_lines(floor) == (Semver(22, 19, 0), Semver(24, 1, 0), Semver(26, 2, 0))


def test_absent_line_floors_is_the_single_line_table(tmp_path: Path) -> None:
    floor = load_host_floor(_write(tmp_path, GOOD))
    assert floor.node_line_floors == ()
    assert supported_node_lines(floor) == (Semver(22, 19, 0),)


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


@pytest.mark.parametrize(
    "line_floors",
    ['  line_floors: "24.1.0"\n', "  line_floors:\n    - 24\n"],
    ids=["a-string", "a-non-string-item"],
)
def test_wrong_typed_line_floors_raises(tmp_path: Path, line_floors: str) -> None:
    with pytest.raises(HostFloorError):
        load_host_floor(_write(tmp_path, GOOD + line_floors))


def test_pi_line_floors_is_ignored(tmp_path: Path) -> None:
    text = GOOD.replace('min_version: "1.0.0"\n', 'min_version: "1.0.0"\n  line_floors: 7\n')
    assert _messages(tmp_path, text) == ""


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


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ('"24.1.0-rc.1"', "plain release version"),
        ('"v24.1.0"', "plain release version"),
        ('"not-a-version"', "is not a semver version"),
        ('""', "is missing"),
    ],
)
def test_non_release_line_floor_is_a_finding(tmp_path: Path, value: str, fragment: str) -> None:
    messages = _messages(tmp_path, GOOD_LINES.replace('"26.2.0"', value))
    assert "`node.line_floors[1]`" in messages
    assert fragment in messages
    assert "`node.line_floors[0]`" not in messages


@pytest.mark.parametrize(
    ("entries", "offending"),
    [
        (["22.30.0"], [0]),
        (["20.19.0"], [0]),
        (["24.1.0", "24.2.0"], [0, 1]),
        (["24.1.0", "26.2.0", "26.3.0"], [1, 2]),
    ],
    ids=["same-major-as-min", "below-min", "duplicated-major", "duplicate-beside-a-good-line"],
)
def test_line_floor_not_a_distinct_line_above_min_is_a_finding(
    tmp_path: Path, entries: list[str], offending: list[int]
) -> None:
    text = GOOD + "  line_floors:\n" + "".join(f'    - "{entry}"\n' for entry in entries)
    issues = validate(load_host_floor(_write(tmp_path, text)))
    expected = [
        f"`node.line_floors[{index}]` '{entries[index]}' must name a release line "
        "above `node.min_version`'s and distinct from its siblings"
        for index in offending
    ]
    assert [issue.message for issue in issues] == expected


def test_line_findings_are_skipped_when_min_version_is_broken(tmp_path: Path) -> None:
    text = GOOD_LINES.replace('"22.19.0"', '"22.19.0-rc.1"').replace('"24.1.0"', '"20.1.0"')
    messages = _messages(tmp_path, text)
    assert "`node.min_version`" in messages
    assert "line_floors" not in messages


# --- consumer accessors ----------------------------------------------------------------------


def test_required_pi_version_on_a_corrupt_floor_raises() -> None:
    corrupt = HostFloor(schema_version=1, pi_min_version="1.0.0-rc.1", node_min_version="")
    with pytest.raises(HostFloorError, match="reinstall perk"):
        required_pi_version(corrupt)
    with pytest.raises(HostFloorError, match="reinstall perk"):
        required_node_version(corrupt)


@pytest.mark.parametrize(
    "corrupt",
    [
        HostFloor(schema_version=1, pi_min_version="1.0.0", node_min_version=""),
        HostFloor(
            schema_version=1,
            pi_min_version="1.0.0",
            node_min_version="22.19.0",
            node_line_floors=("24.1.0-rc.1",),
        ),
        HostFloor(
            schema_version=1,
            pi_min_version="1.0.0",
            node_min_version="22.19.0",
            node_line_floors=("24.1.0", "24.2.0"),
        ),
    ],
    ids=["missing-min", "non-release-line", "duplicated-line"],
)
def test_supported_node_lines_on_a_corrupt_floor_raises(corrupt: HostFloor) -> None:
    assert validate(corrupt) != []
    with pytest.raises(HostFloorError, match="reinstall perk"):
        supported_node_lines(corrupt)


LINES = (Semver(22, 23, 4), Semver(24, 22, 1), Semver(26, 12, 1))


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        (Semver(22, 0, 0), Semver(22, 23, 4)),
        (Semver(24, 30, 0), Semver(24, 22, 1)),
        (Semver(26, 3, 0), Semver(26, 12, 1)),
        (Semver(26, 13, 0, ("rc", "1")), Semver(26, 12, 1)),
        (Semver(20, 19, 0), None),
        (Semver(23, 11, 0), None),
        (Semver(25, 9, 0), None),
        (Semver(27, 0, 0, ("alpha", "0")), None),
    ],
)
def test_node_line_floor_picks_the_observed_major_line(
    observed: Semver, expected: Semver | None
) -> None:
    assert node_line_floor(LINES, observed) == expected


def test_describe_node_lines_renders_every_line() -> None:
    assert describe_node_lines(LINES) == "22.x >= 22.23.4, 24.x >= 24.22.1, 26.x >= 26.12.1"


def test_engines_node_range_renders_the_caret_union() -> None:
    assert engines_node_range(LINES) == "^22.23.4 || ^24.22.1 || ^26.12.1"
