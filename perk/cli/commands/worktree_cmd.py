"""``perk worktree`` — create / list / remove git worktrees (the exterior, cli-vs-pi §2.2).

T4 only *creates and reports* a worktree's path; moving the parent shell into it
(shell-activation) is Phase 1 (phase-0-plan deferral). Output is plain aligned text — Rich
tables are deferred until a real dashboard (python-cli-guidelines §7.3).
"""

from pathlib import Path

import click

from perk import git
from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.context import require_config, require_repo
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.git import GitError, Worktree
from perk.output import user_output


@alias("wt")
@click.group("worktree", cls=AliasGroup)
def worktree() -> None:
    """Create, list, and remove git worktrees."""


@alias("new")
@click.command("create")
@click.argument("name")
@click.option("--branch", default=None, help="Branch to create (default: the worktree name).")
@click.pass_context
def create_worktree(ctx: click.Context, name: str, *, branch: str | None) -> None:
    """Create a worktree NAME under the configured worktree root."""
    _create_impl(
        repo_root=require_repo(ctx),
        worktree_root=require_config(ctx).worktree_root,
        name=name,
        branch=branch,
    )


def _create_impl(*, repo_root: Path, worktree_root: Path, name: str, branch: str | None) -> None:
    Ensure.not_empty(name, "Worktree name cannot be empty.")
    Ensure.invariant(
        "/" not in name and name not in (".", ".."),
        f"Invalid worktree name '{name}' — no path separators.",
    )
    path = worktree_root / name
    Ensure.invariant(not path.exists(), f"Worktree already exists: {path}")
    try:
        git.worktree_add(repo_root, path, branch=branch or name, create_branch=True)
    except GitError as exc:
        raise UserFacingCliError(f"git worktree add failed: {exc}") from exc
    user_output(click.style("✓ ", fg="green") + f"created worktree {name}")
    user_output(f"  {path}")


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


register_with_aliases(worktree, create_worktree)
register_with_aliases(worktree, list_worktrees)
register_with_aliases(worktree, remove_worktree)
