"""`perk doctor`.

Three layers:
- **pure** (no monkeypatch): synthetic `Check` lists exercise exit-code / healthy / json / render;
- **engine** (verify=False): groups, the `--fix` round-trip, self/consumer, no-silent-pass;
- **coherence guard**: every required capability has a doctor check (the D2 SSOT, on coverage).
"""

import os
import shutil
import subprocess

import pytest

from perk import __version__, github
from perk.backends import linear
from perk.cli.commands.doctor import render
from perk.convergence import capabilities, init
from perk.convergence import doctor as doctor_mod
from perk.convergence.doctor import (
    Check,
    DoctorReport,
    _repo_skills_check,
    _runner_checks,
    _skills_delivery_check,
    report_to_dict,
    run_doctor,
)
from perk.convergence.init import run_init
from perk.substrate import git, paths


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


def test_optional_env_tool_maps_to_warn(monkeypatch):
    # A missing optional tool (ast-grep) renders as `warn`, not `fail` — so a report whose only
    # non-ok environment check is optional stays healthy with exit code 0.
    from perk.convergence.env import EnvCheck

    monkeypatch.setattr(
        doctor_mod.env,
        "check_environment",
        lambda: [
            EnvCheck("git", True, "/usr/bin/git", ""),
            EnvCheck("ast-grep", False, "not found", "install it", optional=True),
        ],
    )
    checks = doctor_mod._env_checks()
    ast_grep = next(c for c in checks if c.name == "ast-grep")
    assert ast_grep.status == "warn" and ast_grep.remediation == "install it"
    report = DoctorReport(checks=checks, fixed=[], self_repo=False)
    assert report.healthy and report.exit_code == 0


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
    render.render_report(DoctorReport(checks=checks, fixed=[], self_repo=False), verbose=False)
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
    assert "askuser=perk-ask-user" in providers.message
    assert "footer=perk-footer" in providers.message
    assert "web=pi-web-access" in providers.message
    assert report.exit_code == 0


def test_providers_check_warns_on_unknown_selection(git_repo):
    # A selection naming a non-existent provider is a loud-but-non-fatal warn (exit still 0).
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        '[providers]\nplan = "ghost"\n', encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    providers = next(c for c in report.checks if c.name == "providers")
    assert providers.status == "warn"
    assert "unknown provider `ghost`" in providers.detail
    assert report.exit_code == 0  # a selection typo never fails doctor


def test_issues_check_ok_on_default_repo(git_repo):
    # No [issues] selection → the github default → ok.
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
    assert check.status == "ok" and check.group == "issues"
    assert check.message == "issues backend: github"


def test_issues_check_ok_on_linear_with_team(git_repo):
    # linear + a committed team is a live, valid selection → ok (with the team in the message).
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        '[issues]\nbackend = "linear"\nteam = "ENG"\n', encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
    assert check.status == "ok"
    assert check.message == "issues backend: linear (team ENG)"


def test_issues_check_fails_on_linear_without_team(git_repo):
    # Offline-decidable misconfiguration: linear without a team hard-breaks every
    # issue-touching command → fail.
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        '[issues]\nbackend = "linear"\n', encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
    assert check.status == "fail"
    assert "[issues] team is required" in check.message
    assert "[issues] team" in check.remediation
    assert report.exit_code == 1


def test_issues_check_fails_on_unknown_selection(git_repo):
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        '[issues]\nbackend = "jira"\n', encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
    assert check.status == "fail"
    assert "unknown issue backend" in check.message


def test_issues_check_warns_on_malformed_committed_toml(git_repo):
    # Malformed TOML is the config check's finding; the issues check defers (mirrors providers).
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text("[issues\nbackend =", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
    assert check.status == "warn"
    assert "see the config check" in check.message


def test_stage_models_check_absent_when_unconfigured(git_repo):
    # No [stages] config → the check contributes nothing (keeps a clean repo quiet).
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    assert next((c for c in report.checks if c.name == "stage-models"), None) is None


def test_stage_models_check_ok_on_valid_config(git_repo):
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        '[stages.implement]\nmodel = "a/opus"\nthinking = "high"\n', encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "stage-models")
    assert check.status == "ok" and check.group == "repository"
    assert "implement" in check.message
    assert report.exit_code == 0


def test_stage_models_check_warns_on_unknown_stage(git_repo):
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        '[stages.implment]\nmodel = "a/opus"\n', encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "stage-models")
    assert check.status == "warn"
    assert "implment" in check.detail
    assert report.exit_code == 0  # loud-but-non-fatal


def test_stage_models_check_warns_on_invalid_thinking(git_repo):
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        '[stages.implement]\nthinking = "ultra"\n', encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "stage-models")
    assert check.status == "warn"
    assert "ultra" in check.detail
    assert report.exit_code == 0


def test_stage_models_check_warns_on_malformed_committed_toml(git_repo):
    # Malformed TOML defers to the config check (mirrors providers/issues).
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text("[stages.implement\nmodel =", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "stage-models")
    assert check.status == "warn"
    assert "see the config check" in check.message


def test_issues_group_renders():
    # The _GROUP_ORDER trap: a group missing from GROUP_ORDER silently doesn't render.
    from perk.cli.commands.doctor.render import GROUP_ORDER

    assert "issues" in GROUP_ORDER


def test_linear_group_renders():
    # The _GROUP_ORDER trap again: the verify-gated linear group must be render-visible.
    from perk.cli.commands.doctor.render import GROUP_ORDER

    assert "linear" in GROUP_ORDER


# --- the verify-gated `linear` group ---------------------------------------------------------


def _select_linear(repo, *, team=True):
    body = '[issues]\nbackend = "linear"\n'
    if team:
        body += 'team = "ENG"\n'
    (repo / ".perk" / "config.toml").write_text(body, encoding="utf-8")


def _linear_group(report):
    return [c for c in report.checks if c.group == "linear"]


def test_linear_checks_absent_without_verify(git_repo):
    _scaffold(git_repo)
    _select_linear(git_repo)
    report = run_doctor(git_repo, verify=False)
    assert _linear_group(report) == []


def test_linear_checks_absent_on_github_selection(git_repo, stub_env):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=True)
    assert _linear_group(report) == []


def test_linear_checks_ok_when_ready(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=True
        ),
    )
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(projects_ok=True),
    )
    report = run_doctor(git_repo, verify=True)
    group = {c.name: c for c in _linear_group(report)}
    assert group["linear-auth"].status == "ok" and "Mat" in group["linear-auth"].message
    assert group["linear-team"].status == "ok" and "ENG" in group["linear-team"].message
    assert group["linear-labels"].status == "ok"
    assert group["linear-project-scopes"].status == "ok"
    assert group["linear-workflow-states"].status == "ok"


def test_linear_checks_ok_with_key_from_local_config(git_repo, stub_env, monkeypatch):
    # The key supplied via .perk/local.toml [linear] api_key (env unset) is threaded through
    # to client_from_env(repo_root=...), so the auth check passes without an exported var.
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    (git_repo / ".perk" / "local.toml").write_text(
        '[linear]\napi_key = "lin_api_local"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=True
        ),
    )
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(projects_ok=True),
    )
    report = run_doctor(git_repo, verify=True)
    group = {c.name: c for c in _linear_group(report)}
    assert group["linear-auth"].status == "ok" and "Mat" in group["linear-auth"].message


def test_linear_checks_warn_on_missing_api_key(git_repo, stub_env, monkeypatch):
    # Network readiness is non-fatal (the github-group D3 mirror): warn, never fail.
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    report = run_doctor(git_repo, verify=True)
    group = _linear_group(report)
    assert [c.name for c in group] == ["linear-auth"]
    assert group[0].status == "warn"
    assert "LINEAR_API_KEY" in group[0].remediation


def test_linear_checks_warn_on_auth_failure(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=False, user=None, team_ok=False, error="bad key"
        ),
    )
    report = run_doctor(git_repo, verify=True)
    group = _linear_group(report)
    assert [c.name for c in group] == ["linear-auth"]
    assert group[0].status == "warn" and group[0].detail == "bad key"


def test_linear_checks_warn_on_team_not_found(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=False, error="Linear team 'ENG' not found"
        ),
    )
    report = run_doctor(git_repo, verify=True)
    group = {c.name: c for c in _linear_group(report)}
    assert group["linear-auth"].status == "ok"
    assert group["linear-team"].status == "warn"
    assert "linear-labels" not in group  # team failure skips labels


