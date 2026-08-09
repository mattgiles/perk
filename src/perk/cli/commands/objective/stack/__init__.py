"""``perk objective stack`` — the stacked-delivery train worker group (contracts.md §8.44).

``status`` is the read path: reconstruct + report the ``DeliveryTrain`` projection. The
mutating verbs the architecture assigns here — sync, recover, land — are owned by later
delivery nodes and are deliberately absent (no fictional stubs).
"""

import click

from perk.cli.alias import AliasGroup, register_with_aliases
from perk.cli.commands.objective.stack.status_cmd import status_stack


@click.group("stack", cls=AliasGroup)
def stack_group() -> None:
    """Observe an objective's stacked delivery train (read-only status)."""


register_with_aliases(stack_group, status_stack)
