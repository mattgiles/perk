"""The ``prepare`` envelope: the crawl plan the ``run_librarian`` tool dispatches its child with.

``python`` and ``script_path`` travel only inside ``crawl_command`` — the plan's commands are
constructed once (``DocsCrawlPlan``), so the tool can never disagree with the doors about them.
"""

from typing import Literal

import click

from perk.boundary import OutputModel
from perk.cli.commands.librarian.shared import fail_library_error
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.library import DocsCrawlPlan, LibraryError
from perk.substrate.output import user_output

PrepareAction = Literal["add-docs", "refresh-docs"]


class LibrarianPrepareOut(OutputModel):
    """The ``--json`` envelope of ``perk librarian prepare`` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    action: PrepareAction
    url: str
    slug: str
    scope_prefix: str
    staging_dir: str
    main_root: str
    current_dir: str | None
    replace: bool
    crawl_command: str
    publish_command: str
    warnings: tuple[str, ...]

    @classmethod
    def from_plan(cls, action: PrepareAction, plan: DocsCrawlPlan) -> "LibrarianPrepareOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            action=action,
            url=plan.url,
            slug=plan.slug,
            scope_prefix=plan.scope_prefix,
            staging_dir=str(plan.staging_dir),
            main_root=str(plan.main_root),
            current_dir=str(plan.current_dir) if plan.current_dir is not None else None,
            replace=plan.replace,
            crawl_command=plan.crawl_command,
            publish_command=plan.publish_command,
            warnings=plan.warnings,
        )


def _render_human(out: LibrarianPrepareOut) -> None:
    for key in (
        "action",
        "url",
        "slug",
        "scope_prefix",
        "staging_dir",
        "main_root",
        "current_dir",
        "replace",
        "crawl_command",
        "publish_command",
    ):
        value = getattr(out, key)
        rendered = "" if value is None else str(value).lower() if isinstance(value, bool) else value
        user_output(f"{key}={rendered}")
    for warning in out.warnings:
        user_output(f"warning: {warning}")


def emit_plan(action: PrepareAction, plan: DocsCrawlPlan, *, as_json: bool) -> None:
    out = LibrarianPrepareOut.from_plan(action, plan)
    emit(as_json=as_json, payload=out.model_dump(mode="json"), render=lambda: _render_human(out))


def fail_prepare(
    ctx: click.Context, exc: LibraryError | UserFacingCliError, *, as_json: bool
) -> None:
    """The ``add docs`` door's failure mapping, verbatim."""
    if isinstance(exc, LibraryError):
        fail_library_error(ctx, exc, as_json=as_json)
        return
    fail(
        ctx,
        as_json=as_json,
        error_type=exc.error_type or "invalid_input",
        message=exc.format_message(),
    )
