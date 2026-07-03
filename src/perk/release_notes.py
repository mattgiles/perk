"""Lenient display parser + renderer for perk's bundled release notes (``CHANGELOG.md``).

This is the *display* posture: a total, never-raising line grammar that tolerates the real
changelog's shapes (empty category scaffolds, multi-line bullets, prose paragraphs, the
``<!-- As of … -->`` marker). The *strict* linter/facts posture lives in perk-dev's changelog
toolkit — the small header-regex overlap across the two postures is deliberate.

Totality comes from the grammar being lenient by construction (every line class has a defined
handling), not from exception swallowing — there is no ``try/except`` here. Malformed release
headers are skipped, stray prose is preserved, odd indentation is tolerated.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import click

# Anchored to the strict release-header shape: anything else spelled `## …` is an unknown
# section whose content is skipped (covers the file preamble and malformed headers).
_RELEASE_HEADER_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})\s*$")
_UNRELEASED_HEADER_RE = re.compile(r"^## \[Unreleased\]\s*$")
_CATEGORY_HEADER_RE = re.compile(r"^### +(.+?)\s*$")
_BULLET_RE = re.compile(r"^( *)- (.*)$")
# Single-line HTML comments (the `<!-- As of <hash> -->` marker) never become entries.
_HTML_COMMENT_RE = re.compile(r"^\s*<!--.*-->\s*$")

# The pseudo-release's version label (`## [Unreleased]` carries no date).
UNRELEASED_VERSION = "Unreleased"


@dataclass(frozen=True)
class Entry:
    """One rendered block: a bullet (continuation lines joined) or a bare prose paragraph."""

    kind: Literal["bullet", "prose"]
    text: str
    level: int


@dataclass(frozen=True)
class Category:
    """One ``### <name>`` subsection (any name accepted — display parser, not linter)."""

    name: str
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class Release:
    """One ``## [X.Y.Z] - YYYY-MM-DD`` section, or the ``[Unreleased]`` pseudo-release.

    ``preamble`` holds entries before the first ``###``; ``date`` is ``None`` only for
    the pseudo-release.
    """

    version: str
    date: str | None
    preamble: tuple[Entry, ...]
    categories: tuple[Category, ...]

    def has_content(self) -> bool:
        """Whether any entry exists anywhere (preamble or any category)."""
        if self.preamble:
            return True
        return any(category.entries for category in self.categories)


@dataclass
class _CategoryBuilder:
    name: str
    entries: list[Entry] = field(default_factory=list)


@dataclass
class _ReleaseBuilder:
    version: str
    date: str | None
    preamble: list[Entry] = field(default_factory=list)
    categories: list[_CategoryBuilder] = field(default_factory=list)

    def target(self) -> list[Entry]:
        """Where entries currently land: the latest category, or the preamble before any."""
        if self.categories:
            return self.categories[-1].entries
        return self.preamble

    def finalize(self) -> Release:
        return Release(
            version=self.version,
            date=self.date,
            preamble=tuple(self.preamble),
            categories=tuple(
                Category(name=c.name, entries=tuple(c.entries)) for c in self.categories
            ),
        )


@dataclass
class _OpenEntry:
    """A bullet or prose paragraph mid-accumulation (continuation lines still joining)."""

    kind: Literal["bullet", "prose"]
    parts: list[str]
    level: int


