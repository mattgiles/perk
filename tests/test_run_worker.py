"""`perk run-worker` — the runner-side positioning + drive (Objective #137 Node 2.2)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from perk import cache, github, run_worker
from perk.cli.ensure import UserFacingCliError


def _plan_state(number: int = 42) -> github.PlanState:
    return github.PlanState(
        number=number,
        url=f"https://gh/o/r/issues/{number}",
        title="A plan",
        header={"objective_id": "137", "consumed_learn": []},
        pr=None,
        state="OPEN",
    )


@pytest.fixture
def fake_github(monkeypatch):
    monkeypatch.setattr(github, "get_plan", lambda *, number, repo_root: _plan_state(number))
    monkeypatch.setattr(github, "get_plan_body", lambda *, number, repo_root: "# plan body\n")


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
        plan=42,
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

    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RID9",
        stage_id="address",
        plan=42,
        base=None,
        environ={"PATH": "/usr/bin"},
    )
    assert code == 7  # the worker's exit code is forwarded
    assert captured["argv"] == ["node", str(entry), "address", "--worktree", str(tmp_path)]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["env"]["PERK_RUN_ID"] == "RID9"
    assert captured["kwargs"]["check"] is False


def test_plan_not_found_is_loud(tmp_path, monkeypatch):
    _make_entry(tmp_path)
    monkeypatch.setattr(github, "get_plan", lambda *, number, repo_root: None)
    with pytest.raises(UserFacingCliError) as exc:
        run_worker.run_worker(
            repo_root=tmp_path,
            run_id="R",
            stage_id="implement",
            plan=99,
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
            plan=42,
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
            plan=42,
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
            plan=42,
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


def test_worker_entry_consumer_install(tmp_path):
    entry = (
        tmp_path / ".pi" / "npm" / "node_modules" / "@perk" / "pi" / "extension" / "workerMain.ts"
    )
    entry.parent.mkdir(parents=True)
    entry.write_text("// w\n", encoding="utf-8")
    resolved = run_worker.resolve_worker_entry(tmp_path, {})
    assert resolved.path == entry
    assert resolved.source == "consumer"
