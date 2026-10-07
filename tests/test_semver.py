"""The bounded semver parser/comparator behind the host floor (contracts.md §8.76)."""

from itertools import pairwise

import pytest

from perk.substrate.semver import Semver, compare_semver, parse_semver, satisfies_floor


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.99.2", Semver(0, 99, 2)),
        ("1.0.0", Semver(1, 0, 0)),
        ("1.0.0-rc.1", Semver(1, 0, 0, ("rc", "1"))),
        ("1.0.0-beta+exp.sha.5114f85", Semver(1, 0, 0, ("beta",))),
        ("v22.19.0", Semver(22, 19, 0)),
        (" 1.0.0\n", Semver(1, 0, 0)),
        ("1.0.0+build.7", Semver(1, 0, 0)),
        ("1.0.0-0.3.7", Semver(1, 0, 0, ("0", "3", "7"))),
        ("1.0.0-x-y-z.--", Semver(1, 0, 0, ("x-y-z", "--"))),
    ],
)
def test_parse_accepts_semver(text: str, expected: Semver) -> None:
    assert parse_semver(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1.0",
        "1.0.0.0",
        "01.0.0",
        "1.00.0",
        "1.0.0-",
        "1.0.0-01",
        "1.0.0+",
        "latest",
        "pi 1.0.0",
        "vv1.0.0",
        "1.0.0 extra",
        "\u0661.\u0660.\u0660",  # non-ASCII digits
    ],
)
def test_parse_rejects_non_semver(text: str) -> None:
    assert parse_semver(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "9" * 4301 + ".0.0",  # past Python's int-conversion digit limit
        "1.0.0-" + "9" * 4301,  # a numeric prerelease identifier the comparator would convert
        "1.0.0-" + "a" * 251,  # 257 chars: grammatical, but longer than any version
    ],
)
def test_parse_rejects_oversized_input_without_raising(text: str) -> None:
    assert parse_semver(text) is None


def test_parse_accepts_a_version_at_the_length_cap() -> None:
    text = "1.0.0-" + "a" * 250  # exactly 256 chars
    assert parse_semver(text) == Semver(1, 0, 0, ("a" * 250,))


def test_str_renders_the_canonical_text_without_build_metadata() -> None:
    assert str(parse_semver("v1.0.0-rc.1+abc")) == "1.0.0-rc.1"
    assert str(parse_semver("22.19.0")) == "22.19.0"


def _v(text: str) -> Semver:
    parsed = parse_semver(text)
    assert parsed is not None, text
    return parsed


SEMVER_ORG_CHAIN = [
    "1.0.0-alpha",
    "1.0.0-alpha.1",
    "1.0.0-alpha.beta",
    "1.0.0-beta",
    "1.0.0-beta.2",
    "1.0.0-beta.11",
    "1.0.0-rc.1",
    "1.0.0",
]


def test_precedence_follows_the_semver_org_chain() -> None:
    for lower, higher in pairwise(SEMVER_ORG_CHAIN):
        assert compare_semver(_v(lower), _v(higher)) == -1, (lower, higher)
        assert compare_semver(_v(higher), _v(lower)) == 1, (higher, lower)


def test_precedence_is_numeric_not_lexical() -> None:
    assert compare_semver(_v("1.10.0"), _v("1.9.0")) == 1
    assert compare_semver(_v("0.99.2"), _v("1.0.0")) == -1
    assert compare_semver(_v("22.9.0"), _v("22.19.0")) == -1


def test_build_metadata_carries_no_precedence() -> None:
    assert compare_semver(_v("1.0.0+a"), _v("1.0.0+b")) == 0
    assert compare_semver(_v("1.0.0"), _v("1.0.0")) == 0


def test_satisfies_floor_is_a_minimum() -> None:
    floor = _v("1.0.0")
    assert satisfies_floor(_v("1.0.0"), floor)
    assert satisfies_floor(_v("1.0.3"), floor)
    assert satisfies_floor(_v("1.10.0"), floor)
    assert satisfies_floor(_v("2.0.0-alpha"), floor)
    assert not satisfies_floor(_v("1.0.0-rc.1"), floor)
    assert not satisfies_floor(_v("0.99.2"), floor)
