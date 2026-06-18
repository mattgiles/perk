"""`perk skills list` — list skills discoverable across this repo's sources (pass-through)."""

import click

from perk.cli.alias import alias
from perk.cli.commands.skills.shared import run_skills
from perk.cli.context import require_repo


@alias("ls")
@click.command("list")
@click.pass_context
def list_skills(ctx: click.Context) -> None:
    """List skills discoverable across this repo's sources.

    A pass-through to `skills skill list`.
    """
    run_skills(ctx, ["skill", "list"], cwd=require_repo(ctx))
