"""Tests for ``LinearIssueBackend`` — offline, scripted fake client.

The static conformance check is one annotated binding (``_make_backend``): ty fails the suite if
``LinearIssueBackend`` and the ``IssueBackend`` protocol drift. The runtime tests pin the
GitHub-twin behavior shapes (find/create idempotency, upserts, dry runs, close ops), the
Linear-safe transcoding, the team/state/label caching, and the import-direction discipline.
"""

from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import (
    _LABEL_ABSENT,
    _LABEL_FOUND,
    _STATES_RESPONSE,
    _TEAM_RESPONSE,
    _att_creates,
    _att_fields,
    _attachment_create_ok,
    _attachments_for_url_hit,
    _attachments_for_url_miss,
    _input_payload,
    _make_backend,
    _no_issues,
    _not_found_error,
    _page,
    _perk_attachment_node,
    _queries,
)

from perk import github, plan
from perk.backends import issue_backend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    attachments as linear_attachments,
)
from perk.backends.linear import (
    to_linear_markdown,
)
from perk.backends.linear._helpers import LinearIssueNodeModel
from perk.backends.linear.client import (
    LinearGraphQLError,
    _opt_dict,
    _opt_list,
    _opt_str,
)
from perk.boundary import ValidationError
from perk.github import GitHubError
from perk.run import run_report


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
        backend.list_learn_issues()
        backend.list_learn_issues()
        assert len(_queries(fake, "teams(filter")) == 1

    def test_unknown_team_raises_with_key(self) -> None:
        backend, _ = _make_backend({"teams(filter": [{"teams": {"nodes": []}}]})
        with pytest.raises(IssueBackendError, match="'ENG' not found"):
            backend.list_learn_issues()

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
    def test_find_is_one_exact_url_query(self) -> None:
        backend, fake = _make_backend(
            {
                "attachmentsForURL(": [_attachments_for_url_hit(identifier="ENG-2", url="u-b")],
            }
        )
        found = backend.find_plan_issue(run_id="01HIT")
        assert found == issue_backend.IssueRef(id="ENG-2", url="u-b", existed=True)
        # ONE workspace-wide exact-URL query on the run_id-keyed plan URL — no list-and-parse
        # scan, no team resolution.
        [(_, variables)] = _queries(fake, "attachmentsForURL(")
        assert variables["url"] == "https://perk.invalid/plan/01HIT"
        assert not _queries(fake, "issues(first")
        assert not _queries(fake, "teams(filter")

    @pytest.mark.parametrize("state_type", ["completed", "canceled"])
    def test_find_terminal_state_hit_is_not_found(self, state_type: str) -> None:
        # Parity with the legacy open-only scan: a landed/canceled plan's run_id never
        # resurrects the closed issue on a re-save.
        backend, _ = _make_backend(
            {
                "attachmentsForURL(": [
                    _attachments_for_url_hit(identifier="ENG-2", url="u-b", state_type=state_type)
                ],
            }
        )
        assert backend.find_plan_issue(run_id="01HIT") is None

    def test_find_prefers_the_open_hit_across_multiple_nodes(self) -> None:
        # The multi-hit determinism rule: a landed plan's completed issue and an open re-save
        # can share the run_id URL — the find must return the open hit regardless of the
        # server's node order (closed-first here), never mint duplicates via order luck.
        response: dict[str, object] = {
            "attachmentsForURL": {
                "nodes": [
                    {
                        "issue": {
                            "identifier": "ENG-9",
                            "url": "u-closed",
                            "state": {"type": "completed"},
                            "project": None,
                        }
                    },
                    {
                        "issue": {
                            "identifier": "ENG-10",
                            "url": "u-open",
                            "state": {"type": "unstarted"},
                            "project": None,
                        }
                    },
                ]
            }
        }
        backend, _ = _make_backend({"attachmentsForURL(": [response]})
        found = backend.find_plan_issue(run_id="01HIT")
        assert found == issue_backend.IssueRef(id="ENG-10", url="u-open", existed=True)

    def test_find_no_match_is_none_and_failure_raises(self) -> None:
        backend, _ = _make_backend({"attachmentsForURL(": [_attachments_for_url_miss()]})
        assert backend.find_plan_issue(run_id="01NOPE") is None
        failing, _ = _make_backend(
            {
                "attachmentsForURL(": [LinearGraphQLError("Linear GraphQL error: boom", codes=())],
            }
        )
        with pytest.raises(IssueBackendError, match="boom"):
            failing.find_plan_issue(run_id="01NOPE")

    def test_create_is_find_first_idempotent(self) -> None:
        backend, fake = _make_backend(
            {
                "attachmentsForURL(": [_attachments_for_url_hit(identifier="ENG-4", url="u-x")],
            }
        )
        ref = backend.create_plan_issue(
            title="t", header_fields={"run_id": "01DUP", "created": "t"}, run_id="01DUP"
        )
        assert ref == issue_backend.IssueRef(id="ENG-4", url="u-x", existed=True)
        assert not _queries(fake, "issueCreate(")

    def test_create_dry_run_shape(self) -> None:
        backend, fake = _make_backend()
        ref = backend.create_plan_issue(
            title="t", header_fields={"run_id": "01DRY"}, run_id="01DRY", dry_run=True
        )
        assert ref == issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        assert fake.requests == []

    def test_create_clean_body_with_plan_attachment(self) -> None:
        backend, fake = _make_backend(
            {
                "attachmentsForURL(": [_attachments_for_url_miss()],
                "teams(filter": [_TEAM_RESPONSE],
                "issueLabels(filter": [_LABEL_FOUND],
                "issueCreate(": [
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "iss-n", "identifier": "ENG-5", "url": "u-n"},
                        }
                    }
                ],
                "attachmentCreate(": [_attachment_create_ok()],
            }
        )
        ref = backend.create_plan_issue(
            title="t", header_fields={"run_id": "01NEW", "created": "t"}, run_id="01NEW"
        )
        assert ref == issue_backend.IssueRef(id="ENG-5", url="u-n", existed=False)
        [(_, variables)] = _queries(fake, "issueCreate(")
        input_payload = _input_payload(variables)
        # Clean-body create: the description carries NO machine state.
        assert input_payload["description"] == ""
        assert input_payload["teamId"] == "team-1"
        assert input_payload["labelIds"] == ["lbl-1"]
        # The plan-header rides the run_id-keyed native attachment.
        [att] = _att_creates(fake)
        assert att["issueId"] == "ENG-5"
        assert att["url"] == "https://perk.invalid/plan/01NEW"
        assert _att_fields(att) == {"run_id": "01NEW", "created": "t"}


