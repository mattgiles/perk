import json
import subprocess
from pathlib import Path
from typing import cast

from click.testing import CliRunner

from perk import github, plan
from perk.backends import issue_backend, objective_store, resolve
from perk.backends.github import objectives, plans
from perk.cli.commands.plan.save_cmd import plan_save
from perk.cli.context import PerkContext

PLAN = "# My Feature\n\nDo the thing.\n"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_writes(monkeypatch, *, existed: bool = False) -> dict[str, object]:
    calls: dict[str, object] = {
        "commented": False,
        "updated": None,
        "header": None,
        "callout": None,
    }
    monkeypatch.setattr(plans, "create_label", lambda *a, **k: plans.Label("perk:plan", False))
    monkeypatch.setattr(
        plans,
        "create_plan_issue",
        lambda **k: plans.PlanIssue(number=123, url="https://gh/o/r/issues/123", existed=existed),
    )

    def _comment(**_k):
        calls["commented"] = True
        return plans.CommentResult(posted=True)

    def _update(**k):
        calls["updated"] = k
        return plans.PlanUpdate(
            number=k["number"], body_updated=True, title_updated=True, dry_run=False
        )

    def _update_header(**k):
        calls["header"] = k
        return plans.PlanHeaderUpdate(fields_updated=tuple(k.get("fields", {})), dry_run=False)

    def _callout(**k):
        calls["callout"] = k
        return True

    monkeypatch.setattr(plans, "add_issue_comment", _comment)
    monkeypatch.setattr(plans, "update_plan_issue", _update)
    monkeypatch.setattr(plans, "update_plan_header", _update_header)
    monkeypatch.setattr(plans, "prepend_plan_callout", _callout)
    return calls


def _run(monkeypatch, args, *, write_plan=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_plan:
            (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        return runner.invoke(plan_save, args, obj=PerkContext(cwd=Path(d)))


def test_plan_save_success(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["--plan-file", "plan.md"])
    assert result.exit_code == 0
    assert "#123" in result.output
    assert calls["commented"] is True


def test_plan_save_fresh_create_prepends_plan_callout(monkeypatch):
    # A fresh standalone save prepends a visible `perk impl <id>` callout to the plan issue body.
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["--plan-file", "plan.md"])
    assert result.exit_code == 0
    callout = calls["callout"]
    assert isinstance(callout, dict)
    kwargs = cast("dict[str, object]", callout)
    assert kwargs["issue"] == 123
    assert kwargs["command"] == "perk impl 123"
    assert "perk impl 123" in str(kwargs["callout"])
    assert str(kwargs["callout"]).startswith("**Implement this plan:**")


def test_plan_save_callout_survives_header_block_rewrite():
    # The callout lives above the hidden plan-header block, so it parses fine and survives a
    # subsequent submit-time update_plan_header (which rewrites only the header block).
    issue_body = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, {"run_id": "RUN-XYZ", "lifecycle_stage": "plan"}
    )
    callout = plan.plan_callout("123")
    body = plan.prepend_callout(issue_body, callout, command="perk impl 123")
    assert body.startswith("**Implement this plan:**")
    assert plan.extract_run_id(body) == "RUN-XYZ"
    # Simulate update_plan_header: rewrite only the header block in place.
    header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
    rewritten = plan.replace_metadata_block(
        body, plan.PLAN_HEADER_KEY, {**header, "branch": "perk/plan-123"}
    )
    assert rewritten.startswith("**Implement this plan:**")
    assert plan.extract_run_id(rewritten) == "RUN-XYZ"
    assert "perk impl 123" in rewritten


def test_plan_save_resave_does_not_prepend_callout(monkeypatch):
    # The callout is injected only on the fresh-create path; a re-save never re-prepends.
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch, existed=True)
    result = _run(monkeypatch, ["--plan-file", "plan.md"])
    assert result.exit_code == 0
    assert calls["callout"] is None


# ----------------------------------------------------- in-place issue adoption (§8.29)


def _stub_adopt(monkeypatch) -> dict[str, object]:
    """Stub the adoption write surface; record the adopt call + flag any second-object create."""
    calls: dict[str, object] = {"adopt": None, "created": False}
    monkeypatch.setattr(
        plans,
        "read_issue",
        lambda **k: plans.IssueRead(number=7, url="u/7", title="t", body="b", state="OPEN"),
    )

    def _adopt(**k):
        calls["adopt"] = k
        return plans.PlanAdoption(number=int(k["number"]), url="u/7", dry_run=False)

    def _create(**_k):
        calls["created"] = True  # a second perk:plan issue would be the bug
        return plans.PlanIssue(number=999, url="x", existed=False)

    monkeypatch.setattr(plans, "adopt_issue_as_plan", _adopt)
    monkeypatch.setattr(plans, "create_plan_issue", _create)
    monkeypatch.setattr(plans, "create_label", lambda *a, **k: plans.Label("perk:plan", False))
    return calls


