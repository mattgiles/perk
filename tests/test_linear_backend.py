"""Tests for ``LinearIssueBackend`` (Objective #252, Node 2.2) — offline, scripted fake client.

The static conformance check is one annotated binding (``_make_backend``): ty fails the suite if
``LinearIssueBackend`` and the ``IssueBackend`` protocol drift. The runtime tests pin the
GitHub-twin behavior shapes (find/create idempotency, upserts, dry runs, close ops), the
Linear-safe transcoding, the team/state/label caching, and the import-direction discipline.
"""

import dataclasses
from pathlib import Path
from typing import cast

import pytest

from perk import github, objective, plan
from perk.backends import engagement, issue_backend, linear_backend, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import LinearClient, LinearGraphQLError
from perk.backends.linear_backend import (
    LinearIssueBackend,
    LinearObjectiveStore,
    to_linear_markdown,
)
from perk.backends.objective_store import ObjectiveStoreError
from perk.github import GitHubError
from perk.run import run_report

_TEAM_RESPONSE: dict[str, object] = {"teams": {"nodes": [{"id": "team-1"}]}}
_STATES_RESPONSE: dict[str, object] = {
    "team": {
        "states": {
            "nodes": [
                {"id": "state-later", "name": "Archived", "type": "completed", "position": 9},
                {"id": "state-done", "name": "Done", "type": "completed", "position": 3},
                {"id": "state-todo", "name": "Todo", "type": "unstarted", "position": 1},
            ]
        }
    }
}
_LABEL_FOUND: dict[str, object] = {"issueLabels": {"nodes": [{"id": "lbl-1"}]}}
_LABEL_ABSENT: dict[str, object] = {"issueLabels": {"nodes": []}}


def _page(nodes: list[dict[str, object]], *, has_next: bool = False, cursor: str | None = None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}


def _no_issues() -> dict[str, object]:
    return {"issues": _page([])}


class _FakeLinear(LinearClient):
    """A scripted ``LinearClient`` subclass: records every ``(query, variables)`` pair; responses
    keyed by query-substring match in insertion order. A queue with >1 entries pops per call (the
    last entry is then reused); an ``Exception`` entry is raised. Subclasses ``LinearClient`` (no
    ``super().__init__``) so it INHERITS the real ``team_id``/``paginate`` machinery driven by this
    scripted ``request`` — the team cache is initialized directly."""

    def __init__(self, responses: dict[str, list[object]] | None = None) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._responses = {key: list(queue) for key, queue in (responses or {}).items()}
        self._team_id_cache: dict[str, str] = {}
        # Pre-seeded so `viewer_id()` resolves without a scripted `viewer` arm on every
        # issue/project create (the request path is covered by `test_linear.py` against a
        # MockTransport and by the stateful `FakeLinearWorkspace`). `assigneeId`/`leadId`
        # assertions use this sentinel.
        self._viewer_id_cache: str | None = "viewer-1"

    def request(self, query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((query, variables or {}))
        for needle, queue in self._responses.items():
            if needle in query:
                value = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(value, Exception):
                    raise value
                assert isinstance(value, dict)
                return cast("dict[str, object]", value)
        raise AssertionError(f"unscripted Linear query: {query}")


def _make_backend(
    responses: dict[str, list[object]] | None = None,
) -> tuple[issue_backend.IssueBackend, _FakeLinear]:
    """The static conformance check: ty verifies the backend satisfies the protocol."""
    fake = _FakeLinear(responses)
    backend: issue_backend.IssueBackend = LinearIssueBackend(
        fake, team_key="ENG", repo_root=Path("/repo")
    )
    return backend, fake


def _make_store(
    responses: dict[str, list[object]] | None = None,
) -> tuple[objective_store.ObjectiveStore, _FakeLinear]:
    """The objective-tier twin of ``_make_backend``: ty verifies ``LinearObjectiveStore`` satisfies
    the ``ObjectiveStore`` protocol."""
    fake = _FakeLinear(responses)
    store: objective_store.ObjectiveStore = LinearObjectiveStore(
        fake, team_key="ENG", repo_root=Path("/repo")
    )
    return store, fake


def _queries(fake: _FakeLinear, needle: str) -> list[tuple[str, dict[str, object]]]:
    return [(q, v) for q, v in fake.requests if needle in q]


def _input_payload(variables: dict[str, object]) -> dict[str, object]:
    payload = variables["input"]
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _inline_plan_description(run_id: str) -> str:
    return plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, {"run_id": run_id, "created": "t"}, style="inline-code"
    )


class TestConformance:
    def test_annotated_binding_and_backend_id(self) -> None:
        backend, _ = _make_backend()
        assert backend.backend_id == "linear"


class TestTranscoder:
    def test_html_markers_become_inline_code_sentinels(self) -> None:
        text = (
            "<!-- perk:metadata-block:plan-header -->\nx\n<!-- /perk:metadata-block:plan-header -->"
        )
        out = to_linear_markdown(text)
        assert out == "`perk:metadata-block:plan-header`\nx\n`/perk:metadata-block:plan-header`"

    def test_details_wrapper_lines_dropped(self) -> None:
        rendered = plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "01A"})
        out = to_linear_markdown(rendered)
        assert "<details>" not in out and "</details>" not in out and "<!--" not in out
        # The transcoded block matches the inline-code render exactly.
        assert out == plan.render_metadata_block(
            plan.PLAN_HEADER_KEY, {"run_id": "01A"}, style="inline-code"
        )

    def test_transcoded_plan_body_round_trips(self) -> None:
        comment = plan.render_plan_body("# Plan\n\nbody text\n")
        assert plan.extract_plan_body(to_linear_markdown(comment)) == "# Plan\n\nbody text"

    def test_non_perk_text_is_identity(self) -> None:
        text = "plain prose\n<!-- some other comment -->\n`code`\n"
        assert to_linear_markdown(text) == text

    def test_run_report_marker_shape(self) -> None:
        marker = run_report.RUN_REPORT_MARKER.format(run_id="01RUN")
        assert to_linear_markdown(marker) == "`perk:run-report:01RUN`"


class TestTeamStateLabelCaching:
    def test_team_id_resolves_once_across_calls(self) -> None:
        backend, fake = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]}
        )
        backend.find_plan_issue(run_id="01A")
        backend.find_plan_issue(run_id="01B")
        assert len(_queries(fake, "teams(filter")) == 1

    def test_unknown_team_raises_with_key(self) -> None:
        backend, _ = _make_backend({"teams(filter": [{"teams": {"nodes": []}}]})
        with pytest.raises(IssueBackendError, match="'ENG' not found"):
            backend.find_plan_issue(run_id="01A")

    def test_done_state_picks_lowest_position_completed(self) -> None:
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [_STATES_RESPONSE],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        assert backend.close_issue(issue_id="ENG-1") is True
        [(_, variables)] = _queries(fake, "issueUpdate(")
        assert variables["input"] == {"stateId": "state-done"}
        # the mutation carries the boundary identifier directly — no UUID resolution round-trip
        assert variables["id"] == "ENG-1"
        assert not _queries(fake, "UuidForIssue")
        # cached: a second close re-uses both team and state ids
        backend.close_issue(issue_id="ENG-2")
        assert len(_queries(fake, "team(id")) == 1

    def test_no_completed_state_raises(self) -> None:
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [{"team": {"states": {"nodes": []}}}],
            }
        )
        with pytest.raises(IssueBackendError, match="no completed-type workflow state"):
            backend.close_issue(issue_id="iss-1")


class TestEnsureLabel:
    def test_existing_label_is_not_recreated(self) -> None:
        backend, fake = _make_backend({"issueLabels(filter": [_LABEL_FOUND]})
        label = backend.ensure_label("perk:plan", color="1f883d", description="d")
        assert label == issue_backend.Label(name="perk:plan", created=False)
        assert not _queries(fake, "issueLabelCreate(")

    def test_absent_label_created_workspace_scoped_with_hash_color(self) -> None:
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_ABSENT],
                "issueLabelCreate(": [
                    {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-9"}}}
                ],
            }
        )
        label = backend.ensure_label("perk:plan", color="1f883d", description="d")
        assert label == issue_backend.Label(name="perk:plan", created=True)
        [(_, variables)] = _queries(fake, "issueLabelCreate(")
        # Workspace-scoped: NO teamId (perk's labels are conceptually workspace-wide).
        assert variables["input"] == {
            "name": "perk:plan",
            "color": "#1f883d",
            "description": "d",
        }

    def test_duplicate_create_race_relooks_up(self) -> None:
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_ABSENT, _LABEL_FOUND],
                "issueLabelCreate(": [
                    LinearGraphQLError("Linear GraphQL error: duplicate label name", codes=())
                ],
            }
        )
        label = backend.ensure_label("perk:plan", color="1f883d", description="d")
        assert label == issue_backend.Label(name="perk:plan", created=False)

    def test_dry_run_issues_no_requests(self) -> None:
        backend, fake = _make_backend()
        label = backend.ensure_label("perk:plan", color="1f883d", description="d", dry_run=True)
        assert label == issue_backend.Label(name="perk:plan", created=False)
        assert fake.requests == []


class TestFindAndCreatePlan:
    def test_find_matches_inline_encoded_description_across_pages(self) -> None:
        page1 = {
            "issues": _page(
                [
                    {
                        "id": "iss-a",
                        "identifier": "ENG-1",
                        "url": "u-a",
                        "description": _inline_plan_description("01OTHER"),
                    }
                ],
                has_next=True,
                cursor="C1",
            )
        }
        page2 = {
            "issues": _page(
                [
                    {
                        "id": "iss-b",
                        "identifier": "ENG-2",
                        "url": "u-b",
                        "description": _inline_plan_description("01HIT"),
                    }
                ]
            )
        }
        backend, fake = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [page1, page2]}
        )
        found = backend.find_plan_issue(run_id="01HIT")
        assert found == issue_backend.IssueRef(id="ENG-2", url="u-b", existed=True)
        pages = _queries(fake, "issues(first")
        assert len(pages) == 2
        query, variables = pages[0]
        assert variables["teamId"] == "team-1"
        assert variables["label"] == "perk:plan"
        assert variables["cursor"] is None
        assert pages[1][1]["cursor"] == "C1"
        assert 'nin: ["completed", "canceled"]' in query

    def test_find_matches_a_github_html_encoded_description_too(self) -> None:
        description = plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "01HTML"})
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "issues": _page(
                            [
                                {
                                    "id": "iss-h",
                                    "identifier": "ENG-3",
                                    "url": "u-h",
                                    "description": description,
                                }
                            ]
                        )
                    }
                ],
            }
        )
        found = backend.find_plan_issue(run_id="01HTML")
        assert found is not None and found.id == "ENG-3"

    def test_find_no_match_is_none_and_failure_raises(self) -> None:
        backend, _ = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]}
        )
        assert backend.find_plan_issue(run_id="01NOPE") is None
        failing, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [LinearGraphQLError("Linear GraphQL error: boom", codes=())],
            }
        )
        with pytest.raises(IssueBackendError, match="boom"):
            failing.find_plan_issue(run_id="01NOPE")

    def test_create_is_find_first_idempotent(self) -> None:
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "issues": _page(
                            [
                                {
                                    "id": "iss-x",
                                    "identifier": "ENG-4",
                                    "url": "u-x",
                                    "description": _inline_plan_description("01DUP"),
                                }
                            ]
                        )
                    }
                ],
            }
        )
        ref = backend.create_plan_issue(title="t", body="b", run_id="01DUP")
        assert ref == issue_backend.IssueRef(id="ENG-4", url="u-x", existed=True)
        assert not _queries(fake, "issueCreate(")

    def test_create_dry_run_shape(self) -> None:
        backend, fake = _make_backend()
        ref = backend.create_plan_issue(title="t", body="b", run_id="01DRY", dry_run=True)
        assert ref == issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        assert fake.requests == []

    def test_create_transcodes_the_github_encoded_body(self) -> None:
        github_body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "01NEW"})
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [_no_issues()],
                "issueLabels(filter": [_LABEL_FOUND],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "iss-n", "identifier": "ENG-5", "url": "u-n"},
                        }
                    }
                ],
            }
        )
        ref = backend.create_plan_issue(title="t", body=github_body, run_id="01NEW")
        assert ref == issue_backend.IssueRef(id="ENG-5", url="u-n", existed=False)
        [(_, variables)] = _queries(fake, "issueCreate(")
        input_payload = _input_payload(variables)
        description = input_payload["description"]
        assert isinstance(description, str)
        assert "`perk:metadata-block:plan-header`" in description
        assert "<!--" not in description and "<details>" not in description
        assert input_payload["teamId"] == "team-1"
        assert input_payload["labelIds"] == ["lbl-1"]


class TestLearnTwins:
    def test_find_learn_issue_is_header_and_label_scoped(self) -> None:
        # A plan issue sharing the run_id (plan-header, not learn-header) never matches.
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "issues": _page(
                            [
                                {
                                    "id": "iss-plan",
                                    "identifier": "ENG-6",
                                    "url": "u",
                                    "description": _inline_plan_description("01RUN"),
                                }
                            ]
                        )
                    }
                ],
            }
        )
        assert backend.find_learn_issue(run_id="01RUN") is None
        [(_, variables)] = _queries(fake, "issues(first")
        assert variables["label"] == "perk:learn"

    def test_create_learn_issue_renders_inline_header_with_verbatim_plan_id(self) -> None:
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [_no_issues()],
                "issueLabels(filter": [_LABEL_FOUND],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "iss-l", "identifier": "ENG-7", "url": "u-l"},
                        }
                    }
                ],
            }
        )
        ref = backend.create_learn_issue(
            title="t", body="learnings", run_id="01LEARN", plan_id="ENG-1"
        )
        assert ref.existed is False and ref.id == "ENG-7"
        [(_, variables)] = _queries(fake, "issueCreate(")
        input_payload = _input_payload(variables)
        description = input_payload["description"]
        assert isinstance(description, str)
        assert "`perk:metadata-block:learn-header`" in description
        header = plan.find_metadata_block(description, plan.LEARN_HEADER_KEY)
        assert header is not None
        assert header["run_id"] == "01LEARN"
        assert header["plan"] == "ENG-1"  # the boundary string, verbatim
        assert description.endswith("learnings\n")

    def test_create_learn_issue_is_idempotent_via_find(self) -> None:
        learn_description = plan.render_metadata_block(
            plan.LEARN_HEADER_KEY, {"run_id": "01LEARN"}, style="inline-code"
        )
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "issues": _page(
                            [
                                {
                                    "id": "iss-l",
                                    "identifier": "ENG-7",
                                    "url": "u-l",
                                    "description": learn_description,
                                }
                            ]
                        )
                    }
                ],
            }
        )
        ref = backend.create_learn_issue(title="t", body="b", run_id="01LEARN", plan_id="ENG-1")
        assert ref == issue_backend.IssueRef(id="ENG-7", url="u-l", existed=True)
        assert not _queries(fake, "issueCreate(")

    def test_list_learn_issues_maps_fields_and_raises_on_failure(self) -> None:
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "issues": _page(
                            [
                                {
                                    "id": "iss-1",
                                    "identifier": "ENG-8",
                                    "title": "T",
                                    "url": "u",
                                    "description": "body",
                                }
                            ]
                        )
                    }
                ],
            }
        )
        summaries = backend.list_learn_issues()
        assert summaries == (
            issue_backend.LearnIssueSummary(id="ENG-8", title="T", url="u", body="body"),
        )
        [(_, variables)] = _queries(fake, "issues(first")
        assert variables["label"] == "perk:learn"
        failing, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [LinearGraphQLError("Linear GraphQL error: down", codes=())],
            }
        )
        with pytest.raises(IssueBackendError, match="down"):
            failing.list_learn_issues()


def _comments_response(comments: list[dict[str, object]]) -> dict[str, object]:
    return {"issue": {"comments": _page(comments)}}