class TestLearnTwins:
    def test_find_learn_issue_uses_the_learn_url_namespace(self) -> None:
        # A plan issue sharing the run_id never matches: the learn find keys on the
        # /learn/ URL namespace, disjoint from /plan/ by construction.
        backend, fake = _make_backend({"attachmentsForURL(": [_attachments_for_url_miss()]})
        assert backend.find_learn_issue(run_id="01RUN") is None
        [(_, variables)] = _queries(fake, "attachmentsForURL(")
        assert variables["url"] == "https://perk.invalid/learn/01RUN"

    def _learn_create_responses(self) -> dict[str, list[object]]:
        return {
            "attachmentsForURL(": [_attachments_for_url_miss()],
            "teams(filter": [_TEAM_RESPONSE],
            "issueLabels(filter": [_LABEL_FOUND],
            "issueCreate(": [
                {
                    "issueCreate": {
                        "success": True,
                        "issue": {"id": "iss-l", "identifier": "ENG-7", "url": "u-l"},
                    }
                }
            ],
            "attachmentCreate(": [_attachment_create_ok()],
        }

    def test_create_learn_issue_clean_body_with_verbatim_plan_id(self) -> None:
        backend, fake = _make_backend(self._learn_create_responses())
        ref = backend.create_learn_issue(
            title="t", body="learnings", run_id="01LEARN", plan_id="ENG-1"
        )
        assert ref.existed is False and ref.id == "ENG-7"
        [(_, variables)] = _queries(fake, "issueCreate(")
        # Clean-body create: the description is the learning prose only.
        assert _input_payload(variables)["description"] == "learnings\n"
        # The learn-header rides the run_id-keyed native attachment.
        [att] = _att_creates(fake)
        assert att["url"] == "https://perk.invalid/learn/01LEARN"
        header = _att_fields(att)
        assert header["run_id"] == "01LEARN"
        assert header["plan"] == "ENG-1"  # the boundary string, verbatim
        # A decision-less call omits the captured-classification fields (back-compat).
        assert "decision" not in header and "target" not in header

    def test_create_learn_issue_persists_decision_and_target(self) -> None:
        backend, fake = _make_backend(self._learn_create_responses())
        backend.create_learn_issue(
            title="t",
            body="learnings",
            run_id="01LEARN",
            plan_id="ENG-1",
            decision="NEW_DOC",
            target=None,
        )
        [att] = _att_creates(fake)
        header = _att_fields(att)
        assert header["decision"] == "NEW_DOC"
        # A None target is omitted entirely (distinguishing "no target" from a present value).
        assert "target" not in header

    def test_create_learn_issue_is_idempotent_via_find(self) -> None:
        backend, fake = _make_backend(
            {
                "attachmentsForURL(": [_attachments_for_url_hit(identifier="ENG-7", url="u-l")],
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

    def test_list_learn_issues_decodes_header_attachment(self) -> None:
        # The populated arm: the adapter owns the attachment→LearnHeader decode now, so a
        # learn-header attachment must come back as a typed header (incl. `decision`).
        row: dict[str, object] = {
            "id": "iss-1",
            "identifier": "ENG-8",
            "title": "T",
            "url": "u",
            "description": "body",
            "attachments": {
                "nodes": [
                    _perk_attachment_node(
                        linear_attachments.LEARN_HEADER_KIND,
                        {
                            "run_id": "01L",
                            "created": "t",
                            "plan": "ENG-1",
                            "decision": "SHOULD_BE_CODE",
                        },
                        url=linear_attachments.learn_header_url("01L"),
                    )
                ]
            },
        }
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [{"issues": _page([row])}],
            }
        )
        [summary] = backend.list_learn_issues()
        assert summary.header is not None
        assert summary.header.run_id == "01L"
        assert summary.header.plan == "ENG-1"
        assert summary.header.decision == "SHOULD_BE_CODE"

    def test_list_learn_issues_degrades_on_malformed_learn_attachment(self) -> None:
        # A perk-marked learn attachment with a corrupt payload_json degrades to header=None —
        # one bad attachment never bricks the whole gather (GitHub parse_learn_header parity).
        row: dict[str, object] = {
            "id": "iss-1",
            "identifier": "ENG-8",
            "title": "T",
            "url": "u",
            "description": "body",
            "attachments": {
                "nodes": [
                    {
                        "id": "a1",
                        "url": linear_attachments.learn_header_url("01L"),
                        "metadata": {
                            "source": "perk",
                            "kind": "learn-header",
                            "payload_json": "{not json",
                        },
                    }
                ]
            },
        }
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [{"issues": _page([row])}],
            }
        )
        [summary] = backend.list_learn_issues()
        assert summary.header is None  # degraded, not raised


