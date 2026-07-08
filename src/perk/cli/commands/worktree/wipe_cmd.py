"""`perk worktree wipe` — remove merged, safe-to-delete plan worktrees.

Beyond registered worktrees, wipe also sweeps what git no longer tracks: unregistered
`plan-*` residue dirs (structurally classified, fully offline) and stranded local `plan-*`
branches whose PR is provably MERGED.
"""

import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import click

from perk.backends import issue_backend, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.context import require_config, require_repo
from perk.cli.ensure import Ensure
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
    """Remove all merged, safe-to-delete plan-<N> worktrees (and their branches).

    Also sweeps unregistered plan-* residue dirs (no .git entry) and deletes stranded
    local plan-* branches whose PR is merged.
    """
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


def _gather_branch_pr_state(*, backend: issue_backend.IssueBackend, plan_id: str) -> str | None:
    """PR state for a stranded branch's plan, or ``None`` when undeterminable (⇒ keep).

    Runs on worker threads; never writes output. Uncertainty ⇒ skip: a backend error, a
    missing plan issue, or no linked PR all yield ``None`` and the branch survives.
    """
    try:
        state = backend.get_plan(issue_id=plan_id)
    except IssueBackendError:
        return None
    if state is None or state.pr is None:
        return None
    return state.pr.state


_PLAN_WT_RE = re.compile(r"^plan-(\S+)$")


def _plan_id(name: str) -> str | None:
    """The opaque plan id from a ``plan-<id>`` worktree name (``plan-42`` / ``plan-ENG-123``),
    or None if not a plan worktree."""
    m = _PLAN_WT_RE.match(name)
    return m.group(1) if m else None


def _skip(name: str, reason: str) -> None:
    user_output(f"  skip {name}: {reason}")


@dataclass(frozen=True)
class _Residue:
    """An unregistered ``plan-*`` entry under the worktree root (not a worktree per git)."""

    path: Path
    skip_reason: str | None  # None = structurally removable (no .git entry)


def _enumerate_residue(
    *, wt_root: Path, repo_resolved: Path, registered: set[Path]
) -> list[_Residue]:
    """Unregistered ``plan-*`` entries under the worktree root, classified structurally.

    Residue is what a timed-out removal plus a later ``git worktree prune`` leaves: a partial
    dir git no longer registers, invisible to the registered-candidate sweep. Classification
    is main-thread and fully offline — residue holds no checkout, so there is no PR state to
    protect: no ``.git`` entry ⇒ provably not a worktree ⇒ removable; a ``.git`` (or a
    non-dir / symlink) ⇒ skip with a reason. Name-sorted for deterministic reporting.
    """
    if not wt_root.is_dir():
        return []
    residue: list[_Residue] = []
    for entry in sorted(wt_root.iterdir()):
        if not _PLAN_WT_RE.match(entry.name):
            continue
        resolved = entry.resolve()  # resolve BOTH sides (the macOS /var→/private/var rule)
        if resolved in registered or resolved == repo_resolved:
            continue
        if entry.is_symlink() or not entry.is_dir():
            residue.append(_Residue(path=entry, skip_reason="not a directory — not touching"))
        elif (entry / ".git").exists():
            residue.append(
                _Residue(
                    path=entry,
                    skip_reason=(
                        "unregistered but has a .git — not touching "
                        "(use git worktree / remove manually)"
                    ),
                )
            )
        else:
            residue.append(_Residue(path=entry, skip_reason=None))
    return residue


def _enumerate_stranded_branches(
    repo_root: Path, *, all_worktrees: list[git.Worktree]
) -> list[str]:
    """Local ``plan-*`` branches checked out in NO worktree (stranded-branch candidates).

    Subtracting every checked-out branch excludes the current checkout, the registered plan
    worktrees (their branches ride the removed-worktree delete path), and any non-plan
    worktree.
    """
    checked_out = {wt.branch for wt in all_worktrees if wt.branch}
    return [
        b
        for b in git.local_branches(repo_root, "plan-*")
        if _PLAN_WT_RE.match(b) and b not in checked_out
    ]


