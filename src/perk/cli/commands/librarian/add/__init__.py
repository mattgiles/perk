"""``perk librarian add`` — add a library entry by kind (contracts.md §8.75(i)).

``add source`` clones a source checkout; it is the group's only kind.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.librarian.add.source_cmd import add_source_cmd


@click.group("add", cls=AliasGroup)
def add_group() -> None:
    """Add a library entry by kind."""


add_group.add_command(add_source_cmd)
