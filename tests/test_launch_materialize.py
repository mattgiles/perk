import dataclasses
import json
import subprocess
from pathlib import Path

import pytest
from _launch_helpers import _PLAN_REF, _PLAN_REF_MODEL, _config, _stage

from perk import __version__
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.run.launch import (
    launch_stage,
    materialize_extensions,
    materialize_skills,
    print_launch_banner,
    resolve_worktree,
)
from perk.run.launch.materialize import render_launch_banner
from perk.state import cache
from perk.substrate import git as git_mod
from perk.substrate.config import Config


def test_implement_materializes_worktree_and_is_idempotent(git_repo, monkeypatch):
    """Real-git integration (D4/D5): implement creates plan-<pr_id> + branch, materializes
    handoff + plan-ref into it, and reuses the worktree on a second run."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")

    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append((f, list(a))))
    # Don't shell gh in this real-git integration test (the plan-body fetch is its own test).
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)

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
    assert cache.read_plan_ref(wt) == _PLAN_REF_MODEL
    handoffs = list((wt / ".perk" / "workflow" / "handoff").glob("*.json"))
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


def test_launch_warms_extension_install_before_exec(git_repo, monkeypatch):
    # ensure_extension_install_present is invoked before os.execvpe on the local consumer path.
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    events: list[object] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    monkeypatch.setattr(
        launch.init,
        "ensure_extension_install_present",
        lambda repo_root, *, self_repo: events.append(("warm-install", repo_root, self_repo)),
    )
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: events.append("exec"))
    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert events == [("warm-install", git_repo, False), "exec"]  # warmed first, then exec


def test_launch_does_not_warm_on_dry_run(git_repo, monkeypatch, capsys):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    warmed: list = []
    monkeypatch.setattr(
        launch.init,
        "ensure_extension_install_present",
        lambda repo_root, *, self_repo: warmed.append(repo_root),
    )
    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    assert warmed == []  # --dry-run early-returns before the warm


def test_install_step_resolves_done_when_install_happens(git_repo, monkeypatch, capsys):
    """When the extension is absent and the warm actually installs (returns a change line), the
    installing step resolves to a done milestone."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: None)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    monkeypatch.setattr(
        launch.init,
        "ensure_extension_install_present",
        lambda repo_root, *, self_repo: "installed @mgiles/perk pre-launch",
    )
    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    err = capsys.readouterr().err
    assert "installing perk extension" in err
    assert "installed perk extension" in err  # the step resolved to ✓


def test_install_step_resolves_warn_when_install_did_not_take(git_repo, monkeypatch, capsys):
    """When the extension is absent and the warm returns None with the dir still absent (a swallowed
    failure), the installing step resolves to a warn rather than dangling."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: None)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    monkeypatch.setattr(
        launch.init, "ensure_extension_install_present", lambda repo_root, *, self_repo: None
    )
    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    err = capsys.readouterr().err
    assert "installing perk extension" in err
    assert "install failed" in err  # the step resolved to ⚠, never dangles


def _launch_capturing_env(git_repo, monkeypatch) -> dict[str, str]:
    """Drive a local implement launch, returning the env handed to ``os.execvpe``."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    captured: dict[str, dict[str, str]] = {}
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr(
        "perk.run.launch.os.execvpe", lambda _f, _a, e: captured.update(env=dict(e))
    )
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    return captured["env"]


def test_launch_seeds_linear_key_from_local_config_when_env_absent(git_repo, monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    cfg = git_repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "local.toml").write_text('[linear]\napi_key = "lin_api_local"\n', encoding="utf-8")
    env = _launch_capturing_env(git_repo, monkeypatch)
    assert env["LINEAR_API_KEY"] == "lin_api_local"


