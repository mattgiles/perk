"""``perk gist list`` — the gist tracking read (contracts.md §8.41).

Gathers the issue-tier gists (``IssueBackend.list_gist_issues``) and the project-tier gists
(``ObjectiveStore.list_gist_sources`` — non-empty only on the Linear project store). The default
view **hides adopted gists** (the "what's still unconsumed" backlog view); ``--all`` shows
everything with an adopted marker. Exits 0 on an empty list.
"""

import json

import click

from perk.backends import resolve
from perk.backends.issue_backend import GistSummary, IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@click.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include adopted gists (marked).")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def list_gists(ctx: click.Context, *, show_all: bool, as_json: bool) -> None:
    """List open gists (default: only the unconsumed backlog; --all includes adopted)."""
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)
        backend = resolve.resolve_issue_backend(repo_root)
        store = resolve.resolve_objective_store(repo_root)
        rows: list[tuple[GistSummary, str]] = [
            (summary, "issue") for summary in backend.list_gist_issues()
        ]
        rows.extend((summary, "project") for summary in store.list_gist_sources())
    except (IssueBackendError, ObjectiveStoreError) as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=f"gist list failed\n{exc}")
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if not show_all:
        rows = [(summary, kind) for summary, kind in rows if not summary.adopted]

    if as_json:
        payload = {
            "success": True,
            "error_type": None,
            "gists": [
                {
                    "id": summary.id,
                    "url": summary.url,
                    "title": summary.title,
                    "scope": summary.scope,
                    "adopted": summary.adopted,
                    "kind": kind,
                }
                for summary, kind in rows
            ],
        }
        machine_output(json.dumps(payload))
        return

    if not rows:
        user_output("No gists." if show_all else "No unconsumed gists.")
        return
    for summary, _kind in rows:
        scope = summary.scope or "?"
        marker = "  [adopted]" if summary.adopted else ""
        user_output(f"{summary.id}  [{scope}]  {summary.title}{marker}  {summary.url}")
