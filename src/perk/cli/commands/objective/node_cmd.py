"""`perk objective node` — explicit-status roadmap-node update."""

import json

import click

from perk import objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli import completions
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@click.command("node")
@click.argument("number", shell_complete=completions.complete_objective_id)
@click.option("--node", "node_id", required=True, help="The roadmap node id (e.g. 1.2).")
@click.option(
    "--status",
    type=click.Choice([s.value for s in objective.NodeStatus]),
    help="Set the node's status (explicit-only; never inferred from --pr).",
)
@click.option("--pr", help='Set/clear the PR ("#N" sets, "" clears).')
@click.option("--description", help="Update the node description.")
@click.option("--dry-run", is_flag=True, help="Validate without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def node_objective(
    ctx: click.Context,
    *,
    number: str,
    node_id: str,
    status: str | None,
    pr: str | None,
    description: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Update one roadmap node (explicit-status-only; open #3)."""
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        if not dry_run:
            require_github(ctx)
        result = resolve.resolve_objective_store(repo_root).update_objective_node(
            objective_id=number,
            node_id=node_id,
            status=objective.NodeStatus(status) if status else None,
            pr=pr,
            description=description,
            dry_run=dry_run,
        )
    except ObjectiveStoreError as exc:
        # A not-found node is a user error, not infra — map it to invalid_input.
        error_type = "node_not_found" if "not found" in str(exc) else "github_error"
        fail(ctx, as_json=as_json, error_type=error_type, message=str(exc))
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
        "objective": number,
        "node": result.node_id,
        "comment_updated": result.comment_updated,
        "dry_run": result.dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(click.style("✓ ", fg="green") + f"Updated node {result.node_id} on #{number}")
