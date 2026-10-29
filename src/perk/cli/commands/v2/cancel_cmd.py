"""`perk v2 cancel` — cancel an execution."""

import click

from perk.cli.commands.v2.shared import JSON_HELP, drive
from perk.v2.door import DEFAULT_CANCEL_REASON


@click.command("cancel")
@click.argument("execution_id")
@click.option(
    "--reason", default=DEFAULT_CANCEL_REASON, show_default=True, help="Why it is cancelled."
)
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def cancel_cmd(ctx: click.Context, *, execution_id: str, reason: str, as_json: bool) -> None:
    """Cancel EXECUTION_ID; never observes. A repeated cancel with the same reason replays."""
    drive(
        ctx,
        verb="cancel",
        execution_id=execution_id,
        verb_options=(("reason", reason),),
        as_json=as_json,
    )
