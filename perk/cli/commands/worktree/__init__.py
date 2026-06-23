"""``perk worktree`` — create / list / remove git worktrees (the exterior, cli-vs-pi §2.2).

This group only *creates and reports* a worktree's path; moving the parent shell into it
(shell-activation) is deferred. Output is plain aligned text — Rich
tables await a real dashboard (python-cli-guidelines §7.3).
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.worktree.create_cmd import create_worktree
from perk.cli.commands.worktree.list_cmd import list_worktrees
from perk.cli.commands.worktree.remove_cmd import remove_worktree
from perk.cli.commands.worktree.wipe_cmd import wipe_worktrees


@alias("wt")
@click.group("worktree", cls=AliasGroup)
def worktree_group() -> None:
    """Create, list, and remove git worktrees."""


register_with_aliases(worktree_group, create_worktree)
register_with_aliases(worktree_group, list_worktrees)
register_with_aliases(worktree_group, remove_worktree)
register_with_aliases(worktree_group, wipe_worktrees)
