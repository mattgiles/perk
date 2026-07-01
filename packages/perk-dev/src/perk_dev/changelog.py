"""Deterministic changelog **facts** for ``perk-dev changelog-commits``.

Reports the first-parent commits between the changelog's "last covered commit" cursor and HEAD.
It applies **no** semantic judgment: no categorization, no inclusion/exclusion, no marker mutation
(the categorizer and ``changelog-apply`` own that). Since-commit resolution priority is
``--since`` flag → ``[Unreleased]`` marker → latest release header (``vX.Y.Z`` tag).
"""

import re
from dataclasses import dataclass
from pathlib import Path

from perk.boundary import OutputModel
from perk.substrate import git

_MARKER_RE = re.compile(r"^<!-- As of ([0-9a-f]{7,40}) -->$")
_RELEASE_HEADER_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}")
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
    latest release header → (``vX.Y.Z``, "release-fallback"). A missing ``CHANGELOG.md`` or the
    absence of any reference raises ``ChangelogError``.
    """
    if since_flag is not None:
        return since_flag, "flag"
    changelog = root / "CHANGELOG.md"
    try:
        text = changelog.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ChangelogError("changelog_not_found", f"{changelog} not found") from exc
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