def _pending_plan_row(
    identifier: str,
    *,
    learn_state: str | None = "pending",
    completed_at: str | None = None,
    canceled_at: str | None = None,
    attachment_nodes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """A wire-shaped closed-plan issue row for the pending-learn backlog scan."""
    if attachment_nodes is None:
        fields: dict[str, object] = {"run_id": f"01-{identifier}", "created": "t"}
        if learn_state is not None:
            fields["learn_state"] = learn_state
        attachment_nodes = [
            _perk_attachment_node(
                linear_attachments.PLAN_HEADER_KIND,
                fields,
                url=linear_attachments.plan_header_url(f"01-{identifier}"),
            )
        ]
    return {
        "id": f"iss-{identifier}",
        "identifier": identifier,
        "title": f"T {identifier}",
        "url": f"u/{identifier}",
        "completedAt": completed_at,
        "canceledAt": canceled_at,
        "attachments": {"nodes": attachment_nodes},
    }


class TestPendingLearnBacklog:
    def test_terminal_true_flips_the_state_fragment(self) -> None:
        backend, fake = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]}
        )
        backend.list_plans_pending_learn()
        [(query, variables)] = _queries(fake, "issues(first")
        assert 'state: { type: { in: ["completed", "canceled"] } } ' in query
        assert variables["label"] == "perk:plan"
        # The selection must carry the fields the decoder reads: the row scalars, both close
        # timestamps, and the attachment metadata sub-selection (the scripted fake returns rows
        # regardless of the selection, so pin the query itself).
        assert (
            "id identifier title url completedAt canceledAt "
            "attachments(first: 50) { nodes { id url metadata } }" in query
        )

    def test_default_path_keeps_the_nin_fragment(self) -> None:
        # The byte-compat arm: the open-only listings are untouched by the terminal kwarg.
        backend, fake = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [_no_issues()]}
        )
        backend.list_learn_issues()
        [(query, _)] = _queries(fake, "issues(first")
        assert 'state: { type: { nin: ["completed", "canceled"] } } ' in query

    def test_filters_decodes_sorts_and_truncates(self) -> None:
        rows = [
            _pending_plan_row("ENG-1", completed_at="2026-01-01T00:00:00Z"),
            _pending_plan_row("ENG-2", learn_state="captured", completed_at="2026-03-01T00:00:00Z"),
            _pending_plan_row("ENG-3", canceled_at="2026-02-01T00:00:00Z"),
            _pending_plan_row("ENG-4"),  # no close timestamp -> sorts last
            _pending_plan_row("ENG-5", completed_at="2026-04-01T00:00:00Z"),
        ]
        backend, _ = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [{"issues": _page(rows)}]}
        )
        result = backend.list_plans_pending_learn()
        # captured excluded; most-recently-closed first (canceledAt counts); None last.
        assert [r.id for r in result] == ["ENG-5", "ENG-3", "ENG-1", "ENG-4"]
        assert result[0].title == "T ENG-5" and result[0].url == "u/ENG-5"
        assert result[0].closed_at == "2026-04-01T00:00:00Z"
        assert result[1].closed_at == "2026-02-01T00:00:00Z"  # canceledAt fallback
        assert result[3].closed_at is None

        truncated_backend, _ = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [{"issues": _page(rows)}]}
        )
        truncated = truncated_backend.list_plans_pending_learn(limit=2)
        assert [r.id for r in truncated] == ["ENG-5", "ENG-3"]

    def test_absent_or_malformed_plan_attachment_is_silently_excluded(self) -> None:
        malformed_payload: list[dict[str, object]] = [
            {
                "id": "a1",
                "url": linear_attachments.plan_header_url("01X"),
                "metadata": {
                    "source": "perk",
                    "kind": "plan-header",
                    "payload_json": "{not json",
                },
            }
        ]
        # A malformed envelope SHAPE (non-string `source`) raises ValidationError from the
        # lenient envelope parse — a different failure mode than a bad payload_json.
        malformed_envelope: list[dict[str, object]] = [
            {
                "id": "a2",
                "url": linear_attachments.plan_header_url("01Y"),
                "metadata": {"source": ["perk"], "kind": "plan-header"},
            }
        ]
        rows = [
            _pending_plan_row("ENG-1", attachment_nodes=[]),  # absent attachment
            _pending_plan_row("ENG-2", attachment_nodes=malformed_payload),
            _pending_plan_row("ENG-4", attachment_nodes=malformed_envelope),
            _pending_plan_row("ENG-3", completed_at="2026-01-01T00:00:00Z"),
        ]
        backend, _ = _make_backend(
            {"teams(filter": [_TEAM_RESPONSE], "issues(first": [{"issues": _page(rows)}]}
        )
        result = backend.list_plans_pending_learn()
        assert [r.id for r in result] == ["ENG-3"]  # excluded, not raised

    def test_raises_on_query_failure(self) -> None:
        failing, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [LinearGraphQLError("Linear GraphQL error: down", codes=())],
            }
        )
        with pytest.raises(IssueBackendError, match="down"):
            failing.list_plans_pending_learn()


