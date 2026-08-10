"""Vintage-reckoning + applicability-gate tests (perk_dev.audit.vintage).

Everything drives the pure/injectable seams — synthetic release histories and
timestamps, never the real CHANGELOG or home dir. The reckoning matrix pins the
conservative tie-breaks (min-of-stamps, strict-before on release day, pre-history)
and the tri-state applicability arms.
"""

import datetime
from pathlib import Path

from perk_dev.audit.vintage import (
    APPLICABILITY,
    VINTAGE_BASES,
    Release,
    ReleaseHistory,
    SessionVintage,
    applicability,
    load_release_history,
    parse_version,
    reckon_vintage,
)
from perk_dev.changelog import release_history

# ------------------------------------------------------------------ release history


def test_release_history_parses_headers_in_file_order():
    text = (
        "# Changelog\n\n## [Unreleased]\n\n- x\n\n"
        "## [2.0.0] - 2026-07-10\n\n- y\n\n"
        "## [1.1.0] - 2026-07-04\n\n- z\n"
    )
    assert release_history(text) == (("2.0.0", "2026-07-10"), ("1.1.0", "2026-07-04"))


def test_release_history_none_and_malformed_skipped():
    assert release_history("# Changelog\n\n## [Unreleased]\n") == ()
    malformed = "## [2.0] - 2026-07-10\n## [2.0.0] - July 10\n## 2.0.0 - 2026-07-10\n"
    assert release_history(malformed) == ()


def test_load_release_history_missing_file_is_empty(tmp_path: Path):
    assert load_release_history(tmp_path) == ReleaseHistory(releases=())


def test_load_release_history_sorts_ascending_and_drops_undateable(tmp_path: Path):
    (tmp_path / "CHANGELOG.md").write_text(
        "## [2.0.0] - 2026-07-10\n## [9.9.9] - 2026-13-45\n## [1.1.0] - 2026-07-04\n",
        encoding="utf-8",
    )
    history = load_release_history(tmp_path)
    assert history == ReleaseHistory(
        releases=(
            Release(version="1.1.0", date=datetime.date(2026, 7, 4)),
            Release(version="2.0.0", date=datetime.date(2026, 7, 10)),
        )
    )


# ------------------------------------------------------------------- parse_version


def test_parse_version_strict():
    assert parse_version("2.10.3") == (2, 10, 3)
    assert parse_version("2.3") is None
    assert parse_version("v2.3.0") is None
    assert parse_version("2.3.0-rc1") is None


def test_parse_version_oversized_component_is_invalid_not_a_crash():
    # CPython caps int() at ~4300 digits; a crafted/corrupt stamp beyond it must be
    # an invalid stamp, never a raise that aborts the census.
    assert parse_version("1." + "9" * 5000 + ".0") is None


# ------------------------------------------------------------------ reckon_vintage


HISTORY = ReleaseHistory(
    releases=(
        Release(version="1.0.0", date=datetime.date(2026, 6, 24)),
        Release(version="1.1.0", date=datetime.date(2026, 7, 4)),
        Release(version="2.0.0", date=datetime.date(2026, 7, 10)),
    )
)


def _reckon(
    *,
    perk_versions: tuple[str, ...] = (),
    timestamp: str | None = None,
    history: ReleaseHistory = HISTORY,
) -> SessionVintage:
    return reckon_vintage(perk_versions=perk_versions, timestamp=timestamp, history=history)


def test_stamp_beats_timestamp():
    vintage = _reckon(perk_versions=("2.0.0",), timestamp="2026-06-25T00:00:00Z")
    assert vintage == SessionVintage(version="2.0.0", basis="stamp")


def test_multiple_stamps_take_the_minimum():
    # Forks/branches in one file: conservative = the minimum version (tuple compare,
    # so 1.9.0 < 1.10.0 despite the string order).
    vintage = _reckon(perk_versions=("1.10.0", "1.9.0", "2.0.0"))
    assert vintage == SessionVintage(version="1.9.0", basis="stamp")


def test_invalid_stamp_ignored_valid_one_wins():
    vintage = _reckon(perk_versions=("bogus", "1.1.0"))
    assert vintage == SessionVintage(version="1.1.0", basis="stamp")


def test_all_invalid_stamps_fall_through_to_timestamp():
    vintage = _reckon(perk_versions=("bogus", "v1.1.0"), timestamp="2026-07-06T12:00:00Z")
    assert vintage == SessionVintage(version="1.1.0", basis="timestamp")


