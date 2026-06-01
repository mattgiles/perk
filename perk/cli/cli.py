"""The ``perk`` CLI root group (the session *exterior*).

T1 ships ``--version`` and a minimal, idempotent ``init``. Stage subcommands are
generated from the stage registry (foundational #3) in a later turn; worktrees,
launch, and ``doctor`` follow. See docs/phase-0-plan.md.
"""

from pathlib import Path

import click

from perk import __version__
from perk.cli.commands.doctor_cmd import doctor
from perk.cli.commands.init_cmd import init_perk
from perk.cli.commands.plan_save_cmd import plan_save
from perk.cli.commands.registry_cmd import registry
from perk.cli.commands.state_cmd import state
from perk.cli.commands.worktree_cmd import worktree
from perk.cli.context import PerkContext
from perk.cli.stages import register_stage_commands


@click.group()
@click.version_option(__version__, prog_name="perk", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Plan-oriented engineering workflow for Pi."""
    # Cheap by design (no I/O): require_* resolves the repo/config lazily, so non-repo
    # commands work outside a git repo. Tests inject obj=PerkContext.for_test(...).
    if ctx.obj is None:
        ctx.obj = PerkContext(cwd=Path.cwd())


cli.add_command(init_perk)
cli.add_command(plan_save)
cli.add_command(doctor)
cli.add_command(registry)
cli.add_command(state)
cli.add_command(worktree)
register_stage_commands(cli)


def main() -> None:
    cli()