def _comments_response(comments: list[dict[str, object]]) -> dict[str, object]:
    return {"issue": {"comments": _page(comments)}}


def _plan_attachment(run_id: str, extra: dict[str, object] | None = None) -> dict[str, object]:
    """A wire-shaped plan-header attachment node keyed on ``run_id``."""
    return _perk_attachment_node(
        linear_attachments.PLAN_HEADER_KIND,
        {"run_id": run_id, "created": "t", **(extra or {})},
        url=linear_attachments.plan_header_url(run_id),
    )


def _issue_with_plan_attachment(
    run_id: str, extra: dict[str, object] | None = None
) -> dict[str, object]:
    """An ``issue(id`` response whose issue carries a plan-header attachment (the
    ``issue_attachments`` / ``_ISSUE_SELECTION`` read shape)."""
    return {
        "issue": {
            "id": "iss-1",
            "attachments": {"nodes": [_plan_attachment(run_id, extra)]},
        }
    }


def _objective_attachment() -> dict[str, object]:
    """A wire-shaped objective-header attachment node (the metadata-sentinel shape)."""
    return _perk_attachment_node(
        linear_attachments.OBJECTIVE_HEADER_KIND,
        {"run_id": "01OBJ", "created": "t"},
        url="https://perk.invalid/objective/01OBJ",
        att_id="att-obj",
    )


