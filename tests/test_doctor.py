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

from perk import github
from perk.backends import linear
from perk.cli.commands.doctor import render
from perk.convergence import capabilities, init
from perk.convergence import doctor as doctor_mod
from perk.convergence.doctor import (
    Check,
    DoctorReport,
    _runner_checks,
    _skills_delivery_check,
    report_to_dict,
    run_doctor,
)
from perk.convergence.init import run_init
from perk.substrate import git


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
    (git_repo / ".pi" / "perk.toml").write_text('[providers]\nplan = "ghost"\n', encoding="utf-8")
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
    (git_repo / ".pi" / "perk.toml").write_text(
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
    (git_repo / ".pi" / "perk.toml").write_text('[issues]\nbackend = "linear"\n', encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
    assert check.status == "fail"
    assert "[issues] team is required" in check.message
    assert "[issues] team" in check.remediation
    assert report.exit_code == 1


def test_issues_check_fails_on_unknown_selection(git_repo):
    _scaffold(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text('[issues]\nbackend = "jira"\n', encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
    assert check.status == "fail"
    assert "unknown issue backend" in check.message


def test_issues_check_warns_on_malformed_committed_toml(git_repo):
    # Malformed TOML is the config check's finding; the issues check defers (mirrors providers).
    _scaffold(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text("[issues\nbackend =", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    check = next(c for c in report.checks if c.name == "issues-backend")
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
    (repo / ".pi" / "perk.toml").write_text(body, encoding="utf-8")


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
    # The key supplied via .pi/perk.local.toml [linear] api_key (env unset) is threaded through
    # to client_from_env(repo_root=...), so the auth check passes without an exported var.
    _scaffold(git_repo)
    _select_linear(git_repo)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    (git_repo / ".pi" / "perk.local.toml").write_text(
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


def test_untrack_failure_carried_on_fix_errors(git_repo, monkeypatch):
    # The migration's `git rm --cached` failure is reported on `fix_errors`, never swallowed.
    _scaffold(git_repo)
    monkeypatch.setattr(git, "is_tracked", lambda root, rel: True)

    def boom(root, rel):
        raise git.GitError("rm --cached exploded")

    monkeypatch.setattr(git, "rm_cached", boom)
    report = run_doctor(git_repo, fix=True, verify=False)
    assert report.fix_errors == [
        ".pi/workflow/plan.md: untrack failed (git rm --cached): rm --cached exploded"
    ]
    assert report_to_dict(report)["fix_errors"] == report.fix_errors


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


def test_compaction_drift_detected_and_fixed(git_repo):
    # `[compaction]` converges inside `settings-wiring`, so doctor dry-runs/fixes it for
    # free. Select a compaction policy that diverges from settings.json → drift → `--fix` repairs.
    _scaffold(git_repo)
    (git_repo / ".pi" / "perk.toml").write_text(
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
    # The verify-gated @perk/pi install check fails on an absent install; stub it benign so this
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

    from perk import __version__

    pin = f"npm:@perk/pi@{__version__}"
    _scaffold(git_repo)
    settings_path = git_repo / ".pi" / "settings.json"
    settings = _json.loads(settings_path.read_text())
    settings["packages"] = [
        "npm:@perk/pi@0.0.0" if isinstance(p, str) and p.startswith("npm:@perk/pi") else p
        for p in settings["packages"]
    ]
    settings_path.write_text(_json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    report = run_doctor(git_repo, verify=False)
    assert "settings-wiring" in {c.name for c in report.checks if c.status == "fail"}
    fixed = run_doctor(git_repo, fix=True, verify=False)
    assert fixed.healthy
    packages = _json.loads(settings_path.read_text())["packages"]
    assert pin in packages
    assert "npm:@perk/pi@0.0.0" not in packages


# --- the verify-gated `extension-clone` check -----------------------------------------


def _clone_check(report):
    return next((c for c in report.checks if c.name == "extension-clone"), None)


@pytest.mark.parametrize(
    ("status", "detail", "expect_status", "expect_remediation"),
    [
        ("stale", "clone HEAD aaaaaaaa != origin/main bbbbbbbb", "fail", "perk doctor --fix"),
        ("fresh", "abc123", "ok", ""),
        ("absent", "pi clones fresh at main on next launch", "info", ""),
        ("self", "self-repo uses the local '..' package — no git clone", "info", ""),
        ("unverifiable", "clone HEAD or origin/main tip unreadable — offline?", "warn", ""),
    ],
)
def test_extension_clone_check_statuses(
    git_repo, stub_env, monkeypatch, status, detail, expect_status, expect_remediation
):
    _scaffold(git_repo)
    monkeypatch.setattr(
        doctor_mod.init, "extension_clone_status", lambda root, *, self_repo: (status, detail)
    )
    report = run_doctor(git_repo, verify=True)
    check = _clone_check(report)
    assert check is not None
    assert check.group == "package"
    assert check.status == expect_status
    assert check.remediation == expect_remediation


def test_extension_clone_check_absent_without_verify(git_repo):
    _scaffold(git_repo)
    report = run_doctor(git_repo, verify=False)
    assert _clone_check(report) is None


def test_fix_materializes_stale_extension_clone(git_repo, stub_env, monkeypatch):
    _scaffold(git_repo)
    monkeypatch.setattr(
        doctor_mod.init,
        "extension_clone_status",
        lambda root, *, self_repo: ("stale", "clone HEAD aaaa != origin/main bbbb"),
    )
    calls: list = []

    def _spy(root, *, self_repo):
        calls.append((root, self_repo))
        return ".pi/git/github.com/mattgiles/perk: freshened to origin/main in place"

    # The fix gesture materializes in place (no shutil.rmtree blow-away).
    monkeypatch.setattr(doctor_mod.init, "materialize_extension_clone", _spy)
    report = run_doctor(git_repo, fix=True, verify=True)
    assert len(calls) == 1
    assert any("freshened to origin/main in place" in line for line in report.fixed)


# --- the verify-gated `extension-install` check ---------------------------------------


def _install_check(report):
    return next((c for c in report.checks if c.name == "extension-install"), None)


@pytest.mark.parametrize(
    ("status", "detail", "expect_status", "expect_remediation"),
    [
        ("absent", "perk installs the pinned @perk/pi pre-launch", "fail", "perk doctor --fix"),
        ("mismatch", "installed @perk/pi 0.0.0 != pinned 1.0.0", "fail", "perk doctor --fix"),
        ("present", "1.0.0", "ok", ""),
        ("self", "self-repo uses the local '..' package — no npm install", "info", ""),
        ("unverifiable", "installed @perk/pi package.json version unreadable", "warn", ""),
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
        return ".pi/npm/node_modules/@perk/pi: installed @perk/pi@x (perk-owned)"

    monkeypatch.setattr(doctor_mod.init, "materialize_extension_install", _spy)
    report = run_doctor(git_repo, fix=True, verify=True)
    assert len(calls) == 1
    assert any("@perk/pi" in line for line in report.fixed)