class TestPlanUpserts:
    def test_update_plan_issue_patches_the_existing_plan_body_comment(self) -> None:
        existing = to_linear_markdown(plan.render_plan_body("# Old plan"))
        backend, fake = _make_backend(
            {
                "comments(first": [
                    _comments_response(
                        [
                            {"id": "c-1", "body": "unrelated", "createdAt": "2026-01-01"},
                            {"id": "c-2", "body": existing, "createdAt": "2026-01-02"},
                        ]
                    )
                ],
                "commentUpdate(": [{"commentUpdate": {"success": True}}],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        update = backend.update_plan_issue(
            issue_id="iss-1", title="t2", body_comment=plan.render_plan_body("# New plan")
        )
        assert update == issue_backend.PlanUpdate(
            issue_id="iss-1", body_updated=True, title_updated=True, dry_run=False
        )
        [(_, patch_vars)] = _queries(fake, "commentUpdate(")
        assert patch_vars["id"] == "c-2"
        patch_input = _input_payload(patch_vars)
        body = patch_input["body"]
        assert isinstance(body, str) and "<!--" not in body and "# New plan" in body
        [(_, title_vars)] = _queries(fake, "issueUpdate(")
        assert title_vars["input"] == {"title": "t2"}
        assert title_vars["id"] == "iss-1"  # the boundary identifier is sent directly
        assert not _queries(fake, "UuidForIssue")

    def test_update_plan_issue_posts_fresh_on_a_legacy_issue(self) -> None:
        backend, fake = _make_backend(
            {
                "comments(first": [_comments_response([])],
                "commentCreate(": [{"commentCreate": {"success": True}}],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        update = backend.update_plan_issue(issue_id="iss-1", title="t", body_comment="body")
        assert update.body_updated is False and update.title_updated is True
        assert len(_queries(fake, "commentCreate(")) == 1

    def test_update_plan_issue_dry_run_shape(self) -> None:
        backend, fake = _make_backend()
        update = backend.update_plan_issue(
            issue_id="iss-1", title="t", body_comment="b", dry_run=True
        )
        assert update == issue_backend.PlanUpdate(
            issue_id="iss-1", body_updated=False, title_updated=False, dry_run=True
        )
        assert fake.requests == []

    def test_update_plan_header_rejects_unknown_fields(self) -> None:
        backend, fake = _make_backend()
        with pytest.raises(IssueBackendError, match="unknown plan-header field"):
            backend.update_plan_header(issue_id="iss-1", fields={"nope": 1})
        assert fake.requests == []

    def test_update_plan_header_merges_form_preserving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        description = _inline_plan_description("01HDR")
        backend, fake = _make_backend(
            {
                "issue(id": [{"issue": {"id": "iss-1", "description": description}}],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        # No PR resolves → no attachment attempt (the attachment path is its own test).
        monkeypatch.setattr(github, "get_pr", lambda **k: None)
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"})
        assert update == issue_backend.PlanHeaderUpdate(fields_updated=("pr",), dry_run=False)
        [(_, variables)] = _queries(fake, "issueUpdate(")
        update_input = _input_payload(variables)
        new_description = update_input["description"]
        assert isinstance(new_description, str)
        assert "<!--" not in new_description and "<details>" not in new_description
        header = plan.find_metadata_block(new_description, plan.PLAN_HEADER_KEY)
        assert header is not None and header["pr"] == "12" and header["run_id"] == "01HDR"

    def test_update_plan_header_posts_pr_attachment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend, fake = _make_backend(
            {
                "issue(id": [
                    {"issue": {"id": "iss-1", "description": _inline_plan_description("01H")}}
                ],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "attachmentCreate(": [{"attachmentCreate": {"success": True}}],
            }
        )
        monkeypatch.setattr(
            github,
            "get_pr",
            lambda **k: github.PullRequest(
                number=12,
                url="https://github.com/o/r/pull/12",
                state="OPEN",
                is_draft=True,
                existed=True,
            ),
        )
        backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"})
        [(_, variables)] = _queries(fake, "attachmentCreate(")
        payload = _input_payload(variables)
        assert payload["issueId"] == "iss-1"
        assert payload["url"] == "https://github.com/o/r/pull/12"
        assert payload["title"] == "GitHub PR #12"
        assert payload["subtitle"] == "OPEN"

    def test_update_plan_header_attachment_is_fail_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The PR lookup raising must NOT fail the header stamp (attachment is bookkeeping).
        backend, fake = _make_backend(
            {
                "issue(id": [
                    {"issue": {"id": "iss-1", "description": _inline_plan_description("01H")}}
                ],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        monkeypatch.setattr(
            github, "get_pr", lambda **k: (_ for _ in ()).throw(GitHubError("gh exploded"))
        )
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"})
        assert update.dry_run is False  # the header write committed
        assert not _queries(fake, "attachmentCreate(")  # no attachment posted

    def test_update_plan_header_no_pr_posts_no_attachment(self) -> None:
        backend, fake = _make_backend(
            {
                "issue(id": [
                    {"issue": {"id": "iss-1", "description": _inline_plan_description("01H")}}
                ],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        backend.update_plan_header(issue_id="iss-1", fields={"branch": "plan-ENG-1"})
        assert not _queries(fake, "attachmentCreate(")

    def test_update_plan_header_dry_run_composes_only(self) -> None:
        backend, fake = _make_backend(
            {
                "issue(id": [
                    {"issue": {"id": "iss-1", "description": _inline_plan_description("01HDR")}}
                ],
            }
        )
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"}, dry_run=True)
        assert update.dry_run is True
        assert not _queries(fake, "issueUpdate(")


def _not_found_error() -> LinearGraphQLError:
    return LinearGraphQLError(
        "Linear GraphQL error: Entity not found: Issue", codes=("INPUT_ERROR",)
    )


class TestGetPlan:
    def test_entity_not_found_is_none(self) -> None:
        backend, _ = _make_backend({"issue(id": [_not_found_error()]})
        assert backend.get_plan(issue_id="iss-gone") is None

    def test_other_graphql_errors_reraise(self) -> None:
        backend, _ = _make_backend(
            {"issue(id": [LinearGraphQLError("Linear GraphQL error: rate limited", codes=())]}
        )
        with pytest.raises(IssueBackendError, match="rate limited"):
            backend.get_plan(issue_id="iss-1")

    @pytest.mark.parametrize(
        ("state_type", "expected"),
        [("completed", "CLOSED"), ("canceled", "CLOSED"), ("backlog", "OPEN"), ("started", "OPEN")],
    )
    def test_state_mapping(self, state_type: str, expected: str) -> None:
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-1",
                            "url": "u",
                            "title": "T",
                            "description": _inline_plan_description("01S"),
                            "state": {"type": state_type},
                        }
                    }
                ]
            }
        )
        state = backend.get_plan(issue_id="ENG-1")
        assert state is not None
        assert state.id == "ENG-1"  # the boundary id is the human identifier
        assert state.state == expected
        assert state.pr is None
        assert state.header["run_id"] == "01S"

    def test_pr_header_field_resolves_via_late_bound_github(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        description = plan.render_metadata_block(
            plan.PLAN_HEADER_KEY, {"run_id": "01P", "pr": "12"}, style="inline-code"
        )
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-1",
                            "url": "u",
                            "title": "T",
                            "description": description,
                            "state": {"type": "started"},
                        }
                    }
                ]
            }
        )
        sentinel = github.PullRequest(
            number=12, url="pr-u", state="OPEN", is_draft=False, existed=True
        )
        calls: list[tuple[int, Path]] = []

        def fake_get_pr(*, number: int, repo_root: Path) -> github.PullRequest:
            calls.append((number, repo_root))
            return sentinel

        # Late-bound: the patch lands AFTER backend construction and still intercepts.
        monkeypatch.setattr(github, "get_pr", fake_get_pr)
        state = backend.get_plan(issue_id="iss-1")
        assert state is not None and state.pr is sentinel
        assert calls == [(12, Path("/repo"))]

    def test_github_error_in_pr_resolution_maps_to_issue_backend_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        description = plan.render_metadata_block(
            plan.PLAN_HEADER_KEY, {"run_id": "01P", "pr": "12"}, style="inline-code"
        )
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-1",
                            "url": "u",
                            "title": "T",
                            "description": description,
                            "state": {"type": "started"},
                        }
                    }
                ]
            }
        )

        def boom(*, number: int, repo_root: Path) -> github.PullRequest:
            raise GitHubError("gh exploded")

        monkeypatch.setattr(github, "get_pr", boom)
        with pytest.raises(IssueBackendError, match="gh exploded"):
            backend.get_plan(issue_id="iss-1")


class TestGetPlanBody:
    def test_found_in_the_description(self) -> None:
        description = plan.render_plan_body("# The plan", style="inline-code")
        backend, _ = _make_backend(
            {
                "comments(first": [_comments_response([])],
                "issue(id": [{"issue": {"id": "iss-1", "description": description}}],
            }
        )
        assert backend.get_plan_body(issue_id="iss-1") == "# The plan"

    def test_found_in_a_comment(self) -> None:
        comment_body = to_linear_markdown(plan.render_plan_body("# Comment plan"))
        backend, _ = _make_backend(
            {
                "comments(first": [
                    _comments_response([{"id": "c-1", "body": comment_body, "createdAt": "t"}])
                ],
                "issue(id": [{"issue": {"id": "iss-1", "description": "header only"}}],
            }
        )
        assert backend.get_plan_body(issue_id="iss-1") == "# Comment plan"

    def test_absent_issue_or_block_is_none(self) -> None:
        backend, _ = _make_backend({"issue(id": [_not_found_error()]})
        assert backend.get_plan_body(issue_id="iss-gone") is None
        empty, _ = _make_backend(
            {
                "comments(first": [_comments_response([])],
                "issue(id": [{"issue": {"id": "iss-1", "description": "no block"}}],
            }
        )
        assert empty.get_plan_body(issue_id="iss-1") is None


class TestReadIssueAndAdopt:
    """In-place issue adoption (#706, §8.29) on the Linear backend."""

    def test_read_issue_maps_neutral_shape(self) -> None:
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-7",
                            "url": "u/ENG-7",
                            "title": "Human title",
                            "description": "do the thing",
                            "state": {"type": "started"},
                        }
                    }
                ]
            }
        )
        src = backend.read_issue(issue_id="ENG-7")
        assert src == issue_backend.AdoptableIssue(
            id="ENG-7", url="u/ENG-7", title="Human title", body="do the thing", state="OPEN"
        )

    def test_read_issue_none_when_missing(self) -> None:
        backend, _ = _make_backend({"issue(id": [_not_found_error()]})
        assert backend.read_issue(issue_id="iss-gone") is None

    def test_read_issue_normalizes_closed(self) -> None:
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-7",
                            "url": "u",
                            "title": "t",
                            "description": "b",
                            "state": {"type": "canceled"},
                        }
                    }
                ]
            }
        )
        src = backend.read_issue(issue_id="ENG-7")
        assert src is not None and src.state == "CLOSED"

    def test_adopt_issue_as_plan_stamps_in_place(self) -> None:
        backend, fake = _make_backend(
            {
                "issueLabels(filter": [{"issueLabels": {"nodes": [{"id": "lbl-plan"}]}}],
                "comments(first": [_comments_response([])],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "commentCreate(": [{"commentCreate": {"success": True}}],
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-7",
                            "url": "u/ENG-7",
                            "description": "HUMAN BODY VERBATIM",
                            "labels": {"nodes": [{"id": "lbl-existing"}]},
                        }
                    }
                ],
            }
        )
        header_fields = plan.PlanHeader(run_id="RID", created="t", adopted_from="ENG-7").to_data()
        ref = backend.adopt_issue_as_plan(
            issue_id="ENG-7",
            header_fields=header_fields,
            plan_markdown="# Adopted\n\nthe plan body\n",
            callout=plan.plan_callout("ENG-7"),
            command="perk impl ENG-7",
        )
        assert ref == issue_backend.IssueRef(id="ENG-7", url="u/ENG-7", existed=True)
        updates = [_input_payload(v) for _, v in _queries(fake, "issueUpdate(")]
        # The label add is additive: the existing label id is preserved, the plan label unioned.
        label_update = next(u for u in updates if "labelIds" in u)
        assert set(cast("list[str]", label_update["labelIds"])) == {"lbl-existing", "lbl-plan"}
        # The description stamp is inline-code (Linear-safe), preserves the human body, carries the
        # callout + the adopted_from provenance; the title is never touched.
        desc_update = next(u for u in updates if "description" in u)
        new_desc = cast("str", desc_update["description"])
        assert "HUMAN BODY VERBATIM" in new_desc
        assert "perk impl ENG-7" in new_desc
        assert "<!--" not in new_desc  # inline-code, not lossy HTML
        stamped = plan.find_metadata_block(new_desc, plan.PLAN_HEADER_KEY)
        assert stamped is not None and stamped["adopted_from"] == "ENG-7"
        assert "title" not in desc_update and "title" not in label_update
        # The plan body is upserted as an inline-code comment.
        [(_, create_vars)] = _queries(fake, "commentCreate(")
        comment_body = cast("str", _input_payload(create_vars)["body"])
        assert plan.extract_plan_body(comment_body) is not None


class TestCommentOps:
    def test_find_comment_id_by_marker_matches_transcoded_marker_oldest_first(self) -> None:
        marker = run_report.RUN_REPORT_MARKER.format(run_id="01R")
        needle = to_linear_markdown(marker)
        # Deliberately out of createdAt order — pins the client-side ascending sort.
        backend, _ = _make_backend(
            {
                "comments(first": [
                    _comments_response(
                        [
                            {"id": "c-new", "body": f"{needle}\nnewer", "createdAt": "2026-02-02"},
                            {"id": "c-old", "body": f"{needle}\nolder", "createdAt": "2026-01-01"},
                        ]
                    )
                ]
            }
        )
        assert backend.find_comment_id_by_marker(issue_id="iss-1", marker=marker) == "c-old"

    def test_find_comment_id_no_match_is_none(self) -> None:
        backend, _ = _make_backend(
            {
                "comments(first": [
                    _comments_response([{"id": "c-1", "body": "nope", "createdAt": "t"}])
                ]
            }
        )
        assert backend.find_comment_id_by_marker(issue_id="iss-1", marker="<!-- perk:x -->") is None

    def test_upsert_marked_comment_posts_then_patches(self) -> None:
        marker = run_report.RUN_REPORT_MARKER.format(run_id="01R")
        posted, post_fake = _make_backend(
            {
                "comments(first": [_comments_response([])],
                "commentCreate(": [{"commentCreate": {"success": True}}],
            }
        )
        result = posted.upsert_marked_comment(
            issue_id="iss-1", marker=marker, body=f"{marker}\nstarted"
        )
        assert result == issue_backend.CommentResult(posted=True)
        [(_, create_vars)] = _queries(post_fake, "commentCreate(")
        create_input = _input_payload(create_vars)
        body = create_input["body"]
        # the marker is embedded TRANSCODED, so the next upsert's find matches it
        assert isinstance(body, str) and to_linear_markdown(marker) in body and "<!--" not in body

        patched, patch_fake = _make_backend(
            {
                "comments(first": [
                    _comments_response(
                        [
                            {
                                "id": "c-1",
                                "body": f"{to_linear_markdown(marker)}\nstarted",
                                "createdAt": "t",
                            }
                        ]
                    )
                ],
                "commentUpdate(": [{"commentUpdate": {"success": True}}],
            }
        )
        result = patched.upsert_marked_comment(
            issue_id="iss-1", marker=marker, body=f"{marker}\ndone"
        )
        assert result == issue_backend.CommentResult(posted=True)
        [(_, patch_vars)] = _queries(patch_fake, "commentUpdate(")
        assert patch_vars["id"] == "c-1"
        assert not _queries(patch_fake, "commentCreate(")

    def test_upsert_and_add_comment_dry_runs(self) -> None:
        backend, fake = _make_backend()
        assert backend.upsert_marked_comment(
            issue_id="iss-1", marker="m", body="m", dry_run=True
        ) == issue_backend.CommentResult(posted=False)
        assert backend.add_issue_comment(
            issue_id="iss-1", body="b", dry_run=True
        ) == issue_backend.CommentResult(posted=False)
        assert fake.requests == []

    def test_add_issue_comment_transcodes(self) -> None:
        backend, fake = _make_backend(
            {
                "commentCreate(": [{"commentCreate": {"success": True}}],
            }
        )
        result = backend.add_issue_comment(issue_id="ENG-1", body="<!-- perk:run-report:X -->\nhi")
        assert result == issue_backend.CommentResult(posted=True)
        [(_, variables)] = _queries(fake, "commentCreate(")
        create_input = _input_payload(variables)
        assert create_input["body"] == "`perk:run-report:X`\nhi"
        assert create_input["issueId"] == "ENG-1"  # the boundary identifier is sent directly
        assert not _queries(fake, "UuidForIssue")


class TestCloseOps:
    def test_close_issue_dry_run_returns_false_with_no_requests(self) -> None:
        backend, fake = _make_backend()
        assert backend.close_issue(issue_id="iss-1", dry_run=True) is False
        assert fake.requests == []

    def test_close_issue_is_fail_loud(self) -> None:
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [_STATES_RESPONSE],
                "issueUpdate(": [{"issueUpdate": {"success": False}}],
            }
        )
        with pytest.raises(IssueBackendError, match="failed to close"):
            backend.close_issue(issue_id="iss-1")

    def test_close_and_label_consolidated_dry_run(self) -> None:
        backend, fake = _make_backend()
        assert backend.close_and_label_consolidated(issue_id="iss-1", dry_run=True) is True
        assert fake.requests == []

    def test_close_and_label_consolidated_labels_additively_then_closes(self) -> None:
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [_STATES_RESPONSE],
                "issueLabels(filter": [{"issueLabels": {"nodes": [{"id": "lbl-cons"}]}}],
                "issue(id": [{"issue": {"id": "iss-1", "labels": {"nodes": [{"id": "lbl-a"}]}}}],
                "issueUpdate(": [
                    {"issueUpdate": {"success": True}},
                    {"issueUpdate": {"success": True}},
                ],
            }
        )
        assert backend.close_and_label_consolidated(issue_id="iss-1") is True
        updates = _queries(fake, "issueUpdate(")
        assert len(updates) == 2
        assert updates[0][1]["input"] == {"labelIds": ["lbl-a", "lbl-cons"]}
        assert updates[1][1]["input"] == {"stateId": "state-done"}


