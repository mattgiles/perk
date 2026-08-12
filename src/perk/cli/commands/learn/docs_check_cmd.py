"""``perk learn docs-check`` — verify the learned-docs navigation is current (+ advisory hygiene).

Read-only. ``require_repo`` only (no GitHub/config). Three categories **gate the exit**: freshness
(each generated artifact's marked region must match a fresh registry-aware render), the per-cue
budget (each ``read_when`` ≤ 200 chars and free of the plain-scalar hazards that silently corrupt
the rendered cue), and — when ``docs/learned/clusters.yaml`` is present — the cluster gates (a
valid registry, every doc's ``cluster`` declared + known, no empty clusters, each rollup ≤ 160
chars). **Hygiene** (missing frontmatter, copied-source-looking code blocks,
dup-``read_when``/stale-pointer/broken-link facts reused from ``docs_scan``) is advisory —
printed, never gating. Exit ``0`` ok · ``1`` stale or cue/cluster violation · ``2`` not-a-repo
(D5).
"""

import click

from perk.boundary import OutputModel
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_scan import BrokenDocPath, DuplicateGroup, StalePointer
from perk.learn.docs_sync import (
    CLUSTER_ROLLUP_MAX_CHARS,
    READ_WHEN_MAX_CHARS,
    ClusterIssue,
    CueHazard,
    DocsCheckReport,
    OverlongCue,
    OverlongRollup,
    SourceCodeBlock,
    check_docs,
)
from perk.substrate.output import user_output


@click.command("docs-check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def docs_check_learn(ctx: click.Context, *, as_json: bool) -> None:
    """Verify the learned-docs navigation is current (read-only; advisory hygiene).

    \b
    Freshness, the per-cue budget (each read_when <= 200 chars, no plain-scalar hazards), and —
    with a docs/learned/clusters.yaml registry — the cluster gates (a valid registry, every doc's
    cluster declared + known, no empty clusters, each rollup <= 160 chars) gate the exit (0 ok ·
    1 stale or cue/cluster violation · 2 not-a-repo); hygiene findings always print but never
    change the exit. Run `perk learn docs-sync` to regenerate when stale.
    """
    try:
        repo_root = require_repo(ctx)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    report = check_docs(repo_root)
    emit(
        as_json=as_json,
        payload=DocsCheckOut.from_domain(report).model_dump(mode="json"),
        render=lambda: _render_human(report),
    )
    gating = (
        not report.fresh
        or report.overlong_cues
        or report.cue_hazards
        or report.registry_error is not None
        or report.cluster_issues
        or report.empty_clusters
        or report.overlong_rollups
    )
    if gating:
        ctx.exit(1)


class SourceCodeBlockOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`SourceCodeBlock` (order load-bearing)."""

    doc: str
    language: str
    lines: int

    @classmethod
    def from_domain(cls, block: SourceCodeBlock) -> "SourceCodeBlockOut":
        return cls(doc=block.doc, language=block.language, lines=block.lines)


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


class OverlongCueOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`OverlongCue` (order load-bearing)."""

    doc: str
    length: int

    @classmethod
    def from_domain(cls, cue: OverlongCue) -> "OverlongCueOut":
        return cls(doc=cue.doc, length=cue.length)


class CueHazardOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`CueHazard` (order load-bearing)."""

    doc: str
    hazard: str

    @classmethod
    def from_domain(cls, hazard: CueHazard) -> "CueHazardOut":
        return cls(doc=hazard.doc, hazard=hazard.hazard)


class ClusterIssueOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`ClusterIssue` (order load-bearing)."""

    doc: str
    cluster: str | None
    problem: str

    @classmethod
    def from_domain(cls, issue: ClusterIssue) -> "ClusterIssueOut":
        return cls(doc=issue.doc, cluster=issue.cluster, problem=issue.problem)


class OverlongRollupOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`OverlongRollup` (order load-bearing)."""

    cluster: str
    length: int

    @classmethod
    def from_domain(cls, rollup: OverlongRollup) -> "OverlongRollupOut":
        return cls(cluster=rollup.cluster, length=rollup.length)


class DocsCheckOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`DocsCheckReport` (order load-bearing).

    Under a non-null ``registry_error`` the freshness comparison was skipped:
    ``fresh``/``stale_files`` carry the non-compared defaults (``true``/``[]``), never a verified
    status — ``registry_error`` is the authoritative gating signal.
    """

    success: bool
    error_type: str | None
    message: str | None
    fresh: bool
    stale_files: tuple[str, ...]
    missing_frontmatter: tuple[str, ...]
    source_code_blocks: tuple[SourceCodeBlockOut, ...]
    duplicate_read_when: tuple[DuplicateGroupOut, ...]
    stale_pointers: tuple[StalePointerOut, ...]
    broken_doc_paths: tuple[BrokenDocPathOut, ...]
    overlong_cues: tuple[OverlongCueOut, ...]
    cue_hazards: tuple[CueHazardOut, ...]
    registry_error: str | None
    cluster_issues: tuple[ClusterIssueOut, ...]
    empty_clusters: tuple[str, ...]
    overlong_rollups: tuple[OverlongRollupOut, ...]

    @classmethod
    def from_domain(cls, report: DocsCheckReport) -> "DocsCheckOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            fresh=report.fresh,
            stale_files=report.stale_files,
            missing_frontmatter=report.missing_frontmatter,
            source_code_blocks=tuple(
                SourceCodeBlockOut.from_domain(b) for b in report.source_code_blocks
            ),
            duplicate_read_when=tuple(
                DuplicateGroupOut.from_domain(g) for g in report.duplicate_read_when
            ),
            stale_pointers=tuple(StalePointerOut.from_domain(s) for s in report.stale_pointers),
            broken_doc_paths=tuple(
                BrokenDocPathOut.from_domain(b) for b in report.broken_doc_paths
            ),
            overlong_cues=tuple(OverlongCueOut.from_domain(c) for c in report.overlong_cues),
            cue_hazards=tuple(CueHazardOut.from_domain(h) for h in report.cue_hazards),
            registry_error=report.registry_error,
            cluster_issues=tuple(ClusterIssueOut.from_domain(i) for i in report.cluster_issues),
            empty_clusters=report.empty_clusters,
            overlong_rollups=tuple(
                OverlongRollupOut.from_domain(r) for r in report.overlong_rollups
            ),
        )


