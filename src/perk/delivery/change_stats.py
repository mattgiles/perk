"""Categorized change stats for a PR's diff range — the lines added / removed / modified per row
(Code, Tests, Comments, Learned docs, Other), counted by cloc.

**perk owns the diff pairs; cloc only counts.** The module lists the range's changed files with
git, materializes both sides from the raw committed blobs (no attribute, filter or end-of-line
conversion — the counts describe exactly what the commits store), partitions every file in Python
by its repo-relative path, and hands cloc one explicit pair list per partition. Partition
ownership is therefore disjoint by construction — a rename is one compared pair owned by its
**new** path (the file's new role) — and cloc is never invoked for an empty range or an empty
partition.

Classification is data: an ordered partition tuple (first match wins, a residual last), crossed
with a language-class set (prose vs source, by cloc language name), routed by a six-arm table onto
the five fixed rows. A future partition or a config table maps onto the same shape.

Every failure surfaces as ``ChangeStatsUnavailable`` with a typed ``kind``; callers decide the
posture (publication degrades to a one-line note, the standalone worker fails loudly).
"""

import logging
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from perk.boundary import OutputModel
from perk.substrate import cloc, git, paths

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Partition:
    """A path class; ``pattern is None`` marks the residual partition (must be last)."""

    id: str
    pattern: re.Pattern[str] | None


LEARNED_PATH_RE = re.compile(rf"(^|/){re.escape(paths.LEARNED_DOCS_REL)}/")
TEST_PATH_RE = re.compile(
    "|".join(
        (
            r"(^|/)(test|tests|__tests__|__mocks__|fixtures|e2e|spec|testing|testdata)/",
            r"\.(test|spec)\.[cm]?[jt]sx?$",
            r"(^|/)test_[^/]+\.py$",
            r"_test\.py$",
            r"(^|/)conftest\.py$",
            r"_test\.go$",
        )
    )
)

PARTITIONS: tuple[Partition, ...] = (
    Partition("learned", LEARNED_PATH_RE),
    Partition("tests", TEST_PATH_RE),
    Partition("rest", None),
)


def _check_partitions(partitions: Sequence[Partition]) -> None:
    residuals = [index for index, part in enumerate(partitions) if part.pattern is None]
    if residuals != [len(partitions) - 1]:
        raise ValueError("exactly one residual (pattern-less) partition, and it must be last")


_check_partitions(PARTITIONS)

# cloc language names counted as prose/data; every other language is source.
PROSE_LANGUAGES: frozenset[str] = frozenset(
    {
        "Markdown",
        "reStructuredText",
        "AsciiDoc",
        "Text",
        "YAML",
        "JSON",
        "JSON5",
        "TOML",
        "INI",
        "XML",
        "CSV",
        "SVG",
        "Properties",
    }
)

# The fixed row order; data always carries all five, renderers hide zero rows.
ROWS: tuple[tuple[str, str], ...] = (
    ("code", "Code"),
    ("tests", "Tests"),
    ("comments", "Comments"),
    ("learned_docs", "Learned docs"),
    ("other", "Other"),
)

# U+2212, the typographic minus the renderers print before a removed count.
_MINUS = "\u2212"
_NOTE_MAX_CHARS = 200

type LineKind = Literal["code", "comment"]
type UnavailableKind = Literal["cloc_missing", "cloc_failed", "range_unresolved", "git_failed"]


def partition_of(path: str) -> str:
    """The partition id owning ``path`` (repo-relative POSIX) — the one classification function."""
    for part in PARTITIONS:
        if part.pattern is None or part.pattern.search(path):
            return part.id
    raise AssertionError("unreachable: the residual partition matches every path")


def _route(partition_id: str, language: str, kind: LineKind) -> str:
    """The six-arm routing table: (partition, language class, line kind) → row id."""
    if partition_id == "learned":
        return "learned_docs"
    if partition_id == "tests":
        return "tests" if kind == "code" else "comments"
    if language in PROSE_LANGUAGES:
        return "other"
    return "code" if kind == "code" else "comments"


@dataclass(frozen=True)
class RowStats:
    id: str
    label: str
    added: int
    removed: int
    modified: int

    @property
    def is_zero(self) -> bool:
        return self.added == 0 and self.removed == 0 and self.modified == 0


@dataclass(frozen=True)
class ChangeStats:
    """The counts over ``base..head`` — always every row of ``ROWS``, in order."""

    base: str
    head: str
    rows: tuple[RowStats, ...]


@dataclass(frozen=True)
class DiffRange:
    """A resolved range: ``base`` is the merge-base SHA, ``base_ref`` the ref it came from."""

    base: str
    head: str
    base_ref: str


class ChangeStatsUnavailable(Exception):
    """The stats could not be computed; ``kind`` classifies why."""

    def __init__(self, kind: UnavailableKind, message: str) -> None:
        super().__init__(message)
        self.kind: UnavailableKind = kind
        self.message = message

    def __str__(self) -> str:
        return self.message


