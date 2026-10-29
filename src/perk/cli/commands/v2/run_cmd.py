"""`perk v2 run` — observe an execution's tracked ref and run it to quiescence."""

import click

from perk.cli.commands.v2.shared import JSON_HELP, drive


@click.command("run")
@click.argument("execution_id")
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def run_cmd(ctx: click.Context, *, execution_id: str, as_json: bool) -> None:
    """Observe EXECUTION_ID's tracked ref again and run it to quiescence."""
    drive(ctx, verb="run", execution_id=execution_id, verb_options=(), as_json=as_json)
