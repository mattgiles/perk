"""``perk librarian`` — tend the perk library (contracts.md §8.74).

The perk library is the catalogued, gitignored offline reference of external documentation
mirrors and source checkouts under the MAIN checkout's ``docs/library/``. The group's workers are
deterministic supervisor surfaces: ``list`` (offline, lock-free), ``record`` (the sole catalog
writer — ``--publish`` a staged mirror, ``--adopt`` an uncatalogued directory) and ``remove``.
Every mutating worker runs the cache-only preflight before taking the machine-local library lock,
so it never creates, modifies or deletes a non-ignored or tracked path — which is what admits the
``--json`` forms to read-only perk sessions.

``--json`` → stdout, human text → stderr; exit codes ``0`` ok · ``1`` typed refusal / op failure
· ``2`` not-a-repo. No verb aliases: the read-only gate grammar names exactly the three verbs.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.librarian.list_cmd import list_library_cmd
from perk.cli.commands.librarian.record_cmd import record_library_cmd
from perk.cli.commands.librarian.remove_cmd import remove_library_cmd


@click.group("librarian", cls=AliasGroup)
def librarian_group() -> None:
    """Tend the perk library: the catalogued, gitignored offline reference of external docs and
    source code."""


librarian_group.add_command(list_library_cmd)
librarian_group.add_command(record_library_cmd)
librarian_group.add_command(remove_library_cmd)
