"""`perk objective node-add` — insert a new roadmap node (auto-assigned `<phase>.<n>`)."""

import json

import click

from perk import objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@click.command("node-add")
@click.argument("number")
@click.option("--phase", type=int, required=True, help="The phase number to insert the node into.")
@click.option("--description", required=True, help="The new node's description.")
@click.option(
    "--status",
    type=click.Choice([s.value for s in objective.NodeStatus]),
    default=objective.NodeStatus.PENDING.value,
    help="The new node's status (default: pending).",
)
@click.option("--slug", help="The node slug (auto-derived from the description if omitted).")
@click.option(
    "--depends-on",
    "depends_on_ids",
    multiple=True,
    help="A node id this node depends on (repeatable).",
)
@click.option("--comment", help="An optional note attached to the node.")
@click.option("--dry-run", is_flag=True, help="Validate without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def node_add_objective(
    ctx: click.Context,
    *,
    number: str,
    phase: int,
    description: str,
    status: str,
    slug: str | None,
    depends_on_ids: tuple[str, ...],
    comment: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Insert a new node into a phase (auto-assigned `<phase>.<n>`; appended after that phase's
    last node). Use sparingly — only when a genuinely new unit of work emerged (a deferred
    follow-up, an uncovered defect or gap, a missing prerequisite for a later node, or
    human-requested work)."""
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        if not dry_run:
            require_github(ctx)
        result = resolve.resolve_objective_store(repo_root).add_objective_node(
            objective_id=number,
            phase=phase,
            description=description,
            status=objective.NodeStatus(status),
            slug=slug,
            depends_on=tuple(depends_on_ids) or None,
            comment=comment,
            dry_run=dry_run,
        )
    except ObjectiveStoreError as exc:
        error_type = "invalid_input" if "collision" in str(exc) else "github_error"
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
        user_output(click.style("✓ ", fg="green") + f"Added node {result.node_id} on #{number}")
