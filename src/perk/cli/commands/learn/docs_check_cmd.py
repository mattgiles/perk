"""``perk learn docs-check`` — verify the learned-docs navigation is current (+ advisory hygiene).

Read-only. ``require_repo`` only (no GitHub/config). **Freshness** gates the exit (each generated
artifact's marked region must match a fresh render); **hygiene** (missing frontmatter,
copied-source-looking code blocks, dup-``read_when``/stale-pointer/broken-link facts reused from
``docs_scan``) is
advisory — printed, never gating. Exit ``0`` fresh · ``1`` stale · ``2`` not-a-repo (D5).
"""

import click

from perk.boundary import OutputModel
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_scan import BrokenDocPath, DuplicateGroup, StalePointer
from perk.learn.docs_sync import DocsCheckReport, SourceCodeBlock, check_docs
from perk.substrate.output import user_output


@click.command("docs-check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def docs_check_learn(ctx: click.Context, *, as_json: bool) -> None:
    """Verify the learned-docs navigation is current (read-only; advisory hygiene).

    \b
    Freshness gates the exit (0 fresh · 1 stale); hygiene findings always print but never change a
    fresh exit. Run `perk learn docs-sync` to regenerate when stale.
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
    if not report.fresh:
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


class DocsCheckOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`DocsCheckReport` (order load-bearing)."""

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
        )


def _render_human(report: DocsCheckReport) -> None:
    if report.fresh:
        user_output(click.style("docs-check: fresh", fg="green") + " — generated artifacts current")
    else:
        user_output(
            click.style("docs-check: STALE", fg="red")
            + f" — {', '.join(report.stale_files)} (run `perk learn docs-sync`)"
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
