"""``perk state`` — inspect the local workflow cache and mint run ids.

A developer / CI / `doctor` surface (like `perk registry`), **not** an agent affordance:
the agent reads and writes workflow state through the extension, never by shelling `perk`.
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.state.new_run_cmd import new_run
from perk.cli.commands.state.prune_cmd import prune_run_state
from perk.cli.commands.state.show_cmd import show_state


@alias("st")
@click.group("state", cls=AliasGroup)
def state_group() -> None:
    """Inspect the local workflow cache and mint run ids (dev/CI/doctor surface)."""


register_with_aliases(state_group, new_run)
register_with_aliases(state_group, show_state)
register_with_aliases(state_group, prune_run_state)
