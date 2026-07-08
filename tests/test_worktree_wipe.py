from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.cli.commands.worktree.wipe_cmd import _classify_worktree
from perk.cli.context import PerkContext
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import Config


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


def _plan_state(state: str) -> plans.PlanState:
    return plans.PlanState(
        number=1,
        url="https://gh/o/r/issues/1",
        title="t",
        header={},
        pr=github.PullRequest(number=1, url="u", is_draft=False, state=state, existed=True),
        state="OPEN",
    )


# --- _classify_worktree unit matrix (pure, no I/O) -------------------------


def test_classify_merged_clean_removes():
    d = _classify_worktree(pr_state="MERGED", is_dirty=False, has_pending_learn=False, force=False)
    assert d.remove


def test_classify_merged_dirty_skips_unless_force():
    skip = _classify_worktree(
        pr_state="MERGED", is_dirty=True, has_pending_learn=False, force=False
    )
    assert not skip.remove and "uncommitted" in skip.reason
    forced = _classify_worktree(
        pr_state="MERGED", is_dirty=True, has_pending_learn=False, force=True
    )
    assert forced.remove


def test_classify_merged_pending_learn_skips_unless_force():
    skip = _classify_worktree(
        pr_state="MERGED", is_dirty=False, has_pending_learn=True, force=False
    )
    assert not skip.remove and "pending-learn" in skip.reason
    forced = _classify_worktree(
        pr_state="MERGED", is_dirty=False, has_pending_learn=True, force=True
    )
    assert forced.remove


@pytest.mark.parametrize("state", ["OPEN", "CLOSED"])
def test_classify_unmerged_skips_even_with_force(state):
    for force in (False, True):
        d = _classify_worktree(pr_state=state, is_dirty=False, has_pending_learn=False, force=force)
        assert not d.remove and "not merged" in d.reason


# --- command-level tests ---------------------------------------------------


def _add_plan_wt(repo: Path, n: int) -> Path:
    path = repo / ".worktrees" / f"plan-{n}"
    git.worktree_add(repo, path, branch=f"plan-{n}", create_branch=True)
    return path


def _branches(repo: Path) -> set[str]:
    import subprocess

    out = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return set(out.split())


def test_wipe_happy_path(git_repo, monkeypatch):
    _add_plan_wt(git_repo, 1)
    _add_plan_wt(git_repo, 2)

    def fake_get_plan(*, number: int, repo_root: Path) -> plans.PlanState:
        return _plan_state("MERGED" if number == 1 else "OPEN")

    monkeypatch.setattr(plans, "get_plan", fake_get_plan)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()
    assert (git_repo / ".worktrees" / "plan-2").exists()
    assert "plan-1" in result.output
    assert "skip plan-2" in result.output
    assert "wiped 1 worktree(s); 1 skipped" in result.output
    assert "plan-1" not in _branches(git_repo)
    assert "plan-2" in _branches(git_repo)
    # No origin remote on git_repo: the remote step is a clean no-op (emits nothing).
    assert "remote branch" not in result.output


def test_wipe_dry_run(git_repo, monkeypatch):
    _add_plan_wt(git_repo, 1)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert "would remove plan-1" in result.output
    assert "would wipe 1 worktree(s)" in result.output
    # Dry-run mutates nothing: branch still present, no remote step.
    assert "plan-1" in _branches(git_repo)
    assert "deleted" not in result.output


def test_wipe_dirty_guard(git_repo, monkeypatch):
    wt = _add_plan_wt(git_repo, 1)
    (wt / "dirty.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    skipped = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert "uncommitted changes" in skipped.output

    forced = CliRunner().invoke(cli, ["worktree", "wipe", "--force"], obj=_ctx(git_repo))
    assert forced.exit_code == 0, forced.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()


def test_wipe_pending_learn_guard(git_repo, monkeypatch):
    # perk init gitignores the .perk/workflow/ cache tree in real repos; mirror that so the
    # pending-learn marker alone is the signal (not an untracked-file dirty state).
    (git_repo / ".git" / "info" / "exclude").write_text(".perk/\n", encoding="utf-8")
    wt = _add_plan_wt(git_repo, 1)
    cache.set_marker(wt, cache.PENDING_LEARN)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    skipped = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert "pending-learn" in skipped.output

    forced = CliRunner().invoke(cli, ["worktree", "wipe", "--force"], obj=_ctx(git_repo))
    assert forced.exit_code == 0, forced.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()


def test_wipe_undeterminable_skips(git_repo, monkeypatch):
    _add_plan_wt(git_repo, 1)

    def boom(**k):
        raise github.GitHubError("offline")

    monkeypatch.setattr(plans, "get_plan", boom)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert "could not determine PR state" in result.output


def test_wipe_ignores_non_plan_worktrees(git_repo, monkeypatch):
    git.worktree_add(
        git_repo, git_repo / ".worktrees" / "feature-x", branch="feature-x", create_branch=True
    )
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "feature-x").exists()
    assert "feature-x" not in result.output
    assert "no plan worktrees to wipe" in result.output


