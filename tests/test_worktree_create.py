import pytest

from perk.cli.commands.worktree.create_cmd import _create_impl
from perk.cli.ensure import UserFacingCliError
from perk.run import launch


def test_create_runs_setup_in_new_worktree(git_repo, monkeypatch):
    calls: list = []
    monkeypatch.setattr(launch, "run_worktree_setup", lambda path, cmds: calls.append((path, cmds)))
    _create_impl(
        repo_root=git_repo,
        worktree_root=git_repo / ".worktrees",
        worktree_setup=["uv sync"],
        name="feature",
        branch=None,
    )
    wt = git_repo / ".worktrees" / "feature"
    assert wt.is_dir()
    assert calls == [(wt, ["uv sync"])]


def test_create_no_setup_runs_nothing(git_repo, monkeypatch):
    calls: list = []
    monkeypatch.setattr(launch, "run_worktree_setup", lambda path, cmds: calls.append((path, cmds)))
    _create_impl(
        repo_root=git_repo,
        worktree_root=git_repo / ".worktrees",
        worktree_setup=[],
        name="feature",
        branch=None,
    )
    # run_worktree_setup is still called (it is a no-op on an empty list), with no commands.
    assert calls == [(git_repo / ".worktrees" / "feature", [])]


def test_create_setup_failure_surfaces_after_worktree_created(git_repo, monkeypatch):
    def _boom(_path, _cmds):
        raise UserFacingCliError("nope", error_type="worktree_setup_failed")

    monkeypatch.setattr(launch, "run_worktree_setup", _boom)
    with pytest.raises(UserFacingCliError) as exc:
        _create_impl(
            repo_root=git_repo,
            worktree_root=git_repo / ".worktrees",
            worktree_setup=["boom"],
            name="feature",
            branch=None,
        )
    assert exc.value.error_type == "worktree_setup_failed"
    # the worktree was created before the hook ran — left in place for a fixed re-run
    assert (git_repo / ".worktrees" / "feature").is_dir()