class TestReadComments:
    def test_maps_authors_and_edited_at(self) -> None:
        backend, _ = _make_backend(
            {
                "botActor": [
                    {
                        "issue": {
                            "comments": _page(
                                [
                                    {
                                        "id": "c-2",
                                        "body": "please rebase",
                                        "createdAt": "2026-01-02",
                                        "editedAt": "2026-01-03",
                                        "user": {
                                            "id": "u-1",
                                            "name": "ada",
                                            "displayName": "Ada L",
                                        },
                                        "botActor": None,
                                    },
                                    {
                                        "id": "c-1",
                                        "body": "`perk:metadata-block:plan-body`",
                                        "createdAt": "2026-01-01",
                                        "editedAt": None,
                                        "user": None,
                                        "botActor": {
                                            "id": "bot-x",
                                            "name": "perk",
                                            "type": "app",
                                        },
                                    },
                                ]
                            )
                        }
                    }
                ],
            }
        )
        comments = backend.read_comments(issue_id="ENG-1")
        # Oldest-first (c-1 createdAt < c-2), independent of payload order.
        assert [c.id for c in comments] == ["c-1", "c-2"]
        # c-1 carries a perk sentinel in its body → perk.
        assert comments[0].author.kind == "perk"
        assert comments[0].body == "`perk:metadata-block:plan-body`"
        assert comments[0].edited_at is None
        # c-2 is a human (user, no botActor); displayName preferred; editedAt mapped.
        assert comments[1].author.kind == "human"
        assert comments[1].author.display_name == "Ada L"
        assert comments[1].edited_at == "2026-01-03"

    def test_empty_issue_yields_empty_tuple(self) -> None:
        backend, _ = _make_backend({"botActor": [{"issue": {"comments": _page([])}}]})
        assert backend.read_comments(issue_id="ENG-1") == ()


class TestReadDescriptionEdits:
    def test_filters_to_description_updates_and_maps(self) -> None:
        backend, _ = _make_backend(
            {
                "descriptionUpdatedBy": [
                    {
                        "issue": {
                            "history": _page(
                                [
                                    {
                                        "id": "h-2",
                                        "createdAt": "2026-02-02",
                                        "actor": {"id": "u-1", "name": "Ada"},
                                        "descriptionUpdatedBy": {"id": "u-1", "name": "Ada"},
                                    },
                                    {
                                        "id": "h-1",
                                        "createdAt": "2026-02-01",
                                        "actor": {"id": "u-1", "name": "Ada"},
                                        # A non-description history event (state change etc.):
                                        # no descriptionUpdatedBy → filtered out.
                                        "descriptionUpdatedBy": None,
                                    },
                                ]
                            )
                        }
                    }
                ],
            }
        )
        edits = backend.read_description_edits(issue_id="ENG-1")
        assert len(edits) == 1
        assert edits[0].created_at == "2026-02-02"
        assert edits[0].author.kind == "human"
        assert edits[0].author.display_name == "Ada"
        assert edits[0].diff is None  # Linear history exposes no inline diff (flagged)

    def test_missing_issue_yields_empty(self) -> None:
        backend, _ = _make_backend(
            {
                "descriptionUpdatedBy": [
                    LinearGraphQLError("Entity not found: Issue", codes=("INPUT_ERROR",))
                ]
            }
        )
        assert backend.read_description_edits(issue_id="ENG-404") == ()


class TestReadAgentSession:
    def test_maps_activities_and_derives_stop_signal(self) -> None:
        backend, _ = _make_backend(
            {
                "agentSessions(first": [
                    {"issue": {"agentSessions": {"nodes": [{"id": "sess-1"}]}}}
                ],
                "agentSession(id": [
                    {
                        "agentSession": {
                            "activities": _page(
                                [
                                    {
                                        "id": "a-1",
                                        "createdAt": "2026-03-01",
                                        "signal": None,
                                        "content": {
                                            "__typename": "AgentActivityPromptContent",
                                            "body": "do the thing",
                                        },
                                    },
                                    {
                                        "id": "a-2",
                                        "createdAt": "2026-03-02",
                                        "signal": "stop",
                                        "content": {
                                            "__typename": "AgentActivityPromptContent",
                                            "body": "stop now",
                                        },
                                    },
                                ]
                            )
                        }
                    }
                ],
            }
        )
        session = backend.read_agent_session(issue_id="ENG-1")
        assert [a.id for a in session.activities] == ["a-1", "a-2"]
        assert session.activities[0].kind == "AgentActivityPromptContent"
        assert session.activities[0].body == "do the thing"
        assert session.stop_signal.stopped is True
        assert session.stop_signal.at == "2026-03-02"

    def test_no_stop_signal_indicator_is_not_stopped(self) -> None:
        backend, _ = _make_backend(
            {
                "agentSessions(first": [
                    {"issue": {"agentSessions": {"nodes": [{"id": "sess-1"}]}}}
                ],
                "agentSession(id": [
                    {
                        "agentSession": {
                            "activities": _page(
                                [
                                    {
                                        "id": "a-1",
                                        "createdAt": "2026-03-01",
                                        "signal": None,
                                        "content": {
                                            "__typename": "AgentActivityThoughtContent",
                                            "body": "thinking",
                                        },
                                    }
                                ]
                            )
                        }
                    }
                ],
            }
        )
        session = backend.read_agent_session(issue_id="ENG-1")
        assert session.stop_signal.stopped is False
        assert session.stop_signal.at is None

    def test_missing_session_yields_empty(self) -> None:
        backend, _ = _make_backend(
            {"agentSessions(first": [{"issue": {"agentSessions": {"nodes": []}}}]}
        )
        session = backend.read_agent_session(issue_id="ENG-1")
        assert session.activities == ()
        assert session.stop_signal.stopped is False

    def test_auth_failure_raises(self) -> None:
        # The personal API key cannot read the session: a non-not-found GraphQL error propagates
        # (the contract — read_agent_session raises on infra/auth failure).
        backend, _ = _make_backend(
            {
                "agentSessions(first": [
                    LinearGraphQLError("access denied", codes=("AUTHENTICATION_ERROR",))
                ]
            }
        )
        with pytest.raises(IssueBackendError, match="access denied"):
            backend.read_agent_session(issue_id="ENG-1")


def _objective_nodes() -> list[objective.ObjectiveNode]:
    return [
        objective.ObjectiveNode(id="1.1", description="Alpha", status=objective.NodeStatus.DONE),
        objective.ObjectiveNode(id="1.2", description="Beta", status=objective.NodeStatus.PENDING),
    ]


def _inline_objective_description(
    run_id: str,
    *,
    comment_id: str | int | None = None,
    nodes: list[objective.ObjectiveNode] | None = None,
) -> str:
    header = objective.ObjectiveHeader(
        run_id=run_id, created="t", objective_comment_id=comment_id, status="active"
    )
    header_block = plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, header.to_data(), style="inline-code"
    )
    roadmap_block = plan.render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY,
        objective.render_roadmap_block(nodes if nodes is not None else _objective_nodes()),
        style="inline-code",
    )
    return f"{header_block}\n\n{roadmap_block}\n"


def _objective_issue_response(description: str) -> dict[str, object]:
    return {
        "issue": {
            "id": "obj-1",
            "identifier": "ENG-9",
            "url": "u-obj",
            "title": "Obj",
            "description": description,
        }
    }


_COMMENT_CREATED: dict[str, object] = {
    "commentCreate": {"success": True, "comment": {"id": "cmt-uuid-1"}}
}


class TestFindObjectiveIssue:
    def test_matches_inline_encoded_objective_header(self) -> None:
        description = _inline_objective_description("01OBJ")
        store, fake = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "issues": _page(
                            [
                                {
                                    "id": "obj-1",
                                    "identifier": "ENG-9",
                                    "url": "u",
                                    "description": description,
                                }
                            ]
                        )
                    }
                ],
            }
        )
        found = store.find_objective(run_id="01OBJ")
        assert found == objective_store.ObjectiveRef(id="ENG-9", url="u", existed=True)
        [(_, variables)] = _queries(fake, "issues(first")
        assert variables["label"] == "perk:objective"

    def test_no_match_is_none_after_exhausting_pages(self) -> None:
        page1 = {"issues": _page([], has_next=True, cursor="C1")}
        page2 = {"issues": _page([])}
        store, fake = _make_store(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [page1, page2]}
        )
        assert store.find_objective(run_id="01NOPE") is None
        assert len(_queries(fake, "issues(first")) == 2

    def test_infra_errors_propagate(self) -> None:
        store, _ = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [LinearGraphQLError("Linear GraphQL error: boom", codes=())],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="boom"):
            store.find_objective(run_id="01NOPE")


class TestCreateObjectiveIssue:
    def test_dry_run_shape(self) -> None:
        store, fake = _make_store()
        ref = store.create_objective(
            title="t", body="b", run_id="01DRY", roadmap_nodes=_objective_nodes(), dry_run=True
        )
        assert ref == objective_store.ObjectiveRef(id="0", url="(dry-run)", existed=False)
        assert fake.requests == []

    def test_idempotent_find_then_return(self) -> None:
        description = _inline_objective_description("01DUP")
        store, fake = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "issues": _page(
                            [
                                {
                                    "id": "obj-1",
                                    "identifier": "ENG-9",
                                    "url": "u",
                                    "description": description,
                                }
                            ]
                        )
                    }
                ],
            }
        )
        ref = store.create_objective(
            title="t", body="b", run_id="01DUP", roadmap_nodes=_objective_nodes()
        )
        assert ref == objective_store.ObjectiveRef(id="ENG-9", url="u", existed=True)
        assert not _queries(fake, "issueCreate(")

    def test_empty_roadmap_raises(self) -> None:
        store, _ = _make_store({"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]})
        with pytest.raises(ObjectiveStoreError, match="objective roadmap is empty"):
            store.create_objective(title="t", body="prose only", run_id="01EMPTY")

    def test_invalid_embedded_roadmap_raises(self) -> None:
        bad = plan.render_metadata_block(
            objective.OBJECTIVE_ROADMAP_KEY, {"schema_version": "99", "nodes": []}
        )
        store, _ = _make_store({"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]})
        with pytest.raises(ObjectiveStoreError, match="invalid objective roadmap"):
            store.create_objective(title="t", body=bad, run_id="01BAD")

    def test_full_two_step_create_with_comment_id_backfill(self) -> None:
        store, fake = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [_no_issues()],
                "issueLabels(filter": [_LABEL_FOUND],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "obj-1", "identifier": "ENG-9", "url": "u-obj"},
                        }
                    }
                ],
                "commentCreate(": [_COMMENT_CREATED],
                # the backfill's _get_issue read: returns the freshly created description
                "issue(id": [_objective_issue_response(_inline_objective_description("01NEW"))],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        ref = store.create_objective(
            title="t",
            body="The objective prose.",
            run_id="01NEW",
            roadmap_nodes=_objective_nodes(),
        )
        assert ref == objective_store.ObjectiveRef(id="ENG-9", url="u-obj", existed=False)

        # 1) the issue description is composed directly inline-code-encoded
        [(_, create_vars)] = _queries(fake, "issueCreate(")
        description = _input_payload(create_vars)["description"]
        assert isinstance(description, str)
        assert "`perk:metadata-block:objective-header`" in description
        assert "`perk:metadata-block:objective-roadmap`" in description
        assert "<!--" not in description and "<details>" not in description
        header = plan.find_metadata_block(description, objective.OBJECTIVE_HEADER_KEY)
        assert header is not None and header["run_id"] == "01NEW"
        assert header["objective_comment_id"] is None

        # 2) the body comment is posted transcoded (table + reconcilable sentinels)
        [(_, comment_vars)] = _queries(fake, "commentCreate(")
        comment_input = _input_payload(comment_vars)
        assert comment_input["issueId"] == "ENG-9"  # boundary identifier sent directly
        comment_body = comment_input["body"]
        assert isinstance(comment_body, str)
        assert "`perk:roadmap-table`" in comment_body
        assert "`perk:objective-reconcilable`" in comment_body
        assert "The objective prose." in comment_body
        assert "<!--" not in comment_body
        # leads with the copyable `perk objective plan <ENG-N>` callout, above the rendered table
        assert comment_body.startswith("**Plan the next node:**")
        assert "perk objective plan ENG-9" in comment_body
        assert comment_body.index("perk objective plan ENG-9") < comment_body.index(
            "`perk:roadmap-table`"
        )

        # 3) the captured comment UUID is backfilled into the header (form-preserving)
        [(_, update_vars)] = _queries(fake, "issueUpdate(")
        new_description = _input_payload(update_vars)["description"]
        assert isinstance(new_description, str)
        assert "<!--" not in new_description
        backfilled = plan.find_metadata_block(new_description, objective.OBJECTIVE_HEADER_KEY)
        assert backfilled is not None
        assert backfilled["objective_comment_id"] == "cmt-uuid-1"

    def test_create_persists_base_into_objective_header(self) -> None:
        # #633: the issue-backed store threads `base` into the composed inline-code
        # objective-header block; absent `base` leaves it null.
        store, fake = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [_no_issues()],
                "issueLabels(filter": [_LABEL_FOUND],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "obj-1", "identifier": "ENG-9", "url": "u-obj"},
                        }
                    }
                ],
                "commentCreate(": [_COMMENT_CREATED],
                "issue(id": [_objective_issue_response(_inline_objective_description("01NEW"))],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        store.create_objective(
            title="t",
            body="The objective prose.",
            run_id="01NEW",
            base="develop",
            roadmap_nodes=_objective_nodes(),
        )
        [(_, create_vars)] = _queries(fake, "issueCreate(")
        description = _input_payload(create_vars)["description"]
        assert isinstance(description, str)
        header = plan.find_metadata_block(description, objective.OBJECTIVE_HEADER_KEY)
        assert header is not None and header["base"] == "develop"


class TestGetObjective:
    def test_happy_path(self) -> None:
        description = _inline_objective_description("01OBJ", comment_id="cmt-1")
        store, _ = _make_store({"issue(id": [_objective_issue_response(description)]})
        state = store.get_objective(objective_id="ENG-9")
        assert state is not None
        assert state.id == "ENG-9" and state.url == "u-obj" and state.title == "Obj"
        assert state.header["run_id"] == "01OBJ"
        assert state.header["objective_comment_id"] == "cmt-1"
        assert [n.id for n in state.nodes] == ["1.1", "1.2"]

    def test_missing_issue_is_none(self) -> None:
        store, _ = _make_store({"issue(id": [_not_found_error()]})
        assert store.get_objective(objective_id="obj-gone") is None

    def test_invalid_roadmap_raises(self) -> None:
        broken = "`perk:metadata-block:objective-roadmap`\n\n```yaml\nnodes: [\n```"
        store, _ = _make_store({"issue(id": [_objective_issue_response(broken)]})
        with pytest.raises(ObjectiveStoreError, match="invalid objective roadmap on 'obj-1'"):
            store.get_objective(objective_id="obj-1")


class TestUpdateObjectiveHeader:
    def test_unknown_fields_rejected_lbyl(self) -> None:
        store, fake = _make_store()
        with pytest.raises(ObjectiveStoreError, match="unknown objective-header field"):
            store.update_objective_header(objective_id="obj-1", fields={"nope": 1})
        assert fake.requests == []

    def test_dry_run_composes_only(self) -> None:
        description = _inline_objective_description("01HDR")
        store, fake = _make_store({"issue(id": [_objective_issue_response(description)]})
        update = store.update_objective_header(
            objective_id="obj-1", fields={"status": "complete"}, dry_run=True
        )
        assert update == objective_store.ObjectiveHeaderUpdate(
            fields_updated=("status",), dry_run=True
        )
        assert not _queries(fake, "issueUpdate(")

    def test_write_path_preserves_inline_code_form(self) -> None:
        description = _inline_objective_description("01HDR")
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        update = store.update_objective_header(objective_id="obj-1", fields={"status": "complete"})
        assert update == objective_store.ObjectiveHeaderUpdate(
            fields_updated=("status",), dry_run=False
        )
        [(_, variables)] = _queries(fake, "issueUpdate(")
        new_description = _input_payload(variables)["description"]
        assert isinstance(new_description, str)
        assert "<!--" not in new_description and "<details>" not in new_description
        header = plan.find_metadata_block(new_description, objective.OBJECTIVE_HEADER_KEY)
        assert header is not None
        assert header["status"] == "complete" and header["run_id"] == "01HDR"


