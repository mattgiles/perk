"""The deterministic audit runner: verdict assembly + the report domain + the ``--json`` edge.

Runs on top of the census (which owns corpus identification/coverage; no verdicts) and the
checker registry: for every reported expectation x exercising session, one :class:`Cell`
verdict is assembled in a fixed precedence order —

1. vintage gate positively ``not-applicable`` -> **not-applicable** (a vintage-unknown
   session is checked anyway; its verdict stays visibly discountable via the cell's
   vintage fields);
2. tier ``judgment`` -> **unchecked**, reason ``judgment-tier`` (outside this runner);
3. tier ``deterministic`` with no registered checker -> **unchecked**, reason
   ``no-checker`` (defensive arm — a self-check test pins it unreachable for the
   committed catalog);
4. re-parse with ``parsed.header is None`` -> **unchecked**, reason ``unparsed`` (the
   census's own unreadable predicate: the file was header-confirmed at walk time, so a
   header-less re-parse means the whole-file read failed or the file changed underneath
   us; a present header with zero entries is a legitimately empty session and falls
   through to the checker's precondition arm);
5. ``parsed.malformed_lines > 0`` -> **unchecked**, reason ``malformed`` (a dropped line
   could be the decisive draft/claim/mode/call/result — never a definitive verdict over a
   lossy transcript);
6. else the checker's verdict — **satisfied** / **violated** / **not-exercised** — or
   the checker's own **unchecked** (mapped to reason ``in-flight``: a decisive execution
   is still unpaired, the live-session race — never a definitive absence verdict over an
   unfinished transcript).

An expectation with zero exercising sessions rolls up as **not-exercised** (no cells),
mirroring the census's ``not_exercised`` accounting. Every ``violated`` cell carries >=1
entry-index citation (test-pinned invariant).

Pure/injectable: the census carries the roots; sessions re-parse from
``SessionRecord.path`` (one :class:`ParsedSession` per path, cached across expectations).
Accepted: malformed-line warnings from ``parse_session_jsonl`` can print a second time
for re-parsed files (dev-tool stderr noise).
"""

from dataclasses import dataclass
from pathlib import Path

from perk.boundary import OutputModel
from perk.learn.session_jsonl import ParsedSession, parse_session_jsonl
from perk_dev.audit.checks import CHECKERS
from perk_dev.audit.corpus import Census, SessionRecord
from perk_dev.audit.expectations import Expectation, ExpectationCatalog
from perk_dev.audit.vintage import applicability

# The cell-verdict vocabulary (fixed order — every counts dict is zero-filled over it).
VERDICTS: tuple[str, ...] = (
    "satisfied",
    "violated",
    "not-exercised",
    "not-applicable",
    "unchecked",
)
# The `unchecked` reason vocabulary (assembly-order arms 2-5 above, plus the checker's
# own in-flight arm from arm 6, plus the judgment-fold arms `perk-dev audit fold` writes
# into replaced `judgment-tier` cells: `lane-failed` (a failed/missing auditor lane),
# `auditor-unclear` (an `unclear` verdict or a cite-less `violated` claim), and the
# bundle-manifest degradations `unboundable`/`not-sampled` — see contracts.md §8.49).
UNCHECKED_REASONS: tuple[str, ...] = (
    "judgment-tier",
    "no-checker",
    "unparsed",
    "malformed",
    "in-flight",
    "lane-failed",
    "auditor-unclear",
    "unboundable",
    "not-sampled",
)


@dataclass(frozen=True)
class Cell:
    """One expectation x exercising-session verdict.

    ``reason`` is an ``UNCHECKED_REASONS`` member when ``status == "unchecked"``, else
    ``None``. ``entries`` are ``SessionEntry.index`` citations (file order, header
    excluded). The vintage fields ride every cell so unknown-vintage verdicts stay
    visibly discountable in calibration.
    """

    session_basename: str
    session_path: str
    status: str
    reason: str | None
    vintage_version: str | None
    vintage_basis: str
    entries: tuple[int, ...]
    detail: str


@dataclass(frozen=True)
class ExpectationResult:
    """One expectation's full verdict row: its cells (census session order) plus the
    zero-filled ``VERDICTS``-order status counts."""

    id: str
    kind: str
    tier: str
    applies_to: tuple[str, ...]
    exercising: int
    cells: tuple[Cell, ...]
    status_counts: dict[str, int]
    not_exercised: bool


@dataclass(frozen=True)
class AuditReport:
    """The full audit report: roots, corpus size, per-expectation results (catalog
    order), the zero-filled ``VERDICTS``-order totals, and the not-exercised rollup."""

    sessions_root: str
    main_root: str
    worktree_root: str
    confirmed_sessions: int
    deterministic_count: int
    judgment_count: int
    results: tuple[ExpectationResult, ...]
    totals: dict[str, int]
    not_exercised: tuple[str, ...]


