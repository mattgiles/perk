"""``perk state`` — inspect the local workflow cache and mint run ids.

A developer / CI / `doctor` surface (like `perk registry`), **not** an agent affordance:
the agent reads and writes workflow state through the extension, never by shelling `perk`.
T4's launch primitive reuses ``run_id.mint`` + ``cache.write_handoff``; this group exercises
them now so the T3 gate can drive the shell → ``PERK_RUN_ID`` → claim round-trip before the
real launcher exists.
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.state.new_run_cmd import new_run
from perk.cli.commands.state.show_cmd import show_state


@alias("st")
@click.group("state", cls=AliasGroup)
def state_group() -> None:
    """Inspect the local workflow cache and mint run ids (dev/CI/doctor surface)."""


register_with_aliases(state_group, new_run)
register_with_aliases(state_group, show_state)
