import dataclasses
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _launch_helpers import _PLAN_REF, _PLAN_REF_MODEL, _config, _request, _stage

from perk import __version__
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.run.launch import (
    _build_exec_env,
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

pytestmark = pytest.mark.usefixtures("stub_launch_extension_warm")


def test_implement_materializes_worktree_and_is_idempotent(git_repo, monkeypatch):
    """Real-git integration (D4/D5): implement creates plan-<pr_id> + branch, materializes
    handoff + plan-ref into it, and reuses the worktree on a second run."""
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")

    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch._resolve_pi_executable", lambda: "/stub/bin/pi")
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
    assert execs and execs[0][0] == "/stub/bin/pi"  # the resolver's absolute path, not "pi"

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
    monkeypatch.setattr("perk.run.launch._resolve_pi_executable", lambda: "/stub/bin/pi")
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
    monkeypatch.setattr("perk.run.launch._resolve_pi_executable", lambda: "/stub/bin/pi")
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
    monkeypatch.setattr("perk.run.launch._resolve_pi_executable", lambda: "/stub/bin/pi")
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


def test_launch_seeds_linear_key_from_local_config_when_env_absent(
    git_repo, monkeypatch, launch_context_factory, launch_exec_recorder
):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    cfg = git_repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "local.toml").write_text('[linear]\napi_key = "lin_api_local"\n', encoding="utf-8")
    ctx = launch_context_factory(
        stage=_stage("implement"),
        repo_root=git_repo,
        worktree=git_repo,
    )
    launch._exec_pi(ctx)
    env = launch_exec_recorder.calls[0][2]
    assert env["LINEAR_API_KEY"] == "lin_api_local"


def test_launch_seeds_linear_key_from_main_checkout_when_rooted_in_worktree(
    git_repo, monkeypatch, launch_context_factory, launch_exec_recorder
):
    # A `perk implement` launch rooted inside a linked worktree must still seed LINEAR_API_KEY
    # from the MAIN checkout's gitignored `.perk/local.toml` (never copied into worktrees).
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    cfg = git_repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "local.toml").write_text('[linear]\napi_key = "lin_api_main"\n', encoding="utf-8")
    wt = git_repo / ".worktrees" / "wt-launch"
    git_mod.worktree_add(git_repo, wt, branch="plan-launch", create_branch=True)

    ctx = launch_context_factory(
        stage=_stage("implement"),
        repo_root=wt,
        worktree=wt,
        config=Config(worktree_root=git_repo / ".worktrees"),
        plan_ref=_PLAN_REF,
    )
    launch._exec_pi(ctx)
    assert launch_exec_recorder.calls[0][2]["LINEAR_API_KEY"] == "lin_api_main"


def test_launch_exported_linear_key_wins_over_local_config():
    env = _build_exec_env(
        run_id="01TEST",
        environ={"LINEAR_API_KEY": "lin_api_env"},
        fallback_linear_api_key="lin_api_local",
    )
    assert env["LINEAR_API_KEY"] == "lin_api_env"


def test_exec_pi_resolves_before_chdir_and_execs_the_absolute_path(
    tmp_path, monkeypatch, launch_context_factory
):
    """The pi executable is resolved BEFORE the chdir and the exec receives the resolver's
    absolute path (no bare-name PATH re-resolution under the worktree); argv[0] stays "pi"."""
    events: list[object] = []
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    monkeypatch.setattr(launch, "_pi_agent_dir", lambda: agent_dir)
    monkeypatch.setattr(
        launch,
        "_resolve_pi_executable",
        lambda: events.append("resolve") or "/resolved/bin/pi",
    )
    monkeypatch.setattr(launch.os, "chdir", lambda path: events.append("chdir"))
    monkeypatch.setattr(
        launch.os, "execvpe", lambda program, argv, env: events.append(("exec", program, argv))
    )
    ctx = launch_context_factory(stage=_stage("implement"), plan_ref=_PLAN_REF)
    launch._exec_pi(ctx)
    assert events.index("resolve") < events.index("chdir")  # resolved pre-chdir
    exec_event = events[-1]
    assert exec_event == ("exec", "/resolved/bin/pi", list(ctx.argv))
    assert ctx.argv[0] == "pi"  # argv[0] conventionally stays the bare name


