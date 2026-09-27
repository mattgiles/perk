"""``perk librarian list`` — the library report (offline, lock-free, contracts.md §8.75).

Resolves the MAIN checkout's library from any worktree and prints absolute paths: every
catalogued entry with its derived status, every uncatalogued directory with a copyable adopt
hint, and every leftover staging directory. An empty or absent library is not an error.

Exit codes: 0 ok · 1 typed refusal / op failure (e.g. ``catalog_malformed``) · 2 not-a-repo.
"""

import click

from perk.boundary import OutputModel
from perk.cli.commands.librarian.shared import (
    EntryOut,
    adopt_hint,
    fail_library_error,
    format_duration,
)
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.library import EntryView, LibraryError, ListReport, list_library
from perk.substrate.output import user_output


class UncataloguedOut(OutputModel):
    name: str
    path: str
    hint: str


class StagingOut(OutputModel):
    name: str
    path: str


class LibrarianListOut(OutputModel):
    """The ``--json`` envelope of ``perk librarian list`` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    library_root: str
    catalog_present: bool
    entries: tuple[EntryOut, ...]
    uncatalogued: tuple[UncataloguedOut, ...]
    staging: tuple[StagingOut, ...]

    @classmethod
    def from_domain(cls, report: ListReport) -> "LibrarianListOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            library_root=str(report.root),
            catalog_present=report.catalog_present,
            entries=tuple(EntryOut.from_view(view) for view in report.entries),
            uncatalogued=tuple(
                UncataloguedOut(name=path.name, path=str(path), hint=adopt_hint(path))
                for path in report.uncatalogued
            ),
            staging=tuple(StagingOut(name=path.name, path=str(path)) for path in report.staging),
        )


@click.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def list_library_cmd(ctx: click.Context, *, as_json: bool) -> None:
    """List library entries, uncatalogued directories and staging leftovers.

    \b
    Offline and lock-free; resolves the main checkout's docs/library/ from any worktree
    and prints absolute paths.
    """
    try:
        repo_root = require_repo(ctx)
        report = list_library(repo_root)
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
        payload=LibrarianListOut.from_domain(report).model_dump(mode="json"),
        render=lambda: _render_human(report),
    )


def _render_human(report: ListReport) -> None:
    present = report.root.is_dir()
    user_output(f"library: {report.root}" + ("" if present else " (absent)"))
    for view in report.entries:
        user_output(_entry_line(view))
    if report.uncatalogued:
        user_output("uncatalogued:")
        for path in report.uncatalogued:
            user_output(f"  {path.name:<24} {path}")
            user_output(f"    {adopt_hint(path)}")
    if report.staging:
        user_output("staging:")
        for path in report.staging:
            user_output(f"  {path.name:<24} {path}")


def _entry_line(view: EntryView) -> str:
    entry = view.entry
    age = view.checked_age_seconds
    checked = "never checked" if age is None else f"checked {_approx_age(age)} ago"
    missing = "  [missing]" if not view.present else ""
    return (
        f"  {view.status:<12} {entry.kind:<6} {entry.slug:<24} {view.absolute_path}  "
        f"{checked}{missing}"
    )


def _approx_age(seconds: int) -> str:
    """``seconds`` floored to its largest whole unit (``3d``, ``5h``, ``12m``, ``40s``)."""
    for size in (86_400, 3_600, 60):
        if seconds >= size:
            return format_duration(seconds - seconds % size)
    return format_duration(seconds)
