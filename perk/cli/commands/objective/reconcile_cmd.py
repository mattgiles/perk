"""`perk objective reconcile` — rewrite the Reconcilable prose region."""

import json
from pathlib import Path

import click

from perk import issues
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.issue_backend import IssueBackendError
from perk.output import machine_output, user_output


@alias("rec")
@click.command("reconcile")
@click.argument("number", type=int)
@click.option(
    "--body",
    "body_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the reconciled Reconcilable-prose markdown (stdin-less worker pattern).",
)
@click.option("--dry-run", is_flag=True, help="Compose without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def reconcile_objective(
    ctx: click.Context, *, number: int, body_path: Path, dry_run: bool, as_json: bool
) -> None:
    """Reconcile an objective's Reconcilable prose region against the merged diff (P2.T11b).

    Rewrites ONLY the marker-bounded Reconcilable region of the objective-body comment — the
    Mechanical roadmap table and any Immutable notes are never touched. Node-description
    reconciliation reuses ``perk objective node --description`` (no new flag here).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        prose = body_path.read_text(encoding="utf-8")
        result = issues.resolve_issue_backend(repo_root).update_objective_body(
            issue_id=str(number), prose=prose, dry_run=dry_run
        )
    except IssueBackendError as exc:
        message = str(exc)
        error_type = (
            "reconcile_target_missing"
            if ("no body comment" in message or "no reconcilable region" in message)
            else "github_error"
        )
        fail(ctx, as_json=as_json, error_type=error_type, message=message)
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    payload = {
        "success": True,
        "error_type": None,
        # GitHub-numeric id assumption — re-shape when Linear lands (#252 Phase 2/3)
        "objective": int(result.issue_id),
        "comment_id": None if result.comment_id is None else int(result.comment_id),
        "updated": result.updated,
        "dry_run": result.dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(click.style("✓ ", fg="green") + f"Reconciled objective #{number} prose region")
