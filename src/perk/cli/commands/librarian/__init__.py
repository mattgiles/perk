"""``perk librarian`` — tend the perk library (contracts.md §8.75).

The perk library is the catalogued, gitignored offline reference of external documentation
mirrors and source checkouts under the MAIN checkout's ``docs/library/``. The group's workers are
deterministic supervisor surfaces: ``list`` (offline, lock-free), ``record`` (the docs catalog
writer — ``--publish`` a staged mirror, ``--adopt`` an uncatalogued directory), ``remove``,
``add source`` (clone or re-pin a source checkout), ``check`` (the ONLY freshness probe) and
``refresh`` (fast-forward a source checkout). ``add source`` and ``refresh`` reach the network
only for their own checkout, with every executing git operation config-pinned (hooks disabled,
no global/system config). Every mutating worker runs the cache-only preflight (representative
ignore probes, a tracked-content sweep, real-directory roots) and refuses anything that would
reach outside the gitignored cache — which is what admits the ``--json`` forms to read-only perk
sessions.

Two human forms are doors rather than workers: ``add docs`` and the human ``refresh`` of a
documentation entry claim a staging directory and launch a curating session (mirroring a site is
judgment work — there is no session-free add); the ``--json`` forms stay the deterministic
workers, and neither door is admitted to read-only sessions. ``prepare docs|refresh … --json`` is
the doors' pre-session half plus the staging claim, emitted as the crawl plan the extension's
``run_librarian`` tool dispatches its writer child with; it launches nothing.

``--json`` → stdout, human text → stderr; exit codes ``0`` ok · ``1`` typed refusal / op failure
· ``2`` not-a-repo. No verb aliases: the read-only gate grammar names exactly the six worker
verbs; ``prepare`` — the ``run_librarian`` tool's worker — is not admitted.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.librarian.add import add_group
from perk.cli.commands.librarian.check_cmd import check_library_cmd
from perk.cli.commands.librarian.list_cmd import list_library_cmd
from perk.cli.commands.librarian.prepare import prepare_group
from perk.cli.commands.librarian.record_cmd import record_library_cmd
from perk.cli.commands.librarian.refresh_cmd import refresh_library_cmd
from perk.cli.commands.librarian.remove_cmd import remove_library_cmd


@click.group("librarian", cls=AliasGroup)
def librarian_group() -> None:
    """Tend the perk library: the catalogued, gitignored offline reference of external docs and
    source code."""


librarian_group.add_command(add_group)
librarian_group.add_command(check_library_cmd)
librarian_group.add_command(list_library_cmd)
librarian_group.add_command(prepare_group)
librarian_group.add_command(record_library_cmd)
librarian_group.add_command(refresh_library_cmd)
librarian_group.add_command(remove_library_cmd)
