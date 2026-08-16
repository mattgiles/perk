"""`perk run-worker` — the runner-side positioning + drive."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from perk import plan
from perk.backends.github import plans
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import agent as linear_agent
from perk.cli.ensure import UserFacingCliError
from perk.convergence import init as init_mod
from perk.delivery import StatusResult
from perk.run import launch, run_report, run_worker
from perk.run.launch import worktree as worktree_mod
from perk.state import cache
from perk.substrate import git as gitmod
from perk.substrate.config import Config
from perk.substrate.registry import load_registry


def _plan_state(number: int = 42) -> plans.PlanState:
    return plans.PlanState(
        number=number,
        url=f"https://gh/o/r/issues/{number}",
        title="A plan",
        header={"objective_id": "137", "consumed_learn": []},
        pr=None,
        state="OPEN",
    )


@pytest.fixture(autouse=True)
def stub_skills_sync(monkeypatch):
    """Positioning now runs the skills-CLI sync seam; stub it so no test shells the real CLI
    (dev machines have `skills` on PATH — an unstubbed test would clone for real)."""
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: None)


@pytest.fixture(autouse=True)
def stub_position_branch(monkeypatch):
    """`run_worker` now positions the plan branch itself (`position_branch`, §8.46) — a real
    git op these drive-mechanics tests must not shell. Autouse RECORDING stub (`.calls`
    captures every `(repo_root, plan_ref, base)` invocation so the drive tests can assert the
    run_worker → position_branch wiring); the positioning tests call the REAL function via
    `.real`."""
    calls: list[tuple] = []
    real = run_worker.position_branch
    monkeypatch.setattr(
        run_worker,
        "position_branch",
        lambda repo_root, plan_ref, base: calls.append((repo_root, plan_ref, base)),
    )
    return SimpleNamespace(real=real, calls=calls)


@pytest.fixture(autouse=True)
def stub_main_worktree_root(monkeypatch):
    """The `[issues]` readers anchor to the main checkout via `git.main_worktree_root` (a real
    `git rev-parse` shell). These tests fake the GLOBAL `subprocess.run` to intercept the worker
    spawn, which would otherwise swallow that git call with a broken stand-in; pin the anchor to
    its real non-repo result (`tmp_path` is not a git repo → ``None`` → fall back to the given
    root) so the config reads stay hermetic."""
    monkeypatch.setattr(gitmod, "main_worktree_root", lambda cwd: None)


@pytest.fixture
def fake_github(monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda *, number, repo_root: _plan_state(number))
    monkeypatch.setattr(plans, "get_plan_body", lambda *, number, repo_root: "# plan body\n")


def _make_entry(repo_root: Path) -> Path:
    entry = repo_root / "extension" / "workerMain.ts"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("// worker\n", encoding="utf-8")
    return entry


def test_positioning_materializes_handoff_plan_ref_and_body(
    tmp_path, fake_github, monkeypatch, stub_position_branch
):
    _make_entry(tmp_path)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_worker.subprocess, "run", fake_run)
    # The reporters are covered by test_run_report.py; here they'd hit the faked subprocess.run
    # (whose SimpleNamespace lacks stdout) — no-op them like every other test in this file.
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: None)
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: None)

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
    assert handoff.stage == "implement"
    assert handoff.mode == "read-write"
    ref = cache.read_plan_ref(tmp_path)
    assert ref is not None
    assert ref.pr_id == "42"
    assert ref.provider == "github"
    assert cache.plan_body_path(tmp_path).read_text(encoding="utf-8") == "# plan body\n"
    # The drive positions the plan branch with the RECONSTRUCTED ref + the dispatched base.
    assert [(r.pr_id, base) for _root, r, base in stub_position_branch.calls] == [("42", "main")]


def test_positioning_parity_local_launch_vs_remote_worker(git_repo_with_remote, monkeypatch):
    """Local launch and remote-worker positioning materialize the SAME `.perk/workflow/`
    artifacts (contracts.md §8.38) — pinning `position_worktree`'s "mirrors the cold-local
    positioning in `launch.launch_stage`" docstring as a test. `run_id` is minted per path by
    design and is the one ignored field."""
    clone, _remote, _advance = git_repo_with_remote
    ref = plan.PlanRef(
        provider="github",
        pr_id="42",
        url="https://gh/o/r/issues/42",
        labels=("perk:plan",),
    )
    body = "# plan body\n\n## Steps\n\n1. do it\n"
    monkeypatch.setattr(plans, "get_plan_body", lambda **_k: body)
    stage = next(s for s in load_registry().stages if s.id == "implement")

    # Path A — the cold-local launch (exec + npm warming no-op'd; everything else real).
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda _f, _a, _e: None)
    monkeypatch.setattr(
        launch.init, "ensure_extension_install_present", lambda repo_root, *, self_repo: None
    )
    cache.write_plan_ref(clone, ref)
    launch.launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=stage,
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    local_wt = clone / ".worktrees" / "plan-42"

    # Path B — the remote worker's positioning (the worktree IS the checkout).
    remote_wt = clone.parent / "remote-checkout"
    remote_wt.mkdir()
    run_worker.position_worktree(remote_wt, run_id="RID-REMOTE", stage=stage, plan_ref=ref)

    # Handoff parity: stage/mode agree (run_id is minted per path — ignored by design).
    local_rids = cache.list_handoff_run_ids(local_wt)
    assert len(local_rids) == 1
    local_handoff = cache.read_handoff(local_wt, local_rids[0])
    remote_handoff = cache.read_handoff(remote_wt, "RID-REMOTE")
    assert local_handoff is not None and remote_handoff is not None
    assert local_handoff.stage == remote_handoff.stage == "implement"
    assert local_handoff.mode == remote_handoff.mode == "read-write"
    # Plan-ref parity: byte-identical.
    assert cache.plan_ref_path(local_wt).read_bytes() == cache.plan_ref_path(remote_wt).read_bytes()
    # Plan-body parity: byte-identical.
    assert (
        cache.plan_body_path(local_wt).read_bytes() == cache.plan_body_path(remote_wt).read_bytes()
    )


def test_positioning_parity_explicit_ref_launch_vs_remote_worker(git_repo_with_remote, monkeypatch):
    """The §8.38 parity holds on the direct-ref arm too: a local launch consuming an explicitly
    selected ref (no root selector anywhere) materializes the same artifacts as the remote
    worker — the launch never re-reads mutable cache state after selection."""
    clone, _remote, _advance = git_repo_with_remote
    ref = plan.PlanRef(
        provider="github",
        pr_id="42",
        url="https://gh/o/r/issues/42",
        labels=("perk:plan",),
    )
    monkeypatch.setattr(plans, "get_plan_body", lambda **_k: "# plan body\n")
    stage = next(s for s in load_registry().stages if s.id == "implement")

    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda _f, _a, _e: None)
    monkeypatch.setattr(
        launch.init, "ensure_extension_install_present", lambda repo_root, *, self_repo: None
    )
    assert cache.read_plan_ref(clone) is None  # deliberately: no cache fallback available
    launch.launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=stage,
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
        plan_ref=ref,
    )
    local_wt = clone / ".worktrees" / "plan-42"

    remote_wt = clone.parent / "remote-checkout"
    remote_wt.mkdir()
    run_worker.position_worktree(remote_wt, run_id="RID-REMOTE", stage=stage, plan_ref=ref)

    assert cache.plan_ref_path(local_wt).read_bytes() == cache.plan_ref_path(remote_wt).read_bytes()
    assert (
        cache.plan_body_path(local_wt).read_bytes() == cache.plan_body_path(remote_wt).read_bytes()
    )


def test_positioning_delivers_skills_via_the_sync_seam(tmp_path, monkeypatch):
    # Positioning delivers `.agents/skills/` through the canonical `sync_skills` gesture,
    # against the checkout root.
    calls: list[dict] = []

    def recorder(root, changes, **kw):
        calls.append({"root": root, "changes": changes, **kw})
        return None

    monkeypatch.setattr(init_mod, "sync_skills", recorder)
    ref = plan.PlanRef(
        provider="github",
        pr_id="42",
        url="https://gh/o/r/issues/42",
        labels=("perk:plan",),
    )
    monkeypatch.setattr(plans, "get_plan_body", lambda **_k: "# plan body\n")
    stage = next(s for s in load_registry().stages if s.id == "implement")

    run_worker.position_worktree(tmp_path, run_id="RID-S", stage=stage, plan_ref=ref)

    assert len(calls) == 1
    assert calls[0]["root"] == tmp_path


def test_skills_sync_failure_is_fatal_and_pre_spawn(tmp_path, fake_github, monkeypatch):
    # The chosen fatal posture: a failed sync raises before the worker spawns and before the
    # run is reported started — the same loud pre-spawn failure path as plan_not_found.
    _make_entry(tmp_path)
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: "sync exploded")
    spawned: list[list] = []
    monkeypatch.setattr(
        run_worker.subprocess, "run", lambda argv, **k: spawned.append(argv) or None
    )
    started: list[str] = []
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: started.append("started"))

    with pytest.raises(UserFacingCliError) as exc:
        run_worker.run_worker(
            repo_root=tmp_path,
            run_id="RID-F",
            stage_id="implement",
            plan="42",
            base=None,
            environ={"PATH": "/usr/bin"},
        )
    assert exc.value.error_type == "skills_sync_failed"
    assert "sync exploded" in str(exc.value)
    assert spawned == []  # the worker never spawned
    assert started == []  # the run was never reported started


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


def test_spawn_injects_fff_override_env_default(tmp_path, fake_github, monkeypatch):
    """The remote spawn site injects the PI_FFF_MODE=override default when the passed environ
    lacks it (execution-path parity with the local `_exec_pi` seam), and a caller-provided
    environ value wins (merge order: environ is spread after FFF_OVERRIDE_ENV)."""
    _make_entry(tmp_path)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_worker.subprocess, "run", fake_run)
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: None)
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: None)

    def spawn(environ):
        run_worker.run_worker(
            repo_root=tmp_path,
            run_id="RID9",
            stage_id="address",
            plan="42",
            base=None,
            environ=environ,
        )
        return captured["kwargs"]["env"]

    assert spawn({"PATH": "/usr/bin"})["PI_FFF_MODE"] == "override"  # injected default
    env = spawn({"PATH": "/usr/bin", "PI_FFF_MODE": "tools-and-ui"})
    assert env["PI_FFF_MODE"] == "tools-and-ui"  # operator/workflow environ wins


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
    """Run-started is emitted beside report_started (with the Actions run URL when the
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
    assert started[0]["plan_ref"].pr_id == "42"
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
        raise IssueBackendError("agent substrate down")

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


def _seed_consumer_package(tmp_path):
    """A minimal npm-installed `@mgiles/perk` layout under `.pi/npm/node_modules/`."""
    pkg = tmp_path / ".pi" / "npm" / "node_modules" / "@mgiles" / "perk"
    (pkg / "extension").mkdir(parents=True)
    (pkg / "extension" / "workerMain.ts").write_text("// w\n", encoding="utf-8")
    (pkg / "shared").mkdir()
    (pkg / "shared" / "stages.yaml").write_text("stages: []\n", encoding="utf-8")
    (pkg / "package.json").write_text('{"name": "@mgiles/perk"}\n', encoding="utf-8")
    return pkg


def test_worker_entry_consumer_npm_install_is_staged_outside_node_modules(tmp_path):
    # B8: Node refuses to type-strip .ts files under node_modules, so the consumer entry is a
    # fresh full-package copy at `.pi/npm/perk-worker/` (package-root resources ride along; bare
    # imports resolve by walking up to `.pi/npm/node_modules`).
    pkg = _seed_consumer_package(tmp_path)
    (pkg / "node_modules").mkdir()  # a nested install tree must not ride along
    (pkg / "node_modules" / "stray.txt").write_text("x\n", encoding="utf-8")
    resolved = run_worker.resolve_worker_entry(tmp_path, {})
    staged = tmp_path / ".pi" / "npm" / "perk-worker"
    assert resolved.path == staged / "extension" / "workerMain.ts"
    assert resolved.source == "consumer-npm"
    assert "node_modules" not in resolved.path.relative_to(tmp_path).parts
    assert resolved.path.read_text(encoding="utf-8") == "// w\n"
    assert (staged / "shared" / "stages.yaml").is_file()
    assert (staged / "package.json").is_file()
    assert not (staged / "node_modules").exists()


def test_worker_entry_consumer_staging_is_refreshed_per_resolve(tmp_path):
    # A reinstalled/upgraded package must never leave a stale staged copy behind.
    _seed_consumer_package(tmp_path)
    staged = tmp_path / ".pi" / "npm" / "perk-worker"
    (staged / "extension").mkdir(parents=True)
    (staged / "extension" / "workerMain.ts").write_text("// stale\n", encoding="utf-8")
    (staged / "leftover.txt").write_text("x\n", encoding="utf-8")
    resolved = run_worker.resolve_worker_entry(tmp_path, {})
    assert resolved.path.read_text(encoding="utf-8") == "// w\n"
    assert not (staged / "leftover.txt").exists()


# --- position_branch: the relocated workflow shell step (contracts.md §8.46) ------------


_LINEAGE = "01JB0000000000000000000000"


def _g(cwd, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _push_side_branch(remote: Path, name: str, *, parent_dir: Path) -> str:
    """Push branch ``name`` (one commit ahead of main) to the bare remote from a side clone;
    return its head SHA."""
    import subprocess

    side = parent_dir / f"side-{name}"
    subprocess.run(["git", "clone", "-q", str(remote), str(side)], check=True, capture_output=True)
    _g(side, "config", "user.email", "t@example.com")
    _g(side, "config", "user.name", "perk tests")
    _g(side, "checkout", "-q", "-b", name)
    (side / f"{name}.txt").write_text("layer\n", encoding="utf-8")
    _g(side, "add", ".")
    _g(side, "commit", "-qm", f"seed {name}")
    _g(side, "push", "-q", "-u", "origin", name)
    return _g(side, "rev-parse", "HEAD").strip()


def _incremental_ref(pr_id: str = "42") -> plan.PlanRef:
    return plan.PlanRef(
        provider="github",
        pr_id=pr_id,
        url=f"https://gh/o/r/issues/{pr_id}",
        labels=("perk:plan",),
    )


def _stacked_ref(pr_id: str = "102") -> plan.PlanRef:
    return plan.PlanRef(
        provider="github",
        pr_id=pr_id,
        url=f"https://gh/o/r/issues/{pr_id}",
        labels=("perk:plan",),
        objective_id="10",
        delivery_lineage=_LINEAGE,
    )


def _stacked_train(*, ready: bool = True):
    from perk.delivery import train as train_mod

    def layer(node_id, plan_id, branch):
        return train_mod.TrainLayer(
            node_id=node_id,
            plan_id=plan_id,
            branch=branch,
            pr_number=None,
            intent=train_mod.LayerIntent.PLANNED,
            publication=train_mod.LayerPublication.UNPUBLISHED,
            git=train_mod.LayerGit.ABSENT,
            pr=train_mod.LayerPr.ABSENT,
            membership=train_mod.LayerMembership.NOT_APPLICABLE,
            writer=train_mod.LayerWriter.FREE,
            finalization=train_mod.LayerFinalization.NOT_MERGED,
            parent_checkpoint_sha=None,
            published_head_sha=None,
            observed_remote_head_sha=None,
            observed_pr_base=None,
            expected_pr_base=None,
        )

    return train_mod.DeliveryTrain(
        objective_id="10",
        objective_url="u/10",
        delivery_lineage=_LINEAGE,
        base="main",
        redirected_from=None,
        layers=(layer("1.1", "101", "plan-101"), layer("1.2", "102", "plan-102")),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=train_mod.BuildReadiness(
            next_node_id="1.2" if ready else None,
            ready=ready,
            reason=None if ready else "the train has blocker findings: [x] y",
        ),
    )


def _stub_delivery(monkeypatch, result) -> None:
    class FakeDelivery:
        def status(self, request):
            return StatusResult(
                objective_id=result.objective_id,
                objective_url=result.objective_url,
                redirected_from=result.redirected_from,
                train=result,
                no_train_reason=None,
            )

    monkeypatch.setattr(worktree_mod, "resolve_delivery", lambda _root: FakeDelivery())


def test_position_branch_existing_remote_branch_resets_to_the_remote_tip(
    git_repo_with_remote, stub_position_branch
):
    # Behavior-equivalent to the removed shell's branch-exists arm: check out + hard-reset —
    # a stale local plan-42 is repositioned onto the remote tip.
    clone, remote, _advance = git_repo_with_remote
    tip = _push_side_branch(remote, "plan-42", parent_dir=clone.parent)
    _g(clone, "checkout", "-q", "-b", "plan-42")  # a stale local branch at old main
    _g(clone, "checkout", "-q", "main")
    stub_position_branch.real(clone, _incremental_ref(), "main")
    assert _g(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "plan-42"
    assert _g(clone, "rev-parse", "HEAD").strip() == tip


def test_position_branch_fresh_incremental_creates_from_origin_base(
    git_repo_with_remote, stub_position_branch
):
    # Behavior-equivalent to the removed shell's fresh-plan arm: create plan-<N> from
    # origin/<base>.
    clone, _remote, _advance = git_repo_with_remote
    main_sha = _g(clone, "rev-parse", "origin/main").strip()
    stub_position_branch.real(clone, _incremental_ref(), "main")
    assert _g(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "plan-42"
    assert _g(clone, "rev-parse", "HEAD").strip() == main_sha


def test_position_branch_stacked_not_ready_is_a_typed_refusal(
    git_repo_with_remote, stub_position_branch, monkeypatch
):
    clone, _remote, _advance = git_repo_with_remote
    _stub_delivery(monkeypatch, _stacked_train(ready=False))
    with pytest.raises(UserFacingCliError) as excinfo:
        stub_position_branch.real(clone, _stacked_ref(), "main")
    assert excinfo.value.error_type == "node_not_build_ready"


def test_positioning_parity_stacked_local_create_vs_remote_position(
    git_repo_with_remote, stub_position_branch, monkeypatch
):
    """The §8.46 parity proof: from two clones of ONE bare remote — no pre-existing worktrees,
    no local stack metadata — local fresh creation (`resolve_worktree`) and remote positioning
    (`position_branch`) produce the SAME branch start SHA and byte-identical
    `layer-context.json` (timestamps excepted). The branch-creation GESTURE intentionally
    differs (worktree add vs in-place checkout -b); the prepared start does not."""
    import json as json_mod

    from perk.run.launch.worktree import WorktreeRequest, resolve_worktree
    from perk.substrate.config import Config
    from perk.substrate.registry import load_registry

    local_clone, remote, _advance = git_repo_with_remote
    parent_sha = _push_side_branch(remote, "plan-101", parent_dir=local_clone.parent)
    remote_clone = local_clone.parent / "remote-clone"
    shutil.copytree(local_clone, remote_clone, symlinks=True)

    _stub_delivery(monkeypatch, _stacked_train())

    # Path A — local fresh creation (the launch path).
    cache.write_plan_ref(local_clone, _stacked_ref())
    stage = next(s for s in load_registry().stages if s.id == "implement")
    resolved = resolve_worktree(
        repo_root=local_clone,
        config=Config(worktree_root=local_clone / ".worktrees"),
        request=WorktreeRequest.for_stage(stage),
        worktree=None,
        materialize=True,
    )
    local_head = _g(resolved.path, "rev-parse", "HEAD").strip()
    assert resolved.disposition == "create-fresh"
    assert resolved.base == parent_sha
    assert _g(resolved.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == "plan-102"

    # Path B — remote positioning (the run-worker path; the checkout IS the worktree).
    stub_position_branch.real(remote_clone, _stacked_ref(), "main")
    remote_head = _g(remote_clone, "rev-parse", "HEAD").strip()
    assert _g(remote_clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "plan-102"

    assert local_head == remote_head == parent_sha
    local_record = json_mod.loads(
        (resolved.path / ".perk" / "workflow" / "layer-context.json").read_text(encoding="utf-8")
    )
    remote_record = json_mod.loads(
        (remote_clone / ".perk" / "workflow" / "layer-context.json").read_text(encoding="utf-8")
    )
    local_record.pop("prepared_at")
    remote_record.pop("prepared_at")
    assert local_record == remote_record
    assert local_record["parent_sha"] == parent_sha
    assert local_record["parent_branch"] == "plan-101"
    assert local_record["branch"] == "plan-102"
    assert local_record["predecessor_plan_id"] == "101"
    assert local_record["delivery_lineage"] == _LINEAGE


def test_run_worker_positions_the_branch_before_the_worktree_and_the_spawn(
    tmp_path, fake_github, monkeypatch
):
    # The relocated positioning (contracts.md §8.46) must run with the reconstructed plan
    # ref/base BEFORE worktree materialization and the worker spawn — deleting or reordering
    # the production call must fail this test, not just leave remote drives on the checkout
    # branch.
    _make_entry(tmp_path)
    events: list[tuple] = []
    monkeypatch.setattr(
        run_worker,
        "position_branch",
        lambda repo_root, plan_ref, base: events.append(("branch", plan_ref.pr_id, base)),
    )
    monkeypatch.setattr(
        run_worker,
        "position_worktree",
        lambda repo_root, *, run_id, stage, plan_ref: events.append(("worktree", plan_ref.pr_id)),
    )
    monkeypatch.setattr(
        run_worker,
        "_spawn_worker",
        lambda entry, *, stage_id, worktree, run_id, environ: events.append(("spawn",)) or 0,
    )
    monkeypatch.setattr(run_report, "report_started", lambda *a, **k: None)
    monkeypatch.setattr(run_report, "report_terminal", lambda *a, **k: None)
    code = run_worker.run_worker(
        repo_root=tmp_path,
        run_id="RID123",
        stage_id="implement",
        plan="42",
        base="main",
        environ={"PATH": "/usr/bin"},
    )
    assert code == 0
    assert events == [("branch", "42", "main"), ("worktree", "42"), ("spawn",)]
