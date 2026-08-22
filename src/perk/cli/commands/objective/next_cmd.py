"""`perk objective next` — print the next plannable node."""

import json

import click

from perk import objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli import completions
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import (
    handoff_blocker_phrase,
    node_to_dict,
    parse_objective_id,
    selection_gate_blockers,
    stacked_selection,
)
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@alias("n")
@click.command("next")
@click.argument("number", shell_complete=completions.complete_objective_id)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def next_objective(ctx: click.Context, *, number: str, as_json: bool) -> None:
    """Print the next plannable node (pending, or a resumable ``planning`` claim)."""
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        state = resolve.resolve_objective_store(repo_root).get_objective(objective_id=number)
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )
        # Stacked objectives select the readiness-derived candidate (contracts.md §8.46) — a
        # live train reconstruction, accepted cost for honest selection. Incremental payloads
        # stay byte-identical (`selection is None`).
        selection = stacked_selection(repo_root, state)
    except ObjectiveStoreError as exc:
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

    if selection is not None:
        next_node = selection.node if selection.kind == "plannable" else None
        # The always-present additive blocker rows (contracts.md §8.46): technical rows on
        # build_blocked, handoff rows on handoff_blocked, [] otherwise.
        blockers = selection_gate_blockers(selection)
        payload: dict[str, object] = {
            "success": True,
            "error_type": None,
            "next_node": node_to_dict(next_node) if next_node else None,
            "build_ready": {
                "ready": selection.ready,
                "reason": selection.reason,
                "blockers": [row.model_dump(mode="json") for row in blockers],
            },
        }
        if as_json:
            machine_output(json.dumps(payload))
        elif next_node is not None:
            user_output(f"next: {next_node.id}")
        elif selection.kind == "handoff_blocked" and selection.node is not None:
            for layer in selection.handoff_blockers:
                user_output(
                    f"handoff blocked: node {selection.node.id} waits on "
                    f"{handoff_blocker_phrase(layer)}"
                )
        elif not selection.ready:
            user_output(f"build blocked: {selection.reason}")
        else:
            user_output("next: —")
        return

    next_node = objective.build_graph(list(state.nodes)).next_plannable()
    payload = {
        "success": True,
        "error_type": None,
        "next_node": node_to_dict(next_node) if next_node else None,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(f"next: {next_node.id if next_node else '—'}")