def test_linear_checks_warn_on_missing_labels(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=True, missing_labels=("perk:plan",)
        ),
    )
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(projects_ok=True),
    )
    report = run_doctor(git_repo, verify=True)
    labels = next(c for c in _linear_group(report) if c.name == "linear-labels")
    assert labels.status == "warn"
    assert "perk:plan" in labels.message
    assert "doctor --fix" in labels.remediation


def _patch_ready(monkeypatch):
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=True
        ),
    )


def test_linear_project_checks_warn_on_no_project_access(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    _patch_ready(monkeypatch)
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(
            projects_ok=False, projects_error="no access"
        ),
    )
    report = run_doctor(git_repo, verify=True)
    group = {c.name: c for c in _linear_group(report)}
    scopes = group["linear-project-scopes"]
    assert scopes.status == "warn"
    assert scopes.detail == "no access"
    assert "Projects" in scopes.remediation
    # Non-fatal: warn-level, never fail (exit code keys off fail only).
    assert all(c.status != "fail" for c in _linear_group(report))


def test_linear_project_checks_warn_on_missing_state_types(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    _patch_ready(monkeypatch)
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(
            projects_ok=True, missing_state_types=("canceled",)
        ),
    )
    report = run_doctor(git_repo, verify=True)
    group = {c.name: c for c in _linear_group(report)}
    states = group["linear-workflow-states"]
    assert states.status == "warn"
    assert "canceled" in states.message
    assert "canceled" in states.remediation
    assert all(c.status != "fail" for c in _linear_group(report))


def test_linear_project_checks_warn_on_states_probe_error(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    _patch_ready(monkeypatch)
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(
            projects_ok=True, states_error="states boom"
        ),
    )
    report = run_doctor(git_repo, verify=True)
    states = {c.name: c for c in _linear_group(report)}["linear-workflow-states"]
    assert states.status == "warn"
    assert "not verified" in states.message
    assert states.detail == "states boom"


def test_linear_project_checks_absent_on_auth_failure(git_repo, stub_env, monkeypatch):
    # The project probe is gated behind auth+team success — it is not even called.
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=False, user=None, team_ok=False, error="bad key"
        ),
    )

    def _boom(client, *, team_key):
        raise AssertionError("check_project_readiness must not run when auth failed")

    monkeypatch.setattr(doctor_mod.linear, "check_project_readiness", _boom)
    report = run_doctor(git_repo, verify=True)
    names = {c.name for c in _linear_group(report)}
    assert "linear-project-scopes" not in names
    assert "linear-workflow-states" not in names


def test_linear_project_checks_absent_on_team_failure(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: linear.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=False, error="Linear team 'ENG' not found"
        ),
    )

    def _boom(client, *, team_key):
        raise AssertionError("check_project_readiness must not run when team failed")

    monkeypatch.setattr(doctor_mod.linear, "check_project_readiness", _boom)
    report = run_doctor(git_repo, verify=True)
    names = {c.name for c in _linear_group(report)}
    assert "linear-project-scopes" not in names
    assert "linear-workflow-states" not in names


def test_fix_creates_linear_labels(git_repo, stub_env, monkeypatch):
    # The --fix repair gesture: created labels land on `fixed`; idempotent once converged.
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    calls = []

    def fake_readiness(client, *, team_key, ensure_labels):
        calls.append(ensure_labels)
        if ensure_labels:
            return linear.LinearReadiness(
                auth_ok=True, user="Mat", team_ok=True, created_labels=("perk:plan", "perk:learn")
            )
        return linear.LinearReadiness(auth_ok=True, user="Mat", team_ok=True)

    monkeypatch.setattr(doctor_mod.linear, "check_readiness", fake_readiness)
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(projects_ok=True),
    )
    report = run_doctor(git_repo, fix=True, verify=True)
    assert "Linear: created label perk:plan" in report.fixed
    assert "Linear: created label perk:learn" in report.fixed
    assert True in calls  # the repair ran with ensure_labels=True


def test_fix_linear_label_failure_lands_on_fix_errors(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")

    def fake_readiness(client, *, team_key, ensure_labels):
        if ensure_labels:
            return linear.LinearReadiness(
                auth_ok=True, user="Mat", team_ok=True, error="rate limited"
            )
        return linear.LinearReadiness(auth_ok=True, user="Mat", team_ok=True)

    monkeypatch.setattr(doctor_mod.linear, "check_readiness", fake_readiness)
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: linear.LinearProjectReadiness(projects_ok=True),
    )
    report = run_doctor(git_repo, fix=True, verify=True)
    assert any("rate limited" in e for e in report.fix_errors)


def test_fix_skips_linear_repair_without_selection(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    called = []
    monkeypatch.setattr(
        doctor_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: called.append(True),
    )
    run_doctor(git_repo, fix=True, verify=True)
    assert called == []


def test_subagent_engine_signal_and_defs_dir(git_repo):
    # The constant informational pointer is `ok`, and the defs-dir convergence is `ok`
    # on a freshly-converged repo. The informational detail lists the delivered defs.
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    engine = next(c for c in report.checks if c.name == "subagent-engine")
    assert engine.status == "ok" and engine.group == "package"
    assert "perk.pr-reviewer" in engine.detail  # delivered defs enumerated from .pi/agents/perk/
    defs = next(c for c in report.checks if c.name == "subagent-agents")
    assert defs.status == "ok"


def test_edited_delivered_def_reports_drift_and_is_fixed(git_repo):
    # Hand-editing a delivered `.pi/agents/perk/*.md` makes the `subagent-agents` convergence
    # report drift; `--fix` rewrites it byte-for-byte from the bundled source.
    from perk import _resources
    from perk.convergence.init import PERK_AGENTS

    _scaffold(git_repo)
    name = PERK_AGENTS[0]
    delivered = git_repo / ".pi" / "agents" / "perk" / f"{name}.md"
    delivered.write_text("hand-edited\n", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    assert "subagent-agents" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy
    assert delivered.read_bytes() == (_resources.agents_dir() / f"{name}.md").read_bytes()


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


def test_required_perk_version_drift_detected_and_fixed(git_repo):
    _scaffold(git_repo)
    pin = paths.required_version_file(git_repo)

    # (a) missing file → drift in the `package` group → `--fix` recreates it.
    pin.unlink()
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "required-perk-version")
    assert check.status == "fail" and check.group == "package"
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy
    assert pin.read_text(encoding="utf-8") == f"{__version__}\n"

    # (b) stale content → drift → `--fix` rewrites to the running CLI's version.
    pin.write_text("0.0.1\n", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "required-perk-version")
    assert check.status == "fail" and "updated" in check.detail
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy
    assert pin.read_text(encoding="utf-8") == f"{__version__}\n"
    again = run_doctor(git_repo, fix=True, verify=False)
    assert again.healthy and again.fixed == []  # fix is idempotent


def test_cli_version_check_ok_on_converged_repo(git_repo):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "cli-version")
    assert check.status == "ok" and check.group == "package"


def test_cli_version_check_warns_on_stale_pin_beside_managed_fail(git_repo):
    # Deliberate coexistence on one mismatch: the managed `required-perk-version` check owns
    # file drift + `--fix` (fail), while `cli-version` owns the "your CLI may be the stale
    # side" interpretation (warn, never fail — a running CLI cannot install itself).
    _scaffold(git_repo)
    paths.required_version_file(git_repo).write_text("0.0.1\n", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    cli_version = next(c for c in report.checks if c.name == "cli-version")
    managed = next(c for c in report.checks if c.name == "required-perk-version")
    assert cli_version.status == "warn"
    assert "0.0.1" in cli_version.message and __version__ in cli_version.message
    assert managed.status == "fail"


def test_cli_version_check_info_when_pin_missing(git_repo):
    _scaffold(git_repo)
    paths.required_version_file(git_repo).unlink()
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "cli-version")
    assert check.status == "info" and "required-perk-version" in check.detail


def test_cli_version_check_in_json_report(git_repo):
    _scaffold(git_repo)
    payload = report_to_dict(run_doctor(git_repo, verify=False))
    checks = payload["checks"]
    assert isinstance(checks, list)
    names = [v for c in checks if isinstance(c, dict) for k, v in c.items() if k == "name"]
    assert "cli-version" in names


