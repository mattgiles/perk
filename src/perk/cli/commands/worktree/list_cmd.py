"""`perk worktree list` — list the repo's worktrees."""

import click

from perk.cli.alias import alias
from perk.cli.context import require_repo
from perk.substrate import git
from perk.substrate.git import Worktree
from perk.substrate.output import user_output


@alias("ls")
@click.command("list")
@click.pass_context
def list_worktrees(ctx: click.Context) -> None:
    """List the repo's worktrees."""
    _list_impl(git.worktree_list(require_repo(ctx)))


def _list_impl(worktrees: list[Worktree]) -> None:
    if not worktrees:
        user_output("no worktrees")
        return
    for wt in worktrees:
        user_output(f"  {(wt.branch or '(detached)'):<24} {wt.path}")