# The one-phrase rendered effect per hazard kind (the closed set on `CueHazard.hazard`).
_HAZARD_EFFECTS = {
    "space-hash": "silently truncates the rendered cue",
    "colon-space": "breaks the frontmatter parse — the cue renders empty",
    "multiline": "breaks the one-line routing grammar",
}


def _render_human(report: DocsCheckReport) -> None:
    if report.registry_error is not None:
        # The freshness comparison was SKIPPED (no valid render to compare against) — never
        # claim the artifacts are current while the registry is broken.
        user_output(
            click.style("docs-check: UNCHECKED", fg="red")
            + " — invalid cluster registry; freshness not compared"
        )
    elif report.fresh:
        user_output(click.style("docs-check: fresh", fg="green") + " — generated artifacts current")
    else:
        user_output(
            click.style("docs-check: STALE", fg="red")
            + f" — {', '.join(report.stale_files)} (run `perk learn docs-sync`)"
        )
    # The per-cue budget/hazard violations (gating, like freshness).
    for cue in report.overlong_cues:
        user_output(
            click.style(
                f"  cue over budget: {cue.doc} — {cue.length} chars "
                f"(max {READ_WHEN_MAX_CHARS}); fix the frontmatter",
                fg="red",
            )
        )
    for hazard in report.cue_hazards:
        effect = _HAZARD_EFFECTS.get(hazard.hazard, "corrupts the rendered cue")
        user_output(
            click.style(
                f"  cue hazard: {hazard.doc} — {hazard.hazard} ({effect}); fix the frontmatter",
                fg="red",
            )
        )
    # The cluster gates (gating, like freshness and the cue budget).
    if report.registry_error is not None:
        user_output(click.style(f"  registry invalid: {report.registry_error}", fg="red"))
    for issue in report.cluster_issues:
        user_output(click.style(f"  cluster {issue.problem}: {issue.doc}", fg="red"))
    for empty in report.empty_clusters:
        user_output(click.style(f"  empty cluster: {empty}", fg="red"))
    for rollup in report.overlong_rollups:
        user_output(
            click.style(
                f"  rollup over budget: {rollup.cluster} — {rollup.length} chars "
                f"(max {CLUSTER_ROLLUP_MAX_CHARS})",
                fg="red",
            )
        )
    # Advisory hygiene (never changes the exit).
    user_output(
        click.style(
            "  hygiene: "
            f"missing-frontmatter: {len(report.missing_frontmatter)}, "
            f"source-code-blocks: {len(report.source_code_blocks)}, "
            f"dup-read_when: {len(report.duplicate_read_when)}, "
            f"stale-ptr: {len(report.stale_pointers)}, "
            f"broken-link: {len(report.broken_doc_paths)}",
            dim=True,
        )
    )
