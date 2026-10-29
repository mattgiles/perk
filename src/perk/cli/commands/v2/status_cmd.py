"""`perk v2 status` — the read-only status snapshot of an execution."""

import click

from perk.cli.commands.v2.shared import JSON_HELP, drive


@click.command("status")
@click.argument("execution_id")
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def status_cmd(ctx: click.Context, *, execution_id: str, as_json: bool) -> None:
    """Show EXECUTION_ID's status snapshot; never observes, schedules or commits."""
    drive(ctx, verb="status", execution_id=execution_id, verb_options=(), as_json=as_json)
