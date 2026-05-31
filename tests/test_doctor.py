"""T6 — `perk doctor`.

Three layers (phase-0-turn-6 §6.f / §10.7):
- **pure** (no monkeypatch): synthetic `Check` lists exercise exit-code / healthy / json / render;
- **engine** (verify=False): groups, the `--fix` round-trip, self/consumer, no-silent-pass;
- **coherence guard**: every required capability has a doctor check (the D2 SSOT, on coverage).
"""

import shutil

from perk import capabilities, init
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
