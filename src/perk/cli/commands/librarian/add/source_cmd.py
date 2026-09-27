"""``perk librarian add source`` — clone (or reuse) a source checkout and record it
(contracts.md §8.75(i)).

Parses the repo-ref, partial-clones into ``source-code/<host>/<org>/<repo>/`` (config-pinned,
hooks disabled), optionally detaches at ``--ref`` and records the entry under the library lock.
Idempotent: a rerun over a valid checkout is ``reused``; a different ``--ref`` re-pins. Every
option is a plain string parsed inside the command so a bad value is a typed ``--json``
refusal, never a Click usage error.

Exit codes: 0 ok · 1 typed refusal / op failure · 2 not-a-repo.
"""

from typing import Literal

import click

from perk.boundary import OutputModel
from perk.cli.commands.librarian.shared import EntryOut, fail_library_error, parse_stale_after
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.library import AddSourceOutcome, LibraryError, add_source
from perk.substrate.output import user_output


class LibrarianAddSourceOut(OutputModel):
    """The ``--json`` envelope of ``perk librarian add source`` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    action: Literal["cloned", "reused", "repinned"]
    entry: EntryOut

    @classmethod
    def from_domain(cls, outcome: AddSourceOutcome) -> "LibrarianAddSourceOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            action=outcome.action,
            entry=EntryOut.from_view(outcome.view),
        )


@click.command("source")
@click.argument("repo_ref")
@click.option("--ref", "pin", default=None, help="Pin the checkout at a tag, branch or commit.")
@click.option("--slug", default=None, help="The entry slug (defaults to the repository name).")
@click.option("--stale-after", default=None, help="Freshness window, e.g. 24h or 7d.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def add_source_cmd(
    ctx: click.Context,
    *,
    repo_ref: str,
    pin: str | None,
    slug: str | None,
    stale_after: str | None,
    as_json: bool,
) -> None:
    """Clone a source repository into the library (or reuse / re-pin its checkout).

    \b
    REPO_REF: <org>/<repo> (GitHub), <host>/<org>/<repo>, https://<host>/<org>/<repo>,
    ssh://[user@]<host>/<org>/<repo>, or git@<host>:<org>/<repo>.
    """
    try:
        window = parse_stale_after(stale_after) if stale_after is not None else None
        repo_root = require_repo(ctx)
        outcome = add_source(repo_root, repo_ref=repo_ref, pin=pin, slug=slug, stale_after=window)
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
        payload=LibrarianAddSourceOut.from_domain(outcome).model_dump(mode="json"),
        render=lambda: _render_human(outcome),
    )


def _render_human(outcome: AddSourceOutcome) -> None:
    entry = outcome.view.entry
    path = outcome.view.absolute_path
    if outcome.action == "repinned":
        user_output(f"repinned {entry.slug} at {entry.ref} → {path}")
        return
    pinned = f" at {entry.ref}" if entry.ref is not None else ""
    user_output(f"{outcome.action} {entry.slug}{pinned} → {path}")
