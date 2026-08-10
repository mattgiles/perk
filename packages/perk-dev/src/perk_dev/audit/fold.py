"""The judgment fold: merge the wave's ``verdicts.json`` into the deterministic report.

``perk-dev audit judge`` materializes a coherent bundle (``deterministic.json`` +
``manifest.json`` + ``packets/``) and launches the seeded orchestrator, whose
``run_audit_wave`` call writes ``<bundle>/verdicts.json`` (the TS-written, Python-folded
bridge artifact — contracts.md §8.49). This module reads the three bundle artifacts back
through lenient boundary models (parse → frozen domain → explicit ``validate()``, the
house pattern), then folds the lanes into the deterministic report's **replaceable**
cells: per judgment expectation, only cells with ``status == "unchecked"`` and
``reason == "judgment-tier"`` are replaceable — the runner's vintage-before-tier
precedence means a judgment expectation can carry ``not-applicable`` cells, and those
are preserved untouched. Judgment verdicts are **leads, not proofs**: a ``violated``
lead keeps the deterministic invariant (≥1 citation; a cite-less claim degrades to
``unchecked``/``auditor-unclear``) and its detail names itself a lead.

Fold identity is ``(expectation_id, session_path)`` — ``session_path`` is the census's
unique session identity (basenames are NOT globally unique across encoded session dirs).
Every degradation lands honestly as an ``unchecked`` cell with a fold-tier reason
(``lane-failed`` / ``auditor-unclear`` / ``unboundable`` / ``not-sampled``, plus the
manifest's re-parse arms mapping onto the existing ``unparsed``/``malformed``); a lane
matching no replaceable cell is ignored with a warning on the returned warnings channel.

Pure over its inputs after the load edge: ``fold_report`` does no I/O; the ``load_*``
readers raise :class:`BundleError` (the CLI's ``bad_bundle`` arm) naming the artifact and
its producing command.
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path

from perk.boundary import LenientParseModel, ValidationError
from perk_dev.audit.bounding import PAIR_STATUSES
from perk_dev.audit.runner import (
    UNCHECKED_REASONS,
    VERDICTS,
    AuditReport,
    Cell,
    ExpectationResult,
)

# The verdicts.json lane-status trio (the TS wave tool's vocabulary — contracts.md §8.49).
LANE_STATUSES: tuple[str, ...] = ("report", "lane-failed", "malformed-report")
# The auditor verdict/confidence enums (the AUDIT_VERDICT_SCHEMA vocabulary).
LANE_VERDICTS: tuple[str, ...] = ("satisfied", "violated", "unclear")
LANE_CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")


class BundleError(Exception):
    """A ``bad_bundle`` failure: the message names the artifact + the producing command."""


# ------------------------------------------------------------------- boundary models


class _CellIn(LenientParseModel):
    session_basename: str
    session_path: str
    status: str
    reason: str | None = None
    vintage_version: str | None = None
    vintage_basis: str
    entries: tuple[int, ...] = ()
    detail: str = ""


class _ExpectationResultIn(LenientParseModel):
    id: str
    kind: str
    tier: str
    applies_to: tuple[str, ...] = ()
    exercising: int
    not_exercised: bool
    status_counts: dict[str, int]
    cells: tuple[_CellIn, ...] = ()


class _DeterministicIn(LenientParseModel):
    """The ``deterministic.json`` envelope (the ``audit run`` ``AuditReportOut`` shape)."""

    success: bool
    error_type: str | None = None
    sessions_root: str
    main_root: str
    worktree_root: str
    confirmed_sessions: int
    deterministic_count: int
    judgment_count: int
    totals: dict[str, int]
    not_exercised: tuple[str, ...] = ()
    results: tuple[_ExpectationResultIn, ...] = ()


class _ManifestPairIn(LenientParseModel):
    expectation_id: str
    session_basename: str
    session_path: str
    status: str
    detail: str = ""


class _ManifestExpectationIn(LenientParseModel):
    id: str
    pairs: tuple[_ManifestPairIn, ...] = ()


class _ManifestIn(LenientParseModel):
    """The ``manifest.json`` slice the fold consumes (pair statuses + details)."""

    success: bool
    error_type: str | None = None
    results: tuple[_ManifestExpectationIn, ...] = ()


class _VerdictLaneIn(LenientParseModel):
    expectation_id: str
    session_basename: str
    session_path: str
    status: str
    verdict: str | None = None
    confidence: str | None = None
    citations: tuple[int, ...] = ()
    rationale: str | None = None
    detail: str = ""


class _VerdictsIn(LenientParseModel):
    """The ``verdicts.json`` shape the TS wave tool writes (contracts.md §8.49)."""

    bundle_dir: str
    flow: str
    lanes: tuple[_VerdictLaneIn, ...] = ()


# --------------------------------------------------------------------------- domain


@dataclass(frozen=True)
class ManifestPair:
    """One (expectation x session) bounding outcome, as the fold consumes it."""

    expectation_id: str
    session_basename: str
    session_path: str
    status: str
    detail: str


@dataclass(frozen=True)
class BundleManifest:
    """The manifest slice the fold consumes: pairs keyed per expectation."""

    results: tuple[tuple[str, tuple[ManifestPair, ...]], ...]


@dataclass(frozen=True)
class VerdictLane:
    """One planned auditor lane's recorded outcome from ``verdicts.json``."""

    expectation_id: str
    session_basename: str
    session_path: str
    status: str
    verdict: str | None
    confidence: str | None
    citations: tuple[int, ...]
    rationale: str | None
    detail: str


