import json
import subprocess
from pathlib import Path
from typing import cast

from click.testing import CliRunner

from perk import github, issue_backend, issues
from perk.cli.cli import cli

PLAN = "# My Feature\n\nDo the thing.\n"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_writes(monkeypatch, *, existed: bool = False) -> dict[str, object]:
    calls: dict[str, object] = {"commented": False, "updated": None, "header": None}
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

    def _update_header(**k):
        calls["header"] = k
        return github.PlanHeaderUpdate(fields_updated=tuple(k.get("fields", {})), dry_run=False)

    monkeypatch.setattr(github, "add_issue_comment", _comment)
    monkeypatch.setattr(github, "update_plan_issue", _update)
    monkeypatch.setattr(github, "update_plan_header", _update_header)
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
        "id": "123",
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


def test_plan_save_stamps_provider_from_resolved_backend(monkeypatch):
    # The plan-ref provider is the resolved backend's `backend_id` (contracts.md §8.21), not a
    # hardcoded literal: a stub backend claiming "linear" must surface verbatim in the ref.
    _authed(monkeypatch)

    class _StubBackend:
        backend_id = "linear"

        def ensure_label(self, name, *, color, description, dry_run=False):
            return issue_backend.Label(name=name, created=False)

        def create_plan_issue(self, *, title, body, run_id, dry_run=False):
            return issue_backend.IssueRef(id="9", url="https://lin/i/9", existed=False)

        def add_issue_comment(self, *, issue_id, body, dry_run=False):
            return issue_backend.CommentResult(posted=True)

    monkeypatch.setattr(issues, "resolve_issue_backend", lambda _root: _StubBackend())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(cli, ["plan-save", "--plan-file", "plan.md"])
        assert result.exit_code == 0
        ref = json.loads((Path(d) / ".pi" / "workflow" / "plan-ref.json").read_text())
    assert ref["provider"] == "linear"


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


def _run_with_handoff(monkeypatch, args, handoff, run_id="run-abc"):
    """Run plan-save in an isolated repo seeded with a handoff for ``run_id`` (#78)."""
    from perk.state import cache

    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        if handoff is not None:
            cache.write_handoff(Path(d), run_id, handoff)
        monkeypatch.setenv("PERK_RUN_ID", run_id)
        return runner.invoke(cli, args)


def test_plan_save_recovers_objective_link_from_handoff(monkeypatch):
    # #78: a /plan-save command path (no --objective-id/--node-id) recovers the link from the
    # handoff the objective-plan factory stashed, links the node, and writes objective_id to the
    # plan-ref.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    captured: dict[str, object] = {}

    def _update_node(**k):
        captured.update(k)
        return github.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(github, "update_objective_node", _update_node)
    result = _run_with_handoff(
        monkeypatch,
        ["plan-save", "--plan-file", "plan.md", "--json"],
        {"stage": "objective-plan", "mode": "read-only", "objective_id": "63", "node_id": "1.1"},
    )
    assert result.exit_code == 0, result.output
    from perk import objective

    assert captured["number"] == 63
    assert captured["node_id"] == "1.1"
    assert captured["status"] is objective.NodeStatus.IN_PROGRESS
    assert captured["pr"] == "#123"
    payload = json.loads(result.stdout)
    assert payload["plan_ref"]["objective_id"] == "63"
    assert payload["objective_node"]["linked"] is True


def test_plan_save_explicit_flags_override_handoff(monkeypatch):
    # #78: explicit --objective-id/--node-id always win over the handoff's values.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    captured: dict[str, object] = {}

    def _update_node(**k):
        captured.update(k)
        return github.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(github, "update_objective_node", _update_node)
    result = _run_with_handoff(
        monkeypatch,
        [
            "plan-save",
            "--plan-file",
            "plan.md",
            "--objective-id",
            "7",
            "--node-id",
            "2.3",
            "--json",
        ],
        {"stage": "objective-plan", "mode": "read-only", "objective_id": "63", "node_id": "1.1"},
    )
    assert result.exit_code == 0, result.output
    assert captured["number"] == 7
    assert captured["node_id"] == "2.3"
    assert json.loads(result.stdout)["plan_ref"]["objective_id"] == "7"


def test_plan_save_handoff_without_objective_is_unlinked(monkeypatch):
    # #78: a plain (non-objective) handoff carries no objective_id, so the save stays unlinked.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)

    def _boom(**_k):
        raise AssertionError("must not link a node from a non-objective handoff")

    monkeypatch.setattr(github, "update_objective_node", _boom)
    result = _run_with_handoff(
        monkeypatch,
        ["plan-save", "--plan-file", "plan.md", "--json"],
        {"stage": "plan", "mode": "read-only"},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["plan_ref"]["objective_id"] is None
    assert payload["objective_node"] is None


def test_plan_save_recovers_consumed_learn_from_handoff(monkeypatch):
    # #102: a /plan-save command path (no --consumed-learn) recovers the gathered perk:learn
    # numbers the learn-docs factory stashed in the handoff, persisting them in the plan-ref +
    # header so the on-land consume can close them.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run_with_handoff(
        monkeypatch,
        ["plan-save", "--plan-file", "plan.md", "--json"],
        {"stage": "plan", "mode": "read-only", "consumed_learn": [45, 50]},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["plan_ref"]["consumed_learn"] == ["45", "50"]


def test_plan_save_explicit_consumed_learn_overrides_handoff(monkeypatch):
    # #102: an explicit --consumed-learn always wins over the handoff's numbers.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run_with_handoff(
        monkeypatch,
        ["plan-save", "--plan-file", "plan.md", "--consumed-learn", "7,9", "--json"],
        {"stage": "plan", "mode": "read-only", "consumed_learn": [45, 50]},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["plan_ref"]["consumed_learn"] == ["7", "9"]


def test_plan_save_handoff_without_consumed_learn_is_empty(monkeypatch):
    # #102: a non-factory handoff carries no consumed_learn key, so the save stays empty.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run_with_handoff(
        monkeypatch,
        ["plan-save", "--plan-file", "plan.md", "--json"],
        {"stage": "plan", "mode": "read-only"},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["plan_ref"]["consumed_learn"] == []


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

    monkeypatch.setattr(github._exec, "_run", boom)
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
    assert calls["header"] is None  # no planning header fields -> no header merge


def test_plan_save_resave_merges_header_fields(monkeypatch):
    # Re-save must propagate the planning-time header fields (objective_id, consumed_learn) into
    # the existing plan-header block (the canonical source reconstruct_plan_ref / on-land consume
    # read), since update_plan_issue only rewrites the body comment + title.
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch, existed=True)
    result = _run(
        monkeypatch,
        [
            "plan-save",
            "--plan-file",
            "plan.md",
            "--consumed-learn",
            "50,45",
            "--objective-id",
            "7",
        ],
    )
    assert result.exit_code == 0
    header = calls["header"]
    assert isinstance(header, dict)
    kwargs = cast("dict[str, object]", header)
    assert kwargs["issue"] == 123
    assert kwargs["fields"] == {"objective_id": "7", "consumed_learn": ["45", "50"]}


def test_plan_save_resave_without_header_fields_skips_update(monkeypatch):
    # A plain re-save (no --consumed-learn / --objective-id) must not call update_plan_header —
    # no needless write, no clobber of a previously linked objective/learn set.
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch, existed=True)
    result = _run(monkeypatch, ["plan-save", "--plan-file", "plan.md"])
    assert result.exit_code == 0
    assert calls["header"] is None


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
