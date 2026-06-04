import json
import subprocess
from pathlib import Path
from typing import cast

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


def _stub_writes(monkeypatch, *, existed: bool = False) -> dict[str, object]:
    calls: dict[str, object] = {"commented": False, "updated": None}
    monkeypatch.setattr(github, "create_label", lambda *a, **k: github.Label("perk:plan", False))
    monkeypatch.setattr(
        github,
        "create_plan_issue",
        lambda **k: github.PlanIssue(number=123, url="https://gh/o/r/issues/123", existed=existed),
    )

    def _comment(**_k):
        calls["commented"] = True
        return github.CommentResult(posted=True)

    def _update(**k):
        calls["updated"] = k
        return github.PlanUpdate(
            number=k["number"], body_updated=True, title_updated=True, dry_run=False
        )

    monkeypatch.setattr(github, "add_issue_comment", _comment)
    monkeypatch.setattr(github, "update_plan_issue", _update)
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
    assert payload["issue"] == {
        "number": 123,
        "url": "https://gh/o/r/issues/123",
        "existed": False,
    }
    assert payload["plan_ref"]["provider"] == "github"
    assert payload["plan_ref"]["pr_id"] == "123"  # string
    assert payload["cached"] is True
    assert payload["dry_run"] is False


def test_plan_save_writes_cache_plan_ref(monkeypatch):
    # A real save persists the cache.plan-ref pointer (turn-2b §7).
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(cli, ["plan-save", "--plan-file", "plan.md"])
        assert result.exit_code == 0
        ref = json.loads((Path(d) / ".pi" / "workflow" / "plan-ref.json").read_text())
    assert ref == {
        "provider": "github",
        "pr_id": "123",
        "url": "https://gh/o/r/issues/123",
        "labels": ["perk:plan"],
        "objective_id": None,
        "consumed_learn": [],
    }


def test_plan_save_objective_id_threads_into_header_and_ref(monkeypatch):
    # P2.T10: --objective-id populates the plan header block AND the cache.plan-ref.
    _authed(monkeypatch)
    captured: dict[str, str] = {}
    monkeypatch.setattr(github, "create_label", lambda *a, **k: github.Label("perk:plan", False))

    def _create(**k):
        captured["body"] = k["body"]
        return github.PlanIssue(number=123, url="https://gh/o/r/issues/123", existed=False)

    monkeypatch.setattr(github, "create_plan_issue", _create)
    monkeypatch.setattr(github, "add_issue_comment", lambda **k: github.CommentResult(posted=True))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(cli, ["plan-save", "--plan-file", "plan.md", "--objective-id", "7"])
        assert result.exit_code == 0, result.output
        ref = json.loads((Path(d) / ".pi" / "workflow" / "plan-ref.json").read_text())
    assert "objective_id: '7'" in captured["body"]
    assert ref["objective_id"] == "7"


def test_plan_save_node_id_commits_objective_node(monkeypatch):
    # P2.T10: --objective-id + --node-id flips the node to in_progress with the pr backlink.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    captured: dict[str, object] = {}

    def _update_node(**k):
        captured.update(k)
        return github.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(github, "update_objective_node", _update_node)
    result = _run(
        monkeypatch,
        [
            "plan-save",
            "--plan-file",
            "plan.md",
            "--objective-id",
            "7",
            "--node-id",
            "1.1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    from perk import objective

    assert captured["number"] == 7
    assert captured["node_id"] == "1.1"
    assert captured["status"] is objective.NodeStatus.IN_PROGRESS
    assert captured["pr"] == "#123"
    payload = json.loads(result.stdout)
    assert payload["objective_node"] == {
        "linked": True,
        "node": "1.1",
        "status": "in_progress",
        "error": None,
    }


def test_plan_save_node_link_failure_is_non_fatal(monkeypatch):
    # A failing update_objective_node leaves the save successful (the plan already exists).
    _authed(monkeypatch)
    _stub_writes(monkeypatch)

    def _boom(**_k):
        raise github.GitHubError("node 1.1 not found on #7")

    monkeypatch.setattr(github, "update_objective_node", _boom)
    result = _run(
        monkeypatch,
        [
            "plan-save",
            "--plan-file",
            "plan.md",
            "--objective-id",
            "7",
            "--node-id",
            "1.1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["objective_node"]["linked"] is False
    assert payload["objective_node"]["error"]
    assert "objective node link skipped" in result.stderr


def test_plan_save_without_node_id_skips_objective_node(monkeypatch):
    # Omitting --node-id (even with --objective-id) makes no update_objective_node call.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)

    def _boom(**_k):
        raise AssertionError("must not link a node without --node-id")

    monkeypatch.setattr(github, "update_objective_node", _boom)
    result = _run(
        monkeypatch, ["plan-save", "--plan-file", "plan.md", "--objective-id", "7", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["objective_node"] is None


def test_plan_save_dry_run_does_not_write_cache(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(cli, ["plan-save", "--plan-file", "plan.md", "--dry-run", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["cached"] is False
        assert not (Path(d) / ".pi" / "workflow" / "plan-ref.json").exists()


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


def test_plan_save_resave_updates_in_place(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch, existed=True)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md"])
    assert result.exit_code == 0
    assert "Updated" in result.output
    assert calls["commented"] is False  # existing issue -> no add_issue_comment dup
    # The upsert path PATCHes the existing issue with the re-derived title + body.
    updated = calls["updated"]
    assert isinstance(updated, dict)
    kwargs = cast("dict[str, object]", updated)
    assert kwargs["number"] == 123
    assert kwargs["title"] == "My Feature"  # re-derived from the plan H1
    assert "Do the thing." in str(kwargs["body_comment"])


def test_plan_save_resave_json_reports_updated(monkeypatch):
    _authed(monkeypatch)
    _stub_writes(monkeypatch, existed=True)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["updated"] is True
    assert payload["issue"]["existed"] is True
    assert payload["cached"] is True


def test_plan_save_fresh_create_reports_not_updated(monkeypatch):
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md", "--json"])
    payload = json.loads(result.stdout)
    assert payload["updated"] is False
    assert payload["cached"] is True
