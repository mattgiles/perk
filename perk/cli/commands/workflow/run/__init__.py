"""``perk workflow run`` — observe and control dispatched runs."""

import click

from perk.cli.alias import AliasGroup, register_with_aliases
from perk.cli.commands.workflow.run.cancel_cmd import cancel_run
from perk.cli.commands.workflow.run.list_cmd import list_runs
from perk.cli.commands.workflow.run.retry_cmd import retry_run


@click.group("run", cls=AliasGroup)
def run_group() -> None:
    """Observe and (Node 3.2) control dispatched runs."""


register_with_aliases(run_group, list_runs)
register_with_aliases(run_group, cancel_run)
register_with_aliases(run_group, retry_run)
