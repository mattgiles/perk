"""T6 — `perk doctor`.

Three layers (phase-0-turn-6 §6.f / §10.7):
- **pure** (no monkeypatch): synthetic `Check` lists exercise exit-code / healthy / json / render;
- **engine** (verify=False): groups, the `--fix` round-trip, self/consumer, no-silent-pass;
- **coherence guard**: every required capability has a doctor check (the D2 SSOT, on coverage).
"""

import os
import shutil
import subprocess

import pytest

from perk import capabilities, git, init
from perk.cli.commands import doctor_cmd
from perk.doctor import Check, DoctorReport, report_to_dict, run_doctor
from perk.init import run_init


def _check(name="x", group="g", status="ok", **kw):
    return Check(name=name, group=group, status=status, message="m", **kw)


# --- pure layer (no monkeypatch) ------------------------------------------------------------


def test_exit_code_healthy_allows_warnings():
    report = DoctorReport(
        checks=[_check(status="ok"), _check(status="warn")], fixed=[], self_repo=False
    )
    assert report.healthy and report.exit_code == 0


def test_exit_code_unhealthy_on_fail():
    report = DoctorReport(checks=[_check(status="fail")], fixed=[], self_repo=False)
    assert not report.healthy and report.exit_code == 1


def test_exit_code_not_repo_is_two():
    report = DoctorReport.not_repo()
    assert report.exit_code == 2 and report.error_type == "not_a_repo" and not report.healthy


def test_report_to_dict_shape():
    report = DoctorReport(
        checks=[_check(status="ok"), _check(status="warn"), _check(status="fail")],
        fixed=["did a thing"],
        self_repo=True,
    )
    data = report_to_dict(report)
    assert data["success"] is True and data["healthy"] is False and data["self_repo"] is True
    assert data["summary"] == {"passed": 1, "warnings": 1, "failed": 1}
    checks = data["checks"]
    assert isinstance(checks, list) and len(checks) == 3
    assert data["fixed"] == ["did a thing"]


def test_render_three_way_condensed(capsys):
    checks = [
        _check("git", "environment", "ok"),
        _check("gh", "environment", "ok"),
        _check(
            "gitignore-block", "repository", "fail", detail="drift", remediation="perk doctor --fix"
        ),
        _check("github-auth", "github", "warn", remediation="Run: gh auth login"),
    ]
    doctor_cmd._render(DoctorReport(checks=checks, fixed=[], self_repo=False), verbose=False)
    err = capsys.readouterr().err
    assert "environment (2 checks)" in err  # clean group collapses
    assert "repository (0/1 checks)" in err  # failing group expands its failure
    assert "github (1 checks)" in err  # warning group expands its warning
    assert "perk doctor --fix" in err and "gh auth login" in err  # consolidated remediation
    assert "1 check(s) failed" in err


# --- engine (verify=False) ------------------------------------------------------------------


def _scaffold(repo):
    run_init(repo, verify=False)
    return repo


def test_healthy_after_init(git_repo):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    assert report.healthy and report.exit_code == 0
    groups = {c.group for c in report.checks}
    assert {"package", "repository", "registry", "state"} <= groups
    assert "environment" not in groups and "github" not in groups  # external shells skipped


def test_providers_check_ok_on_default_repo(git_repo):
    # A default repo (no [providers] selection) resolves to the reference providers → `ok`.
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    providers = next(c for c in report.checks if c.name == "providers")
    assert providers.status == "ok" and providers.group == "providers"
    assert "plan=perk-plan" in providers.message and "todo=perk-checkpoints" in providers.message
    assert report.exit_code == 0