def test_wipe_gathers_concurrently(git_repo, monkeypatch):
    """Both get_plan calls must be in flight simultaneously (parallel gather phase)."""
    import threading

    _add_plan_wt(git_repo, 1)
    _add_plan_wt(git_repo, 2)
    barrier = threading.Barrier(2, timeout=10)

    def fake_get_plan(*, number: int, repo_root: Path) -> plans.PlanState:
        barrier.wait()  # times out (BrokenBarrierError) if gathering were sequential
        return _plan_state("MERGED")

    monkeypatch.setattr(plans, "get_plan", fake_get_plan)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()
    assert not (git_repo / ".worktrees" / "plan-2").exists()
    assert "wiped 2 worktree(s); 0 skipped" in result.output


def test_wipe_output_in_candidate_order(git_repo, monkeypatch):
    """Per-worktree lines appear in worktree-name order regardless of gather completion order."""
    for n in (1, 2, 3):
        _add_plan_wt(git_repo, n)
    states = {1: "MERGED", 2: "OPEN", 3: "MERGED"}

    def fake_get_plan(*, number: int, repo_root: Path) -> plans.PlanState:
        return _plan_state(states[number])

    monkeypatch.setattr(plans, "get_plan", fake_get_plan)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    positions = [result.output.index(f"plan-{n}") for n in (1, 2, 3)]
    assert positions == sorted(positions), result.output


def test_wipe_backend_resolution_failure_skips_all(git_repo, monkeypatch):
    from perk.backends import resolve
    from perk.backends.issue_backend import IssueBackendError

    _add_plan_wt(git_repo, 1)
    _add_plan_wt(git_repo, 2)

    def boom(repo_root: Path):
        raise IssueBackendError("offline")

    monkeypatch.setattr(resolve, "resolve_issue_backend", boom)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert (git_repo / ".worktrees" / "plan-2").exists()
    assert result.output.count("could not determine PR state") == 2
    assert "wiped 0 worktree(s); 2 skipped" in result.output


def test_wipe_removes_worktrees_concurrently(git_repo, monkeypatch):
    """Both worktree removals must be in flight simultaneously (parallel removal pool)."""
    import threading

    _add_plan_wt(git_repo, 1)
    _add_plan_wt(git_repo, 2)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))

    barrier = threading.Barrier(2, timeout=10)
    real_remove = git.worktree_remove

    def gated_remove(repo, path, *, force):
        barrier.wait()  # times out (BrokenBarrierError) if removal were sequential
        return real_remove(repo, path, force=force)

    from perk.cli.commands.worktree import wipe_cmd

    monkeypatch.setattr(wipe_cmd.git, "worktree_remove", gated_remove)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()
    assert not (git_repo / ".worktrees" / "plan-2").exists()
    assert "plan-1" not in _branches(git_repo)
    assert "plan-2" not in _branches(git_repo)
    assert "wiped 2 worktree(s); 0 skipped" in result.output


def test_wipe_removal_failure_isolation(git_repo, monkeypatch):
    """One worktree's removal failure is isolated: the other still wipes, its branch deletes."""
    _add_plan_wt(git_repo, 1)
    _add_plan_wt(git_repo, 2)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))

    real_remove = git.worktree_remove

    def flaky_remove(repo, path, *, force):
        if path.name == "plan-1":
            raise git.GitError("boom")
        return real_remove(repo, path, force=force)

    from perk.cli.commands.worktree import wipe_cmd

    monkeypatch.setattr(wipe_cmd.git, "worktree_remove", flaky_remove)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert not (git_repo / ".worktrees" / "plan-2").exists()
    assert "git worktree remove failed" in result.output
    assert "plan-1" in _branches(git_repo)  # kept (removal failed)
    assert "plan-2" not in _branches(git_repo)  # deleted
    assert "wiped 1 worktree(s); 1 skipped" in result.output


