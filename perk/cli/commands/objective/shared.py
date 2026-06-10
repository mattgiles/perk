"""Cross-verb helpers for the ``perk objective`` group."""

import json

import click

from perk import objective
from perk.output import machine_output, user_output

EXIT_FOR_TYPE = {"not_a_repo": 2}


def fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(EXIT_FOR_TYPE.get(error_type, 1))


def node_to_dict(node: objective.ObjectiveNode) -> dict[str, object]:
    return {
        "id": node.id,
        "description": node.description,
        "status": node.status.value,
        "pr": node.pr,
        "phase": objective.phase_label(objective.derive_phase(node.id)),
    }