def resolve_range(repo_root: Path, *, base: str, head_ref: str = "HEAD", fetch: bool) -> DiffRange:
    """Resolve ``merge-base(<base>, head_ref)..head_ref``.

    With ``fetch`` (publication) the remote is the authority: ``origin/<base>`` is fetched first
    — a stale tracking ref can yield a merge-base GitHub would not use — and a failed fetch is
    ``range_unresolved`` (no local fallback). Without ``fetch`` (the offline worker) no network:
    ``origin/<base>`` when it resolves locally, else the local ``<base>``.
    """
    remote_ref = f"origin/{base}"
    if fetch:
        try:
            git.fetch_refspecs(repo_root, [base])
        except git.GitError as exc:
            raise ChangeStatsUnavailable(
                "range_unresolved", f"could not fetch {remote_ref}: {exc}"
            ) from exc
        base_ref = remote_ref
    else:
        base_ref = remote_ref if git.remote_ref_exists(repo_root, remote_ref) else base
    head = git.resolve_commit(repo_root, head_ref)
    if head is None:
        raise ChangeStatsUnavailable("range_unresolved", f"could not resolve {head_ref}")
    base_sha = git.merge_base(repo_root, base_ref, head)
    if base_sha is None:
        raise ChangeStatsUnavailable(
            "range_unresolved", f"no merge-base between {base_ref} and {head_ref}"
        )
    return DiffRange(base=base_sha, head=head, base_ref=base_ref)


type ClocRunner = Callable[..., cloc.DiffReport]


@dataclass
class _PartitionPairs:
    added: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    compared: list[tuple[Path, Path]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.compared)

    def freeze(self) -> cloc.DiffPairs:
        return cloc.DiffPairs(
            added=tuple(self.added), removed=tuple(self.removed), compared=tuple(self.compared)
        )


def summarize(
    repo_root: Path, base: str, head: str, *, run_cloc: ClocRunner = cloc.diff_pairs
) -> ChangeStats:
    """Count ``base..head`` (commit SHAs) into the five rows.

    ``run_cloc`` is the internal seam (``cloc.diff_pairs``'s signature). Raises
    ``ChangeStatsUnavailable``: ``git_failed`` (listing, reading or materializing the range),
    ``cloc_missing`` / ``cloc_failed`` (counting it).
    """
    if base == head:
        return _stats(base, head, {})
    try:
        listed = git.diff_entries(repo_root, base, head)
    except git.GitError as exc:
        raise ChangeStatsUnavailable("git_failed", f"could not list the diff: {exc}") from exc
    entries = [entry for entry in listed if _representable(entry)]
    if not entries:
        return _stats(base, head, {})
    try:
        blobs = git.read_blobs(
            repo_root,
            [oid for entry in entries for oid in (entry.old_blob, entry.new_blob) if oid],
        )
    except git.GitError as exc:
        raise ChangeStatsUnavailable("git_failed", f"could not read the diff: {exc}") from exc
    with tempfile.TemporaryDirectory(prefix="perk-change-stats-") as tmp:
        root = Path(tmp)
        try:
            by_partition = _materialize(entries, blobs, root)
        except OSError as exc:
            raise ChangeStatsUnavailable(
                "git_failed", f"could not materialize the diff: {exc}"
            ) from exc
        totals: dict[str, list[int]] = {}
        for part in PARTITIONS:
            pairs = by_partition.get(part.id)
            if not pairs:
                continue
            report = _count(run_cloc, pairs.freeze(), workdir=root / part.id)
            _fold(totals, part.id, report)
    return _stats(base, head, totals)


def _representable(entry: git.DiffEntry) -> bool:
    """Whether cloc's list grammar can carry the entry's materialized file names (only the base
    name reaches cloc — each side lands under its own scratch directory)."""
    for path in (entry.path, entry.old_path):
        if path is not None and not cloc.representable(PurePosixPath(path).name):
            _log.debug("change stats: skipping %r (unrepresentable in a cloc list file)", path)
            return False
    return True


def _materialize(
    entries: Sequence[git.DiffEntry], blobs: Mapping[str, bytes], root: Path
) -> dict[str, _PartitionPairs]:
    """Write each entry's regular-file sides as the committed blob bytes and route the entry to
    its partition's pairs.

    Every side lands at ``<root>/<a|b>/<entry index>/<base name>``: a private directory per
    entry keeps same-named files apart (case-insensitive filesystems included), and the base
    name keeps cloc's language detection. A side without a blob (absent, a symlink, a submodule)
    is absent: a compared pair missing one side degrades to an add or a remove, and an entry
    with no counted side is dropped.
    """
    by_partition: dict[str, _PartitionPairs] = {}
    for index, entry in enumerate(entries):
        left = _write_side(
            root / "a" / str(index), entry.old_path or entry.path, entry.old_blob, blobs
        )
        right = _write_side(root / "b" / str(index), entry.path, entry.new_blob, blobs)
        pairs = by_partition.setdefault(partition_of(entry.path), _PartitionPairs())
        if left is not None and right is not None:
            pairs.compared.append((left, right))
        elif right is not None:
            pairs.added.append(right)
        elif left is not None:
            pairs.removed.append(left)
        else:
            _log.debug("change stats: skipping %r (no regular file on either side)", entry.path)
    return by_partition


