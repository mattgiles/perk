"""``perk librarian add`` — add a library entry by kind (contracts.md §8.75(i)/(k)).

``add source`` clones a source checkout; ``add docs`` launches the session that mirrors a
documentation site.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.librarian.add.docs_cmd import add_docs_cmd
from perk.cli.commands.librarian.add.source_cmd import add_source_cmd


@click.group("add", cls=AliasGroup)
def add_group() -> None:
    """Add a library entry by kind."""


add_group.add_command(add_docs_cmd)
add_group.add_command(add_source_cmd)
