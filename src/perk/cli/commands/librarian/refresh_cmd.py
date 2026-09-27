"""``perk librarian refresh`` — fast-forward a source entry's checkout, or open the docs-refresh
door (contracts.md §8.75(i)/(k)).

Fetches an unpinned source checkout (config-pinned) and fast-forwards it to its default branch
under the library lock; a dirty tree or a HEAD off that branch is skipped, and a pinned entry is
refused with the re-pin hint. Refreshing a documentation mirror is session judgment work
(re-crawl, curate, ``record --publish --replace``): the human form of a docs entry is the
docs-refresh door — it claims a staging directory and launches the refresh session — while the
``--json`` worker refuses it with the typed ``needs_session``.

Exit codes: 0 ok (including the ``skipped_*`` outcomes) · 1 typed refusal / op failure · 2
not-a-repo.
"""

from typing import Literal

import click

from perk.boundary import OutputModel
from perk.cli.commands.librarian.door import launch_docs_session, render_refresh_seed
from perk.cli.commands.librarian.shared import EntryOut, fail_library_error
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.library import (
    LibraryError,
    RefreshOutcome,
    SourceUpstream,
    entry_kind,
    plan_refresh_docs,
    refresh_entry,
)
from perk.substrate.output import user_output


class LibrarianRefreshOut(OutputModel):
    """The ``--json`` envelope of ``perk librarian refresh`` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    action: Literal["fast_forwarded", "up_to_date", "skipped_dirty", "skipped_non_ff"]
    detail: str | None
    previous_head: str | None
    entry: EntryOut

    @classmethod
    def from_domain(cls, outcome: RefreshOutcome) -> "LibrarianRefreshOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            action=outcome.action,
            detail=outcome.detail,
            previous_head=outcome.previous_head,
            entry=EntryOut.from_view(outcome.view),
        )


@click.command("refresh")
@click.argument("slug")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def refresh_library_cmd(ctx: click.Context, *, slug: str, as_json: bool) -> None:
    """Fetch a source entry's checkout and fast-forward it to its default branch.

    On a documentation entry (without --json) this launches the refresh session instead: a
    re-crawl into a fresh staging directory with the prior crawl's scope, curated and published
    over the current revision with `record --publish … --replace`.
    """
    try:
        repo_root = require_repo(ctx)
        if not as_json and entry_kind(repo_root, slug) == "docs":
            plan = plan_refresh_docs(repo_root, slug=slug)
            launch_docs_session(
                ctx,
                plan=plan,
                seed=render_refresh_seed(plan),
                trigger="command:librarian-refresh",
                pi_args=(),
                note=(
                    f"refreshing documentation entry {slug} ({plan.url}) — staging "
                    f"{plan.staging_dir}; launching session"
                ),
            )
            return
        outcome = refresh_entry(repo_root, slug=slug)
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
        payload=LibrarianRefreshOut.from_domain(outcome).model_dump(mode="json"),
        render=lambda: _render_human(outcome),
    )


def _short(sha: str | None) -> str:
    return (sha or "?")[:7]


def _render_human(outcome: RefreshOutcome) -> None:
    entry = outcome.view.entry
    head = entry.upstream.head_sha if isinstance(entry.upstream, SourceUpstream) else None
    if outcome.action == "fast_forwarded":
        user_output(f"fast-forwarded {entry.slug} {_short(outcome.previous_head)}..{_short(head)}")
    elif outcome.action == "up_to_date":
        user_output(f"up to date {entry.slug} ({_short(head)})")
    else:
        kind = "dirty" if outcome.action == "skipped_dirty" else "non-ff"
        user_output(f"skipped ({kind}) {entry.slug}: {outcome.detail}")