def test_providers_check_warns_on_unknown_selection(git_repo):
    # A selection naming a non-existent provider is a loud-but-non-fatal warn (exit still 0).
    _scaffold(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text('[providers]\nplan = "ghost"\n', encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    providers = next(c for c in report.checks if c.name == "providers")
    assert providers.status == "warn"
    assert "unknown provider `ghost`" in providers.detail
    assert report.exit_code == 0  # a selection typo never fails doctor


def test_subagent_engine_signal_and_defs_dir(git_repo):
    # P2.T6: the constant informational pointer is `ok`, and the defs-dir convergence is `ok`
    # on a freshly-converged repo.
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    engine = next(c for c in report.checks if c.name == "subagent-engine")
    assert engine.status == "ok" and engine.group == "package"
    defs = next(c for c in report.checks if c.name == "subagent-agents")
    assert defs.status == "ok"


def test_missing_agents_dir_is_fail_only_on_owning_check(git_repo):
    # Removing `.pi/agents/` fails the owning `subagent-agents` convergence, NOT the
    # informational `subagent-engine` pointer (no duplicate drift). `--fix` re-creates it.
    _scaffold(git_repo)
    shutil.rmtree(git_repo / ".pi" / "agents")
    report = run_doctor(git_repo, verify=False)
    assert "subagent-agents" in {c.name for c in report.checks if c.status == "fail"}
    assert next(c for c in report.checks if c.name == "subagent-engine").status == "ok"
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".pi" / "agents" / ".gitkeep").is_file() and fixed.healthy


def test_drift_detected_and_fixed_idempotently(git_repo):
    _scaffold(git_repo)
    (git_repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")  # clobber the block
    report = run_doctor(git_repo, verify=False)
    assert not report.healthy
    assert "gitignore-block" in {c.name for c in report.checks if c.status == "fail"}

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy and fixed.fixed
    again = run_doctor(git_repo, fix=True, verify=False)
    assert again.healthy and again.fixed == []  # fix is idempotent


def test_legacy_tracked_plan_md_is_repaired(git_repo):
    # #43: `.pi/workflow/plan.md` is a transient cache.plan body. A legacy repo committed it and
    # hand-added a stray ungrouped ignore line. `--fix` untracks the file + removes the stray
    # line (the managed block already owns it), idempotently.
    _scaffold(git_repo)
    rel = ".pi/workflow/plan.md"
    plan_md = git_repo / rel
    plan_md.write_text("# materialized plan body\n", encoding="utf-8")
    # Simulate the legacy stray ungrouped ignore line (outside the managed block).
    gitignore = git_repo / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + f"/{rel}\n", encoding="utf-8")
    # Force-track it past its own ignore rule (mirrors how it got committed before the rule).
    subprocess.run(
        ["git", "add", "-f", rel], cwd=git_repo, check=True, capture_output=True, text=True
    )
    assert git.is_tracked(git_repo, rel)

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy and fixed.fixed
    # The file is untracked but left on disk (cache, not deleted); the stray line is gone, and
    # exactly one managed occurrence of the ignore line remains.
    assert not git.is_tracked(git_repo, rel)
    assert plan_md.is_file()
    assert gitignore.read_text(encoding="utf-8").count(f"/{rel}\n") == 1
    again = run_doctor(git_repo, fix=True, verify=False)
    assert again.healthy and again.fixed == []  # repair is idempotent


def test_skills_manifest_drift_detected_and_fixed(git_repo):
    # The committed manifest fragment is a managed convergence: tampering is drift, and `--fix`
    # re-converges it idempotently (grouped under "skills").
    _scaffold(git_repo)
    fragment = git_repo / ".agents" / "manifest.d" / "perk.yaml"
    assert fragment.is_file()
    report = run_doctor(git_repo, verify=False)
    skills_check = next(c for c in report.checks if c.name == "skills-manifest")
    assert skills_check.status == "ok" and skills_check.group == "skills"

    fragment.write_text("# clobbered\n", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    assert "skills-manifest" in {c.name for c in report.checks if c.status == "fail"}

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy and fixed.fixed
    again = run_doctor(git_repo, fix=True, verify=False)
    assert again.healthy and again.fixed == []  # fix is idempotent


def test_missing_workflow_subdir_is_fixed(git_repo):
    _scaffold(git_repo)
    shutil.rmtree(git_repo / ".pi" / "workflow" / "handoff")
    report = run_doctor(git_repo, verify=False)
    assert "workflow-dir" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".pi" / "workflow" / "handoff").is_dir() and fixed.healthy


def test_config_user_edit_is_not_drift(git_repo):
    _scaffold(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text(
        "[worktree]\nroot = 'custom-wt'\n", encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    config = next(c for c in report.checks if c.name == "config")
    assert config.status == "ok"  # user-editable config is never flagged as drift


def test_missing_config_is_reseeded(git_repo):
    _scaffold(git_repo)
    (git_repo / ".pi" / "perk.toml").unlink()
    report = run_doctor(git_repo, verify=False)
    assert "config" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".pi" / "perk.toml").is_file() and fixed.healthy


def test_no_silent_pass_on_unverifiable_check(git_repo):
    _scaffold(git_repo)
    (git_repo / ".pi" / "settings.json").write_text("{not json", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    settings = next(c for c in report.checks if c.name == "settings-wiring")
    assert settings.status == "fail"  # un-evaluable -> fail, never a silent ok


def test_unreadable_managed_file_is_fail_not_crash(git_repo):
    _scaffold(git_repo)
    agents = git_repo / "AGENTS.md"
    agents.chmod(0o000)
    # Skip-guard: root (and some CI) can read through a 0o000 mode, so the boundary never trips.
    if os.access(agents, os.R_OK):
        agents.chmod(0o644)
        pytest.skip("cannot revoke read access (likely running as root)")
    try:
        report = run_doctor(git_repo, verify=False)  # must not raise
    finally:
        agents.chmod(0o644)
    agents_block = next(c for c in report.checks if c.name == "agents-block")
    assert agents_block.status == "fail"  # un-readable -> fail, never a crash


# --- skills sync under --fix (the repair gesture) -------------------------------------------


def test_fix_verify_stays_healthy_with_stubbed_sync(git_repo, stub_env):
    # `stub_env` no-ops `init._sync_skills`; `run_doctor(fix=True, verify=True)` must not crash
    # and stays healthy on a freshly converged repo.
    _scaffold(git_repo)
    report = run_doctor(git_repo, fix=True, verify=True)
    assert report.healthy and report.exit_code == 0


def test_fix_invokes_sync_under_verify(git_repo, monkeypatch, stub_env):
    # `stub_env` keeps env/github offline; re-patch the sync seam (overriding the fixture's
    # no-op) to observe that `--fix` materializes skills under `verify`.
    _scaffold(git_repo)
    called = []
    monkeypatch.setattr(init, "_sync_skills", lambda root, changes: called.append(root))
    run_doctor(git_repo, fix=True, verify=True)
    assert called == [git_repo]


def test_plain_doctor_does_not_sync(git_repo, monkeypatch, stub_env):
    _scaffold(git_repo)
    called = []
    monkeypatch.setattr(init, "_sync_skills", lambda root, changes: called.append(root))
    run_doctor(git_repo, fix=False, verify=True)
    assert called == []


# --- bindings check (Node 3.1) --------------------------------------------------------------


def _install_default_skills(root, subdir=".agents/skills"):
    """Plant a SKILL.md for each of the 8 shipped default binding skills under ``subdir``."""
    from perk.bindings import load_bindings

    for binding in load_bindings().bindings:
        path = root / subdir / binding.skill / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# skill\n", encoding="utf-8")


def _bindings_check(report):
    return next(c for c in report.checks if c.name == "bindings")


def test_bindings_check_ok_when_defaults_installed(git_repo):
    _scaffold(git_repo)
    _install_default_skills(git_repo)
    check = _bindings_check(run_doctor(git_repo, verify=False))
    assert check.status == "ok" and check.group == "bindings"


def test_bindings_check_warns_on_missing_skill_but_stays_healthy(git_repo):
    _scaffold(git_repo)
    _install_default_skills(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text(
        '[[bindings]]\ntrigger = "stage:plan"\nskill = "ghost-skill"\nmode = "nudge"\n',
        encoding="utf-8",
    )
    report = run_doctor(git_repo, verify=False)
    check = _bindings_check(report)
    assert check.status == "warn" and "ghost-skill" in check.detail
    assert report.healthy and report.exit_code == 0  # loud-but-non-fatal


def test_bindings_check_warns_on_unknown_stage_target(git_repo):
    _scaffold(git_repo)
    _install_default_skills(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text(
        '[[bindings]]\ntrigger = "stage:nope"\nskill = "perk-plan"\nmode = "nudge"\n',
        encoding="utf-8",
    )
    check = _bindings_check(run_doctor(git_repo, verify=False))
    assert check.status == "warn" and "nope" in check.detail


def test_bindings_check_warns_on_command_without_delivery_surface(git_repo):
    _scaffold(git_repo)
    _install_default_skills(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text(
        '[[bindings]]\ntrigger = "command:ci"\nskill = "perk-plan"\nmode = "nudge"\n',
        encoding="utf-8",
    )
    check = _bindings_check(run_doctor(git_repo, verify=False))
    assert check.status == "warn" and "never fires" in check.detail


def test_bindings_check_self_repo_skills_fallback(git_repo):
    _scaffold(git_repo)
    (git_repo / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    _install_default_skills(git_repo, subdir="skills")  # perk's own layout, not .agents/skills
    report = run_doctor(git_repo, verify=False)
    assert report.self_repo is True
    assert _bindings_check(report).status == "ok"  # self-repo skills/ fallback, not 8 warnings


def test_self_vs_consumer_dual_mode(git_repo):
    _scaffold(git_repo)
    assert run_doctor(git_repo, verify=False).self_repo is False
    (git_repo / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    assert run_doctor(git_repo, verify=False).self_repo is True


# --- coherence guard (the D2 SSOT, on coverage) ---------------------------------------------


def test_every_required_capability_has_a_doctor_check(git_repo):
    _scaffold(git_repo)
    check_names = {c.name for c in run_doctor(git_repo, verify=False).checks}

    covered = {"config"}  # the config check covers the `config` capability
    for mc in init.managed_convergences(git_repo, False):
        assert mc.name in check_names  # every dry-run convergence is verified by a check
        covered |= set(mc.covers)

    applicable = {cap.name for cap in capabilities.applicable(False)}
    assert applicable <= covered  # no required capability is left unverified
