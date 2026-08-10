from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import (
    _LABEL_ABSENT,
    _STATES_RESPONSE,
    _TEAM_RESPONSE,
    _att_creates,
    _att_fields,
    _attachment_create_ok,
    _attachments_for_url_hit,
    _attachments_for_url_miss,
    _FakeLinear,
    _input_payload,
    _make_store,
    _milestone_create,
    _page,
    _perk_attachment_node,
    _project_not_found,
    _queries,
)

from perk import objective, plan
from perk.backends import engagement, linear, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    attachments as linear_attachments,
)
from perk.backends.linear import (
    to_linear_markdown,
)
from perk.backends.linear.client import (
    LinearGraphQLError,
)
from perk.backends.objective_store import ObjectiveStoreError


def _make_project_store(
    responses: dict[str, list[object]] | None = None,
) -> tuple[objective_store.ObjectiveStore, _FakeLinear]:
    """Construct the project-backed objective store over a fake `LinearClient`. The explicit
    ``ObjectiveStore`` annotation is the static conformance binding: ty fails the suite
    if ``LinearProjectObjectiveStore`` drifts from the protocol — the twin of ``_make_store`` for
    the issue-backed ``LinearObjectiveStore``."""
    fake = _FakeLinear(responses)
    store: objective_store.ObjectiveStore = linear.LinearProjectObjectiveStore(
        fake, team_key="ENG", repo_root=Path("/repo")
    )
    return store, fake


def _overview_for(run_id: str) -> str:
    """A project overview content carrying the inline-code objective-header for ``run_id``."""
    header = objective.ObjectiveHeader(
        run_id=run_id, created="t", objective_comment_id=None, status="active"
    )
    return plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, objective.render_header_block(header), style="inline-code"
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


def _node_issue(
    node: objective.ObjectiveNode, *, uuid: str, identifier: str, pr: str | None = None
) -> dict[str, object]:
    """A raw ``project_issues`` node-issue row: clean prose description; the ``objective-node``
    payload rides an attachment (plus a ``plan-header`` attachment when ``pr`` is given — the
    backlink presence signal)."""
    atts = [
        _perk_attachment_node(
            linear_attachments.OBJECTIVE_NODE_KIND,
            objective.render_node_block(node),
            url=linear_attachments.node_url(identifier),
            att_id=f"att-node-{identifier}",
        )
    ]
    if pr is not None:
        atts.append(
            _perk_attachment_node(
                linear_attachments.PLAN_HEADER_KIND,
                {"run_id": "01PLAN", "created": "t", "pr": pr},
                url=linear_attachments.plan_header_url("01PLAN"),
                att_id=f"att-plan-{identifier}",
            )
        )
    return {
        "id": uuid,
        "identifier": identifier,
        "url": f"u/{identifier}",
        "description": node.description,
        "attachments": {"nodes": atts},
    }