def test_package_group_renders():
    # The _GROUP_ORDER trap: `cli-version` rides the existing `package` group — no new group is
    # introduced; this pins the assumption.
    from perk.cli.commands.doctor.render import GROUP_ORDER

    assert "package" in GROUP_ORDER


def test_legacy_tracked_plan_md_is_repaired(git_repo):
    # `.pi/workflow/plan.md` is a legacy transient cache.plan body. A legacy repo committed it and
    # hand-added a stray ungrouped ignore line. Post-move the managed block no longer ignores it
    # (the whole `.perk/workflow/` tree is gitignored instead), so the line is now a fully-legacy
    # stray. `--fix` untracks the file + removes the stray line idempotently.
    _scaffold(git_repo)
    rel = ".pi/workflow/plan.md"
    plan_md = git_repo / rel
    plan_md.parent.mkdir(parents=True, exist_ok=True)
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
    # The file is untracked but left on disk (cache, not deleted); the stray line is gone, and no
    # occurrence of the legacy ignore line remains (the managed block no longer owns it).
    assert not git.is_tracked(git_repo, rel)
    assert plan_md.is_file()
    assert gitignore.read_text(encoding="utf-8").count(f"/{rel}\n") == 0
    again = run_doctor(git_repo, fix=True, verify=False)
    assert again.healthy and again.fixed == []  # repair is idempotent


def test_untrack_failure_carried_on_fix_errors(git_repo, monkeypatch):
    # The migrations' `git rm --cached` failures are reported on `fix_errors`, never swallowed.
    # With everything reported tracked, both the legacy plan.md untrack and the legacy `.gitkeep`
    # untrack fail loudly.
    _scaffold(git_repo)
    monkeypatch.setattr(git, "is_tracked", lambda root, rel: True)

    def boom(root, rel):
        raise git.GitError("rm --cached exploded")

    monkeypatch.setattr(git, "rm_cached", boom)
    report = run_doctor(git_repo, fix=True, verify=False)
    assert (
        ".pi/workflow/plan.md: untrack failed (git rm --cached): rm --cached exploded"
        in report.fix_errors
    )
    assert (
        ".pi/workflow/.gitkeep: untrack failed (git rm --cached): rm --cached exploded"
        in report.fix_errors
    )
    assert report_to_dict(report)["fix_errors"] == report.fix_errors


def test_tracked_subagent_artifacts_are_untracked(git_repo):
    # `.pi-subagents/` is the borrowed pi-subagents engine's transient run-artifact root. A
    # legacy repo committed artifacts before the managed gitignore entry existed; `--fix`
    # untracks the whole directory (files kept on disk), idempotently.
    _scaffold(git_repo)
    rel = ".pi-subagents/artifacts/run_x_output.md"
    artifact = git_repo / rel
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# subagent run output\n", encoding="utf-8")
    # Force-track it past the managed ignore rule (mirrors how the real files got committed).
    subprocess.run(
        ["git", "add", "-f", rel], cwd=git_repo, check=True, capture_output=True, text=True
    )
    assert git.is_tracked(git_repo, rel)

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy
    assert not git.is_tracked(git_repo, rel)
    assert artifact.is_file()  # untracked, never deleted
    assert ".pi-subagents: untracked 1 transient subagent artifact(s) (kept on disk)" in fixed.fixed
    again = run_doctor(git_repo, fix=True, verify=False)
    assert again.healthy and again.fixed == []  # repair is idempotent


def test_subagent_untrack_failure_carried_on_fix_errors(git_repo, monkeypatch):
    # A failed `.pi-subagents` untrack lands on `fix_errors`, never swallowed.
    _scaffold(git_repo)
    monkeypatch.setattr(
        git,
        "tracked_paths",
        lambda root, pathspecs: [".pi-subagents/artifacts/run_x_output.md"],
    )

    def boom(root, rel, *, recursive=False):
        raise git.GitError("rm -r --cached exploded")

    monkeypatch.setattr(git, "rm_cached", boom)
    report = run_doctor(git_repo, fix=True, verify=False)
    assert (
        ".pi-subagents: untrack failed (git rm -r --cached): rm -r --cached exploded"
        in report.fix_errors
    )
    assert report_to_dict(report)["fix_errors"] == report.fix_errors


