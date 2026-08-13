"""`perk worktree create` — create a worktree under the configured root."""

from pathlib import Path

import click

from perk.cli.alias import alias
from perk.cli.context import require_config, require_repo
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.run import launch
from perk.state import cache
from perk.substrate import git
from perk.substrate.git import GitError
from perk.substrate.output import user_output


@alias("new")
@click.command("create")
@click.argument("name")
@click.option("--branch", help="Branch to create (default: the worktree name).")
@click.pass_context
def create_worktree(ctx: click.Context, *, name: str, branch: str | None) -> None:
    """Create a worktree NAME under the configured worktree root."""
    config = require_config(ctx)
    _create_impl(
        repo_root=require_repo(ctx),
        worktree_root=config.worktree_root,
        worktree_setup=config.worktree_setup,
        name=name,
        branch=branch,
    )


def _create_impl(
    *,
    repo_root: Path,
    worktree_root: Path,
    worktree_setup: list[str],
    name: str,
    branch: str | None,
) -> None:
    Ensure.not_empty(name, "Worktree name cannot be empty.")
    Ensure.invariant(
        "/" not in name and name not in (".", ".."),
        f"Invalid worktree name '{name}' — no path separators.",
    )
    path = worktree_root / name
    if path.exists() and cache.has_marker(path, cache.SETUP_PENDING):
        # A previous create whose setup failed left the pending marker: re-running the same
        # command RETRIES the hook (marker-gated, cleared only on success) instead of refusing
        # — the documented fix-then-re-run recovery, matching the cold-door launchers.
        user_output(f"worktree {name} exists with a pending setup — retrying setup")
        launch.run_pending_setup(path, worktree_setup)
        user_output(click.style("✓ ", fg="green") + f"setup completed in {name}")
        return
    Ensure.invariant(not path.exists(), f"Worktree already exists: {path}")
    try:
        git.worktree_add(repo_root, path, branch=branch or name, create_branch=True)
    except GitError as exc:
        raise UserFacingCliError(f"git worktree add failed: {exc}") from exc
    user_output(click.style("✓ ", fg="green") + f"created worktree {name}")
    user_output(f"  {path}")
    # Marker-gated `[worktree] setup` in the just-created worktree (the same canonical gesture
    # the cold-door launchers use): the marker is set at creation and cleared only on success,
    # so a failed setup exits non-zero, leaves the worktree in place, and the SAME command
    # re-run retries the hook.
    cache.ensure_layout(path)
    cache.set_marker(path, cache.SETUP_PENDING)
    launch.run_pending_setup(path, worktree_setup)