def _sentinel_row(
    run_id: str = "01RUN",
    *,
    uuid: str = "i-s",
    identifier: str = "ENG-0",
    header_extra: dict[str, object] | None = None,
    manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    """A raw project-issue row for the metadata sentinel: empty body; the ``objective-header``
    (+ optional ``objective-manifest``) envelopes ride its attachments."""
    header = objective.ObjectiveHeader(
        run_id=run_id, created="t", objective_comment_id=None, status="active"
    )
    header_fields: dict[str, object] = dict(objective.render_header_block(header))
    header_fields.update(header_extra or {})
    atts = [
        _perk_attachment_node(
            linear_attachments.OBJECTIVE_HEADER_KIND,
            header_fields,
            url=linear_attachments.objective_header_url(run_id),
            att_id="att-hdr",
        )
    ]
    if manifest is not None:
        atts.append(
            _perk_attachment_node(
                linear_attachments.OBJECTIVE_MANIFEST_KIND,
                manifest,
                url=linear_attachments.objective_manifest_url(run_id),
                att_id="att-man",
            )
        )
    return {
        "id": uuid,
        "identifier": identifier,
        "url": f"u/{identifier}",
        "title": "Perk: objective metadata",
        "description": "",
        "attachments": {"nodes": atts},
    }


_NODE_URL_PREFIX = "https://perk.invalid/node/"

# A team-states response with a `canceled` state — the sentinel's born-canceled lookup.
_STATES_WITH_CANCELED: dict[str, object] = {
    "team": {
        "states": {
            "nodes": [
                {"id": "state-todo", "name": "Todo", "type": "unstarted", "position": 1},
                {"id": "state-x", "name": "Canceled", "type": "canceled", "position": 9},
            ]
        }
    }
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
        objective.OBJECTIVE_HEADER_KEY, objective.render_header_block(header), style="inline-code"
    )
    reconcilable = (
        f"{objective.OBJECTIVE_RECONCILABLE_MARKER_START}\n"
        f"{prose}\n"
        f"{objective.OBJECTIVE_RECONCILABLE_MARKER_END}"
    )
    return to_linear_markdown(f"{header_block}\n\n{reconcilable}\n")


class TestLinearProjectObjectiveStore:
    """The dormant project-backed objective store: `find_objective` + `create_objective`,
    all offline through the `_FakeLinear` `LinearClient` subclass."""

    def _create_responses(self) -> dict[str, list[object]]:
        return {
            "teams(filter": [_TEAM_RESPONSE],
            "attachmentsForURL(": [_attachments_for_url_miss()],  # find_objective dedup miss
            "projectCreate(": [_project_create_ok()],
            "team(id": [_STATES_WITH_CANCELED],  # the sentinel's born-canceled state lookup
            "attachmentCreate(": [_attachment_create_ok()],
            "entityExternalLinkCreate(": [{"entityExternalLinkCreate": {"success": True}}],
            "projectUpdate(": [{"projectUpdate": {"success": True, "project": {"id": "proj-1"}}}],
            "projectMilestoneCreate(": [_milestone_create("m-1"), _milestone_create("m-2")],
            # The `perk:objective-node` label: looked up (absent) then created once (cached).
            "issueLabels(filter": [_LABEL_ABSENT],
            "issueLabelCreate(": [
                {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-node"}}}
            ],
            "issueCreate(": [
                _issue_create("ENG-0", "i-0"),  # the metadata sentinel is minted FIRST
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

        # (a) overview: reconcilable markers + prose ONLY — no metadata blocks at all (the
        # header + manifest ride the metadata sentinel's attachments), NO roadmap table
        [(_, pvars)] = _queries(fake, "projectCreate(")
        content = cast("str", _input_payload(pvars)["content"])
        assert "perk:metadata-block" not in content
        assert "`perk:objective-reconcilable`" in content
        assert "Objective prose here." in content
        assert "roadmap-table" not in content
        assert "<!--" not in content  # fully transcoded to inline-code sentinels
        # the API-key user is the project lead, and a startDate is set (required for the graph)
        pinput = _input_payload(pvars)
        assert pinput["leadId"] == "viewer-1"
        assert isinstance(pinput["startDate"], str) and pinput["startDate"]

        # (a2) the metadata sentinel: the FIRST issueCreate — empty body, born canceled, in the
        # project; the header + manifest attachments carry the run_id-keyed envelopes.
        sentinel_input = _input_payload(_queries(fake, "issueCreate(")[0][1])
        assert sentinel_input["title"] == "Perk: objective metadata"
        assert sentinel_input["description"] == ""
        assert sentinel_input["projectId"] == "proj-1"
        assert sentinel_input["stateId"] == "state-x"  # the team's canceled state
        att_inputs = _att_creates(fake)
        by_url = {a["url"]: a for a in att_inputs}
        header_att = by_url["https://perk.invalid/objective/01RUN"]
        assert header_att["issueId"] == "i-0"
        assert _att_fields(header_att)["run_id"] == "01RUN"
        manifest_att = by_url["https://perk.invalid/manifest/01RUN"]
        assert manifest_att["issueId"] == "i-0"
        manifest_fields = _att_fields(manifest_att)
        parsed, errors = objective.parse_manifest_data(manifest_fields)
        assert parsed is not None and not errors
        assert [n.id for n in parsed.nodes] == ["1.1", "1.2", "2.1"]
        assert parsed.phase_names == {"1": "Foundations", "2": "Build"}
        # the best-effort human-discoverability link points the project Resources at the sentinel
        [(_, lvars)] = _queries(fake, "entityExternalLinkCreate(")
        assert _input_payload(lvars)["label"] == "Perk metadata"

        # (b) one milestone per phase, enriched names from the body headers
        mvars = [_input_payload(v) for _, v in _queries(fake, "projectMilestoneCreate(")]
        assert [m["name"] for m in mvars] == ["Foundations", "Build"]
        assert all(m["projectId"] == "proj-1" for m in mvars)
        # Routing through `ensure_phase_milestone` with a seeded-empty `known` keeps the
        # create path's network calls byte-identical — NO extra `project_milestones` read.
        assert not _queries(fake, "projectMilestones(")

        # (c) one issue per node, in node_sort_key order, projectId + milestone, node label
        # (the FIRST issueCreate is the sentinel — sliced off)
        ivars = [_input_payload(v) for _, v in _queries(fake, "issueCreate(")][1:]
        assert [v["title"] for v in ivars] == ["1.1: alpha", "1.2: beta", "2.1: gamma"]
        assert [v.get("projectMilestoneId") for v in ivars] == ["m-1", "m-1", "m-2"]
        assert all(v["projectId"] == "proj-1" for v in ivars)
        # node-issues carry the workspace `perk:objective-node` label (additive filterability)
        assert all(v["labelIds"] == ["lbl-node"] for v in ivars)
        # every perk-created issue is assigned to the API-key user (the viewer)
        assert all(v["assigneeId"] == "viewer-1" for v in ivars)
        # the description is CLEAN prose; the node payload rides an identifier-keyed attachment
        assert ivars[0]["description"] == "Alpha"
        node_atts = {
            a["url"]: a for a in _att_creates(fake) if str(a["url"]).startswith(_NODE_URL_PREFIX)
        }
        assert set(node_atts) == {
            "https://perk.invalid/node/ENG-1",
            "https://perk.invalid/node/ENG-2",
            "https://perk.invalid/node/ENG-3",
        }
        first = _att_fields(node_atts["https://perk.invalid/node/ENG-1"])
        assert first["id"] == "1.1" and first["status"] == "pending"

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

    def test_create_objective_persists_base_into_sentinel_header(self) -> None:
        # The header composer (render_header_block) carries `base` — into the sentinel attachment.
        store, fake = _make_project_store(self._create_responses())
        store.create_objective(
            title="Big Objective",
            body=_STORE_BODY,
            run_id="01RUN",
            base="develop",
            roadmap_nodes=_store_nodes(),
        )
        header_att = next(
            a for a in _att_creates(fake) if a["url"] == "https://perk.invalid/objective/01RUN"
        )
        assert _att_fields(header_att)["base"] == "develop"

    def test_create_objective_persists_delivery_pair_into_sentinel_header(self) -> None:
        store, fake = _make_project_store(self._create_responses())
        store.create_objective(
            title="Big Objective",
            body=_STORE_BODY,
            run_id="01RUN",
            roadmap_nodes=_store_nodes(),
            delivery=objective.DeliveryPolicy.STACKED,
            delivery_lineage="01LINEAGE",
        )
        header_att = next(
            a for a in _att_creates(fake) if a["url"] == "https://perk.invalid/objective/01RUN"
        )
        fields = _att_fields(header_att)
        assert fields["delivery"] == "stacked" and fields["delivery_lineage"] == "01LINEAGE"

    def test_create_objective_absent_delivery_keeps_header_fields_identical(self) -> None:
        store, fake = _make_project_store(self._create_responses())
        store.create_objective(
            title="Big Objective",
            body=_STORE_BODY,
            run_id="01RUN",
            roadmap_nodes=_store_nodes(),
        )
        header_att = next(
            a for a in _att_creates(fake) if a["url"] == "https://perk.invalid/objective/01RUN"
        )
        fields = _att_fields(header_att)
        assert "delivery" not in fields and "delivery_lineage" not in fields

    def test_supersede_objective_persists_delivery_pair_into_successor_header(self) -> None:
        # The supersede arm composes the SUCCESSOR header separately from create — the delivery
        # pair (and the cold door's copied lineage) must reach that sentinel too. The old-side
        # close is fail-open, so its first read is scripted to fail (the create must survive).
        responses = self._create_responses()
        responses["project(id: $id)"] = [IssueBackendError("old project unreadable (scripted)")]
        store, fake = _make_project_store(responses)
        ref = store.supersede_objective(
            old_objective_id="proj-old",
            title="Successor",
            prose=_STORE_BODY,
            run_id="01RUN",
            roadmap_nodes=_store_nodes(),
            carry_map={},
            delivery=objective.DeliveryPolicy.STACKED,
            delivery_lineage="01OLDLINEAGE",
        )
        assert ref == objective_store.ObjectiveRef(id="proj-1", url="p/url", existed=False)
        header_att = next(
            a for a in _att_creates(fake) if a["url"] == "https://perk.invalid/objective/01RUN"
        )
        fields = _att_fields(header_att)
        assert fields["supersedes"] == "proj-old"
        assert fields["delivery"] == "stacked"
        assert fields["delivery_lineage"] == "01OLDLINEAGE"

    def test_supersede_objective_absent_delivery_keeps_successor_header_fields_identical(
        self,
    ) -> None:
        responses = self._create_responses()
        responses["project(id: $id)"] = [IssueBackendError("old project unreadable (scripted)")]
        store, fake = _make_project_store(responses)
        store.supersede_objective(
            old_objective_id="proj-old",
            title="Successor",
            prose=_STORE_BODY,
            run_id="01RUN",
            roadmap_nodes=_store_nodes(),
            carry_map={},
        )
        header_att = next(
            a for a in _att_creates(fake) if a["url"] == "https://perk.invalid/objective/01RUN"
        )
        fields = _att_fields(header_att)
        assert "delivery" not in fields and "delivery_lineage" not in fields

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

    def test_create_objective_sentinel_without_canceled_state(self) -> None:
        # The no-canceled-state fallback: a team with no canceled-type workflow state creates
        # the sentinel OPEN (no stateId) — the canceled state is cosmetic, the sentinel is
        # load-bearing storage either way.
        responses = self._create_responses()
        responses["team(id"] = [_STATES_RESPONSE]  # completed/unstarted only — no canceled
        store, fake = _make_project_store(responses)
        store.create_objective(
            title="Big Objective", body=_STORE_BODY, run_id="01RUN", roadmap_nodes=_store_nodes()
        )
        sentinel_input = _input_payload(_queries(fake, "issueCreate(")[0][1])
        assert sentinel_input["title"] == "Perk: objective metadata"
        assert "stateId" not in sentinel_input
        # the header + manifest attachments still land (load-bearing storage)
        assert "https://perk.invalid/objective/01RUN" in {a["url"] for a in _att_creates(fake)}

    def test_create_objective_dry_run_writes_nothing(self) -> None:
        store, fake = _make_project_store()
        ref = store.create_objective(
            title="X", body=_STORE_BODY, run_id="01RUN", roadmap_nodes=_store_nodes(), dry_run=True
        )
        assert ref == objective_store.ObjectiveRef(id="0", url="(dry-run)", existed=False)
        assert fake.requests == []

    def test_create_objective_empty_roadmap_raises(self) -> None:
        store, _ = _make_project_store({"attachmentsForURL(": [_attachments_for_url_miss()]})
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
        store, _ = _make_project_store(self._create_responses())
        with pytest.raises(ObjectiveStoreError, match="unknown node"):
            store.create_objective(title="X", body="prose", run_id="01RUN", roadmap_nodes=bad)

    def test_create_objective_idempotent_short_circuits(self) -> None:
        store, fake = _make_project_store(
            {
                "attachmentsForURL(": [
                    _attachments_for_url_hit(
                        identifier="ENG-0",
                        url="u/ENG-0",
                        state_type="canceled",
                        project={"id": "proj-9", "url": "p/9", "name": "O"},
                    )
                ],
            }
        )
        ref = store.create_objective(
            title="X", body=_STORE_BODY, run_id="01RUN", roadmap_nodes=_store_nodes()
        )
        assert ref == objective_store.ObjectiveRef(id="proj-9", url="p/9", existed=True)
        assert not _queries(fake, "projectCreate(")

    def test_find_objective_hit(self) -> None:
        store, fake = _make_project_store(
            {
                "attachmentsForURL(": [
                    _attachments_for_url_hit(
                        identifier="ENG-0",
                        url="u/ENG-0",
                        state_type="canceled",
                        project={"id": "proj-1", "url": "p/1", "name": "O"},
                    )
                ],
            }
        )
        assert store.find_objective(run_id="01RUN") == objective_store.ObjectiveRef(
            id="proj-1", url="p/1", existed=True
        )
        # ONE workspace-wide exact-URL query on the run_id-keyed header URL — no project scan.
        [(_, variables)] = _queries(fake, "attachmentsForURL(")
        assert variables["url"] == "https://perk.invalid/objective/01RUN"

    def test_find_objective_miss_returns_none(self) -> None:
        store, _ = _make_project_store({"attachmentsForURL(": [_attachments_for_url_miss()]})
        assert store.find_objective(run_id="01RUN") is None

    def test_find_objective_sentinel_without_project_raises(self) -> None:
        # A header attachment on an issue with no project is a broken sentinel — raise, never None.
        store, _ = _make_project_store(
            {
                "attachmentsForURL(": [
                    _attachments_for_url_hit(
                        identifier="ENG-0", url="u/ENG-0", state_type="canceled", project=None
                    )
                ],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="no project"):
            store.find_objective(run_id="01RUN")

    # ----------------------------------------------------------------- get_objective

    def test_get_objective_happy_path(self) -> None:
        N = objective.NodeStatus
        n11 = objective.ObjectiveNode(id="1.1", description="Alpha", status=N.PENDING, slug="a")
        n12 = objective.ObjectiveNode(id="1.2", description="Beta", status=N.PLANNING, slug="b")
        n21 = objective.ObjectiveNode(id="2.1", description="Gamma", status=N.DONE, slug="g")
        # Scrambled connection order: sentinel, 2.1, 1.1, 1.2 (never returned in roadmap order).
        issues_page = _page(
            [
                _sentinel_row("01RUN"),
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
                    {"project": {"id": "proj-1", "url": "p/url", "name": "Big Objective"}}
                ],
            }
        )
        state = store.get_objective(objective_id="proj-1")
        assert state is not None
        assert state.id == "proj-1"
        assert state.url == "p/url"
        assert state.title == "Big Objective"
        # the header is read from the metadata sentinel's attachment (same issues scan)
        assert state.header.get("run_id") == "01RUN"
        # Sorted by node_sort_key (never the scrambled connection order).
        assert [n.id for n in state.nodes] == ["1.1", "1.2", "2.1"]
        assert [n.status for n in state.nodes] == [N.PENDING, N.PLANNING, N.DONE]
        assert [n.depends_on for n in state.nodes] == [None, ("1.1",), ("1.2",)]

    def test_get_objective_pr_is_node_issue_identifier(self) -> None:
        # The backlink is the node-issue's OWN identifier whenever it carries a
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
                                    _sentinel_row("01RUN"),
                                    _node_issue(n11, uuid="i-11", identifier="ENG-11", pr="#42"),
                                    _node_issue(n12, uuid="i-12", identifier="ENG-12"),
                                ]
                            )
                        }
                    }
                ],
                "inverseRelations(": [_blocked_by(), _blocked_by()],
                "project(id": [{"project": {"id": "proj-1", "url": "u", "name": "O"}}],
            }
        )
        state = store.get_objective(objective_id="proj-1")
        assert state is not None
        by_id = {n.id: n for n in state.nodes}
        assert by_id["1.1"].pr == "#ENG-11"  # identifier-derived, not the plan-header.pr value
        assert by_id["1.2"].pr is None  # no plan-header attachment → no backlink

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
                                    _sentinel_row("01RUN"),
                                    _node_issue(n11, uuid="i-11", identifier="ENG-11"),
                                    # a foreign/human-added issue (no objective-node attachment)
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
                "project(id": [{"project": {"id": "proj-1", "url": "u", "name": "O"}}],
            }
        )
        state = store.get_objective(objective_id="proj-1")
        assert state is not None
        assert [n.id for n in state.nodes] == ["1.1"]
        # Neither the foreign issue's nor the sentinel's blockers are ever queried.
        assert len(_queries(fake, "inverseRelations(")) == 1

    def test_get_objective_absent_project_is_none(self) -> None:
        store, _ = _make_project_store({"project(id": [_project_not_found()]})
        assert store.get_objective(objective_id="p-gone") is None

    def test_get_objective_malformed_node_raises(self) -> None:
        # An objective-node attachment payload missing `status` (hand-built to dodge the builder).
        bad_row: dict[str, object] = {
            "id": "i-1",
            "identifier": "ENG-1",
            "url": "u/ENG-1",
            "description": "x",
            "attachments": {
                "nodes": [
                    _perk_attachment_node(
                        linear_attachments.OBJECTIVE_NODE_KIND,
                        {"id": "1.1", "description": "x"},
                        url=linear_attachments.node_url("ENG-1"),
                    )
                ]
            },
        }
        store, _ = _make_project_store(
            {
                "issues(first": [{"project": {"issues": _page([_sentinel_row("01RUN"), bad_row])}}],
                "project(id": [{"project": {"id": "proj-1", "url": "u", "name": "O"}}],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="invalid objective node"):
            store.get_objective(objective_id="proj-1")

    def test_get_objective_without_sentinel_is_none(self) -> None:
        # A project with issues but no metadata sentinel is not a perk objective.
        n11 = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        store, _ = _make_project_store(
            {
                "issues(first": [
                    {
                        "project": {
                            "issues": _page([_node_issue(n11, uuid="i-11", identifier="ENG-11")])
                        }
                    }
                ],
                "project(id": [{"project": {"id": "proj-1", "url": "u", "name": "O"}}],
            }
        )
        assert store.get_objective(objective_id="proj-1") is None

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
        responses["attachmentCreate("] = [_attachment_create_ok()]
        responses["issueUpdate("] = [{"issueUpdate": {"success": True}}]
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
        # (1) the authoritative write upserts the identifier-keyed objective-node attachment
        # with the new status (whole-envelope REPLACE semantics)
        [att] = _att_creates(fake)
        assert att["issueId"] == "i-1"
        assert att["url"] == "https://perk.invalid/node/ENG-1"
        fields = _att_fields(att)
        assert fields["status"] == "in_progress"
        assert fields["id"] == "1.1"
        # (2) the best-effort workflow-state mirror sets the mapped `started` state
        [(_, uvars)] = _queries(fake, "issueUpdate(")
        assert _input_payload(uvars) == {"stateId": "state-doing"}
        # (3) the project lifecycle nudge advances the project Planned→Started
        [(_, pvars)] = _queries(fake, "projectUpdate(")
        assert _input_payload(pvars) == {"state": "started"}

    def test_update_objective_node_mirror_fail_open(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        responses = self._node_issue_responses(node)
        # The attachment write succeeds; the stateId mirror write fails — swallowed.
        responses["attachmentCreate("] = [_attachment_create_ok()]
        responses["issueUpdate("] = [{"issueUpdate": {"success": False}}]
        responses["teams(filter"] = [_TEAM_RESPONSE]
        responses["team(id"] = [_STATES_WITH_STARTED]
        # the lifecycle nudge fires after the (failed) mirror; it is independently fail-open
        responses["projectUpdate("] = [{"projectUpdate": {"success": False}}]
        store, fake = _make_project_store(responses)
        result = store.update_objective_node(
            objective_id="proj-1", node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
        )
        # No raise; the attachment write is committed.
        assert result.dry_run is False
        assert len(_att_creates(fake)) == 1
        assert len(_queries(fake, "issueUpdate(")) == 1

    def test_update_objective_node_mirror_failure_reports(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The fail-open mirror swallow now reports loud-but-non-fatal (report-don't-swallow).
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        responses = self._node_issue_responses(node)
        responses["attachmentCreate("] = [_attachment_create_ok()]  # the authoritative write
        responses["issueUpdate("] = [
            {"issueUpdate": {"success": False}},  # the mirror write fails → IssueBackendError
        ]
        responses["teams(filter"] = [_TEAM_RESPONSE]
        responses["team(id"] = [_STATES_WITH_STARTED]
        responses["projectUpdate("] = [{"projectUpdate": {"success": False}}]
        store, _fake = _make_project_store(responses)
        result = store.update_objective_node(
            objective_id="proj-1", node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
        )
        assert result.dry_run is False  # the node update still succeeds
        assert "perk linear: node status mirror skipped" in capsys.readouterr().err

    def test_update_objective_node_pr_not_written_to_block(self) -> None:
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        responses = self._node_issue_responses(node)
        responses["attachmentCreate("] = [_attachment_create_ok()]
        store, fake = _make_project_store(responses)
        store.update_objective_node(objective_id="proj-1", node_id="1.1", pr="#7")
        [att] = _att_creates(fake)
        # render_node_block excludes pr; the backlink's single home is the plan-header attachment
        assert "pr" not in _att_fields(att)

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
        assert not _att_creates(fake)

    # ----------------------------------------------------------------- add_objective_node

    def _add_node_responses(self, n11: objective.ObjectiveNode) -> dict[str, list[object]]:
        # The sentinel carries the manifest pinning only phase 1 — phase 2's name is enriched
        # from the overview prose (`### Phase 2: Build`) and its milestone minted fresh.
        manifest = objective.render_manifest_block([n11], {"1": "Foundations"})
        sentinel = _sentinel_row("01RUN", manifest=manifest)
        return {
            "teams(filter": [_TEAM_RESPONSE],
            "issues(first": [
                {
                    "project": {
                        "issues": _page(
                            [sentinel, _node_issue(n11, uuid="i-11", identifier="ENG-11")]
                        )
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
            "attachmentCreate(": [_attachment_create_ok()],
            "project(id": [
                {"project": {"id": "proj-1", "url": "u", "name": "O", "content": _STORE_BODY}},
                {"project": {"content": _STORE_BODY}},
            ],
        }

    def test_add_objective_node_materializes_node_issue(self) -> None:
        n11 = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING, slug="alpha"
        )
        store, fake = _make_project_store(self._add_node_responses(n11))
        added = store.add_objective_node(objective_id="proj-1", phase=2, description="Beta work")
        assert added == objective_store.ObjectiveNodeAdd(
            objective_id="proj-1", node_id="2.1", comment_updated=False, dry_run=False
        )
        # the phase-2 milestone is minted by its enriched name (`### Phase 2: Build`)
        [(_, mvars)] = _queries(fake, "projectMilestoneCreate(")
        assert _input_payload(mvars)["name"] == "Build"
        # the new node-issue: CLEAN prose description, attached to the milestone + node label
        [(_, ivars)] = _queries(fake, "issueCreate(")
        payload = _input_payload(ivars)
        assert payload["projectId"] == "proj-1"
        assert payload["projectMilestoneId"] == "m-2"
        assert payload["labelIds"] == ["lbl-node"]  # workspace perk:objective-node label
        assert payload["description"] == "Beta work"
        # the node payload rides the identifier-keyed attachment; the manifest gains 2.1 + the
        # new phase pin (upserted on the sentinel)
        atts = _att_creates(fake)
        node_att = next(a for a in atts if a["url"] == "https://perk.invalid/node/ENG-22")
        assert node_att["issueId"] == "i-22"
        assert _att_fields(node_att)["id"] == "2.1"
        manifest_att = next(a for a in atts if a["url"] == "https://perk.invalid/manifest/01RUN")
        assert manifest_att["issueId"] == "i-s"
        synced, errors = objective.parse_manifest_data(_att_fields(manifest_att))
        assert synced is not None and not errors
        assert [n.id for n in synced.nodes] == ["1.1", "2.1"]
        assert synced.phase_names == {"1": "Foundations", "2": "Build"}
        # no depends_on -> no blocking relations
        assert not _queries(fake, "issueRelationCreate(")

    def test_add_objective_node_relation_uses_create_time_uuids(self) -> None:
        # An explicit depends_on edge: the relation is created with the issue UUIDs (the new
        # node's UUID from its `issueCreate` response, the dep's UUID from `_find_node_issue`) —
        # never the identifier — and no UuidForIssue resolution query fires.
        n11 = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING, slug="alpha"
        )
        responses = self._add_node_responses(n11)
        responses["issueRelationCreate("] = [_relation_create_ok()]
        store, fake = _make_project_store(responses)
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
                            "issues": _page(
                                [
                                    _sentinel_row("01RUN"),
                                    _node_issue(n11, uuid="i-11", identifier="ENG-11"),
                                ]
                            )
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
        assert not _att_creates(fake)

    # ----------------------------------------------------------------- update_objective_body

    def test_update_objective_body_splices_overview(self) -> None:
        overview = _overview_with_region("01RUN", "old prose")
        store, fake = _make_project_store(
            {
                # the phase-pin refresh's sentinel scan: no sentinel → clean no-op
                "issues(first": [{"project": {"issues": _page([])}}],
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
                "issues(first": [{"project": {"issues": _page([_sentinel_row("01RUN")])}}],
                "attachmentCreate(": [_attachment_create_ok()],
            }
        )
        result = store.update_objective_header(objective_id="proj-1", fields={"status": "done"})
        assert result == objective_store.ObjectiveHeaderUpdate(
            fields_updated=("status",), dry_run=False
        )
        # merge-and-upsert on the sentinel's header attachment (same URL — the upsert identity)
        [att] = _att_creates(fake)
        assert att["issueId"] == "i-s"
        assert att["url"] == "https://perk.invalid/objective/01RUN"
        fields = _att_fields(att)
        assert fields["status"] == "done"
        assert fields["run_id"] == "01RUN"  # existing fields preserved

    def test_update_objective_header_unknown_field_raises(self) -> None:
        store, _ = _make_project_store({})
        with pytest.raises(ObjectiveStoreError, match="unknown objective-header field"):
            store.update_objective_header(objective_id="proj-1", fields={"bogus": 1})

    def test_update_objective_header_no_sentinel_raises(self) -> None:
        store, _ = _make_project_store({"issues(first": [{"project": {"issues": _page([])}}]})
        with pytest.raises(ObjectiveStoreError, match="no perk metadata sentinel"):
            store.update_objective_header(objective_id="proj-1", fields={"status": "done"})

    def test_update_objective_header_dry_run_writes_nothing(self) -> None:
        store, fake = _make_project_store(
            {"issues(first": [{"project": {"issues": _page([_sentinel_row("01RUN")])}}]}
        )
        result = store.update_objective_header(
            objective_id="proj-1", fields={"status": "done"}, dry_run=True
        )
        assert result.dry_run is True
        assert not _att_creates(fake)

    # ----------------------------------------------------------------- save_node_plan

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
            "attachmentCreate(": [_attachment_create_ok()],
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
        header_fields = plan.render_plan_header_fields(plan.PlanHeader(run_id="01RUN", created="t"))
        ref = store.save_node_plan(
            objective_id="proj-1",
            node_id="1.1",
            header_fields=header_fields,
            plan_markdown="# My Plan\n\nbody text\n",
        )
        # Returns the node-issue ref (existed=True): the node-issue IS the plan issue.
        assert ref == objective_store.ObjectiveRef(id="ENG-1", url="u/ENG-1", existed=True)
        # (1) the plan-header rides its own attachment (run_id-keyed on first save), coexisting
        # with the objective-node attachment; the description write only prepends the callout.
        [att] = _att_creates(fake)
        assert att["issueId"] == "i-1"
        assert att["url"] == "https://perk.invalid/plan/01RUN"
        assert _att_fields(att)["run_id"] == "01RUN"
        [(_, uvars)] = _queries(fake, "issueUpdate(")
        desc = cast("str", _input_payload(uvars)["description"])
        assert "perk:metadata-block" not in desc
        assert "Alpha" in desc
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
            header_fields=plan.render_plan_header_fields(
                plan.PlanHeader(run_id="01RUN", created="t")
            ),
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
        # re-save must not prepend a second one (idempotent on the command string) — the
        # already-converged description is not rewritten at all.
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.IN_PROGRESS, slug="a"
        )
        row = _node_issue(node, uuid="i-1", identifier="ENG-1")
        row["description"] = plan.plan_callout("ENG-1") + "\n\n" + cast("str", row["description"])
        responses = self._save_node_responses(node=node)
        responses["issues(first"] = [{"project": {"issues": _page([row])}}]
        store, fake = _make_project_store(responses)
        store.save_node_plan(
            objective_id="proj-1",
            node_id="1.1",
            header_fields=plan.render_plan_header_fields(
                plan.PlanHeader(run_id="01RUN", created="t")
            ),
            plan_markdown="# My Plan\n\nbody\n",
        )
        assert not _queries(fake, "issueUpdate(")

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

    # ----------------------------------------------------------------- close_objective

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

    # ----------------------------------------------------------------- reopen_objective

    def test_reopen_objective_moves_completed_project_to_started(self) -> None:
        store, fake = _make_project_store(
            {
                "project(id": [{"project": {"state": "completed"}}],
                "projectUpdate(": [{"projectUpdate": {"success": True}}],
            }
        )
        assert store.reopen_objective(objective_id="proj-1") is True
        [(_, variables)] = _queries(fake, "projectUpdate(")
        assert variables["id"] == "proj-1"
        assert _input_payload(variables) == {"state": "started"}

    def test_reopen_objective_noop_when_not_completed(self) -> None:
        # ONLY completed reopens — canceled is a human cancel (not perk's to undo) and the open
        # states are already-converged no-ops.
        for state in ("started", "planned", "canceled"):
            store, fake = _make_project_store({"project(id": [{"project": {"state": state}}]})
            assert store.reopen_objective(objective_id="proj-1") is False
            assert not _queries(fake, "projectUpdate(")

    def test_reopen_objective_dry_run_writes_nothing(self) -> None:
        store, fake = _make_project_store()
        assert store.reopen_objective(objective_id="proj-1", dry_run=True) is False
        assert fake.requests == []

    def test_reopen_objective_missing_project_raises(self) -> None:
        # The reopen follows a successful write to the objective — an absent project is an infra
        # anomaly (raise), never a silent skip.
        store, _ = _make_project_store({"project(id": [{"project": None}]})
        with pytest.raises(ObjectiveStoreError, match="not found"):
            store.reopen_objective(objective_id="proj-1")

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

    def test_journal_carrier_id_is_the_sentinel_identifier(self) -> None:
        # §8.43: the journal carrier is the metadata sentinel issue's identifier.
        store, _ = _make_project_store(
            {
                "issues(first": [{"project": {"issues": _page([_sentinel_row("01RUN")])}}],
                "project(id": [{"project": {"id": "proj-1"}}],
            }
        )
        assert store.journal_carrier_id(objective_id="proj-1") == "ENG-0"

    def test_journal_carrier_id_sentinel_less_project_raises(self) -> None:
        # A project WITHOUT a sentinel is a broken perk objective — raise, never None.
        store, _ = _make_project_store(
            {
                "issues(first": [{"project": {"issues": _page([])}}],
                "project(id": [{"project": {"id": "proj-1"}}],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="no perk metadata sentinel"):
            store.journal_carrier_id(objective_id="proj-1")

    def test_journal_carrier_id_none_when_project_absent(self) -> None:
        store, _ = _make_project_store({"project(id": [_project_not_found()]})
        assert store.journal_carrier_id(objective_id="proj-gone") is None


class TestGistProjects:
    """The §8.41 project-tier gist arm: create_gist_source + list_gist_sources."""

    def _gist_overview(self, run_id: str, scope: str = "objective") -> str:
        return plan.render_gist_header(run_id=run_id, created="t", scope=scope, style="inline-code")

    def test_create_gist_source_creates_a_light_project(self) -> None:
        store, fake = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [{"team": {"projects": _page([])}}],
                "projectCreate(": [_project_create_ok()],
            }
        )
        ref = store.create_gist_source(title="Gist: X", prose="intent prose", run_id="01G")
        assert ref == objective_store.ObjectiveRef(id="proj-1", url="p/url", existed=False)
        [(_, pvars)] = _queries(fake, "projectCreate(")
        payload = _input_payload(pvars)
        assert payload["name"] == "Gist: X"
        content = payload["content"]
        assert isinstance(content, str)
        # The inline-code gist-header block IS the identity (no sentinel, no milestones).
        assert plan.extract_run_id(content, header_key=plan.GIST_HEADER_KEY) == "01G"
        header = plan.find_metadata_block(content, plan.GIST_HEADER_KEY)
        assert header is not None and header["scope"] == "objective"
        assert "intent prose" in content
        # Deliberately light: no milestones, no node-issues, no metadata sentinel.
        assert not _queries(fake, "projectMilestoneCreate")
        assert not _queries(fake, "issueCreate(")
        assert not _queries(fake, "attachmentCreate(")

    def test_create_gist_source_is_idempotent_via_the_projects_scan(self) -> None:
        existing: dict[str, object] = {
            "id": "proj-9",
            "url": "p/9",
            "name": "Gist: X",
            "content": self._gist_overview("01G"),
        }
        store, fake = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [{"team": {"projects": _page([existing])}}],
            }
        )
        ref = store.create_gist_source(title="t", prose="p", run_id="01G")
        assert ref == objective_store.ObjectiveRef(id="proj-9", url="p/9", existed=True)
        assert not _queries(fake, "projectCreate(")

    def test_create_gist_source_dry_run_is_offline_none(self) -> None:
        store, fake = _make_project_store({})
        assert store.create_gist_source(title="t", prose="p", run_id="01G", dry_run=True) is None
        assert fake.requests == []

    def test_list_gist_sources_filters_and_detects_adopted(self) -> None:
        fresh: dict[str, object] = {
            "id": "proj-1",
            "url": "p/1",
            "name": "G fresh",
            "content": self._gist_overview("01G"),
        }
        adopted: dict[str, object] = {
            "id": "proj-2",
            "url": "p/2",
            "name": "G adopted",
            # Re-authored in place as an objective through the REAL adoption composer: the
            # Reconcilable region joins the overview (the headers ride the sentinel's
            # attachments — never an overview block) and the original gist overview survives
            # verbatim in the Immutable archive note (keeping the gist-header scannable).
            "content": linear.LinearProjectObjectiveStore._compose_overview(
                "New objective prose.", original_overview=self._gist_overview("01H")
            ),
        }
        not_a_gist: dict[str, object] = {
            "id": "proj-3",
            "url": "p/3",
            "name": "Plain",
            "content": _overview_for("01X"),
        }
        store, _ = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [{"team": {"projects": _page([fresh, adopted, not_a_gist])}}],
            }
        )
        summaries = store.list_gist_sources()
        assert [s.id for s in summaries] == ["proj-1", "proj-2"]
        assert summaries[0].title == "G fresh"
        assert summaries[0].scope == "objective" and summaries[0].adopted is False
        assert summaries[1].adopted is True


