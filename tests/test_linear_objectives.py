import dataclasses
from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import (
    _LABEL_FOUND,
    _STATES_RESPONSE,
    _TEAM_RESPONSE,
    _input_payload,
    _make_backend,
    _make_store,
    _no_issues,
    _not_found_error,
    _page,
    _queries,
)

from perk import objective, plan
from perk.backends import issue_backend, linear, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    attachments,
    to_linear_markdown,
)
from perk.backends.linear.client import (
    LinearGraphQLError,
)
from perk.backends.objective_store import ObjectiveStoreError


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
    origin: str | None = None,
    delivery: str | None = None,
) -> str:
    header = objective.ObjectiveHeader(
        run_id=run_id,
        created="t",
        objective_comment_id=comment_id,
        status="active",
        origin=origin,
        delivery=delivery,
    )
    header_block = plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, objective.render_header_block(header), style="inline-code"
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


class TestObjectiveCompletionCandidates:
    """The dormant store's bounded one-page label read (Protocol conformance): a single
    ``first: 50`` request, never a cursor walk, sorted ``createdAt``-descending locally."""

    def test_one_page_label_read_sorted_newest_first(self) -> None:
        rows: list[dict[str, object]] = [
            {
                "identifier": "ENG-1",
                "title": "Old",
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "identifier": "ENG-2",
                "title": "New",
                "createdAt": "2026-02-01T00:00:00Z",
            },
        ]
        store, fake = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first: 50, filter": [{"issues": _page(rows, has_next=True, cursor="c")}],
            }
        )
        result = store.list_objective_completion_candidates()
        assert [(r.id, r.title) for r in result] == [("ENG-2", "New"), ("ENG-1", "Old")]
        # Exactly ONE request — hasNextPage: true never triggers a cursor walk.
        scans = _queries(fake, "issues(first: 50, filter")
        assert len(scans) == 1
        [(query, variables)] = scans
        assert variables["label"] == objective.OBJECTIVE_LABEL
        assert "$cursor" not in query and "cursor" not in variables
        # Only the consumed fields ride the selection.
        assert "nodes { identifier title createdAt }" in query

    def test_raises_on_query_failure(self) -> None:
        failing, _ = _make_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first: 50, filter": [
                    LinearGraphQLError("Linear GraphQL error: down", codes=())
                ],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="down"):
            failing.list_objective_completion_candidates()


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
        # The issue-backed store threads `base` into the composed inline-code
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

    def test_create_persists_origin_into_objective_header(self) -> None:
        # The dormant store still stamps origin at create (it composes a real header) — only
        # the lookup refuses (see TestFindOpenObjectiveByOrigin). The backfill reread is
        # origin-bearing so the final issueUpdate proves the comment-id merge RETAINS origin
        # (the dormant-writer round-trip regression).
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
                "issue(id": [
                    _objective_issue_response(
                        _inline_objective_description("01NEW", origin="learn-dream")
                    )
                ],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        store.create_objective(
            title="t",
            body="The objective prose.",
            run_id="01NEW",
            roadmap_nodes=_objective_nodes(),
            origin=objective.ObjectiveOrigin.LEARN_DREAM,
        )
        [(_, create_vars)] = _queries(fake, "issueCreate(")
        description = _input_payload(create_vars)["description"]
        assert isinstance(description, str)
        header = plan.find_metadata_block(description, objective.OBJECTIVE_HEADER_KEY)
        assert header is not None and header["origin"] == "learn-dream"
        # The comment-id backfill (an unrelated header merge) must not erase the stamp.
        [(_, update_vars)] = _queries(fake, "issueUpdate(")
        backfilled_description = _input_payload(update_vars)["description"]
        assert isinstance(backfilled_description, str)
        backfilled = plan.find_metadata_block(
            backfilled_description, objective.OBJECTIVE_HEADER_KEY
        )
        assert backfilled is not None
        assert backfilled["origin"] == "learn-dream"
        assert backfilled["objective_comment_id"] == "cmt-uuid-1"


