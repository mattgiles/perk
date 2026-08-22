"""Tests for the GitHub objective-store adapter (``perk/backends/github/objective_store.py``).

Covers: static ``ObjectiveStore`` conformance (ty-checked), ``GitHubObjectiveStore`` per-method
delegation onto the objective substrate (``perk.backends.github.objectives``) and — for
``read_objective_source``/``close_objective`` — the plan/issue substrate
(``perk.backends.github.plans``, a GitHub objective IS an issue), constructor-bound ``repo_root``,
``dry_run`` passthrough, str-id results, ``GitHubError`` → ``ObjectiveStoreError`` translation + the
non-numeric-id guard, the late-binding interception guarantee, and the honest engagement reads.
The resolver + consumer-boundary source scans live in ``tests/test_resolve.py`` (split out of the
retired ``test_objective_stores.py`` to match the module home, mirroring the 2.1 backend/resolve
split).
"""

from pathlib import Path
from typing import Any

import pytest

from perk import github, objective
from perk.backends import engagement, objective_store
from perk.backends.github import engagement as gh_engagement
from perk.backends.github import objectives, plans
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.backends.linear import LinearObjectiveStore
from perk.backends.objective_store import ObjectiveStoreError


def _make_store(repo_root: Path) -> objective_store.ObjectiveStore:
    """The static conformance check: ty verifies ``GitHubObjectiveStore`` satisfies the protocol."""
    store: objective_store.ObjectiveStore = GitHubObjectiveStore(repo_root)
    return store


