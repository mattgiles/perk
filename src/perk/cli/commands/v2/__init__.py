"""``perk v2`` — the experimental pi-durable v2 door (contracts.md §8.77).

Hidden, and runnable only inside perk's own source checkout (``[tool.perk] self = true``): it is
not shipped. Each verb mints or names an execution, invokes the TypeScript v2 host, and prints
its door envelope — human lines on stderr, or the envelope itself on stdout under ``--json``.
Every option is a plain string, so the host's refusals stay typed under ``--json``.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.v2.cancel_cmd import cancel_cmd
from perk.cli.commands.v2.reply_cmd import reply_cmd
from perk.cli.commands.v2.run_cmd import run_cmd
from perk.cli.commands.v2.start_cmd import start_cmd
from perk.cli.commands.v2.status_cmd import status_cmd


@click.group("v2", cls=AliasGroup, hidden=True)
def v2_group() -> None:
    """Drive experimental pi-durable v2 executions (perk's own checkout only)."""


v2_group.add_command(start_cmd)
v2_group.add_command(run_cmd)
v2_group.add_command(status_cmd)
v2_group.add_command(reply_cmd)
v2_group.add_command(cancel_cmd)
