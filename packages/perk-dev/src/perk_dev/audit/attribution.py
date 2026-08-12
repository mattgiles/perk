"""Transcript-composition attribution: what a session file actually accumulates.

Pure analysis over one :class:`~perk.learn.session_jsonl.ParsedSession`: every count is
derived from the read edge's per-line ``raw_chars`` metric — code points of the decoded
JSONL line, newline excluded. The metric is complete per line (unknown fields and
unprojected payloads like ``message.details`` included), so the accounting reconciles
exactly: per-kind rows sum to the **entry** total (``total_chars``), and
``total_chars + header_chars + malformed_chars`` covers the whole file (whitespace-only
lines, which the parser skips, excepted) — robust to grammar evolution. Whole-file
totals are primary; the active-branch divergence is *named* (the off-branch row, via
``select_active_branch``), never hidden.

Privacy posture (the census's): identifiers + derived counts only — never result content.
The top-results rows carry entry index, tool name, chars, the error flag, and (for the
``read`` tool) the recovered ``path`` argument.

Determinism: kind/tool rows sort chars-desc then label-asc; read-path classes render in
the fixed ``READ_CLASSES`` order; top results tie-break by ascending entry index. The
read-path classification is **lexical** (no filesystem access) — see
:func:`classify_read_path`.
"""

from collections import Counter
from dataclasses import dataclass

from perk.boundary import OutputModel
from perk.learn.normalize import select_active_branch
from perk.learn.session_jsonl import ParsedSession, SessionEntry
from perk_dev.audit.checks import pair_executions

# The largest-individual-results cap (fixed; ordering is chars-desc, tie index-asc).
TOP_RESULTS = 10

# The fixed read-path class vocabulary, in render order.
READ_CLASSES: tuple[str, ...] = ("docs/learned/", "skills/", "prompts/", "other", "unresolved")

# The tool label for a toolResult entry carrying no toolName.
_UNKNOWN_TOOL = "(unknown)"


@dataclass(frozen=True)
class KindRow:
    """One kind-attribution row: a stable label (``message:<role>``,
    ``<kind>:<custom_type>``, or bare ``kind``) with its entry count + raw chars."""

    label: str
    entries: int
    chars: int


@dataclass(frozen=True)
class ToolRow:
    """One tool-attribution row: toolResult entries grouped by tool name."""

    tool: str
    entries: int
    chars: int


@dataclass(frozen=True)
class ReadClassRow:
    """One read-path-class row (a ``READ_CLASSES`` member): ``read``-tool results whose
    recovered ``path`` argument classifies into this class."""

    read_class: str
    entries: int
    chars: int


@dataclass(frozen=True)
class TopResult:
    """One of the largest individual toolResult entries — provenance only, never content.
    ``path`` is the recovered ``read`` call's ``path`` argument (``None`` otherwise)."""

    index: int
    tool: str
    chars: int
    is_error: bool
    path: str | None


@dataclass(frozen=True)
class SessionAttribution:
    """One session file's full attribution: reconciliation totals (entries/chars, header,
    malformed, off-branch) plus the kind/tool/read-class/top-results breakdowns."""

    source: str
    total_entries: int
    total_chars: int
    header_chars: int
    malformed_lines: int
    malformed_chars: int
    off_branch_entries: int
    off_branch_chars: int
    kinds: tuple[KindRow, ...]
    tools: tuple[ToolRow, ...]
    read_classes: tuple[ReadClassRow, ...]
    top_results: tuple[TopResult, ...]


@dataclass(frozen=True)
class AttributionReport:
    """The full report: one :class:`SessionAttribution` per input file, in argument order."""

    sessions: tuple[SessionAttribution, ...]


def classify_read_path(path: str) -> str:
    """Classify a ``read`` call's ``path`` argument lexically (no filesystem access).

    Separators normalize to ``/``; fixed precedence: substring ``docs/learned/`` →
    ``docs/learned/``; else segment ``skills`` among the *directory* segments (covers
    ``skills/``, ``.agents/skills/``, ``.pi/npm/…/skills/``) → ``skills/``; else directory
    segment ``prompts`` → ``prompts/``; else ``other``. Filename segments never match
    (``src/perk/prompts.py`` → ``other``).
    """
    normalized = path.replace("\\", "/")
    if "docs/learned/" in normalized:
        return "docs/learned/"
    directory_segments = normalized.split("/")[:-1]
    if "skills" in directory_segments:
        return "skills/"
    if "prompts" in directory_segments:
        return "prompts/"
    return "other"


def _kind_label(entry: SessionEntry) -> str:
    """The kind-row label: ``message:<role>`` for message entries (missing role → ``?``);
    ``<kind>:<custom_type>`` for custom entries carrying one (mirroring the normalize
    pipeline's boilerplate-digest labels); bare ``kind`` otherwise."""
    if entry.kind == "message":
        return f"message:{entry.role if entry.role is not None else '?'}"
    if entry.custom_type is not None:
        return f"{entry.kind}:{entry.custom_type}"
    return entry.kind


def _is_tool_result(entry: SessionEntry) -> bool:
    return entry.kind == "message" and entry.role == "toolResult"


def _rows(counts: Counter[str], chars: Counter[str]) -> list[tuple[str, int, int]]:
    """Deterministic row ordering: chars-desc, tie label-asc."""
    return sorted(
        ((label, counts[label], chars[label]) for label in counts),
        key=lambda row: (-row[2], row[0]),
    )


def _read_paths_by_result_index(parsed: ParsedSession) -> dict[int, str | None]:
    """result_index → the paired ``read`` call's ``path`` argument (``None`` when the
    decoded args carry no string ``path``). An unpaired read result is absent."""
    executions, _pending = pair_executions(parsed, "read")
    out: dict[int, str | None] = {}
    for ex in executions:
        path = ex.args.get("path")
        out[ex.result_index] = path if isinstance(path, str) else None
    return out