def run_audit(
    *,
    census: Census,
    catalog: ExpectationCatalog,
    expectation_ids: tuple[str, ...],
) -> AuditReport:
    """Assemble the verdict matrix over the census's confirmed sessions.

    ``expectation_ids == ()`` means **all** (the Click ``multiple=True`` default passes
    straight through); a non-empty tuple selects the named subset — duplicates deduped,
    always iterated in catalog order. The CLI has already validated the ids.
    """
    wanted = set(expectation_ids)
    selected = tuple(e for e in catalog.expectations if not wanted or e.id in wanted)

    cache: dict[str, ParsedSession] = {}
    results: list[ExpectationResult] = []
    totals = {verdict: 0 for verdict in VERDICTS}
    not_exercised: list[str] = []
    for expectation in selected:
        applies = set(expectation.applies_to)
        exercising = [
            r for r in census.sessions if applies.intersection(e.trigger for e in r.evidence)
        ]
        cells = tuple(_cell(expectation, record, cache) for record in exercising)
        counts = {verdict: 0 for verdict in VERDICTS}
        for cell in cells:
            counts[cell.status] += 1
            totals[cell.status] += 1
        results.append(
            ExpectationResult(
                id=expectation.id,
                kind=expectation.kind,
                tier=expectation.tier,
                applies_to=expectation.applies_to,
                exercising=len(exercising),
                cells=cells,
                status_counts=counts,
                not_exercised=not exercising,
            )
        )
        if not exercising:
            not_exercised.append(expectation.id)

    return AuditReport(
        sessions_root=census.sessions_root,
        main_root=census.main_root,
        worktree_root=census.worktree_root,
        confirmed_sessions=census.totals.confirmed,
        deterministic_count=sum(1 for e in selected if e.tier == "deterministic"),
        judgment_count=sum(1 for e in selected if e.tier == "judgment"),
        results=tuple(results),
        totals=totals,
        not_exercised=tuple(not_exercised),
    )


def _cell(expectation: Expectation, record: SessionRecord, cache: dict[str, ParsedSession]) -> Cell:
    """One cell verdict, in the module-docstring precedence order."""

    def cell(
        status: str,
        *,
        reason: str | None = None,
        entries: tuple[int, ...] = (),
        detail: str = "",
    ) -> Cell:
        return Cell(
            session_basename=record.basename,
            session_path=record.path,
            status=status,
            reason=reason,
            vintage_version=record.vintage_version,
            vintage_basis=record.vintage_basis,
            entries=entries,
            detail=detail,
        )

    if applicability(expectation.vintage_floor, record.vintage()) == "not-applicable":
        return cell(
            "not-applicable",
            detail=f"session vintage below the {expectation.vintage_floor} floor",
        )
    if expectation.tier == "judgment":
        return cell(
            "unchecked",
            reason="judgment-tier",
            detail="judgment-tier expectation — outside the deterministic runner",
        )
    checker = CHECKERS.get(expectation.id)
    if checker is None:
        return cell(
            "unchecked",
            reason="no-checker",
            detail="deterministic expectation with no registered checker",
        )
    parsed = cache.get(record.path)
    if parsed is None:
        parsed = parse_session_jsonl(Path(record.path))
        cache[record.path] = parsed
    if parsed.header is None:
        return cell(
            "unchecked",
            reason="unparsed",
            detail="the session file could not be re-parsed",
        )
    if parsed.malformed_lines > 0:
        return cell(
            "unchecked",
            reason="malformed",
            detail=(
                f"{parsed.malformed_lines} malformed line(s) — no definitive verdict "
                "over a lossy transcript"
            ),
        )
    result = checker(parsed)
    if result.status == "unchecked":
        return cell("unchecked", reason="in-flight", entries=result.entries, detail=result.detail)
    return cell(result.status, entries=result.entries, detail=result.detail)


# -------------------------------------------------------------------- serialize edge


class CellOut(OutputModel):
    session_basename: str
    session_path: str
    status: str
    reason: str | None
    vintage_version: str | None
    vintage_basis: str
    entries: tuple[int, ...]
    detail: str


class ExpectationResultOut(OutputModel):
    id: str
    kind: str
    tier: str
    applies_to: tuple[str, ...]
    exercising: int
    not_exercised: bool
    status_counts: dict[str, int]
    cells: tuple[CellOut, ...]


class AuditReportOut(OutputModel):
    """The ``--json`` envelope for a successful audit run.

    Cell ``entries`` are the read edge's file-order entry indices (header excluded) —
    ``SessionEntry.index``'s own coordinate system.
    """

    success: bool
    error_type: str | None
    sessions_root: str
    main_root: str
    worktree_root: str
    confirmed_sessions: int
    deterministic_count: int
    judgment_count: int
    totals: dict[str, int]
    not_exercised: tuple[str, ...]
    results: tuple[ExpectationResultOut, ...]

    @classmethod
    def from_domain(cls, report: AuditReport) -> "AuditReportOut":
        return cls(
            success=True,
            error_type=None,
            sessions_root=report.sessions_root,
            main_root=report.main_root,
            worktree_root=report.worktree_root,
            confirmed_sessions=report.confirmed_sessions,
            deterministic_count=report.deterministic_count,
            judgment_count=report.judgment_count,
            totals=report.totals,
            not_exercised=report.not_exercised,
            results=tuple(
                ExpectationResultOut(
                    id=result.id,
                    kind=result.kind,
                    tier=result.tier,
                    applies_to=result.applies_to,
                    exercising=result.exercising,
                    not_exercised=result.not_exercised,
                    status_counts=result.status_counts,
                    cells=tuple(
                        CellOut(
                            session_basename=cell.session_basename,
                            session_path=cell.session_path,
                            status=cell.status,
                            reason=cell.reason,
                            vintage_version=cell.vintage_version,
                            vintage_basis=cell.vintage_basis,
                            entries=cell.entries,
                            detail=cell.detail,
                        )
                        for cell in result.cells
                    ),
                )
                for result in report.results
            ),
        )
