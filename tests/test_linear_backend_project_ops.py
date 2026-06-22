from pathlib import Path

import pytest
from _linear_fakes import (
    _LABEL_ABSENT,
    _LABEL_FOUND,
    _TEAM_RESPONSE,
    _FakeLinear,
    _input_payload,
    _milestone_create,
    _page,
    _project_not_found,
    _queries,
)

from perk import objective, plan
from perk.backends import linear_backend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    LinearGraphQLError,
)

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
