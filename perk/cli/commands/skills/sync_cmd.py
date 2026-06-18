"""`perk skills sync` — update all sources to newer commits and re-sync links (pass-through)."""

import click

from perk.cli.commands.skills.shared import run_skills
from perk.cli.context import require_repo


@click.command("sync")
@click.pass_context
def sync_skills_cmd(ctx: click.Context) -> None:
    """Update all sources to newer commits and re-sync links.

    A pass-through to `skills update --sync`. (Named ``sync_skills_cmd`` to avoid colliding with
    ``perk.convergence.init.sync_skills``.)
    """
    run_skills(ctx, ["update", "--sync"], cwd=require_repo(ctx))
