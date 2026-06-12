"""`perk worktree wipe` — remove merged, safe-to-delete plan worktrees."""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import click

from perk.backends import issue_backend, issues
from perk.backends.issue_backend import IssueBackendError
from perk.cli.context import require_config, require_repo
from perk.state import cache
from perk.substrate import git
from perk.substrate.git import GitError
from perk.substrate.output import user_output


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


# Gather (PR-state lookups) is network-bound, so parallelize it; removal stays sequential.
_MAX_GATHER_WORKERS = 32


@dataclass(frozen=True)
class _GatheredFacts:
    """Per-worktree facts collected concurrently; consumed sequentially on the main thread."""

    skip_reason: str | None  # pre-classification skip (backend error / no issue / no PR)
    pr_state: str | None  # PR state when skip_reason is None
    is_dirty: bool
    has_pending_learn: bool


def _gather_facts(
    *, backend: issue_backend.IssueBackend, wt_path: Path, plan_id: str
) -> _GatheredFacts:
    """Read-only per-worktree fact gathering — runs on worker threads; never writes output."""

    def _skip_facts(reason: str) -> _GatheredFacts:
        return _GatheredFacts(
            skip_reason=reason, pr_state=None, is_dirty=False, has_pending_learn=False
        )

    # Determine PR state (network); skip on any uncertainty — never delete on doubt.
    try:
        state = backend.get_plan(issue_id=plan_id)
    except IssueBackendError as exc:
        return _skip_facts(f"could not determine PR state ({exc})")
    if state is None:
        return _skip_facts("plan issue not found")
    if state.pr is None:
        return _skip_facts("no PR linked to plan")
    return _GatheredFacts(
        skip_reason=None,
        pr_state=state.pr.state,
        is_dirty=git.is_dirty(wt_path),
        has_pending_learn=cache.has_marker(wt_path, cache.PENDING_LEARN),
    )


_PLAN_WT_RE = re.compile(r"^plan-(\S+)$")


def _plan_id(name: str) -> str | None:
    """The opaque plan id from a ``plan-<id>`` worktree name (``plan-42`` / ``plan-ENG-123``),
    or None if not a plan worktree."""
    m = _PLAN_WT_RE.match(name)
    return m.group(1) if m else None


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

    # Partition on the main thread: current-worktree skips never reach the gather pool.
    # (Never wipe the worktree the command is being run from — git refuses; surface clearly.)
    targets = [wt for wt in candidates if wt.path.resolve() != repo_resolved]

    # Gather phase: collect per-worktree facts concurrently (read-only, no output from workers).
    facts_by_path: dict[Path, _GatheredFacts] = {}
    if targets:
        try:
            backend = issues.resolve_issue_backend(repo_root)
        except IssueBackendError as exc:
            reason = f"could not determine PR state ({exc})"
            facts_by_path = {
                wt.path: _GatheredFacts(
                    skip_reason=reason, pr_state=None, is_dirty=False, has_pending_learn=False
                )
                for wt in targets
            }
        else:
            user_output(f"checking {len(targets)} plan worktree(s)…")
            with ThreadPoolExecutor(max_workers=min(_MAX_GATHER_WORKERS, len(targets))) as pool:
                futures = {}
                for wt in targets:
                    plan_id = _plan_id(wt.path.name)  # non-None by the regex filter above
                    assert plan_id is not None
                    futures[wt.path] = pool.submit(
                        lambda p=wt.path, i=plan_id: _gather_facts(
                            backend=backend, wt_path=p, plan_id=i
                        )
                    )
                # Unexpected (non-IssueBackendError) worker exceptions propagate here —
                # same crash semantics as the previous inline code.
                facts_by_path = {path: fut.result() for path, fut in futures.items()}

    # Act phase: sequential, in original candidate order (deterministic output + git mutations).
    removed = 0
    skipped = 0
    for wt in candidates:
        name = wt.path.name
        if wt.path.resolve() == repo_resolved:
            _skip(name, "current worktree")
            skipped += 1
            continue
        facts = facts_by_path[wt.path]
        if facts.skip_reason is not None:
            _skip(name, facts.skip_reason)
            skipped += 1
            continue
        assert facts.pr_state is not None
        decision = _classify_worktree(
            pr_state=facts.pr_state,
            is_dirty=facts.is_dirty,
            has_pending_learn=facts.has_pending_learn,
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
