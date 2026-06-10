"""`perk objective next` — print the next plannable node."""

import json

import click

from perk import github, objective
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import fail, node_to_dict
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output


@alias("n")
@click.command("next")
@click.argument("number", type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def next_objective(ctx: click.Context, *, number: int, as_json: bool) -> None:
    """Print the next plannable node (pending, or a resumable ``planning`` claim)."""
    try:
        repo_root = require_repo(ctx)
        state = github.get_objective(number=number, repo_root=repo_root)
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )
    except GitHubError as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    next_node = objective.build_graph(list(state.nodes)).next_node()
    payload = {
        "success": True,
        "error_type": None,
        "next_node": node_to_dict(next_node) if next_node else None,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(f"next: {next_node.id if next_node else '—'}")
