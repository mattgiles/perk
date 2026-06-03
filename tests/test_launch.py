import json
import subprocess

import pytest

from perk import cache
from perk.cli.ensure import UserFacingCliError
from perk.config import Config
from perk.launch import (
    _initial_prompt,
    launch_stage,
    resolve_plan_worktree_name,
    resolve_worktree,
)
from perk.registry import Stage, load_registry

_PLAN_REF = {
    "provider": "github",
    "pr_id": "42",
    "url": "https://gh/o/r/issues/42",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _stage(stage_id: str) -> Stage:
    return next(s for s in load_registry().stages if s.id == stage_id)


def _config(tmp_path) -> Config:
    return Config(worktree_root=tmp_path / ".worktrees")


def test_resolve_worktree_none_is_repo_root(tmp_path):
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        materialize=True,
    )
    assert resolved.path == tmp_path
    assert resolved.plan_ref is None


# --- T4a: plan-ref-aware worktree resolution -------------------------------------------


@pytest.mark.parametrize(
    ("pr_id", "expected"),
    [("42", "plan-42"), ("PROJ-123", "plan-PROJ-123")],
)
def test_resolve_plan_worktree_name(pr_id, expected):
    assert resolve_plan_worktree_name({"pr_id": pr_id}) == expected


@pytest.mark.parametrize("pr_id", ["", "a/b", ".", ".."])
def test_resolve_plan_worktree_name_rejects_unusable(pr_id):
    with pytest.raises(UserFacingCliError, match="unusable as a worktree name"):
        resolve_plan_worktree_name({"pr_id": pr_id})


def test_implement_no_plan_ref_errors(tmp_path):
    with pytest.raises(UserFacingCliError, match="needs a saved plan") as exc:
        resolve_worktree(
            repo_root=tmp_path,
            config=_config(tmp_path),
            stage=_stage("implement"),
            worktree=None,
            materialize=False,
        )
    assert exc.value.error_type == "no_plan_ref"


def test_implement_derives_name_from_active_plan_ref(tmp_path):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        materialize=False,  # dry-run: derive without creating
    )
    assert resolved.path == _config(tmp_path).worktree_root / "plan-42"
    assert resolved.plan_ref == _PLAN_REF


def test_implement_dry_run_json_carries_worktree_and_plan_ref(tmp_path, capsys):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    assert data["stage"] == "implement"
    assert data["worktree"].endswith("/plan-42")
    assert data["plan_ref"] == _PLAN_REF
    # Bug 1 (P1.T4c): the implement launch is primed — argv carries the initial prompt.
    assert data["argv"][0] == "pi"
    assert len(data["argv"]) == 2
    assert "gh issue view 42 --comments" in data["argv"][1]
    # dry run is side-effect-free: no worktree, no handoff
    assert not (_config(tmp_path).worktree_root / "plan-42").exists()


def test_initial_prompt_primes_implement_and_address():
    """P1.T4c Bug 1 + P2.T7: implement and address are primed; other stages launch unprimed."""
    impl = _initial_prompt(_stage("implement"), _PLAN_REF)
    assert impl is not None and "gh issue view 42 --comments" in impl and "/submit" in impl
    addr = _initial_prompt(_stage("address"), _PLAN_REF)
    assert addr is not None and "perk-address" in addr and "review-classifier" in addr
    assert _initial_prompt(_stage("plan"), _PLAN_REF) is None
    assert _initial_prompt(_stage("implement"), None) is None
    assert _initial_prompt(_stage("address"), None) is None


def test_implement_materializes_worktree_and_is_idempotent(git_repo, monkeypatch):
    """Real-git integration (D4/D5): implement creates plan-<pr_id> + branch, materializes
    handoff + plan-ref into it, and reuses the worktree on a second run."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")

    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr("perk.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.launch.os.execvpe", lambda f, a, e: execs.append((f, list(a))))
    # Don't shell gh in this real-git integration test (the plan-body fetch is its own test).
    monkeypatch.setattr("perk.launch.github.get_plan_body", lambda **_k: None)

    def _run() -> None:
        launch_stage(
            repo_root=git_repo,
            config=config,
            stage=_stage("implement"),
            worktree=None,
            dry_run=False,
            remote=None,
            pi_args=[],
        )

    _run()
    wt = config.worktree_root / "plan-42"
    assert wt.is_dir()
    assert (wt / ".git").exists()  # a real linked worktree
    # plan-ref + handoff materialized into the worktree
    assert cache.read_plan_ref(wt) == _PLAN_REF
    handoffs = list((wt / ".pi" / "workflow" / "handoff").glob("*.json"))
    assert len(handoffs) == 1
    assert execs and execs[0][0] == "pi"

    # branch plan-42 exists
    branches = subprocess.run(
        ["git", "branch", "--list", "plan-42"], cwd=git_repo, capture_output=True, text=True
    ).stdout
    assert "plan-42" in branches

    # second run: idempotent reuse — no error, no duplicate branch creation
    _run()
    assert len(execs) == 2  # launched again
    assert wt.is_dir()


def test_implement_materializes_plan_body_for_checkpoints(git_repo, monkeypatch):
    """P2.T2c: the cold door caches the plan body into the worktree so in-session checkpoints can
    seed from its `## Steps` list."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    monkeypatch.setattr("perk.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.launch.os.execvpe", lambda f, a, e: None)
    markdown = "# Add retry\n\n## Steps\n1. Add helper\n2. Wire it in\n"
    monkeypatch.setattr("perk.launch.github.get_plan_body", lambda **_k: markdown)

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    wt = config.worktree_root / "plan-42"
    assert cache.plan_body_path(wt).read_text(encoding="utf-8").strip() == markdown.strip()


def test_implement_plan_body_fetch_is_best_effort(git_repo, monkeypatch, capsys):
    """A GitHub failure fetching the body never blocks the launch (checkpoints stay inert)."""
    from perk.github import GitHubError

    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    execs: list[str] = []
    monkeypatch.setattr("perk.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.launch.os.execvpe", lambda f, a, e: execs.append(f))

    def boom(**_k):
        raise GitHubError("gh unreachable")

    monkeypatch.setattr("perk.launch.github.get_plan_body", boom)
    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    wt = config.worktree_root / "plan-42"
    assert execs == ["pi"], "launch still proceeded"
    assert not cache.plan_body_path(wt).exists(), "no body cached on fetch failure"
    assert "could not fetch plan #42 body" in capsys.readouterr().err


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
