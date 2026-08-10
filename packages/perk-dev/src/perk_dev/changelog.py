"""Deterministic changelog **facts** for ``perk-dev changelog-commits``.

Reports the first-parent commits between the changelog's "last covered commit" cursor and HEAD.
It applies **no** semantic judgment: no categorization, no inclusion/exclusion, no marker mutation
(the categorizer and ``changelog-apply`` own that). Since-commit resolution priority is
``--since`` flag → ``[Unreleased]`` marker → latest release header (``vX.Y.Z`` tag).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk.boundary import (
    OutputModel,
    StrictInputModel,
    ValidationError,
    format_validation_error,
)
from perk.substrate import git

_MARKER_RE = re.compile(r"^<!-- As of ([0-9a-f]{7,40}) -->$")
_RELEASE_HEADER_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})")
# Structural-linter patterns (``changelog-check``). Distinct from the strict facts patterns above:
# these accept *malformed* shapes so the linter can name the defect rather than silently miss it.
_RELEASE_HEADER_STRICT_RE = re.compile(r"^## \[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}\s*$")
_MARKER_SHAPE_RE = re.compile(r"^<!--\s*As of\s+(\S+)\s*-->\s*$")
_TRAILING_HASH_RE = re.compile(r" \([0-9a-f]{7,40}\)\s*$")
_BULLET_RE = re.compile(r"^( *)- ")
# Keep-a-Changelog 1.1.0 categories plus perk's ``Major Changes``, in the canonical subsection
# order ``changelog-apply`` inserts by (Major Changes first). Single source of truth: the
# linter's allowed set is derived from it.
_CATEGORY_ORDER: tuple[str, ...] = (
    "Major Changes",
    "Added",
    "Changed",
    "Deprecated",
    "Removed",
    "Fixed",
    "Security",
)
_ALLOWED_CATEGORIES: frozenset[str] = frozenset(_CATEGORY_ORDER)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_PR_RE = re.compile(r"\(#(\d+)\)")
_MERGE_PR_RE = re.compile(r"^Merge pull request #(\d+)\b")
_BODY_TRUNCATE_CHARS = 500
# Only the two root lockfiles are dropped — never the generated/managed workflow/.pi/AGENTS/skills
# files, which can be user-facing (the categorizer, node 3.1, owns all judgment).
_ALWAYS_INTERNAL_PATHS = frozenset({"uv.lock", "package-lock.json"})


def find_marker(text: str) -> str | None:
    """The captured hash of the first ``<!-- As of <hash> -->`` marker line, or ``None``.

    ``rstrip`` tolerates trailing whitespace/CR on the line.
    """
    for line in text.splitlines():
        match = _MARKER_RE.match(line.rstrip())
        if match is not None:
            return match.group(1)
    return None


def latest_release_version(text: str) -> str | None:
    """The ``X.Y.Z`` of the first ``## [X.Y.Z] - DATE`` header (top-down = newest), or ``None``."""
    for line in text.splitlines():
        match = _RELEASE_HEADER_RE.match(line)
        if match is not None:
            return match.group(1)
    return None


def latest_release(text: str) -> tuple[str, str] | None:
    """``(version, date)`` of the first ``## [X.Y.Z] - DATE`` header (top-down = newest), or
    ``None`` when no release header exists."""
    for line in text.splitlines():
        match = _RELEASE_HEADER_RE.match(line)
        if match is not None:
            return match.group(1), match.group(2)
    return None


def release_history(text: str) -> tuple[tuple[str, str], ...]:
    """Every ``(version, date)`` from ``## [X.Y.Z] - DATE`` headers, in file order.

    File order is top-down = newest first. Pure text, never raises; lines that do not
    match the release-header shape are simply skipped.
    """
    releases: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _RELEASE_HEADER_RE.match(line)
        if match is not None:
            releases.append((match.group(1), match.group(2)))
    return tuple(releases)


def extract_pr(subject: str) -> int | None:
    """The PR number from a commit ``subject``, or ``None``.

    Reads the **subject only** (the body's trailing ``Closes #NNNN`` is an issue, not the PR).
    Prefers the last ``(#N)`` paren match (a squash-merge subject); falls back to a
    ``Merge pull request #N`` prefix.
    """
    matches = _PR_RE.findall(subject)
    if matches:
        return int(matches[-1])
    merge = _MERGE_PR_RE.match(subject)
    if merge is not None:
        return int(merge.group(1))
    return None