class TestUpdateObjectiveNode:
    def test_node_not_found_raises(self) -> None:
        description = _inline_objective_description("01N")
        store, _ = _make_store({"issue(id": [_objective_issue_response(description)]})
        with pytest.raises(
            ObjectiveStoreError, match=r"objective node '9\.9' not found on 'obj-1'"
        ):
            store.update_objective_node(
                objective_id="obj-1", node_id="9.9", status=objective.NodeStatus.DONE
            )

    def test_dry_run_shape(self) -> None:
        description = _inline_objective_description("01N")
        store, fake = _make_store({"issue(id": [_objective_issue_response(description)]})
        update = store.update_objective_node(
            objective_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE, dry_run=True
        )
        assert update == objective_store.ObjectiveNodeUpdate(
            objective_id="obj-1", node_id="1.2", comment_updated=False, dry_run=True
        )
        assert not _queries(fake, "issueUpdate(")

    def test_authoritative_write_plus_comment_rerender(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-uuid-1")
        comment_body = to_linear_markdown(
            objective.render_body_comment(_objective_nodes(), prose="Prose.")
        )
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [{"comment": {"body": comment_body}}],
                "commentUpdate(": [{"commentUpdate": {"success": True}}],
            }
        )
        update = store.update_objective_node(
            objective_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update == objective_store.ObjectiveNodeUpdate(
            objective_id="obj-1", node_id="1.2", comment_updated=True, dry_run=False
        )
        # the authoritative roadmap write (form-preserving inline-code)
        [(_, body_vars)] = _queries(fake, "issueUpdate(")
        new_description = _input_payload(body_vars)["description"]
        assert isinstance(new_description, str) and "<!--" not in new_description
        nodes, errors = objective.parse_roadmap_nodes(new_description)
        assert errors == []
        assert next(n for n in nodes if n.id == "1.2").status is objective.NodeStatus.DONE
        # the best-effort comment re-render (form-preserving inline-code)
        [(_, patch_vars)] = _queries(fake, "commentUpdate(")
        assert patch_vars["id"] == "cmt-uuid-1"
        patched = _input_payload(patch_vars)["body"]
        assert isinstance(patched, str)
        assert "`perk:roadmap-table`" in patched and "<!--" not in patched
        line = next(ln for ln in patched.splitlines() if ln.startswith("| 1.2 "))
        assert "done" in line
        assert "Prose." in patched

    def test_missing_comment_id_degrades_to_comment_not_updated(self) -> None:
        description = _inline_objective_description("01N", comment_id=None)
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        update = store.update_objective_node(
            objective_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update.comment_updated is False
        assert len(_queries(fake, "issueUpdate(")) == 1  # roadmap still written

    def test_comment_not_found_degrades(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-gone")
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [_not_found_error()],
            }
        )
        update = store.update_objective_node(
            objective_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update.comment_updated is False
        assert not _queries(fake, "commentUpdate(")

    def test_markerless_comment_degrades(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-1")
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [{"comment": {"body": "no table markers here"}}],
            }
        )
        update = store.update_objective_node(
            objective_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update.comment_updated is False
        assert not _queries(fake, "commentUpdate(")


class TestAddObjectiveNode:
    def test_authoritative_write_plus_comment_rerender(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-uuid-1")
        comment_body = to_linear_markdown(
            objective.render_body_comment(_objective_nodes(), prose="Prose.")
        )
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [{"comment": {"body": comment_body}}],
                "commentUpdate(": [{"commentUpdate": {"success": True}}],
            }
        )
        added = store.add_objective_node(objective_id="obj-1", phase=1, description="Gamma")
        assert added == objective_store.ObjectiveNodeAdd(
            objective_id="obj-1", node_id="1.3", comment_updated=True, dry_run=False
        )
        # the authoritative roadmap write inserts the new node (form-preserving inline-code)
        [(_, body_vars)] = _queries(fake, "issueUpdate(")
        new_description = _input_payload(body_vars)["description"]
        assert isinstance(new_description, str) and "<!--" not in new_description
        nodes, errors = objective.parse_roadmap_nodes(new_description)
        assert errors == []
        assert [n.id for n in nodes] == ["1.1", "1.2", "1.3"]
        assert next(n for n in nodes if n.id == "1.3").description == "Gamma"

    def test_dry_run_shape(self) -> None:
        description = _inline_objective_description("01N")
        store, fake = _make_store({"issue(id": [_objective_issue_response(description)]})
        added = store.add_objective_node(
            objective_id="obj-1", phase=1, description="Gamma", dry_run=True
        )
        assert added == objective_store.ObjectiveNodeAdd(
            objective_id="obj-1", node_id="1.3", comment_updated=False, dry_run=True
        )
        assert not _queries(fake, "issueUpdate(")


class TestUpdateObjectiveBody:
    def test_missing_comment_id_raises(self) -> None:
        description = _inline_objective_description("01B", comment_id=None)
        store, _ = _make_store({"issue(id": [_objective_issue_response(description)]})
        with pytest.raises(ObjectiveStoreError, match="objective 'obj-1' has no body comment"):
            store.update_objective_body(objective_id="obj-1", prose="p")

    def test_comment_not_found_raises(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-gone")
        store, _ = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [_not_found_error()],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="has no body comment"):
            store.update_objective_body(objective_id="obj-1", prose="p")

    def test_no_reconcilable_region_raises(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-1")
        store, _ = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [{"comment": {"body": "no markers"}}],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="no reconcilable region"):
            store.update_objective_body(objective_id="obj-1", prose="p")

    def test_dry_run_composes_only(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-1")
        comment_body = to_linear_markdown(
            objective.render_body_comment(_objective_nodes(), prose="Old.")
        )
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [{"comment": {"body": comment_body}}],
            }
        )
        update = store.update_objective_body(objective_id="obj-1", prose="New.", dry_run=True)
        assert update == objective_store.ObjectiveBodyUpdate(
            objective_id="obj-1", comment_id="cmt-1", updated=False, dry_run=True
        )
        assert not _queries(fake, "commentUpdate(")

    def test_splice_preserves_immutable_tail(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-1")
        comment_body = (
            to_linear_markdown(objective.render_body_comment(_objective_nodes(), prose="Old."))
            + "\n## Immutable history\nnever touch this\n"
        )
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [{"comment": {"body": comment_body}}],
                "commentUpdate(": [{"commentUpdate": {"success": True}}],
            }
        )
        update = store.update_objective_body(objective_id="obj-1", prose="New prose.")
        assert update == objective_store.ObjectiveBodyUpdate(
            objective_id="obj-1", comment_id="cmt-1", updated=True, dry_run=False
        )
        [(_, patch_vars)] = _queries(fake, "commentUpdate(")
        assert patch_vars["id"] == "cmt-1"
        patched = _input_payload(patch_vars)["body"]
        assert isinstance(patched, str)
        assert "New prose." in patched and "Old." not in patched
        assert "never touch this" in patched  # the Immutable tail is preserved
        assert "`perk:roadmap-table`" in patched  # the Mechanical block above is preserved
        assert "<!--" not in patched


class TestIssueBackedStoreNode34Methods:
    """The dormant issue-backed `LinearObjectiveStore`'s Node 3.4 methods: it does NOT unify node +
    plan (`save_node_plan` → None) and `close_objective` moves the objective issue to Done."""

    def test_save_node_plan_returns_none(self) -> None:
        store, fake = _make_store()
        result = store.save_node_plan(
            objective_id="obj-1", node_id="1.1", header_fields={"run_id": "R"}, plan_markdown="# p"
        )
        assert result is None
        assert fake.requests == []

    def test_close_objective_moves_issue_to_done(self) -> None:
        store, fake = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [_STATES_RESPONSE],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        assert store.close_objective(objective_id="obj-1") is True
        [(_, variables)] = _queries(fake, "issueUpdate(")
        assert variables["id"] == "obj-1"  # boundary identifier sent directly
        assert not _queries(fake, "UuidForIssue")
        assert _input_payload(variables) == {"stateId": "state-done"}

    def test_close_objective_dry_run_writes_nothing(self) -> None:
        store, fake = _make_store()
        assert store.close_objective(objective_id="obj-1", dry_run=True) is False
        assert fake.requests == []

    def test_post_status_update_is_noop_false(self) -> None:
        # The issue-backed store has no project status-update surface (Node 4.3) — always False,
        # never raises, no request.
        store, fake = _make_store()
        assert store.post_status_update(objective_id="obj-1", body="x") is False
        assert store.post_status_update(objective_id="obj-1", body="x", dry_run=True) is False
        assert fake.requests == []


class TestMutationIdentifiers:
    """The verified mutations (``issueUpdate``/``commentCreate``) take the boundary identifier
    directly — no identifier→UUID resolution round-trip, no ``UuidForIssue`` query (live-verified
    at the Mode 2 smoke gate, 2026-06-15)."""

    def test_mutations_carry_the_identifier_directly(self) -> None:
        backend, fake = _make_backend(
            {
                "commentCreate(": [{"commentCreate": {"success": True}}],
            }
        )
        backend.add_issue_comment(issue_id="ENG-1", body="a")
        backend.add_issue_comment(issue_id="ENG-1", body="b")
        assert not _queries(fake, "UuidForIssue")  # no resolution layer remains
        for _, variables in _queries(fake, "commentCreate("):
            assert _input_payload(variables)["issueId"] == "ENG-1"

    def test_update_plan_header_sends_the_identifier(self) -> None:
        # update_plan_header reads the issue first, then patches it — the mutation carries the
        # boundary identifier, never a resolved UUID, and fires no UuidForIssue query.
        description = _inline_plan_description("01HDR")
        backend, fake = _make_backend(
            {
                "issue(id": [{"issue": {"id": "uuid-1", "description": description}}],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        backend.update_plan_header(issue_id="ENG-1", fields={"pr": "12"})
        assert not _queries(fake, "UuidForIssue")
        [(_, variables)] = _queries(fake, "issueUpdate(")
        assert variables["id"] == "ENG-1"


def _generic_input_error() -> LinearGraphQLError:
    # An INPUT_ERROR that is NOT a missing entity — e.g. argument validation. The code is
    # present but the message lacks the "Entity not found" prefix, so the pairing predicate
    # must NOT swallow it.
    return LinearGraphQLError(
        "Linear GraphQL error: Argument Validation Error", codes=("INPUT_ERROR",)
    )


def _not_found_message_wrong_code() -> LinearGraphQLError:
    # A "not found"-shaped message under a different code — the regression the tightening buys:
    # the old loose substring check would have swallowed this as a missing entity.
    return LinearGraphQLError(
        "Linear GraphQL error: Entity not found: Issue", codes=("RATELIMITED",)
    )


def _not_found_message_no_code() -> LinearGraphQLError:
    # A "not found"-shaped message with no code at all — also must re-raise now.
    return LinearGraphQLError("Linear GraphQL error: Entity not found: Issue", codes=())


class TestEntityNotFoundDiscrimination:
    """The not-found predicate pairs ``INPUT_ERROR in exc.codes`` with the ``"Entity not
    found"`` message prefix (Node 1.2, docs/planning/linear-smoke-gate.md gate-8). These prove the
    tightening actually narrowed: a code-present/message-absent error and a
    message-present/code-wrong error both re-raise at all three call sites, while the observed
    shape is still swallowed."""

    # --- _issue_or_none (via get_plan) ---

    def test_read_observed_shape_is_none(self) -> None:
        backend, _ = _make_backend({"issue(id": [_not_found_error()]})
        assert backend.get_plan(issue_id="iss-gone") is None

    def test_read_generic_input_error_reraises(self) -> None:
        backend, _ = _make_backend({"issue(id": [_generic_input_error()]})
        with pytest.raises(IssueBackendError, match="Argument Validation Error"):
            backend.get_plan(issue_id="iss-1")

    def test_read_not_found_message_wrong_code_reraises(self) -> None:
        # The key regression: a "not found" message under RATELIMITED is no longer swallowed.
        backend, _ = _make_backend({"issue(id": [_not_found_message_wrong_code()]})
        with pytest.raises(IssueBackendError, match="Linear GraphQL error: Entity not found"):
            backend.get_plan(issue_id="iss-1")

    def test_read_not_found_message_no_code_reraises(self) -> None:
        backend, _ = _make_backend({"issue(id": [_not_found_message_no_code()]})
        with pytest.raises(IssueBackendError, match="Linear GraphQL error: Entity not found"):
            backend.get_plan(issue_id="iss-1")

    # --- verified mutations (commentCreate/issueUpdate via _request_issue_mutation) ---
    # The not-found mapping the old `uuid_for` resolution emitted is now preserved on the
    # mutation itself: a missing entity becomes the byte-identical "Linear issue '<id>' not
    # found", every other error re-raises raw.

    def test_mutation_observed_shape_raises_converted(self) -> None:
        backend, _ = _make_backend({"commentCreate(": [_not_found_error()]})
        with pytest.raises(IssueBackendError, match="'ENG-404' not found"):
            backend.add_issue_comment(issue_id="ENG-404", body="x")

    def test_mutation_generic_input_error_reraises_raw(self) -> None:
        backend, _ = _make_backend({"commentCreate(": [_generic_input_error()]})
        with pytest.raises(IssueBackendError, match="Argument Validation Error"):
            backend.add_issue_comment(issue_id="ENG-404", body="x")

    def test_mutation_not_found_message_wrong_code_reraises_raw(self) -> None:
        # Re-raises the raw GraphQL error, NOT the converted "'ENG-404' not found" message.
        backend, _ = _make_backend({"commentCreate(": [_not_found_message_wrong_code()]})
        with pytest.raises(IssueBackendError, match="Linear GraphQL error: Entity not found"):
            backend.add_issue_comment(issue_id="ENG-404", body="x")

    # --- _comment_body_or_none (via update_objective_node) ---

    def test_comment_observed_shape_degrades(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-gone")
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [_not_found_error()],
            }
        )
        update = store.update_objective_node(
            objective_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update.comment_updated is False
        assert not _queries(fake, "commentUpdate(")

    def test_comment_not_found_message_wrong_code_reraises(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-gone")
        store, _ = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [_not_found_message_wrong_code()],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="Linear GraphQL error: Entity not found"):
            store.update_objective_node(
                objective_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
            )


class TestImportDirection:
    def test_linear_backend_never_imports_the_resolver_module(self) -> None:
        # The resolver module will import us at wiring time (Nodes 2.3/2.4); importing it back
        # would be a cycle. Mirrors the TestImportDirection substring style.
        source = Path(linear_backend.__file__).read_text(encoding="utf-8")
        assert "perk.backends.issues" not in source
        assert "import issues" not in source


class TestValueShapes:
    def test_issue_refs_are_frozen_with_string_ids(self) -> None:
        ref = issue_backend.IssueRef(id="uuid-1", url="u", existed=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = "x"  # ty: ignore[invalid-assignment]


# ---------------------------------------------------------------------------- readiness probe

_VIEWER_OK: dict[str, object] = {"viewer": {"id": "u1", "name": "Mat", "email": "m@x.io"}}
_VIEWER_EMAIL_ONLY: dict[str, object] = {"viewer": {"id": "u1", "name": "", "email": "m@x.io"}}
_LABEL_CREATED: dict[str, object] = {
    "issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-new"}}
}


class TestCheckReadiness:
    def test_auth_failure_short_circuits(self) -> None:
        fake = _FakeLinear({"viewer": [IssueBackendError("Linear API request failed: boom")]})
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=False)
        assert readiness.auth_ok is False
        assert readiness.team_ok is False
        assert readiness.user is None
        assert readiness.error is not None and "boom" in readiness.error
        # Auth failure short-circuits: no team/label queries issued.
        assert len(fake.requests) == 1

    def test_team_not_found(self) -> None:
        fake = _FakeLinear({"viewer": [_VIEWER_OK], "teams(filter": [{"teams": {"nodes": []}}]})
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=False)
        assert readiness.auth_ok is True
        assert readiness.user == "Mat"
        assert readiness.team_ok is False
        assert readiness.error is not None and "ENG" in readiness.error
        # Team failure skips labels.
        assert not _queries(fake, "issueLabels")

    def test_user_falls_back_to_email(self) -> None:
        fake = _FakeLinear(
            {
                "viewer": [_VIEWER_EMAIL_ONLY],
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_FOUND],
            }
        )
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=False)
        assert readiness.user == "m@x.io"

    def test_all_labels_present_lookup_only(self) -> None:
        fake = _FakeLinear(
            {
                "viewer": [_VIEWER_OK],
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_FOUND],
            }
        )
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=False)
        assert readiness == linear_backend.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=True, missing_labels=(), created_labels=()
        )
        # Lookup-only: no create mutation issued under ensure_labels=False.
        assert not _queries(fake, "issueLabelCreate")
        assert len(_queries(fake, "issueLabels(filter")) == 5

    def test_missing_labels_reported(self) -> None:
        fake = _FakeLinear(
            {
                "viewer": [_VIEWER_OK],
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_ABSENT],
            }
        )
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=False)
        assert readiness.missing_labels == (
            plan.PLAN_LABEL,
            plan.LEARN_LABEL,
            plan.CONSOLIDATED_LABEL,
            objective.OBJECTIVE_LABEL,
            objective.OBJECTIVE_NODE_LABEL,
        )
        assert readiness.created_labels == ()
        assert readiness.error is None

    def test_ensure_labels_creates_and_reports(self) -> None:
        fake = _FakeLinear(
            {
                "viewer": [_VIEWER_OK],
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_ABSENT],
                "issueLabelCreate": [_LABEL_CREATED],
            }
        )
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=True)
        assert readiness.created_labels == (
            plan.PLAN_LABEL,
            plan.LEARN_LABEL,
            plan.CONSOLIDATED_LABEL,
            objective.OBJECTIVE_LABEL,
            objective.OBJECTIVE_NODE_LABEL,
        )
        assert readiness.missing_labels == ()
        assert len(_queries(fake, "issueLabelCreate")) == 5

    def test_ensure_labels_preexisting_reports_none(self) -> None:
        # The genuine-delta rule: lookup-first idempotency → a converged workspace creates none.
        fake = _FakeLinear(
            {
                "viewer": [_VIEWER_OK],
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_FOUND],
            }
        )
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=True)
        assert readiness.created_labels == ()
        assert not _queries(fake, "issueLabelCreate")

    def test_label_phase_failure_lands_in_error(self) -> None:
        fake = _FakeLinear(
            {
                "viewer": [_VIEWER_OK],
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [IssueBackendError("rate limited")],
            }
        )
        readiness = linear_backend.check_readiness(fake, team_key="ENG", ensure_labels=False)
        assert readiness.auth_ok is True
        assert readiness.team_ok is True
        assert readiness.error is not None and "rate limited" in readiness.error


