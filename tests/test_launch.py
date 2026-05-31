import json

import pytest

from perk.cli.ensure import UserFacingCliError
from perk.config import Config
from perk.launch import launch_stage, resolve_worktree
from perk.registry import Stage, load_registry


def _stage(stage_id: str) -> Stage:
    return next(s for s in load_registry().stages if s.id == stage_id)


def _config(tmp_path) -> Config:
    return Config(worktree_root=tmp_path / ".worktrees")


def test_resolve_worktree_none_is_repo_root(tmp_path):
    wt = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        materialize=True,
    )
    assert wt == tmp_path


def test_implement_needs_worktree(tmp_path):
    with pytest.raises(UserFacingCliError, match="needs a worktree"):
        resolve_worktree(
            repo_root=tmp_path,
            config=_config(tmp_path),
            stage=_stage("implement"),
            worktree=None,
            materialize=False,
        )


def test_dry_run_has_no_side_effects(tmp_path, capsys):
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=["-p", "x"],
    )
    data = json.loads(capsys.readouterr().out)
    assert data["stage"] == "plan"
    assert data["argv"] == ["pi", "-p", "x"]
    # no handoff written on a dry run
    assert not (tmp_path / ".pi" / "workflow" / "handoff").exists()


def test_remote_is_blocked(tmp_path):
    with pytest.raises(UserFacingCliError, match="remote target is Phase 3"):
        launch_stage(
            repo_root=tmp_path,
            config=_config(tmp_path),
            stage=_stage("plan"),
            worktree=None,
            dry_run=False,
            remote="",
            pi_args=[],
        )