@dataclass
class _Parser:
    """Single line-pass state: an open release collects; ``None`` means content is skipped."""

    include_unreleased: bool
    releases: list[Release] = field(default_factory=list)
    _builder: _ReleaseBuilder | None = None
    _open: _OpenEntry | None = None

    def feed(self, line: str) -> None:
        release_match = _RELEASE_HEADER_RE.match(line)
        if release_match is not None:
            self._open_release(version=release_match.group(1), date=release_match.group(2))
            return
        if _UNRELEASED_HEADER_RE.match(line) is not None:
            if self.include_unreleased:
                self._open_release(version=UNRELEASED_VERSION, date=None)
            else:
                self._close_release()
            return
        if line.startswith("## "):
            # Any other second-level header (file preamble, malformed release header):
            # close the open release; the unknown section's content is skipped.
            self._close_release()
            return
        if self._builder is None:
            return
        category_match = _CATEGORY_HEADER_RE.match(line)
        if category_match is not None:
            self._flush_entry()
            self._builder.categories.append(_CategoryBuilder(name=category_match.group(1)))
            return
        if _HTML_COMMENT_RE.match(line) is not None:
            return
        if not line.strip():
            self._flush_entry()
            return
        bullet_match = _BULLET_RE.match(line)
        if bullet_match is not None:
            self._flush_entry()
            indent = len(bullet_match.group(1))
            # Lenient on odd indents: integer division maps 2/4/… → 1/2/… and 3 → 1.
            self._open = _OpenEntry(
                kind="bullet", parts=[bullet_match.group(2).strip()], level=indent // 2
            )
            return
        # Non-blank, non-header, non-bullet: a continuation line of the open bullet/paragraph,
        # or the start of a new prose paragraph.
        if self._open is not None:
            self._open.parts.append(line.strip())
            return
        self._open = _OpenEntry(kind="prose", parts=[line.strip()], level=0)

    def finish(self) -> tuple[Release, ...]:
        self._close_release()
        return tuple(self.releases)

    def _open_release(self, *, version: str, date: str | None) -> None:
        self._close_release()
        self._builder = _ReleaseBuilder(version=version, date=date)

    def _close_release(self) -> None:
        self._flush_entry()
        if self._builder is not None:
            self.releases.append(self._builder.finalize())
            self._builder = None

    def _flush_entry(self) -> None:
        if self._open is None:
            return
        if self._builder is not None:
            entry = Entry(
                kind=self._open.kind,
                text=" ".join(self._open.parts).strip(),
                level=self._open.level,
            )
            self._builder.target().append(entry)
        self._open = None


def parse_release_notes(text: str, *, include_unreleased: bool = False) -> tuple[Release, ...]:
    """Parse changelog markdown into releases, in file order (newest first).

    Total over any string input: malformed headers are skipped, stray prose is preserved.
    The ``[Unreleased]`` pseudo-release is collected only when ``include_unreleased`` is set
    (yielded first, ``date=None``).
    """
    parser = _Parser(include_unreleased=include_unreleased)
    for line in text.splitlines():
        parser.feed(line)
    return parser.finish()


def find_release(releases: Sequence[Release], version: str) -> Release | None:
    """The release whose version equals ``version`` exactly, or ``None``."""
    for release in releases:
        if release.version == version:
            return release
    return None


def render_release(release: Release) -> str:
    """Plain terminal text for one release: bold header, preamble, non-empty categories.

    Empty category scaffolds are dropped; bullets indent by level; prose renders as a bare
    paragraph (blank-line separated from preceding entries).
    """
    header = release.version if release.date is None else f"{release.version} ({release.date})"
    blocks: list[str] = [click.style(header, bold=True)]
    if release.preamble:
        blocks.append(_render_entries(release.preamble))
    for category in release.categories:
        if not category.entries:
            continue
        blocks.append(f"{category.name}:\n" + _render_entries(category.entries))
    return "\n\n".join(blocks)


def render_releases(releases: Sequence[Release]) -> str:
    """All releases rendered, joined by a blank line."""
    return "\n\n".join(render_release(release) for release in releases)


def _render_entries(entries: Sequence[Entry]) -> str:
    lines: list[str] = []
    for entry in entries:
        if entry.kind == "bullet":
            lines.append(("  " * (entry.level + 1)) + "- " + entry.text)
            continue
        if lines:
            lines.append("")
        lines.append(entry.text)
    return "\n".join(lines)
