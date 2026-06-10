"""`perk worktree remove` — remove a worktree by name."""

from pathlib import Path

import click

from perk import git
from perk.cli.alias import alias
from perk.cli.context import require_config, require_repo
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.git import GitError
from perk.output import user_output


@alias("rm")
@click.command("remove")
@click.argument("name")
@click.option("-f", "--force", is_flag=True, help="Remove even with uncommitted changes.")
@click.pass_context
def remove_worktree(ctx: click.Context, name: str, *, force: bool) -> None:
    """Remove the worktree NAME."""
    _remove_impl(
        repo_root=require_repo(ctx),
        worktree_root=require_config(ctx).worktree_root,
        name=name,
        force=force,
    )


def _remove_impl(*, repo_root: Path, worktree_root: Path, name: str, force: bool) -> None:
    path = worktree_root / name
    Ensure.path_exists(path, f"Worktree not found: {path}")
    try:
        git.worktree_remove(repo_root, path, force=force)
    except GitError as exc:
        raise UserFacingCliError(f"git worktree remove failed: {exc}") from exc
    user_output(click.style("✓ ", fg="green") + f"removed worktree {name}")
