"""``perk worktree`` — create / list / remove / check out git worktrees (the exterior,
cli-vs-pi §2.2).

A subprocess can never ``cd`` its parent shell, so ``checkout`` prints the worktree's path on
stdout (composes with ``cd "$(perk wt co NAME)"``) and ``--script`` emits a ``cd`` script for
``source <(perk wt co NAME --script)`` — the gesture that actually moves the current shell.
Output is plain aligned text — Rich tables await a real dashboard (python-cli-guidelines §7.3).
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.worktree.checkout_cmd import checkout_worktree
from perk.cli.commands.worktree.create_cmd import create_worktree
from perk.cli.commands.worktree.list_cmd import list_worktrees
from perk.cli.commands.worktree.remove_cmd import remove_worktree
from perk.cli.commands.worktree.wipe_cmd import wipe_worktrees


@alias("wt")
@click.group("worktree", cls=AliasGroup)
def worktree_group() -> None:
    """Create, list, remove, and check out git worktrees."""


register_with_aliases(worktree_group, checkout_worktree)
register_with_aliases(worktree_group, create_worktree)
register_with_aliases(worktree_group, list_worktrees)
register_with_aliases(worktree_group, remove_worktree)
register_with_aliases(worktree_group, wipe_worktrees)
