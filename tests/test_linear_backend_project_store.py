from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import (
    _LABEL_ABSENT,
    _TEAM_RESPONSE,
    _FakeLinear,
    _input_payload,
    _make_store,
    _milestone_create,
    _page,
    _project_not_found,
    _queries,
)

from perk import objective, plan
from perk.backends import engagement, linear_backend, objective_store
from perk.backends.linear import (
    LinearGraphQLError,
)
from perk.backends.linear_backend import (
    to_linear_markdown,
)
from perk.backends.objective_store import ObjectiveStoreError


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

    def test_update_objective_node_mirror_failure_reports(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The fail-open mirror swallow now reports loud-but-non-fatal (report-don't-swallow).
        node = objective.ObjectiveNode(
            id="1.1", description="Alpha", status=objective.NodeStatus.PENDING
        )
        responses = self._node_issue_responses(node)
        responses["issueUpdate("] = [
            {"issueUpdate": {"success": True}},  # the authoritative description write
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


class TestLinearProjectAdoption:
    """In-place objective adoption on the project-backed store (#709, Node 3.2):
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
                                    self._existing_issue(
                                        uuid="i-1",
                                        identifier="ENG-1",
                                        title="Issue one",
                                        body="body one",
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
            "projects(first": [{"team": {"projects": _page([])}}],  # find_objective dedup miss
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
            "projectMilestoneCreate(": [_milestone_create("m-1")],
            "issueLabels(filter": [_LABEL_ABSENT],
            "issueLabelCreate(": [
                {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-node"}}}
            ],
            # mapped issue (ENG-1) label read for the additive union
            "issue(id": [
                {"issue": {"id": "i-1", "description": "HUMAN ISSUE BODY", "labels": _page([])}}
            ],
            "issueUpdate(": [{"issueUpdate": {"success": True}}],  # mapped desc + milestone attach
            "issueCreate(": [_issue_create("ENG-2", "i-2")],  # unmapped node 1.2
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
        # Two projectUpdate writes: the composed overview, then the callout prepend.
        composed = update_contents[0]
        header = plan.find_metadata_block(composed, objective.OBJECTIVE_HEADER_KEY)
        assert header is not None and header["adopted_from"] == "proj-1"
        assert "MODEL PROSE" in composed
        # the original overview is archived verbatim in the Immutable note (inline-code marker)
        assert "ORIGINAL OVERVIEW VERBATIM" in composed
        assert to_linear_markdown(objective.ADOPTED_OVERVIEW_MARKER) in composed
        assert "perk objective plan proj-1" in update_contents[-1]

        # The mapped issue ENG-1 got the node block stamped additively (human body verbatim) +
        # the node label union, via issueUpdate; the unmapped node 1.2 was minted fresh.
        issue_updates = [_input_payload(v) for _, v in _queries(fake, "issueUpdate(")]
        desc_update = next(u for u in issue_updates if "description" in u)
        new_desc = cast("str", desc_update["description"])
        assert "HUMAN ISSUE BODY" in new_desc
        assert "`perk:metadata-block:objective-node`" in new_desc
        assert desc_update["labelIds"] == ["lbl-node"]
        # the unmapped node minted exactly one fresh issue
        ivars = [_input_payload(v) for _, v in _queries(fake, "issueCreate(")]
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
        store, _ = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [{"team": {"projects": _page([])}}],
            }
        )
        with pytest.raises(ObjectiveStoreError, match="roadmap is empty"):
            store.adopt_source_as_objective(
                source_id="proj-1",
                title="t",
                prose="p",
                run_id="01RUN",
                roadmap_nodes=[],
                adopt_map={},
            )

    def test_adopt_source_as_objective_unknown_adopt_issue_raises(self) -> None:
        store, _ = _make_project_store(
            {
                "teams(filter": [_TEAM_RESPONSE],
                "projects(first": [{"team": {"projects": _page([])}}],
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