def attribute_session(parsed: ParsedSession, *, source: str) -> SessionAttribution:
    """Attribute one parsed session's transcript composition (pure; deterministic)."""
    kind_counts: Counter[str] = Counter()
    kind_chars: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    tool_chars: Counter[str] = Counter()
    for entry in parsed.entries:
        label = _kind_label(entry)
        kind_counts[label] += 1
        kind_chars[label] += entry.raw_chars
        if _is_tool_result(entry):
            tool = entry.tool_name if entry.tool_name is not None else _UNKNOWN_TOOL
            tool_counts[tool] += 1
            tool_chars[tool] += entry.raw_chars

    read_paths = _read_paths_by_result_index(parsed)
    class_counts: Counter[str] = Counter()
    class_chars: Counter[str] = Counter()
    for entry in parsed.entries:
        if not _is_tool_result(entry) or entry.tool_name != "read":
            continue
        if entry.index in read_paths:
            path = read_paths[entry.index]
            read_class = classify_read_path(path) if path is not None else "unresolved"
        else:
            read_class = "unresolved"  # an unpaired read result
        class_counts[read_class] += 1
        class_chars[read_class] += entry.raw_chars

    results = [e for e in parsed.entries if _is_tool_result(e)]
    results.sort(key=lambda e: (-e.raw_chars, e.index))
    top = tuple(
        TopResult(
            index=entry.index,
            tool=entry.tool_name if entry.tool_name is not None else _UNKNOWN_TOOL,
            chars=entry.raw_chars,
            is_error=entry.is_error,
            path=read_paths.get(entry.index) if entry.tool_name == "read" else None,
        )
        for entry in results[:TOP_RESULTS]
    )

    on_branch_ids = {id(e) for e in select_active_branch(parsed.entries)}
    off_branch = [e for e in parsed.entries if id(e) not in on_branch_ids]

    return SessionAttribution(
        source=source,
        total_entries=len(parsed.entries),
        total_chars=sum(e.raw_chars for e in parsed.entries),
        header_chars=parsed.header.raw_chars if parsed.header is not None else 0,
        malformed_lines=parsed.malformed_lines,
        malformed_chars=parsed.malformed_chars,
        off_branch_entries=len(off_branch),
        off_branch_chars=sum(e.raw_chars for e in off_branch),
        kinds=tuple(
            KindRow(label=k, entries=n, chars=c) for k, n, c in _rows(kind_counts, kind_chars)
        ),
        tools=tuple(
            ToolRow(tool=k, entries=n, chars=c) for k, n, c in _rows(tool_counts, tool_chars)
        ),
        read_classes=tuple(
            ReadClassRow(read_class=rc, entries=class_counts[rc], chars=class_chars[rc])
            for rc in READ_CLASSES
        ),
        top_results=top,
    )


# -------------------------------------------------------------------- serialize edge


class KindRowOut(OutputModel):
    label: str
    entries: int
    chars: int


class ToolRowOut(OutputModel):
    tool: str
    entries: int
    chars: int


class ReadClassRowOut(OutputModel):
    read_class: str
    entries: int
    chars: int


class TopResultOut(OutputModel):
    index: int
    tool: str
    chars: int
    is_error: bool
    path: str | None


class SessionAttributionOut(OutputModel):
    source: str
    total_entries: int
    total_chars: int
    header_chars: int
    malformed_lines: int
    malformed_chars: int
    off_branch_entries: int
    off_branch_chars: int
    kinds: tuple[KindRowOut, ...]
    tools: tuple[ToolRowOut, ...]
    read_classes: tuple[ReadClassRowOut, ...]
    top_results: tuple[TopResultOut, ...]


class AttributionReportOut(OutputModel):
    """The ``--json`` envelope for a successful attribution run.

    All ``chars`` values are Python code points of raw JSONL lines (decoded, newlines
    excluded). ``total_chars`` covers the entries; the whole file reconciles as
    ``total_chars + header_chars + malformed_chars`` (parser-skipped whitespace-only
    lines excepted). ``index`` values are the read edge's file-order entry indices
    (header excluded).
    """

    success: bool
    error_type: str | None
    sessions: tuple[SessionAttributionOut, ...]

    @classmethod
    def from_domain(cls, report: AttributionReport) -> "AttributionReportOut":
        return cls(
            success=True,
            error_type=None,
            sessions=tuple(
                SessionAttributionOut(
                    source=session.source,
                    total_entries=session.total_entries,
                    total_chars=session.total_chars,
                    header_chars=session.header_chars,
                    malformed_lines=session.malformed_lines,
                    malformed_chars=session.malformed_chars,
                    off_branch_entries=session.off_branch_entries,
                    off_branch_chars=session.off_branch_chars,
                    kinds=tuple(
                        KindRowOut(label=r.label, entries=r.entries, chars=r.chars)
                        for r in session.kinds
                    ),
                    tools=tuple(
                        ToolRowOut(tool=r.tool, entries=r.entries, chars=r.chars)
                        for r in session.tools
                    ),
                    read_classes=tuple(
                        ReadClassRowOut(read_class=r.read_class, entries=r.entries, chars=r.chars)
                        for r in session.read_classes
                    ),
                    top_results=tuple(
                        TopResultOut(
                            index=t.index,
                            tool=t.tool,
                            chars=t.chars,
                            is_error=t.is_error,
                            path=t.path,
                        )
                        for t in session.top_results
                    ),
                )
                for session in report.sessions
            ),
        )
