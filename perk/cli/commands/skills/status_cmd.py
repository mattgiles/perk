"""`perk skills status` — show installed skill link status for this repo (pass-through)."""

import click

from perk.cli.commands.skills.shared import run_skills
from perk.cli.context import require_repo


@click.command("status")
@click.pass_context
def status_skills(ctx: click.Context) -> None:
    """Show installed skill link status for this repo.

    A pass-through to `skills status`.
    """
    run_skills(ctx, ["status"], cwd=require_repo(ctx))