def test_legacy_workflow_check_warns_then_ok_after_fix(git_repo):
    # A stale tracked `.pi/workflow/.gitkeep` (the old committed layout sentinel) makes the
    # `legacy-workflow` check `warn`; `--fix` untracks it and the check converges to `ok`.
    _scaffold(git_repo)
    gitkeep = git_repo / ".pi" / "workflow" / ".gitkeep"
    gitkeep.parent.mkdir(parents=True, exist_ok=True)
    gitkeep.write_text("", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".pi/workflow/.gitkeep"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert git.is_tracked(git_repo, ".pi/workflow/.gitkeep")

    report = run_doctor(git_repo, verify=False)
    legacy = {c.name: c for c in report.checks}["legacy-workflow"]
    assert legacy.status == "warn"

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert not git.is_tracked(git_repo, ".pi/workflow/.gitkeep")
    assert {c.name: c for c in fixed.checks}["legacy-workflow"].status == "ok"


def test_migrate_legacy_workflow_cache(git_repo):
    # The forward migration: untrack a tracked legacy `.gitkeep`, move the simple active mirrors
    # (`plan-ref.json`/`agent-session.json`) to `.perk/workflow/` only when the target is absent,
    # and never touch disposable scratch (run dirs / handoff blobs). Idempotent.
    _scaffold(git_repo)
    legacy = git_repo / ".pi" / "workflow"
    (legacy / "handoff").mkdir(parents=True, exist_ok=True)
    (legacy / ".gitkeep").write_text("", encoding="utf-8")
    (legacy / "plan-ref.json").write_text('{"pr_id": "1"}\n', encoding="utf-8")
    (legacy / "agent-session.json").write_text('{"session_id": "s"}\n', encoding="utf-8")
    # Disposable scratch + a handoff blob that must be left untouched.
    (legacy / "scratch" / "runs" / "01RID").mkdir(parents=True, exist_ok=True)
    (legacy / "scratch" / "runs" / "01RID" / "diff.txt").write_text("x", encoding="utf-8")
    (legacy / "handoff" / "01RID.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".pi/workflow/.gitkeep"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert not git.is_tracked(git_repo, ".pi/workflow/.gitkeep")
    target = git_repo / ".perk" / "workflow"
    assert (target / "plan-ref.json").is_file() and not (legacy / "plan-ref.json").exists()
    assert (target / "agent-session.json").is_file()
    assert not (legacy / "agent-session.json").exists()
    # Disposable scratch + handoff blobs are left where they are (gitignored cache).
    assert (legacy / "scratch" / "runs" / "01RID" / "diff.txt").is_file()
    assert (legacy / "handoff" / "01RID.json").is_file()
    assert any(".pi/workflow/plan-ref.json: moved" in line for line in fixed.fixed)

    again = run_doctor(git_repo, fix=True, verify=False)
    assert not any(".pi/workflow/" in line for line in again.fixed)  # idempotent


def test_migrate_legacy_workflow_cache_keeps_present_target(git_repo):
    # A movable mirror is NOT moved when the `.perk/workflow/` target already exists (no clobber).
    _scaffold(git_repo)
    legacy = git_repo / ".pi" / "workflow"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "plan-ref.json").write_text('{"pr_id": "legacy"}\n', encoding="utf-8")
    target = git_repo / ".perk" / "workflow"
    target.mkdir(parents=True, exist_ok=True)
    (target / "plan-ref.json").write_text('{"pr_id": "live"}\n', encoding="utf-8")

    fixed = run_doctor(git_repo, fix=True, verify=False)
    # The live target is untouched; the legacy copy is left in place (manual cleanup).
    assert (target / "plan-ref.json").read_text(encoding="utf-8") == '{"pr_id": "live"}\n'
    assert (legacy / "plan-ref.json").is_file()
    assert not any(".pi/workflow/plan-ref.json: moved" in line for line in fixed.fixed)


def test_fix_removes_orphaned_git_clone(git_repo):
    # The forward migration: a consumer previously on pi's git-clone has an orphaned
    # `.pi/git/<host>/<path>` tree after the npm install superseded it. `--fix` rmtrees it once
    # (migrating forward) and a second `--fix` is a no-op (idempotent).
    _scaffold(git_repo)
    clone = doctor_mod.init.consumer_git_clone_root(git_repo)
    clone.mkdir(parents=True)
    (clone / "package.json").write_text("{}", encoding="utf-8")

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert not clone.exists()
    rel = clone.relative_to(git_repo)
    assert any("removed orphaned perk clone" in line for line in fixed.fixed)
    assert any(str(rel) in line for line in fixed.fixed)
    again = run_doctor(git_repo, fix=True, verify=False)
    assert not any("removed orphaned perk clone" in line for line in again.fixed)  # idempotent


def test_fix_migrates_legacy_repo_skill_when_target_absent(git_repo):
    # Legacy `.pi/skills/foo` with no `.perk/skills/foo` target → moved forward; idempotent.
    _scaffold(git_repo)
    legacy = git_repo / ".pi" / "skills" / "foo"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("---\nname: foo\n---\n", encoding="utf-8")

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert not legacy.exists()
    moved = git_repo / ".perk" / "skills" / "foo" / "SKILL.md"
    assert moved.is_file()
    assert any(".pi/skills/foo: moved to .perk/skills/foo" in line for line in fixed.fixed)
    # The now-empty legacy root is rmdir'd (D3 empty-dir cleanup).
    assert not (git_repo / ".pi" / "skills").exists()

    again = run_doctor(git_repo, fix=True, verify=False)
    assert not any(".pi/skills/foo" in line for line in again.fixed)  # idempotent


def test_fix_removes_legacy_repo_skill_when_identical(git_repo):
    # Legacy `.pi/skills/foo` byte-identical to an existing `.perk/skills/foo` → legacy dropped.
    _scaffold(git_repo)
    body = "---\nname: foo\n---\nbody\n"
    legacy = git_repo / ".pi" / "skills" / "foo"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text(body, encoding="utf-8")
    target = git_repo / ".perk" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(body, encoding="utf-8")

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert not legacy.exists()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == body
    assert any(
        ".pi/skills/foo: removed legacy (identical to .perk/skills/foo)" in line
        for line in fixed.fixed
    )


def test_fix_reports_conflict_when_legacy_repo_skill_differs(git_repo):
    # Legacy `.pi/skills/foo` differs from an existing `.perk/skills/foo` → not moved, error.
    _scaffold(git_repo)
    legacy = git_repo / ".pi" / "skills" / "foo"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("---\nname: foo\n---\nlegacy\n", encoding="utf-8")
    target = git_repo / ".perk" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("---\nname: foo\n---\nnew\n", encoding="utf-8")

    report = run_doctor(git_repo, fix=True, verify=False)
    assert legacy.exists()  # left in place for manual resolution
    assert any(
        ".pi/skills/foo: conflicts with .perk/skills/foo" in line for line in report.fix_errors
    )
    assert report_to_dict(report)["fix_errors"] == report.fix_errors  # surfaced in the dict
    assert any(".pi/skills/foo: conflicts" in line for line in report.fix_errors)


def test_fix_mixed_legacy_repo_skills_in_one_pass(git_repo):
    # One pass over `.pi/skills/` with a move (absent target), an identical-drop, and a conflict:
    # the loop processes all three, and the legacy root is RETAINED because the conflict remains.
    _scaffold(git_repo)
    legacy_root = git_repo / ".pi" / "skills"
    target_root = git_repo / ".perk" / "skills"
    # `mover` → target absent → moved.
    (legacy_root / "mover").mkdir(parents=True)
    (legacy_root / "mover" / "SKILL.md").write_text("---\nname: mover\n---\n", encoding="utf-8")
    # `dup` → byte-identical target → legacy dropped.
    dup_body = "---\nname: dup\n---\nbody\n"
    (legacy_root / "dup").mkdir(parents=True)
    (legacy_root / "dup" / "SKILL.md").write_text(dup_body, encoding="utf-8")
    (target_root / "dup").mkdir(parents=True)
    (target_root / "dup" / "SKILL.md").write_text(dup_body, encoding="utf-8")
    # `clash` → differing target → conflict, left in place.
    (legacy_root / "clash").mkdir(parents=True)
    (legacy_root / "clash" / "SKILL.md").write_text(
        "---\nname: clash\n---\nold\n", encoding="utf-8"
    )
    (target_root / "clash").mkdir(parents=True)
    (target_root / "clash" / "SKILL.md").write_text(
        "---\nname: clash\n---\nnew\n", encoding="utf-8"
    )

    report = run_doctor(git_repo, fix=True, verify=False)
    assert (target_root / "mover" / "SKILL.md").is_file()  # moved
    assert not (legacy_root / "mover").exists()
    assert not (legacy_root / "dup").exists()  # dropped
    assert (legacy_root / "clash").exists()  # conflict retained
    assert any(".pi/skills/mover: moved to .perk/skills/mover" in line for line in report.fixed)
    assert any(".pi/skills/dup: removed legacy" in line for line in report.fixed)
    assert any(".pi/skills/clash: conflicts" in line for line in report.fix_errors)
    # Legacy root is NOT removed while the conflicting skill still lives under it.
    assert legacy_root.is_dir()


def test_fix_reports_conflict_on_deep_nested_difference(git_repo):
    # `_dirs_identical` must descend: a multi-file skill where a DEEP nested file differs is a
    # conflict (not a redundant drop), even though shallower files match.
    _scaffold(git_repo)
    legacy = git_repo / ".pi" / "skills" / "foo"
    target = git_repo / ".perk" / "skills" / "foo"
    for root in (legacy, target):
        (root / "nested").mkdir(parents=True)
        (root / "SKILL.md").write_text("---\nname: foo\n---\nbody\n", encoding="utf-8")
        (root / "references.md").write_text("shared\n", encoding="utf-8")
    # Only the deep nested file diverges.
    (legacy / "nested" / "detail.md").write_text("legacy detail\n", encoding="utf-8")
    (target / "nested" / "detail.md").write_text("new detail\n", encoding="utf-8")

    report = run_doctor(git_repo, fix=True, verify=False)
    assert legacy.exists()  # NOT dropped — the deep difference is a conflict
    assert any(
        ".pi/skills/foo: conflicts with .perk/skills/foo" in line for line in report.fix_errors
    )


# --- the legacy config migration (`.pi/perk.toml` -> `.perk/`) --------------------------------


def _seed_legacy(repo, *, committed=None, local=None):
    pi = repo / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    if committed is not None:
        (pi / "perk.toml").write_text(committed, encoding="utf-8")
    if local is not None:
        (pi / "perk.local.toml").write_text(local, encoding="utf-8")


def test_config_check_diagnoses_legacy_not_migrated(git_repo):
    # A present legacy `.pi/perk.toml` with no `.perk/config.toml` is diagnosed distinctly from a
    # genuinely-missing config ("legacy config not migrated", not "config missing").
    _seed_legacy(git_repo, committed='[worktree]\nroot = "wt"\n')
    report = run_doctor(git_repo, verify=False)
    config = next(c for c in report.checks if c.name == "config")
    assert config.status == "fail"
    assert config.message == "legacy config not migrated"
    assert config.detail == ".pi/perk.toml"
    assert config.remediation == "perk doctor --fix"


def test_fix_config_absent_seeds_template_without_migration(git_repo):
    # No legacy, no target → `--fix` seeds the template (the normal scaffold), no migration line.
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".perk" / "config.toml").is_file()
    assert (git_repo / ".perk" / "local.toml").is_file()
    assert not any("migrated to" in line for line in fixed.fixed)