def test_launch_seeds_linear_key_from_main_checkout_when_rooted_in_worktree(git_repo, monkeypatch):
    # A `perk implement` launch rooted inside a linked worktree must still seed LINEAR_API_KEY
    # from the MAIN checkout's gitignored `.perk/local.toml` (never copied into worktrees).
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    cfg = git_repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "local.toml").write_text('[linear]\napi_key = "lin_api_main"\n', encoding="utf-8")
    wt = git_repo / ".worktrees" / "wt-launch"
    git_mod.worktree_add(git_repo, wt, branch="plan-launch", create_branch=True)

    cache.write_plan_ref(wt, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    captured: dict[str, dict[str, str]] = {}
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr(
        "perk.run.launch.os.execvpe", lambda _f, _a, e: captured.update(env=dict(e))
    )
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    launch_stage(
        repo_root=wt,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert captured["env"]["LINEAR_API_KEY"] == "lin_api_main"


def test_launch_exported_linear_key_wins_over_local_config(git_repo, monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_env")
    cfg = git_repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "local.toml").write_text('[linear]\napi_key = "lin_api_local"\n', encoding="utf-8")
    env = _launch_capturing_env(git_repo, monkeypatch)
    assert env["LINEAR_API_KEY"] == "lin_api_env"


class _Result:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_run_worktree_setup_empty_runs_nothing(tmp_path, monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    launch.run_worktree_setup(tmp_path, [])
    assert calls == []
    assert "running worktree setup" not in capsys.readouterr().err  # no header when empty


def test_run_worktree_setup_runs_each_command_in_order(tmp_path, monkeypatch, capsys):
    calls: list = []

    def _run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Result(0)

    monkeypatch.setattr(launch.subprocess, "run", _run)
    launch.run_worktree_setup(tmp_path, ["uv sync", "npm ci"])
    err = capsys.readouterr().err
    assert "running worktree setup" in err  # the header precedes the echoes
    assert "\u2713 worktree setup complete" in err  # the success path resolves the step
    assert [c[0] for c in calls] == [
        ["bash", "-lc", "uv sync"],
        ["bash", "-lc", "npm ci"],
    ]
    for _argv, kwargs in calls:
        assert kwargs["cwd"] == tmp_path
        assert kwargs["check"] is False
        assert kwargs["timeout"] == launch._WORKTREE_SETUP_TIMEOUT_S
        # the capture posture: output is swallowed on success, replayed only on failure
        assert kwargs["stdout"] is subprocess.PIPE
        assert kwargs["stderr"] is subprocess.STDOUT
        assert kwargs["text"] is True


def test_run_worktree_setup_swallows_command_output_on_success(tmp_path, monkeypatch, capsys):
    def _run(argv, **kwargs):
        return _Result(0, stdout="Resolved 28 packages\nInstalled 27 packages")

    monkeypatch.setattr(launch.subprocess, "run", _run)
    launch.run_worktree_setup(tmp_path, ["uv sync"])
    err = capsys.readouterr().err
    assert "Resolved 28 packages" not in err
    assert "Installed 27 packages" not in err
    assert "$ uv sync" in err  # the sub-bullet narrates the command
    assert "\u2713 worktree setup complete" in err


def test_run_worktree_setup_nonzero_aborts_and_stops(tmp_path, monkeypatch, capsys):
    calls: list = []

    def _run(argv, **kwargs):
        calls.append(argv)
        if argv[-1] == "ok":
            return _Result(0)
        return _Result(3, stdout="error: no solution found")

    monkeypatch.setattr(launch.subprocess, "run", _run)
    with pytest.raises(UserFacingCliError) as exc:
        launch.run_worktree_setup(tmp_path, ["ok", "boom", "never"])
    assert exc.value.error_type == "worktree_setup_failed"
    assert "boom" in str(exc.value)
    # stops at the failing command — "never" is not reached
    assert calls == [["bash", "-lc", "ok"], ["bash", "-lc", "boom"]]
    # the captured output is replayed to stderr before the raise (the failure diagnostics)
    assert "error: no solution found" in capsys.readouterr().err


def test_run_worktree_setup_timeout_aborts(tmp_path, monkeypatch):
    def _run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

    monkeypatch.setattr(launch.subprocess, "run", _run)
    with pytest.raises(UserFacingCliError) as exc:
        launch.run_worktree_setup(tmp_path, ["uv sync"])
    assert exc.value.error_type == "worktree_setup_failed"


def test_run_worktree_setup_missing_bash_aborts(tmp_path, monkeypatch):
    def _run(argv, **kwargs):
        raise FileNotFoundError("bash")

    monkeypatch.setattr(launch.subprocess, "run", _run)
    with pytest.raises(UserFacingCliError) as exc:
        launch.run_worktree_setup(tmp_path, ["uv sync"])
    assert exc.value.error_type == "worktree_setup_failed"


def test_resolve_worktree_created_true_on_fresh_create(git_repo):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    resolved = resolve_worktree(
        repo_root=git_repo,
        config=Config(worktree_root=git_repo / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        materialize=True,
    )
    assert resolved.created is True


def test_resolve_worktree_created_false_on_dry_run(tmp_path):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        materialize=False,
    )
    assert resolved.created is False


def test_resolve_worktree_created_false_on_reuse(git_repo):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")

    def _resolve():
        return resolve_worktree(
            repo_root=git_repo,
            config=config,
            stage=_stage("implement"),
            worktree=None,
            materialize=True,
        )

    assert _resolve().created is True  # fresh
    assert _resolve().created is False  # idempotent reuse


def test_resolve_worktree_created_false_on_worktree_none(tmp_path):
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        materialize=True,
    )
    assert resolved.created is False


def test_launch_runs_setup_before_exec_on_fresh_create(git_repo, monkeypatch):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees", worktree_setup=["uv sync", "npm ci"])
    events: list = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: events.append(("exec", f)))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    monkeypatch.setattr(
        launch, "run_worktree_setup", lambda wt, cmds: events.append(("setup", wt, cmds))
    )

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert events == [
        ("setup", config.worktree_root / "plan-42", ["uv sync", "npm ci"]),
        ("exec", "pi"),
    ]


def test_launch_setup_failure_aborts_before_exec(git_repo, monkeypatch):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees", worktree_setup=["boom"])
    execs: list = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append(f))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)

    def _boom(_wt, _cmds):
        raise UserFacingCliError("nope", error_type="worktree_setup_failed")

    monkeypatch.setattr(launch, "run_worktree_setup", _boom)
    with pytest.raises(UserFacingCliError) as exc:
        launch_stage(
            repo_root=git_repo,
            config=config,
            stage=_stage("implement"),
            worktree=None,
            dry_run=False,
            remote=None,
            pi_args=[],
        )
    assert exc.value.error_type == "worktree_setup_failed"
    assert execs == []  # exec pi was never reached


