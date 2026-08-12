"""``perk learn docs-sync`` — regenerate the learned-docs navigation artifacts.

Derives the ambient routing block (``.pi/APPEND_SYSTEM.md``) + the per-doc catalog table
(``docs/learned/index.md``) from each learned doc's frontmatter (SSOT) — grouped at cluster grain
when the ``docs/learned/clusters.yaml`` registry is present (absent ⇒ the legacy per-doc
rendering). Purely local: ``require_repo`` only (no GitHub/config). Writes only artifacts whose
content changed; ``--dry-run`` previews without writing. An invalid registry refuses loudly and
writes nothing. Exit ``0`` ok · ``1`` invalid registry · ``2`` not-a-repo.
"""

import click

from perk.boundary import OutputModel
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_sync import InvalidClusterRegistry, SyncResult, sync_docs
from perk.substrate.output import user_output


@click.command("docs-sync")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.option("--dry-run", is_flag=True, help="Compute changes + report them; write nothing.")
@click.pass_context
def docs_sync_learn(ctx: click.Context, *, as_json: bool, dry_run: bool) -> None:
    """Regenerate docs/learned/index.md + .pi/APPEND_SYSTEM.md from doc frontmatter (local-only).

    \b
    With a docs/learned/clusters.yaml registry the ambient block renders one line per cluster
    (rollup cue + member doc slugs); without it, one line per doc. An invalid registry fails
    (exit 1) and writes nothing.

    \b
    Examples:
      perk learn docs-sync            # regenerate + write the two navigation artifacts
      perk learn docs-sync --dry-run  # report what would change; write nothing
    """
    try:
        repo_root = require_repo(ctx)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
            extra={"dry_run": dry_run},
        )
        return

    result = sync_docs(repo_root, dry_run=dry_run)
    if isinstance(result, InvalidClusterRegistry):
        fail(
            ctx,
            as_json=as_json,
            error_type="invalid_cluster_registry",
            message=result.reason,
            extra={"dry_run": dry_run},
        )
        return
    payload = DocsSyncOut.from_domain(result, dry_run=dry_run).model_dump(mode="json")
    emit(as_json=as_json, payload=payload, render=lambda: _render_human(result, dry_run=dry_run))


class DocsSyncOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`SyncResult` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    written: tuple[str, ...]
    unchanged: tuple[str, ...]
    dry_run: bool

    @classmethod
    def from_domain(cls, result: SyncResult, *, dry_run: bool) -> "DocsSyncOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            written=result.written,
            unchanged=result.unchanged,
            dry_run=dry_run,
        )


def _render_human(result: SyncResult, *, dry_run: bool) -> None:
    verb = "would write" if dry_run else "wrote"
    if result.written:
        user_output(f"docs-sync {verb} {len(result.written)}: {', '.join(result.written)}")
    else:
        user_output(click.style("docs-sync: already current (no changes)", dim=True))
    if result.unchanged:
        user_output(click.style(f"  unchanged: {', '.join(result.unchanged)}", dim=True))