def test_plan_save_adopt_from_stamps_in_place(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_adopt(monkeypatch)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--adopt-from", "7", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] is True
    assert payload["issue"]["id"] == "7" and payload["issue"]["existed"] is True
    assert payload["plan_ref"]["pr_id"] == "7"
    assert payload["plan_ref"]["labels"] == [plan.PLAN_LABEL]
    # No second object minted; the adoption stamp carried the provenance + the impl callout.
    assert calls["created"] is False
    adopt = cast("dict[str, object]", calls["adopt"])
    header_fields = cast("dict[str, object]", adopt["header_fields"])
    assert header_fields["adopted_from"] == "7"
    assert adopt["command"] == "perk impl 7"
    assert "Do the thing" in cast("str", adopt["plan_markdown"])


def test_plan_save_adopt_from_strips_hash(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_adopt(monkeypatch)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--adopt-from", "#7", "--json"])
    assert result.exit_code == 0, result.output
    adopt = cast("dict[str, object]", calls["adopt"])
    header_fields = cast("dict[str, object]", adopt["header_fields"])
    assert adopt["number"] == 7 and header_fields["adopted_from"] == "7"


def test_plan_save_adopt_from_mutually_exclusive_with_objective(monkeypatch):
    _authed(monkeypatch)
    _stub_adopt(monkeypatch)
    result = _run(
        monkeypatch,
        ["--plan-file", "plan.md", "--adopt-from", "7", "--objective-id", "5", "--json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_input"
    assert "mutually exclusive" in payload["message"]


def test_plan_save_adopt_from_recovered_from_handoff(monkeypatch):
    from perk.state import cache

    _authed(monkeypatch)
    calls = _stub_adopt(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        cache.write_handoff(Path(d), "RID7", {"stage": "plan", "adopt_from": "7"})
        # No --adopt-from flag: the link is recovered from the run handoff.
        result = runner.invoke(
            plan_save,
            ["--plan-file", "plan.md", "--run-id", "RID7", "--json"],
            obj=PerkContext(cwd=Path(d)),
        )
        assert result.exit_code == 0, result.output
    adopt = cast("dict[str, object]", calls["adopt"])
    assert adopt["number"] == 7
    assert calls["created"] is False


def test_plan_save_json_shape(monkeypatch):
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--json"])
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
    # A real save persists the cache.plan-ref pointer.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(plan_save, ["--plan-file", "plan.md"], obj=PerkContext(cwd=Path(d)))
        assert result.exit_code == 0
        ref = json.loads((Path(d) / ".pi" / "workflow" / "plan-ref.json").read_text())
    assert ref == {
        "provider": "github",
        "pr_id": "123",
        "url": "https://gh/o/r/issues/123",
        "labels": ["perk:plan"],
        "objective_id": None,
        "consumed_learn": [],
        "base": None,
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

        def prepend_plan_callout(self, *, issue_id, callout, command, dry_run=False):
            return True

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: _StubBackend())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(plan_save, ["--plan-file", "plan.md"], obj=PerkContext(cwd=Path(d)))
        assert result.exit_code == 0
        ref = json.loads((Path(d) / ".pi" / "workflow" / "plan-ref.json").read_text())
    assert ref["provider"] == "linear"


def test_plan_save_objective_id_threads_into_header_and_ref(monkeypatch):
    # --objective-id populates the plan header block AND the cache.plan-ref.
    _authed(monkeypatch)
    captured: dict[str, str] = {}
    monkeypatch.setattr(plans, "create_label", lambda *a, **k: plans.Label("perk:plan", False))

    def _create(**k):
        captured["body"] = k["body"]
        return plans.PlanIssue(number=123, url="https://gh/o/r/issues/123", existed=False)

    monkeypatch.setattr(plans, "create_plan_issue", _create)
    monkeypatch.setattr(plans, "add_issue_comment", lambda **k: plans.CommentResult(posted=True))
    monkeypatch.setattr(plans, "prepend_plan_callout", lambda **k: True)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(
            plan_save,
            ["--plan-file", "plan.md", "--objective-id", "7"],
            obj=PerkContext(cwd=Path(d)),
        )
        assert result.exit_code == 0, result.output
        ref = json.loads((Path(d) / ".pi" / "workflow" / "plan-ref.json").read_text())
    assert "objective_id: '7'" in captured["body"]
    assert ref["objective_id"] == "7"


def test_plan_save_node_id_commits_objective_node(monkeypatch):
    # --objective-id + --node-id flips the node to in_progress with the pr backlink.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    captured: dict[str, object] = {}

    def _update_node(**k):
        captured.update(k)
        return objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "update_objective_node", _update_node)
    result = _run(
        monkeypatch,
        [
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

    monkeypatch.setattr(objectives, "update_objective_node", _boom)
    result = _run(
        monkeypatch,
        [
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

    monkeypatch.setattr(objectives, "update_objective_node", _boom)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--objective-id", "7", "--json"])
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
        return runner.invoke(plan_save, args, obj=PerkContext(cwd=Path(d)))


def test_plan_save_recovers_objective_link_from_handoff(monkeypatch):
    # #78: a /plan-save command path (no --objective-id/--node-id) recovers the link from the
    # handoff the objective-plan factory stashed, links the node, and writes objective_id to the
    # plan-ref.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    captured: dict[str, object] = {}

    def _update_node(**k):
        captured.update(k)
        return objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "update_objective_node", _update_node)
    result = _run_with_handoff(
        monkeypatch,
        ["--plan-file", "plan.md", "--json"],
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
        return objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "update_objective_node", _update_node)
    result = _run_with_handoff(
        monkeypatch,
        [
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

    monkeypatch.setattr(objectives, "update_objective_node", _boom)
    result = _run_with_handoff(
        monkeypatch,
        ["--plan-file", "plan.md", "--json"],
        {"stage": "plan", "mode": "read-only"},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["plan_ref"]["objective_id"] is None
    assert payload["objective_node"] is None


def test_plan_save_recovers_consumed_learn_from_handoff(monkeypatch):
    # A /plan-save command path (no --consumed-learn) recovers the gathered perk:learn
    # numbers the learn-docs factory stashed in the handoff, persisting them in the plan-ref +
    # header so the on-land consume can close them.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run_with_handoff(
        monkeypatch,
        ["--plan-file", "plan.md", "--json"],
        {"stage": "plan", "mode": "read-only", "consumed_learn": [45, 50]},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["plan_ref"]["consumed_learn"] == ["45", "50"]


def test_plan_save_explicit_consumed_learn_overrides_handoff(monkeypatch):
    # An explicit --consumed-learn always wins over the handoff's numbers.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run_with_handoff(
        monkeypatch,
        ["--plan-file", "plan.md", "--consumed-learn", "7,9", "--json"],
        {"stage": "plan", "mode": "read-only", "consumed_learn": [45, 50]},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["plan_ref"]["consumed_learn"] == ["7", "9"]


def test_plan_save_handoff_without_consumed_learn_is_empty(monkeypatch):
    # A non-factory handoff carries no consumed_learn key, so the save stays empty.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run_with_handoff(
        monkeypatch,
        ["--plan-file", "plan.md", "--json"],
        {"stage": "plan", "mode": "read-only"},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["plan_ref"]["consumed_learn"] == []


def _run_with_config(monkeypatch, args, *, config):
    """Run plan-save in an isolated repo seeded with a committed `.perk/config.toml` (base)."""
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cfg = Path(d) / ".perk"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.toml").write_text(config, encoding="utf-8")
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(plan_save, args, obj=PerkContext(cwd=Path(d)))
        ref = None
        ref_path = Path(d) / ".pi" / "workflow" / "plan-ref.json"
        if ref_path.exists():
            ref = json.loads(ref_path.read_text())
    return result, ref


def test_plan_save_pins_base_from_config(monkeypatch):
    # A standalone save with [workflow] base set pins it into BOTH the plan-header body and
    # the cache.plan-ref.
    _authed(monkeypatch)
    captured: dict[str, str] = {}
    monkeypatch.setattr(plans, "create_label", lambda *a, **k: plans.Label("perk:plan", False))

    def _create(**k):
        captured["body"] = k["body"]
        return plans.PlanIssue(number=123, url="https://gh/o/r/issues/123", existed=False)

    monkeypatch.setattr(plans, "create_plan_issue", _create)
    monkeypatch.setattr(plans, "add_issue_comment", lambda **k: plans.CommentResult(posted=True))
    monkeypatch.setattr(plans, "prepend_plan_callout", lambda **k: True)
    result, ref = _run_with_config(
        monkeypatch, ["--plan-file", "plan.md"], config='[workflow]\nbase = "develop"\n'
    )
    assert result.exit_code == 0, result.output
    assert "base: develop" in captured["body"]
    assert ref is not None and ref["base"] == "develop"


def test_plan_save_inherits_objective_base(monkeypatch):
    # An objective-linked save reads the objective's own base (objective-header) and pins it
    # into the plan-header + plan-ref, winning over the config default.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: objectives.ObjectiveState(
            number=7, url="u/7", title="t", header={"base": "release"}, nodes=()
        ),
    )
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    result, ref = _run_with_config(
        monkeypatch,
        ["--plan-file", "plan.md", "--objective-id", "7", "--node-id", "1.1", "--json"],
        config='[workflow]\nbase = "develop"\n',
    )
    assert result.exit_code == 0, result.output
    assert ref is not None and ref["base"] == "release"  # objective base wins over config
    assert json.loads(result.stdout)["plan_ref"]["base"] == "release"


def test_plan_save_objective_without_base_falls_through_to_config(monkeypatch):
    # An objective whose header carries NO base falls through fail-soft to [workflow] base.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: objectives.ObjectiveState(number=7, url="u/7", title="t", header={}, nodes=()),
    )
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    result, ref = _run_with_config(
        monkeypatch,
        ["--plan-file", "plan.md", "--objective-id", "7", "--node-id", "1.1", "--json"],
        config='[workflow]\nbase = "develop"\n',
    )
    assert result.exit_code == 0, result.output
    assert ref is not None and ref["base"] == "develop"


def test_plan_save_get_objective_failure_falls_through_to_config(monkeypatch):
    # A failing get_objective must be fail-soft — fall through to config base, never block.
    _authed(monkeypatch)
    _stub_writes(monkeypatch)

    def _boom(**_k):
        raise github.GitHubError("boom")

    monkeypatch.setattr(objectives, "get_objective", _boom)
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    result, ref = _run_with_config(
        monkeypatch,
        ["--plan-file", "plan.md", "--objective-id", "7", "--node-id", "1.1", "--json"],
        config='[workflow]\nbase = "develop"\n',
    )
    assert result.exit_code == 0, result.output
    assert ref is not None and ref["base"] == "develop"


def test_plan_save_no_base_anywhere_is_none(monkeypatch):
    # Neither an objective base nor [workflow] base → base stays None (default-branch path).
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["plan_ref"]["base"] is None


def test_plan_save_resave_preserves_base(monkeypatch):
    # An idempotent re-save merges base back into the existing plan-header (never drops it).
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch, existed=True)
    result, _ref = _run_with_config(
        monkeypatch, ["--plan-file", "plan.md"], config='[workflow]\nbase = "develop"\n'
    )
    assert result.exit_code == 0, result.output
    header = calls["header"]
    assert isinstance(header, dict)
    assert cast("dict[str, object]", header)["fields"] == {"base": "develop"}


def test_plan_save_dry_run_does_not_write_cache(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(
            plan_save,
            ["--plan-file", "plan.md", "--dry-run", "--json"],
            obj=PerkContext(cwd=Path(d)),
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["cached"] is False
        assert not (Path(d) / ".pi" / "workflow" / "plan-ref.json").exists()


def test_plan_save_unauthed_exit_1(monkeypatch):
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(False, None, (), "not logged in")
    )
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_unauthed"


def test_plan_save_missing_plan_file_exit_1(monkeypatch):
    _authed(monkeypatch)
    result = _run(monkeypatch, ["--json"], write_plan=False)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"


def test_plan_save_empty_plan_file_exit_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text("   \n", encoding="utf-8")
        result = runner.invoke(plan_save, ["--plan-file", "plan.md"], obj=PerkContext(cwd=Path(d)))
    assert result.exit_code == 1
    assert "empty" in result.output


def test_plan_save_not_a_repo_exit_2(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:  # no git init
        result = runner.invoke(
            plan_save, ["--plan-file", "plan.md", "--json"], obj=PerkContext(cwd=Path(d))
        )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_plan_save_dry_run_offline(monkeypatch):
    # --dry-run must skip require_github and shell NO gh. Boom the gh wrapper (not git, which
    # require_repo legitimately shells); dry_run short-circuits before any gh call.
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(github._exec, "_run", boom)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--dry-run"])
    assert result.exit_code == 0
    assert "plan-header" in result.output and "plan-body" in result.output


def test_plan_save_github_error_exit_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "create_label", lambda *a, **k: plans.Label("perk:plan", False))

    def _boom(**_k):
        raise github.GitHubError("403 forbidden")

    monkeypatch.setattr(plans, "create_plan_issue", _boom)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"


def test_plan_save_resave_updates_in_place(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch, existed=True)
    result = _run(monkeypatch, ["--plan-file", "plan.md"])
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
    result = _run(monkeypatch, ["--plan-file", "plan.md"])
    assert result.exit_code == 0
    assert calls["header"] is None


def test_plan_save_resave_json_reports_updated(monkeypatch):
    _authed(monkeypatch)
    _stub_writes(monkeypatch, existed=True)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["updated"] is True
    assert payload["issue"]["existed"] is True
    assert payload["cached"] is True


def test_plan_save_fresh_create_reports_not_updated(monkeypatch):
    _authed(monkeypatch)
    _stub_writes(monkeypatch)
    result = _run(monkeypatch, ["--plan-file", "plan.md", "--json"])
    payload = json.loads(result.stdout)
    assert payload["updated"] is False
    assert payload["cached"] is True


def test_plan_save_unified_node_issue_path(monkeypatch):
    # An objective-linked save into a UNIFYING store (save_node_plan returns a node-issue
    # ref) writes the plan INTO the node-issue — NO create_plan_issue/ensure_label — and stamps
    # cache.plan-ref at that node-issue id (no perk:plan label), reporting updated=True +
    # objective_node.linked=True.
    _authed(monkeypatch)
    node_calls: dict[str, object] = {}

    class _UnifyingStore:
        backend_id = "linear"

        def save_node_plan(
            self, *, objective_id, node_id, header_fields, plan_markdown, dry_run=False
        ):
            node_calls["save"] = {"objective_id": objective_id, "node_id": node_id}
            node_calls["header_fields"] = header_fields
            return objective_store.ObjectiveRef(id="ENG-7", url="https://lin/i/ENG-7", existed=True)

        def update_objective_node(self, **k):
            node_calls["link"] = k
            return objective_store.ObjectiveNodeUpdate(
                objective_id=str(k["objective_id"]),
                node_id=k["node_id"],
                comment_updated=False,
                dry_run=False,
            )

    class _Backend:
        backend_id = "linear"

        def ensure_label(self, *a, **k):
            raise AssertionError("ensure_label must not run on the unified path")

        def create_plan_issue(self, **k):
            raise AssertionError("create_plan_issue must not run on the unified path")

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: _UnifyingStore())
    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: _Backend())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        result = runner.invoke(
            plan_save,
            [
                "--plan-file",
                "plan.md",
                "--objective-id",
                "proj-1",
                "--node-id",
                "1.1",
                "--json",
            ],
            obj=PerkContext(cwd=Path(d)),
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        ref = json.loads((Path(d) / ".pi" / "workflow" / "plan-ref.json").read_text())
    assert payload["issue"]["id"] == "ENG-7"
    assert payload["issue"]["existed"] is True
    assert payload["updated"] is True
    assert payload["objective_node"]["linked"] is True
    assert ref["pr_id"] == "ENG-7"
    assert ref["provider"] == "linear"
    assert ref["labels"] == []  # the node-issue carries no perk:plan label
    # the unification write got the composed PlanHeader data + the link-commit ran uniformly
    assert node_calls["save"] == {"objective_id": "proj-1", "node_id": "1.1"}
    assert "lifecycle_stage" in cast("dict", node_calls["header_fields"])
    assert cast("dict", node_calls["link"])["pr"] == "#ENG-7"


def test_plan_save_dry_run_keeps_offline_preview_for_unifying_store(monkeypatch):
    # --dry-run never calls save_node_plan (offline compose-preview); the standalone preview path
    # is taken even with an objective link.
    _authed(monkeypatch)

    class _Store:
        backend_id = "github"

        def save_node_plan(self, **k):
            raise AssertionError("save_node_plan must not run on --dry-run")

        def update_objective_node(self, **k):
            raise AssertionError("no link-commit on --dry-run")

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: _Store())
    result = _run(
        monkeypatch,
        [
            "--plan-file",
            "plan.md",
            "--objective-id",
            "7",
            "--node-id",
            "1.1",
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["cached"] is False
