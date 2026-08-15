"""Tests for the GitHub issue backend adapter.

Covers: static protocol conformance (ty-checked), per-method delegation onto the GitHub substrate's
issue-tier functions in ``perk.backends.github.plans`` (constructor-bound ``repo_root``,
``dry_run`` passthrough, str-id results),
``GitHubError`` → ``IssueBackendError`` translation (message verbatim, cause chained), the
non-numeric-id guard, the late-binding monkeypatch-interception guarantee, and the honest
human-engagement reads (the github-native rows from ``perk.backends.github.engagement`` mapped to
the neutral contract). The resolver + consumer-boundary source scan live in
``tests/test_resolve.py``.
"""

from pathlib import Path
from typing import Any

import pytest

from perk import github, objective, plan
from perk.backends import engagement, issue_backend
from perk.backends.github import engagement as gh_engagement
from perk.backends.github import plans
from perk.backends.github.backend import GitHubIssueBackend


def _make_backend(repo_root: Path) -> issue_backend.IssueBackend:
    """The static conformance check: ty verifies ``GitHubIssueBackend`` satisfies the protocol."""
    backend: issue_backend.IssueBackend = GitHubIssueBackend(repo_root)
    return backend


class TestConformance:
    def test_backend_satisfies_protocol(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        assert isinstance(backend, GitHubIssueBackend)

    def test_github_backend_id(self) -> None:
        assert GitHubIssueBackend.backend_id == "github"


class _Recorder:
    """Record a delegate call's kwargs and return a canned value."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}
        self.args: tuple[Any, ...] = ()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.args = args
        self.kwargs = kwargs
        return self.result


class TestDelegation:
    """Each method delegates with the bound repo_root, converts ids, and passes dry_run."""

    def test_ensure_label(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.Label(name="perk:plan", created=True))
        monkeypatch.setattr(plans, "create_label", rec)
        result = GitHubIssueBackend(tmp_path).ensure_label(
            "perk:plan", color="ababab", description="d", dry_run=True
        )
        assert rec.args == ("perk:plan",)
        assert rec.kwargs == {
            "color": "ababab",
            "description": "d",
            "repo_root": tmp_path,
            "dry_run": True,
        }
        assert result == issue_backend.Label(name="perk:plan", created=True)

    def test_find_plan_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanIssue(number=7, url="u7", existed=True))
        monkeypatch.setattr(plans, "find_plan_issue", rec)
        result = GitHubIssueBackend(tmp_path).find_plan_issue(run_id="RUN1")
        assert rec.kwargs == {"run_id": "RUN1", "repo_root": tmp_path}
        assert result == issue_backend.IssueRef(id="7", url="u7", existed=True)

    def test_find_plan_issue_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plans, "find_plan_issue", _Recorder(None))
        assert GitHubIssueBackend(tmp_path).find_plan_issue(run_id="RUN1") is None

    def test_create_plan_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanIssue(number=12, url="u12", existed=False))
        monkeypatch.setattr(plans, "create_plan_issue", rec)
        fields: dict[str, object] = {"run_id": "RUN1", "created": "t0"}
        result = GitHubIssueBackend(tmp_path).create_plan_issue(
            title="t", header_fields=fields, run_id="RUN1"
        )
        # The adapter renders the header block itself — the stored body is byte-identical to the
        # body the caller used to pre-render before the header_fields reshape.
        assert rec.kwargs == {
            "title": "t",
            "body": plan.render_metadata_block(plan.PLAN_HEADER_KEY, fields),
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "dry_run": False,
        }
        assert result == issue_backend.IssueRef(id="12", url="u12", existed=False)

    def test_update_plan_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            plans.PlanUpdate(number=12, body_updated=True, title_updated=True, dry_run=False)
        )
        monkeypatch.setattr(plans, "update_plan_issue", rec)
        result = GitHubIssueBackend(tmp_path).update_plan_issue(
            issue_id="12", title="t", body_comment="bc"
        )
        assert rec.kwargs == {
            "number": 12,
            "title": "t",
            "body_comment": "bc",
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == issue_backend.PlanUpdate(
            issue_id="12", body_updated=True, title_updated=True, dry_run=False
        )

    def test_update_plan_header(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanHeaderUpdate(fields_updated=("stage",), dry_run=True))
        monkeypatch.setattr(plans, "update_plan_header", rec)
        result = GitHubIssueBackend(tmp_path).update_plan_header(
            issue_id="3", fields={"stage": "implement"}, dry_run=True
        )
        assert rec.kwargs == {
            "issue": 3,
            "fields": {"stage": "implement"},
            "repo_root": tmp_path,
            "dry_run": True,
        }
        assert result == issue_backend.PlanHeaderUpdate(fields_updated=("stage",), dry_run=True)

    def test_get_plan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pr = github.PullRequest(number=9, url="pu", is_draft=True, state="OPEN", existed=True)
        rec = _Recorder(
            plans.PlanState(
                number=3,
                url="u3",
                title="t",
                header={"stage": "implement"},
                pr=pr,
                state="OPEN",
                has_plan_header=True,
            )
        )
        monkeypatch.setattr(plans, "get_plan", rec)
        result = GitHubIssueBackend(tmp_path).get_plan(issue_id="3")
        assert rec.kwargs == {"number": 3, "repo_root": tmp_path}
        assert result == issue_backend.PlanState(
            id="3",
            url="u3",
            title="t",
            header={"stage": "implement"},
            pr=pr,
            state="OPEN",
            has_plan_header=True,
        )

    def test_get_plan_maps_both_presence_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Both presence flags cross the native→neutral boundary verbatim.
        monkeypatch.setattr(
            plans,
            "get_plan",
            _Recorder(
                plans.PlanState(
                    number=3,
                    url="u3",
                    title="t",
                    header={},
                    pr=None,
                    state="OPEN",
                    has_plan_header=True,
                    has_objective_header=True,
                )
            ),
        )
        result = GitHubIssueBackend(tmp_path).get_plan(issue_id="3")
        assert result is not None
        assert result.has_plan_header is True and result.has_objective_header is True

    def test_get_plan_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plans, "get_plan", _Recorder(None))
        assert GitHubIssueBackend(tmp_path).get_plan(issue_id="3") is None

    def test_get_plan_body(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder("# the plan\n")
        monkeypatch.setattr(plans, "get_plan_body", rec)
        result = GitHubIssueBackend(tmp_path).get_plan_body(issue_id="3")
        assert rec.kwargs == {"number": 3, "repo_root": tmp_path}
        assert result == "# the plan\n"

    def test_read_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            plans.IssueRead(number=7, url="u7", title="Human title", body="do it", state="OPEN")
        )
        monkeypatch.setattr(plans, "read_issue", rec)
        result = GitHubIssueBackend(tmp_path).read_issue(issue_id="7")
        assert rec.kwargs == {"number": 7, "repo_root": tmp_path}
        assert result == issue_backend.AdoptableIssue(
            id="7", url="u7", title="Human title", body="do it", state="OPEN"
        )

    def test_read_issue_already_objective_from_the_body_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The adapter computes already_objective from the objective-header body block
        # (presence-only) — the native→neutral mapping for the wrong-kind door refusals.
        body = plan.render_metadata_block(
            objective.OBJECTIVE_HEADER_KEY, {"run_id": "01OBJ", "created": "t"}
        )
        monkeypatch.setattr(
            plans,
            "read_issue",
            _Recorder(plans.IssueRead(number=63, url="u", title="t", body=body, state="OPEN")),
        )
        result = GitHubIssueBackend(tmp_path).read_issue(issue_id="63")
        assert result is not None
        assert result.already_objective is True and result.already_plan is False

    def test_read_issue_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plans, "read_issue", _Recorder(None))
        assert GitHubIssueBackend(tmp_path).read_issue(issue_id="7") is None

    def test_read_issue_normalizes_closed_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `gh issue view` casing is normalized into the contract's OPEN/CLOSED vocabulary.
        monkeypatch.setattr(
            plans,
            "read_issue",
            _Recorder(plans.IssueRead(number=7, url="u7", title="t", body="b", state="closed")),
        )
        result = GitHubIssueBackend(tmp_path).read_issue(issue_id="7")
        assert result is not None and result.state == "CLOSED"

    def test_adopt_issue_as_plan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanAdoption(number=7, url="u7", dry_run=False))
        monkeypatch.setattr(plans, "adopt_issue_as_plan", rec)
        result = GitHubIssueBackend(tmp_path).adopt_issue_as_plan(
            issue_id="7",
            header_fields={"run_id": "R", "adopted_from": "7"},
            plan_markdown="# plan\n",
            callout="CALLOUT",
            command="perk impl 7",
        )
        assert rec.kwargs == {
            "number": 7,
            "header_fields": {"run_id": "R", "adopted_from": "7"},
            "plan_markdown": "# plan\n",
            "callout": "CALLOUT",
            "command": "perk impl 7",
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == issue_backend.IssueRef(id="7", url="u7", existed=True)

    def test_find_learn_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanIssue(number=8, url="u8", existed=True))
        monkeypatch.setattr(plans, "find_learn_issue", rec)
        result = GitHubIssueBackend(tmp_path).find_learn_issue(run_id="RUN1")
        assert rec.kwargs == {"run_id": "RUN1", "repo_root": tmp_path}
        assert result == issue_backend.IssueRef(id="8", url="u8", existed=True)

    def test_create_learn_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanIssue(number=14, url="u14", existed=False))
        monkeypatch.setattr(plans, "create_learn_issue", rec)
        result = GitHubIssueBackend(tmp_path).create_learn_issue(
            title="t", body="b", run_id="RUN1", plan_id="12", dry_run=True
        )
        assert rec.kwargs == {
            "title": "t",
            "body": "b",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "plan_number": 12,
            "decision": None,
            "target": None,
            "dry_run": True,
        }
        assert result == issue_backend.IssueRef(id="14", url="u14", existed=False)

    def test_list_learn_issues(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder((plans.LearnIssueSummary(number=5, title="t5", url="u5", body="b5"),))
        monkeypatch.setattr(plans, "list_learn_issues", rec)
        result = GitHubIssueBackend(tmp_path).list_learn_issues()
        assert rec.kwargs == {"repo_root": tmp_path}
        assert result == (issue_backend.LearnIssueSummary(id="5", title="t5", url="u5", body="b5"),)

    def test_list_learn_issues_decodes_header_from_body(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The populated arm: the adapter (not the factory) owns the body→LearnHeader parse now,
        # so a rendered learn-header block must come back decoded (incl. `decision`).
        body = plan.render_metadata_block(
            plan.LEARN_HEADER_KEY,
            {"run_id": "01L", "created": "t", "plan": 12, "decision": "SHOULD_BE_CODE"},
        )
        rec = _Recorder((plans.LearnIssueSummary(number=5, title="t5", url="u5", body=body),))
        monkeypatch.setattr(plans, "list_learn_issues", rec)
        [summary] = GitHubIssueBackend(tmp_path).list_learn_issues()
        assert summary.header is not None
        assert summary.header.run_id == "01L"
        assert summary.header.plan == 12
        assert summary.header.decision == "SHOULD_BE_CODE"

    def test_list_plans_pending_learn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(
            (
                plans.PendingLearnPlanIssue(
                    number=8, title="t8", url="u8", closed_at="2026-01-02T03:04:05Z"
                ),
            )
        )
        monkeypatch.setattr(plans, "list_plans_pending_learn", rec)
        result = GitHubIssueBackend(tmp_path).list_plans_pending_learn(limit=25)
        assert rec.kwargs == {"repo_root": tmp_path, "limit": 25}
        assert result == (
            issue_backend.PendingLearnPlan(
                id="8", title="t8", url="u8", closed_at="2026-01-02T03:04:05Z"
            ),
        )

    def test_find_gist_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanIssue(number=9, url="u9", existed=True))
        monkeypatch.setattr(plans, "find_gist_issue", rec)
        result = GitHubIssueBackend(tmp_path).find_gist_issue(run_id="RUN1")
        assert rec.kwargs == {"run_id": "RUN1", "repo_root": tmp_path}
        assert result == issue_backend.IssueRef(id="9", url="u9", existed=True)

    def test_create_gist_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.PlanIssue(number=15, url="u15", existed=False))
        monkeypatch.setattr(plans, "create_gist_issue", rec)
        result = GitHubIssueBackend(tmp_path).create_gist_issue(
            title="t", body="b", run_id="RUN1", scope="plan", dry_run=True
        )
        assert rec.kwargs == {
            "title": "t",
            "body": "b",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "scope": "plan",
            "dry_run": True,
        }
        assert result == issue_backend.IssueRef(id="15", url="u15", existed=False)

    def test_list_gist_issues(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder((plans.GistIssueSummary(number=6, title="t6", url="u6", body="b6"),))
        monkeypatch.setattr(plans, "list_gist_issues", rec)
        result = GitHubIssueBackend(tmp_path).list_gist_issues()
        assert rec.kwargs == {"repo_root": tmp_path}
        assert result == (
            issue_backend.GistSummary(
                id="6", title="t6", url="u6", body="b6", scope=None, adopted=False
            ),
        )

    def test_list_gist_issues_decodes_scope_and_adopted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The adapter owns the body→scope parse + adopted detection: a body carrying a
        # plan-header (or objective-header) beside the gist-header flips `adopted`.
        gist_only = plan.render_gist_header(run_id="01G", created="t", scope="objective")
        adopted_body = (
            plan.render_gist_header(run_id="01H", created="t", scope="plan")
            + "\n\n"
            + plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "01P"})
        )
        objective_adopted_body = (
            plan.render_gist_header(run_id="01I", created="t", scope="objective")
            + "\n\n"
            + plan.render_metadata_block(objective.OBJECTIVE_HEADER_KEY, {"run_id": "01O"})
        )
        rec = _Recorder(
            (
                plans.GistIssueSummary(number=1, title="a", url="u1", body=gist_only),
                plans.GistIssueSummary(number=2, title="b", url="u2", body=adopted_body),
                plans.GistIssueSummary(number=3, title="c", url="u3", body=objective_adopted_body),
            )
        )
        monkeypatch.setattr(plans, "list_gist_issues", rec)
        fresh, plan_adopted, objective_adopted = GitHubIssueBackend(tmp_path).list_gist_issues()
        assert fresh.scope == "objective" and fresh.adopted is False
        assert plan_adopted.scope == "plan" and plan_adopted.adopted is True
        assert objective_adopted.adopted is True

    def test_close_and_label_consolidated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(True)
        monkeypatch.setattr(plans, "close_and_label_consolidated", rec)
        assert GitHubIssueBackend(tmp_path).close_and_label_consolidated(issue_id="5") is True
        assert rec.kwargs == {"issue": 5, "repo_root": tmp_path, "dry_run": False}

    def test_close_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(True)
        monkeypatch.setattr(plans, "close_issue", rec)
        assert GitHubIssueBackend(tmp_path).close_issue(issue_id="5", dry_run=True) is True
        assert rec.kwargs == {"number": 5, "repo_root": tmp_path, "dry_run": True}

    def test_add_issue_comment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.CommentResult(posted=True))
        monkeypatch.setattr(plans, "add_issue_comment", rec)
        result = GitHubIssueBackend(tmp_path).add_issue_comment(issue_id="5", body="hi")
        assert rec.kwargs == {"issue": 5, "body": "hi", "repo_root": tmp_path, "dry_run": False}
        assert result == issue_backend.CommentResult(posted=True)

    def test_find_comment_id_by_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(98765)
        monkeypatch.setattr(plans, "find_comment_id_by_marker", rec)
        result = GitHubIssueBackend(tmp_path).find_comment_id_by_marker(
            issue_id="5", marker="<!-- m -->"
        )
        assert rec.kwargs == {"issue": 5, "marker": "<!-- m -->", "repo_root": tmp_path}
        assert result == "98765"

    def test_find_comment_id_by_marker_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plans, "find_comment_id_by_marker", _Recorder(None))
        backend = GitHubIssueBackend(tmp_path)
        assert backend.find_comment_id_by_marker(issue_id="5", marker="m") is None

    def test_upsert_marked_comment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(plans.CommentResult(posted=False))
        monkeypatch.setattr(plans, "upsert_marked_comment", rec)
        result = GitHubIssueBackend(tmp_path).upsert_marked_comment(
            issue_id="5", marker="m", body="b", dry_run=True
        )
        assert rec.kwargs == {
            "issue": 5,
            "marker": "m",
            "body": "b",
            "repo_root": tmp_path,
            "dry_run": True,
        }
        assert result == issue_backend.CommentResult(posted=False)


class TestEngagementReads:
    """The honest GitHub reads: github-native rows → neutral engagement contract."""

    def test_read_comments_maps_authors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            gh_engagement.IssueCommentRow(
                id="IC_1",
                body="a human note",
                created_at="2026-03-01T00:00:00Z",
                edited_at=None,
                author_login="alice",
                author_id="11",
                author_is_bot=False,
            ),
            gh_engagement.IssueCommentRow(
                id="IC_2",
                body="automation beep",
                created_at="2026-03-02T00:00:00Z",
                edited_at="2026-03-03T00:00:00Z",
                author_login="other-bot",
                author_id="22",
                author_is_bot=True,
            ),
            gh_engagement.IssueCommentRow(
                id="IC_3",
                body="summary <!-- perk:metadata-block:plan-body --> end",
                created_at="2026-03-04T00:00:00Z",
                edited_at=None,
                author_login="carol",
                author_id="33",
                author_is_bot=False,
            ),
        ]
        rec = _Recorder(rows)
        monkeypatch.setattr(gh_engagement, "read_issue_comments", rec)
        comments = GitHubIssueBackend(tmp_path).read_comments(issue_id="42")
        assert rec.kwargs == {"issue": 42, "repo_root": tmp_path}
        assert [c.author.kind for c in comments] == ["human", "other_agent", "perk"]
        assert comments[0].author.id == "11" and comments[0].edited_at is None
        assert comments[1].edited_at == "2026-03-03T00:00:00Z"
        # the perk-by-sentinel comment came from a human actor but classifies as perk
        assert comments[2].author.display_name == "carol"

    def test_read_description_edits_maps_diff_and_authors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            gh_engagement.DescriptionEditRow(
                edited_at="2026-04-01T00:00:00Z",
                diff="@@ -1 +1 @@",
                editor_login="human",
                editor_id="8",
                editor_is_bot=False,
            ),
            gh_engagement.DescriptionEditRow(
                edited_at="2026-04-02T00:00:00Z",
                diff=None,
                editor_login="bot",
                editor_id="9",
                editor_is_bot=True,
            ),
        ]
        rec = _Recorder(rows)
        monkeypatch.setattr(gh_engagement, "read_description_edits", rec)
        edits = GitHubIssueBackend(tmp_path).read_description_edits(issue_id="42")
        assert rec.kwargs == {"issue": 42, "repo_root": tmp_path}
        assert edits[0].diff == "@@ -1 +1 @@" and edits[0].author.kind == "human"
        assert edits[1].diff is None and edits[1].author.kind == "other_agent"
        assert edits[1].created_at == "2026-04-02T00:00:00Z"

    def test_read_comments_deleted_author_classifies_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A deleted/unresolvable GitHub account (author null) carries no login/id: it must
        # classify as `unknown`, never `human`.
        rows = [
            gh_engagement.IssueCommentRow(
                id="IC_1",
                body="orphaned comment",
                created_at="2026-03-01T00:00:00Z",
                edited_at=None,
                author_login=None,
                author_id=None,
                author_is_bot=False,
            )
        ]
        monkeypatch.setattr(gh_engagement, "read_issue_comments", _Recorder(rows))
        comments = GitHubIssueBackend(tmp_path).read_comments(issue_id="42")
        assert comments[0].author.kind == "unknown"
        assert comments[0].author.id is None and comments[0].author.display_name is None

    def test_read_agent_session_is_github_no_op(self, tmp_path: Path) -> None:
        result = GitHubIssueBackend(tmp_path).read_agent_session(issue_id="42")
        assert result is engagement.EMPTY_AGENT_SESSION

    def test_read_comments_error_translation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**kwargs: Any) -> None:
            raise github.GitHubError("HTTP 500: boom")

        monkeypatch.setattr(gh_engagement, "read_issue_comments", boom)
        with pytest.raises(issue_backend.IssueBackendError, match="HTTP 500: boom"):
            GitHubIssueBackend(tmp_path).read_comments(issue_id="42")

    def test_read_comments_non_numeric_id_raises(self, tmp_path: Path) -> None:
        with pytest.raises(issue_backend.IssueBackendError, match="numeric"):
            GitHubIssueBackend(tmp_path).read_comments(issue_id="LIN-42")


class TestErrorTranslation:
    def test_github_error_wrapped_message_verbatim_cause_chained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = github.GitHubError("objective node '9.9' not found on #252")

        def boom(**kwargs: Any) -> None:
            raise original

        monkeypatch.setattr(plans, "get_plan", boom)
        with pytest.raises(issue_backend.IssueBackendError) as excinfo:
            GitHubIssueBackend(tmp_path).get_plan(issue_id="252")
        assert str(excinfo.value) == "objective node '9.9' not found on #252"
        assert excinfo.value.__cause__ is original

    def test_non_numeric_issue_id_raises_backend_error(self, tmp_path: Path) -> None:
        backend = GitHubIssueBackend(tmp_path)
        with pytest.raises(issue_backend.IssueBackendError, match="LIN-42"):
            backend.get_plan(issue_id="LIN-42")
        with pytest.raises(issue_backend.IssueBackendError, match="numeric"):
            backend.create_learn_issue(title="t", body="b", run_id=None, plan_id="abc")


class TestLateBinding:
    def test_patch_after_construction_still_intercepts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The guarantee the whole pytest suite relies on: backends delegate via attribute
        # access on the github module object at CALL time, so a monkeypatch applied after the
        # backend was constructed is still seen.
        backend = GitHubIssueBackend(tmp_path)
        rec = _Recorder(
            plans.PlanState(number=1, url="u", title="t", header={}, pr=None, state="OPEN")
        )
        monkeypatch.setattr(plans, "get_plan", rec)
        result = backend.get_plan(issue_id="1")
        assert result is not None
        assert result.id == "1"
        assert rec.kwargs == {"number": 1, "repo_root": tmp_path}