def _states_payload(types: list[str]) -> dict[str, object]:
    return {"team": {"states": {"nodes": [{"type": t} for t in types]}}}


_ALL_STATE_TYPES: list[str] = ["unstarted", "started", "completed", "canceled"]
_PROJECTS_OK: dict[str, object] = {"team": {"projects": {"nodes": [{"id": "proj-1"}]}}}


class TestCheckProjectReadiness:
    def test_derivation_guard_in_lockstep_with_map(self) -> None:
        assert frozenset(linear_backend._NODE_STATUS_STATE_TYPE.values()) == (
            linear_backend._REQUIRED_STATE_TYPES
        )

    def test_all_ready(self) -> None:
        fake = _FakeLinear(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first: 1": [_PROJECTS_OK],
                "states { nodes { type }": [_states_payload(_ALL_STATE_TYPES)],
            }
        )
        result = linear_backend.check_project_readiness(fake, team_key="ENG")
        assert result == linear_backend.LinearProjectReadiness(
            projects_ok=True,
            projects_error=None,
            missing_state_types=(),
            states_error=None,
        )

    def test_projects_error_does_not_short_circuit_states(self) -> None:
        fake = _FakeLinear(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first: 1": [IssueBackendError("no project access")],
                "states { nodes { type }": [_states_payload(_ALL_STATE_TYPES)],
            }
        )
        result = linear_backend.check_project_readiness(fake, team_key="ENG")
        assert result.projects_ok is False
        assert result.projects_error is not None and "no project access" in result.projects_error
        # The states phase still ran (projects error does not short-circuit it).
        assert _queries(fake, "states { nodes { type }")
        assert result.missing_state_types == ()
        assert result.states_error is None

    def test_missing_state_type_reported_sorted(self) -> None:
        fake = _FakeLinear(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first: 1": [_PROJECTS_OK],
                "states { nodes { type }": [_states_payload(["unstarted", "started", "completed"])],
            }
        )
        result = linear_backend.check_project_readiness(fake, team_key="ENG")
        assert result.projects_ok is True
        assert result.missing_state_types == ("canceled",)

    def test_states_probe_error(self) -> None:
        fake = _FakeLinear(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first: 1": [_PROJECTS_OK],
                "states { nodes { type }": [IssueBackendError("states boom")],
            }
        )
        result = linear_backend.check_project_readiness(fake, team_key="ENG")
        assert result.states_error is not None and "states boom" in result.states_error
        assert result.missing_state_types == ()

    def test_malformed_state_nodes_skipped_not_raised(self) -> None:
        fake = _FakeLinear(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first: 1": [_PROJECTS_OK],
                "states { nodes { type }": [
                    {
                        "team": {
                            "states": {
                                "nodes": [
                                    "junk",
                                    {"type": 7},
                                    *[{"type": t} for t in _ALL_STATE_TYPES],
                                ]
                            }
                        }
                    }
                ],
            }
        )
        result = linear_backend.check_project_readiness(fake, team_key="ENG")
        assert result.missing_state_types == ()
        assert result.states_error is None


# ---------------------------------------------------------------------- project ops (Node 3.1)


def _make_project_ops(
    responses: dict[str, list[object]] | None = None,
) -> tuple[linear_backend._LinearProjectOps, _FakeLinear]:
    """Construct the dormant ``_LinearProjectOps`` client-only (the correction §3b ownership shape
    — it registers the client; the shared cache lives on the client)."""
    fake = _FakeLinear(responses)
    ops = linear_backend._LinearProjectOps(fake, team_key="ENG", repo_root=Path("/repo"))
    return ops, fake


def _make_issue_ops(
    responses: dict[str, list[object]] | None = None,
) -> tuple[linear_backend._LinearIssueOps, _FakeLinear]:
    """Construct a client-only ``_LinearIssueOps`` (for the `_create_issue` substrate tests)."""
    fake = _FakeLinear(responses)
    ops = linear_backend._LinearIssueOps(fake, team_key="ENG", repo_root=Path("/repo"))
    return ops, fake


def _project_not_found(entity: str = "Project") -> LinearGraphQLError:
    return LinearGraphQLError(
        f"Linear GraphQL error: Entity not found: {entity}", codes=("INPUT_ERROR",)
    )


def _relation_validation_error() -> LinearGraphQLError:
    # The DIVERGENT relation-create miss: argument validation fires before entity lookup, so a
    # bogus relatedIssueId is INVALID_INPUT / "Argument Validation Error" — neither the code nor
    # the message-prefix matches `_is_entity_not_found`, so it must propagate (fail loud).
    return LinearGraphQLError(
        "Linear GraphQL error: Argument Validation Error", codes=("INVALID_INPUT",)
    )


class TestLinearProjectOps:
    """The dormant Linear Projects substrate (Node 3.1): the ten ops + the `_create_issue`
    create-in-project extension, all offline through the `_FakeLinear` `GraphQLClient`."""

    def test_create_project_resolves_team_and_returns_id_url(self) -> None:
        ops, fake = _make_project_ops(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projectCreate(": [
                    {"projectCreate": {"success": True, "project": {"id": "p-1", "url": "u"}}}
                ],
            }
        )
        result = ops.create_project(name="Phase 3", content="overview")
        assert result == {"id": "p-1", "url": "u"}
        [(_, variables)] = _queries(fake, "projectCreate(")
        payload = _input_payload(variables)
        assert payload["teamIds"] == ["team-1"]  # the resolved team UUID, as a list
        assert payload["name"] == "Phase 3"
        assert payload["content"] == "overview"

    def test_create_project_failure_raises(self) -> None:
        ops, _ = _make_project_ops(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projectCreate(": [{"projectCreate": {"success": False}}],
            }
        )
        with pytest.raises(IssueBackendError, match="failed to create Linear project"):
            ops.create_project(name="Phase 3", content="overview")

    def test_update_project_content_no_uuid_resolution(self) -> None:
        ops, fake = _make_project_ops(
            {"projectUpdate(": [{"projectUpdate": {"success": True, "project": {"id": "p-1"}}}]}
        )
        ops.update_project_content("p-1", "new overview")
        # Project ids are opaque UUIDs: no UuidForIssue resolution.
        assert not _queries(fake, "UuidForIssue")
        [(_, variables)] = _queries(fake, "projectUpdate(")
        assert variables["id"] == "p-1"
        assert _input_payload(variables)["content"] == "new overview"

    def test_update_project_content_failure_raises(self) -> None:
        ops, _ = _make_project_ops({"projectUpdate(": [{"projectUpdate": {"success": False}}]})
        with pytest.raises(IssueBackendError, match="failed to update Linear project"):
            ops.update_project_content("p-1", "x")

    def test_project_or_none_hit_returns_parsed_dict(self) -> None:
        ops, _ = _make_project_ops(
            {"project(id": [{"project": {"id": "p-1", "content": "overview"}}]}
        )
        assert ops.project_or_none("p-1", "id content") == {"id": "p-1", "content": "overview"}

    def test_project_or_none_entity_not_found_is_none(self) -> None:
        ops, _ = _make_project_ops({"project(id": [_project_not_found()]})
        assert ops.project_or_none("p-gone", "content") is None

    def test_project_or_none_other_error_reraises(self) -> None:
        ops, _ = _make_project_ops({"project(id": [_relation_validation_error()]})
        with pytest.raises(IssueBackendError, match="Argument Validation Error"):
            ops.project_or_none("p-1", "content")

    def test_project_milestones_paginates_and_keys_by_name(self) -> None:
        page1 = {
            "project": {
                "projectMilestones": _page(
                    [{"id": "m-1", "name": "Phase 1"}], has_next=True, cursor="C"
                )
            }
        }
        page2 = {"project": {"projectMilestones": _page([{"id": "m-2", "name": "Phase 2"}])}}
        ops, _ = _make_project_ops({"projectMilestones(": [page1, page2]})
        assert ops.project_milestones("p-1") == [
            {"id": "m-1", "name": "Phase 1"},
            {"id": "m-2", "name": "Phase 2"},
        ]

    def test_project_issues_paginates_and_carries_url(self) -> None:
        page1 = {
            "project": {
                "issues": _page(
                    [{"id": "i-1", "identifier": "ENG-1", "url": "u/1", "description": "body-1"}],
                    has_next=True,
                    cursor="C",
                )
            }
        }
        page2 = {
            "project": {
                "issues": _page(
                    [{"id": "i-2", "identifier": "ENG-2", "url": "u/2", "description": ""}]
                )
            }
        }
        ops, _ = _make_project_ops({"issues(first": [page1, page2]})
        # `url` is selected + returned (Node 3.4: save_node_plan returns the node-issue ref).
        assert ops.project_issues("p-1") == [
            {"id": "i-1", "identifier": "ENG-1", "url": "u/1", "description": "body-1"},
            {"id": "i-2", "identifier": "ENG-2", "url": "u/2", "description": ""},
        ]

    def test_set_project_state_marks_completed(self) -> None:
        ops, fake = _make_project_ops({"projectUpdate(": [{"projectUpdate": {"success": True}}]})
        ops.set_project_state("p-1", "completed")
        [(_, variables)] = _queries(fake, "projectUpdate(")
        assert variables["id"] == "p-1"
        assert _input_payload(variables) == {"state": "completed"}

    def test_set_project_state_failure_raises(self) -> None:
        ops, _ = _make_project_ops({"projectUpdate(": [{"projectUpdate": {"success": False}}]})
        with pytest.raises(IssueBackendError, match="failed to set state"):
            ops.set_project_state("p-1", "completed")

    def test_create_project_milestone_returns_id(self) -> None:
        ops, fake = _make_project_ops(
            {
                "projectMilestoneCreate(": [
                    {
                        "projectMilestoneCreate": {
                            "success": True,
                            "projectMilestone": {"id": "m-1", "name": "Phase 1"},
                        }
                    }
                ]
            }
        )
        assert ops.create_project_milestone(project_id="p-1", name="Phase 1") == "m-1"
        [(_, variables)] = _queries(fake, "projectMilestoneCreate(")
        payload = _input_payload(variables)
        assert payload == {"projectId": "p-1", "name": "Phase 1"}

    # --- ensure_phase_milestone: name-keyed lookup-or-create (Node 4.3) ---

    def test_ensure_phase_milestone_known_hit_reuses_id_no_network(self) -> None:
        ops, fake = _make_project_ops()
        known = {"Phase 1": "m-1"}
        assert ops.ensure_phase_milestone(project_id="p-1", name="Phase 1", known=known) == "m-1"
        # A `known` hit lists nothing and creates nothing.
        assert fake.requests == []

    def test_ensure_phase_milestone_known_miss_creates_and_updates_map(self) -> None:
        ops, fake = _make_project_ops({"projectMilestoneCreate(": [_milestone_create("m-new")]})
        known: dict[str, str] = {"Phase 1": "m-1"}
        assert ops.ensure_phase_milestone(project_id="p-1", name="Phase 2", known=known) == "m-new"
        # The new id is written back into the caller's map (amortizes a batch).
        assert known == {"Phase 1": "m-1", "Phase 2": "m-new"}
        assert not _queries(fake, "projectMilestones(")  # `known` supplied → no list read

    def test_ensure_phase_milestone_matches_by_name_not_list_position(self) -> None:
        # Milestone order is NOT insertion order: a `known` map built from a list whose order
        # differs from the phase order still resolves by NAME.
        page = {
            "project": {
                "projectMilestones": _page(
                    [{"id": "m-2", "name": "Phase 2"}, {"id": "m-1", "name": "Phase 1"}]
                )
            }
        }
        ops, fake = _make_project_ops({"projectMilestones(": [page]})
        assert ops.ensure_phase_milestone(project_id="p-1", name="Phase 1") == "m-1"
        # `known=None` → lists once.
        assert len(_queries(fake, "projectMilestones(")) == 1

    def test_ensure_phase_milestone_known_none_lists_once_then_creates_on_miss(self) -> None:
        page = {"project": {"projectMilestones": _page([{"id": "m-1", "name": "Phase 1"}])}}
        ops, fake = _make_project_ops(
            {
                "projectMilestones(": [page],
                "projectMilestoneCreate(": [_milestone_create("m-2")],
            }
        )
        assert ops.ensure_phase_milestone(project_id="p-1", name="Phase 2") == "m-2"
        assert len(_queries(fake, "projectMilestones(")) == 1
        [(_, variables)] = _queries(fake, "projectMilestoneCreate(")
        assert _input_payload(variables) == {"projectId": "p-1", "name": "Phase 2"}

    # --- create_project_update: projectUpdateCreate (Node 4.3) ---

    def test_create_project_update_returns_id(self) -> None:
        ops, fake = _make_project_ops(
            {
                "projectUpdateCreate(": [
                    {
                        "projectUpdateCreate": {
                            "success": True,
                            "projectUpdate": {"id": "u-1"},
                        }
                    }
                ]
            }
        )
        assert ops.create_project_update(project_id="p-1", body="**Hi**") == "u-1"
        [(query, variables)] = _queries(fake, "projectUpdateCreate(")
        assert "projectUpdateCreate(input: $input)" in query
        payload = _input_payload(variables)
        # Only projectId + body — `health` is deliberately omitted (D3).
        assert payload == {"projectId": "p-1", "body": "**Hi**"}
        assert "health" not in payload

    def test_create_project_update_failure_raises(self) -> None:
        ops, _ = _make_project_ops(
            {"projectUpdateCreate(": [{"projectUpdateCreate": {"success": False}}]}
        )
        with pytest.raises(IssueBackendError, match="failed to create Linear project update"):
            ops.create_project_update(project_id="p-1", body="x")

    def test_attach_issue_to_project_sends_the_identifier(self) -> None:
        ops, fake = _make_project_ops(
            {
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        ops.attach_issue_to_project(issue_id="ENG-1", project_id="p-1")
        [(_, variables)] = _queries(fake, "issueUpdate(")
        assert variables["id"] == "ENG-1"  # boundary identifier sent directly
        assert not _queries(fake, "UuidForIssue")
        assert _input_payload(variables)["projectId"] == "p-1"

    def test_create_document_returns_id(self) -> None:
        ops, fake = _make_project_ops(
            {"documentCreate(": [{"documentCreate": {"success": True, "document": {"id": "d-1"}}}]}
        )
        assert ops.create_document(project_id="p-1", title="Overview", content="x") == "d-1"
        [(_, variables)] = _queries(fake, "documentCreate(")
        assert _input_payload(variables) == {
            "projectId": "p-1",
            "title": "Overview",
            "content": "x",
        }

    def test_document_content_hit(self) -> None:
        ops, _ = _make_project_ops({"document(id": [{"document": {"content": "overview"}}]})
        assert ops.document_content_or_none("d-1") == "overview"

    def test_document_content_not_found_is_none(self) -> None:
        ops, _ = _make_project_ops({"document(id": [_project_not_found("Document")]})
        assert ops.document_content_or_none("d-gone") is None

    def test_create_issue_relation_fires_blocks_type(self) -> None:
        ops, fake = _make_project_ops(
            {
                "issueRelationCreate(": [
                    {
                        "issueRelationCreate": {
                            "success": True,
                            "issueRelation": {"id": "rel-1", "type": "blocks"},
                        }
                    }
                ]
            }
        )
        rel = ops.create_issue_relation(issue_id="uuid-a", related_issue_id="uuid-b")
        assert rel == "rel-1"
        [(_, variables)] = _queries(fake, "issueRelationCreate(")
        assert _input_payload(variables) == {
            "issueId": "uuid-a",
            "relatedIssueId": "uuid-b",
            "type": "blocks",
        }

    def test_create_issue_relation_validation_error_propagates(self) -> None:
        # The divergent miss: NOT swallowed as not-found — it fails loud.
        ops, _ = _make_project_ops({"issueRelationCreate(": [_relation_validation_error()]})
        with pytest.raises(IssueBackendError, match="Argument Validation Error"):
            ops.create_issue_relation(issue_id="uuid-a", related_issue_id="uuid-bogus")

    def test_create_issue_relation_failure_raises(self) -> None:
        ops, _ = _make_project_ops(
            {"issueRelationCreate(": [{"issueRelationCreate": {"success": False}}]}
        )
        with pytest.raises(IssueBackendError, match="failed to create Linear issue relation"):
            ops.create_issue_relation(issue_id="uuid-a", related_issue_id="uuid-b")

    def test_issue_blocks_filters_to_blocks_type(self) -> None:
        nodes: list[dict[str, object]] = [
            {"type": "blocks", "relatedIssue": {"identifier": "ENG-2"}},
            {"type": "related", "relatedIssue": {"identifier": "ENG-3"}},
            {"type": "duplicate", "relatedIssue": {"identifier": "ENG-4"}},
            {"type": "blocks", "relatedIssue": {"identifier": "ENG-5"}},
        ]
        ops, _ = _make_project_ops({"relations(first": [{"issue": {"relations": _page(nodes)}}]})
        assert ops.issue_blocks("ENG-1") == ["ENG-2", "ENG-5"]

    def test_issue_blocked_by_filters_to_blocks_type(self) -> None:
        nodes: list[dict[str, object]] = [
            {"type": "blocks", "issue": {"identifier": "ENG-9"}},
            {"type": "related", "issue": {"identifier": "ENG-8"}},
            {"type": "blocks", "issue": {"identifier": "ENG-7"}},
        ]
        ops, _ = _make_project_ops(
            {"inverseRelations(first": [{"issue": {"inverseRelations": _page(nodes)}}]}
        )
        assert ops.issue_blocked_by("ENG-1") == ["ENG-9", "ENG-7"]

    def test_create_issue_with_project_and_milestone_adds_keys(self) -> None:
        ops, fake = _make_issue_ops(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "i-1", "identifier": "ENG-1", "url": "u"},
                        }
                    }
                ],
            }
        )
        ops._create_issue(
            title="T", description="D", label_id="lbl-1", project_id="p-1", milestone_id="m-1"
        )
        [(_, variables)] = _queries(fake, "issueCreate(")
        payload = _input_payload(variables)
        assert payload["projectId"] == "p-1"
        assert payload["projectMilestoneId"] == "m-1"

    def test_create_issue_without_project_omits_keys(self) -> None:
        ops, fake = _make_issue_ops(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "i-1", "identifier": "ENG-1", "url": "u"},
                        }
                    }
                ],
            }
        )
        ops._create_issue(title="T", description="D", label_id="lbl-1")
        [(_, variables)] = _queries(fake, "issueCreate(")
        payload = _input_payload(variables)
        assert "projectId" not in payload
        assert "projectMilestoneId" not in payload

    def test_create_issue_label_optional_omits_label_ids(self) -> None:
        ops, fake = _make_issue_ops(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "i-1", "identifier": "ENG-1", "url": "u"},
                        }
                    }
                ],
            }
        )
        ops._create_issue(title="T", description="D")
        [(_, variables)] = _queries(fake, "issueCreate(")
        assert "labelIds" not in _input_payload(variables)

    def test_create_issue_label_given_includes_label_ids(self) -> None:
        ops, fake = _make_issue_ops(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "i-1", "identifier": "ENG-1", "url": "u"},
                        }
                    }
                ],
            }
        )
        ops._create_issue(title="T", description="D", label_id="lbl-1")
        [(_, variables)] = _queries(fake, "issueCreate(")
        assert _input_payload(variables)["labelIds"] == ["lbl-1"]

    def test_create_issue_assigns_the_viewer(self) -> None:
        ops, fake = _make_issue_ops(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "i-1", "identifier": "ENG-1", "url": "u"},
                        }
                    }
                ],
            }
        )
        ops._create_issue(title="T", description="D")
        [(_, variables)] = _queries(fake, "issueCreate(")
        assert _input_payload(variables)["assigneeId"] == "viewer-1"

    def test_create_attachment_sends_idempotent_card_input(self) -> None:
        ops, fake = _make_issue_ops(
            {"attachmentCreate(": [{"attachmentCreate": {"success": True}}]}
        )
        ops.create_attachment("ENG-1", url="u/pr/9", title="GitHub PR #9", subtitle="OPEN")
        [(_, variables)] = _queries(fake, "attachmentCreate(")
        assert _input_payload(variables) == {
            "issueId": "ENG-1",
            "url": "u/pr/9",
            "title": "GitHub PR #9",
            "subtitle": "OPEN",
        }

    def test_create_attachment_omits_absent_subtitle(self) -> None:
        ops, fake = _make_issue_ops(
            {"attachmentCreate(": [{"attachmentCreate": {"success": True}}]}
        )
        ops.create_attachment("ENG-1", url="u/pr/9", title="GitHub PR #9")
        [(_, variables)] = _queries(fake, "attachmentCreate(")
        assert "subtitle" not in _input_payload(variables)

    def test_create_attachment_failure_raises(self) -> None:
        ops, _ = _make_issue_ops({"attachmentCreate(": [{"attachmentCreate": {"success": False}}]})
        with pytest.raises(IssueBackendError, match="failed to create attachment"):
            ops.create_attachment("ENG-1", url="u", title="t")


