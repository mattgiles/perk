"""The ``perk`` CLI root group (the session *exterior*).

T1 ships ``--version`` and a minimal, idempotent ``init``. Stage subcommands are
generated from the stage registry (foundational #3) in a later turn; worktrees,
launch, and ``doctor`` follow. See docs/phase-0-plan.md.
"""

import click

from perk import __version__
from perk.cli.commands.init_cmd import init_perk
from perk.cli.commands.registry_cmd import registry
from perk.cli.commands.state_cmd import state


@click.group()
@click.version_option(__version__, prog_name="perk", message="%(prog)s %(version)s")
def cli() -> None:
    """Plan-oriented engineering workflow for Pi."""


cli.add_command(init_perk)
cli.add_command(registry)
cli.add_command(state)


def main() -> None:
    cli()