def test_launch_resume_does_not_run_setup(git_repo, monkeypatch):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees", worktree_setup=["uv sync"])
    setup_calls: list = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: None)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    monkeypatch.setattr(
        launch, "run_worktree_setup", lambda wt, cmds: setup_calls.append((wt, cmds))
    )

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

    _run()  # fresh create → setup runs
    _run()  # idempotent reuse → setup skipped
    assert len(setup_calls) == 1


def test_launch_dry_run_previews_setup_without_running(tmp_path, capsys, monkeypatch):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    config = Config(worktree_root=tmp_path / ".worktrees", worktree_setup=["uv sync", "npm ci"])
    setup_calls: list = []
    monkeypatch.setattr(
        launch, "run_worktree_setup", lambda wt, cmds: setup_calls.append((wt, cmds))
    )
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["setup"] == ["uv sync", "npm ci"]
    assert "would run setup: uv sync; npm ci" in (captured.out + captured.err)
    assert setup_calls == []  # never executed on a dry run


def _launch_and_capture_env(git_repo, monkeypatch) -> dict[str, str]:
    """Drive a real implement launch to the exec and capture the child env."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")

    envs: list[dict[str, str]] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: envs.append(dict(e)))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert len(envs) == 1
    return envs[0]


def test_launch_injects_npm_quiet_env(git_repo, monkeypatch):
    """The child env carries the npm-quieting vars so pi's startup npm installs inherit
    them, and PERK_RUN_ID survives the merge (regression guard)."""
    monkeypatch.delenv("npm_config_loglevel", raising=False)
    env = _launch_and_capture_env(git_repo, monkeypatch)
    assert env["npm_config_loglevel"] == "error"
    assert env["npm_config_fund"] == "false"
    assert env["npm_config_audit"] == "false"
    assert env["PERK_RUN_ID"]


def test_launch_npm_quiet_env_user_override_wins(git_repo, monkeypatch):
    """Setdefault semantics: an operator's own npm_config_* env var beats the injected map."""
    monkeypatch.setenv("npm_config_loglevel", "verbose")
    env = _launch_and_capture_env(git_repo, monkeypatch)
    assert env["npm_config_loglevel"] == "verbose"
    assert env["npm_config_fund"] == "false"