class TestFindOpenObjectiveByOrigin:
    def test_refuses_with_a_raise_never_none(self) -> None:
        # The dormant store cannot answer the exhaustive-or-raise lookup authoritatively — it
        # RAISES (deliberately outside the → None / → False no-op family): a silent None would
        # falsely assert authoritatively-none and open a fail-closed guard.
        store, fake = _make_store()
        with pytest.raises(ObjectiveStoreError, match="does not support origin lookups"):
            store.find_open_objective_by_origin(origin=objective.ObjectiveOrigin.LEARN_DREAM)
        assert fake.requests == []


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
        assert state.state == "open"  # no positive completed/canceled state type → open

    @pytest.mark.parametrize("state_type", ["completed", "canceled"])
    def test_closed_lifecycle_state(self, state_type: str) -> None:
        description = _inline_objective_description("01OBJ", comment_id="cmt-1")
        response = _objective_issue_response(description)
        issue = cast("dict[str, object]", response["issue"])
        issue["state"] = {"type": state_type}
        store, _ = _make_store({"issue(id": [response]})
        state = store.get_objective(objective_id="ENG-9")
        assert state is not None and state.state == "closed"

    def test_missing_issue_is_none(self) -> None:
        store, _ = _make_store({"issue(id": [_not_found_error()]})
        assert store.get_objective(objective_id="obj-gone") is None

    def test_invalid_roadmap_raises(self) -> None:
        broken = "`perk:metadata-block:objective-roadmap`\n\n```yaml\nnodes: [\n```"
        store, _ = _make_store({"issue(id": [_objective_issue_response(broken)]})
        with pytest.raises(ObjectiveStoreError, match="invalid objective roadmap on 'obj-1'"):
            store.get_objective(objective_id="obj-1")


class TestJournalCarrierId:
    """The dormant issue-backed store's §8.43 carrier: the objective issue itself."""

    def test_resolving_issue_is_its_own_carrier(self) -> None:
        store, _ = _make_store({"issue(id": [_objective_issue_response("")]})
        assert store.journal_carrier_id(objective_id="ENG-9") == "ENG-9"

    def test_absent_issue_is_none(self) -> None:
        store, _ = _make_store({"issue(id": [_not_found_error()]})
        assert store.journal_carrier_id(objective_id="ENG-gone") is None

    def test_infra_failure_translates(self) -> None:
        store, _ = _make_store(
            {"issue(id": [LinearGraphQLError("Linear GraphQL error: boom", codes=())]}
        )
        with pytest.raises(ObjectiveStoreError, match="boom"):
            store.journal_carrier_id(objective_id="ENG-9")


