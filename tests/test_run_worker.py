"""`perk run-worker` — the runner-side positioning + drive (Objective #137 Node 2.2)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from perk.backends.github import plans
from perk.backends.linear import agent as linear_agent
from perk.cli.ensure import UserFacingCliError
from perk.run import run_report, run_worker
from perk.state import cache


def _plan_state(number: int = 42) -> plans.PlanState:
    return plans.PlanState(
        number=number,
        url=f"https://gh/o/r/issues/{number}",
        title="A plan",
        header={"objective_id": "137", "consumed_learn": []},
        pr=None,
        state="OPEN",
    )


@pytest.fixture
def fake_github(monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_state(number))
    monkeypatch.setattr(plans, "get_plan_body", lambda *, number, repo_root: "# plan body\n")


def _make_entry(repo_root: Path) -> Path:
    entry = repo_root / "extension" / "workerMain.ts"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("// worker\n", encoding="utf-8")
    return entry


def test_positioning_materializes_handoff_plan_ref_and_body(tmp_path, fake_github, monkeypatch):
    _make_entry(tmp_path)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_worker.subprocess, "run", fake_run)

    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RID123",
        stage_id="implement",
        plan="42",
        base="main",
        environ={"PATH": "/usr/bin"},
    )
    assert code == 0
    # The worker consumes a prepared worktree: handoff + plan-ref + plan-body materialized.
    handoff = cache.read_handoff(tmp_path, "RID123")
    assert handoff is not None
    assert handoff["stage"] == "implement"
    assert handoff["mode"] == "read-write"
    ref = cache.read_plan_ref(tmp_path)
    assert ref is not None
    assert ref["pr_id"] == "42"
    assert ref["provider"] == "github"
    assert cache.plan_body_path(tmp_path).read_text(encoding="utf-8") == "# plan body\n"


def test_spawn_argv_env_and_forwarded_exit_code(tmp_path, fake_github, monkeypatch):
    entry = _make_entry(tmp_path)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(run_worker.subprocess, "run", fake_run)
    # Isolate the spawn: reporting (its own gh calls) is covered in test_run_report.
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: None)
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: None)

    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RID9",
        stage_id="address",
        plan="42",
        base=None,
        environ={"PATH": "/usr/bin"},
    )
    assert code == 7  # the worker's exit code is forwarded
    assert captured["argv"] == ["node", str(entry), "address", "--worktree", str(tmp_path)]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["env"]["PERK_RUN_ID"] == "RID9"
    assert captured["kwargs"]["check"] is False


def test_reporting_brackets_the_spawn_and_is_exit_code_neutral(tmp_path, fake_github, monkeypatch):
    _make_entry(tmp_path)
    order: list[str] = []

    def fake_run(argv, **kwargs):
        order.append("spawn")
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(run_worker.subprocess, "run", fake_run)
    # report_started runs before the spawn; report_terminal after it returns. The orchestrators are
    # internally fail-soft (asserted in test_run_report), so a swallowed reporting failure here
    # still forwards the worker's exit code unchanged.
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: order.append("started"))
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: order.append("terminal"))

    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RIDX",
        stage_id="implement",
        plan="42",
        base=None,
        environ={"PATH": "/usr/bin"},
    )
    assert code == 3  # reporting never changes the worker exit code
    assert order == ["started", "spawn", "terminal"]


def test_linear_agent_hooks_bracket_the_spawn(tmp_path, fake_github, monkeypatch):
    """Node 5.1: run-started is emitted beside report_started (with the Actions run URL when the
    env carries one) and run-failed beside report_terminal on a nonzero worker exit."""
    _make_entry(tmp_path)
    monkeypatch.setattr(run_worker.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=5))
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: None)
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: None)
    started: list[dict] = []
    failed: list[dict] = []
    monkeypatch.setattr(
        run_worker.linear_agent, "emit_run_started", lambda _wt, **kw: started.append(kw)
    )
    monkeypatch.setattr(
        run_worker.linear_agent, "emit_run_failed", lambda _wt, **kw: failed.append(kw)
    )
    environ = {
        "PATH": "/usr/bin",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "123",
    }

    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RIDL",
        stage_id="implement",
        plan="42",
        base=None,
        environ=environ,
    )
    assert code == 5
    assert len(started) == 1
    assert started[0]["run_id"] == "RIDL"
    assert started[0]["plan_ref"]["pr_id"] == "42"
    assert started[0]["external_urls"] == [
        ("GitHub Actions run", "https://github.com/o/r/actions/runs/123")
    ]
    assert len(failed) == 1
    assert failed[0]["exit_code"] == 5
    assert failed[0]["run_url"] == "https://github.com/o/r/actions/runs/123"


def test_linear_agent_success_emits_no_run_failed(tmp_path, fake_github, monkeypatch):
    """A zero worker exit emits no terminal activity (the in-run submit already emitted the PR)."""
    _make_entry(tmp_path)
    monkeypatch.setattr(run_worker.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: None)
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: None)
    started: list[dict] = []
    failed: list[dict] = []
    monkeypatch.setattr(
        run_worker.linear_agent, "emit_run_started", lambda _wt, **kw: started.append(kw)
    )
    monkeypatch.setattr(
        run_worker.linear_agent, "emit_run_failed", lambda _wt, **kw: failed.append(kw)
    )

    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RIDS",
        stage_id="implement",
        plan="42",
        base=None,
        environ={"PATH": "/usr/bin"},
    )
    assert code == 0
    assert len(started) == 1
    assert started[0]["external_urls"] == []  # no Actions env -> no run URL
    assert failed == []


def test_linear_agent_emission_failure_is_exit_code_neutral(tmp_path, fake_github, monkeypatch):
    """Fail-soft end-to-end: a broken emitter substrate never changes the forwarded exit code."""
    _make_entry(tmp_path)
    monkeypatch.setattr(run_worker.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=4))
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: None)
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: None)
    # Force the gate open (the reconstructed plan-ref here is github-backed), then break the
    # client substrate: the emitters must swallow the failure.
    monkeypatch.setattr(linear_agent, "emission_enabled", lambda *_a, **_k: True)

    def boom(_environ):
        raise RuntimeError("agent substrate down")

    monkeypatch.setattr(linear_agent, "agent_client_from_env", boom)

    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RIDF",
        stage_id="implement",
        plan="42",
        base=None,
        environ={"PATH": "/usr/bin", "LINEAR_AGENT_TOKEN": "tok"},
    )
    assert code == 4  # emission failures are swallowed inside the emitters


def test_plan_not_found_is_loud(tmp_path, monkeypatch):
    _make_entry(tmp_path)
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: None)
    with pytest.raises(UserFacingCliError) as exc:
        run_worker.run_worker(
            repo_root=tmp_path,
            run_id="R",
            stage_id="implement",
            plan="99",
            base=None,
            environ={},
        )
    assert exc.value.error_type == "plan_not_found"


def test_non_drivable_stage_is_rejected(tmp_path, fake_github):
    with pytest.raises(UserFacingCliError) as exc:
        run_worker.run_worker(
            repo_root=tmp_path,
            run_id="R",
            stage_id="plan",  # warm/cold_local only, no cold_remote door
            base=None,
            plan="42",
            environ={},
        )
    assert exc.value.error_type == "stage_not_drivable"


def test_unknown_stage_is_rejected(tmp_path, fake_github):
    with pytest.raises(UserFacingCliError) as exc:
        run_worker.run_worker(
            repo_root=tmp_path,
            run_id="R",
            stage_id="nope",
            base=None,
            plan="42",
            environ={},
        )
    assert exc.value.error_type == "stage_not_drivable"


def test_missing_worker_entry_is_loud(tmp_path, fake_github):
    # No extension/workerMain.ts anywhere and no PERK_WORKER_ENTRY override.
    with pytest.raises(UserFacingCliError) as exc:
        run_worker.run_worker(
            repo_root=tmp_path,
            run_id="R",
            stage_id="implement",
            base=None,
            plan="42",
            environ={},
        )
    assert exc.value.error_type == "worker_entry_missing"


def test_worker_entry_env_override(tmp_path):
    custom = tmp_path / "elsewhere" / "workerMain.ts"
    custom.parent.mkdir(parents=True)
    custom.write_text("// w\n", encoding="utf-8")
    resolved = run_worker.resolve_worker_entry(tmp_path, {"PERK_WORKER_ENTRY": str(custom)})
    assert resolved.path == custom
    assert resolved.source == "env"


def test_worker_entry_env_override_missing_file_is_loud(tmp_path):
    with pytest.raises(UserFacingCliError) as exc:
        run_worker.resolve_worker_entry(tmp_path, {"PERK_WORKER_ENTRY": str(tmp_path / "ghost.ts")})
    assert exc.value.error_type == "worker_entry_missing"


def test_worker_entry_consumer_npm_install(tmp_path):
    entry = (
        tmp_path / ".pi" / "npm" / "node_modules" / "@perk" / "pi" / "extension" / "workerMain.ts"
    )
    entry.parent.mkdir(parents=True)
    entry.write_text("// w\n", encoding="utf-8")
    resolved = run_worker.resolve_worker_entry(tmp_path, {})
    assert resolved.path == entry
    assert resolved.source == "consumer-npm"


def test_worker_entry_consumer_git_clone(tmp_path):
    # B2: pi clones the `git:` package to `.pi/git/<host>/<path>`; the resolver finds it (derived
    # from GIT_PACKAGE) before the npm fallback.
    entry = run_worker._git_clone_worker_entry(tmp_path)
    entry.parent.mkdir(parents=True)
    entry.write_text("// w\n", encoding="utf-8")
    resolved = run_worker.resolve_worker_entry(tmp_path, {})
    assert resolved.path == entry
    assert resolved.source == "consumer-git"