def test_launch_sweeps_stale_lock_before_exec(git_repo, monkeypatch, tmp_path):
    """Integration: the real launch path sweeps the stale agent-dir lock before exec'ing pi."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    stale = agent_dir / "settings.json.lock"
    stale.write_text("", encoding="utf-8")

    execs: list[str] = []
    monkeypatch.setattr("perk.run.launch._pi_agent_dir", lambda: agent_dir)
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append(f))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert not stale.exists()  # swept before exec
    assert execs == ["pi"]  # exec was reached


def test_implement_materializes_plan_body_for_checkpoints(git_repo, monkeypatch, capsys):
    """The cold door caches the plan body into the worktree so in-session checkpoints can
    seed from its `## Steps` list, narrating the fetch wait + its cached milestone."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: None)
    markdown = "# Add retry\n\n## Steps\n1. Add helper\n2. Wire it in\n"
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: markdown)

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
    err = capsys.readouterr().err
    assert "fetching plan #42 body" in err
    assert "cached plan #42 body" in err


def test_implement_plan_body_fetch_is_best_effort(git_repo, monkeypatch, capsys):
    """A GitHub failure fetching the body never blocks the launch (checkpoints stay inert)."""
    from perk.github import GitHubError

    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    execs: list[str] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append(f))

    def boom(**_k):
        raise GitHubError("gh unreachable")

    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", boom)
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


def test_implement_empty_plan_body_resolves_the_step(git_repo, monkeypatch, capsys):
    """An empty body is a successful fetch with nothing to cache; the fetching step must still
    resolve (to a warn) so it never dangles as a false 'stuck' signal."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    execs: list[str] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append(f))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: "")
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
    assert execs == ["pi"]
    assert not cache.plan_body_path(wt).exists()  # nothing cached for an empty body
    assert "plan #42 body is empty" in capsys.readouterr().err


def _seed_skills(repo_root: Path, *names: str) -> None:
    """Materialize `repo_root/.agents/skills/<name>/SKILL.md` for each name (the gitignored tree
    `perk init` produces in the main repo but a linked worktree never carries)."""
    for name in names:
        skill = repo_root / ".agents" / "skills" / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def _drive_implement(git_repo, monkeypatch) -> tuple[Path, list[str]]:
    """Drive a real implement launch to the exec; return (worktree, execs)."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    execs: list[str] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append(f))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    return config.worktree_root / "plan-42", execs