def test_fix_migrates_legacy_only_config_secret_safely(git_repo):
    # legacy-only: `--fix` moves `.pi/perk.toml` -> `.perk/config.toml` (and local likewise),
    # secret-safely; a re-run is idempotent.
    secret = "lin_secret_do_not_print"
    _seed_legacy(
        git_repo,
        committed='[worktree]\nroot = "wt"\n',
        local=f'[linear]\napi_key = "{secret}"\n',
    )
    fixed = run_doctor(git_repo, fix=True, verify=False)

    assert (git_repo / ".perk" / "config.toml").read_text(encoding="utf-8") == (
        '[worktree]\nroot = "wt"\n'
    )
    assert (git_repo / ".perk" / "local.toml").read_text(encoding="utf-8") == (
        f'[linear]\napi_key = "{secret}"\n'
    )
    assert not (git_repo / ".pi" / "perk.toml").exists()
    assert not (git_repo / ".pi" / "perk.local.toml").exists()
    assert any(".pi/perk.toml: migrated to .perk/config.toml" in line for line in fixed.fixed)
    # Secret-safety: the value never appears in any rendered fix line / error.
    assert all(secret not in line for line in (*fixed.fixed, *fixed.fix_errors))
    # The local secret is NEVER promoted into the committed file.
    assert "[linear]" not in (git_repo / ".perk" / "config.toml").read_text(encoding="utf-8")
    # The migrated secret is readable from `.perk/local.toml`.
    from perk.substrate.config import load_local_linear_api_key

    assert load_local_linear_api_key(git_repo) == secret
    # The managed gitignore now ignores the local file.
    assert "/.perk/local.toml" in (git_repo / ".gitignore").read_text(encoding="utf-8")
    # Idempotent: a second `--fix` re-migrates nothing.
    again = run_doctor(git_repo, fix=True, verify=False)
    assert not any("migrated to" in line for line in again.fixed)


def test_fix_removes_identical_legacy_config(git_repo):
    # both byte-identical: `--fix` removes the redundant legacy file; idempotent.
    body = '[worktree]\nroot = "wt"\n'
    _seed_legacy(git_repo, committed=body)
    cfg = git_repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(body, encoding="utf-8")
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert not (git_repo / ".pi" / "perk.toml").exists()
    assert (git_repo / ".perk" / "config.toml").read_text(encoding="utf-8") == body
    assert any("removed (identical to .perk/config.toml)" in line for line in fixed.fixed)
    again = run_doctor(git_repo, fix=True, verify=False)
    assert not any("removed (identical" in line for line in again.fixed)


def test_fix_reports_conflict_when_legacy_and_target_differ(git_repo):
    # both present and differing: `--fix` reports a `fix_errors` entry (paths only), leaves both
    # files, and repeats the error every run until resolved by hand.
    _seed_legacy(git_repo, committed='[worktree]\nroot = "legacy"\n')
    cfg = git_repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text('[worktree]\nroot = "new"\n', encoding="utf-8")
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".pi" / "perk.toml").exists()  # left untouched
    assert any(
        ".pi/perk.toml and .perk/config.toml differ — resolve by hand" in e
        for e in fixed.fix_errors
    )
    again = run_doctor(git_repo, fix=True, verify=False)
    assert any("differ — resolve by hand" in e for e in again.fix_errors)


def test_cache_gc_ok_when_no_prunable_state(git_repo):
    # A converged repo with no run state → `cache-gc` is `ok` (group `state`, no remediation).
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "cache-gc")
    assert check.status == "ok" and check.group == "state"
    assert report.exit_code == 0


def test_cache_gc_warns_on_prunable_state(git_repo):
    # A backdated warm run dir is prunable → `cache-gc` warns with the `perk state prune`
    # remediation; a warn never fails doctor (exit stays 0).
    from datetime import UTC, datetime, timedelta

    from ulid import ULID

    from perk.state import cache

    _scaffold(git_repo)
    rid = str(ULID.from_datetime(datetime.now(UTC) - timedelta(days=20)))
    cache.write_scratch(git_repo, rid, "x", "y")
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "cache-gc")
    assert check.status == "warn"
    assert check.remediation == "perk state prune"
    assert report.exit_code == 0


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
    shutil.rmtree(git_repo / ".perk" / "workflow" / "handoff")
    report = run_doctor(git_repo, verify=False)
    assert "workflow-dir" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".perk" / "workflow" / "handoff").is_dir() and fixed.healthy


def test_config_user_edit_is_not_drift(git_repo):
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        "[worktree]\nroot = 'custom-wt'\n", encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    config = next(c for c in report.checks if c.name == "config")
    assert config.status == "ok"  # user-editable config is never flagged as drift


def test_missing_config_is_reseeded(git_repo):
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").unlink()
    report = run_doctor(git_repo, verify=False)
    assert "config" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".perk" / "config.toml").is_file() and fixed.healthy


def test_no_silent_pass_on_unverifiable_check(git_repo):
    _scaffold(git_repo)
    (git_repo / ".pi" / "settings.json").write_text("{not json", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    settings = next(c for c in report.checks if c.name == "settings-wiring")
    assert settings.status == "fail"  # un-evaluable -> fail, never a silent ok


def test_compaction_drift_detected_and_fixed(git_repo):
    # `[compaction]` converges inside `settings-wiring`, so doctor dry-runs/fixes it for
    # free. Select a compaction policy that diverges from settings.json → drift → `--fix` repairs.
    _scaffold(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
        "[compaction]\nenabled = false\nreserve_tokens = 8192\n", encoding="utf-8"
    )
    report = run_doctor(git_repo, verify=False)
    assert "settings-wiring" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy
    import json

    compaction = json.loads((git_repo / ".pi" / "settings.json").read_text())["compaction"]
    assert compaction == {"enabled": False, "reserveTokens": 8192}
    again = run_doctor(git_repo, verify=False)  # converged → no drift
    assert next(c for c in again.checks if c.name == "settings-wiring").status == "ok"


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


def test_fix_verify_stays_healthy_with_stubbed_sync(git_repo, stub_env, converge_skills_workspace):
    # `stub_env` no-ops `init.sync_skills`; `run_doctor(fix=True, verify=True)` must not crash
    # and stays healthy on a freshly converged repo (with a delivered skills substrate).
    _scaffold(git_repo)
    converge_skills_workspace(git_repo)
    report = run_doctor(git_repo, fix=True, verify=True)
    assert report.healthy and report.exit_code == 0


def test_fix_invokes_sync_under_verify(git_repo, monkeypatch, stub_env):
    # `stub_env` keeps env/github offline; re-patch the sync seam (overriding the fixture's
    # no-op) to observe that `--fix` materializes skills under `verify`.
    _scaffold(git_repo)
    called = []
    monkeypatch.setattr(init, "sync_skills", lambda root, changes, **kw: called.append(root))
    run_doctor(git_repo, fix=True, verify=True)
    assert called == [git_repo]


def test_plain_doctor_does_not_sync(git_repo, monkeypatch, stub_env):
    _scaffold(git_repo)
    called = []
    monkeypatch.setattr(init, "sync_skills", lambda root, changes, **kw: called.append(root))
    run_doctor(git_repo, fix=False, verify=True)
    assert called == []


# --- skills-delivery check (load-bearing delivery substrate) -------------------------


def _delivery_check(report):
    return next(c for c in report.checks if c.name == "skills-delivery")


def test_skills_delivery_ok_on_healthy_substrate(git_repo, converge_skills_workspace, stub_env):
    _scaffold(git_repo)
    converge_skills_workspace(git_repo)
    check = _delivery_check(run_doctor(git_repo, verify=True))
    assert check.status == "ok" and check.group == "skills"


def test_skills_delivery_fails_on_tracked_conflict(git_repo, converge_skills_workspace, stub_env):
    _scaffold(git_repo)
    converge_skills_workspace(git_repo)
    skill = git_repo / ".claude" / "skills" / "x" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".claude"], cwd=git_repo, check=True, capture_output=True)
    report = run_doctor(git_repo, verify=True)
    check = _delivery_check(report)
    assert check.status == "fail" and ".claude/skills/x/SKILL.md" in check.detail
    assert "Migrate" in check.remediation
    assert report.exit_code == 1


def test_skills_delivery_giterror_degrades_to_warn(git_repo, monkeypatch, stub_env):
    def boom(root):
        raise git.GitError("probe failed")

    monkeypatch.setattr(init, "skills_conflict_paths", boom)
    check = _skills_delivery_check(git_repo, False)
    assert check.status == "warn" and "not evaluated" in check.detail  # no silent pass


def test_skills_delivery_fails_without_workspace_manifest(git_repo, stub_env):
    # (b): the perk fragment exists but .agents/manifest.yaml does not -> skills init never ran.
    _scaffold(git_repo)  # writes .agents/manifest.d/perk.yaml
    check = _delivery_check(run_doctor(git_repo, verify=True))
    assert check.status == "fail" and "not initialized" in check.message


def test_skills_delivery_fails_on_missing_skills(git_repo, converge_skills_workspace, stub_env):
    _scaffold(git_repo)
    converge_skills_workspace(git_repo)
    shutil.rmtree(git_repo / ".agents" / "skills" / "perk-plan")
    check = _delivery_check(run_doctor(git_repo, verify=True))
    assert check.status == "fail" and "perk-plan" in check.detail
    assert check.remediation == "Run 'perk doctor --fix'."