@dataclass(frozen=True)
class BundleVerdicts:
    """The parsed ``verdicts.json``: the wave's per-lane outcomes."""

    bundle_dir: str
    flow: str
    lanes: tuple[VerdictLane, ...]


# ------------------------------------------------------------------------ load edge

_JUDGE_HINT = "run `perk-dev audit judge` first"
_WAVE_HINT = "the wave never ran — the seeded session writes verdicts.json via run_audit_wave"


def _read_json(bundle_dir: Path, name: str, hint: str) -> object:
    path = bundle_dir / name
    if not path.exists():
        raise BundleError(f"{name} missing under {bundle_dir} — {hint}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"{name} unreadable/unparseable ({exc}) — {hint}") from exc


def load_deterministic(bundle_dir: Path) -> AuditReport:
    """Read + validate ``deterministic.json`` into the runner's report domain."""
    raw = _read_json(bundle_dir, "deterministic.json", _JUDGE_HINT)
    try:
        parsed = _DeterministicIn.model_validate(raw)
    except ValidationError as exc:
        raise BundleError(f"deterministic.json ill-shaped ({exc}) — {_JUDGE_HINT}") from exc
    report = AuditReport(
        sessions_root=parsed.sessions_root,
        main_root=parsed.main_root,
        worktree_root=parsed.worktree_root,
        confirmed_sessions=parsed.confirmed_sessions,
        deterministic_count=parsed.deterministic_count,
        judgment_count=parsed.judgment_count,
        results=tuple(
            ExpectationResult(
                id=result.id,
                kind=result.kind,
                tier=result.tier,
                applies_to=result.applies_to,
                exercising=result.exercising,
                cells=tuple(
                    Cell(
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
                status_counts=dict(result.status_counts),
                not_exercised=result.not_exercised,
            )
            for result in parsed.results
        ),
        totals=dict(parsed.totals),
        not_exercised=parsed.not_exercised,
    )
    findings = _validate_deterministic(parsed.success, report)
    if findings:
        raise BundleError(f"deterministic.json invalid: {'; '.join(findings)} — {_JUDGE_HINT}")
    return report


def load_manifest(bundle_dir: Path) -> BundleManifest:
    """Read + validate the ``manifest.json`` slice the fold consumes."""
    raw = _read_json(bundle_dir, "manifest.json", _JUDGE_HINT)
    try:
        parsed = _ManifestIn.model_validate(raw)
    except ValidationError as exc:
        raise BundleError(f"manifest.json ill-shaped ({exc}) — {_JUDGE_HINT}") from exc
    manifest = BundleManifest(
        results=tuple(
            (
                result.id,
                tuple(
                    ManifestPair(
                        expectation_id=pair.expectation_id,
                        session_basename=pair.session_basename,
                        session_path=pair.session_path,
                        status=pair.status,
                        detail=pair.detail,
                    )
                    for pair in result.pairs
                ),
            )
            for result in parsed.results
        ),
    )
    findings = _validate_manifest(parsed.success, manifest)
    if findings:
        raise BundleError(f"manifest.json invalid: {'; '.join(findings)} — {_JUDGE_HINT}")
    return manifest


def load_verdicts(bundle_dir: Path) -> BundleVerdicts:
    """Read + validate ``verdicts.json`` against the folded bundle's identity."""
    raw = _read_json(bundle_dir, "verdicts.json", _WAVE_HINT)
    try:
        parsed = _VerdictsIn.model_validate(raw)
    except ValidationError as exc:
        raise BundleError(f"verdicts.json ill-shaped ({exc}) — {_WAVE_HINT}") from exc
    verdicts = BundleVerdicts(
        bundle_dir=parsed.bundle_dir,
        flow=parsed.flow,
        lanes=tuple(
            VerdictLane(
                expectation_id=lane.expectation_id,
                session_basename=lane.session_basename,
                session_path=lane.session_path,
                status=lane.status,
                verdict=lane.verdict,
                confidence=lane.confidence,
                citations=lane.citations,
                rationale=lane.rationale,
                detail=lane.detail,
            )
            for lane in parsed.lanes
        ),
    )
    findings = _validate_verdicts(verdicts, bundle_dir)
    if findings:
        raise BundleError(f"verdicts.json invalid: {'; '.join(findings)} — {_WAVE_HINT}")
    return verdicts


# --------------------------------------------------------------- content validation


def _validate_deterministic(success: bool, report: AuditReport) -> list[str]:
    """Enumerated invariants over the parsed deterministic report (findings, not raises)."""
    findings: list[str] = []
    if not success:
        findings.append("success header is not true (a failure envelope is not a report)")
    for result in report.results:
        seen: set[str] = set()
        for cell in result.cells:
            if cell.status not in VERDICTS:
                findings.append(f"{result.id}: unknown cell status '{cell.status}'")
            if cell.reason is not None and cell.reason not in UNCHECKED_REASONS:
                findings.append(f"{result.id}: unknown unchecked reason '{cell.reason}'")
            if cell.session_path in seen:
                findings.append(
                    f"{result.id}: duplicate cell identity for session {cell.session_path}"
                )
            seen.add(cell.session_path)
    return findings


def _validate_manifest(success: bool, manifest: BundleManifest) -> list[str]:
    """Enumerated invariants over the parsed manifest slice (findings, not raises)."""
    findings: list[str] = []
    if not success:
        findings.append("success header is not true (a failure envelope is not a manifest)")
    seen: set[tuple[str, str]] = set()
    for expectation_id, pairs in manifest.results:
        for pair in pairs:
            if pair.status not in PAIR_STATUSES:
                findings.append(f"{expectation_id}: unknown pair status '{pair.status}'")
            key = (pair.expectation_id, pair.session_path)
            if key in seen:
                findings.append(
                    f"duplicate pair identity {pair.expectation_id} x {pair.session_path}"
                )
            seen.add(key)
    return findings


def _validate_verdicts(verdicts: BundleVerdicts, bundle_dir: Path) -> list[str]:
    """Enumerated invariants over the parsed verdicts file (findings, not raises)."""
    findings: list[str] = []
    if verdicts.flow != "audit":
        findings.append(f"flow is '{verdicts.flow}', expected 'audit'")
    if verdicts.bundle_dir != str(bundle_dir):
        findings.append(
            f"bundle_dir is '{verdicts.bundle_dir}', expected '{bundle_dir}' "
            "(a copied/foreign verdicts file must never fold into this bundle)"
        )
    seen: set[tuple[str, str]] = set()
    for lane in verdicts.lanes:
        if lane.status not in LANE_STATUSES:
            findings.append(f"{lane.expectation_id}: unknown lane status '{lane.status}'")
        if lane.verdict is not None and lane.verdict not in LANE_VERDICTS:
            findings.append(f"{lane.expectation_id}: unknown verdict '{lane.verdict}'")
        if lane.confidence is not None and lane.confidence not in LANE_CONFIDENCES:
            findings.append(f"{lane.expectation_id}: unknown confidence '{lane.confidence}'")
        if lane.status == "report" and (lane.verdict is None or lane.confidence is None):
            findings.append(
                f"{lane.expectation_id}: a 'report' lane must carry a verdict and a confidence"
            )
        key = (lane.expectation_id, lane.session_path)
        if key in seen:
            findings.append(f"duplicate lane identity {lane.expectation_id} x {lane.session_path}")
        seen.add(key)
    return findings


# ------------------------------------------------------------------------- the fold


def _fold_cell(cell: Cell, pair: ManifestPair, lane: VerdictLane | None) -> Cell:
    """Fold one replaceable ``judgment-tier`` cell from its manifest pair + wave lane.

    Every arm preserves the deterministic cell's identity + vintage fields; only
    ``status``/``reason``/``entries``/``detail`` are replaced. The violated⇒citations
    invariant is preserved by degrading a cite-less ``violated`` lead to
    ``unchecked``/``auditor-unclear`` (named as such).
    """

    def folded(
        status: str,
        *,
        reason: str | None = None,
        entries: tuple[int, ...] = (),
        detail: str = "",
    ) -> Cell:
        return replace(cell, status=status, reason=reason, entries=entries, detail=detail)

    if pair.status != "packetized":
        # The manifest degradations: unboundable/not-sampled map onto the fold-tier
        # reasons; unparsed/malformed reuse the runner's existing reasons.
        return folded("unchecked", reason=pair.status, detail=pair.detail)
    if lane is None:
        return folded("unchecked", reason="lane-failed", detail="no verdict recorded for this pair")
    if lane.status != "report":
        return folded("unchecked", reason="lane-failed", detail=lane.detail)
    lead = f"(confidence {lane.confidence}): {lane.rationale or ''}"
    if lane.verdict == "satisfied":
        return folded("satisfied", entries=lane.citations, detail=f"judgment lead {lead}")
    if lane.verdict == "violated" and len(lane.citations) >= 1:
        return folded("violated", entries=lane.citations, detail=f"judgment lead, not proof {lead}")
    if lane.verdict == "violated":
        return folded(
            "unchecked",
            reason="auditor-unclear",
            detail=f"cite-less violation claim — degraded to unchecked {lead}",
        )
    return folded("unchecked", reason="auditor-unclear", detail=f"auditor unclear {lead}")


def fold_report(
    deterministic: AuditReport,
    manifest: BundleManifest,
    verdicts: BundleVerdicts,
) -> tuple[AuditReport, tuple[str, ...]]:
    """Fold the wave's verdict lanes into the deterministic report (pure; no I/O).

    Keyed by ``(expectation_id, session_path)``. Only ``unchecked``/``judgment-tier``
    cells are replaceable; everything else — deterministic-tier results, vintage-gated
    ``not-applicable`` cells, ``not_exercised`` rollups — passes through untouched.
    ``status_counts``/``totals`` are recomputed zero-filled over ``VERDICTS``. The
    second element is the warnings channel: a lane matching no replaceable cell is
    ignored + named there (the caller emits; this core does no I/O).
    """
    pairs_by_key: dict[tuple[str, str], ManifestPair] = {}
    for expectation_id, pairs in manifest.results:
        for pair in pairs:
            pairs_by_key[(expectation_id, pair.session_path)] = pair
    lanes_by_key = {(lane.expectation_id, lane.session_path): lane for lane in verdicts.lanes}

    consumed: set[tuple[str, str]] = set()
    totals = dict.fromkeys(VERDICTS, 0)
    results: list[ExpectationResult] = []
    for result in deterministic.results:
        cells: list[Cell] = []
        for cell in result.cells:
            key = (result.id, cell.session_path)
            replaceable = cell.status == "unchecked" and cell.reason == "judgment-tier"
            pair = pairs_by_key.get(key)
            if not replaceable or pair is None:
                # A filtered-at-judge-time expectation (no manifest entry) or a
                # pair-less cell stays honestly `judgment-tier`.
                cells.append(cell)
                continue
            lane = lanes_by_key.get(key)
            if lane is not None:
                consumed.add(key)
            cells.append(_fold_cell(cell, pair, lane))
        counts = dict.fromkeys(VERDICTS, 0)
        for cell in cells:
            counts[cell.status] += 1
            totals[cell.status] += 1
        results.append(replace(result, cells=tuple(cells), status_counts=counts))

    warnings = tuple(
        f"verdict lane {lane.expectation_id} x {lane.session_path} matches no replaceable "
        "deterministic cell — ignored"
        for lane in verdicts.lanes
        if (lane.expectation_id, lane.session_path) not in consumed
    )
    return (
        replace(deterministic, results=tuple(results), totals=totals),
        warnings,
    )