def _wipe_impl(*, repo_root: Path, worktree_root: Path, dry_run: bool, force: bool) -> None:
    wt_root = worktree_root.resolve()
    repo_resolved = repo_root.resolve()
    all_worktrees = git.worktree_list(repo_root)
    candidates = [
        wt
        for wt in all_worktrees
        if wt.path.parent.resolve() == wt_root and _PLAN_WT_RE.match(wt.path.name)
    ]
    residue = _enumerate_residue(
        wt_root=wt_root,
        repo_resolved=repo_resolved,
        registered={wt.path.resolve() for wt in all_worktrees},
    )
    stranded = _enumerate_stranded_branches(repo_root, all_worktrees=all_worktrees)
    if not candidates and not residue and not stranded:
        user_output("no plan worktrees to wipe")
        return

    # Partition on the main thread: current-worktree skips never reach the gather pool.
    # (Never wipe the worktree the command is being run from — git refuses; surface clearly.)
    targets = [wt for wt in candidates if wt.path.resolve() != repo_resolved]

    # Gather phase: collect per-worktree facts + stranded-branch PR states concurrently
    # (read-only, no output from workers). The backend is resolved only when a PR-gated
    # candidate exists — a residue-only sweep is fully offline and needs no backend at all.
    facts_by_path: dict[Path, _GatheredFacts] = {}
    branch_pr_state: dict[str, str | None] = {}
    if targets or stranded:
        try:
            backend = resolve.resolve_issue_backend(repo_root)
        except IssueBackendError as exc:
            # Offline ⇒ no-op posture: every PR-gated candidate is skipped; residue still sweeps.
            reason = f"could not determine PR state ({exc})"
            facts_by_path = {
                wt.path: _GatheredFacts(
                    skip_reason=reason, pr_state=None, is_dirty=False, has_pending_learn=False
                )
                for wt in targets
            }
            branch_pr_state = {b: None for b in stranded}
        else:
            if targets:
                user_output(f"checking {len(targets)} plan worktree(s)…")
            workers = min(_MAX_GATHER_WORKERS, len(targets) + len(stranded))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {}
                for wt in targets:
                    plan_id = Ensure.not_none(
                        _plan_id(wt.path.name),  # non-None by the regex filter above
                        f"could not derive a plan id from worktree name {wt.path.name!r}",
                    )
                    futures[wt.path] = pool.submit(
                        lambda p=wt.path, i=plan_id: _gather_facts(
                            backend=backend, wt_path=p, plan_id=i
                        )
                    )
                branch_futures = {}
                for branch in stranded:
                    branch_plan_id = Ensure.not_none(
                        _plan_id(branch),  # non-None by the regex filter above
                        f"could not derive a plan id from branch name {branch!r}",
                    )
                    branch_futures[branch] = pool.submit(
                        lambda i=branch_plan_id: _gather_branch_pr_state(backend=backend, plan_id=i)
                    )
                # Unexpected (non-IssueBackendError) worker exceptions propagate here —
                # same crash semantics as the previous inline code.
                facts_by_path = {path: fut.result() for path, fut in futures.items()}
                branch_pr_state = {b: fut.result() for b, fut in branch_futures.items()}

    # Stranded-branch classification: delete iff the PR is provably MERGED (--force does not
    # relax this — a stranded branch has no working tree, so there is no local guard to bypass).
    stranded_delete = [b for b in stranded if branch_pr_state.get(b) == "MERGED"]
    stranded_skipped = len(stranded) - len(stranded_delete)

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
        pr_state = Ensure.not_none(
            facts.pr_state,
            f"no PR state gathered for worktree {wt.path.name!r} (and no skip reason recorded)",
        )
        decision = _classify_worktree(
            pr_state=pr_state,
            is_dirty=facts.is_dirty,
            has_pending_learn=facts.has_pending_learn,
            force=force,
        )
        if not decision.remove:
            skip_reasons[wt.path] = decision.reason
            continue
        to_remove.append(wt)

    # b. Dry-run: report intent, no git mutations, no pool.
    if dry_run:
        for wt in candidates:
            reason = skip_reasons.get(wt.path)
            if reason is not None:
                _skip(wt.path.name, reason)
            elif wt in to_remove:
                user_output(f"  would remove {wt.path.name}  (PR merged)")
        residue_removable = 0
        for res in residue:
            if res.skip_reason is not None:
                _skip(res.path.name, res.skip_reason)
            else:
                user_output(
                    f"  would remove {res.path.name}  (residue — not a registered worktree)"
                )
                residue_removable += 1
        summary = f"would wipe {len(to_remove)} worktree(s)"
        if residue:
            summary += f" + {residue_removable} residue dir(s)"
        residue_skips = sum(1 for r in residue if r.skip_reason is not None)
        user_output(summary + f"; {len(skip_reasons) + residue_skips} skipped")
        if to_remove:
            user_output(
                f"  would delete {len(to_remove)} local + {len(to_remove)} remote branch(es)"
            )
        if stranded:
            user_output(
                f"  would delete {len(stranded_delete)} stranded local branch(es); "
                f"{stranded_skipped} skipped"
            )
        return

    # c. Removal pool: parallel FS rm -rf (lock-free). No output from worker threads. Residue
    #    rmtrees ride the SAME pool — they are the same heavy FS deletes, so a combined pool
    #    keeps the disk-thrash worker cap meaningful.
    removal_errors: dict[Path, GitError] = {}
    residue_errors: dict[Path, OSError] = {}
    residue_to_remove = [res.path for res in residue if res.skip_reason is None]
    if to_remove or residue_to_remove:
        workers = min(_MAX_REMOVE_WORKERS, len(to_remove) + len(residue_to_remove))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                wt.path: pool.submit(
                    lambda p=wt.path: git.worktree_remove(repo_root, p, force=force)
                )
                for wt in to_remove
            }
            residue_futures = {
                path: pool.submit(lambda p=path: shutil.rmtree(p)) for path in residue_to_remove
            }
            for path, fut in futures.items():
                try:
                    fut.result()  # success → None; non-GitError propagates (crash, as before)
                except GitError as exc:
                    removal_errors[path] = exc
            for path, fut in residue_futures.items():
                try:
                    fut.result()
                except OSError as exc:
                    residue_errors[path] = exc

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

    # One name-sorted residue pass after the candidate pass: skip lines + removal results.
    residue_removed = 0
    for res in residue:
        name = res.path.name
        if res.skip_reason is not None:
            _skip(name, res.skip_reason)
            skipped += 1
            continue
        os_exc = residue_errors.get(res.path)
        if os_exc is not None:
            _skip(name, f"residue removal failed: {os_exc}")
            skipped += 1
            continue
        user_output(click.style("✓ ", fg="green") + f"removed {name} (residue)")
        residue_removed += 1

    # Prune stale admin entries BEFORE branch deletes. A fallback-path removal leaves a stale
    # `.git/worktrees/<id>` entry; until it is pruned git still believes the (deleted) dir has the
    # plan branch checked out and refuses `git branch -D` with "checked out at …". This single
    # serialized prune also sweeps pre-existing orphan admin entries already on disk.
    git.worktree_prune(repo_root)

    # d. Batched local branch delete (-D: the PR is provably MERGED, so force is safe).
    #    Stranded MERGED branches ride the same batch — aggregate their report (one line,
    #    not one per branch) and only when stranded candidates exist.
    if stranded:
        user_output(
            f"stranded branch(es): {len(stranded_delete)} to delete, "
            f"{stranded_skipped} skipped (not merged or undeterminable)"
        )
    branches = [wt.branch or wt.path.name for wt in removed_worktrees] + stranded_delete
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

    # f. Summary. The residue segment appears only when residue candidates were found, so
    #    residue-free output (and its test pins) stays byte-identical.
    summary = f"wiped {removed} worktree(s)"
    if residue:
        summary += f" + {residue_removed} residue dir(s)"
    user_output(summary + f"; {skipped} skipped")