def test_implement_mirrors_skills_into_worktree(git_repo, monkeypatch):
    """The cold door mirrors repo_root/.agents/skills/* into the worktree as per-skill symlinks,
    delivering perk's own skill AND borrowed ones — both must resolve and be readable."""
    _seed_skills(git_repo, "perk-implement", "ruff")
    wt, execs = _drive_implement(git_repo, monkeypatch)
    assert execs == ["pi"]
    perk_skill = wt / ".agents" / "skills" / "perk-implement"
    assert perk_skill.is_symlink()  # mirrored as a symlink, not a copy
    # both perk + borrowed skill files resolve through the symlink target chain and are readable
    assert (perk_skill / "SKILL.md").read_text(encoding="utf-8") == "# perk-implement\n"
    assert (wt / ".agents" / "skills" / "ruff" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# ruff\n"


def test_skills_mirror_is_idempotent_on_resume(git_repo, monkeypatch):
    """D4 resume: a second launch leaves the correct symlink untouched — no error, resolves."""
    _seed_skills(git_repo, "perk-implement")
    wt, _ = _drive_implement(git_repo, monkeypatch)
    wt2, execs = _drive_implement(git_repo, monkeypatch)
    assert wt2 == wt
    assert len(execs) == 1  # second drive reached exec (execs is fresh per drive)
    assert (wt / ".agents" / "skills" / "perk-implement" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# perk-implement\n"


def test_skills_mirror_missing_source_is_non_fatal(git_repo, monkeypatch, capsys):
    """A repo with no .agents/skills/ (perk init never ran) warns but never blocks the launch."""
    wt, execs = _drive_implement(git_repo, monkeypatch)
    assert execs == ["pi"]  # exec still reached — launch never blocked
    assert not (wt / ".agents" / "skills").exists()  # nothing mirrored
    assert "skills: repo .agents/skills/ missing" in capsys.readouterr().err


def test_skills_mirror_never_clobbers_real_dir(tmp_path):
    """A pre-existing real (non-symlink) skill dir + sentinel survive — the helper skips it."""
    repo_root = tmp_path / "repo"
    _seed_skills(repo_root, "perk-implement")
    worktree = tmp_path / "wt"
    real = worktree / ".agents" / "skills" / "perk-implement"
    real.mkdir(parents=True)
    sentinel = real / "sentinel.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")

    materialize_skills(repo_root, worktree)

    link = worktree / ".agents" / "skills" / "perk-implement"
    assert not link.is_symlink()  # real dir left untouched
    assert sentinel.read_text(encoding="utf-8") == "keep me\n"


def test_implement_calls_linear_agent_run_started_once(git_repo, monkeypatch):
    """The cold-local implement launch calls the (internally gated) Linear agent
    run-started emitter exactly once, with the worktree + plan-ref + minted run_id."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    execs: list[str] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append(f))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    calls: list[tuple[Path, dict]] = []
    monkeypatch.setattr(
        "perk.run.launch.linear_agent.emit_run_started",
        lambda wt, **kw: calls.append((wt, kw)),
    )

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert execs == ["pi"]
    assert len(calls) == 1
    wt, kw = calls[0]
    assert wt == config.worktree_root / "plan-42"
    assert kw["plan_ref"] == _PLAN_REF_MODEL
    assert kw["run_id"]  # the minted PERK_RUN_ID


def test_non_implement_stage_skips_linear_agent_emission(git_repo, monkeypatch):
    """Only implement launches emit run-started (address/learn/plan do not)."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")
    (config.worktree_root / "plan-42").mkdir(parents=True)  # address reuses an existing worktree
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: None)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    calls: list[object] = []
    monkeypatch.setattr(
        "perk.run.launch.linear_agent.emit_run_started", lambda *a, **kw: calls.append(a)
    )

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("address"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert calls == []


def test_implement_linear_emission_failure_never_blocks_exec(git_repo, monkeypatch, capsys):
    """Fail-soft end-to-end: an open gate + a broken emitter substrate still reaches exec."""
    linear_ref = dataclasses.replace(_PLAN_REF, provider="linear", pr_id="ENG-9")
    cache.write_plan_ref(git_repo, linear_ref)
    monkeypatch.setenv("LINEAR_AGENT_TOKEN", "lin_oauth_x")
    config = Config(worktree_root=git_repo / ".worktrees")
    execs: list[str] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: execs.append(f))
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)

    def boom(_environ):
        raise IssueBackendError("agent substrate down")

    monkeypatch.setattr("perk.backends.linear.agent.agent_client_from_env", boom)

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert execs == ["pi"], "emission failure never blocks the launch"
    assert "run-started emission skipped (non-fatal)" in capsys.readouterr().err


def test_handoff_extra_is_merged_into_handoff(git_repo, monkeypatch):
    """launch_stage merges handoff_extra into the handoff blob (objective-plan ferries the
    objective_id/node_id link this way so a later plan-save recovers it)."""
    config = Config(worktree_root=git_repo / ".worktrees")
    captured: dict[str, dict[str, object]] = {}

    def _capture(root, run_id, data):
        captured["data"] = data
        return cache.handoff_path(root, run_id)

    monkeypatch.setattr("perk.run.launch.cache.write_handoff", _capture)
    monkeypatch.setattr("perk.run.launch.cache.write_plan_ref", lambda *a, **k: None)
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: None)

    launch_stage(
        repo_root=git_repo,
        config=config,
        stage=_stage("objective-plan"),  # worktree: none -> handoff at repo root
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
        prompt_override="seed",
        handoff_extra={"objective_id": "63", "node_id": "1.1"},
    )
    data = captured["data"]
    assert data["stage"] == "objective-plan"
    assert data["objective_id"] == "63"
    assert data["node_id"] == "1.1"


