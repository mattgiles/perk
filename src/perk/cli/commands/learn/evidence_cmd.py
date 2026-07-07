"""`perk learn evidence --json` — gather a landed plan's session-grounded evidence bundle.

The first consumer of the cross-run session resolver (`perk/learn/sessions.py`) + the session-export
seam (`perk/learn/export.py`). Reads the local `cache.plan-ref` (no positional arg, mirroring
`perk learn capture` / `perk pr review-context`), resolves the plan + PR + planning/implementation
session JSONLs + a basic existing-docs inventory, materializes the artifacts into a worktree scratch
dir, and emits a stable bundle manifest. A learn-docs consolidation plan (non-empty plan-header
`consumed_learn`) returns a stable skip up front.

Each source degrades independently — one missing/ambiguous source never fails the command. Exit
codes: 0 ok (skip OR gathered manifest) · 1 no plan-ref / invalid · 2 not-a-repo.
"""

import json
from pathlib import Path

import click

from perk.boundary import OutputModel
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_scan import (
    BrokenDocPath,
    DocFindings,
    DuplicateGroup,
    StalePointer,
)
from perk.learn.evidence import DocEntry, EvidenceBundle, EvidenceSource, gather_evidence
from perk.learn.normalize import (
    BoilerplateDigest,
    RenderReport,
    SessionReport,
    render_evidence,
)
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@click.command("evidence")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable manifest to stdout.")
@click.option(
    "--render",
    "do_render",
    is_flag=True,
    help="Normalize the found session JSONLs into bounded, untrusted-DATA-fenced Markdown chunks.",
)
@click.pass_context
def evidence_learn(ctx: click.Context, *, as_json: bool, do_render: bool) -> None:
    """Gather a landed plan's session-grounded evidence bundle (read-only; the /learn cold door).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    With --render, the found session JSONLs are projected into bounded fenced chunks under the
    bundle's chunks/ dir and a normalization report rides the --json envelope's `render` field.
    """
    try:
        repo_root = require_repo(ctx)
        plan_ref = cache.read_plan_ref(repo_root)
        if plan_ref is None:
            raise UserFacingCliError(
                "No saved plan in this worktree\nRun /plan-save then perk implement first.",
                error_type="no_plan_ref",
            )
        bundle = gather_evidence(repo_root, plan_ref)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    render = _maybe_render(repo_root, bundle) if do_render else None
    payload = EvidenceBundleOut.from_domain(bundle, render=render).model_dump(mode="json")

    # Self-contained bundle: write the full manifest (the same payload as `--json` stdout, including
    # `render`) into the bundle dir so the analyst children can `read` it (they cannot read the
    # door's stdout). Written unconditionally on a materialized bundle (independent of `--json`);
    # deterministic (the envelope carries no wall-clock). No write on a skip (`bundle_dir is None`).
    if bundle.bundle_dir is not None and not bundle.skipped:
        manifest_path = repo_root / bundle.bundle_dir / "manifest.json"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    if as_json:
        machine_output(json.dumps(payload))
    else:
        _render_human(bundle, render)


_SESSION_CATEGORIES = ("planning-session", "implementation-session")


def _maybe_render(repo_root: Path, bundle: EvidenceBundle) -> RenderReport | None:
    """Project the bundle's found session sources into bounded chunks; ``None`` for a skipped
    bundle (a learn-docs plan) or one with no materialized bundle dir."""
    if bundle.skipped or bundle.bundle_dir is None:
        return None
    sessions = tuple(
        (f"{s.category}/{s.label}", s.artifact)
        for s in bundle.sources
        if s.category in _SESSION_CATEGORIES and s.status == "found" and s.artifact is not None
    )
    return render_evidence(repo_root, repo_root / bundle.bundle_dir, sessions)


class EvidenceSourceOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`EvidenceSource` (order load-bearing)."""

    category: str
    label: str
    status: str
    artifact: str | None
    detail: str | None

    @classmethod
    def from_domain(cls, source: EvidenceSource) -> "EvidenceSourceOut":
        return cls(
            category=source.category,
            label=source.label,
            status=source.status,
            artifact=source.artifact,
            detail=source.detail,
        )


class DocEntryOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`DocEntry` (order load-bearing)."""

    kind: str
    path: str
    title: str | None
    snippet: str | None

    @classmethod
    def from_domain(cls, entry: DocEntry) -> "DocEntryOut":
        return cls(kind=entry.kind, path=entry.path, title=entry.title, snippet=entry.snippet)


class StalePointerOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`StalePointer` (order load-bearing)."""

    doc: str
    pointer: str
    reason: str

    @classmethod
    def from_domain(cls, ptr: StalePointer) -> "StalePointerOut":
        return cls(doc=ptr.doc, pointer=ptr.pointer, reason=ptr.reason)


class BrokenDocPathOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`BrokenDocPath` (order load-bearing)."""

    doc: str
    target: str

    @classmethod
    def from_domain(cls, broken: BrokenDocPath) -> "BrokenDocPathOut":
        return cls(doc=broken.doc, target=broken.target)


class DuplicateGroupOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`DuplicateGroup` (order load-bearing)."""

    basis: str
    key: str
    docs: tuple[str, ...]

    @classmethod
    def from_domain(cls, group: DuplicateGroup) -> "DuplicateGroupOut":
        return cls(basis=group.basis, key=group.key, docs=group.docs)


class DocFindingsOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`DocFindings` (order load-bearing)."""

    stale_pointers: tuple[StalePointerOut, ...]
    broken_doc_paths: tuple[BrokenDocPathOut, ...]
    duplicate_groups: tuple[DuplicateGroupOut, ...]

    @classmethod
    def from_domain(cls, findings: DocFindings) -> "DocFindingsOut":
        return cls(
            stale_pointers=tuple(StalePointerOut.from_domain(s) for s in findings.stale_pointers),
            broken_doc_paths=tuple(
                BrokenDocPathOut.from_domain(b) for b in findings.broken_doc_paths
            ),
            duplicate_groups=tuple(
                DuplicateGroupOut.from_domain(d) for d in findings.duplicate_groups
            ),
        )


class BoilerplateDigestOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`BoilerplateDigest` (order load-bearing)."""

    label: str
    count: int

    @classmethod
    def from_domain(cls, digest: BoilerplateDigest) -> "BoilerplateDigestOut":
        return cls(label=digest.label, count=digest.count)


class SessionReportOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`SessionReport` (order load-bearing)."""

    role: str
    source: str
    entries_read: int
    entries_kept: int
    entries_pruned: int
    malformed_lines: int
    duplicate_groups: int
    truncations: int
    boilerplate: tuple[BoilerplateDigestOut, ...]
    chunk_paths: tuple[str, ...]

    @classmethod
    def from_domain(cls, report: SessionReport) -> "SessionReportOut":
        return cls(
            role=report.role,
            source=report.source,
            entries_read=report.entries_read,
            entries_kept=report.entries_kept,
            entries_pruned=report.entries_pruned,
            malformed_lines=report.malformed_lines,
            duplicate_groups=report.duplicate_groups,
            truncations=report.truncations,
            boilerplate=tuple(BoilerplateDigestOut.from_domain(b) for b in report.boilerplate),
            chunk_paths=report.chunk_paths,
        )


class RenderReportOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`RenderReport` (order load-bearing)."""

    sessions: tuple[SessionReportOut, ...]

    @classmethod
    def from_domain(cls, report: RenderReport) -> "RenderReportOut":
        return cls(sessions=tuple(SessionReportOut.from_domain(s) for s in report.sessions))


class EvidenceBundleOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`EvidenceBundle` (order load-bearing).

    Always serializes the full shape (no ``exclude_unset``) so a machine consumer sees stable keys
    (absent values render ``null``) — matching the ``LearnCaptureOut`` full-dump convention. The
    ``render`` field is declared LAST and is ``null`` unless ``--render`` was passed.
    """

    success: bool
    error_type: str | None
    message: str | None
    skipped: bool
    skip_reason: str | None
    plan_id: str | None
    bundle_dir: str | None
    sources: tuple[EvidenceSourceOut, ...]
    existing_docs: tuple[DocEntryOut, ...]
    docs_findings: DocFindingsOut
    render: RenderReportOut | None = None

    @classmethod
    def from_domain(
        cls, bundle: EvidenceBundle, *, render: RenderReport | None = None
    ) -> "EvidenceBundleOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            skipped=bundle.skipped,
            skip_reason=bundle.skip_reason,
            plan_id=bundle.plan_id,
            bundle_dir=bundle.bundle_dir,
            sources=tuple(EvidenceSourceOut.from_domain(s) for s in bundle.sources),
            existing_docs=tuple(DocEntryOut.from_domain(d) for d in bundle.existing_docs),
            docs_findings=DocFindingsOut.from_domain(bundle.docs_findings),
            render=None if render is None else RenderReportOut.from_domain(render),
        )


def _render_human(bundle: EvidenceBundle, render: RenderReport | None = None) -> None:
    if bundle.skipped:
        user_output(click.style("learn evidence skipped", dim=True) + f" — {bundle.skip_reason}")
        return
    by_category: dict[str, list[EvidenceSource]] = {}
    for source in bundle.sources:
        by_category.setdefault(source.category, []).append(source)
    plan_status = _first_status(by_category, "plan")
    pr_status = _first_status(by_category, "pr")
    planning = by_category.get("planning-session", [])
    planning_summary = "/".join(s.status for s in planning) or "missing"
    impl_runs = len(
        {
            s.label.split("/")[0]
            for s in by_category.get("implementation-session", [])
            if s.label != "(none)"
        }
    )
    docs = len(bundle.existing_docs)
    findings = bundle.docs_findings
    user_output(
        f"plan {plan_status}, pr {pr_status}, planning {planning_summary}, "
        f"{impl_runs} impl run(s), docs: {docs} "
        f"(stale-ptr: {len(findings.stale_pointers)}, "
        f"broken-link: {len(findings.broken_doc_paths)}, "
        f"dup-groups: {len(findings.duplicate_groups)})"
    )
    if render is not None:
        for report in render.sessions:
            user_output(
                f"render: {report.role} kept {report.entries_kept}/{report.entries_read} "
                f"({report.duplicate_groups} dup, {report.truncations} trunc) → "
                f"{len(report.chunk_paths)} chunk(s)"
            )


def _first_status(by_category: dict[str, list[EvidenceSource]], category: str) -> str:
    entries = by_category.get(category, [])
    return entries[0].status if entries else "missing"
