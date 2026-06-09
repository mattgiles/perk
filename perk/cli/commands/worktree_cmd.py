"""``perk worktree`` — create / list / remove git worktrees (the exterior, cli-vs-pi §2.2).

T4 only *creates and reports* a worktree's path; moving the parent shell into it
(shell-activation) is Phase 1 (phase-0-plan deferral). Output is plain aligned text — Rich
tables are deferred until a real dashboard (python-cli-guidelines §7.3).
"""

import re
from dataclasses import dataclass
from pathlib import Path

import click

from perk import cache, git, github
from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.context import require_config, require_repo
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.git import GitError, Worktree
from perk.github import GitHubError
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


@click.command("wipe")
@click.option("--dry-run", is_flag=True, help="Preview removals without deleting anything.")
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Bypass the safety guards (remove even if dirty or pending-learn).",
)
@click.pass_context
def wipe_worktrees(ctx: click.Context, *, dry_run: bool, force: bool) -> None:
    """Remove all merged, safe-to-delete plan-<N> worktrees (and their branches)."""
    _wipe_impl(
        repo_root=require_repo(ctx),
        worktree_root=require_config(ctx).worktree_root,
        dry_run=dry_run,
        force=force,
    )


@dataclass(frozen=True)
class WipeDecision:
    remove: bool
    reason: str  # human-readable reason (why removed / why skipped)


def _classify_worktree(
    *, pr_state: str, is_dirty: bool, has_pending_learn: bool, force: bool
) -> WipeDecision:
    """Decide whether a *known* plan worktree is wipeable.

    no-longer-used == PR MERGED (the only removable state; --force does NOT relax this).
    safe-to-delete == not dirty AND no pending-learn, unless --force bypasses both guards.
    """
    if pr_state != "MERGED":
        return WipeDecision(remove=False, reason=f"PR is {pr_state}, not merged")
    if not force:
        if is_dirty:
            return WipeDecision(remove=False, reason="uncommitted changes (use --force)")
        if has_pending_learn:
            return WipeDecision(remove=False, reason="pending-learn not cleared (use --force)")
    return WipeDecision(remove=True, reason="PR merged")


_PLAN_WT_RE = re.compile(r"^plan-(\d+)$")


def _plan_number(name: str) -> int | None:
    """The integer plan id from a ``plan-<N>`` worktree name, or None if not a numeric plan wt."""
    m = _PLAN_WT_RE.match(name)
    return int(m.group(1)) if m else None


def _skip(name: str, reason: str) -> None:
    user_output(f"  skip {name}: {reason}")


def _wipe_impl(*, repo_root: Path, worktree_root: Path, dry_run: bool, force: bool) -> None:
    wt_root = worktree_root.resolve()
    repo_resolved = repo_root.resolve()
    candidates = [
        wt
        for wt in git.worktree_list(repo_root)
        if wt.path.parent.resolve() == wt_root and _PLAN_WT_RE.match(wt.path.name)
    ]
    if not candidates:
        user_output("no plan worktrees to wipe")
        return

    removed = 0
    skipped = 0
    for wt in candidates:
        name = wt.path.name
        # Never wipe the worktree the command is being run from (git refuses; surface clearly).
        if wt.path.resolve() == repo_resolved:
            _skip(name, "current worktree")
            skipped += 1
            continue
        number = _plan_number(name)  # guaranteed non-None by the regex filter above
        assert number is not None
        # Determine PR state (network); skip on any uncertainty — never delete on doubt.
        try:
            state = github.get_plan(number=number, repo_root=repo_root)
        except GitHubError as exc:
            _skip(name, f"could not determine PR state ({exc})")
            skipped += 1
            continue
        if state is None:
            _skip(name, "plan issue not found")
            skipped += 1
            continue
        if state.pr is None:
            _skip(name, "no PR linked to plan")
            skipped += 1
            continue
        decision = _classify_worktree(
            pr_state=state.pr.state,
            is_dirty=git.is_dirty(wt.path),
            has_pending_learn=cache.has_marker(wt.path, cache.PENDING_LEARN),
            force=force,
        )
        if not decision.remove:
            _skip(name, decision.reason)
            skipped += 1
            continue
        if dry_run:
            user_output(f"  would remove {name}  ({decision.reason})")
            removed += 1
            continue
        try:
            git.worktree_remove(repo_root, wt.path, force=force)
        except GitError as exc:
            _skip(name, f"git worktree remove failed: {exc}")
            skipped += 1
            continue
        branch = wt.branch or name
        try:
            git.delete_branch(repo_root, branch)
            user_output(click.style("✓ ", fg="green") + f"removed {name} (+ branch {branch})")
        except GitError as exc:
            user_output(
                click.style("✓ ", fg="green") + f"removed {name}; branch {branch} kept ({exc})"
            )
        removed += 1

    verb = "would wipe" if dry_run else "wiped"
    user_output(f"{verb} {removed} worktree(s); {skipped} skipped")


register_with_aliases(worktree, create_worktree)
register_with_aliases(worktree, list_worktrees)
register_with_aliases(worktree, remove_worktree)
register_with_aliases(worktree, wipe_worktrees)
