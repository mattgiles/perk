import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli
from perk.substrate import git


def _sha(repo, ref: str = "HEAD") -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_cleanup_removes_registered_worktree(git_repo, monkeypatch):
    wt = git_repo / ".worktrees" / "review-7"
    git.worktree_add_detached(git_repo, wt, _sha(git_repo))
    monkeypatch.chdir(git_repo)

    result = CliRunner().invoke(cli, ["pr", "review", "cleanup", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["success"] is True
    assert data["pr"] == 7
    assert data["removed"] is True
    assert Path(data["path"]).resolve() == wt.resolve()
    assert not wt.exists()
    # The admin entry is pruned too.
    assert "review-7" not in {w.path.name for w in git.worktree_list(git_repo)}


def test_cleanup_is_idempotent(git_repo, monkeypatch):
    wt = git_repo / ".worktrees" / "review-7"
    git.worktree_add_detached(git_repo, wt, _sha(git_repo))
    monkeypatch.chdir(git_repo)
    runner = CliRunner()

    first = runner.invoke(cli, ["pr", "review", "cleanup", "--pr", "7", "--json"])
    assert json.loads(first.stdout)["removed"] is True
    second = runner.invoke(cli, ["pr", "review", "cleanup", "--pr", "7", "--json"])
    assert second.exit_code == 0
    data = json.loads(second.stdout)
    assert data["success"] is True
    assert data["removed"] is False


def test_cleanup_removes_dirty_worktree(git_repo, monkeypatch):
    # The force posture: the checkout is disposable investigation material — dirty is removed.
    wt = git_repo / ".worktrees" / "review-7"
    git.worktree_add_detached(git_repo, wt, _sha(git_repo))
    (wt / "scribble.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.chdir(git_repo)

    result = CliRunner().invoke(cli, ["pr", "review", "cleanup", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["removed"] is True
    assert not wt.exists()


def test_cleanup_removes_unregistered_leftover_dir(git_repo, monkeypatch):
    # The rmtree arm: a plain dir at the review path (never a registered worktree).
    wt = git_repo / ".worktrees" / "review-7"
    wt.mkdir(parents=True)
    (wt / "residue.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.chdir(git_repo)

    result = CliRunner().invoke(cli, ["pr", "review", "cleanup", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["removed"] is True
    assert not wt.exists()


def test_cleanup_deletes_leftover_temp_ref(git_repo, monkeypatch):
    subprocess.run(
        ["git", "update-ref", "refs/perk/review/7", "HEAD"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(git_repo)

    result = CliRunner().invoke(cli, ["pr", "review", "cleanup", "--pr", "7", "--json"])
    assert result.exit_code == 0
    assert git.resolve_commit(git_repo, "refs/perk/review/7") is None


def test_cleanup_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "review", "cleanup", "--pr", "7", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"