class TestConformance:
    def test_github_store_satisfies_protocol(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert isinstance(store, GitHubObjectiveStore)

    def test_github_store_backend_id(self) -> None:
        assert GitHubObjectiveStore.backend_id == "github"

    def test_linear_store_backend_id(self) -> None:
        assert LinearObjectiveStore.backend_id == "linear"


class _Recorder:
    """Record a delegate call's kwargs and return a canned value."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.result


class TestGitHubDelegation:
    def test_find_objective(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(objectives.ObjectiveIssue(number=252, url="u252", existed=True))
        monkeypatch.setattr(objectives, "find_objective_issue", rec)
        result = GitHubObjectiveStore(tmp_path).find_objective(run_id="RUN1")
        assert rec.kwargs == {"run_id": "RUN1", "repo_root": tmp_path}
        assert result == objective_store.ObjectiveRef(id="252", url="u252", existed=True)

    def test_find_objective_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(objectives, "find_objective_issue", _Recorder(None))
        assert GitHubObjectiveStore(tmp_path).find_objective(run_id="RUN1") is None

    def test_create_objective(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(objectives.ObjectiveIssue(number=252, url="u252", existed=False))
        monkeypatch.setattr(objectives, "create_objective_issue", rec)
        result = GitHubObjectiveStore(tmp_path).create_objective(
            title="t", body="b", run_id="RUN1", status="active", roadmap_nodes=None
        )
        assert rec.kwargs == {
            "title": "t",
            "body": "b",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "status": "active",
            "base": None,
            "roadmap_nodes": None,
            "delivery": None,
            "delivery_lineage": None,
            "origin": None,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveRef(id="252", url="u252", existed=False)

    def test_create_objective_forwards_stacked_delivery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The non-None arm: the enum reaches the substrate as its "stacked" value, the lineage
        # verbatim — dropping/hard-coding either in the adapter must fail here.
        rec = _Recorder(objectives.ObjectiveIssue(number=252, url="u252", existed=False))
        monkeypatch.setattr(objectives, "create_objective_issue", rec)
        GitHubObjectiveStore(tmp_path).create_objective(
            title="t",
            body="b",
            run_id="RUN1",
            delivery=objective.DeliveryPolicy.STACKED,
            delivery_lineage="01LINEAGE",
        )
        assert rec.kwargs is not None
        assert rec.kwargs["delivery"] == "stacked"
        assert rec.kwargs["delivery_lineage"] == "01LINEAGE"

    def test_create_objective_forwards_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The non-None arm (the defaulted-None forwarding discipline): the enum reaches the
        # substrate as its "learn-dream" value — dropping/hard-coding it in the adapter fails
        # here; the default-None forwarding is pinned by test_create_objective's kwargs dict.
        rec = _Recorder(objectives.ObjectiveIssue(number=252, url="u252", existed=False))
        monkeypatch.setattr(objectives, "create_objective_issue", rec)
        GitHubObjectiveStore(tmp_path).create_objective(
            title="t", body="b", run_id="RUN1", origin=objective.ObjectiveOrigin.LEARN_DREAM
        )
        assert rec.kwargs is not None
        assert rec.kwargs["origin"] == "learn-dream"

    def test_find_open_objective_by_origin_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(objectives.ObjectiveIssue(number=252, url="u252", existed=True))
        monkeypatch.setattr(objectives, "find_objective_issue_by_origin", rec)
        result = GitHubObjectiveStore(tmp_path).find_open_objective_by_origin(
            origin=objective.ObjectiveOrigin.LEARN_DREAM, exclude_run_id="RUN1"
        )
        assert rec.kwargs == {
            "origin": "learn-dream",
            "exclude_run_id": "RUN1",
            "repo_root": tmp_path,
        }
        assert result == objective_store.ObjectiveRef(id="252", url="u252", existed=True)

    def test_find_open_objective_by_origin_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(None)
        monkeypatch.setattr(objectives, "find_objective_issue_by_origin", rec)
        result = GitHubObjectiveStore(tmp_path).find_open_objective_by_origin(
            origin=objective.ObjectiveOrigin.LEARN_DREAM
        )
        assert result is None
        assert rec.kwargs["exclude_run_id"] is None  # the default forwards as None

    def test_find_open_objective_by_origin_translates_github_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**kwargs: Any) -> None:
            raise github.GitHubError("origin scan exploded")

        monkeypatch.setattr(objectives, "find_objective_issue_by_origin", boom)
        with pytest.raises(ObjectiveStoreError, match="origin scan exploded"):
            GitHubObjectiveStore(tmp_path).find_open_objective_by_origin(
                origin=objective.ObjectiveOrigin.LEARN_DREAM
            )

    def test_list_objective_completion_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder((objectives.OpenObjectiveIssue(number=252, title="O252"),))
        monkeypatch.setattr(objectives, "list_open_objective_issues", rec)
        result = GitHubObjectiveStore(tmp_path).list_objective_completion_candidates()
        assert rec.kwargs == {"repo_root": tmp_path}
        assert result == (objective_store.ObjectiveSummary(id="252", title="O252"),)

    def test_get_objective(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            objectives.ObjectiveState(number=252, url="u252", title="t", header={}, nodes=())
        )
        monkeypatch.setattr(objectives, "get_objective", rec)
        result = GitHubObjectiveStore(tmp_path).get_objective(objective_id="252")
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path}
        assert result == objective_store.ObjectiveState(
            id="252", url="u252", title="t", header={}, nodes=()
        )

    def test_get_objective_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(objectives, "get_objective", _Recorder(None))
        assert GitHubObjectiveStore(tmp_path).get_objective(objective_id="252") is None

    def test_get_objective_lifecycle_state_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(
            objectives.ObjectiveState(
                number=252, url="u252", title="t", header={}, nodes=(), state="closed"
            )
        )
        monkeypatch.setattr(objectives, "get_objective", rec)
        result = GitHubObjectiveStore(tmp_path).get_objective(objective_id="252")
        assert result is not None and result.state == "closed"

    def test_journal_carrier_id_is_the_objective_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(
            objectives.ObjectiveState(number=252, url="u252", title="t", header={}, nodes=())
        )
        monkeypatch.setattr(objectives, "get_objective", rec)
        assert GitHubObjectiveStore(tmp_path).journal_carrier_id(objective_id="252") == "252"
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path}

    def test_journal_carrier_id_none_when_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(objectives, "get_objective", _Recorder(None))
        assert GitHubObjectiveStore(tmp_path).journal_carrier_id(objective_id="252") is None

    def test_update_objective_header(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(objectives.ObjectiveHeaderUpdate(fields_updated=("status",), dry_run=False))
        monkeypatch.setattr(objectives, "update_objective_header", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_header(
            objective_id="252", fields={"status": "done"}
        )
        assert rec.kwargs == {
            "number": 252,
            "fields": {"status": "done"},
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveHeaderUpdate(
            fields_updated=("status",), dry_run=False
        )

    def test_update_objective_node(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            objectives.ObjectiveNodeUpdate(
                number=252, node_id="1.2", comment_updated=True, dry_run=False
            )
        )
        monkeypatch.setattr(objectives, "update_objective_node", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_node(
            objective_id="252",
            node_id="1.2",
            status=objective.NodeStatus.DONE,
            pr="#325",
            description=None,
        )
        assert rec.kwargs == {
            "number": 252,
            "node_id": "1.2",
            "status": objective.NodeStatus.DONE,
            "pr": "#325",
            "description": None,
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveNodeUpdate(
            objective_id="252", node_id="1.2", comment_updated=True, dry_run=False
        )

    def test_add_objective_node(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            objectives.ObjectiveNodeAdd(
                number=252, node_id="1.3", comment_updated=True, dry_run=False
            )
        )
        monkeypatch.setattr(objectives, "add_objective_node", rec)
        result = GitHubObjectiveStore(tmp_path).add_objective_node(
            objective_id="252",
            phase=1,
            description="Gamma",
            depends_on=("1.1",),
        )
        assert rec.kwargs == {
            "number": 252,
            "phase": 1,
            "description": "Gamma",
            "status": objective.NodeStatus.PENDING,
            "slug": None,
            "depends_on": ("1.1",),
            "comment": None,
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveNodeAdd(
            objective_id="252", node_id="1.3", comment_updated=True, dry_run=False
        )

    def test_add_objective_node_stacked_refusal_passes_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The substrate's typed tail-append refusal (contracts.md §8.66) must reach the door
        # AS StackedAppendRefused — the adapter's GitHubError translation never rewraps it.
        def _refuse(**_kwargs: object) -> objectives.ObjectiveNodeAdd:
            raise objective_store.StackedAppendRefused(("not a tail append",))

        monkeypatch.setattr(objectives, "add_objective_node", _refuse)
        with pytest.raises(objective_store.StackedAppendRefused) as err:
            GitHubObjectiveStore(tmp_path).add_objective_node(
                objective_id="252", phase=1, description="Gamma"
            )
        assert err.value.errors == ("not a tail append",)

    def test_update_objective_body(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            objectives.ObjectiveBodyUpdate(number=252, comment_id=777, updated=True, dry_run=False)
        )
        monkeypatch.setattr(objectives, "update_objective_body", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_body(objective_id="252", prose="p")
        assert rec.kwargs == {
            "number": 252,
            "prose": "p",
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveBodyUpdate(
            objective_id="252", comment_id="777", updated=True, dry_run=False
        )

    def test_update_objective_body_none_comment_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(
            objectives.ObjectiveBodyUpdate(number=252, comment_id=None, updated=False, dry_run=True)
        )
        monkeypatch.setattr(objectives, "update_objective_body", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_body(
            objective_id="252", prose="p", dry_run=True
        )
        assert result.comment_id is None

    def test_read_objective_source(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            plans.IssueRead(number=7, url="u7", title="Human title", body="OVERVIEW", state="OPEN")
        )
        monkeypatch.setattr(plans, "read_issue", rec)
        result = GitHubObjectiveStore(tmp_path).read_objective_source(source_id="7")
        assert rec.kwargs == {"number": 7, "repo_root": tmp_path}
        assert result == objective_store.AdoptableObjectiveSource(
            id="7", url="u7", title="Human title", prose="OVERVIEW", issues=()
        )

    def test_read_objective_source_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plans, "read_issue", _Recorder(None))
        assert GitHubObjectiveStore(tmp_path).read_objective_source(source_id="7") is None

    def test_adopt_source_as_objective(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(
            objectives.ObjectiveAdoption(number=7, url="u7", existed=False, dry_run=False)
        )
        monkeypatch.setattr(objectives, "adopt_issue_as_objective", rec)
        nodes = [
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
        ]
        result = GitHubObjectiveStore(tmp_path).adopt_source_as_objective(
            source_id="7",
            title="t",
            prose="p",
            run_id="RUN1",
            roadmap_nodes=nodes,
            adopt_map={"1.1": "ignored-on-github"},
        )
        assert rec.kwargs == {
            "number": 7,
            "title": "t",
            "prose": "p",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "status": "active",
            "base": None,
            "roadmap_nodes": nodes,
        }
        assert result == objective_store.ObjectiveRef(id="7", url="u7", existed=False)

    def test_adopt_source_as_objective_dry_run_returns_none(self, tmp_path: Path) -> None:
        result = GitHubObjectiveStore(tmp_path).adopt_source_as_objective(
            source_id="7",
            title="t",
            prose="p",
            run_id="RUN1",
            roadmap_nodes=[],
            adopt_map={},
            dry_run=True,
        )
        assert result is None

    def test_supersede_objective(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(objectives.ObjectiveIssue(number=99, url="u99", existed=False))
        monkeypatch.setattr(objectives, "supersede_objective_issue", rec)
        nodes = [
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
        ]
        result = GitHubObjectiveStore(tmp_path).supersede_objective(
            old_objective_id="42",
            title="t",
            prose="p",
            run_id="RUN1",
            roadmap_nodes=nodes,
            carry_map={"1.1": "ignored-on-github"},
        )
        assert rec.kwargs == {
            "old_number": 42,
            "title": "t",
            "prose": "p",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "status": "active",
            "base": None,
            "roadmap_nodes": nodes,
            "delivery": None,
            "delivery_lineage": None,
            "close_predecessor": True,
        }
        assert result == objective_store.ObjectiveRef(id="99", url="u99", existed=False)

    def test_supersede_objective_forwards_deferred_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(objectives.ObjectiveIssue(number=99, url="u99", existed=False))
        monkeypatch.setattr(objectives, "supersede_objective_issue", rec)
        nodes = [
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
        ]
        GitHubObjectiveStore(tmp_path).supersede_objective(
            old_objective_id="42",
            title="t",
            prose="p",
            run_id="RUN1",
            roadmap_nodes=nodes,
            carry_map={},
            close_predecessor=False,
        )
        assert rec.kwargs is not None and rec.kwargs["close_predecessor"] is False

    def test_finalize_supersession_delegates_and_translates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(None)
        monkeypatch.setattr(objectives, "finalize_supersession_issue", rec)
        store = GitHubObjectiveStore(tmp_path)
        assert store.finalize_supersession(old_objective_id="#42", new_objective_id="99")
        assert rec.kwargs == {"old_number": 42, "new_number": 99, "repo_root": tmp_path}

        def _fail(**_kwargs):
            raise github.GitHubError("finalize failed")

        monkeypatch.setattr(objectives, "finalize_supersession_issue", _fail)
        with pytest.raises(ObjectiveStoreError, match="finalize failed") as excinfo:
            store.finalize_supersession(old_objective_id="42", new_objective_id="99")
        assert isinstance(excinfo.value.__cause__, github.GitHubError)

    def test_supersede_objective_forwards_stacked_delivery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(objectives.ObjectiveIssue(number=99, url="u99", existed=False))
        monkeypatch.setattr(objectives, "supersede_objective_issue", rec)
        nodes = [
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
        ]
        GitHubObjectiveStore(tmp_path).supersede_objective(
            old_objective_id="42",
            title="t",
            prose="p",
            run_id="RUN1",
            roadmap_nodes=nodes,
            carry_map={},
            delivery=objective.DeliveryPolicy.STACKED,
            delivery_lineage="01LINEAGE",
        )
        assert rec.kwargs is not None
        assert rec.kwargs["delivery"] == "stacked"
        assert rec.kwargs["delivery_lineage"] == "01LINEAGE"

    def test_supersede_objective_dry_run_returns_none(self, tmp_path: Path) -> None:
        result = GitHubObjectiveStore(tmp_path).supersede_objective(
            old_objective_id="42",
            title="t",
            prose="p",
            run_id="RUN1",
            roadmap_nodes=[],
            carry_map={},
            dry_run=True,
        )
        assert result is None

    def test_save_node_plan_returns_none(self, tmp_path: Path) -> None:
        # GitHub does not unify node + plan: always None so the caller takes the standalone path.
        result = GitHubObjectiveStore(tmp_path).save_node_plan(
            objective_id="252", node_id="1.1", header_fields={"run_id": "R"}, plan_markdown="# p"
        )
        assert result is None

    def test_close_objective_closes_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(True)
        monkeypatch.setattr(plans, "close_issue", rec)
        result = GitHubObjectiveStore(tmp_path).close_objective(objective_id="252")
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path, "dry_run": False}
        assert result is True

    def test_close_objective_dry_run_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(False)
        monkeypatch.setattr(plans, "close_issue", rec)
        result = GitHubObjectiveStore(tmp_path).close_objective(objective_id="252", dry_run=True)
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path, "dry_run": True}
        assert result is False

    def test_reopen_objective_reopens_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(True)
        monkeypatch.setattr(plans, "reopen_issue", rec)
        result = GitHubObjectiveStore(tmp_path).reopen_objective(objective_id="252")
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path, "dry_run": False}
        assert result is True

    def test_reopen_objective_dry_run_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(False)
        monkeypatch.setattr(plans, "reopen_issue", rec)
        result = GitHubObjectiveStore(tmp_path).reopen_objective(objective_id="252", dry_run=True)
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path, "dry_run": True}
        assert result is False

    def test_post_status_update_is_noop_false(self, tmp_path: Path) -> None:
        # GitHub has no Project Updates surface — always False, never raises, no `gh`.
        store = GitHubObjectiveStore(tmp_path)
        assert store.post_status_update(objective_id="252", body="x") is False
        assert store.post_status_update(objective_id="252", body="x", dry_run=True) is False

    def test_read_node_engagement_is_empty(self, tmp_path: Path) -> None:
        # GitHub single-issue objectives have no per-node issues — honest empty no-op.
        result = GitHubObjectiveStore(tmp_path).read_node_engagement(
            objective_id="252", node_id="1.1"
        )
        assert result is engagement.EMPTY_NODE_ENGAGEMENT

    def test_read_comments_honest_over_objective_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Honest over the objective issue itself: reuse
        # `gh_engagement.read_issue_comments` + the shared `backend._engagement_comment` mapper.
        row = gh_engagement.IssueCommentRow(
            id="c-1",
            body="please rescope",
            created_at="2026-03-01T10:00:00Z",
            edited_at=None,
            author_login="ada",
            author_id="u-1",
            author_is_bot=False,
        )
        captured: dict[str, Any] = {}

        def _read(**kwargs: Any) -> list[gh_engagement.IssueCommentRow]:
            captured.update(kwargs)
            return [row]

        monkeypatch.setattr(gh_engagement, "read_issue_comments", _read)
        out = GitHubObjectiveStore(tmp_path).read_comments(objective_id="252")
        assert captured == {"issue": 252, "repo_root": tmp_path}
        assert [c.id for c in out] == ["c-1"]
        assert out[0].body == "please rescope"
        assert out[0].author.kind == "human"

    def test_read_description_edits_honest_over_objective_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        row = gh_engagement.DescriptionEditRow(
            edited_at="2026-03-02T11:00:00Z",
            diff="@@ -1 +1 @@",
            editor_login="ada",
            editor_id="u-1",
            editor_is_bot=False,
        )
        captured: dict[str, Any] = {}

        def _read(**kwargs: Any) -> list[gh_engagement.DescriptionEditRow]:
            captured.update(kwargs)
            return [row]

        monkeypatch.setattr(gh_engagement, "read_description_edits", _read)
        out = GitHubObjectiveStore(tmp_path).read_description_edits(objective_id="252")
        assert captured == {"issue": 252, "repo_root": tmp_path}
        assert len(out) == 1
        assert out[0].created_at == "2026-03-02T11:00:00Z"
        assert out[0].diff == "@@ -1 +1 @@"
        assert out[0].author.kind == "human"

    def test_read_comments_wraps_github_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**kwargs: Any) -> list[gh_engagement.IssueCommentRow]:
            raise github.GitHubError("gh exploded")

        monkeypatch.setattr(gh_engagement, "read_issue_comments", _boom)
        with pytest.raises(ObjectiveStoreError, match="gh exploded"):
            GitHubObjectiveStore(tmp_path).read_comments(objective_id="252")


class TestErrorTranslation:
    def test_github_error_wrapped_message_verbatim_cause_chained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = github.GitHubError("objective node '9.9' not found on #252")

        def boom(**kwargs: Any) -> None:
            raise original

        monkeypatch.setattr(objectives, "get_objective", boom)
        with pytest.raises(ObjectiveStoreError) as excinfo:
            GitHubObjectiveStore(tmp_path).get_objective(objective_id="252")
        assert str(excinfo.value) == "objective node '9.9' not found on #252"
        assert excinfo.value.__cause__ is original

    def test_non_numeric_objective_id_raises_store_error(self, tmp_path: Path) -> None:
        store = GitHubObjectiveStore(tmp_path)
        with pytest.raises(ObjectiveStoreError, match="LIN-42"):
            store.get_objective(objective_id="LIN-42")
        with pytest.raises(ObjectiveStoreError, match="numeric"):
            store.update_objective_body(objective_id="abc", prose="p")

    def test_canonical_hash_id_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The store accepts its own supersession writer's canonical `#<n>` rendering (the
        # `supersedes`/`superseded_by` values feed straight back into `get_objective`).
        rec = _Recorder(
            objectives.ObjectiveState(number=42, url="u42", title="t", header={}, nodes=())
        )
        monkeypatch.setattr(objectives, "get_objective", rec)
        result = GitHubObjectiveStore(tmp_path).get_objective(objective_id="#42")
        assert rec.kwargs == {"number": 42, "repo_root": tmp_path}
        assert result is not None and result.id == "42"

    def test_hash_only_junk_still_raises(self, tmp_path: Path) -> None:
        store = GitHubObjectiveStore(tmp_path)
        with pytest.raises(ObjectiveStoreError, match="numeric"):
            store.get_objective(objective_id="#abc")
        with pytest.raises(ObjectiveStoreError, match="numeric"):
            store.get_objective(objective_id="##42")


class TestLateBinding:
    def test_patch_after_construction_still_intercepts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Backends delegate via attribute access on the objectives module object at CALL time, so
        # a monkeypatch applied after the store was constructed is still seen (the equivalence lock
        # that keeps the CLI objective tests green through the extraction).
        store = GitHubObjectiveStore(tmp_path)
        rec = _Recorder(objectives.ObjectiveIssue(number=7, url="u7", existed=True))
        monkeypatch.setattr(objectives, "find_objective_issue", rec)
        result = store.find_objective(run_id="RUN1")
        assert result is not None
        assert result.id == "7"