def test_skills_delivery_fails_on_missing_external_skill(
    git_repo, converge_skills_workspace, stub_env
):
    # The promoted external skills are enforced just like perk-authored ones: removing one
    # makes verified-mode skills-delivery fail and names it.
    _scaffold(git_repo)
    converge_skills_workspace(git_repo)
    external = init.REQUIRED_EXTERNAL_SKILLS[0][1]  # e.g. "ruff"
    shutil.rmtree(git_repo / ".agents" / "skills" / external)
    check = _delivery_check(run_doctor(git_repo, verify=True))
    assert check.status == "fail" and external in check.detail


def test_skills_delivery_absent_without_verify(git_repo):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    assert "skills-delivery" not in {c.name for c in report.checks}


# --- repo-authored-skills check ------------------------------------------------------


def _repo_check(report):
    return next(c for c in report.checks if c.name == "repo-skills")


def _stub_repo_identity(monkeypatch):
    monkeypatch.setattr(
        github,
        "repo_identity",
        lambda root: github.RepoIdentity("acme", "https://github.com/x/acme", "main"),
    )


def _plant_repo_skill(root, dir_name, *, fm=None):
    skill = root / ".perk" / "skills" / dir_name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(fm or f"---\nname: {dir_name}\ndescription: A skill.\n---\n# body\n", "utf-8")
    return skill


def test_repo_skills_ok_no_skills(git_repo, stub_env):
    check = _repo_skills_check(git_repo)
    assert check.status == "ok" and check.group == "skills"
    assert check.message == "no repo-authored skills"


def test_repo_skills_ok_when_declared_and_converged(git_repo, monkeypatch, stub_env):
    _plant_repo_skill(git_repo, "alpha")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=git_repo, check=True, capture_output=True)
    _stub_repo_identity(monkeypatch)
    init.converge_repo_skills_manifest(git_repo, apply=True)  # fragment on disk
    check = _repo_skills_check(git_repo)
    assert check.status == "ok" and "1 repo-authored skill" in check.message


def test_repo_skills_warn_untracked(git_repo, monkeypatch, stub_env):
    _plant_repo_skill(git_repo, "alpha")  # NOT committed
    _stub_repo_identity(monkeypatch)
    init.converge_repo_skills_manifest(git_repo, apply=True)  # fragment rendered despite warning
    check = _repo_skills_check(git_repo)
    assert check.status == "warn" and "not committed" in check.message


def test_repo_skills_fail_invalid(git_repo, monkeypatch, stub_env):
    _plant_repo_skill(git_repo, "alpha", fm="no frontmatter here\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=git_repo, check=True, capture_output=True)
    _stub_repo_identity(monkeypatch)
    check = _repo_skills_check(git_repo)
    assert check.status == "fail" and "invalid" in check.message


def test_repo_skills_fail_no_github_remote(git_repo, monkeypatch, stub_env):
    _plant_repo_skill(git_repo, "alpha")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=git_repo, check=True, capture_output=True)

    def boom(root):
        raise github.GitHubError("no remote")

    monkeypatch.setattr(github, "repo_identity", boom)
    check = _repo_skills_check(git_repo)
    assert check.status == "fail" and "invalid" in check.message


def test_repo_skills_fail_on_drift(git_repo, monkeypatch, stub_env):
    # Valid skills but no fragment on disk → the convergence reports a "created" delta → drift.
    _plant_repo_skill(git_repo, "alpha")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=git_repo, check=True, capture_output=True)
    _stub_repo_identity(monkeypatch)
    check = _repo_skills_check(git_repo)
    assert check.status == "fail" and check.message == "repo-skills-manifest drift"


def test_repo_skills_absent_without_verify(git_repo):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    assert "repo-skills" not in {c.name for c in report.checks}


def test_fix_converges_repo_skills_drift(
    git_repo, monkeypatch, stub_env, converge_skills_workspace
):
    # A valid repo skill with no fragment on disk is drift; --fix writes it and the post-fix
    # re-verify shows the repo-skills check ok.
    _scaffold(git_repo)
    converge_skills_workspace(git_repo)
    _plant_repo_skill(git_repo, "alpha")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=git_repo, check=True, capture_output=True)
    _stub_repo_identity(monkeypatch)
    report = run_doctor(git_repo, fix=True, verify=True)
    assert any("perk-repo-skills.yaml: created" in f for f in report.fixed)
    assert _repo_check(report).status == "ok"


