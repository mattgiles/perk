"""Per-session perk-version reckoning + the expectation applicability gate.

Best-effort vintage estimation for recorded sessions: exact where a session carries a
``perk_version`` stamp in its ``perk:workflow-state`` data (the stamp key is the pinned
cross-node coordination point — the workflow-state writer stamps it at claim/mint; this
module is the read side), else estimated from the session-header timestamp against the
committed ``CHANGELOG.md`` release history.

The reckoning is **conservative everywhere** — the invariant is "never judge an old
session against an expectation that postdates it", so every ambiguity resolves
*downward*:

- Multiple distinct stamps in one file (forks/branches) → the **minimum** version.
- Timestamp basis: the estimated version is the latest release whose date is *strictly
  before* the session's UTC date (a release-day session may predate the release, so it
  takes the previous release).
- A parseable timestamp earlier than every known release → pre-history
  (``version=None`` — below every floor, so not-applicable to everything).

Accepted, documented coarseness: dev sessions between releases report the last
*released* version (pyproject bumps at release time), and UTC-session vs
local-release-date skew is ≤1 day — both err toward not-applicable, never toward a
false violation.

Unknown vintage (no stamp, no parseable timestamp, or an empty release history) is a
distinct tri-state arm — ``vintage-unknown`` — surfaced in the census accounting,
never silently gated.

Pure/injectable throughout (mirroring ``expectations.py``/``corpus.py``): every input
is an explicit parameter and nothing here raises on content.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path

from perk_dev import changelog
from perk_dev.audit.expectations import VERSION_PATTERN

# The vintage-basis vocabulary (strongest first: a stamp is exact, a timestamp is an
# estimate, unknown is the honest fallback).
VINTAGE_BASES: tuple[str, ...] = ("stamp", "timestamp", "unknown")
# The tri-state applicability vocabulary the census partitions exercising sessions by.
APPLICABILITY: tuple[str, ...] = ("applicable", "not-applicable", "vintage-unknown")


def parse_version(text: str) -> tuple[int, int, int] | None:
    """The ``(major, minor, patch)`` tuple of a strict ``X.Y.Z`` string, else ``None``."""
    if VERSION_PATTERN.fullmatch(text) is None:
        return None
    major, minor, patch = text.split(".")
    return (int(major), int(minor), int(patch))


@dataclass(frozen=True)
class Release:
    """One released perk version and its (local) release date."""

    version: str
    date: datetime.date


@dataclass(frozen=True)
class ReleaseHistory:
    """The known releases, sorted ascending by ``(date, version-tuple)``."""

    releases: tuple[Release, ...]


def load_release_history(root: Path) -> ReleaseHistory:
    """Parse ``root/CHANGELOG.md`` release headers into a sorted ``ReleaseHistory``.

    Never raises: a missing/unreadable file is an empty history, and any header whose
    version or date fails strict parsing is dropped. The census surfaces the release
    count, so an empty history is visible rather than silent.
    """
    try:
        text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ReleaseHistory(releases=())
    releases: list[Release] = []
    for version, date_text in changelog.release_history(text):
        if parse_version(version) is None:
            continue
        try:
            date = datetime.date.fromisoformat(date_text)
        except ValueError:
            continue
        releases.append(Release(version=version, date=date))
    releases.sort(key=lambda r: (r.date, parse_version(r.version) or (0, 0, 0)))
    return ReleaseHistory(releases=tuple(releases))


@dataclass(frozen=True)
class SessionVintage:
    """One session's reckoned perk version and how it was reckoned.

    ``basis="stamp"``: ``version`` is the minimum valid stamped version (exact).
    ``basis="timestamp"``: ``version`` is the estimated release, or ``None`` for a
    pre-history session (earlier than every known release).
    ``basis="unknown"``: ``version`` is ``None``.
    """

    version: str | None
    basis: str


def _parse_timestamp_utc_date(timestamp: str) -> datetime.date | None:
    """The UTC calendar date of an ISO-8601 timestamp, else ``None``.

    ``fromisoformat`` handles the ``Z`` suffix on 3.13. A naive timestamp is assumed
    UTC; an aware one is converted to UTC before taking the date.
    """
    try:
        parsed = datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(datetime.UTC).date()


def reckon_vintage(
    *,
    perk_versions: tuple[str, ...],
    timestamp: str | None,
    history: ReleaseHistory,
) -> SessionVintage:
    """Reckon one session's vintage: stamps win, then the timestamp estimate.

    Invalid-format stamps are ignored (all-invalid falls through to the timestamp
    basis). On the timestamp basis the estimate is the latest release *strictly
    before* the session's UTC date; a date before every release is pre-history
    (``version=None``). No stamp, no parseable timestamp, or an empty history →
    ``basis="unknown"``.
    """
    stamped = [(parsed, v) for v in perk_versions if (parsed := parse_version(v)) is not None]
    if stamped:
        return SessionVintage(version=min(stamped)[1], basis="stamp")

    if timestamp is None or not history.releases:
        return SessionVintage(version=None, basis="unknown")
    session_date = _parse_timestamp_utc_date(timestamp)
    if session_date is None:
        return SessionVintage(version=None, basis="unknown")
    estimated: str | None = None
    for release in history.releases:  # ascending — the last strictly-before wins
        if release.date < session_date:
            estimated = release.version
    return SessionVintage(version=estimated, basis="timestamp")


def applicability(vintage_floor: str, vintage: SessionVintage) -> str:
    """The tri-state gate: does ``vintage_floor`` apply to a session of this vintage?

    ``basis="unknown"`` → ``vintage-unknown``; an unparseable floor (defensive — the
    committed catalog validates it) → ``vintage-unknown``; pre-history → ``not-applicable``;
    else a tuple comparison ``version >= floor``.
    """
    if vintage.basis == "unknown":
        return "vintage-unknown"
    floor = parse_version(vintage_floor)
    if floor is None:
        return "vintage-unknown"
    if vintage.version is None:  # pre-history: below every floor
        return "not-applicable"
    version = parse_version(vintage.version)
    if version is None:  # defensive: reckon_vintage only emits parseable versions
        return "vintage-unknown"
    return "applicable" if version >= floor else "not-applicable"
