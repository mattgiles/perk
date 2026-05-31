"""The ``perk`` CLI root group (the session *exterior*).

T1 ships ``--version`` and a minimal, idempotent ``init``. Stage subcommands are
generated from the stage registry (foundational #3) in a later turn; worktrees,
launch, and ``doctor`` follow. See docs/phase-0-plan.md.
"""

from __future__ import annotations

import click

from perk import __version__
from perk.cli.commands.init_cmd import init_perk


@click.group()
@click.version_option(__version__, prog_name="perk", message="%(prog)s %(version)s")
def cli() -> None:
    """Plan-oriented engineering workflow for Pi."""


cli.add_command(init_perk)


def main() -> None:
    cli()