def test_skills_mirror_prints_total_delivered_count(tmp_path, capsys):
    """The mirror emits a `✓ mirrored N skills` milestone reporting the TOTAL delivered (not just
    freshly linked) count, so it reads correctly on an idempotent resume."""
    repo_root = tmp_path / "repo"
    _seed_skills(repo_root, "perk-implement", "ruff")
    worktree = tmp_path / "wt"

    materialize_skills(repo_root, worktree)

    # both skills were mirrored as symlinks
    assert (worktree / ".agents" / "skills" / "perk-implement").is_symlink()
    assert "mirrored 2 skills" in capsys.readouterr().err


def test_skills_mirror_count_is_total_not_freshly_linked_on_resume(tmp_path, capsys):
    """A second mirror (idempotent resume, where `linked` would be 0) still reports the total."""
    repo_root = tmp_path / "repo"
    _seed_skills(repo_root, "perk-implement", "ruff")
    worktree = tmp_path / "wt"
    materialize_skills(repo_root, worktree)
    capsys.readouterr()  # drop the first run's output
    materialize_skills(repo_root, worktree)
    assert "mirrored 2 skills" in capsys.readouterr().err


# --- launch banner -------------------------------------------------------------------------


def test_render_launch_banner_contains_wordmark_version_and_summary():
    banner = render_launch_banner(skills=25, extensions=7)
    lines = banner.splitlines()
    # three wordmark lines (box-drawing), the version on the third, the summary on the fourth
    assert lines[0].strip().startswith("\u250c")  # ┌
    assert f"perk v{__version__}" in lines[2]
    assert lines[3] == " 25 skills \u00b7 7 extensions ready"


def _seed_settings(repo_root: Path, package_count: int) -> None:
    settings = repo_root / ".pi" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"packages": [f"pkg{i}" for i in range(package_count)]}), encoding="utf-8"
    )


def test_print_launch_banner_counts_skills_and_extensions(tmp_path, capsys):
    repo_root = tmp_path / "repo"
    _seed_skills(repo_root, "a", "b", "c")
    _seed_settings(repo_root, 5)

    print_launch_banner(repo_root)

    err = capsys.readouterr().err
    assert "3 skills \u00b7 5 extensions ready" in err
    assert f"perk v{__version__}" in err


def test_print_launch_banner_idempotent_emits_once(tmp_path, capsys):
    """A second `print_launch_banner` call in the same process is a no-op (the guard latches), so
    the summary marker appears exactly once even across two calls."""
    repo_root = tmp_path / "repo"
    _seed_skills(repo_root, "a", "b")
    _seed_settings(repo_root, 4)

    print_launch_banner(repo_root)
    print_launch_banner(repo_root)

    err = capsys.readouterr().err
    assert err.count("skills \u00b7") == 1


def test_print_launch_banner_no_ansi_when_not_a_tty(tmp_path, capsys):
    """Under capsys stderr is not a tty, so the summary carries no ANSI escape codes."""
    repo_root = tmp_path / "repo"
    _seed_skills(repo_root, "a")
    _seed_settings(repo_root, 1)

    print_launch_banner(repo_root)

    assert "\x1b[" not in capsys.readouterr().err


