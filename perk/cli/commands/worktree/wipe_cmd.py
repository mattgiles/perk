"""`perk worktree wipe` — remove merged, safe-to-delete plan worktrees."""

import re
from dataclasses import dataclass
from pathlib import Path

import click

from perk import cache, git, issues
from perk.cli.context import require_config, require_repo
from perk.git import GitError
from perk.issue_backend import IssueBackendError
from perk.output import user_output


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
            state = issues.resolve_issue_backend(repo_root).get_plan(issue_id=str(number))
        except IssueBackendError as exc:
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