def test_wipe_force_deletes_branch_ahead_of_trunk(git_repo, monkeypatch):
    """A merged plan branch with a commit not in local trunk must still be deleted (-D, not -d)."""
    wt = _add_plan_wt(git_repo, 1)
    import subprocess

    (wt / "extra.txt").write_text("ahead\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=wt, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "ahead of trunk"], cwd=wt, check=True, capture_output=True
    )
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()
    assert "plan-1" not in _branches(git_repo)  # -D forced through despite being ahead


# --- remote-branch deletion (git_repo_with_remote) -------------------------


def _ctx_remote(clone: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=clone, repo_root=clone, config=Config(worktree_root=clone / ".worktrees")
    )


def _push_plan_branch(clone: Path, n: int) -> None:
    import subprocess

    subprocess.run(
        ["git", "push", "-q", "origin", f"plan-{n}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    )


def _remote_heads(clone: Path) -> str:
    import subprocess

    return subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_wipe_deletes_remote_branches(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    _add_plan_wt(clone, 1)
    _add_plan_wt(clone, 2)
    _push_plan_branch(clone, 1)
    _push_plan_branch(clone, 2)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx_remote(clone))
    assert result.exit_code == 0, result.output
    heads = _remote_heads(clone)
    assert "plan-1" not in heads and "plan-2" not in heads
    assert "plan-1" not in _branches(clone) and "plan-2" not in _branches(clone)
    assert "deleted 2 remote branch(es) on origin" in result.output


def test_wipe_remote_blind_batch_tolerates_already_gone(git_repo_with_remote, monkeypatch):
    """A branch never pushed to origin is harmlessly tolerated (blind batch)."""
    clone, _remote, _advance = git_repo_with_remote
    _add_plan_wt(clone, 1)
    _add_plan_wt(clone, 2)
    _push_plan_branch(clone, 1)  # plan-2 never pushed → already "gone" on origin
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx_remote(clone))
    assert result.exit_code == 0, result.output
    heads = _remote_heads(clone)
    assert "plan-1" not in heads
    assert "deleted 1 remote branch(es) on origin (1 already gone)" in result.output


def test_wipe_empty(git_repo):
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "no plan worktrees to wipe" in result.output


# --- residue-dir sweep (unregistered plan-* dirs) ---------------------------


def _make_residue(repo: Path, name: str) -> Path:
    """An unregistered ``plan-*`` dir (no .git) with nested content under the worktree root."""
    d = repo / ".worktrees" / name
    (d / ".pi" / "npm" / "node_modules").mkdir(parents=True)
    (d / ".pi" / "npm" / "node_modules" / "junk.js").write_text("x\n", encoding="utf-8")
    return d


def test_wipe_sweeps_residue_dir(git_repo, monkeypatch):
    _add_plan_wt(git_repo, 1)
    residue = _make_residue(git_repo, "plan-77")
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not residue.exists()
    assert "✓ removed plan-77 (residue)" in result.output
    assert "wiped 1 worktree(s) + 1 residue dir(s); 0 skipped" in result.output


def test_wipe_residue_with_gitlink_skipped(git_repo, monkeypatch):
    """An unregistered dir that still carries a .git is never touched (skip with reason)."""
    _add_plan_wt(git_repo, 1)
    d = git_repo / ".worktrees" / "plan-88"
    d.mkdir(parents=True)
    (d / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert d.exists()
    assert "skip plan-88: unregistered but has a .git — not touching" in result.output
    assert "wiped 1 worktree(s) + 0 residue dir(s); 1 skipped" in result.output


def test_wipe_residue_only_resolves_no_backend(git_repo, monkeypatch):
    """A residue-only repo sweeps offline: the early return is gone, no backend is resolved."""
    from perk.backends import resolve

    residue = _make_residue(git_repo, "plan-77")

    def boom(repo_root: Path):
        raise AssertionError("backend must not be resolved for a residue-only sweep")

    monkeypatch.setattr(resolve, "resolve_issue_backend", boom)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not residue.exists()
    assert "removed plan-77 (residue)" in result.output
    assert "wiped 0 worktree(s) + 1 residue dir(s); 0 skipped" in result.output


def test_wipe_dry_run_previews_residue(git_repo):
    residue = _make_residue(git_repo, "plan-77")
    result = CliRunner().invoke(cli, ["worktree", "wipe", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert residue.exists()  # dry-run mutates nothing
    assert "would remove plan-77  (residue — not a registered worktree)" in result.output
    assert "would wipe 0 worktree(s) + 1 residue dir(s); 0 skipped" in result.output


def test_wipe_skips_plan_named_symlink(git_repo):
    target = git_repo / "elsewhere"
    target.mkdir()
    (target / "keep.txt").write_text("x\n", encoding="utf-8")
    (git_repo / ".worktrees").mkdir()
    link = git_repo / ".worktrees" / "plan-99"
    link.symlink_to(target)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert link.is_symlink()
    assert (target / "keep.txt").exists()
    assert "skip plan-99: not a directory — not touching" in result.output
    assert "wiped 0 worktree(s) + 0 residue dir(s); 1 skipped" in result.output


# --- stranded-branch sweep (local plan-* branches with no worktree) ---------


def _add_branch(repo: Path, name: str) -> None:
    import subprocess

    subprocess.run(["git", "branch", name], cwd=repo, check=True, capture_output=True, text=True)


def test_wipe_deletes_stranded_merged_branch(git_repo, monkeypatch):
    """A stranded MERGED branch is deleted; a stranded OPEN one is kept (aggregate report)."""
    _add_branch(git_repo, "plan-9")
    _add_branch(git_repo, "plan-10")

    def fake_get_plan(*, number: int, repo_root: Path) -> plans.PlanState:
        return _plan_state("MERGED" if number == 9 else "OPEN")

    monkeypatch.setattr(plans, "get_plan", fake_get_plan)

    dry = CliRunner().invoke(cli, ["worktree", "wipe", "--dry-run"], obj=_ctx(git_repo))
    assert dry.exit_code == 0, dry.output
    assert "would delete 1 stranded local branch(es); 1 skipped" in dry.output
    assert "plan-9" in _branches(git_repo)  # dry-run deletes nothing

    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "plan-9" not in _branches(git_repo)
    assert "plan-10" in _branches(git_repo)
    assert (
        "stranded branch(es): 1 to delete, 1 skipped (not merged or undeterminable)"
        in result.output
    )
    assert "deleted 1 local branch(es)" in result.output


def test_wipe_stranded_branch_undeterminable_kept(git_repo, monkeypatch):
    _add_branch(git_repo, "plan-9")

    def boom(**k):
        raise github.GitHubError("offline")

    monkeypatch.setattr(plans, "get_plan", boom)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "plan-9" in _branches(git_repo)
    assert (
        "stranded branch(es): 0 to delete, 1 skipped (not merged or undeterminable)"
        in result.output
    )


def test_wipe_offline_still_sweeps_residue(git_repo, monkeypatch):
    """Backend-resolution failure: worktrees + stranded branches skip, residue still sweeps."""
    from perk.backends import resolve
    from perk.backends.issue_backend import IssueBackendError

    _add_plan_wt(git_repo, 1)
    residue = _make_residue(git_repo, "plan-77")
    _add_branch(git_repo, "plan-9")

    def boom(repo_root: Path):
        raise IssueBackendError("offline")

    monkeypatch.setattr(resolve, "resolve_issue_backend", boom)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()  # PR-gated target skipped
    assert not residue.exists()  # residue is offline-sweepable
    assert "plan-9" in _branches(git_repo)  # stranded branch kept
    assert "could not determine PR state" in result.output
    assert "stranded branch(es): 0 to delete, 1 skipped" in result.output
    assert "wiped 0 worktree(s) + 1 residue dir(s); 1 skipped" in result.output


def test_wipe_stranded_branch_remote_delete(git_repo_with_remote, monkeypatch):
    """A pushed stranded MERGED branch rides the existing batched remote delete."""
    clone, _remote, _advance = git_repo_with_remote
    _add_branch(clone, "plan-9")
    _push_plan_branch(clone, 9)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx_remote(clone))
    assert result.exit_code == 0, result.output
    assert "plan-9" not in _branches(clone)
    assert "plan-9" not in _remote_heads(clone)
    assert "deleted 1 remote branch(es) on origin (0 already gone)" in result.output


def test_wipe_recovers_broken_worktree(git_repo, monkeypatch):
    wt = _add_plan_wt(git_repo, 1)
    # Reproduce the `validation failed … '.git' does not exist` mode a prior interrupted run left.
    (wt / ".git").unlink()
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state("MERGED"))
    # --force: the broken worktree's `git status` walks up to the (dirty) main test repo.
    result = CliRunner().invoke(cli, ["worktree", "wipe", "--force"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()
    assert "plan-1" not in {w.path.name for w in git.worktree_list(git_repo)}
    assert "plan-1" not in _branches(git_repo)
    assert "wiped 1 worktree(s)" in result.output
