from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli
from perk.cli.context import PerkContext
from perk.config import Config


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


def test_all_stages_are_generated():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for stage_id in ("plan", "save", "implement", "submit", "address", "land", "learn"):
        assert stage_id in result.output


def test_remote_door_blocked():
    result = CliRunner().invoke(cli, ["plan", "--remote"], obj=_ctx(Path("/repo")))
    assert result.exit_code == 1
    assert "remote target is Phase 3" in result.output


def test_implement_requires_plan_ref():
    # T4a: implement derives the worktree from the active plan-ref; with none, it asks for a plan.
    result = CliRunner().invoke(cli, ["implement"], obj=_ctx(Path("/repo")))
    assert result.exit_code == 1
    assert "needs a saved plan" in result.output


def test_worktree_create_list_remove(git_repo):
    runner = CliRunner()
    obj = _ctx(git_repo)
    created = runner.invoke(cli, ["worktree", "create", "wt1"], obj=obj)
    assert created.exit_code == 0, created.output
    assert (git_repo / ".worktrees" / "wt1").is_dir()

    listed = runner.invoke(cli, ["worktree", "list"], obj=obj)
    assert "wt1" in listed.output

    removed = runner.invoke(cli, ["worktree", "remove", "wt1"], obj=obj)
    assert removed.exit_code == 0, removed.output
    assert not (git_repo / ".worktrees" / "wt1").exists()
