"""``perk librarian check`` — the library's only freshness probe (contracts.md §8.75(i)).

Probes every entry (or the named slugs, in order): pinned entries are never probed, entries
checked inside their ``stale_after`` window are skipped unless ``--force``, source entries are
probed with ``git ls-remote`` and docs entries with bounded conditional requests plus the
sitemap/``llms.txt`` fingerprint. Records ``checked_at``, ``evidence`` and ``drifted``.

Exit codes: 0 — a completed check, even with ``failed`` results · 1 typed refusal (an unknown
slug, a malformed catalog, a preflight refusal, ``library_busy``, ``io_error``) · 2 not-a-repo.
"""

from typing import Literal

import click
import httpx

from perk.boundary import OutputModel
from perk.cli.commands.librarian.shared import EntryOut, fail_library_error
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.library import CheckOutcome, CheckResult, LibraryError, check_entries
from perk.substrate.output import user_output


class CheckResultOut(OutputModel):
    """One entry's check result (order load-bearing)."""

    action: Literal["probed", "pinned", "recent", "missing", "failed"]
    detail: str | None
    notes: tuple[str, ...]
    entry: EntryOut

    @classmethod
    def from_domain(cls, result: CheckResult) -> "CheckResultOut":
        return cls(
            action=result.action,
            detail=result.detail,
            notes=result.notes,
            entry=EntryOut.from_view(result.view),
        )


class LibrarianCheckOut(OutputModel):
    """The ``--json`` envelope of ``perk librarian check`` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    results: tuple[CheckResultOut, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_domain(cls, outcome: CheckOutcome) -> "LibrarianCheckOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            results=tuple(CheckResultOut.from_domain(result) for result in outcome.results),
            warnings=outcome.warnings,
        )


def http_transport() -> httpx.BaseTransport | None:
    """The docs probe's HTTP transport — ``None`` (the network) in production; tests replace
    this seam with an ``httpx.MockTransport``."""
    return None


@click.command("check")
@click.argument("slugs", nargs=-1)
@click.option("--force", is_flag=True, help="Probe even entries checked inside their window.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def check_library_cmd(
    ctx: click.Context, *, slugs: tuple[str, ...], force: bool, as_json: bool
) -> None:
    """Probe library entries for upstream changes (all entries, or the named slugs).

    \b
    The only freshness probe: pinned entries are never probed, and entries checked
    inside their stale-after window are skipped unless --force.
    """
    try:
        repo_root = require_repo(ctx)
        outcome = check_entries(repo_root, slugs=slugs, force=force, transport=http_transport())
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
        payload=LibrarianCheckOut.from_domain(outcome).model_dump(mode="json"),
        render=lambda: _render_human(outcome),
    )


def _render_human(outcome: CheckOutcome) -> None:
    if not outcome.results:
        user_output("no library entries to check")
    for result in outcome.results:
        entry = result.view.entry
        user_output(
            f"{result.action:<8} {result.view.status:<12} {entry.kind:<6} {entry.slug:<24} "
            f"{result.detail or ''}".rstrip()
        )
        for note in result.notes:
            user_output(f"  note: {note}")
    for warning in outcome.warnings:
        user_output(f"warning: {warning}")