class TestGistTwins:
    def test_find_gist_issue_uses_the_gist_url_namespace(self) -> None:
        # A plan issue sharing the run_id never matches: the gist find keys on the
        # /gist/ URL namespace, disjoint from /plan/ and /learn/ by construction.
        backend, fake = _make_backend({"attachmentsForURL(": [_attachments_for_url_miss()]})
        assert backend.find_gist_issue(run_id="01RUN") is None
        [(_, variables)] = _queries(fake, "attachmentsForURL(")
        assert variables["url"] == "https://perk.invalid/gist/01RUN"

    def _gist_create_responses(self) -> dict[str, list[object]]:
        return {
            "attachmentsForURL(": [_attachments_for_url_miss()],
            "teams(filter": [_TEAM_RESPONSE],
            "issueLabels(filter": [_LABEL_FOUND],
            "issueCreate(": [
                {
                    "issueCreate": {
                        "success": True,
                        "issue": {"id": "iss-g", "identifier": "ENG-9", "url": "u-g"},
                    }
                }
            ],
            "attachmentCreate(": [_attachment_create_ok()],
        }

    def test_create_gist_issue_clean_body_with_scope_header(self) -> None:
        backend, fake = _make_backend(self._gist_create_responses())
        ref = backend.create_gist_issue(title="t", body="intent", run_id="01GIST", scope="plan")
        assert ref.existed is False and ref.id == "ENG-9"
        [(_, variables)] = _queries(fake, "issueCreate(")
        # Clean-body create: the description is the intent prose only.
        assert _input_payload(variables)["description"] == "intent\n"
        # The gist-header rides the run_id-keyed native attachment (incl. the scope).
        [att] = _att_creates(fake)
        assert att["url"] == "https://perk.invalid/gist/01GIST"
        header = _att_fields(att)
        assert header["run_id"] == "01GIST"
        assert header["scope"] == "plan"

    def test_create_gist_issue_is_idempotent_via_find(self) -> None:
        backend, fake = _make_backend(
            {
                "attachmentsForURL(": [_attachments_for_url_hit(identifier="ENG-9", url="u-g")],
            }
        )
        ref = backend.create_gist_issue(title="t", body="b", run_id="01GIST", scope="plan")
        assert ref == issue_backend.IssueRef(id="ENG-9", url="u-g", existed=True)
        assert not _queries(fake, "issueCreate(")

    def test_create_gist_issue_dry_run_is_offline(self) -> None:
        backend, fake = _make_backend({})
        ref = backend.create_gist_issue(
            title="t", body="b", run_id="01GIST", scope="plan", dry_run=True
        )
        assert ref == issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        assert fake.requests == []

    def test_list_gist_issues_decodes_scope_and_adopted(self) -> None:
        # scope decodes off the gist-header attachment; a plan-header attachment on the same
        # issue flips `adopted` (a Linear issue-gist can only be adopted as a plan).
        fresh_row: dict[str, object] = {
            "id": "iss-1",
            "identifier": "ENG-10",
            "title": "G1",
            "url": "u1",
            "description": "body 1",
            "attachments": {
                "nodes": [
                    _perk_attachment_node(
                        linear_attachments.GIST_HEADER_KIND,
                        {"run_id": "01G", "created": "t", "scope": "objective"},
                        url=linear_attachments.gist_header_url("01G"),
                    )
                ]
            },
        }
        adopted_row: dict[str, object] = {
            "id": "iss-2",
            "identifier": "ENG-11",
            "title": "G2",
            "url": "u2",
            "description": "body 2",
            "attachments": {
                "nodes": [
                    _perk_attachment_node(
                        linear_attachments.GIST_HEADER_KIND,
                        {"run_id": "01H", "created": "t", "scope": "plan"},
                        url=linear_attachments.gist_header_url("01H"),
                    ),
                    _perk_attachment_node(
                        linear_attachments.PLAN_HEADER_KIND,
                        {"run_id": "01P", "created": "t"},
                        url=linear_attachments.plan_header_url("01P"),
                    ),
                ]
            },
        }
        backend, fake = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [{"issues": _page([fresh_row, adopted_row])}],
            }
        )
        fresh, adopted = backend.list_gist_issues()
        assert fresh == issue_backend.GistSummary(
            id="ENG-10", title="G1", url="u1", body="body 1", scope="objective", adopted=False
        )
        assert adopted.scope == "plan" and adopted.adopted is True
        [(_, variables)] = _queries(fake, "issues(first")
        assert variables["label"] == "perk:gist"

    def test_list_gist_issues_raises_on_failure(self) -> None:
        failing, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [LinearGraphQLError("Linear GraphQL error: down", codes=())],
            }
        )
        with pytest.raises(IssueBackendError, match="down"):
            failing.list_gist_issues()

    def test_list_gist_issues_degrades_on_malformed_gist_attachment(self) -> None:
        # A perk-marked gist attachment with a corrupt payload degrades to scope=None — one bad
        # attachment never bricks the gather.
        row: dict[str, object] = {
            "id": "iss-1",
            "identifier": "ENG-12",
            "title": "G",
            "url": "u",
            "description": "b",
            "attachments": {
                "nodes": [
                    {
                        "id": "att-1",
                        "url": linear_attachments.gist_header_url("01G"),
                        "metadata": {
                            "source": "perk",
                            "kind": linear_attachments.GIST_HEADER_KIND,
                            "payload_json": "{not json",
                        },
                    }
                ]
            },
        }
        backend, _ = _make_backend(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "issues(first": [{"issues": _page([row])}],
            }
        )
        [summary] = backend.list_gist_issues()
        assert summary.scope is None and summary.adopted is False


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

    def test_update_plan_header_merges_whole_envelope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend, fake = _make_backend(
            {
                "issue(id": [_issue_with_plan_attachment("01HDR")],
                "attachmentCreate(": [_attachment_create_ok()],
            }
        )
        # No PR resolves → no PR-card attempt (the PR-card path is its own test).
        monkeypatch.setattr(github, "get_pr", lambda **k: None)
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"})
        assert update == issue_backend.PlanHeaderUpdate(fields_updated=("pr",), dry_run=False)
        # Merge-and-upsert on the FOUND attachment's URL (the upsert identity), carrying the
        # complete merged envelope (server write semantics are REPLACE).
        [att] = _att_creates(fake)
        assert att["url"] == "https://perk.invalid/plan/01HDR"
        header = _att_fields(att)
        assert header["pr"] == "12" and header["run_id"] == "01HDR"
        assert not _queries(fake, "issueUpdate(")  # the description is never touched

    def test_update_plan_header_absent_attachment_refuses_merge_only(self) -> None:
        # Merge-only (contracts §8.4): an absent attachment is an unconditional refusal —
        # update_plan_header never creates a plan-header (creation is confined to the seams).
        backend, fake = _make_backend(
            {"issue(id": [{"issue": {"id": "iss-1", "attachments": {"nodes": []}}}]}
        )
        with pytest.raises(IssueBackendError, match="merge-only"):
            backend.update_plan_header(issue_id="iss-1", fields={"branch": "b"})
        assert not _queries(fake, "attachmentCreate(")  # refused before any write

    def test_update_plan_header_absent_attachment_refuses_even_with_run_id(self) -> None:
        # The old run_id-keyed creation fallback is GONE: a run_id in the merged fields no
        # longer keys a fresh attachment — the refusal is unconditional.
        backend, fake = _make_backend(
            {"issue(id": [{"issue": {"id": "iss-1", "attachments": {"nodes": []}}}]}
        )
        with pytest.raises(IssueBackendError, match="merge-only"):
            backend.update_plan_header(issue_id="iss-1", fields={"run_id": "01NEW"})
        assert not _queries(fake, "attachmentCreate(")

    def test_update_plan_header_posts_pr_attachment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend, fake = _make_backend(
            {
                "issue(id": [_issue_with_plan_attachment("01H")],
                "attachmentCreate(": [_attachment_create_ok()],
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
        # Two attachment writes: the header envelope upsert, then the human-facing PR card.
        header_att, pr_card = _att_creates(fake)
        assert header_att["url"] == "https://perk.invalid/plan/01H"
        assert pr_card["issueId"] == "iss-1"
        assert pr_card["url"] == "https://github.com/o/r/pull/12"
        assert pr_card["title"] == "GitHub PR #12"
        assert pr_card["subtitle"] == "OPEN"
        assert "metadata" not in pr_card  # the PR card carries no machine envelope

    def test_update_plan_header_attachment_is_fail_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The PR lookup raising must NOT fail the header stamp (the PR card is bookkeeping).
        backend, fake = _make_backend(
            {
                "issue(id": [_issue_with_plan_attachment("01H")],
                "attachmentCreate(": [_attachment_create_ok()],
            }
        )
        monkeypatch.setattr(
            github, "get_pr", lambda **k: (_ for _ in ()).throw(GitHubError("gh exploded"))
        )
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"})
        assert update.dry_run is False  # the header write committed
        # Only the header-envelope write fired — no PR card was posted.
        [att] = _att_creates(fake)
        assert att["url"] == "https://perk.invalid/plan/01H"

    def test_update_plan_header_attachment_failure_reports(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The fail-open swallow now reports loud-but-non-fatal to stderr (report-don't-swallow).
        backend, _fake = _make_backend(
            {
                "issue(id": [_issue_with_plan_attachment("01H")],
                "attachmentCreate(": [_attachment_create_ok()],
            }
        )
        monkeypatch.setattr(
            github, "get_pr", lambda **k: (_ for _ in ()).throw(GitHubError("gh exploded"))
        )
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"})
        assert update.dry_run is False  # the header write still committed
        err = capsys.readouterr().err
        assert "perk linear: PR attachment skipped" in err
        assert "gh exploded" in err

    def test_update_plan_header_no_pr_posts_no_pr_card(self) -> None:
        backend, fake = _make_backend(
            {
                "issue(id": [_issue_with_plan_attachment("01H")],
                "attachmentCreate(": [_attachment_create_ok()],
            }
        )
        backend.update_plan_header(issue_id="iss-1", fields={"branch": "plan-ENG-1"})
        # Only the header-envelope write — a pr-less stamp never posts a PR card.
        [att] = _att_creates(fake)
        assert att["url"] == "https://perk.invalid/plan/01H"

    def test_update_plan_header_dry_run_composes_only(self) -> None:
        backend, fake = _make_backend({"issue(id": [_issue_with_plan_attachment("01HDR")]})
        update = backend.update_plan_header(issue_id="iss-1", fields={"pr": "12"}, dry_run=True)
        assert update.dry_run is True
        assert not _att_creates(fake)
        assert not _queries(fake, "issueUpdate(")


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

    def test_malformed_payload_maps_validation_error_to_issue_backend_error(self) -> None:
        # A present-but-malformed issue (missing the required `identifier`) raises a
        # ValidationError the call site maps to a labelled IssueBackendError.
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "url": "u",
                            "title": "T",
                            "state": {"type": "started"},
                        }
                    }
                ]
            }
        )
        with pytest.raises(IssueBackendError, match="read plan issue"):
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
                            "description": "clean prose",
                            "state": {"type": state_type},
                            "attachments": {"nodes": [_plan_attachment("01S")]},
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
        assert state.has_plan_header is True and state.has_objective_header is False

    def test_flags_from_attachment_presence(self) -> None:
        # Presence-only kind evidence off the attachment nodes already fetched (no extra read):
        # an objective-header attachment (a metadata sentinel) reads has_objective_header=True.
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "SEN-9",
                            "url": "u",
                            "title": "T",
                            "description": "",
                            "state": {"type": "started"},
                            "attachments": {"nodes": [_objective_attachment()]},
                        }
                    }
                ]
            }
        )
        state = backend.get_plan(issue_id="SEN-9")
        assert state is not None
        assert state.has_plan_header is False and state.has_objective_header is True
        assert state.header == {}

    def test_corrupt_plan_payload_still_raises(self) -> None:
        # The fail-early read posture is deliberately unchanged: a perk-marked plan
        # attachment with a corrupt payload_json keeps failing loud at get_plan — before any
        # side effect — never degrading to header={}.
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-7",
                            "url": "u",
                            "title": "T",
                            "description": "",
                            "state": {"type": "started"},
                            "attachments": {
                                "nodes": [
                                    {
                                        "id": "a1",
                                        "url": "https://perk.invalid/plan/01P",
                                        "metadata": {
                                            "source": "perk",
                                            "kind": "plan-header",
                                            "payload_json": "{not json",
                                        },
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        )
        with pytest.raises(IssueBackendError, match="invalid payload_json"):
            backend.get_plan(issue_id="ENG-7")

    def test_pr_header_field_resolves_via_late_bound_github(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-1",
                            "url": "u",
                            "title": "T",
                            "description": "",
                            "state": {"type": "started"},
                            "attachments": {"nodes": [_plan_attachment("01P", {"pr": "12"})]},
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
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-1",
                            "url": "u",
                            "title": "T",
                            "description": "",
                            "state": {"type": "started"},
                            "attachments": {"nodes": [_plan_attachment("01P", {"pr": "12"})]},
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

    @pytest.mark.parametrize("raw_pr", ["garbage", "0", "-3", 0, -3])
    def test_malformed_pr_stays_raw_with_no_lookup(
        self, monkeypatch: pytest.MonkeyPatch, raw_pr: object
    ) -> None:
        # The shared tolerant read-boundary parser (§8.54): malformed/non-positive `pr`
        # metadata resolves NO PR (no GitHub lookup) while the raw header value stays
        # readable for classification and cancellation evidence.
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-1",
                            "url": "u",
                            "title": "T",
                            "description": "",
                            "state": {"type": "started"},
                            "attachments": {"nodes": [_plan_attachment("01P", {"pr": raw_pr})]},
                        }
                    }
                ]
            }
        )

        def boom(*, number: int, repo_root: Path) -> github.PullRequest:
            raise AssertionError("no PR lookup may be attempted for a malformed claim")

        monkeypatch.setattr(github, "get_pr", boom)
        state = backend.get_plan(issue_id="iss-1")
        assert state is not None and state.pr is None
        assert state.header["pr"] == raw_pr  # raw claim preserved, never rewritten


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
    """In-place issue adoption (§8.29) on the Linear backend."""

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

    def test_read_issue_already_plan_true_with_plan_attachment(self) -> None:
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
                            "state": {"type": "started"},
                            "attachments": {"nodes": [_plan_attachment("01P")]},
                        }
                    }
                ]
            }
        )
        src = backend.read_issue(issue_id="ENG-7")
        assert src is not None and src.already_plan is True

    def test_read_issue_already_plan_is_presence_only_and_tolerant(self) -> None:
        # A perk-marked plan attachment with a corrupt payload still means "already a plan" —
        # the adoption refusal must refuse, never crash (has_perk_attachment, not the
        # fail-loud decoder).
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
                            "state": {"type": "started"},
                            "attachments": {
                                "nodes": [
                                    {
                                        "id": "a1",
                                        "url": "https://perk.invalid/plan/01P",
                                        "metadata": {
                                            "source": "perk",
                                            "kind": "plan-header",
                                            "payload_json": "{not json",
                                        },
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        )
        src = backend.read_issue(issue_id="ENG-7")
        assert src is not None and src.already_plan is True

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
                "attachmentCreate(": [_attachment_create_ok()],
                "issue(id": [
                    # First read: the wrong-kind writer guard's attachment scan (clean).
                    {"issue": {"id": "iss-1", "attachments": {"nodes": []}}},
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "ENG-7",
                            "url": "u/ENG-7",
                            "description": "HUMAN BODY VERBATIM",
                            "labels": {"nodes": [{"id": "lbl-existing"}]},
                        }
                    },
                ],
            }
        )
        header_fields = plan.render_plan_header_fields(
            plan.PlanHeader(run_id="RID", created="t", adopted_from="ENG-7")
        )
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
        # The plan-header rides the run_id-keyed attachment — the human body is preserved
        # VERBATIM (no metadata splice), only the callout is prepended above it.
        [att] = _att_creates(fake)
        assert att["issueId"] == "ENG-7"
        assert att["url"] == "https://perk.invalid/plan/RID"
        assert _att_fields(att)["adopted_from"] == "ENG-7"
        desc_update = next(u for u in updates if "description" in u)
        new_desc = cast("str", desc_update["description"])
        assert "HUMAN BODY VERBATIM" in new_desc
        assert "perk impl ENG-7" in new_desc
        assert "perk:metadata-block" not in new_desc  # no header splice into the body
        assert "title" not in desc_update and "title" not in label_update
        # The plan body is upserted as an inline-code comment.
        [(_, create_vars)] = _queries(fake, "commentCreate(")
        comment_body = cast("str", _input_payload(create_vars)["body"])
        assert plan.extract_plan_body(comment_body) is not None

    def test_adopt_issue_as_plan_refuses_an_objective_carrier(self) -> None:
        # Wrong-kind writer guard (§8.29): an objective-header attachment refuses BEFORE any
        # mutation — closes the `--adopt-from` direct-save bypass at the mutation boundary.
        backend, fake = _make_backend(
            {
                "issue(id": [
                    {"issue": {"id": "iss-1", "attachments": {"nodes": [_objective_attachment()]}}}
                ],
            }
        )
        with pytest.raises(IssueBackendError, match="wrong kind for plan adoption"):
            backend.adopt_issue_as_plan(
                issue_id="ENG-7",
                header_fields={"run_id": "RID", "created": "t"},
                plan_markdown="# P",
                callout="c",
                command="perk impl ENG-7",
            )
        # Presence-only guard read only — no label/update/comment/attachment mutation fired.
        assert not _queries(fake, "issueUpdate(")
        assert not _queries(fake, "attachmentCreate(")
        assert not _queries(fake, "commentCreate(")

    def test_read_issue_already_objective_from_the_objective_attachment(self) -> None:
        backend, _ = _make_backend(
            {
                "issue(id": [
                    {
                        "issue": {
                            "id": "iss-1",
                            "identifier": "SEN-9",
                            "url": "u",
                            "title": "t",
                            "description": "b",
                            "state": {"type": "started"},
                            "attachments": {"nodes": [_objective_attachment()]},
                        }
                    }
                ]
            }
        )
        src = backend.read_issue(issue_id="SEN-9")
        assert src is not None and src.already_objective is True and src.already_plan is False


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


