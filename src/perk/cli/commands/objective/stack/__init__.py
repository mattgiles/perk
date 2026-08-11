"""``perk objective stack`` — the stacked-delivery train worker group
(contracts.md §8.44/§8.49/§8.51).

``status`` is the read path: reconstruct + report the ``DeliveryTrain`` projection. ``sync``
is the published-suffix synchronization cascade with its control surface (§8.49: --base,
--dry-run, --adopt, --continue/--abort). ``recover`` is conclude-only recovery + the orphan
sweep (§8.51). The remaining verb the architecture assigns here is owned by the
atomic-landing node and is deliberately absent (no fictional stubs): land.
"""

import click

from perk.cli.alias import AliasGroup, register_with_aliases
from perk.cli.commands.objective.stack.recover_cmd import recover_stack
from perk.cli.commands.objective.stack.status_cmd import status_stack
from perk.cli.commands.objective.stack.sync_cmd import sync_stack


@click.group("stack", cls=AliasGroup)
def stack_group() -> None:
    """Observe, synchronize, and recover an objective's stacked delivery train."""


register_with_aliases(stack_group, status_stack)
register_with_aliases(stack_group, sync_stack)
register_with_aliases(stack_group, recover_stack)