def test_timestamp_z_suffix_estimates_latest_qualifying_release():
    # July 6 is more than one day after 1.1.0's July 4 header — 1.1.0 qualifies.
    vintage = _reckon(timestamp="2026-07-06T03:38:32.430Z")
    assert vintage == SessionVintage(version="1.1.0", basis="timestamp")


def test_naive_timestamp_assumed_utc():
    vintage = _reckon(timestamp="2026-07-06T03:38:32")
    assert vintage == SessionVintage(version="1.1.0", basis="timestamp")


def test_aware_timestamp_converted_to_utc_date():
    # 01:30+05:00 on July 6 is July 5 20:30 UTC → the UTC date is the 5th, only one
    # day after 1.1.0's header → the margin drops the estimate to 1.0.0. (Mishandled
    # as naive, the date would be the 6th and the estimate 1.1.0.)
    vintage = _reckon(timestamp="2026-07-06T01:30:00+05:00")
    assert vintage == SessionVintage(version="1.0.0", basis="timestamp")


def test_extreme_aware_timestamp_degrades_to_unknown():
    # Year 1 with a positive offset underflows astimezone() — scanned content must
    # degrade to unknown, never crash the census.
    vintage = _reckon(timestamp="0001-01-01T00:00:00+05:00")
    assert vintage == SessionVintage(version=None, basis="unknown")


def test_release_day_and_day_after_sessions_take_the_previous_release():
    # The one-day safety margin: release headers are the maintainer's LOCAL day while
    # session dates are UTC, so a release stamped on day D can occur as late as UTC
    # day D+1 — both D and D+1 sessions conservatively estimate the previous release.
    for timestamp in ("2026-07-10T23:59:59Z", "2026-07-11T23:59:59Z"):
        vintage = _reckon(timestamp=timestamp)
        assert vintage == SessionVintage(version="1.1.0", basis="timestamp")
    vintage = _reckon(timestamp="2026-07-12T00:00:00Z")
    assert vintage == SessionVintage(version="2.0.0", basis="timestamp")


def test_pre_history_timestamp_is_none_version_timestamp_basis():
    vintage = _reckon(timestamp="2026-06-01T00:00:00Z")
    assert vintage == SessionVintage(version=None, basis="timestamp")


def test_unparseable_timestamp_is_unknown():
    vintage = _reckon(timestamp="yesterday-ish")
    assert vintage == SessionVintage(version=None, basis="unknown")


def test_no_signals_is_unknown():
    vintage = _reckon()
    assert vintage == SessionVintage(version=None, basis="unknown")


def test_empty_history_with_timestamp_is_unknown():
    vintage = _reckon(timestamp="2026-07-05T00:00:00Z", history=ReleaseHistory(releases=()))
    assert vintage == SessionVintage(version=None, basis="unknown")


def test_empty_history_stamp_still_wins():
    vintage = _reckon(perk_versions=("1.1.0",), history=ReleaseHistory(releases=()))
    assert vintage == SessionVintage(version="1.1.0", basis="stamp")


def test_basis_vocabulary_is_pinned():
    assert VINTAGE_BASES == ("stamp", "timestamp", "unknown")


# ------------------------------------------------------------------- applicability


def test_applicable_at_and_above_floor():
    assert applicability("1.1.0", SessionVintage(version="1.1.0", basis="stamp")) == "applicable"
    assert (
        applicability("1.1.0", SessionVintage(version="2.0.0", basis="timestamp")) == "applicable"
    )


def test_not_applicable_below_floor():
    assert (
        applicability("2.0.0", SessionVintage(version="1.1.0", basis="stamp")) == "not-applicable"
    )


def test_pre_history_not_applicable_to_everything():
    assert (
        applicability("1.0.0", SessionVintage(version=None, basis="timestamp")) == "not-applicable"
    )


def test_unknown_basis_is_vintage_unknown():
    assert applicability("1.0.0", SessionVintage(version=None, basis="unknown")) == (
        "vintage-unknown"
    )


def test_unparseable_floor_is_vintage_unknown():
    assert applicability("not-a-version", SessionVintage(version="2.0.0", basis="stamp")) == (
        "vintage-unknown"
    )


def test_applicability_vocabulary_is_pinned():
    assert APPLICABILITY == ("applicable", "not-applicable", "vintage-unknown")
