"""`perk objective node` — explicit-status roadmap-node update."""

import json

import click

from perk import github, objective
from perk.cli.commands.objective.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output


@click.command("node")
@click.argument("number", type=int)
@click.option("--node", "node_id", required=True, help="The roadmap node id (e.g. 1.2).")
@click.option(
    "--status",
    "status",
    type=click.Choice([s.value for s in objective.NodeStatus]),
    default=None,
    help="Set the node's status (explicit-only; never inferred from --pr).",
)
@click.option("--pr", "pr", default=None, help='Set/clear the PR ("#N" sets, "" clears).')
@click.option("--description", "description", default=None, help="Update the node description.")
@click.option("--dry-run", "dry_run", is_flag=True, help="Validate without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def node_objective(
    ctx: click.Context,
    *,
    number: int,
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
        if not dry_run:
            require_github(ctx)
        result = github.update_objective_node(
            number=number,
            node_id=node_id,
            status=objective.NodeStatus(status) if status else None,
            pr=pr,
            description=description,
            repo_root=repo_root,
            dry_run=dry_run,
        )
    except GitHubError as exc:
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
