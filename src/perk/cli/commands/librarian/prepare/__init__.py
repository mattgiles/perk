"""``perk librarian prepare`` — the ``run_librarian`` tool's worker (contracts.md §8.75(k)/(l)).

Runs the docs doors' pre-session half — input validation, eligibility, the skill/converter
prerequisites, the cache-only preflight — then claims the empty staging directory and emits the
crawl plan (the one construction of the crawl and publish commands). Launches nothing: the
extension dispatches the ``perk.librarian`` writer child with the plan. Not admitted to
read-only sessions — the tool reaches it through the extension's own exec.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.librarian.prepare.docs_cmd import prepare_docs_cmd
from perk.cli.commands.librarian.prepare.refresh_cmd import prepare_refresh_cmd


@click.group("prepare", cls=AliasGroup)
def prepare_group() -> None:
    """Prepare a documentation crawl plan for the run_librarian tool (claims the staging
    directory; launches nothing)."""


prepare_group.add_command(prepare_docs_cmd)
prepare_group.add_command(prepare_refresh_cmd)