def _make_project_store(
    responses: dict[str, list[object]] | None = None,
) -> tuple[objective_store.ObjectiveStore, _FakeLinear]:
    """Construct the project-backed objective store over a fake `LinearClient`. The explicit
    ``ObjectiveStore`` annotation is the static conformance binding (Node 3.3): ty fails the suite
    if ``LinearProjectObjectiveStore`` drifts from the protocol — the twin of ``_make_store`` for
    the issue-backed ``LinearObjectiveStore``."""
    fake = _FakeLinear(responses)
    store: objective_store.ObjectiveStore = linear_backend.LinearProjectObjectiveStore(
        fake, team_key="ENG", repo_root=Path("/repo")
    )
    return store, fake


def _overview_for(run_id: str) -> str:
    """A project overview content carrying the inline-code objective-header for ``run_id``."""
    header = objective.ObjectiveHeader(
        run_id=run_id, created="t", objective_comment_id=None, status="active"
    )
    return plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, header.to_data(), style="inline-code"
    )


def _project_create_ok() -> dict[str, object]:
    return {"projectCreate": {"success": True, "project": {"id": "proj-1", "url": "p/url"}}}


def _issue_create(identifier: str, uuid: str) -> dict[str, object]:
    return {
        "issueCreate": {
            "success": True,
            "issue": {"id": uuid, "identifier": identifier, "url": f"u/{identifier}"},
        }
    }


def _milestone_create(mid: str) -> dict[str, object]:
    return {
        "projectMilestoneCreate": {
            "success": True,
            "projectMilestone": {"id": mid, "name": "Phase"},
        }
    }


def _relation_create_ok() -> dict[str, object]:
    return {
        "issueRelationCreate": {"success": True, "issueRelation": {"id": "rel", "type": "blocks"}}
    }


def _store_nodes() -> list[objective.ObjectiveNode]:
    N = objective.NodeStatus
    return [
        objective.ObjectiveNode(id="1.1", description="Alpha", status=N.PENDING, slug="alpha"),
        objective.ObjectiveNode(
            id="1.2", description="Beta", status=N.PENDING, slug="beta", depends_on=("1.1",)
        ),
        objective.ObjectiveNode(
            id="2.1", description="Gamma", status=N.PENDING, slug="gamma", depends_on=("1.2",)
        ),
    ]


_STORE_BODY = "Objective prose here.\n\n### Phase 1: Foundations\n\n### Phase 2: Build\n"

# A team-states response that includes a `started` state (the workflow-state mirror target). The
# module-level `_STATES_RESPONSE` deliberately has none, so node 3.3 needs its own fixture.
_STATES_WITH_STARTED: dict[str, object] = {
    "team": {
        "states": {
            "nodes": [
                {"id": "state-todo", "name": "Todo", "type": "unstarted", "position": 1},
                {"id": "state-doing", "name": "In Progress", "type": "started", "position": 2},
                {"id": "state-done", "name": "Done", "type": "completed", "position": 3},
            ]
        }
    }
}


def _node_block_desc(node: objective.ObjectiveNode, *, pr: str | None = None) -> str:
    """A node-issue description: the inline-code ``objective-node`` block, optionally a
    ``plan-header`` block carrying ``pr`` (the Node 3.4 backlink), then the prose description."""
    parts = [
        plan.render_metadata_block(
            objective.OBJECTIVE_NODE_KEY,
            objective.render_node_block(node),
            style="inline-code",
        )
    ]
    if pr is not None:
        parts.append(
            plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"pr": pr}, style="inline-code")
        )
    parts.append(node.description)
    return "\n\n".join(parts)


def _node_issue(
    node: objective.ObjectiveNode, *, uuid: str, identifier: str, pr: str | None = None
) -> dict[str, object]:
    """A ``project_issues`` node-issue row (id/identifier/url/description)."""
    return {
        "id": uuid,
        "identifier": identifier,
        "url": f"u/{identifier}",
        "description": _node_block_desc(node, pr=pr),
    }


def _blocked_by(*identifiers: str) -> dict[str, object]:
    """An ``issue_blocked_by`` (``inverseRelations``) response listing blocker identifiers."""
    return {
        "issue": {
            "inverseRelations": _page(
                [{"type": "blocks", "issue": {"identifier": i}} for i in identifiers]
            )
        }
    }


def _overview_with_region(run_id: str, prose: str) -> str:
    """A project overview carrying the inline-code header + a Reconcilable region (the create-path
    encoding: HTML markers transcoded to inline-code sentinels)."""
    header = objective.ObjectiveHeader(
        run_id=run_id, created="t", objective_comment_id=None, status="active"
    )
    header_block = plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, header.to_data(), style="inline-code"
    )
    reconcilable = (
        f"{objective.OBJECTIVE_RECONCILABLE_MARKER_START}\n"
        f"{prose}\n"
        f"{objective.OBJECTIVE_RECONCILABLE_MARKER_END}"
    )
    return to_linear_markdown(f"{header_block}\n\n{reconcilable}\n")