def test_exec_pi_which_miss_aborts_before_any_exec_phase_side_effect(
    tmp_path, monkeypatch, launch_context_factory
):
    """A PATH miss is a typed pi_cli_missing refusal raised BEFORE any exec-phase side effect
    (no chdir, no exec) — the REAL resolver runs through which_absolute. Deliberately scoped:
    this claims nothing about earlier launch_stage phases (the idempotent-resume posture)."""
    events: list[str] = []
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    monkeypatch.setattr(launch, "_pi_agent_dir", lambda: agent_dir)
    monkeypatch.setattr(shutil, "which", lambda binary: None)
    monkeypatch.setattr(launch.os, "chdir", lambda path: events.append("chdir"))
    monkeypatch.setattr(launch.os, "execvpe", lambda program, argv, env: events.append("exec"))
    ctx = launch_context_factory(stage=_stage("implement"), plan_ref=_PLAN_REF)
    with pytest.raises(UserFacingCliError) as excinfo:
        launch._exec_pi(ctx)
    assert excinfo.value.error_type == "pi_cli_missing"
    assert "npm install -g @earendil-works/pi-coding-agent" in excinfo.value.format_message()
    assert events == []  # neither chdir nor exec happened


def test_exec_pi_exec_race_oserror_becomes_launch_failed(
    tmp_path, monkeypatch, launch_context_factory
):
    """The presence probe does not eliminate the exec race: a chdir/exec OSError is the typed
    launch_failed refusal naming the worktree, chained from the original error."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    monkeypatch.setattr(launch, "_pi_agent_dir", lambda: agent_dir)
    monkeypatch.setattr(launch, "_resolve_pi_executable", lambda: "/stub/bin/pi")
    monkeypatch.setattr(launch.os, "chdir", lambda path: None)

    def _boom(program, argv, env):
        raise OSError("boom")

    monkeypatch.setattr(launch.os, "execvpe", _boom)
    ctx = launch_context_factory(stage=_stage("implement"), plan_ref=_PLAN_REF)
    with pytest.raises(UserFacingCliError) as excinfo:
        launch._exec_pi(ctx)
    assert excinfo.value.error_type == "launch_failed"
    assert str(ctx.resolved.path) in excinfo.value.format_message()
    assert isinstance(excinfo.value.__cause__, OSError)


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


def test_resolve_worktree_fresh_create_disposition_binds_and_marks(git_repo):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    resolved = resolve_worktree(
        repo_root=git_repo,
        config=Config(worktree_root=git_repo / ".worktrees"),
        request=_request("implement"),
        worktree=None,
        materialize=True,
    )
    assert resolved.disposition == "create-fresh"
    assert resolved.branch == "plan-42"
    # Positioner-owned materialization: the fresh checkout is bound at creation and carries
    # the setup-pending marker the marker-gated hook consumes.
    assert cache.read_plan_ref(resolved.path) == _PLAN_REF
    assert cache.has_marker(resolved.path, cache.SETUP_PENDING)


def test_resolve_worktree_dry_run_previews_create_fresh_without_creating(tmp_path):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        request=_request("implement"),
        worktree=None,
        materialize=False,
    )
    assert resolved.disposition == "create-fresh"  # the same disposition the real run takes
    assert not resolved.path.exists()  # …but a dry run creates nothing


def test_resolve_worktree_reuse_local_disposition_on_second_resolve(git_repo):
    cache.write_plan_ref(git_repo, _PLAN_REF)
    config = Config(worktree_root=git_repo / ".worktrees")

    def _resolve():
        return resolve_worktree(
            repo_root=git_repo,
            config=config,
            request=_request("implement"),
            worktree=None,
            materialize=True,
        )

    assert _resolve().disposition == "create-fresh"  # fresh
    assert _resolve().disposition == "reuse-local"  # idempotent validated reuse


def test_resolve_worktree_root_disposition_on_worktree_none(tmp_path):
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        request=_request("plan"),
        worktree=None,
        materialize=True,
    )
    assert resolved.disposition == "root"


def _stub_unrelated_launch_phases(monkeypatch, resolved: launch.ResolvedWorktree) -> None:
    """Leave setup and exec live while replacing unrelated launch phases."""
    monkeypatch.setattr(launch, "print_launch_banner", lambda _root: None)
    monkeypatch.setattr(launch, "resolve_worktree", lambda **_kwargs: resolved)
    monkeypatch.setattr(launch, "_resolve_prompt", lambda **_kwargs: None)
    monkeypatch.setattr(launch, "_build_argv", lambda **_kwargs: ("pi",))
    monkeypatch.setattr(launch, "_write_session_handoff", lambda _ctx, _extra: None)
    monkeypatch.setattr(launch, "_warm_extension_install", lambda _ctx: None)
    monkeypatch.setattr(launch, "_materialize_into_worktree", lambda _ctx: None)
    monkeypatch.setattr(launch, "_emit_linear_run_started", lambda _ctx: None)


def test_launch_runs_setup_before_exec_on_fresh_create(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    cache.set_marker(worktree, cache.SETUP_PENDING)  # what the positioner leaves at creation
    resolved = launch.ResolvedWorktree(worktree, _PLAN_REF, disposition="create-fresh")
    _stub_unrelated_launch_phases(monkeypatch, resolved)
    config = Config(worktree_root=tmp_path / ".worktrees", worktree_setup=["uv sync", "npm ci"])
    events: list = []
    monkeypatch.setattr(
        launch, "run_worktree_setup", lambda wt, cmds: events.append(("setup", wt, cmds))
    )
    monkeypatch.setattr(launch, "_exec_pi", lambda _ctx: events.append(("exec", "pi")))

    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert events == [
        ("setup", worktree, ["uv sync", "npm ci"]),
        ("exec", "pi"),
    ]
    assert not cache.has_marker(worktree, cache.SETUP_PENDING)  # cleared on success


def test_launch_setup_failure_aborts_before_exec(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    cache.set_marker(worktree, cache.SETUP_PENDING)
    resolved = launch.ResolvedWorktree(worktree, _PLAN_REF, disposition="create-fresh")
    _stub_unrelated_launch_phases(monkeypatch, resolved)
    config = Config(worktree_root=tmp_path / ".worktrees", worktree_setup=["boom"])
    execs: list = []
    monkeypatch.setattr(launch, "_exec_pi", lambda _ctx: execs.append("pi"))

    def _boom(_wt, _cmds):
        raise UserFacingCliError("nope", error_type="worktree_setup_failed")

    monkeypatch.setattr(launch, "run_worktree_setup", _boom)
    with pytest.raises(UserFacingCliError) as exc:
        launch_stage(
            repo_root=tmp_path,
            config=config,
            stage=_stage("implement"),
            worktree=None,
            dry_run=False,
            remote=None,
            pi_args=[],
        )
    assert exc.value.error_type == "worktree_setup_failed"
    assert execs == []  # exec pi was never reached
    assert cache.has_marker(worktree, cache.SETUP_PENDING)  # left in place — the retry signal


def test_launch_resume_does_not_run_setup(monkeypatch, launch_context_factory):
    # A validated reuse without the setup-pending marker never re-runs the hook.
    config = Config(worktree_root=Path(".worktrees"), worktree_setup=["uv sync"])
    setup_calls: list = []
    monkeypatch.setattr(
        launch, "run_worktree_setup", lambda wt, cmds: setup_calls.append((wt, cmds))
    )
    ctx = launch_context_factory(
        stage=_stage("implement"),
        config=config,
        plan_ref=_PLAN_REF,
        disposition="reuse-local",
    )
    launch._run_setup_hook(ctx)
    assert setup_calls == []


def test_launch_reuse_with_pending_marker_reruns_setup(monkeypatch, launch_context_factory):
    # A reuse-local checkout still carrying the marker (a previously failed setup) is
    # setup-eligible: the hook re-runs and the marker clears on success (fail-then-retry).
    config = Config(worktree_root=Path(".worktrees"), worktree_setup=["uv sync"])
    setup_calls: list = []
    monkeypatch.setattr(
        launch, "run_worktree_setup", lambda wt, cmds: setup_calls.append((wt, cmds))
    )
    ctx = launch_context_factory(
        stage=_stage("implement"),
        config=config,
        plan_ref=_PLAN_REF,
        disposition="reuse-local",
    )
    cache.set_marker(ctx.resolved.path, cache.SETUP_PENDING)
    launch._run_setup_hook(ctx)
    assert setup_calls == [(ctx.resolved.path, ["uv sync"])]
    assert not cache.has_marker(ctx.resolved.path, cache.SETUP_PENDING)


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


def test_launch_injects_npm_quiet_env():
    """The child env carries the npm-quieting vars so pi's startup npm installs inherit
    them, and PERK_RUN_ID survives the merge (regression guard)."""
    env = _build_exec_env(
        run_id="01TEST",
        environ={},
        fallback_linear_api_key=None,
    )
    assert env["npm_config_loglevel"] == "error"
    assert env["npm_config_fund"] == "false"
    assert env["npm_config_audit"] == "false"
    assert env["PERK_RUN_ID"] == "01TEST"


def test_launch_npm_quiet_env_user_override_wins():
    """Setdefault semantics: an operator's own npm_config_* env var beats the injected map."""
    env = _build_exec_env(
        run_id="01TEST",
        environ={"npm_config_loglevel": "verbose"},
        fallback_linear_api_key=None,
    )
    assert env["npm_config_loglevel"] == "verbose"
    assert env["npm_config_fund"] == "false"


