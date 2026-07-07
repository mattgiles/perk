"""`perk objective reconcile` — rewrite the Reconcilable prose region."""

import json
import sys
from pathlib import Path

import click

from perk import objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@alias("rec")
@click.command("reconcile")
@click.argument("number")
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
    ctx: click.Context, *, number: str, body_path: Path, dry_run: bool, as_json: bool
) -> None:
    """Reconcile an objective's Reconcilable prose region against the merged diff.

    Rewrites ONLY the marker-bounded Reconcilable region of the objective-body comment — the
    Mechanical roadmap table and any Immutable notes are never touched. Node-description
    reconciliation reuses ``perk objective node --description`` (no new flag here).
    """
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        if not dry_run:
            require_github(ctx)
        prose = body_path.read_text(encoding="utf-8")
        store = resolve.resolve_objective_store(repo_root)
        result = store.update_objective_body(objective_id=number, prose=prose, dry_run=dry_run)
    except ObjectiveStoreError as exc:
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

    # Fail-open Project Update: post on a real (non-dry-run) update only. Linear project
    # store posts; GitHub + the issue-backed Linear store no-op. A failure is logged
    # loud-but-non-fatal and NEVER changes the reconcile result.
    if not dry_run and result.updated:
        try:
            store.post_status_update(objective_id=number, body=objective.reconciled_update_body())
        except Exception as exc:  # fail-open: the status update is bookkeeping, never load-bearing
            print(
                f"perk objective reconcile: project update skipped (non-fatal): {exc}",
                file=sys.stderr,
            )

    payload = {
        "success": True,
        "error_type": None,
        # Opaque string ids at every machine boundary (contracts §8.21).
        "objective": result.objective_id,
        "comment_id": result.comment_id,
        "updated": result.updated,
        "dry_run": result.dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(click.style("✓ ", fg="green") + f"Reconciled objective #{number} prose region")