def test_print_launch_banner_missing_sources_count_zero(tmp_path, capsys):
    """No .agents/skills/ and no .pi/settings.json → both counts fall back to 0, never raises."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    print_launch_banner(repo_root)

    assert "0 skills \u00b7 0 extensions ready" in capsys.readouterr().err


def test_launch_banner_heads_output_before_staging_warnings(git_repo, monkeypatch, capsys):
    """An end-to-end implement launch prints the banner lines before any skills/extensions
    warning, and the old `(skills: mirrored` success line never appears."""
    _seed_skills(git_repo, "perk-implement")
    # Keep repo-root .pi/npm empty so materialize_extensions takes the deterministic
    # "not staged" warning path (no network install) for the ordering assertion.
    monkeypatch.setattr(launch.init, "ensure_extension_install_present", lambda *_a, **_k: None)
    _wt, execs = _drive_implement(git_repo, monkeypatch)
    assert execs == ["pi"]
    err = capsys.readouterr().err
    assert "skills: mirrored" not in err
    # the summary line heads the output, before the extensions staging warning
    banner_idx = err.index("skills \u00b7")
    staged_idx = err.index("extensions: repo .pi/npm not staged")
    assert banner_idx < staged_idx


# --- materialize_extensions ----------------------------------------------------------------


def _seed_npm_install(repo_root: Path, *packages: str) -> None:
    """Seed a populated repo-root `.pi/npm/node_modules/<pkg>/package.json` install."""
    modules = repo_root / ".pi" / "npm" / "node_modules"
    for pkg in packages:
        pkg_dir = modules / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "package.json").write_text(
            json.dumps({"name": pkg, "version": "1.0.0"}), encoding="utf-8"
        )


def test_materialize_extensions_stages_populated_source(tmp_path, capsys):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "wt"
    _seed_npm_install(repo_root, "ext-a")

    materialize_extensions(repo_root, worktree)

    staged = worktree / ".pi" / "npm" / "node_modules" / "ext-a" / "package.json"
    assert staged.is_file()
    assert json.loads(staged.read_text(encoding="utf-8"))["name"] == "ext-a"
    assert "staged extensions" in capsys.readouterr().err  # the success milestone


def test_materialize_extensions_idempotent_resume(tmp_path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "wt"
    _seed_npm_install(repo_root, "ext-a")
    # a pre-populated worktree install with a sentinel that must survive (no clobber)
    dst_modules = worktree / ".pi" / "npm" / "node_modules"
    dst_modules.mkdir(parents=True)
    sentinel = dst_modules / "sentinel.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")

    materialize_extensions(repo_root, worktree)

    assert sentinel.read_text(encoding="utf-8") == "keep me\n"
    assert not (dst_modules / "ext-a").exists()  # resume left the install untouched


def test_materialize_extensions_missing_source_is_non_fatal(tmp_path, capsys):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"

    materialize_extensions(repo_root, worktree)

    assert "extensions: repo .pi/npm not staged" in capsys.readouterr().err
    assert not (worktree / ".pi" / "npm").exists()  # nothing staged


def test_materialize_extensions_clone_failure_is_non_fatal(tmp_path, capsys, monkeypatch):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "wt"
    _seed_npm_install(repo_root, "ext-a")

    def _boom(*_a, **_k):
        raise OSError("disk full")

    # both arms of the clone ladder fail → the warning, launch not blocked
    monkeypatch.setattr("perk.run.launch.materialize.shutil.copytree", _boom)

    materialize_extensions(repo_root, worktree)

    assert "extensions: could not stage .pi/npm" in capsys.readouterr().err


def test_materialize_extensions_clone_failure_cleans_up_partial_tree(tmp_path, capsys, monkeypatch):
    """A clone that fails mid-copy leaves a partial tree; the outer handler removes it so the
    presence-only resume guard never permanently caches a half-copied (corrupt) install."""
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "wt"
    _seed_npm_install(repo_root, "ext-a")
    dst = worktree / ".pi" / "npm"

    def _partial_then_boom(src, dest, **_k):
        # simulate a copy that wrote some files before failing partway through
        (Path(dest) / "node_modules" / "half").mkdir(parents=True, exist_ok=True)
        raise OSError("disk full")

    monkeypatch.setattr("perk.run.launch.materialize.shutil.copytree", _partial_then_boom)

    materialize_extensions(repo_root, worktree)

    assert "extensions: could not stage .pi/npm" in capsys.readouterr().err
    assert not dst.exists()  # partial tree removed → next launch re-stages / pi installs fresh


def test_materialize_extensions_hardlink_fallback_deep_copies(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "wt"
    _seed_npm_install(repo_root, "ext-a")

    def _no_hardlink(*_a, **_k):
        raise OSError("EXDEV")

    # the hardlink arm fails (e.g. cross-device); the deep-copy fallback still stages the files
    monkeypatch.setattr("perk.run.launch.materialize.os.link", _no_hardlink)

    materialize_extensions(repo_root, worktree)

    assert (worktree / ".pi" / "npm" / "node_modules" / "ext-a" / "package.json").is_file()
