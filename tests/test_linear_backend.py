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
from perk.backends import issue_backend, linear_backend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import LinearGraphQLError
from perk.backends.linear_backend import LinearIssueBackend, to_linear_markdown
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


class _FakeLinear:
    """A scripted ``GraphQLClient``: records every ``(query, variables)`` pair; responses keyed
    by query-substring match in insertion order. A queue with >1 entries pops per call (the last
    entry is then reused); an ``Exception`` entry is raised."""

    def __init__(self, responses: dict[str, list[object]] | None = None) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._responses = {key: list(queue) for key, queue in (responses or {}).items()}

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
                "UuidForIssue": [{"issue": {"id": "uuid-1"}}, {"issue": {"id": "uuid-2"}}],
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [_STATES_RESPONSE],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        assert backend.close_issue(issue_id="ENG-1") is True
        [(_, variables)] = _queries(fake, "issueUpdate(")
        assert variables["input"] == {"stateId": "state-done"}
        # the mutation id is the resolved UUID, never the boundary identifier
        assert variables["id"] == "uuid-1"
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

    def test_absent_label_created_team_scoped_with_hash_color(self) -> None:
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
        assert variables["input"] == {
            "name": "perk:plan",
            "color": "#1f883d",
            "description": "d",
            "teamId": "team-1",
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
                "UuidForIssue": [{"issue": {"id": "uuid-iss-1"}}],
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
        assert title_vars["id"] == "uuid-iss-1"  # mutation id resolved to the UUID

    def test_update_plan_issue_posts_fresh_on_a_legacy_issue(self) -> None:
        backend, fake = _make_backend(
            {
                "UuidForIssue": [{"issue": {"id": "uuid-iss-1"}}],
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

    def test_update_plan_header_merges_form_preserving(self) -> None:
        description = _inline_plan_description("01HDR")
        backend, fake = _make_backend(
            {
                "issue(id": [{"issue": {"id": "iss-1", "description": description}}],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"})
        assert update == issue_backend.PlanHeaderUpdate(fields_updated=("pr",), dry_run=False)
        [(_, variables)] = _queries(fake, "issueUpdate(")
        update_input = _input_payload(variables)
        new_description = update_input["description"]
        assert isinstance(new_description, str)
        assert "<!--" not in new_description and "<details>" not in new_description
        header = plan.find_metadata_block(new_description, plan.PLAN_HEADER_KEY)
        assert header is not None and header["pr"] == "12" and header["run_id"] == "01HDR"

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
    return LinearGraphQLError("Linear GraphQL error: Entity not found", codes=())


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
                "UuidForIssue": [{"issue": {"id": "uuid-iss-1"}}],
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
                "UuidForIssue": [{"issue": {"id": "uuid-iss-1"}}],
                "commentCreate(": [{"commentCreate": {"success": True}}],
            }
        )
        result = backend.add_issue_comment(issue_id="ENG-1", body="<!-- perk:run-report:X -->\nhi")
        assert result == issue_backend.CommentResult(posted=True)
        [(_, variables)] = _queries(fake, "commentCreate(")
        create_input = _input_payload(variables)
        assert create_input["body"] == "`perk:run-report:X`\nhi"
        assert create_input["issueId"] == "uuid-iss-1"  # issueId resolved to the UUID


class TestCloseOps:
    def test_close_issue_dry_run_returns_false_with_no_requests(self) -> None:
        backend, fake = _make_backend()
        assert backend.close_issue(issue_id="iss-1", dry_run=True) is False
        assert fake.requests == []

    def test_close_issue_is_fail_loud(self) -> None:
        backend, _ = _make_backend(
            {
                "UuidForIssue": [{"issue": {"id": "uuid-1"}}],
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
        backend, fake = _make_backend(
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
        found = backend.find_objective_issue(run_id="01OBJ")
        assert found == issue_backend.IssueRef(id="ENG-9", url="u", existed=True)
        [(_, variables)] = _queries(fake, "issues(first")
        assert variables["label"] == "perk:objective"

    def test_no_match_is_none_after_exhausting_pages(self) -> None:
        page1 = {"issues": _page([], has_next=True, cursor="C1")}
        page2 = {"issues": _page([])}
        backend, fake = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [page1, page2]}
        )
        assert backend.find_objective_issue(run_id="01NOPE") is None
        assert len(_queries(fake, "issues(first")) == 2

    def test_infra_errors_propagate(self) -> None:
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [LinearGraphQLError("Linear GraphQL error: boom", codes=())],
            }
        )
        with pytest.raises(IssueBackendError, match="boom"):
            backend.find_objective_issue(run_id="01NOPE")


class TestCreateObjectiveIssue:
    def test_dry_run_shape(self) -> None:
        backend, fake = _make_backend()
        ref = backend.create_objective_issue(
            title="t", body="b", run_id="01DRY", roadmap_nodes=_objective_nodes(), dry_run=True
        )
        assert ref == issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        assert fake.requests == []

    def test_idempotent_find_then_return(self) -> None:
        description = _inline_objective_description("01DUP")
        backend, fake = _make_backend(
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
        ref = backend.create_objective_issue(
            title="t", body="b", run_id="01DUP", roadmap_nodes=_objective_nodes()
        )
        assert ref == issue_backend.IssueRef(id="ENG-9", url="u", existed=True)
        assert not _queries(fake, "issueCreate(")

    def test_empty_roadmap_raises(self) -> None:
        backend, _ = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]}
        )
        with pytest.raises(IssueBackendError, match="objective roadmap is empty"):
            backend.create_objective_issue(title="t", body="prose only", run_id="01EMPTY")

    def test_invalid_embedded_roadmap_raises(self) -> None:
        bad = plan.render_metadata_block(
            objective.OBJECTIVE_ROADMAP_KEY, {"schema_version": "99", "nodes": []}
        )
        backend, _ = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]}
        )
        with pytest.raises(IssueBackendError, match="invalid objective roadmap"):
            backend.create_objective_issue(title="t", body=bad, run_id="01BAD")

    def test_full_two_step_create_with_comment_id_backfill(self) -> None:
        backend, fake = _make_backend(
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
        ref = backend.create_objective_issue(
            title="t",
            body="The objective prose.",
            run_id="01NEW",
            roadmap_nodes=_objective_nodes(),
        )
        assert ref == issue_backend.IssueRef(id="ENG-9", url="u-obj", existed=False)

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
        assert comment_input["issueId"] == "obj-1"
        comment_body = comment_input["body"]
        assert isinstance(comment_body, str)
        assert "`perk:roadmap-table`" in comment_body
        assert "`perk:objective-reconcilable`" in comment_body
        assert "The objective prose." in comment_body
        assert "<!--" not in comment_body

        # 3) the captured comment UUID is backfilled into the header (form-preserving)
        [(_, update_vars)] = _queries(fake, "issueUpdate(")
        new_description = _input_payload(update_vars)["description"]
        assert isinstance(new_description, str)
        assert "<!--" not in new_description
        backfilled = plan.find_metadata_block(new_description, objective.OBJECTIVE_HEADER_KEY)
        assert backfilled is not None
        assert backfilled["objective_comment_id"] == "cmt-uuid-1"


class TestGetObjective:
    def test_happy_path(self) -> None:
        description = _inline_objective_description("01OBJ", comment_id="cmt-1")
        backend, _ = _make_backend({"issue(id": [_objective_issue_response(description)]})
        state = backend.get_objective(issue_id="ENG-9")
        assert state is not None
        assert state.id == "ENG-9" and state.url == "u-obj" and state.title == "Obj"
        assert state.header["run_id"] == "01OBJ"
        assert state.header["objective_comment_id"] == "cmt-1"
        assert [n.id for n in state.nodes] == ["1.1", "1.2"]

    def test_missing_issue_is_none(self) -> None:
        backend, _ = _make_backend({"issue(id": [_not_found_error()]})
        assert backend.get_objective(issue_id="obj-gone") is None

    def test_invalid_roadmap_raises(self) -> None:
        broken = "`perk:metadata-block:objective-roadmap`\n\n```yaml\nnodes: [\n```"
        backend, _ = _make_backend({"issue(id": [_objective_issue_response(broken)]})
        with pytest.raises(IssueBackendError, match="invalid objective roadmap on 'obj-1'"):
            backend.get_objective(issue_id="obj-1")


class TestUpdateObjectiveHeader:
    def test_unknown_fields_rejected_lbyl(self) -> None:
        backend, fake = _make_backend()
        with pytest.raises(IssueBackendError, match="unknown objective-header field"):
            backend.update_objective_header(issue_id="obj-1", fields={"nope": 1})
        assert fake.requests == []

    def test_dry_run_composes_only(self) -> None:
        description = _inline_objective_description("01HDR")
        backend, fake = _make_backend({"issue(id": [_objective_issue_response(description)]})
        update = backend.update_objective_header(
            issue_id="obj-1", fields={"status": "complete"}, dry_run=True
        )
        assert update == issue_backend.ObjectiveHeaderUpdate(
            fields_updated=("status",), dry_run=True
        )
        assert not _queries(fake, "issueUpdate(")

    def test_write_path_preserves_inline_code_form(self) -> None:
        description = _inline_objective_description("01HDR")
        backend, fake = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        update = backend.update_objective_header(issue_id="obj-1", fields={"status": "complete"})
        assert update == issue_backend.ObjectiveHeaderUpdate(
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
        backend, _ = _make_backend({"issue(id": [_objective_issue_response(description)]})
        with pytest.raises(IssueBackendError, match=r"objective node '9\.9' not found on 'obj-1'"):
            backend.update_objective_node(
                issue_id="obj-1", node_id="9.9", status=objective.NodeStatus.DONE
            )

    def test_dry_run_shape(self) -> None:
        description = _inline_objective_description("01N")
        backend, fake = _make_backend({"issue(id": [_objective_issue_response(description)]})
        update = backend.update_objective_node(
            issue_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE, dry_run=True
        )
        assert update == issue_backend.ObjectiveNodeUpdate(
            issue_id="obj-1", node_id="1.2", comment_updated=False, dry_run=True
        )
        assert not _queries(fake, "issueUpdate(")

    def test_authoritative_write_plus_comment_rerender(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-uuid-1")
        comment_body = to_linear_markdown(
            objective.render_body_comment(_objective_nodes(), prose="Prose.")
        )
        backend, fake = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [{"comment": {"body": comment_body}}],
                "commentUpdate(": [{"commentUpdate": {"success": True}}],
            }
        )
        update = backend.update_objective_node(
            issue_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update == issue_backend.ObjectiveNodeUpdate(
            issue_id="obj-1", node_id="1.2", comment_updated=True, dry_run=False
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
        backend, fake = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        update = backend.update_objective_node(
            issue_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update.comment_updated is False
        assert len(_queries(fake, "issueUpdate(")) == 1  # roadmap still written

    def test_comment_not_found_degrades(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-gone")
        backend, fake = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [_not_found_error()],
            }
        )
        update = backend.update_objective_node(
            issue_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update.comment_updated is False
        assert not _queries(fake, "commentUpdate(")

    def test_markerless_comment_degrades(self) -> None:
        description = _inline_objective_description("01N", comment_id="cmt-1")
        backend, fake = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
                "comment(id": [{"comment": {"body": "no table markers here"}}],
            }
        )
        update = backend.update_objective_node(
            issue_id="obj-1", node_id="1.2", status=objective.NodeStatus.DONE
        )
        assert update.comment_updated is False
        assert not _queries(fake, "commentUpdate(")


class TestUpdateObjectiveBody:
    def test_missing_comment_id_raises(self) -> None:
        description = _inline_objective_description("01B", comment_id=None)
        backend, _ = _make_backend({"issue(id": [_objective_issue_response(description)]})
        with pytest.raises(IssueBackendError, match="objective 'obj-1' has no body comment"):
            backend.update_objective_body(issue_id="obj-1", prose="p")

    def test_comment_not_found_raises(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-gone")
        backend, _ = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [_not_found_error()],
            }
        )
        with pytest.raises(IssueBackendError, match="has no body comment"):
            backend.update_objective_body(issue_id="obj-1", prose="p")

    def test_no_reconcilable_region_raises(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-1")
        backend, _ = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [{"comment": {"body": "no markers"}}],
            }
        )
        with pytest.raises(IssueBackendError, match="no reconcilable region"):
            backend.update_objective_body(issue_id="obj-1", prose="p")

    def test_dry_run_composes_only(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-1")
        comment_body = to_linear_markdown(
            objective.render_body_comment(_objective_nodes(), prose="Old.")
        )
        backend, fake = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [{"comment": {"body": comment_body}}],
            }
        )
        update = backend.update_objective_body(issue_id="obj-1", prose="New.", dry_run=True)
        assert update == issue_backend.ObjectiveBodyUpdate(
            issue_id="obj-1", comment_id="cmt-1", updated=False, dry_run=True
        )
        assert not _queries(fake, "commentUpdate(")

    def test_splice_preserves_immutable_tail(self) -> None:
        description = _inline_objective_description("01B", comment_id="cmt-1")
        comment_body = (
            to_linear_markdown(objective.render_body_comment(_objective_nodes(), prose="Old."))
            + "\n## Immutable history\nnever touch this\n"
        )
        backend, fake = _make_backend(
            {
                "issue(id": [_objective_issue_response(description)],
                "comment(id": [{"comment": {"body": comment_body}}],
                "commentUpdate(": [{"commentUpdate": {"success": True}}],
            }
        )
        update = backend.update_objective_body(issue_id="obj-1", prose="New prose.")
        assert update == issue_backend.ObjectiveBodyUpdate(
            issue_id="obj-1", comment_id="cmt-1", updated=True, dry_run=False
        )
        [(_, patch_vars)] = _queries(fake, "commentUpdate(")
        assert patch_vars["id"] == "cmt-1"
        patched = _input_payload(patch_vars)["body"]
        assert isinstance(patched, str)
        assert "New prose." in patched and "Old." not in patched
        assert "never touch this" in patched  # the Immutable tail is preserved
        assert "`perk:roadmap-table`" in patched  # the Mechanical block above is preserved
        assert "<!--" not in patched