def truncate_body(body: str) -> str:
    """``body`` stripped, capped at ``_BODY_TRUNCATE_CHARS`` chars; ``…`` appended on overflow."""
    stripped = body.strip()
    if len(stripped) > _BODY_TRUNCATE_CHARS:
        return stripped[:_BODY_TRUNCATE_CHARS].rstrip() + "\u2026"
    return stripped


@dataclass(frozen=True)
class CommitRecord:
    """One commit's presentation-ready facts (filtered files, truncated body, extracted PR)."""

    hash: str
    subject: str
    body: str
    files: tuple[str, ...]
    pr: int | None


@dataclass(frozen=True)
class ChangelogCommits:
    """The full facts report: the resolved range + its first-parent commits (newest first)."""

    since_commit: str
    head_commit: str
    since_source: str  # "flag" | "marker" | "release-fallback"
    commits: tuple[CommitRecord, ...]


class ChangelogError(Exception):
    """A recoverable changelog-facts failure carrying a machine ``error_type`` + human message."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def resolve_since(root: Path, since_flag: str | None) -> tuple[str, str]:
    """Resolve the since-*ref* (not yet a SHA) + its ``source``.

    ``--since`` → (flag, "flag"); else the ``CHANGELOG.md`` marker → ("marker"); else the
    latest release header → (``vX.Y.Z``, "release-fallback"). A missing or non-UTF-8
    ``CHANGELOG.md``, or the absence of any reference, raises ``ChangelogError``.
    """
    if since_flag is not None:
        return since_flag, "flag"
    changelog = root / "CHANGELOG.md"
    try:
        text = changelog.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ChangelogError("changelog_not_found", f"{changelog} not found") from exc
    except UnicodeDecodeError as exc:
        raise ChangelogError("changelog_not_utf8", f"{changelog} is not valid UTF-8") from exc
    marker = find_marker(text)
    if marker is not None:
        return marker, "marker"
    version = latest_release_version(text)
    if version is not None:
        return f"v{version}", "release-fallback"
    raise ChangelogError(
        "no_since_reference",
        "CHANGELOG.md has neither an '<!-- As of <hash> -->' marker nor a release header",
    )


def _to_record(info: git.CommitInfo) -> CommitRecord:
    return CommitRecord(
        hash=info.hash,
        subject=info.subject,
        body=truncate_body(info.body),
        files=tuple(f for f in info.files if f not in _ALWAYS_INTERNAL_PATHS),
        pr=extract_pr(info.subject),
    )


# Maps the resolved since-source to the error_type raised when its ref fails to resolve to a SHA.
_UNRESOLVABLE_FOR_SOURCE = {
    "flag": "since_unresolvable",
    "marker": "marker_unresolvable",
    "release-fallback": "release_tag_unresolvable",
}


def gather(root: Path, *, since_flag: str | None) -> ChangelogCommits:
    """The facts report for ``root``: resolve the range, then read its first-parent commits."""
    ref, source = resolve_since(root, since_flag)
    since_commit = git.resolve_commit(root, ref)
    if since_commit is None:
        raise ChangelogError(
            _UNRESOLVABLE_FOR_SOURCE[source], f"since ref does not resolve to a commit: {ref}"
        )
    head_commit = git.resolve_commit(root, "HEAD")
    if head_commit is None:
        raise ChangelogError("head_unresolvable", "HEAD does not resolve to a commit")
    commits = tuple(_to_record(i) for i in git.log_first_parent(root, since=since_commit))
    return ChangelogCommits(
        since_commit=since_commit,
        head_commit=head_commit,
        since_source=source,
        commits=commits,
    )


class CommitOut(OutputModel):
    """The ``--json`` snapshot of one commit (field order is load-bearing for emitted JSON)."""

    hash: str
    subject: str
    body: str
    files: tuple[str, ...]
    pr: int | None

    @classmethod
    def from_domain(cls, r: CommitRecord) -> "CommitOut":
        return cls(hash=r.hash, subject=r.subject, body=r.body, files=r.files, pr=r.pr)


class ChangelogCommitsOut(OutputModel):
    """The ``--json`` envelope for a successful facts report."""

    success: bool
    error_type: str | None
    since_commit: str
    head_commit: str
    since_source: str
    commits: tuple[CommitOut, ...]

    @classmethod
    def from_domain(cls, c: ChangelogCommits) -> "ChangelogCommitsOut":
        return cls(
            success=True,
            error_type=None,
            since_commit=c.since_commit,
            head_commit=c.head_commit,
            since_source=c.since_source,
            commits=tuple(CommitOut.from_domain(r) for r in c.commits),
        )


# --- changelog-check: a pure text-structural linter ---------------------------------
#
# Validates ``CHANGELOG.md`` against the normalized two-phase convention and the pinned
# Keep-a-Changelog category set. No git, no semantic judgment: a single line-indexed pass over
# the file text. Structural defects are ``error`` findings (the CLI exits non-zero); softer style
# issues are ``warning`` findings (exit 0).


@dataclass(frozen=True)
class Finding:
    """One structural-lint result: its ``severity``, machine ``code``, 1-based ``line``, message."""

    severity: Literal["error", "warning"]
    code: str
    line: int | None
    message: str


@dataclass(frozen=True)
class ChangelogCheck:
    """The structural-lint report: all findings in first-seen order."""

    findings: tuple[Finding, ...]

    def has_errors(self) -> bool:
        """Whether any finding is an ``error`` (a method, not a property — it iterates)."""
        return any(f.severity == "error" for f in self.findings)


def check(root: Path) -> ChangelogCheck:
    """Lint ``root/CHANGELOG.md`` structurally, returning every finding (LBYL on file presence).

    Section state (``pre``/``unreleased``/``released``) drives the per-section bullet-token rule
    and the marker-position check; only the two ``## [...]`` bracket-header forms transition it, so
    the ``[Unreleased]`` span (for marker "inside" purposes) is exactly ``section == "unreleased"``.
    """
    path = root / "CHANGELOG.md"
    if not path.exists():
        raise ChangelogError("changelog_not_found", f"{path} not found")
    text = path.read_text(encoding="utf-8")

    findings: list[Finding] = []

    def add(
        severity: Literal["error", "warning"], code: str, line: int | None, message: str
    ) -> None:
        findings.append(Finding(severity, code, line, message))

    section = "pre"  # "pre" | "unreleased" | "released"
    unreleased_count = 0
    marker_count = 0

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped == "## [Unreleased]":
            unreleased_count += 1
            section = "unreleased"
            continue
        if line.startswith("## ["):
            section = "released"
            if _RELEASE_HEADER_STRICT_RE.match(line) is None:
                add("error", "bad_release_header", i, f"malformed release header: {stripped!r}")
            continue
        if line.startswith("### "):
            name = stripped[4:].strip()
            if name not in _ALLOWED_CATEGORIES:
                add("error", "unknown_category", i, f"unknown category: {name!r}")
            continue
        marker = _MARKER_SHAPE_RE.match(line)
        if marker is not None:
            marker_count += 1
            token = marker.group(1)
            if re.fullmatch(r"[0-9a-f]{7,40}", token) is None:
                add("error", "bad_marker_hash", i, f"malformed marker hash: {token!r}")
            if section != "unreleased":
                add("error", "marker_outside_unreleased", i, "marker is not inside [Unreleased]")
            continue
        bullet = _BULLET_RE.match(line)
        if bullet is not None:
            indent = bullet.group(1)
            if len(indent) % 2 != 0:
                add("warning", "bad_bullet_indent", i, "bullet indent is not a 2-space multiple")
            if indent == "":
                has_token = _TRAILING_HASH_RE.search(line) is not None
                if section == "unreleased" and not has_token:
                    add("error", "unreleased_missing_hash", i, "[Unreleased] bullet lacks a token")
                elif section == "released" and has_token:
                    add("error", "released_has_hash", i, "released bullet carries a (hash) token")
            continue

    if unreleased_count == 0:
        add("error", "no_unreleased", None, "no '## [Unreleased]' section")
    elif unreleased_count > 1:
        add("error", "duplicate_unreleased", None, f"{unreleased_count} '## [Unreleased]' sections")
    if marker_count > 1:
        add("error", "duplicate_marker", None, f"{marker_count} marker lines")
    if unreleased_count >= 1 and marker_count == 0:
        add("warning", "missing_marker", None, "[Unreleased] present but no marker line")

    return ChangelogCheck(tuple(findings))


class FindingOut(OutputModel):
    """The ``--json`` snapshot of one structural-lint finding."""

    severity: str
    code: str
    line: int | None
    message: str

    @classmethod
    def from_domain(cls, f: Finding) -> "FindingOut":
        return cls(severity=f.severity, code=f.code, line=f.line, message=f.message)


class ChangelogCheckOut(OutputModel):
    """The ``--json`` envelope for a structural-lint report (perk-dev's success+error_type)."""

    success: bool
    error_type: str | None
    findings: tuple[FindingOut, ...]

    @classmethod
    def from_domain(cls, c: ChangelogCheck) -> "ChangelogCheckOut":
        has_errors = c.has_errors()
        return cls(
            success=not has_errors,
            error_type="structural_errors" if has_errors else None,
            findings=tuple(FindingOut.from_domain(f) for f in c.findings),
        )


# --- changelog-apply: apply an approved proposal ------------------------------------
#
# The deterministic "apply + advance marker" step of the accrual loop. It consumes the
# categorizer's pinned proposal JSON and performs a **pure text transform** of CHANGELOG.md
# (no git, no subprocess): append each entry as a top-level bullet under its ``### <category>``
# subsection of ``[Unreleased]`` (stamping the primary commit's 7-char hash) and advance the
# ``<!-- As of <hash> -->`` marker to the proposal's ``head_commit``. It never authors,
# reclassifies, filters, or reorders entries, and it is intentionally NOT idempotent — the
# marker advance is the loop's re-run guard.


class ProposalEntryModel(StrictInputModel):
    """One proposal entry as pinned by ``docs/release/changelog-categorizer.md``.

    ``confidence`` / ``backend`` are review metadata — part of the pinned shape but unused by
    apply; optional so a hand-authored apply-only proposal may omit them.
    """

    category: str
    text: str
    commits: list[str]
    confidence: str | None = None
    backend: str | None = None


class ProposalModel(StrictInputModel):
    """The pinned proposal envelope (machine-authored batch input — a typo must fail loudly)."""

    since_commit: str
    head_commit: str
    entries: list[ProposalEntryModel]


@dataclass(frozen=True)
class ProposalEntry:
    """One approved entry: its category, bullet body, and contributing commits."""

    category: str
    text: str
    commits: tuple[str, ...]

    @property
    def primary(self) -> str:
        """The primary (first) commit — its short hash is the stamped ``(hash)`` token."""
        return self.commits[0]


@dataclass(frozen=True)
class Proposal:
    """The approved proposal apply consumes (``since_commit`` is review metadata, unused)."""

    since_commit: str
    head_commit: str
    entries: tuple[ProposalEntry, ...]


def _validate_proposal(proposal: Proposal) -> None:
    """Content pass over a shape-valid proposal; each defect raises ``bad_proposal``."""
    for name, sha in (
        ("since_commit", proposal.since_commit),
        ("head_commit", proposal.head_commit),
    ):
        if _SHA_RE.match(sha) is None:
            raise ChangelogError("bad_proposal", f"{name} is not a commit SHA: {sha!r}")
    for i, entry in enumerate(proposal.entries):
        where = f"entries[{i}]"
        if entry.category not in _ALLOWED_CATEGORIES:
            raise ChangelogError("bad_proposal", f"{where}: unknown category: {entry.category!r}")
        if not entry.commits:
            raise ChangelogError("bad_proposal", f"{where}: commits is empty")
        for sha in entry.commits:
            if _SHA_RE.match(sha) is None:
                raise ChangelogError("bad_proposal", f"{where}: not a commit SHA: {sha!r}")
        if not entry.text.strip():
            raise ChangelogError("bad_proposal", f"{where}: text is empty")
        if _TRAILING_HASH_RE.search(entry.text) is not None:
            raise ChangelogError(
                "bad_proposal",
                f"{where}: text already ends with a (hash) token — apply stamps exactly one",
            )


def parse_proposal(data: object) -> Proposal:
    """Parse + validate a proposal object into the frozen domain ``Proposal``.

    The strict model IS the authoritative shape validator (EAFP); the content rules
    (categories, SHA shapes, no pre-stamped token) run as a separate LBYL pass.
    """
    try:
        model = ProposalModel.model_validate(data)
    except ValidationError as exc:
        raise ChangelogError(
            "bad_proposal", format_validation_error(exc, source="proposal")
        ) from exc
    proposal = Proposal(
        since_commit=model.since_commit,
        head_commit=model.head_commit,
        entries=tuple(
            ProposalEntry(category=e.category, text=e.text, commits=tuple(e.commits))
            for e in model.entries
        ),
    )
    _validate_proposal(proposal)
    return proposal


def load_proposal(path: Path) -> Proposal:
    """Read + parse a proposal JSON file (LBYL on presence; the JSON parser is the JSON test)."""
    if not path.is_file():
        raise ChangelogError("proposal_not_found", f"{path} not found")
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChangelogError("bad_proposal", f"{path} is not valid JSON: {exc}") from exc
    return parse_proposal(data)


@dataclass(frozen=True)
class _Segment:
    """One ``### <category>`` subsection of ``[Unreleased]``: its raw heading + content lines.

    Frozen identity; ``content`` is a mutable accumulator (untouched segments re-emit their
    lines byte-identically).
    """

    heading: str
    content: list[str]

    @property
    def category(self) -> str:
        return self.heading[4:].strip()


def _unreleased_bounds(lines: list[str]) -> tuple[int, int]:
    """(header index, exclusive end index) of the ``## [Unreleased]`` section."""
    start = next((i for i, line in enumerate(lines) if line.strip() == "## [Unreleased]"), None)
    if start is None:
        raise ChangelogError("no_unreleased", "CHANGELOG.md has no '## [Unreleased]' section")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def _advance_marker(body: list[str], head_commit: str) -> list[str]:
    """``body`` with its marker line rewritten to ``head_commit``'s 7-char short hash."""
    for i, line in enumerate(body):
        if _MARKER_SHAPE_RE.match(line) is not None:
            return [*body[:i], f"<!-- As of {head_commit[:7]} -->", *body[i + 1 :]]
    raise ChangelogError(
        "marker_missing", "[Unreleased] has no '<!-- As of <hash> -->' marker line"
    )


def _split_segments(body: list[str]) -> tuple[list[str], list[_Segment]]:
    """Split the ``[Unreleased]`` body into its preamble + ``### `` segments, in order."""
    preamble: list[str] = []
    segments: list[_Segment] = []
    for line in body:
        if line.startswith("### "):
            segments.append(_Segment(heading=line, content=[]))
        elif segments:
            segments[-1].content.append(line)
        else:
            preamble.append(line)
    return preamble, segments


def _with_bullets(content: list[str], bullets: list[str]) -> list[str]:
    """Existing content with ``bullets`` appended: one leading + one trailing blank line."""
    kept = list(content)
    while kept and kept[0].strip() == "":
        kept.pop(0)
    while kept and kept[-1].strip() == "":
        kept.pop()
    return ["", *kept, *bullets, ""]


def _splice_new_segment(segments: list[_Segment], new: _Segment) -> list[_Segment]:
    """Insert ``new`` by ``_CATEGORY_ORDER`` rank: before the first segment ranked after it."""
    rank = _CATEGORY_ORDER.index(new.category)
    for i, seg in enumerate(segments):
        if seg.category in _ALLOWED_CATEGORIES and _CATEGORY_ORDER.index(seg.category) > rank:
            return [*segments[:i], new, *segments[i:]]
    return [*segments, new]


def apply_to_text(changelog_text: str, proposal: Proposal) -> str:
    """The new full changelog text: entries appended + marker advanced (pure, no I/O)."""
    lines = changelog_text.splitlines()
    start, end = _unreleased_bounds(lines)
    body = _advance_marker(lines[start + 1 : end], proposal.head_commit)
    preamble, segments = _split_segments(body)
    grouped: dict[str, list[str]] = {}
    for entry in proposal.entries:
        grouped.setdefault(entry.category, []).append(f"- {entry.text} ({entry.primary[:7]})")
    for category, bullets in grouped.items():
        existing = next((s for s in segments if s.category == category), None)
        if existing is not None:
            existing.content[:] = _with_bullets(existing.content, bullets)
        else:
            new = _Segment(heading=f"### {category}", content=["", *bullets, ""])
            segments = _splice_new_segment(segments, new)
    new_body = preamble + [line for seg in segments for line in (seg.heading, *seg.content)]
    return "\n".join(lines[: start + 1] + new_body + lines[end:]) + "\n"


def extract_unreleased(changelog_text: str) -> str:
    """The ``## [Unreleased]`` section (trailing blank lines trimmed), for ``--dry-run``."""
    lines = changelog_text.splitlines()
    start, end = _unreleased_bounds(lines)
    section = lines[start:end]
    while section and section[-1].strip() == "":
        section.pop()
    return "\n".join(section) + "\n"


# --- bump-version: roll [Unreleased] into a release section --------------------------
#
# The release-phase text transform of the two-phase convention: ``[Unreleased]`` becomes
# ``## [X.Y.Z] - DATE`` (tokens stripped from top-level bullets, empty category scaffolds
# dropped, the old marker removed) and a fresh ``[Unreleased]`` — marker only, no scaffold —
# is created above it (``changelog-apply`` creates category segments on demand). Pure text,
# no git, no I/O; the orchestration lives in ``perk_dev.bump``.


@dataclass(frozen=True)
class RolledChangelog:
    """A completed roll: the new full changelog text + the top-level bullets released."""

    text: str
    entries: int


def roll_unreleased(text: str, *, version: str, date: str, head_short: str) -> RolledChangelog:
    """Roll ``[Unreleased]`` into a ``## [version] - date`` section (pure, no I/O).

    Tokens are stripped from **top-level** bullets only (nested bullets are exempt,
    mirroring ``changelog-check``'s enforcement); everything outside the ``[Unreleased]``
    span is re-emitted byte-identically.
    """
    lines = text.splitlines()
    header_prefix = f"## [{version}]"
    if any(line.startswith(header_prefix) for line in lines):
        raise ChangelogError(
            "duplicate_release_header",
            f"CHANGELOG.md already has a '## [{version}]' release header",
        )
    start, end = _unreleased_bounds(lines)

    body: list[str] = []
    entries = 0
    for line in lines[start + 1 : end]:
        if _MARKER_SHAPE_RE.match(line) is not None:
            continue
        bullet = _BULLET_RE.match(line)
        if bullet is not None and bullet.group(1) == "":
            entries += 1
            line = _TRAILING_HASH_RE.sub("", line)
        body.append(line)
    if entries == 0:
        raise ChangelogError(
            "nothing_to_release", "[Unreleased] has no entries (no top-level bullets)"
        )

    def _stripped(block: list[str]) -> list[str]:
        kept = list(block)
        while kept and kept[0].strip() == "":
            kept.pop(0)
        while kept and kept[-1].strip() == "":
            kept.pop()
        return kept

    preamble, segments = _split_segments(body)
    blocks = [block for block in [_stripped(preamble)] if block]
    blocks.extend(
        [seg.heading, "", *content] for seg in segments if (content := _stripped(seg.content))
    )
    release_body: list[str] = []
    for block in blocks:
        release_body += ["", *block]
    release_body.append("")
    if end == len(lines):  # no remainder: avoid a trailing blank line at EOF
        while release_body and release_body[-1] == "":
            release_body.pop()

    new_top = [
        "## [Unreleased]",
        "",
        f"<!-- As of {head_short} -->",
        "",
        f"## [{version}] - {date}",
        *release_body,
    ]
    rolled = "\n".join(lines[:start] + new_top + lines[end:]) + "\n"
    return RolledChangelog(text=rolled, entries=entries)


def extract_roll_preview(text: str, version: str) -> str:
    """``## [Unreleased]`` through the end of the ``## [version]`` section, for ``--dry-run``.

    The sibling of ``extract_unreleased``, spanning both sections a roll rewrites. Expects
    rolled text (the version header must exist).
    """
    lines = text.splitlines()
    start, _ = _unreleased_bounds(lines)
    header_prefix = f"## [{version}]"
    header = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(header_prefix)), None
    )
    if header is None:
        raise ChangelogError(
            "no_release_header", f"CHANGELOG.md has no '## [{version}]' release header"
        )
    end = next((i for i in range(header + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[start:end]
    while section and section[-1].strip() == "":
        section.pop()
    return "\n".join(section) + "\n"