class TestUpdateObjectiveHeader:
    def test_unknown_fields_rejected_lbyl(self) -> None:
        store, fake = _make_store()
        with pytest.raises(ObjectiveStoreError, match="unknown objective-header field"):
            store.update_objective_header(objective_id="obj-1", fields={"nope": 1})
        assert fake.requests == []

    def test_origin_merge_rejected_lbyl(self) -> None:
        # `origin` is deliberately OUTSIDE OBJECTIVE_HEADER_FIELDS (create/supersede-only).
        store, fake = _make_store()
        with pytest.raises(ObjectiveStoreError, match="unknown objective-header field"):
            store.update_objective_header(objective_id="obj-1", fields={"origin": "learn-dream"})
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

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_stacked_refuses_non_tail_append(self, dry_run: bool) -> None:
        # The store-owned tail-append guard over the same fresh description read — dry-run
        # included: a mid-roadmap phase insertion re-points inference and is refused.
        nodes = [
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING),
            objective.ObjectiveNode(id="2.1", description="B", status=objective.NodeStatus.PENDING),
        ]
        description = _inline_objective_description("01N", nodes=nodes, delivery="stacked")
        store, fake = _make_store({"issue(id": [_objective_issue_response(description)]})
        with pytest.raises(objective_store.StackedAppendRefused) as err:
            store.add_objective_node(
                objective_id="obj-1", phase=1, description="Gamma", dry_run=dry_run
            )
        assert any("resolved dependencies" in e for e in err.value.errors)
        assert not _queries(fake, "issueUpdate(")

    def test_stacked_accepts_tail_append(self) -> None:
        nodes = [
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING),
            objective.ObjectiveNode(id="2.1", description="B", status=objective.NodeStatus.PENDING),
        ]
        description = _inline_objective_description("01N", nodes=nodes, delivery="stacked")
        store, fake = _make_store(
            {
                "issue(id": [_objective_issue_response(description)],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        added = store.add_objective_node(objective_id="obj-1", phase=2, description="Gamma")
        assert added.node_id == "2.2" and added.dry_run is False
        assert len(_queries(fake, "issueUpdate(")) == 1

    def test_junk_delivery_header_refused(self) -> None:
        description = _inline_objective_description("01N", delivery="weird")
        store, fake = _make_store({"issue(id": [_objective_issue_response(description)]})
        with pytest.raises(
            objective_store.StackedAppendRefused, match="unknown objective delivery"
        ):
            store.add_objective_node(objective_id="obj-1", phase=1, description="Gamma")
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
    """The dormant issue-backed `LinearObjectiveStore`'s methods: it does NOT unify node +
    plan (`save_node_plan` → None) and `close_objective` moves the objective issue to Done."""

    def test_save_node_plan_returns_none(self) -> None:
        store, fake = _make_store()
        result = store.save_node_plan(
            objective_id="obj-1", node_id="1.1", header_fields={"run_id": "R"}, plan_markdown="# p"
        )
        assert result is None
        assert fake.requests == []

    def test_supersede_objective_returns_none(self) -> None:
        store, fake = _make_store()
        result = store.supersede_objective(
            old_objective_id="obj-1",
            title="t",
            prose="p",
            run_id="R",
            roadmap_nodes=[
                objective.ObjectiveNode(
                    id="1.1", description="A", status=objective.NodeStatus.PENDING
                )
            ],
            carry_map={},
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

    def test_reopen_objective_moves_completed_issue_to_started(self) -> None:
        states_with_started: dict[str, object] = {
            "team": {
                "states": {
                    "nodes": [
                        {"id": "state-done", "name": "Done", "type": "completed", "position": 3},
                        {"id": "state-doing", "name": "Doing", "type": "started", "position": 2},
                    ]
                }
            }
        }
        store, fake = _make_store(
            {
                "issue(id": [{"issue": {"state": {"type": "completed"}}}],
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [states_with_started],
                "issueUpdate(": [{"issueUpdate": {"success": True}}],
            }
        )
        assert store.reopen_objective(objective_id="obj-1") is True
        [(_, variables)] = _queries(fake, "issueUpdate(")
        assert variables["id"] == "obj-1"
        assert _input_payload(variables) == {"stateId": "state-doing"}

    def test_reopen_objective_noop_when_not_completed(self) -> None:
        # Only a completed-type state reopens; canceled is a human cancel (not perk's to undo)
        # and the open types are already-converged no-ops.
        for state_type in ("started", "unstarted", "canceled"):
            store, fake = _make_store({"issue(id": [{"issue": {"state": {"type": state_type}}}]})
            assert store.reopen_objective(objective_id="obj-1") is False
            assert not _queries(fake, "issueUpdate(")

    def test_reopen_objective_dry_run_writes_nothing(self) -> None:
        store, fake = _make_store()
        assert store.reopen_objective(objective_id="obj-1", dry_run=True) is False
        assert fake.requests == []

    def test_reopen_objective_without_started_state_raises(self) -> None:
        # A team with no started-type workflow state is an infra anomaly, not a policy skip.
        store, _ = _make_store(
            {
                "issue(id": [{"issue": {"state": {"type": "completed"}}}],
                "teams(filter": [_TEAM_RESPONSE],
                "team(id": [_STATES_RESPONSE],  # completed/unstarted only — no started type
            }
        )
        with pytest.raises(ObjectiveStoreError, match="no 'started' workflow state"):
            store.reopen_objective(objective_id="obj-1")

    def test_post_status_update_is_noop_false(self) -> None:
        # The issue-backed store has no project status-update surface — always False,
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
        # update_plan_header reads the issue's attachments first, then upserts the plan
        # attachment — both carry the boundary identifier, never a resolved UUID, and fire no
        # UuidForIssue query.
        card = attachments.encode(attachments.PLAN_HEADER_KIND, {"run_id": "01HDR"})
        att = {
            "id": "att-1",
            "url": attachments.plan_header_url("01HDR"),
            "metadata": card.metadata,
        }
        backend, fake = _make_backend(
            {
                "issue(id": [{"issue": {"id": "uuid-1", "attachments": {"nodes": [att]}}}],
                "attachmentCreate(": [{"attachmentCreate": {"success": True}}],
            }
        )
        backend.update_plan_header(issue_id="ENG-1", fields={"pr": "12"})
        assert not _queries(fake, "UuidForIssue")
        [(_, variables)] = _queries(fake, "attachmentCreate(")
        payload = _input_payload(variables)
        assert payload["issueId"] == "ENG-1"
        assert payload["url"] == attachments.plan_header_url("01HDR")


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
    found"`` message prefix. These prove the
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
        # The resolver module (perk/backends/resolve.py) imports us at wiring time; importing it
        # back would be a cycle. Mirrors the TestImportDirection substring style. linear_backend is
        # a package (split) — `__file__` is `__init__.py` only, so scan every submodule
        # source under the package dir (mirrors tests/test_resolve.py's rglob scan).
        package_dir = Path(linear.__file__).parent
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(package_dir.glob("*.py"))
        )
        assert "perk.backends.resolve" not in source


class TestValueShapes:
    def test_issue_refs_are_frozen_with_string_ids(self) -> None:
        ref = issue_backend.IssueRef(id="uuid-1", url="u", existed=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = "x"  # ty: ignore[invalid-assignment]
