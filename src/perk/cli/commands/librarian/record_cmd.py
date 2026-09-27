"""``perk librarian record`` — the sole catalog writer (contracts.md §8.74(e)).

``--publish <staging-dir> --slug <slug>`` moves a staged mirror from ``.staging/`` to
``documentation/<slug>/`` and records it atomically (create-only; ``--replace`` refreshes an
existing docs entry). ``--adopt <dir>`` catalogs a pre-existing uncatalogued directory
(orphan-only). Every option is a plain string parsed inside the command so a bad value is a
typed ``--json`` refusal, never a Click usage error.

Exit codes: 0 ok · 1 typed refusal / op failure · 2 not-a-repo.
"""

from pathlib import Path
from typing import Literal

import click

from perk.boundary import OutputModel
from perk.cli.commands.librarian.shared import (
    EntryOut,
    fail_library_error,
    parse_stale_after,
    validate_source_url,
)
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.library import LibraryError, RecordOutcome, adopt, publish
from perk.substrate.output import user_output


class LibrarianRecordOut(OutputModel):
    """The ``--json`` envelope of ``perk librarian record`` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    action: Literal["publish", "adopt"]
    entry: EntryOut
    replaced_previous: bool
    warnings: tuple[str, ...]

    @classmethod
    def from_domain(cls, outcome: RecordOutcome) -> "LibrarianRecordOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            action=outcome.action,
            entry=EntryOut.from_view(outcome.view),
            replaced_previous=outcome.replaced_previous,
            warnings=outcome.warnings,
        )


@click.command("record")
@click.option("--publish", "publish_dir", default=None, help="A staged mirror under .staging/.")
@click.option("--adopt", "adopt_dir", default=None, help="An uncatalogued directory to catalog.")
@click.option("--slug", default=None, help="The entry slug (required with --publish).")
@click.option("--kind", default="docs", show_default=True, help="The entry kind (docs only).")
@click.option("--source", default=None, help="The upstream http(s) URL the mirror came from.")
@click.option("--replace", is_flag=True, help="Refresh an existing docs entry (--publish only).")
@click.option(
    "--accept-failures",
    is_flag=True,
    help="Publish despite a non-empty failed-pages.json crawl report (--publish only).",
)
@click.option("--stale-after", default=None, help="Freshness window, e.g. 7d or 24h.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def record_library_cmd(
    ctx: click.Context,
    *,
    publish_dir: str | None,
    adopt_dir: str | None,
    slug: str | None,
    kind: str,
    source: str | None,
    replace: bool,
    accept_failures: bool,
    stale_after: str | None,
    as_json: bool,
) -> None:
    """Publish a staged mirror, or adopt an uncatalogued directory.

    \b
    perk librarian record --publish <staging-dir> --slug <slug> --source <url> [--replace]
    perk librarian record --adopt <dir> [--slug <slug>] --kind docs --source <url>
    """
    try:
        if (publish_dir is None) == (adopt_dir is None):
            raise _exactly_one()
        if kind != "docs":
            raise LibraryError(
                "invalid_kind",
                "only `docs` entries are recorded here; source checkouts are recorded by "
                "`perk librarian add source`",
            )
        if source is None:
            raise UserFacingCliError(
                "--source <url> is required (the upstream the entry came from)",
                error_type="invalid_input",
            )
        validate_source_url(source)
        window = parse_stale_after(stale_after) if stale_after is not None else None
        if publish_dir is not None:
            if slug is None:
                raise UserFacingCliError("--publish requires --slug", error_type="invalid_input")
            repo_root = require_repo(ctx)
            outcome = publish(
                repo_root,
                staging=Path(publish_dir),
                slug=slug,
                source=source,
                replace=replace,
                accept_failures=accept_failures,
                stale_after=window,
            )
        elif adopt_dir is not None:
            if replace or accept_failures:
                raise UserFacingCliError(
                    "--replace and --accept-failures apply to --publish only",
                    error_type="invalid_input",
                )
            repo_root = require_repo(ctx)
            outcome = adopt(
                repo_root, directory=Path(adopt_dir), slug=slug, source=source, stale_after=window
            )
        else:
            raise _exactly_one()
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
        payload=LibrarianRecordOut.from_domain(outcome).model_dump(mode="json"),
        render=lambda: _render_human(outcome),
    )


def _exactly_one() -> UserFacingCliError:
    return UserFacingCliError(
        "pass exactly one of --publish <staging-dir> or --adopt <dir>", error_type="invalid_input"
    )


def _render_human(outcome: RecordOutcome) -> None:
    verb = "published" if outcome.action == "publish" else "adopted"
    user_output(f"{verb} {outcome.view.entry.slug} → {outcome.view.absolute_path}")
    for warning in outcome.warnings:
        user_output(f"warning: {warning}")
