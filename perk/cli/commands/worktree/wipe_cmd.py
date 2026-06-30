"""`perk worktree wipe` — remove merged, safe-to-delete plan worktrees."""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import click

from perk.backends import issue_backend, resolve
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


# Gather (PR-state lookups) is network-bound, so parallelize it.
_MAX_GATHER_WORKERS = 32

# Worktree removal is dominated by the filesystem rm -rf (lock-free); parallelize it too.
# 32 concurrent `rm -rf`s of `node_modules`/`.venv` trees thrash the disk badly enough that
# individual removals starve and time out (the broken-worktree residue then accrues); a smaller
# pool lets each finish on the primary git path.
_MAX_REMOVE_WORKERS = 8


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
    # The working dir is entirely gone (a fully-missing entry whose `.git`-walk would otherwise
    # run `git status` against an unexpected ancestor or crash on a nonexistent cwd). Flow it
    # through classification with neutral facts; the end-of-pool prune clears its admin record.
    if not wt_path.exists():
        return _GatheredFacts(
            skip_reason=None, pr_state=state.pr.state, is_dirty=False, has_pending_learn=False
        )
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
            backend = resolve.resolve_issue_backend(repo_root)
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

    # Act phase: classify (main thread) → remove (pool) → batched branch deletes. All per-worktree
    # output is deferred to one candidate-order pass after the pool so the global ordering holds.
    skipped = 0

    # a. Classify on the main thread, in candidate order. Skips are recorded (not yet emitted) so
    #    skip + removal lines interleave in one candidate-ordered pass below.
    skip_reasons: dict[Path, str] = {}
    to_remove: list[git.Worktree] = []
    for wt in candidates:
        if wt.path.resolve() == repo_resolved:
            skip_reasons[wt.path] = "current worktree"
            continue
        facts = facts_by_path[wt.path]
        if facts.skip_reason is not None:
            skip_reasons[wt.path] = facts.skip_reason
            continue
        assert facts.pr_state is not None
        decision = _classify_worktree(
            pr_state=facts.pr_state,
            is_dirty=facts.is_dirty,
            has_pending_learn=facts.has_pending_learn,
            force=force,
        )
        if not decision.remove:
            skip_reasons[wt.path] = decision.reason
            continue
        to_remove.append(wt)

    # b. Dry-run: report intent, no git mutations, no pool, no network.
    if dry_run:
        for wt in candidates:
            reason = skip_reasons.get(wt.path)
            if reason is not None:
                _skip(wt.path.name, reason)
            elif wt in to_remove:
                user_output(f"  would remove {wt.path.name}  (PR merged)")
        user_output(f"would wipe {len(to_remove)} worktree(s); {len(skip_reasons)} skipped")
        if to_remove:
            user_output(
                f"  would delete {len(to_remove)} local + {len(to_remove)} remote branch(es)"
            )
        return

    # c. Removal pool: parallel FS rm -rf (lock-free). No output from worker threads.
    removal_errors: dict[Path, GitError] = {}
    if to_remove:
        with ThreadPoolExecutor(max_workers=min(_MAX_REMOVE_WORKERS, len(to_remove))) as pool:
            futures = {
                wt.path: pool.submit(
                    lambda p=wt.path: git.worktree_remove(repo_root, p, force=force)
                )
                for wt in to_remove
            }
            for path, fut in futures.items():
                try:
                    fut.result()  # success → None; non-GitError propagates (crash, as before)
                except GitError as exc:
                    removal_errors[path] = exc

    # One candidate-order pass: interleave skip lines + removal results; collect the removed.
    removed = 0
    removed_worktrees: list[git.Worktree] = []
    for wt in candidates:
        name = wt.path.name
        reason = skip_reasons.get(wt.path)
        if reason is not None:
            _skip(name, reason)
            skipped += 1
            continue
        exc = removal_errors.get(wt.path)
        if exc is not None:
            _skip(name, f"git worktree remove failed: {exc}")
            skipped += 1
            continue
        user_output(click.style("✓ ", fg="green") + f"removed {name}")
        removed_worktrees.append(wt)
        removed += 1

    # Prune stale admin entries BEFORE branch deletes. A fallback-path removal leaves a stale
    # `.git/worktrees/<id>` entry; until it is pruned git still believes the (deleted) dir has the
    # plan branch checked out and refuses `git branch -D` with "checked out at …". This single
    # serialized prune also sweeps pre-existing orphan admin entries already on disk.
    git.worktree_prune(repo_root)

    # d. Batched local branch delete (-D: the PR is provably MERGED, so force is safe).
    branches = [wt.branch or wt.path.name for wt in removed_worktrees]
    if branches:
        deleted_local = git.delete_branches(repo_root, branches, force=True)
        line = f"deleted {len(deleted_local)} local branch(es)"
        kept = [b for b in branches if b not in deleted_local]
        if kept:
            line += f"; kept {', '.join(kept)}"
        user_output(line)

    # e. Batched remote branch delete (best-effort, guarded by has_remote — no-op when absent).
    if branches and git.has_remote(repo_root):
        deleted_remote = git.delete_remote_branches(repo_root, branches)
        already_gone = len(branches) - len(deleted_remote)
        user_output(
            f"deleted {len(deleted_remote)} remote branch(es) on origin "
            f"({already_gone} already gone)"
        )

    # f. Summary.
    user_output(f"wiped {removed} worktree(s); {skipped} skipped")
