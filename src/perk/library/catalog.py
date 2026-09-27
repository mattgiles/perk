"""The ``catalog.json`` envelope: domain model, parse boundary, content pass, derived status.

The catalog is written only by the CLI, by atomic replace, under ``library_lock``; a malformed
catalog is a typed ``catalog_malformed`` refusal and no worker ever rewrites it (contracts.md
§8.75(b)). Both entry kinds are modeled from day one — ``docs`` mirrors and ``source``
checkouts — so every status (incl. ``pinned`` and ``unverifiable``) is derivable now.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.library.errors import LibraryError
from perk.library.layout import SLUG_RE, Kind, LibraryLayout, entry_path_shape
from perk.substrate import paths
from perk.substrate.fs import atomic_write_text

type Evidence = Literal["strong", "weak", "none"]
type Status = Literal["fresh", "stale", "drifted", "unverifiable", "pinned", "unknown"]
type Clock = Callable[[], datetime]

CATALOG_VERSION = 1
# Default freshness windows in seconds: docs 14 days, source 24 hours.
DEFAULT_STALE_AFTER: dict[str, int] = {"docs": 1_209_600, "source": 86_400}

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_CATALOG_SOURCE = f"{paths.LIBRARY_REL}/catalog.json"


@dataclass(frozen=True)
class PageMarker:
    """One upstream page's change markers (seeded from the mirror's inventory)."""

    url: str
    etag: str | None = None
    last_modified: str | None = None
    sitemap_lastmod: str | None = None


@dataclass(frozen=True)
class DocsUpstream:
    pages: tuple[PageMarker, ...] = ()
    fingerprint: str | None = None


@dataclass(frozen=True)
class SourceUpstream:
    branch: str | None = None
    head_sha: str | None = None


@dataclass(frozen=True)
class Entry:
    """One catalogued library entry. ``path`` is relative to the library root (POSIX)."""

    kind: Kind
    slug: str
    source: str
    path: str
    added_at: str
    stale_after: int
    upstream: DocsUpstream | SourceUpstream
    ref: str | None = None
    checked_at: str | None = None
    evidence: Evidence = "none"
    drifted: bool = False


@dataclass(frozen=True)
class Catalog:
    entries: tuple[Entry, ...] = ()

    def get(self, slug: str) -> Entry | None:
        return next((entry for entry in self.entries if entry.slug == slug), None)

    def owner_of(self, path: str) -> Entry | None:
        """The entry whose ``path`` equals the given library-relative path."""
        return next((entry for entry in self.entries if entry.path == path), None)

    def with_entry(self, entry: Entry) -> "Catalog":
        """Replace the entry with the same slug in place, else append."""
        if self.get(entry.slug) is None:
            return replace(self, entries=(*self.entries, entry))
        return replace(
            self,
            entries=tuple(
                entry if current.slug == entry.slug else current for current in self.entries
            ),
        )

    def without(self, slug: str) -> "Catalog":
        return replace(self, entries=tuple(entry for entry in self.entries if entry.slug != slug))


class PageMarkerModel(LenientParseModel):
    url: str
    etag: str | None = None
    last_modified: str | None = None
    sitemap_lastmod: str | None = None

    def to_domain(self) -> PageMarker:
        return PageMarker(
            url=self.url,
            etag=self.etag,
            last_modified=self.last_modified,
            sitemap_lastmod=self.sitemap_lastmod,
        )

    @classmethod
    def from_domain(cls, marker: PageMarker) -> "PageMarkerModel":
        return cls(
            url=marker.url,
            etag=marker.etag,
            last_modified=marker.last_modified,
            sitemap_lastmod=marker.sitemap_lastmod,
        )


class DocsUpstreamModel(LenientParseModel):
    kind: Literal["docs"]
    pages: tuple[PageMarkerModel, ...] = ()
    fingerprint: str | None = None

    def to_domain(self) -> DocsUpstream:
        return DocsUpstream(
            pages=tuple(page.to_domain() for page in self.pages), fingerprint=self.fingerprint
        )

    @classmethod
    def from_domain(cls, upstream: DocsUpstream) -> "DocsUpstreamModel":
        return cls(
            kind="docs",
            pages=tuple(PageMarkerModel.from_domain(page) for page in upstream.pages),
            fingerprint=upstream.fingerprint,
        )


class SourceUpstreamModel(LenientParseModel):
    kind: Literal["source"]
    branch: str | None = None
    head_sha: str | None = None

    def to_domain(self) -> SourceUpstream:
        return SourceUpstream(branch=self.branch, head_sha=self.head_sha)

    @classmethod
    def from_domain(cls, upstream: SourceUpstream) -> "SourceUpstreamModel":
        return cls(kind="source", branch=upstream.branch, head_sha=upstream.head_sha)


class EntryModel(LenientParseModel):
    """One catalog entry on disk (field order is the serialized key order)."""

    kind: Kind
    slug: str
    source: str
    path: str
    ref: str | None = None
    added_at: str
    checked_at: str | None = None
    upstream: Annotated[DocsUpstreamModel | SourceUpstreamModel, Field(discriminator="kind")]
    evidence: Evidence = "none"
    drifted: bool = False
    stale_after: int

    def to_domain(self) -> Entry:
        return Entry(
            kind=self.kind,
            slug=self.slug,
            source=self.source,
            path=self.path,
            added_at=self.added_at,
            stale_after=self.stale_after,
            upstream=self.upstream.to_domain(),
            ref=self.ref,
            checked_at=self.checked_at,
            evidence=self.evidence,
            drifted=self.drifted,
        )

    @classmethod
    def from_domain(cls, entry: Entry) -> "EntryModel":
        # The upstream discriminator comes from the domain variant's class, never from
        # `entry.kind` — a kind/upstream disagreement must stay visible to the content pass.
        upstream: DocsUpstreamModel | SourceUpstreamModel
        if isinstance(entry.upstream, DocsUpstream):
            upstream = DocsUpstreamModel.from_domain(entry.upstream)
        else:
            upstream = SourceUpstreamModel.from_domain(entry.upstream)
        return cls(
            kind=entry.kind,
            slug=entry.slug,
            source=entry.source,
            path=entry.path,
            ref=entry.ref,
            added_at=entry.added_at,
            checked_at=entry.checked_at,
            upstream=upstream,
            evidence=entry.evidence,
            drifted=entry.drifted,
            stale_after=entry.stale_after,
        )


class CatalogFileModel(LenientParseModel):
    version: int
    entries: tuple[EntryModel, ...] = ()

    def to_domain(self) -> Catalog:
        return Catalog(entries=tuple(entry.to_domain() for entry in self.entries))

    @classmethod
    def from_domain(cls, catalog: Catalog) -> "CatalogFileModel":
        return cls(
            version=CATALOG_VERSION,
            entries=tuple(EntryModel.from_domain(entry) for entry in catalog.entries),
        )


class _CatalogParseError(Exception):
    """The ``translate_validation_errors`` target, re-raised as ``catalog_malformed``."""


def _malformed(message: str) -> LibraryError:
    return LibraryError(
        "catalog_malformed",
        f"{message} — repair or remove {_CATALOG_SOURCE} by hand (perk librarian never rewrites "
        "a malformed catalog)",
    )


def load_catalog(layout: LibraryLayout) -> Catalog:
    """Parse and content-check ``catalog.json``; an absent file is the empty catalog."""
    path = layout.catalog_path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Catalog()
    except (OSError, UnicodeDecodeError) as exc:
        raise _malformed(f"{path} is unreadable ({exc})") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _malformed(f"{path} is not valid JSON ({exc})") from exc
    try:
        with translate_validation_errors(_CatalogParseError, source=_CATALOG_SOURCE):
            model = CatalogFileModel.model_validate(raw)
    except _CatalogParseError as exc:
        raise _malformed(str(exc)) from exc
    if model.version != CATALOG_VERSION:
        raise _malformed(
            f"{path} has version {model.version}; this perk reads version {CATALOG_VERSION}"
        )
    catalog = model.to_domain()
    _content_pass(catalog)
    return catalog


def _content_pass(catalog: Catalog) -> None:
    seen_slugs: set[str] = set()
    seen_paths: dict[str, str] = {}
    for entry in catalog.entries:
        label = f"entry {entry.slug!r}"
        if SLUG_RE.fullmatch(entry.slug) is None or ".." in entry.slug:
            raise _malformed(f"{label}: the slug is outside the slug grammar")
        if entry.slug in seen_slugs:
            raise _malformed(f"{label}: duplicate slug")
        seen_slugs.add(entry.slug)
        upstream_kind = "docs" if isinstance(entry.upstream, DocsUpstream) else "source"
        if entry.kind != upstream_kind:
            raise _malformed(
                f"{label}: kind {entry.kind!r} disagrees with its {upstream_kind!r} upstream"
            )
        if not entry_path_shape(entry.kind, entry.path):
            shape = (
                "documentation/<slug>"
                if entry.kind == "docs"
                else "source-code/<host>/<org>/<repo>"
            )
            raise _malformed(f"{label}: path {entry.path!r} is not of the form {shape}")
        if entry.path in seen_paths:
            raise _malformed(f"{label}: path {entry.path!r} is also {seen_paths[entry.path]!r}'s")
        for other_path, other_slug in seen_paths.items():
            if other_path.startswith(f"{entry.path}/") or entry.path.startswith(f"{other_path}/"):
                raise _malformed(
                    f"{label}: path {entry.path!r} overlaps {other_slug!r}'s {other_path!r}"
                )
        seen_paths[entry.path] = entry.slug
        for field_name, value in (("added_at", entry.added_at), ("checked_at", entry.checked_at)):
            if value is None:
                continue
            try:
                parse_ts(value)
            except ValueError as exc:
                raise _malformed(f"{label}: malformed {field_name} {value!r}") from exc


def render_catalog(catalog: Catalog) -> str:
    return (
        json.dumps(CatalogFileModel.from_domain(catalog).model_dump(mode="json"), indent=2) + "\n"
    )


def write_catalog(layout: LibraryLayout, catalog: Catalog) -> None:
    """Atomically replace ``catalog.json``.

    Precondition: the caller holds ``library_lock`` (the ops module is the only production
    caller) and has passed the cache-only preflight.
    """
    layout.root.mkdir(parents=True, exist_ok=True)
    atomic_write_text(layout.catalog_path, render_catalog(catalog))


def derive_status(entry: Entry, *, now: datetime) -> Status:
    """The entry's derived status — it names the next action.

    Precedence: ``pinned`` (a source entry with a ``ref``) > ``drifted`` > ``unknown`` (never
    checked) > ``stale`` (``now - checked_at ≥ stale_after``) > ``unverifiable`` (checked with no
    evidence) > ``fresh``.
    """
    if entry.kind == "source" and entry.ref is not None:
        return "pinned"
    if entry.drifted:
        return "drifted"
    if entry.checked_at is None:
        return "unknown"
    if (now - parse_ts(entry.checked_at)).total_seconds() >= entry.stale_after:
        return "stale"
    if entry.evidence == "none":
        return "unverifiable"
    return "fresh"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def format_ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(_TS_FORMAT)


def parse_ts(text: str) -> datetime:
    """Parse a ``YYYY-MM-DDTHH:MM:SSZ`` timestamp (``ValueError`` when malformed)."""
    return datetime.strptime(text, _TS_FORMAT).replace(tzinfo=UTC)
