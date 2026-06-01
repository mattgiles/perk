import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.cli.cli import cli

PLAN = "# My Feature\n\nDo the thing.\n"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_writes(monkeypatch, *, existed: bool = False) -> dict[str, bool]:
    calls = {"commented": False}
    monkeypatch.setattr(github, "create_label", lambda *a, **k: github.Label("perk:plan", False))
    monkeypatch.setattr(
        github,
        "create_plan_issue",
        lambda **k: github.PlanIssue(number=123, url="https://gh/o/r/issues/123", existed=existed),
    )

    def _comment(**_k):
        calls["commented"] = True
        return github.CommentResult(posted=True)

    monkeypatch.setattr(github, "add_issue_comment", _comment)
    return calls


def _run(monkeypatch, args, *, write_plan=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_plan:
            (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        return runner.invoke(cli, args)


def test_plan_save_success(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md"])
    assert result.exit_code == 0
    assert "#123" in result.output
    assert calls["commented"] is True


def test_plan_save_json_shape(monkeypatch):
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["issue"] == {"number": 123, "url": "https://gh/o/r/issues/123"}
    assert payload["plan_ref"]["provider"] == "github"
    assert payload["plan_ref"]["pr_id"] == "123"  # string
    assert payload["dry_run"] is False


def test_plan_save_unauthed_exit_1(monkeypatch):
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(False, None, (), "not logged in")
    )
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_unauthed"


def test_plan_save_missing_plan_file_exit_1(monkeypatch):
    _authed(monkeypatch)
    result = _run(monkeypatch, ["plan-save", "--json"], write_plan=False)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"


def test_plan_save_empty_plan_file_exit_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text("   \n", encoding="utf-8")
        result = runner.invoke(cli, ["plan-save", "--plan-file", "plan.md"])
    assert result.exit_code == 1
    assert "empty" in result.output


def test_plan_save_not_a_repo_exit_2(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["plan-save", "--plan-file", "plan.md", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_plan_save_dry_run_offline(monkeypatch):
    # --dry-run must skip require_github and shell NO gh. Boom the gh wrapper (not git, which
    # require_repo legitimately shells); dry_run short-circuits before any gh call.
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(github, "_run", boom)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md", "--dry-run"])
    assert result.exit_code == 0
    assert "plan-header" in result.output and "plan-body" in result.output


def test_plan_save_github_error_exit_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "create_label", lambda *a, **k: github.Label("perk:plan", False))

    def _boom(**_k):
        raise github.GitHubError("403 forbidden")

    monkeypatch.setattr(github, "create_plan_issue", _boom)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"


def test_plan_save_idempotent_no_comment(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch, existed=True)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md"])
    assert result.exit_code == 0
    assert "Found existing" in result.output
    assert calls["commented"] is False  # existing issue -> no duplicate comment