def test_launch_sweeps_stale_lock_before_exec(launch_context_factory, launch_exec_recorder):
    """The exec phase sweeps the stale agent-dir lock before exec'ing pi."""
    stale = launch_exec_recorder.agent_dir / "settings.json.lock"
    stale.write_text("", encoding="utf-8")
    ctx = launch_context_factory(
        stage=_stage("implement"),
        plan_ref=_PLAN_REF,
    )
    launch._exec_pi(ctx)
    assert not stale.exists()  # swept before exec
    assert [call[0] for call in launch_exec_recorder.calls] == [launch_exec_recorder.pi_path]


def test_implement_materializes_plan_body_snapshot(tmp_path, monkeypatch, capsys):
    """The materializer caches the plan body snapshot and narrates the fetch milestone."""
    worktree = tmp_path / "worktree"
    markdown = "# Add retry\n\n## Steps\n1. Add helper\n2. Wire it in\n"
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: markdown)

    launch.materialize_plan_body(tmp_path, worktree, _PLAN_REF)
    assert cache.plan_body_path(worktree).read_text(encoding="utf-8").strip() == markdown.strip()
    err = capsys.readouterr().err
    assert "fetching plan #42 body" in err
    assert "cached plan #42 body" in err


def test_implement_plan_body_fetch_is_best_effort(tmp_path, monkeypatch, capsys):
    """A GitHub failure is swallowed by the materializer and leaves no snapshot."""
    from perk.github import GitHubError

    def boom(**_k):
        raise GitHubError("gh unreachable")

    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", boom)
    worktree = tmp_path / "worktree"
    launch.materialize_plan_body(tmp_path, worktree, _PLAN_REF)
    assert not cache.plan_body_path(worktree).exists(), "no body cached on fetch failure"
    assert "plan snapshot: could not fetch plan #42 body" in capsys.readouterr().err


