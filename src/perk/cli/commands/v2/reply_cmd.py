"""`perk v2 reply` — answer an execution's open decision."""

import click

from perk.cli.commands.v2.shared import JSON_HELP, drive
from perk.v2.door import DEFAULT_ACTOR


@click.command("reply")
@click.argument("execution_id")
@click.argument("decision_id")
@click.argument("action")
@click.option("--actor", default=DEFAULT_ACTOR, show_default=True, help="Who replies.")
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def reply_cmd(
    ctx: click.Context,
    *,
    execution_id: str,
    decision_id: str,
    action: str,
    actor: str,
    as_json: bool,
) -> None:
    """Reply ACTION to DECISION_ID of EXECUTION_ID (the host refuses a bad action or actor)."""
    drive(
        ctx,
        verb="reply",
        execution_id=execution_id,
        verb_options=(("decision", decision_id), ("action", action), ("actor", actor)),
        as_json=as_json,
    )
