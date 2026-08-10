"""``perk objective stack`` — the stacked-delivery train worker group (contracts.md §8.44/§8.49).

``status`` is the read path: reconstruct + report the ``DeliveryTrain`` projection. ``sync``
is the published-suffix synchronization cascade (§8.49; its recovery surface — adopt,
dry-run, continue/abort — is a later node's). The remaining verbs the architecture assigns
here are owned by later delivery nodes and are deliberately absent (no fictional stubs):
recover, and — in the atomic-landing node — land.
"""

import click

from perk.cli.alias import AliasGroup, register_with_aliases
from perk.cli.commands.objective.stack.status_cmd import status_stack
from perk.cli.commands.objective.stack.sync_cmd import sync_stack


@click.group("stack", cls=AliasGroup)
def stack_group() -> None:
    """Observe and synchronize an objective's stacked delivery train."""


register_with_aliases(stack_group, status_stack)
register_with_aliases(stack_group, sync_stack)
