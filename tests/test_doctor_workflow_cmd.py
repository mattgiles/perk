"""`perk doctor workflow` — the workflow-focused diagnostic subgroup (Node 3.3; §8.19)."""

import json
import subprocess

from click.testing import CliRunner

from perk import doctor, github, init, workflow_smoke
from perk.cli.cli import cli
from perk.doctor import Check


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _invoke_in_repo(args, *, git=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git:
            _git_init(d)
        return runner.invoke(cli, args)


def _ok_auth() -> github.AuthStatus:
    return github.AuthStatus(True, "octocat", (), None)


def _check(name, group, status, **kw) -> Check:
    kw.setdefault("message", f"{name} {status}")
    return Check(name=name, group=group, status=status, **kw)


# --- bare group -----------------------------------------------------------------------------


def test_bare_group_prints_help():
    result = CliRunner().invoke(cli, ["doctor", "workflow"])
    assert result.exit_code == 0
    assert "Static remote-runner prereq checks" in result.output
    assert "smoke-test" in result.output


# --- check ----------------------------------------------------------------------------------


def test_check_json_shape_and_exit(monkeypatch):
    monkeypatch.setattr(init, "is_self_repo", lambda root: False)
    monkeypatch.setattr(
        doctor,
        "workflow_checks",
        lambda root, self_repo, **kw: [_check("runner-workflow", "repository", "ok")],
    )
    result = _invoke_in_repo(["doctor", "workflow", "check", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True and payload["healthy"] is True
    assert payload["self_repo"] is False
    assert payload["summary"] == {"passed": 1, "warnings": 0, "failed": 0}
    assert payload["checks"][0]["name"] == "runner-workflow"


def test_check_exit_1_on_fail(monkeypatch):
    monkeypatch.setattr(init, "is_self_repo", lambda root: False)
    monkeypatch.setattr(
        doctor,
        "workflow_checks",
        lambda root, self_repo, **kw: [_check("runner-workflow", "repository", "fail")],
    )
    result = _invoke_in_repo(["doctor", "workflow", "check", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["healthy"] is False


def test_check_not_a_repo_exit_2():
    result = _invoke_in_repo(["doctor", "workflow", "check", "--json"], git=False)
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


# --- smoke-test -----------------------------------------------------------------------------


def _stub_checks(monkeypatch, *, auth_ok=True):
    status = "ok" if auth_ok else "warn"
    monkeypatch.setattr(init, "is_self_repo", lambda root: False)
    monkeypatch.setattr(
        doctor,
        "workflow_checks",
        lambda root, self_repo, **kw: [
            _check("github-auth", "github", status),
            _check("runner-workflow", "repository", "ok"),
        ],
    )
    monkeypatch.setattr(github, "check_auth", _ok_auth)


def test_smoke_refuses_when_github_auth_check_not_ok(monkeypatch):
    # require_github passes (auth ok) but the github-auth check is warn → gate refuses.
    monkeypatch.setattr(init, "is_self_repo", lambda root: False)
    monkeypatch.setattr(github, "check_auth", _ok_auth)
    monkeypatch.setattr(
        doctor,
        "workflow_checks",
        lambda root, self_repo, **kw: [_check("github-auth", "github", "warn")],
    )
    result = _invoke_in_repo(["doctor", "workflow", "smoke-test", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_unauthed"


def test_smoke_refuses_when_runner_disabled(monkeypatch):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(github, "get_repo_variable", lambda *, name, repo_root: "false")
    result = _invoke_in_repo(["doctor", "workflow", "smoke-test", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "runner_disabled"


def test_smoke_dispatch_no_wait_exit_0(monkeypatch):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(github, "get_repo_variable", lambda *, name, repo_root: None)
    monkeypatch.setattr(
        workflow_smoke,
        "dispatch_smoke",
        lambda root: workflow_smoke.SmokeDispatch(run_id="01J", run_ref="555", url="u/runs/555"),
    )
    result = _invoke_in_repo(["doctor", "workflow", "smoke-test", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["waited"] is False and payload["run_ref"] == "555"


def test_smoke_dispatch_error_exit_1(monkeypatch):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(github, "get_repo_variable", lambda *, name, repo_root: None)
    monkeypatch.setattr(
        workflow_smoke,
        "dispatch_smoke",
        lambda root: workflow_smoke.SmokeError("dispatch", "boom"),
    )
    result = _invoke_in_repo(["doctor", "workflow", "smoke-test", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "smoke_dispatch_failed"


def _wait_setup(monkeypatch, poll: workflow_smoke.SmokePollResult, cancelled: list):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(github, "get_repo_variable", lambda *, name, repo_root: None)
    monkeypatch.setattr(
        workflow_smoke,
        "dispatch_smoke",
        lambda root: workflow_smoke.SmokeDispatch(run_id="01J", run_ref="555", url="u/runs/555"),
    )
    monkeypatch.setattr(workflow_smoke, "poll_smoke", lambda root, ref, url: poll)
    monkeypatch.setattr(workflow_smoke, "cancel_smoke", lambda root, ref: cancelled.append(ref))


def test_smoke_wait_success_exit_0(monkeypatch):
    cancelled: list = []
    _wait_setup(
        monkeypatch,
        workflow_smoke.SmokePollResult("completed", "success", "u/runs/555", False),
        cancelled,
    )
    result = _invoke_in_repo(["doctor", "workflow", "smoke-test", "--wait", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["waited"] is True and payload["conclusion"] == "success"
    assert cancelled == []


def test_smoke_wait_failure_exit_1(monkeypatch):
    cancelled: list = []
    _wait_setup(
        monkeypatch,
        workflow_smoke.SmokePollResult("completed", "failure", "u/runs/555", False),
        cancelled,
    )
    result = _invoke_in_repo(["doctor", "workflow", "smoke-test", "--wait", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["conclusion"] == "failure"
    assert cancelled == []


def test_smoke_wait_timeout_exit_0_and_cancels(monkeypatch):
    cancelled: list = []
    _wait_setup(
        monkeypatch,
        workflow_smoke.SmokePollResult("in_progress", None, "u/runs/555", True),
        cancelled,
    )
    result = _invoke_in_repo(["doctor", "workflow", "smoke-test", "--wait", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["timed_out"] is True
    assert cancelled == ["555"]  # the timed-out run was self-cancelled