class TestLinearProjectAdoption:
    """In-place objective adoption on the project-backed store:
    `read_objective_source` + `adopt_source_as_objective`, all offline through `_FakeLinear`.
    """

    def _existing_issue(
        self, *, uuid: str, identifier: str, title: str, body: str
    ) -> dict[str, object]:
        return {
            "id": uuid,
            "identifier": identifier,
            "url": f"u/{identifier}",
            "title": title,
            "description": body,
        }

    def test_read_objective_source_maps_project_and_issues(self) -> None:
        # `issues(first` registered BEFORE `project(id`: project_issues_for_adoption carries both
        # substrings, project_or_none only `project(id` (the insertion-order footgun).
        store, _ = _make_project_store(
            {
                "issues(first": [
                    {
                        "project": {
                            "issues": _page(
                                [
                                    # a stale metadata sentinel is never an adoptable candidate
                                    _sentinel_row("01OLD"),
                                    self._existing_issue(
                                        uuid="i-1",
                                        identifier="ENG-1",
                                        title="Issue one",
                                        body="body one",
                                    ),
                                ]
                            )
                        }
                    }
                ],
                "project(id": [
                    {
                        "project": {
                            "id": "proj-1",
                            "url": "p/url",
                            "name": "My Project",
                            "content": "OVERVIEW PROSE",
                        }
                    }
                ],
            }
        )
        src = store.read_objective_source(source_id="proj-1")
        assert src is not None
        assert src.id == "proj-1"
        assert src.url == "p/url"
        assert src.title == "My Project"
        assert src.prose == "OVERVIEW PROSE"
        # the sentinel (ENG-0) is excluded — only the human issue surfaces
        assert src.issues == (
            objective_store.AdoptableSourceIssue(
                id="i-1", identifier="ENG-1", url="u/ENG-1", title="Issue one", body="body one"
            ),
        )

    def test_read_objective_source_absent_returns_none(self) -> None:
        store, _ = _make_project_store({"project(id": [_project_not_found()]})
        assert store.read_objective_source(source_id="proj-x") is None

    def _adopt_nodes(self) -> list[objective.ObjectiveNode]:
        N = objective.NodeStatus
        return [
            objective.ObjectiveNode(id="1.1", description="Alpha", status=N.PENDING, slug="alpha"),
            objective.ObjectiveNode(
                id="1.2", description="Beta", status=N.PENDING, slug="beta", depends_on=("1.1",)
            ),
        ]

    def _adopt_responses(self) -> dict[str, list[object]]:
        # Maps node 1.1 -> existing issue ENG-1 (in place); node 1.2 is minted fresh.
        # Insertion order matters (the substring footgun): every `project(id` sub-query carries
        # that needle, so the more-specific ones (`projectMilestones(`, `issues(first`) precede the
        # generic `project(id` (project_or_none).
        return {
            "teams(filter": [_TEAM_RESPONSE],
            "attachmentsForURL(": [_attachments_for_url_miss()],  # find_objective dedup miss
            "projectMilestones(": [{"project": {"projectMilestones": _page([])}}],
            "issues(first": [
                {
                    "project": {
                        "issues": _page(
                            [
                                self._existing_issue(
                                    uuid="i-1",
                                    identifier="ENG-1",
                                    title="Human issue one",
                                    body="HUMAN ISSUE BODY",
                                )
                            ]
                        )
                    }
                }
            ],
            "project(id": [
                {
                    "project": {
                        "id": "proj-1",
                        "url": "p/url",
                        "name": "My Project",
                        "content": "ORIGINAL OVERVIEW VERBATIM",
                    }
                }
            ],
            "projectUpdate(": [{"projectUpdate": {"success": True, "project": {"id": "proj-1"}}}],
            "team(id": [_STATES_WITH_CANCELED],  # the sentinel's born-canceled state lookup
            "attachmentCreate(": [_attachment_create_ok()],
            "entityExternalLinkCreate(": [{"entityExternalLinkCreate": {"success": True}}],
            "projectMilestoneCreate(": [_milestone_create("m-1")],
            "issueLabels(filter": [_LABEL_ABSENT],
            "issueLabelCreate(": [
                {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-node"}}}
            ],
            # mapped issue (ENG-1) label read for the additive union
            "issue(id": [{"issue": {"id": "i-1", "labels": _page([])}}],
            "issueUpdate(": [{"issueUpdate": {"success": True}}],  # mapped label + milestone
            "issueCreate(": [
                _issue_create("ENG-9", "i-9"),  # the fresh metadata sentinel
                _issue_create("ENG-2", "i-2"),  # unmapped node 1.2
            ],
            "issueRelationCreate(": [_relation_create_ok()],
        }

    def test_adopt_source_as_objective_stamps_in_place(self) -> None:
        store, fake = _make_project_store(self._adopt_responses())
        ref = store.adopt_source_as_objective(
            source_id="proj-1",
            title="Adopted objective",
            prose="MODEL PROSE",
            run_id="01RUN",
            roadmap_nodes=self._adopt_nodes(),
            adopt_map={"1.1": "ENG-1"},
        )
        assert ref == objective_store.ObjectiveRef(id="proj-1", url="p/url", existed=False)

        # The overview is UPDATED in place (projectUpdate), never created (no projectCreate).
        assert not _queries(fake, "projectCreate(")
        update_contents = [
            cast("str", _input_payload(v)["content"]) for _, v in _queries(fake, "projectUpdate(")
        ]
        # ONE composed-overview write (with the callout prepended before the write): the header +
        # manifest ride the fresh sentinel's attachments, never the overview.
        composed = update_contents[0]
        assert "perk:metadata-block" not in composed
        assert "MODEL PROSE" in composed
        # the original overview is archived verbatim in the Immutable note (inline-code marker)
        assert "ORIGINAL OVERVIEW VERBATIM" in composed
        assert to_linear_markdown(objective.ADOPTED_OVERVIEW_MARKER) in composed
        assert "perk objective plan proj-1" in update_contents[-1]
        # the fresh sentinel's header attachment carries adopted_from=<source project>
        header_att = next(
            a for a in _att_creates(fake) if a["url"] == "https://perk.invalid/objective/01RUN"
        )
        assert header_att["issueId"] == "i-9"
        assert _att_fields(header_att)["adopted_from"] == "proj-1"

        # The mapped issue ENG-1 got the node attachment stamped ADDITIVELY (title + human body
        # untouched — no description write) + the node label union; node 1.2 was minted fresh.
        issue_updates = [_input_payload(v) for _, v in _queries(fake, "issueUpdate(")]
        assert not any("description" in u for u in issue_updates)
        mapped_att = next(
            a for a in _att_creates(fake) if a["url"] == "https://perk.invalid/node/ENG-1"
        )
        assert mapped_att["issueId"] == "i-1"
        assert _att_fields(mapped_att)["id"] == "1.1"
        assert any(u.get("labelIds") == ["lbl-node"] for u in issue_updates)
        # the unmapped node minted exactly one fresh issue (after the sentinel)
        ivars = [_input_payload(v) for _, v in _queries(fake, "issueCreate(")][1:]
        assert [v["title"] for v in ivars] == ["1.2: beta"]
        # a milestone attach fired for the mapped issue (issueUpdate with projectMilestoneId)
        assert any("projectMilestoneId" in u for u in issue_updates)
        # a blocking relation for the explicit depends_on (1.1 blocks 1.2); 1.1 is the mapped UUID
        rels = [_input_payload(v) for _, v in _queries(fake, "issueRelationCreate(")]
        assert {(r["issueId"], r["relatedIssueId"]) for r in rels} == {("i-1", "i-2")}

    def test_adopt_source_as_objective_dry_run_returns_none(self) -> None:
        store, fake = _make_project_store()
        assert (
            store.adopt_source_as_objective(
                source_id="proj-1",
                title="t",
                prose="p",
                run_id="01RUN",
                roadmap_nodes=self._adopt_nodes(),
                adopt_map={},
                dry_run=True,
            )
            is None
        )
        assert fake.requests == []

    def test_adopt_source_as_objective_idempotent_short_circuits(self) -> None:
        store, fake = _make_project_store(
            {
                "attachmentsForURL(": [
                    _attachments_for_url_hit(
                        identifier="ENG-0",
                        url="u/ENG-0",
                        state_type="canceled",
                        project={"id": "proj-9", "url": "p/9", "name": "O"},
                    )
                ],
            }
        )
        ref = store.adopt_source_as_objective(
            source_id="proj-1",
            title="t",
            prose="p",
            run_id="01RUN",
            roadmap_nodes=self._adopt_nodes(),
            adopt_map={},
        )
        assert ref == objective_store.ObjectiveRef(id="proj-9", url="p/9", existed=True)
        assert not _queries(fake, "projectUpdate(")

    def test_adopt_source_as_objective_empty_roadmap_raises(self) -> None:
        store, _ = _make_project_store({"attachmentsForURL(": [_attachments_for_url_miss()]})
        with pytest.raises(ObjectiveStoreError, match="roadmap is empty"):
            store.adopt_source_as_objective(
                source_id="proj-1",
                title="t",
                prose="p",
                run_id="01RUN",
                roadmap_nodes=[],
                adopt_map={},
            )

    def test_adopt_source_excludes_sentinel_from_mappable_candidates(self) -> None:
        # A metadata sentinel among the project's issues is never a mappable adopt target:
        # mapping a node onto its identifier fails loud as not-a-member (the skip filter).
        store, _ = _make_project_store(
            {
                "attachmentsForURL(": [_attachments_for_url_miss()],
                "issues(first": [{"project": {"issues": _page([_sentinel_row("01OLD")])}}],
                "project(id": [
                    {"project": {"id": "proj-1", "url": "p/url", "name": "P", "content": "O"}}
                ],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="not a member of project"):
            store.adopt_source_as_objective(
                source_id="proj-1",
                title="t",
                prose="p",
                run_id="01RUN",
                roadmap_nodes=self._adopt_nodes(),
                adopt_map={"1.1": "ENG-0"},  # the sentinel's identifier — skipped, so unknown
            )

    def test_adopt_source_as_objective_unknown_adopt_issue_raises(self) -> None:
        store, _ = _make_project_store(
            {
                "attachmentsForURL(": [_attachments_for_url_miss()],
                "issues(first": [{"project": {"issues": _page([])}}],  # no members
                "project(id": [
                    {
                        "project": {
                            "id": "proj-1",
                            "url": "p/url",
                            "name": "P",
                            "content": "OVERVIEW",
                        }
                    }
                ],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="not a member of project"):
            store.adopt_source_as_objective(
                source_id="proj-1",
                title="t",
                prose="p",
                run_id="01RUN",
                roadmap_nodes=self._adopt_nodes(),
                adopt_map={"1.1": "ENG-404"},
            )


class TestReadNodeEngagement:
    """`read_node_engagement`: node-keyed engagement over the project
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
    """`read_comments` / `read_description_edits` on the project-backed store:
    honest over the Linear project's comments; description edits stay an honest empty."""

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