class TestOptionalAwareHelpers:
    """The tolerant (never-raise) `_opt_*` siblings of the `_require_*` family."""

    def test_opt_dict_returns_value_on_dict_else_none(self) -> None:
        payload: dict[str, object] = {"a": 1}
        assert _opt_dict(payload) is payload
        assert _opt_dict([1, 2]) is None
        assert _opt_dict("x") is None
        assert _opt_dict(None) is None

    def test_opt_list_returns_value_on_list_else_none(self) -> None:
        payload: list[object] = [1, 2]
        assert _opt_list(payload) is payload
        assert _opt_list({"a": 1}) is None
        assert _opt_list("x") is None
        assert _opt_list(None) is None

    def test_opt_str_returns_value_on_str_else_none(self) -> None:
        assert _opt_str("x") == "x"
        assert _opt_str("") == ""
        assert _opt_str(7) is None
        assert _opt_str(None) is None


class TestLinearIssueNodeModel:
    """The lenient response model for the recurring 6-field issue selection: ``identifier`` is the
    required boundary identity; every other field tolerant; the happy path is byte-identical to the
    retired `_require_issue_node`."""

    def test_builds_from_well_formed_payload(self) -> None:
        node = LinearIssueNodeModel.model_validate(
            {
                "id": "uuid-1",
                "identifier": "ENG-1",
                "url": "https://linear.app/x/issue/ENG-1",
                "title": "A title",
                "description": "the body",
                "state": {"type": "started"},
            }
        )
        assert node.id == "uuid-1"
        assert node.identifier == "ENG-1"
        assert node.url == "https://linear.app/x/issue/ENG-1"
        assert node.title == "A title"
        assert node.description == "the body"
        assert node.normalized_state() == "OPEN"

    @pytest.mark.parametrize(
        ("state_type", "expected"),
        [("started", "OPEN"), ("completed", "CLOSED"), ("canceled", "CLOSED")],
    )
    def test_normalized_state(self, state_type: str, expected: str) -> None:
        node = LinearIssueNodeModel.model_validate(
            {"identifier": "ENG-1", "state": {"type": state_type}}
        )
        assert node.normalized_state() == expected

    def test_tolerates_absent_description(self) -> None:
        # Linear leaves `description` unset on a description-less issue: tolerant `None`.
        node = LinearIssueNodeModel.model_validate(
            {
                "id": "uuid-1",
                "identifier": "ENG-1",
                "url": "u",
                "title": "t",
                "description": None,
                "state": {"type": "unstarted"},
            }
        )
        assert node.description is None

    def test_absent_state_normalizes_to_open(self) -> None:
        # Edge loosening (NEW posture): an absent/None state no longer raises; it normalizes to
        # OPEN, and absent url/title default to "".
        node = LinearIssueNodeModel.model_validate({"identifier": "ENG-1"})
        assert node.normalized_state() == "OPEN"
        assert node.url == ""
        assert node.title == ""
        assert node.description is None

    def test_raises_on_missing_identifier(self) -> None:
        with pytest.raises(ValidationError):
            LinearIssueNodeModel.model_validate(
                {"id": "uuid-1", "url": "u", "title": "t", "state": {"type": "unstarted"}}
            )
