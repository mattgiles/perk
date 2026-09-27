"""``perk librarian remove`` — drop a library entry (contracts.md §8.74(e)).

Removes the entry from the catalog first, then deletes exactly its leaf entry directory (after a
symlink-component check). A failed deletion leaves an adoptable orphan ``list`` reports.

Exit codes: 0 ok · 1 typed refusal / op failure · 2 not-a-repo.
"""

import click

from perk.boundary import OutputModel
from perk.cli.commands.librarian.shared import fail_library_error
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.library import Kind, LibraryError, RemoveOutcome, remove
from perk.substrate.output import user_output


class LibrarianRemoveOut(OutputModel):
    """The ``--json`` envelope of ``perk librarian remove`` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    slug: str
    kind: Kind
    path: str
    content_removed: bool

    @classmethod
    def from_domain(cls, outcome: RemoveOutcome) -> "LibrarianRemoveOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            slug=outcome.slug,
            kind=outcome.kind,
            path=str(outcome.absolute_path),
            content_removed=outcome.content_removed,
        )


@click.command("remove")
@click.argument("slug")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def remove_library_cmd(ctx: click.Context, *, slug: str, as_json: bool) -> None:
    """Remove a library entry: its catalog record, then its directory."""
    try:
        repo_root = require_repo(ctx)
        outcome = remove(repo_root, slug=slug)
    except LibraryError as exc:
        fail_library_error(ctx, exc, as_json=as_json)
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return
    emit(
        as_json=as_json,
        payload=LibrarianRemoveOut.from_domain(outcome).model_dump(mode="json"),
        render=lambda: _render_human(outcome),
    )


def _render_human(outcome: RemoveOutcome) -> None:
    user_output(f"removed {outcome.slug} ({outcome.kind}) — {outcome.absolute_path}")