def test_fix_repo_skills_errors_land_on_fix_errors(git_repo, monkeypatch, stub_env):
    # A malformed SKILL.md is loud on fix_errors; the post-fix repo-skills check stays fail.
    _scaffold(git_repo)
    _plant_repo_skill(git_repo, "alpha", fm="no frontmatter here\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=git_repo, check=True, capture_output=True)
    _stub_repo_identity(monkeypatch)
    report = run_doctor(git_repo, fix=True, verify=True)
    assert any("alpha" in e for e in report.fix_errors)
    assert _repo_check(report).status == "fail"


def test_fix_sync_failure_carried_on_fix_errors(git_repo, monkeypatch, stub_env):
    _scaffold(git_repo)
    (git_repo / ".gitignore").write_text("x\n", encoding="utf-8")  # drift to trigger fixes
    monkeypatch.setattr(init, "sync_skills", lambda root, changes, **kw: "sync exploded")
    report = run_doctor(git_repo, fix=True, verify=True)
    assert report.fix_errors == ["sync exploded"]
    # The post-fix re-verify shows the still-broken skills-delivery check (exit reflects it).
    assert _delivery_check(report).status == "fail"
    assert report.exit_code == 1
    assert report_to_dict(report)["fix_errors"] == ["sync exploded"]


def test_report_to_dict_carries_empty_fix_errors():
    data = report_to_dict(DoctorReport(checks=[], fixed=[], self_repo=False))
    assert data["fix_errors"] == []


def test_render_fix_errors(capsys):
    report = DoctorReport(
        checks=[_check("x", "state", "ok")],
        fixed=["a thing"],
        self_repo=False,
        fix_errors=["skills delivery failed: boom"],
    )
    render.render_report(report, verbose=False)
    err = capsys.readouterr().err
    assert "Fix failures" in err and "skills delivery failed: boom" in err


# --- bindings check --------------------------------------------------------------


def _install_default_skills(root, subdir=".agents/skills"):
    """Plant a SKILL.md for each of the 8 shipped default binding skills under ``subdir``."""
    from perk.substrate.bindings import load_bindings

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
    (git_repo / ".perk" / "config.toml").write_text(
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
    (git_repo / ".perk" / "config.toml").write_text(
        '[[bindings]]\ntrigger = "stage:nope"\nskill = "perk-plan"\nmode = "nudge"\n',
        encoding="utf-8",
    )
    check = _bindings_check(run_doctor(git_repo, verify=False))
    assert check.status == "warn" and "nope" in check.detail


def test_bindings_check_warns_on_command_without_delivery_surface(git_repo):
    _scaffold(git_repo)
    _install_default_skills(git_repo)
    (git_repo / ".perk" / "config.toml").write_text(
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


# --- runner-prerequisite checks (§8.16) -------------------------------------------


def _runner_env(monkeypatch, *, authed=True, enabled=None, pat=True, models=None, perms=True):
    """Stub the gh-shelling seams `_runner_checks` calls so no real gh runs."""
    monkeypatch.setattr(
        github,
        "check_auth",
        lambda: github.AuthStatus(
            authed, "octocat" if authed else None, (), None if authed else "no"
        ),
    )
    monkeypatch.setattr(github, "get_repo_variable", lambda *, name, repo_root: enabled)
    model_map = (
        models if models is not None else {"ANTHROPIC_API_KEY": True, "OPENAI_API_KEY": False}
    )

    def fake_secret(*, name, repo_root):
        if name == "PERK_GH_PAT":
            return pat
        return model_map.get(name)

    monkeypatch.setattr(github, "secret_exists", fake_secret)
    monkeypatch.setattr(
        github,
        "get_workflow_permissions",
        lambda *, repo_root: (
            None if perms is None else github.WorkflowPermissions("write", bool(perms))
        ),
    )


def test_runner_unauthed_single_info(monkeypatch, tmp_path):
    _runner_env(monkeypatch, authed=False)
    checks = _runner_checks(tmp_path, False)
    assert [c.name for c in checks] == ["runner-prereqs"]
    assert checks[0].status == "info"


def test_runner_disabled_skips_probes(monkeypatch, tmp_path):
    _runner_env(monkeypatch, enabled="false")
    checks = _runner_checks(tmp_path, False)
    assert [c.name for c in checks] == ["runner-enabled"]
    assert "disabled" in checks[0].message


def test_runner_all_present_ok(monkeypatch, tmp_path):
    _runner_env(monkeypatch, pat=True, models={"ANTHROPIC_API_KEY": True, "OPENAI_API_KEY": False})
    by = {c.name: c for c in _runner_checks(tmp_path, False)}
    assert by["runner-pat-secret"].status == "ok"
    assert by["runner-model-secret"].status == "ok"
    assert "ANTHROPIC_API_KEY" in by["runner-model-secret"].message
    # report stays healthy / exit 0 (only ok+info)
    report = DoctorReport(checks=list(by.values()), fixed=[], self_repo=False)
    assert report.healthy and report.exit_code == 0


def test_runner_pat_absent_warn_stays_healthy(monkeypatch, tmp_path):
    _runner_env(monkeypatch, pat=False)
    by = {c.name: c for c in _runner_checks(tmp_path, False)}
    assert by["runner-pat-secret"].status == "warn"
    assert by["runner-pat-secret"].remediation == "gh secret set PERK_GH_PAT"
    report = DoctorReport(checks=list(by.values()), fixed=[], self_repo=False)
    assert report.healthy and report.exit_code == 0  # non-fatal


def test_runner_pat_unverifiable_info(monkeypatch, tmp_path):
    _runner_env(monkeypatch, pat=None)
    by = {c.name: c for c in _runner_checks(tmp_path, False)}
    assert by["runner-pat-secret"].status == "info"


def test_runner_model_only_openai_ok(monkeypatch, tmp_path):
    _runner_env(monkeypatch, models={"ANTHROPIC_API_KEY": False, "OPENAI_API_KEY": True})
    by = {c.name: c for c in _runner_checks(tmp_path, False)}
    assert by["runner-model-secret"].status == "ok"
    assert "OPENAI_API_KEY" in by["runner-model-secret"].message


def test_runner_model_both_absent_warn(monkeypatch, tmp_path):
    _runner_env(monkeypatch, models={"ANTHROPIC_API_KEY": False, "OPENAI_API_KEY": False})
    by = {c.name: c for c in _runner_checks(tmp_path, False)}
    assert by["runner-model-secret"].status == "warn"


def test_runner_workflow_permissions_advisory_info(monkeypatch, tmp_path):
    _runner_env(monkeypatch, perms=False)
    by = {c.name: c for c in _runner_checks(tmp_path, False)}
    perm = by["runner-workflow-permissions"]
    assert perm.status == "info" and "cannot create PRs" in perm.message and perm.remediation


def test_runner_self_vs_consumer_detail(monkeypatch, tmp_path):
    _runner_env(monkeypatch, pat=False)
    consumer = {c.name: c for c in _runner_checks(tmp_path, False)}["runner-pat-secret"]
    self_ = {c.name: c for c in _runner_checks(tmp_path, True)}["runner-pat-secret"]
    assert "required only if" in consumer.detail
    assert "dogfoods" in self_.detail


def test_runner_githuberror_degrades(monkeypatch, tmp_path, converge_skills_workspace):
    def boom():
        raise github.GitHubError("gh not found on PATH")

    monkeypatch.setattr(github, "check_auth", boom)
    # The _build_checks wrapper degrades to a single info (driven via run_doctor under verify).
    from perk.convergence import doctor

    monkeypatch.setattr(doctor, "_env_checks", lambda: [])
    monkeypatch.setattr(doctor, "_github_checks", lambda root: [])
    monkeypatch.setattr(init, "sync_skills", lambda root, changes, **kw: None)
    # The verify-gated @mgiles/perk install check fails on an absent install; stub it benign so this
    # test stays about runner-prereqs degradation (not install ownership).
    monkeypatch.setattr(
        init, "extension_install_status", lambda root, *, self_repo: ("present", "x")
    )
    _scaffold(tmp_path_repo := _git_repo_at(tmp_path))
    converge_skills_workspace(tmp_path_repo)
    report = run_doctor(tmp_path_repo, verify=True)
    runner = [c for c in report.checks if c.group == "runner"]
    assert len(runner) == 1 and runner[0].name == "runner-prereqs" and runner[0].status == "info"
    assert report.healthy


def _git_repo_at(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()

    def g(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "perk tests")
    (repo / "f.txt").write_text("hi\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "init")
    return repo


def test_runner_group_renders_in_human_output(capsys):
    checks = [
        _check("git", "environment", "ok"),
        _check("runner-enabled", "runner", "info"),
        _check("runner-pat-secret", "runner", "warn", remediation="gh secret set PERK_GH_PAT"),
    ]
    render.render_report(DoctorReport(checks=checks, fixed=[], self_repo=False), verbose=False)
    err = capsys.readouterr().err
    assert "runner (" in err  # the runner group is visible (D7 — added to _GROUP_ORDER)
    assert "gh secret set PERK_GH_PAT" in err


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


# --- workflow_checks (§8.19 static layer) -----------------------------------------


def test_workflow_checks_verify_false_only_managed(git_repo):
    from perk.convergence import doctor

    _scaffold(git_repo)
    checks = doctor.workflow_checks(git_repo, False, verify=False)
    assert [c.name for c in checks] == ["runner-workflow"]
    assert checks[0].status == "ok" and checks[0].group == "repository"


def test_workflow_checks_managed_fail_on_deleted_workflow(git_repo):
    from perk.convergence import doctor
    from perk.run import workflow_artifacts

    _scaffold(git_repo)
    (git_repo / workflow_artifacts.RUNNER_WORKFLOW_PATH).unlink()
    check = doctor.workflow_checks(git_repo, False, verify=False)[0]
    assert check.name == "runner-workflow" and check.status == "fail"
    assert check.remediation == "perk doctor --fix"


def test_workflow_checks_composes_github_and_runner_under_verify(monkeypatch, git_repo):
    from perk.convergence import doctor

    _scaffold(git_repo)
    _runner_env(monkeypatch, authed=True)
    monkeypatch.setattr(
        github,
        "check_repo_access",
        lambda root: github.RepoAccess(ok=True, repo="octocat/repo", can_push=True, error=None),
    )
    checks = doctor.workflow_checks(git_repo, False, verify=True)
    groups = {c.group for c in checks}
    assert {"github", "runner", "repository"} <= groups
    assert any(c.name == "runner-workflow" for c in checks)


def test_workflow_checks_githuberror_degrades_to_info(monkeypatch, git_repo):
    from perk.convergence import doctor

    _scaffold(git_repo)
    monkeypatch.setattr(doctor, "_github_checks", lambda root: [])

    def boom(root, self_repo):
        raise github.GitHubError("gh not found")

    monkeypatch.setattr(doctor, "_runner_checks", boom)
    checks = doctor.workflow_checks(git_repo, False, verify=True)
    runner_checks = [c for c in checks if c.name == "runner-prereqs"]
    assert len(runner_checks) == 1 and runner_checks[0].status == "info"


# --- init perk-package ref reconcile -------------------------------------------------


def test_ref_drift_detected_and_fixed(git_repo):
    # A stale pinned perk npm version surfaces as a settings-wiring fail; --fix reconciles to
    # the version this perk wants (`@{__version__}`).
    import json as _json

    pin = f"npm:@mgiles/perk@{__version__}"
    _scaffold(git_repo)
    settings_path = git_repo / ".pi" / "settings.json"
    settings = _json.loads(settings_path.read_text())
    settings["packages"] = [
        "npm:@mgiles/perk@0.0.0" if isinstance(p, str) and p.startswith("npm:@mgiles/perk") else p
        for p in settings["packages"]
    ]
    settings_path.write_text(_json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    assert "settings-wiring" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy
    packages = _json.loads(settings_path.read_text())["packages"]
    assert pin in packages
    assert "npm:@mgiles/perk@0.0.0" not in packages


# --- the verify-gated `extension-install` check ---------------------------------------


def _install_check(report):
    return next((c for c in report.checks if c.name == "extension-install"), None)


@pytest.mark.parametrize(
    ("status", "detail", "expect_status", "expect_remediation"),
    [
        ("absent", "perk installs the pinned @mgiles/perk pre-launch", "fail", "perk doctor --fix"),
        ("mismatch", "installed @mgiles/perk 0.0.0 != pinned 1.0.0", "fail", "perk doctor --fix"),
        ("present", "1.0.0", "ok", ""),
        ("self", "self-repo uses the local '..' package — no npm install", "info", ""),
        ("unverifiable", "installed @mgiles/perk package.json version unreadable", "warn", ""),
    ],
)
def test_extension_install_check_statuses(
    git_repo, stub_env, monkeypatch, status, detail, expect_status, expect_remediation
):
    _scaffold(git_repo)
    monkeypatch.setattr(
        doctor_mod.init, "extension_install_status", lambda root, *, self_repo: (status, detail)
    )
    report = run_doctor(git_repo, verify=True)
    check = _install_check(report)
    assert check is not None
    assert check.group == "package"
    assert check.status == expect_status
    assert check.remediation == expect_remediation


def test_extension_install_check_absent_without_verify(git_repo):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    assert _install_check(report) is None


@pytest.mark.parametrize("status", ["absent", "mismatch"])
def test_fix_materializes_perk_extension_install(git_repo, stub_env, monkeypatch, status):
    _scaffold(git_repo)
    monkeypatch.setattr(
        doctor_mod.init,
        "extension_install_status",
        lambda root, *, self_repo: (status, "drift"),
    )
    calls: list = []

    def _spy(root, *, self_repo):
        calls.append((root, self_repo))
        return ".pi/npm/node_modules/@mgiles/perk: installed @mgiles/perk@x (perk-owned)"

    monkeypatch.setattr(doctor_mod.init, "materialize_extension_install", _spy)
    report = run_doctor(git_repo, fix=True, verify=True)
    assert len(calls) == 1
    assert any("@mgiles/perk" in line for line in report.fixed)


# --- artifact-health (the report-only state-group classification) ---------------------------


def _health_check(report):
    return next(c for c in report.checks if c.name == "artifact-health")


def _health_row(report, key):
    return next(r for r in report.artifact_health if r.key == key)


def _edit_agents_block_inner(repo):
    """Edit text INSIDE the AGENTS.md managed block (markers intact) — observed drift."""
    agents_md = repo / "AGENTS.md"
    text = agents_md.read_text(encoding="utf-8")
    assert "perk conventions" in text
    agents_md.write_text(text.replace("perk conventions", "edited conventions"), encoding="utf-8")


def test_artifact_health_ok_on_converged_repo(git_repo):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    check = _health_check(report)
    assert check.group == "state" and check.status == "ok"
    assert check.message == "8 managed artifacts up-to-date"
    assert len(report.artifact_health) == 8
    assert all(r.status == "up-to-date" for r in report.artifact_health)


def test_artifact_health_info_when_state_not_recorded(git_repo):
    _scaffold(git_repo)
    paths.managed_state_file(git_repo).unlink()
    report = run_doctor(git_repo, verify=False)
    check = _health_check(report)
    assert check.status == "info"
    assert check.message == "8 managed artifacts up-to-date; state not yet recorded"
    assert ".perk/managed-state.toml" in check.detail


def test_artifact_health_state_missing_row(git_repo):
    _scaffold(git_repo)
    paths.managed_state_file(git_repo).unlink()
    _edit_agents_block_inner(git_repo)
    report = run_doctor(git_repo, verify=False)
    check = _health_check(report)
    assert check.status == "warn" and check.remediation == "perk doctor --fix"
    assert "1 state-missing" in check.message and "7 up-to-date" in check.message
    assert "AGENTS.md (agents-block): state-missing" in check.detail
    assert _health_row(report, "agents-block").status == "state-missing"


def test_artifact_health_locally_modified(git_repo):
    _scaffold(git_repo)
    _edit_agents_block_inner(git_repo)
    report = run_doctor(git_repo, verify=False)
    check = _health_check(report)
    assert check.status == "warn"
    assert "1 locally-modified" in check.message
    row = _health_row(report, "agents-block")
    assert row.status == "locally-modified"
    assert row.recorded_hash == row.desired_hash != row.observed_hash


def test_artifact_health_changed_upstream(git_repo):
    # Deterministic construction: edit the artifact, then rewrite its recorded row's hash to the
    # OBSERVED hash (simulating "perk wrote this content, then desired moved").
    import dataclasses

    from perk.convergence.managed_state import (
        ManagedState,
        load_managed_state,
        managed_artifacts,
        save_managed_state,
    )

    _scaffold(git_repo)
    _edit_agents_block_inner(git_repo)
    descriptor = next(d for d in managed_artifacts() if d.key == "agents-block")
    observed = descriptor.observed_hash(git_repo)
    assert observed is not None
    state = load_managed_state(git_repo)
    assert state is not None
    artifacts = tuple(
        dataclasses.replace(a, hash=observed) if a.key == "agents-block" else a
        for a in state.artifacts
    )
    save_managed_state(git_repo, ManagedState(version=state.version, artifacts=artifacts))
    report = run_doctor(git_repo, verify=False)
    check = _health_check(report)
    assert check.status == "warn" and "1 changed-upstream" in check.message
    row = _health_row(report, "agents-block")
    assert row.status == "changed-upstream"
    assert row.observed_hash == row.recorded_hash != row.desired_hash


def test_artifact_health_not_installed(git_repo):
    _scaffold(git_repo)
    # Strip the managed markers from .gitignore + delete the runner workflow entirely.
    (git_repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    (git_repo / ".github" / "workflows" / "perk-run.yml").unlink()
    report = run_doctor(git_repo, verify=False)
    check = _health_check(report)
    assert check.status == "warn" and "2 not-installed" in check.message
    assert _health_row(report, "gitignore-block").status == "not-installed"
    assert _health_row(report, "runner-workflow").status == "not-installed"


def test_artifact_health_malformed_state_warns_then_fix_rewrites(git_repo):
    _scaffold(git_repo)
    paths.managed_state_file(git_repo).write_text("not = [valid", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    check = _health_check(report)
    assert check.status == "warn"
    assert check.message == ".perk/managed-state.toml malformed"
    assert check.detail  # the ManagedStateError reason, never a silent pass
    assert check.remediation == "perk doctor --fix"
    # Rows are still classified (recorded=None) — the converged repo reads up-to-date.
    assert all(r.status == "up-to-date" for r in report.artifact_health)

    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert ".perk/managed-state.toml: updated" in fixed.fixed
    assert _health_check(fixed).status == "ok"


def test_fix_backfills_state_file_and_is_idempotent(git_repo):
    _scaffold(git_repo)
    paths.managed_state_file(git_repo).unlink()
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert ".perk/managed-state.toml: recorded" in fixed.fixed
    assert _health_check(fixed).status == "ok"
    again = run_doctor(git_repo, fix=True, verify=False)
    assert again.fixed == []  # the doctor-fix idempotency gate


def test_artifact_health_never_fails_and_serializes(git_repo):
    # The check is report-only in every scenario above; assert via the state-group statuses
    # (never via report.healthy — other groups own pass/fail) and pin the --json row shape.
    _scaffold(git_repo)
    _edit_agents_block_inner(git_repo)
    paths.managed_state_file(git_repo).unlink()
    report = run_doctor(git_repo, verify=False)
    state_checks = [c for c in report.checks if c.group == "state"]
    assert state_checks and all(c.status != "fail" for c in state_checks)
    payload = report_to_dict(report)
    rows = payload["artifact_health"]
    assert isinstance(rows, list) and len(rows) == 8
    statuses: dict[object, object] = {}
    for row in rows:
        assert isinstance(row, dict)
        # `.items()`-iteration reads known keys off the `dict[Unknown, Unknown]`-narrowed row
        # without a cast (`row["key"]` does not type-check under ty).
        fields = {str(k): v for k, v in row.items()}
        assert list(fields) == [
            "key",
            "path",
            "kind",
            "status",
            "recorded_version",
            "recorded_hash",
            "desired_hash",
            "observed_hash",
        ]
        statuses[fields["key"]] = fields["status"]
    assert statuses["agents-block"] == "state-missing"
    assert statuses["gitignore-block"] == "up-to-date"
