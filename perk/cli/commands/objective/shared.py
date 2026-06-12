"""Cross-verb helpers for the ``perk objective`` group."""

import json

import click

from perk import objective
from perk.cli.commands.resume_cmd import parse_plan_id
from perk.substrate.output import machine_output, user_output

EXIT_FOR_TYPE = {"not_a_repo": 2}


def parse_objective_id(raw: str) -> str:
    """Validate an opaque objective issue id (``7``, ``#7``, or Linear's ``ENG-7``).

    The single shared parse for every ``perk objective`` verb — a thin alias of the re-typed
    :func:`perk.cli.commands.resume_cmd.parse_plan_id` (one definition, no duplication; D5).
    """
    return parse_plan_id(raw, what="objective")


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