class TestLinearProjectObjectiveStore:
    """The dormant project-backed objective store (Node 3.2): `find_objective` + `create_objective`,
    all offline through the `_FakeLinear` `LinearClient` subclass."""

    def _create_responses(self) -> dict[str, list[object]]:
        return {
            "teams(filter": [_TEAM_RESPONSE],
            "projects(first": [{"team": {"projects": _page([])}}],  # find_objective dedup miss
            "projectCreate(": [_project_create_ok()],
            "projectUpdate(": [{"projectUpdate": {"success": True, "project": {"id": "proj-1"}}}],
            "projectMilestoneCreate(": [_milestone_create("m-1"), _milestone_create("m-2")],
            # The `perk:objective-node` label: looked up (absent) then created once (cached).
            "issueLabels(filter": [_LABEL_ABSENT],
            "issueLabelCreate(": [
                {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-node"}}}
            ],
            "issueCreate(": [
                _issue_create("ENG-1", "i-1"),
                _issue_create("ENG-2", "i-2"),
                _issue_create("ENG-3", "i-3"),
            ],
            "issueRelationCreate(": [_relation_create_ok()],
        }

    def test_create_objective_happy_path(self) -> None:
        store, fake = _make_project_store(self._create_responses())
        ref = store.create_objective(
            title="Big Objective",
            body=_STORE_BODY,
            run_id="01RUN",
            roadmap_nodes=_store_nodes(),
        )
        # (e) returns the project id, url, existed=False
        assert ref == objective_store.ObjectiveRef(id="proj-1", url="p/url", existed=False)

        # (a) overview: inline-code header + reconcilable markers + prose, NO roadmap table
        [(_, pvars)] = _queries(fake, "projectCreate(")
        content = cast("str", _input_payload(pvars)["content"])
        assert "`perk:metadata-block:objective-header`" in content
        assert "`perk:objective-reconcilable`" in content
        assert "Objective prose here." in content
        assert "roadmap-table" not in content
        assert "<!--" not in content  # fully transcoded to inline-code sentinels
        # prose-first: the human Reconcilable prose precedes the machine header/manifest blocks
        assert content.index("Objective prose here.") < content.index(
            "`perk:metadata-block:objective-header`"
        )
        # the API-key user is the project lead, and a startDate is set (required for the graph)
        pinput = _input_payload(pvars)
        assert pinput["leadId"] == "viewer-1"
        assert isinstance(pinput["startDate"], str) and pinput["startDate"]

        # (b) one milestone per phase, enriched names from the body headers
        mvars = [_input_payload(v) for _, v in _queries(fake, "projectMilestoneCreate(")]
        assert [m["name"] for m in mvars] == ["Foundations", "Build"]
        assert all(m["projectId"] == "proj-1" for m in mvars)
        # Node 4.3: routing through `ensure_phase_milestone` with a seeded-empty `known` keeps the
        # create path's network calls byte-identical — NO extra `project_milestones` read.
        assert not _queries(fake, "projectMilestones(")

        # (c) one issue per node, in node_sort_key order, projectId + milestone, node label
        ivars = [_input_payload(v) for _, v in _queries(fake, "issueCreate(")]
        assert [v["title"] for v in ivars] == ["1.1: alpha", "1.2: beta", "2.1: gamma"]
        assert [v.get("projectMilestoneId") for v in ivars] == ["m-1", "m-1", "m-2"]
        assert all(v["projectId"] == "proj-1" for v in ivars)
        # node-issues carry the workspace `perk:objective-node` label (additive filterability)
        assert all(v["labelIds"] == ["lbl-node"] for v in ivars)
        # every perk-created issue is assigned to the API-key user (the viewer)
        assert all(v["assigneeId"] == "viewer-1" for v in ivars)
        # node block + description embedded in the issue description
        assert "`perk:metadata-block:objective-node`" in cast("str", ivars[0]["description"])
        assert "Alpha" in cast("str", ivars[0]["description"])

        # (d) a blocking relation per explicit depends_on edge (dep -> node), none for empty.
        # The relation args are the issue UUIDs captured from the `issueCreate` response (not the
        # identifiers) and no identifier->UUID resolution query fires.
        rels = [_input_payload(v) for _, v in _queries(fake, "issueRelationCreate(")]
        assert {(r["issueId"], r["relatedIssueId"]) for r in rels} == {
            ("i-1", "i-2"),  # 1.1 blocks 1.2
            ("i-2", "i-3"),  # 1.2 blocks 2.1
        }
        assert all(r["type"] == "blocks" for r in rels)
        assert not _queries(fake, "UuidForIssue")

    def test_create_objective_persists_base_into_overview_header(self) -> None:
        # #633: the project-backed overview header composer (header.to_data()) carries `base`.
        store, fake = _make_project_store(self._create_responses())
        store.create_objective(
            title="Big Objective",
            body=_STORE_BODY,
            run_id="01RUN",
            base="develop",
            roadmap_nodes=_store_nodes(),
        )
        [(_, pvars)] = _queries(fake, "projectCreate(")
        content = cast("str", _input_payload(pvars)["content"])
        header = plan.find_metadata_block(content, objective.OBJECTIVE_HEADER_KEY)
        assert header is not None and header["base"] == "develop"

    def test_create_objective_prepends_overview_callout(self) -> None:
        # A fresh project-backed objective leads its overview with the copyable
        # `perk objective plan <project-uuid>` callout, written via a post-create projectUpdate.
        store, fake = _make_project_store(self._create_responses())
        store.create_objective(
            title="Big Objective",
            body=_STORE_BODY,
            run_id="01RUN",
            roadmap_nodes=_store_nodes(),
        )
        [(_, uvars)] = _queries(fake, "projectUpdate(")
        content = cast("str", _input_payload(uvars)["content"])
        assert content.startswith("**Plan the next node:**")
        assert "perk objective plan proj-1" in content

    def test_create_objective_dry_run_writes_nothing(self) -> None:
        store, fake = _make_project_store()
        ref = store.create_objective(
            title="X", body=_STORE_BODY, run_id="01RUN", roadmap_nodes=_store_nodes(), dry_run=True
        )
        assert ref == objective_store.ObjectiveRef(id="0", url="(dry-run)", existed=False)
        assert fake.requests == []

    def test_create_objective_empty_roadmap_raises(self) -> None:
        store, _ = _make_project_store(
            {
                "projects(first": [{"team": {"projects": _page([])}}],
                "teams(filter": [_TEAM_RESPONSE],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="roadmap is empty"):
            store.create_objective(title="X", body="prose", run_id="01RUN", roadmap_nodes=[])

    def test_create_objective_unknown_dependency_raises(self) -> None:
        bad = [
            objective.ObjectiveNode(
                id="1.1",
                description="A",
                status=objective.NodeStatus.PENDING,
                depends_on=("9.9",),
            )
        ]
        store, _ = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [{"team": {"projects": _page([])}}],
                "projectCreate(": [_project_create_ok()],
                "projectUpdate(": [
                    {"projectUpdate": {"success": True, "project": {"id": "proj-1"}}}
                ],
                "projectMilestoneCreate(": [_milestone_create("m-1")],
                "issueLabels(filter": [_LABEL_ABSENT],
                "issueLabelCreate(": [
                    {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-node"}}}
                ],
                "issueCreate(": [_issue_create("ENG-1", "i-1")],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="unknown node"):
            store.create_objective(title="X", body="prose", run_id="01RUN", roadmap_nodes=bad)

    def test_create_objective_idempotent_short_circuits(self) -> None:
        store, fake = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [
                    {
                        "team": {
                            "projects": _page(
                                [{"id": "proj-9", "url": "p/9", "content": _overview_for("01RUN")}]
                            )
                        }
                    }
                ],
            }
        )
        ref = store.create_objective(
            title="X", body=_STORE_BODY, run_id="01RUN", roadmap_nodes=_store_nodes()
        )
        assert ref == objective_store.ObjectiveRef(id="proj-9", url="p/9", existed=True)
        assert not _queries(fake, "projectCreate(")

    def test_find_objective_hit(self) -> None:
        store, _ = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [
                    {
                        "team": {
                            "projects": _page(
                                [{"id": "proj-1", "url": "p/1", "content": _overview_for("01RUN")}]
                            )
                        }
                    }
                ],
            }
        )
        assert store.find_objective(run_id="01RUN") == objective_store.ObjectiveRef(
            id="proj-1", url="p/1", existed=True
        )

    def test_find_objective_miss_returns_none(self) -> None:
        store, _ = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [
                    {
                        "team": {
                            "projects": _page(
                                [{"id": "proj-1", "url": "p/1", "content": _overview_for("OTHER")}]
                            )
                        }
                    }
                ],
            }
        )
        assert store.find_objective(run_id="01RUN") is None

    def test_find_objective_paginates_project_list(self) -> None:
        page1 = {
            "team": {
                "projects": _page(
                    [{"id": "proj-1", "url": "p/1", "content": None}], has_next=True, cursor="C"
                )
            }
        }
        page2 = {
            "team": {
                "projects": _page(
                    [{"id": "proj-2", "url": "p/2", "content": _overview_for("01RUN")}]
                )
            }
        }
        store, fake = _make_project_store(
            {"teams(filter": [_TEAM_RESPONSE], "projects(first": [page1, page2]}
        )
        assert store.find_objective(run_id="01RUN") == objective_store.ObjectiveRef(
            id="proj-2", url="p/2", existed=True
        )
        assert len(_queries(fake, "projects(first")) == 2

    # ----------------------------------------------------------------- get_objective

    def test_get_objective_happy_path(self) -> None:
        N = objective.NodeStatus
        n11 = objective.ObjectiveNode(id="1.1", description="Alpha", status=N.PENDING, slug="a")
        n12 = objective.ObjectiveNode(id="1.2", description="Beta", status=N.PLANNING, slug="b")
        n21 = objective.ObjectiveNode(id="2.1", description="Gamma", status=N.DONE, slug="g")
        # Scrambled connection order: 2.1, 1.1, 1.2 (never returned in this order).
        issues_page = _page(
            [
                _node_issue(n21, uuid="i-21", identifier="ENG-21"),
                _node_issue(n11, uuid="i-11", identifier="ENG-11"),
                _node_issue(n12, uuid="i-12", identifier="ENG-12"),
            ]
        )
        # `issues(first` is registered BEFORE `project(id`: the project_issues query contains both
        # substrings, and the fake matches the first-inserted needle.
        store, _ = _make_project_store(
            {
                "issues(first": [{"project": {"issues": issues_page}}],
                # inverseRelations pops in parsed (== connection) order: 2.1, 1.1, 1.2.
                "inverseRelations(": [
                    _blocked_by("ENG-12"),  # 2.1 blocked by 1.2
                    _blocked_by(),  # 1.1 blocked by nothing
                    _blocked_by("ENG-11"),  # 1.2 blocked by 1.1
                ],
                "project(id": [
                    {
                        "project": {
                            "id": "proj-1",
                            "url": "p/url",
                            "name": "Big Objective",
                            "content": _overview_for("01RUN"),
                        }
                    }
                ],
            }
        )
        state = store.get_objective(objective_id="proj-1")
        assert state is not None
        assert state.id == "proj-1"
        assert state.url == "p/url"
        assert state.title == "Big Objective"
        assert state.header.get("run_id") == "01RUN"
        # Sorted by node_sort_key (never the scrambled connection order).
        assert [n.id for n in state.nodes] == ["1.1", "1.2", "2.1"]
        assert [n.status for n in state.nodes] == [N.PENDING, N.PLANNING, N.DONE]
        assert [n.depends_on for n in state.nodes] == [None, ("1.1",), ("1.2",)]

    def test_get_objective_pr_is_node_issue_identifier(self) -> None:
        # Node 3.4 (D4): the backlink is the node-issue's OWN identifier whenever it carries a
        # plan-header block (a plan was saved into it) — self-referential by the unification model,
        # and stable across submit clobbering plan-header.pr with the GitHub PR number. The value
        # stored in plan-header.pr (here "#42") is intentionally NOT used.
        N = objective.NodeStatus
        n11 = objective.ObjectiveNode(id="1.1", description="Alpha", status=N.IN_PROGRESS)
        n12 = objective.ObjectiveNode(id="1.2", description="Beta", status=N.PENDING)
        store, _ = _make_project_store(
            {
                "issues(first": [
                    {
                        "project": {
                            "issues": _page(
                                [
                                    _node_issue(n11, uuid="i-11", identifier="ENG-11", pr="#42"),
                                    _node_issue(n12, uuid="i-12", identifier="ENG-12"),
                                ]
                            )
                        }
                    }
                ],
                "inverseRelations(": [_blocked_by(), _blocked_by()],
                "project(id": [
                    {"project": {"id": "proj-1", "url": "u", "name": "O", "content": ""}}
                ],
            }
        )
        state = store.get_objective(objective_id="proj-1")
        assert state is not None
        by_id = {n.id: n for n in state.nodes}
        assert by_id["1.1"].pr == "#ENG-11"  # identifier-derived, not the plan-header.pr value
        assert by_id["1.2"].pr is None  # no plan-header block → no backlink

    def test_get_objective_skips_foreign_issues(self) -> None:
        N = objective.NodeStatus
        n11 = objective.ObjectiveNode(id="1.1", description="Alpha", status=N.PENDING)
        store, fake = _make_project_store(
            {
                "issues(first": [
                    {
                        "project": {
                            "issues": _page(
                                [
                                    _node_issue(n11, uuid="i-11", identifier="ENG-11"),
                                    # a foreign/human-added project issue (no objective-node block)
                                    {
                                        "id": "i-99",
                                        "identifier": "ENG-99",
                                        "url": "u/ENG-99",
                                        "description": "just a normal issue",
                                    },
                                ]
                            )
                        }
                    }
                ],
                "inverseRelations(": [_blocked_by()],
                "project(id": [
                    {"project": {"id": "proj-1", "url": "u", "name": "O", "content": ""}}
                ],
            }
        )
        state = store.get_objective(objective_id="proj-1")
        assert state is not None
        assert [n.id for n in state.nodes] == ["1.1"]
        # The foreign issue's blockers are never queried (only one inverseRelations call).
        assert len(_queries(fake, "inverseRelations(")) == 1

    def test_get_objective_absent_project_is_none(self) -> None:
        store, _ = _make_project_store({"project(id": [_project_not_found()]})
        assert store.get_objective(objective_id="p-gone") is None

    def test_get_objective_malformed_node_raises(self) -> None:
        # An objective-node block missing `status` (rendered by hand to dodge the typed builder).
        bad_block = plan.render_metadata_block(
            objective.OBJECTIVE_NODE_KEY, {"id": "1.1", "description": "x"}, style="inline-code"
        )
        store, _ = _make_project_store(
            {
                "issues(first": [
                    {
                        "project": {
                            "issues": _page(
                                [
                                    {
                                        "id": "i-1",
                                        "identifier": "ENG-1",
                                        "url": "u/ENG-1",
                                        "description": bad_block,
                                    }
                                ]
                            )
                        }
                    }
                ],
                "project(id": [
                    {"project": {"id": "proj-1", "url": "u", "name": "O", "content": ""}}
                ],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="invalid objective node"):
            store.get_objective(objective_id="proj-1")

    # ----------------------------------------------------------------- update_objective_node

    def _node_issue_responses(
        self, node: objective.ObjectiveNode, *, uuid: str = "i-1", identifier: str = "ENG-1"
    ) -> dict[str, list[object]]:
        issue = _node_issue(node, uuid=uuid, identifier=identifier)
        return {
            "issues(first": [{"project": {"issues": _page([issue])}}],
        }

    def test_update_objective_node_status_and_mirror(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING, slug="a"
        )
        responses = self._node_issue_responses(node)
        responses["issueUpdate("] = [
            {"issueUpdate": {"success": True}},
            {"issueUpdate": {"success": True}},
        ]
        responses["teams(filter"] = [_TEAM_RESPONSE]
        responses["team(id"] = [_STATES_WITH_STARTED]
        # the project lifecycle nudge: in_progress maps to a `started`-type → Planned→Started
        responses["projectUpdate("] = [{"projectUpdate": {"success": True}}]
        store, fake = _make_project_store(responses)
        result = store.update_objective_node(
            objective_id="proj-1", node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
        )
        assert result == objective_store.ObjectiveNodeUpdate(
            objective_id="proj-1", node_id="1.1", comment_updated=False, dry_run=False
        )
        updates = [_input_payload(v) for _, v in _queries(fake, "issueUpdate(")]
        # (1) the authoritative description write re-renders the node block with the new status
        desc = cast("str", updates[0]["description"])
        block = plan.find_metadata_block(desc, objective.OBJECTIVE_NODE_KEY)
        assert block is not None
        assert block["status"] == "in_progress"
        assert "<!--" not in desc  # form preserved: inline-code, no HTML markers
        # (2) the best-effort workflow-state mirror sets the mapped `started` state
        assert updates[1] == {"stateId": "state-doing"}
        # (3) the project lifecycle nudge advances the project Planned→Started
        [(_, pvars)] = _queries(fake, "projectUpdate(")
        assert _input_payload(pvars) == {"state": "started"}

    def test_update_objective_node_mirror_fail_open(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        responses = self._node_issue_responses(node)
        # The description write succeeds; the stateId mirror write fails — swallowed.
        responses["issueUpdate("] = [
            {"issueUpdate": {"success": True}},
            {"issueUpdate": {"success": False}},
        ]
        responses["teams(filter"] = [_TEAM_RESPONSE]
        responses["team(id"] = [_STATES_WITH_STARTED]
        # the lifecycle nudge fires after the (failed) mirror; it is independently fail-open
        responses["projectUpdate("] = [{"projectUpdate": {"success": False}}]
        store, fake = _make_project_store(responses)
        result = store.update_objective_node(
            objective_id="proj-1", node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
        )
        # No raise; the description write is committed.
        assert result.dry_run is False
        assert len(_queries(fake, "issueUpdate(")) == 2

    def test_update_objective_node_pr_not_written_to_block(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        responses = self._node_issue_responses(node)
        responses["issueUpdate("] = [{"issueUpdate": {"success": True}}]
        store, fake = _make_project_store(responses)
        store.update_objective_node(objective_id="proj-1", node_id="1.1", pr="#7")
        [(_, variables)] = _queries(fake, "issueUpdate(")
        desc = cast("str", _input_payload(variables)["description"])
        block = plan.find_metadata_block(desc, objective.OBJECTIVE_NODE_KEY)
        assert block is not None
        assert "pr" not in block  # render_node_block excludes pr; the backlink lives in plan-header

    def test_update_objective_node_not_found_raises(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        issue = _node_issue(node, uuid="i-1", identifier="ENG-1")
        store, _ = _make_project_store({"issues(first": [{"project": {"issues": _page([issue])}}]})
        with pytest.raises(ObjectiveStoreError, match=r"objective node '9.9' not found"):
            store.update_objective_node(objective_id="proj-1", node_id="9.9")

    def test_update_objective_node_dry_run_writes_nothing(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        issue = _node_issue(node, uuid="i-1", identifier="ENG-1")
        store, fake = _make_project_store(
            {"issues(first": [{"project": {"issues": _page([issue])}}]}
        )
        result = store.update_objective_node(
            objective_id="proj-1", node_id="1.1", status=objective.NodeStatus.DONE, dry_run=True
        )
        assert result.dry_run is True
        assert not _queries(fake, "issueUpdate(")

    # ----------------------------------------------------------------- add_objective_node

    def test_add_objective_node_materializes_node_issue(self) -> None:
        n11 = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING, slug="alpha"
        )
        store, fake = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "project": {
                            "issues": _page([_node_issue(n11, uuid="i-11", identifier="ENG-11")])
                        }
                    }
                ],
                "projectMilestones(first": [{"project": {"projectMilestones": _page([])}}],
                "inverseRelations(": [_blocked_by()],
                "projectMilestoneCreate(": [_milestone_create("m-2")],
                "issueLabels(filter": [_LABEL_ABSENT],
                "issueLabelCreate(": [
                    {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-node"}}}
                ],
                "issueCreate(": [_issue_create("ENG-22", "i-22")],
                "project(id": [
                    {
                        "project": {
                            "id": "proj-1",
                            "url": "u",
                            "name": "O",
                            "content": _STORE_BODY,
                        }
                    },
                    {"project": {"content": _STORE_BODY}},
                ],
            }
        )
        added = store.add_objective_node(objective_id="proj-1", phase=2, description="Beta work")
        assert added == objective_store.ObjectiveNodeAdd(
            objective_id="proj-1", node_id="2.1", comment_updated=False, dry_run=False
        )
        # the phase-2 milestone is minted by its enriched name (`### Phase 2: Build`)
        [(_, mvars)] = _queries(fake, "projectMilestoneCreate(")
        assert _input_payload(mvars)["name"] == "Build"
        # the new node-issue carries the objective-node block + prose, attached to the milestone
        [(_, ivars)] = _queries(fake, "issueCreate(")
        payload = _input_payload(ivars)
        assert payload["projectId"] == "proj-1"
        assert payload["projectMilestoneId"] == "m-2"
        assert payload["labelIds"] == ["lbl-node"]  # workspace perk:objective-node label
        description = cast("str", payload["description"])
        assert "`perk:metadata-block:objective-node`" in description
        assert "Beta work" in description
        assert "<!--" not in description  # inline-code form
        # prose-first: the node prose precedes the objective-node block
        assert description.index("Beta work") < description.index(
            "`perk:metadata-block:objective-node`"
        )
        # no depends_on -> no blocking relations
        assert not _queries(fake, "issueRelationCreate(")

    def test_add_objective_node_relation_uses_create_time_uuids(self) -> None:
        # An explicit depends_on edge: the relation is created with the issue UUIDs (the new
        # node's UUID from its `issueCreate` response, the dep's UUID from `_find_node_issue`) —
        # never the identifier — and no UuidForIssue resolution query fires.
        n11 = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING, slug="alpha"
        )
        store, fake = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [
                    {
                        "project": {
                            "issues": _page([_node_issue(n11, uuid="i-11", identifier="ENG-11")])
                        }
                    }
                ],
                "projectMilestones(first": [{"project": {"projectMilestones": _page([])}}],
                "inverseRelations(": [_blocked_by()],
                "projectMilestoneCreate(": [_milestone_create("m-2")],
                "issueLabels(filter": [_LABEL_ABSENT],
                "issueLabelCreate(": [
                    {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-node"}}}
                ],
                "issueCreate(": [_issue_create("ENG-22", "i-22")],
                "issueRelationCreate(": [_relation_create_ok()],
                "project(id": [
                    {
                        "project": {
                            "id": "proj-1",
                            "url": "u",
                            "name": "O",
                            "content": _STORE_BODY,
                        }
                    },
                    {"project": {"content": _STORE_BODY}},
                ],
            }
        )
        added = store.add_objective_node(
            objective_id="proj-1", phase=2, description="Beta work", depends_on=("1.1",)
        )
        assert added.node_id == "2.1"
        [(_, rvars)] = _queries(fake, "issueRelationCreate(")
        relation = _input_payload(rvars)
        assert relation["issueId"] == "i-11"  # dep UUID (from _find_node_issue)
        assert relation["relatedIssueId"] == "i-22"  # new node's create-time UUID
        assert not _queries(fake, "UuidForIssue")

    def test_add_objective_node_dry_run_writes_nothing(self) -> None:
        n11 = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        store, fake = _make_project_store(
            {
                "issues(first": [
                    {
                        "project": {
                            "issues": _page([_node_issue(n11, uuid="i-11", identifier="ENG-11")])
                        }
                    }
                ],
                "inverseRelations(": [_blocked_by()],
                "project(id": [
                    {"project": {"id": "proj-1", "url": "u", "name": "O", "content": _STORE_BODY}}
                ],
            }
        )
        added = store.add_objective_node(
            objective_id="proj-1", phase=1, description="Beta work", dry_run=True
        )
        assert added == objective_store.ObjectiveNodeAdd(
            objective_id="proj-1", node_id="1.2", comment_updated=False, dry_run=True
        )
        assert not _queries(fake, "issueCreate(")
        assert not _queries(fake, "projectMilestoneCreate(")

    # ----------------------------------------------------------------- update_objective_body

    def test_update_objective_body_splices_overview(self) -> None:
        overview = _overview_with_region("01RUN", "old prose")
        store, fake = _make_project_store(
            {
                "project(id": [{"project": {"content": overview}}],
                "projectUpdate(": [{"projectUpdate": {"success": True}}],
            }
        )
        result = store.update_objective_body(objective_id="proj-1", prose="new prose")
        assert result == objective_store.ObjectiveBodyUpdate(
            objective_id="proj-1", comment_id=None, updated=True, dry_run=False
        )
        [(_, variables)] = _queries(fake, "projectUpdate(")
        content = cast("str", _input_payload(variables)["content"])
        assert "new prose" in content
        assert "old prose" not in content
        assert "perk:objective-reconcilable" in content  # region markers preserved (inline-code)
        assert "<!--" not in content

    def test_update_objective_body_no_region_raises(self) -> None:
        store, _ = _make_project_store(
            {"project(id": [{"project": {"content": _overview_for("01RUN")}}]}
        )
        with pytest.raises(ObjectiveStoreError, match="no reconcilable region"):
            store.update_objective_body(objective_id="proj-1", prose="x")

    def test_update_objective_body_absent_project_raises(self) -> None:
        store, _ = _make_project_store({"project(id": [_project_not_found()]})
        with pytest.raises(ObjectiveStoreError, match="not found"):
            store.update_objective_body(objective_id="p-gone", prose="x")

    def test_update_objective_body_dry_run_writes_nothing(self) -> None:
        overview = _overview_with_region("01RUN", "old prose")
        store, fake = _make_project_store({"project(id": [{"project": {"content": overview}}]})
        result = store.update_objective_body(objective_id="proj-1", prose="new prose", dry_run=True)
        assert result.dry_run is True
        assert not _queries(fake, "projectUpdate(")

    # ----------------------------------------------------------------- update_objective_header

    def test_update_objective_header_merges_field(self) -> None:
        store, fake = _make_project_store(
            {
                "project(id": [{"project": {"content": _overview_for("01RUN")}}],
                "projectUpdate(": [{"projectUpdate": {"success": True}}],
            }
        )
        result = store.update_objective_header(objective_id="proj-1", fields={"status": "done"})
        assert result == objective_store.ObjectiveHeaderUpdate(
            fields_updated=("status",), dry_run=False
        )
        [(_, variables)] = _queries(fake, "projectUpdate(")
        content = cast("str", _input_payload(variables)["content"])
        header = plan.find_metadata_block(content, objective.OBJECTIVE_HEADER_KEY)
        assert header is not None
        assert header["status"] == "done"
        assert header["run_id"] == "01RUN"  # existing fields preserved

    def test_update_objective_header_unknown_field_raises(self) -> None:
        store, _ = _make_project_store(
            {"project(id": [{"project": {"content": _overview_for("01RUN")}}]}
        )
        with pytest.raises(ObjectiveStoreError, match="unknown objective-header field"):
            store.update_objective_header(objective_id="proj-1", fields={"bogus": 1})

    def test_update_objective_header_dry_run_writes_nothing(self) -> None:
        store, fake = _make_project_store(
            {"project(id": [{"project": {"content": _overview_for("01RUN")}}]}
        )
        result = store.update_objective_header(
            objective_id="proj-1", fields={"status": "done"}, dry_run=True
        )
        assert result.dry_run is True
        assert not _queries(fake, "projectUpdate(")

    # ----------------------------------------------------------------- save_node_plan (Node 3.4)

    def _save_node_responses(
        self,
        *,
        node: objective.ObjectiveNode,
        uuid: str = "i-1",
        identifier: str = "ENG-1",
        comments: list[dict[str, object]] | None = None,
    ) -> dict[str, list[object]]:
        return {
            "issues(first": [
                {
                    "project": {
                        "issues": _page([_node_issue(node, uuid=uuid, identifier=identifier)])
                    }
                }
            ],
            "issueUpdate(": [{"issueUpdate": {"success": True}}],
            "comments(first": [{"issue": {"comments": _page(comments or [])}}],
            "commentCreate(": [{"commentCreate": {"success": True}}],
            "commentUpdate(": [{"commentUpdate": {"success": True}}],
        }

    def test_save_node_plan_writes_into_node_issue(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.IN_PROGRESS, slug="a"
        )
        store, fake = _make_project_store(self._save_node_responses(node=node))
        header_fields = plan.PlanHeader(run_id="01RUN", created="t").to_data()
        ref = store.save_node_plan(
            objective_id="proj-1",
            node_id="1.1",
            header_fields=header_fields,
            plan_markdown="# My Plan\n\nbody text\n",
        )
        # Returns the node-issue ref (existed=True): the node-issue IS the plan issue.
        assert ref == objective_store.ObjectiveRef(id="ENG-1", url="u/ENG-1", existed=True)
        # (1) the description write merges an inline-code plan-header WITHOUT disturbing the
        # objective-node block or the prose, and stays inline-code (no HTML).
        [(_, uvars)] = _queries(fake, "issueUpdate(")
        desc = cast("str", _input_payload(uvars)["description"])
        assert plan.find_metadata_block(desc, plan.PLAN_HEADER_KEY) is not None
        assert plan.find_metadata_block(desc, objective.OBJECTIVE_NODE_KEY) is not None
        assert "Alpha" in desc
        assert "<!--" not in desc
        # the node-issue description leads with the copyable `perk impl <ENG-N>` callout
        assert desc.startswith("**Implement this plan:**")
        assert "perk impl ENG-1" in desc
        # (2) the plan body is upserted as a single inline-code comment (create path here).
        [(_, cvars)] = _queries(fake, "commentCreate(")
        body = cast("str", _input_payload(cvars)["body"])
        assert plan.extract_plan_body(body) == "# My Plan\n\nbody text"
        assert "<details>" not in body  # inline-code, never the lossy HTML form
        assert not _queries(fake, "commentUpdate(")

    def test_save_node_plan_upserts_existing_body_comment(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.IN_PROGRESS
        )
        existing: dict[str, object] = {
            "id": "c-1",
            "body": plan.render_plan_body("# Old\n\nold body\n", style="inline-code"),
            "createdAt": "2026-01-01T00:00:00Z",
        }
        store, fake = _make_project_store(self._save_node_responses(node=node, comments=[existing]))
        store.save_node_plan(
            objective_id="proj-1",
            node_id="1.1",
            header_fields=plan.PlanHeader(run_id="01RUN", created="t").to_data(),
            plan_markdown="# New\n\nnew body\n",
        )
        # Idempotent: the existing plan-body comment is PATCHed, never a duplicate create.
        [(_, uvars)] = _queries(fake, "commentUpdate(")
        assert uvars["id"] == "c-1"
        body = cast("str", _input_payload(uvars)["body"])
        assert plan.extract_plan_body(body) == "# New\n\nnew body"
        assert not _queries(fake, "commentCreate(")

    def test_save_node_plan_does_not_duplicate_callout_on_resave(self) -> None:
        # The node description already carries the `perk impl ENG-1` callout (a prior save); a
        # re-save must not prepend a second one (idempotent on the command string).
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.IN_PROGRESS, slug="a"
        )
        base_desc = cast("str", _node_issue(node, uuid="i-1", identifier="ENG-1")["description"])
        existing_desc = plan.plan_callout("ENG-1") + "\n\n" + base_desc
        responses = self._save_node_responses(node=node)
        responses["issues(first"] = [
            {
                "project": {
                    "issues": _page(
                        [
                            {
                                "id": "i-1",
                                "identifier": "ENG-1",
                                "url": "u/ENG-1",
                                "description": existing_desc,
                            }
                        ]
                    )
                }
            }
        ]
        store, fake = _make_project_store(responses)
        store.save_node_plan(
            objective_id="proj-1",
            node_id="1.1",
            header_fields=plan.PlanHeader(run_id="01RUN", created="t").to_data(),
            plan_markdown="# My Plan\n\nbody\n",
        )
        [(_, uvars)] = _queries(fake, "issueUpdate(")
        desc = cast("str", _input_payload(uvars)["description"])
        assert desc.count("perk impl ENG-1") == 1

    def test_save_node_plan_node_not_found_raises(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        store, _ = _make_project_store(
            {
                "issues(first": [
                    {
                        "project": {
                            "issues": _page([_node_issue(node, uuid="i-1", identifier="ENG-1")])
                        }
                    }
                ]
            }
        )
        with pytest.raises(ObjectiveStoreError, match=r"objective node '9.9' not found"):
            store.save_node_plan(
                objective_id="proj-1",
                node_id="9.9",
                header_fields={"run_id": "01RUN"},
                plan_markdown="# p",
            )

    def test_save_node_plan_dry_run_returns_none(self) -> None:
        store, fake = _make_project_store()
        ref = store.save_node_plan(
            objective_id="proj-1",
            node_id="1.1",
            header_fields={"run_id": "01RUN"},
            plan_markdown="# p",
            dry_run=True,
        )
        assert ref is None
        assert fake.requests == []

    # ----------------------------------------------------------------- close_objective (Node 3.4)

    def test_close_objective_marks_project_complete(self) -> None:
        store, fake = _make_project_store(
            {"projectUpdate(": [{"projectUpdate": {"success": True}}]}
        )
        assert store.close_objective(objective_id="proj-1") is True
        [(_, variables)] = _queries(fake, "projectUpdate(")
        assert variables["id"] == "proj-1"
        assert _input_payload(variables) == {"state": "completed"}

    def test_close_objective_dry_run_writes_nothing(self) -> None:
        store, fake = _make_project_store()
        assert store.close_objective(objective_id="proj-1", dry_run=True) is False
        assert fake.requests == []

    def test_close_objective_failure_raises(self) -> None:
        store, _ = _make_project_store({"projectUpdate(": [{"projectUpdate": {"success": False}}]})
        with pytest.raises(ObjectiveStoreError, match="failed to set state"):
            store.close_objective(objective_id="proj-1")

    # ----------------------------------------------------------------- post_status_update (4.3)

    def test_post_status_update_posts_project_update(self) -> None:
        store, fake = _make_project_store(
            {
                "projectUpdateCreate(": [
                    {"projectUpdateCreate": {"success": True, "projectUpdate": {"id": "u-1"}}}
                ]
            }
        )
        assert store.post_status_update(objective_id="proj-1", body="**Plan landed**") is True
        [(_, variables)] = _queries(fake, "projectUpdateCreate(")
        assert _input_payload(variables) == {"projectId": "proj-1", "body": "**Plan landed**"}

    def test_post_status_update_dry_run_writes_nothing(self) -> None:
        store, fake = _make_project_store()
        assert store.post_status_update(objective_id="proj-1", body="x", dry_run=True) is False
        assert fake.requests == []

    def test_post_status_update_failure_raises(self) -> None:
        store, _ = _make_project_store(
            {"projectUpdateCreate(": [{"projectUpdateCreate": {"success": False}}]}
        )
        with pytest.raises(ObjectiveStoreError, match="failed to create Linear project update"):
            store.post_status_update(objective_id="proj-1", body="x")


class TestReadNodeEngagement:
    """`read_node_engagement` (Objective #682, Node 2.1): node-keyed engagement over the project
    store (honest) + the empty no-ops on the issue-backed store."""

    def _node(self) -> objective.ObjectiveNode:
        return objective.ObjectiveNode(
            id="2.1", description="Gamma", status=objective.NodeStatus.PENDING, slug="gamma"
        )

    def _responses(self) -> dict[str, list[object]]:
        node = self._node()
        return {
            # _find_node_issue → project_issues → resolves node 2.1 to UUID i-21.
            "project(id: $id)": [
                {
                    "project": {
                        "issues": _page([_node_issue(node, uuid="i-21", identifier="ENG-21")])
                    }
                }
            ],
            # _comments_with_authors(i-21)
            "botActor": [
                {
                    "issue": {
                        "comments": _page(
                            [
                                {
                                    "id": "c-1",
                                    "body": "please scope this down",
                                    "createdAt": "2026-03-01",
                                    "editedAt": None,
                                    "user": {"id": "u-1", "name": "ada", "displayName": "Ada L"},
                                    "botActor": None,
                                }
                            ]
                        )
                    }
                }
            ],
            # _description_edits(i-21)
            "descriptionUpdatedBy": [
                {
                    "issue": {
                        "history": _page(
                            [
                                {
                                    "id": "h-1",
                                    "createdAt": "2026-03-02",
                                    "actor": {"id": "u-1", "name": "Ada"},
                                    "descriptionUpdatedBy": {"id": "u-1", "name": "Ada"},
                                }
                            ]
                        )
                    }
                }
            ],
        }

    def test_resolves_node_issue_and_maps_comments_and_edits(self) -> None:
        store, _ = _make_project_store(self._responses())
        ne = store.read_node_engagement(objective_id="proj-1", node_id="2.1")
        assert isinstance(ne, engagement.NodeEngagement)
        assert [c.id for c in ne.comments] == ["c-1"]
        assert ne.comments[0].author.kind == "human"
        assert ne.comments[0].author.display_name == "Ada L"
        assert ne.comments[0].body == "please scope this down"
        assert len(ne.description_edits) == 1
        assert ne.description_edits[0].created_at == "2026-03-02"
        assert ne.description_edits[0].diff is None

    def test_unknown_node_yields_empty(self) -> None:
        # project_issues resolves no matching node-issue → empty bundle (no comment/history query).
        store, fake = _make_project_store(
            {
                "project(id: $id)": [
                    {
                        "project": {
                            "issues": _page(
                                [_node_issue(self._node(), uuid="i-21", identifier="ENG-21")]
                            )
                        }
                    }
                ]
            }
        )
        ne = store.read_node_engagement(objective_id="proj-1", node_id="9.9")
        assert ne is engagement.EMPTY_NODE_ENGAGEMENT
        assert _queries(fake, "botActor") == []

    def test_issue_backed_store_is_empty(self) -> None:
        store, fake = _make_store()
        ne = store.read_node_engagement(objective_id="ENG-7", node_id="2.1")
        assert ne is engagement.EMPTY_NODE_ENGAGEMENT
        assert fake.requests == []  # honest no-op: no network


class TestReadObjectiveEngagement:
    """`read_comments` / `read_description_edits` on the project-backed store (Objective #682,
    Node 2.3): honest over the Linear project's comments; description edits stay an honest empty."""

    def _comment_node(self, cid: str, created_at: str) -> dict[str, object]:
        return {
            "id": cid,
            "body": "discuss the objective",
            "createdAt": created_at,
            "editedAt": None,
            "user": {"id": "u-1", "name": "ada", "displayName": "Ada L"},
            "botActor": None,
        }

    def test_read_comments_maps_and_orders_ascending(self) -> None:
        store, fake = _make_project_store(
            {
                # _project_comments(proj-1) — returned out of order to prove the ascending sort.
                "botActor": [
                    {
                        "project": {
                            "comments": _page(
                                [
                                    self._comment_node("c-2", "2026-03-02"),
                                    self._comment_node("c-1", "2026-03-01"),
                                ]
                            )
                        }
                    }
                ]
            }
        )
        comments = store.read_comments(objective_id="proj-1")
        assert [c.id for c in comments] == ["c-1", "c-2"]
        assert comments[0].author.kind == "human"
        assert comments[0].author.display_name == "Ada L"
        assert comments[0].body == "discuss the objective"
        # The query was over the project's comment connection.
        assert _queries(fake, "project(id: $id)")
        assert _queries(fake, "comments(first")

    def test_read_description_edits_is_honest_empty(self) -> None:
        # Linear projects expose no description-edit-history primitive — honest () with no network.
        store, fake = _make_project_store({})
        assert store.read_description_edits(objective_id="proj-1") == ()
        assert fake.requests == []

    def test_infra_failure_raises_objective_store_error(self) -> None:
        store, _ = _make_project_store(
            {"botActor": [LinearGraphQLError("Linear GraphQL error: boom", codes=())]}
        )
        with pytest.raises(ObjectiveStoreError, match="boom"):
            store.read_comments(objective_id="proj-1")
