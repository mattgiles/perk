from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github
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


def _plan_state(state: str) -> github.PlanState:
    return github.PlanState(
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

    def fake_get_plan(*, number: int, repo_root: Path) -> github.PlanState:
        return _plan_state("MERGED" if number == 1 else "OPEN")

    monkeypatch.setattr(github, "get_plan", fake_get_plan)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()
    assert (git_repo / ".worktrees" / "plan-2").exists()
    assert "plan-1" in result.output
    assert "skip plan-2" in result.output
    assert "wiped 1 worktree(s); 1 skipped" in result.output
    assert "plan-1" not in _branches(git_repo)
    assert "plan-2" in _branches(git_repo)


def test_wipe_dry_run(git_repo, monkeypatch):
    _add_plan_wt(git_repo, 1)
    monkeypatch.setattr(github, "get_plan", lambda **k: _plan_state("MERGED"))
    result = CliRunner().invoke(cli, ["worktree", "wipe", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert "would remove plan-1" in result.output
    assert "would wipe 1 worktree(s)" in result.output


def test_wipe_dirty_guard(git_repo, monkeypatch):
    wt = _add_plan_wt(git_repo, 1)
    (wt / "dirty.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(github, "get_plan", lambda **k: _plan_state("MERGED"))
    skipped = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert "uncommitted changes" in skipped.output

    forced = CliRunner().invoke(cli, ["worktree", "wipe", "--force"], obj=_ctx(git_repo))
    assert forced.exit_code == 0, forced.output
    assert not (git_repo / ".worktrees" / "plan-1").exists()


def test_wipe_pending_learn_guard(git_repo, monkeypatch):
    # perk init gitignores .pi/ in real repos; mirror that so the marker alone is the signal.
    (git_repo / ".git" / "info" / "exclude").write_text(".pi/\n", encoding="utf-8")
    wt = _add_plan_wt(git_repo, 1)
    cache.set_marker(wt, cache.PENDING_LEARN)
    monkeypatch.setattr(github, "get_plan", lambda **k: _plan_state("MERGED"))
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

    monkeypatch.setattr(github, "get_plan", boom)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert "could not determine PR state" in result.output


def test_wipe_ignores_non_plan_worktrees(git_repo, monkeypatch):
    git.worktree_add(
        git_repo, git_repo / ".worktrees" / "feature-x", branch="feature-x", create_branch=True
    )
    monkeypatch.setattr(github, "get_plan", lambda **k: _plan_state("MERGED"))
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

    def fake_get_plan(*, number: int, repo_root: Path) -> github.PlanState:
        barrier.wait()  # times out (BrokenBarrierError) if gathering were sequential
        return _plan_state("MERGED")

    monkeypatch.setattr(github, "get_plan", fake_get_plan)
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

    def fake_get_plan(*, number: int, repo_root: Path) -> github.PlanState:
        return _plan_state(states[number])

    monkeypatch.setattr(github, "get_plan", fake_get_plan)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    positions = [result.output.index(f"plan-{n}") for n in (1, 2, 3)]
    assert positions == sorted(positions), result.output


def test_wipe_backend_resolution_failure_skips_all(git_repo, monkeypatch):
    from perk.backends import issues
    from perk.backends.issue_backend import IssueBackendError

    _add_plan_wt(git_repo, 1)
    _add_plan_wt(git_repo, 2)

    def boom(repo_root: Path):
        raise IssueBackendError("offline")

    monkeypatch.setattr(issues, "resolve_issue_backend", boom)
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert (git_repo / ".worktrees" / "plan-1").exists()
    assert (git_repo / ".worktrees" / "plan-2").exists()
    assert result.output.count("could not determine PR state") == 2
    assert "wiped 0 worktree(s); 2 skipped" in result.output


def test_wipe_empty(git_repo):
    result = CliRunner().invoke(cli, ["worktree", "wipe"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "no plan worktrees to wipe" in result.output
