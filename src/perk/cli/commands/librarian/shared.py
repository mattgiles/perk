"""Shared pieces of the ``perk librarian`` workers: the entry envelope, the in-command option
parsers (typed Click options would break the ``--json`` refusal contract), and the failure
mapping."""

import re
import shlex
import urllib.parse
from pathlib import Path

import click

from perk.boundary import OutputModel
from perk.cli.emit import fail
from perk.library import EntryView, Evidence, Kind, LibraryError, Status

_STALE_AFTER_RE = re.compile(r"([1-9][0-9]*)([smhd])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3_600, "d": 86_400}


class EntryOut(OutputModel):
    """One catalogued entry in a ``--json`` envelope (order load-bearing; ``path`` absolute)."""

    kind: Kind
    slug: str
    source: str
    path: str
    present: bool
    ref: str | None
    added_at: str
    checked_at: str | None
    checked_age_seconds: int | None
    stale_after: int
    evidence: Evidence
    drifted: bool
    status: Status

    @classmethod
    def from_view(cls, view: EntryView) -> "EntryOut":
        entry = view.entry
        return cls(
            kind=entry.kind,
            slug=entry.slug,
            source=entry.source,
            path=str(view.absolute_path),
            present=view.present,
            ref=entry.ref,
            added_at=entry.added_at,
            checked_at=entry.checked_at,
            checked_age_seconds=view.checked_age_seconds,
            stale_after=entry.stale_after,
            evidence=entry.evidence,
            drifted=entry.drifted,
            status=view.status,
        )


def parse_stale_after(text: str) -> int:
    """``<int>[smhd]`` → seconds; else ``invalid_stale_after``."""
    match = _STALE_AFTER_RE.fullmatch(text)
    if match is None:
        raise LibraryError(
            "invalid_stale_after",
            f"invalid --stale-after {text!r}: use a positive integer with a unit s, m, h or d "
            "(e.g. 7d, 24h)",
        )
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def validate_source_url(url: str) -> str:
    """An absolute ``http(s)`` URL with a host; else ``invalid_source``."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as exc:  # e.g. an unmatched IPv6 bracket
        raise LibraryError("invalid_source", f"invalid --source {url!r}: {exc}") from exc
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise LibraryError(
            "invalid_source", f"invalid --source {url!r}: use an absolute http(s) URL"
        )
    return url


def format_duration(seconds: int) -> str:
    """The largest unit that divides ``seconds`` exactly (``14d``, ``24h``, ``90m``, ``45s``)."""
    for unit, size in (("d", 86_400), ("h", 3_600), ("m", 60)):
        if seconds and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def fail_library_error(ctx: click.Context, exc: LibraryError, *, as_json: bool) -> None:
    fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))


def adopt_hint(path: Path) -> str:
    """The copyable command that catalogs an uncatalogued directory."""
    return f"perk librarian record --adopt {shlex.quote(str(path))} --kind docs --source <url>"