def test_implement_empty_plan_body_resolves_the_step(tmp_path, monkeypatch, capsys):
    """An empty body is a successful fetch with nothing to cache; the fetching step must still
    resolve (to a warn) so it never dangles as a false 'stuck' signal."""
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: "")
    worktree = tmp_path / "worktree"
    launch.materialize_plan_body(tmp_path, worktree, _PLAN_REF)
    assert not cache.plan_body_path(worktree).exists()  # nothing cached for an empty body
    assert "plan snapshot: plan #42 body is empty" in capsys.readouterr().err


def _seed_skills(repo_root: Path, *names: str) -> None:
    """Materialize `repo_root/.agents/skills/<name>/SKILL.md` for each name (the gitignored tree
    `perk init` produces in the main repo but a linked worktree never carries)."""
    for name in names:
        skill = repo_root / ".agents" / "skills" / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def test_implement_mirrors_skills_into_worktree(tmp_path):
    """The materializer mirrors repo_root/.agents/skills/* as per-skill symlinks,
    delivering perk's own skill AND borrowed ones — both must resolve and be readable."""
    repo_root = tmp_path / "repo"
    wt = tmp_path / "worktree"
    _seed_skills(repo_root, "perk-implement", "ruff")
    materialize_skills(repo_root, wt)
    perk_skill = wt / ".agents" / "skills" / "perk-implement"
    assert perk_skill.is_symlink()  # mirrored as a symlink, not a copy
    # both perk + borrowed skill files resolve through the symlink target chain and are readable
    assert (perk_skill / "SKILL.md").read_text(encoding="utf-8") == "# perk-implement\n"
    assert (wt / ".agents" / "skills" / "ruff" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# ruff\n"


def test_skills_mirror_is_idempotent_on_resume(tmp_path):
    """D4 resume: a second launch leaves the correct symlink untouched — no error, resolves."""
    repo_root = tmp_path / "repo"
    wt = tmp_path / "worktree"
    _seed_skills(repo_root, "perk-implement")
    materialize_skills(repo_root, wt)
    materialize_skills(repo_root, wt)
    assert (wt / ".agents" / "skills" / "perk-implement" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# perk-implement\n"


def test_skills_mirror_missing_source_is_non_fatal(tmp_path, capsys):
    """A repo with no .agents/skills/ warns and returns without raising."""
    repo_root = tmp_path / "repo"
    wt = tmp_path / "worktree"
    materialize_skills(repo_root, wt)
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


def test_implement_calls_linear_agent_run_started_once(monkeypatch, launch_context_factory):
    """The implement phase calls the gated Linear emitter with its resolved context."""
    calls: list[tuple[Path, dict]] = []
    monkeypatch.setattr(
        "perk.run.launch.linear_agent.emit_run_started",
        lambda wt, **kw: calls.append((wt, kw)),
    )

    ctx = launch_context_factory(
        stage=_stage("implement"),
        plan_ref=_PLAN_REF,
        rid="01LINEAR",
    )
    launch._emit_linear_run_started(ctx)
    assert len(calls) == 1
    wt, kw = calls[0]
    assert wt == ctx.resolved.path
    assert kw["plan_ref"] == _PLAN_REF_MODEL
    assert kw["run_id"] == "01LINEAR"


def test_non_implement_stage_skips_linear_agent_emission(monkeypatch, launch_context_factory):
    """Only implement launches emit run-started (address/learn/plan do not)."""
    calls: list[object] = []
    monkeypatch.setattr(
        "perk.run.launch.linear_agent.emit_run_started", lambda *a, **kw: calls.append(a)
    )

    ctx = launch_context_factory(
        stage=_stage("address"),
        plan_ref=_PLAN_REF,
    )
    launch._emit_linear_run_started(ctx)
    assert calls == []


def test_implement_linear_emission_failure_never_blocks_exec(
    monkeypatch, capsys, launch_context_factory, launch_exec_recorder
):
    """An open gate plus a broken emitter substrate returns and still reaches exec."""
    linear_ref = dataclasses.replace(_PLAN_REF, provider="linear", pr_id="ENG-9")
    monkeypatch.setenv("LINEAR_AGENT_TOKEN", "lin_oauth_x")

    def boom(_environ):
        raise IssueBackendError("agent substrate down")

    monkeypatch.setattr("perk.backends.linear.agent.agent_client_from_env", boom)
    ctx = launch_context_factory(
        stage=_stage("implement"),
        plan_ref=linear_ref,
    )
    launch._emit_linear_run_started(ctx)
    launch._exec_pi(ctx)
    assert [call[0] for call in launch_exec_recorder.calls] == [launch_exec_recorder.pi_path]
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
    monkeypatch.setattr("perk.run.launch._resolve_pi_executable", lambda: "/stub/bin/pi")
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


def test_launch_banner_heads_output_before_staging_warnings(
    git_repo, monkeypatch, capsys, launch_exec_recorder
):
    """An end-to-end implement launch prints the banner lines before any skills/extensions
    warning, and the old `(skills: mirrored` success line never appears."""
    _seed_skills(git_repo, "perk-implement")
    # Keep repo-root .pi/npm empty so materialize_extensions takes the deterministic
    # "not staged" warning path (no network install) for the ordering assertion.
    monkeypatch.setattr(launch.init, "ensure_extension_install_present", lambda *_a, **_k: None)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    cache.write_plan_ref(git_repo, _PLAN_REF)
    launch_stage(
        repo_root=git_repo,
        config=Config(worktree_root=git_repo / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert [call[0] for call in launch_exec_recorder.calls] == [launch_exec_recorder.pi_path]
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