class TestUuidResolution:
    """The D3 mutation-path identifier→UUID resolution (`_uuid_for`): cached, read-seeded."""

    def test_uuid_for_resolves_once_and_caches(self) -> None:
        backend, fake = _make_backend(
            {
                "UuidForIssue": [{"issue": {"id": "uuid-1"}}],
                "commentCreate(": [{"commentCreate": {"success": True}}],
            }
        )
        backend.add_issue_comment(issue_id="ENG-1", body="a")
        backend.add_issue_comment(issue_id="ENG-1", body="b")
        assert len(_queries(fake, "UuidForIssue")) == 1  # second mutation hits the cache
        for _, variables in _queries(fake, "commentCreate("):
            assert _input_payload(variables)["issueId"] == "uuid-1"

    def test_issue_reads_seed_the_uuid_cache(self) -> None:
        # update_plan_header reads the issue first; the follow-up mutation must not issue a
        # separate UuidForIssue lookup (the read seeded the cache).
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
        assert variables["id"] == "uuid-1"

    def test_uuid_for_missing_entity_raises_not_found(self) -> None:
        backend, _ = _make_backend(
            {
                "UuidForIssue": [_not_found_error()],
            }
        )
        with pytest.raises(IssueBackendError, match="'ENG-404' not found"):
            backend.add_issue_comment(issue_id="ENG-404", body="x")


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
        assert len(_queries(fake, "issueLabels(filter")) == 4

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
        )
        assert readiness.missing_labels == ()
        assert len(_queries(fake, "issueLabelCreate")) == 4

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