def _write_side(
    directory: Path, rel_path: str, blob: str | None, blobs: Mapping[str, bytes]
) -> Path | None:
    if blob is None:
        return None
    directory.mkdir(parents=True)
    target = directory / PurePosixPath(rel_path).name
    target.write_bytes(blobs[blob])
    return target


def _count(run_cloc: ClocRunner, pairs: cloc.DiffPairs, *, workdir: Path) -> cloc.DiffReport:
    try:
        return run_cloc(pairs, workdir=workdir)
    except cloc.ClocError as exc:
        if exc.kind == "missing":
            raise ChangeStatsUnavailable("cloc_missing", exc.message) from exc
        raise ChangeStatsUnavailable("cloc_failed", f"{exc.kind}: {exc.message}") from exc
    except (OSError, UnicodeError) as exc:
        raise ChangeStatsUnavailable("cloc_failed", f"list file: {exc}") from exc


def _fold(totals: dict[str, list[int]], partition_id: str, report: cloc.DiffReport) -> None:
    """Add each language's added / removed / modified code and comment lines to its routed row
    (blank lines and unchanged ``same`` lines are not counted)."""
    for language, diff in report.languages.items():
        for kind in ("code", "comment"):
            row = totals.setdefault(_route(partition_id, language, kind), [0, 0, 0])
            row[0] += getattr(diff.added, kind)
            row[1] += getattr(diff.removed, kind)
            row[2] += getattr(diff.modified, kind)


def _stats(base: str, head: str, totals: dict[str, list[int]]) -> ChangeStats:
    rows = []
    for row_id, label in ROWS:
        added, removed, modified = totals.get(row_id, (0, 0, 0))
        rows.append(RowStats(row_id, label, added, removed, modified))
    return ChangeStats(base=base, head=head, rows=tuple(rows))


def _nonzero(stats: ChangeStats) -> list[RowStats]:
    return [row for row in stats.rows if not row.is_zero]


def _span(stats: ChangeStats) -> str:
    return f"{stats.base[:7]}..{stats.head[:7]}"


def normalize_note(note: str) -> str:
    """One line, whitespace collapsed, at most 200 characters."""
    flat = " ".join(note.split())
    if len(flat) > _NOTE_MAX_CHARS:
        return flat[: _NOTE_MAX_CHARS - 1] + "…"
    return flat


def render_pr_section(stats: ChangeStats | None, *, note: str | None) -> str:
    """The PR-body ``### Change stats`` section. Exactly one of ``stats`` / ``note`` is set."""
    if (stats is None) == (note is None):
        raise ValueError("render_pr_section needs exactly one of stats or note")
    heading = "### Change stats"
    if stats is None:
        assert note is not None
        return f"{heading}\n\n_Unavailable: {normalize_note(note).rstrip('.')}._"
    rows = _nonzero(stats)
    if not rows:
        return f"{heading}\n\n_No lines counted by cloc over {_span(stats)}._"
    table = [f"| | + | {_MINUS} | ~ |", "| --- | ---: | ---: | ---: |"]
    table += [f"| {r.label} | {r.added} | {r.removed} | {r.modified} |" for r in rows]
    footnote = (
        f"<sub>Lines counted by cloc (whitespace-insensitive) over {_span(stats)} — added / "
        "removed / modified; blank lines and files cloc does not recognize are excluded; "
        "renames count under their new path.</sub>"
    )
    return "\n".join([heading, "", *table, "", footnote])


def render_lines(stats: ChangeStats) -> list[str]:
    """The CLI rows (non-zero rows only)."""
    rows = _nonzero(stats)
    if not rows:
        return ["no lines counted by cloc"]
    return [f"{r.label:<13} +{r.added:<6} {_MINUS}{r.removed:<6} ~{r.modified}" for r in rows]


def render_compact(stats: ChangeStats) -> str:
    """One line over the non-zero rows: each row's lowercased label with its ``+added``,
    minus-removed and ``~modified`` counts, joined by `` · ``."""
    rows = _nonzero(stats)
    if not rows:
        return "no counted lines"
    return " · ".join(
        f"{r.label.lower()} +{r.added} {_MINUS}{r.removed} ~{r.modified}" for r in rows
    )


class ChangeStatsRowOut(OutputModel):
    id: str
    label: str
    added: int
    removed: int
    modified: int


class ChangeStatsOut(OutputModel):
    """The ``--json`` projection; ``rows`` is ordered so a future row appends compatibly."""

    base: str
    head: str
    rows: tuple[ChangeStatsRowOut, ...]

    @classmethod
    def from_domain(cls, stats: ChangeStats) -> "ChangeStatsOut":
        return cls(
            base=stats.base,
            head=stats.head,
            rows=tuple(
                ChangeStatsRowOut(
                    id=r.id, label=r.label, added=r.added, removed=r.removed, modified=r.modified
                )
                for r in stats.rows
            ),
        )
