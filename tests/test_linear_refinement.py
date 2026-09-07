"""Objective-node refinement over the REAL Linear store + adapter (contracts.md §8.67).

The stateful ``FakeLinearWorkspace`` fakes the external transport only: every test drives the
real ``LinearProjectObjectiveStore`` (the refinement target read), the real
``LinearIssueBackend`` (the guarded marked-comment upsert + the plan-comment exclusion), and the
real ``perk.objective.refinement.service``. Fault and race injection goes through the
workspace's deterministic ``before_request`` / ``after_request`` hooks — never sleeps.

Assertions are semantic (complete pagination, correct mutation identity, full replacement,
typed outcomes, zero forbidden effects, at-most-one mutation attempt) — never frozen GraphQL
documents or total read counts. The **Phase-1 gate** at the bottom is an ordinary pytest case
over a temp repo + the actual resolvers.
"""

import copy
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import _TEAM_KEY, FakeLinearWorkspace

from perk import objective, plan
from perk.backends import resolve
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.backends.issue_backend import (
    CommentResult,
    IssueBackendError,
    MarkedCommentError,
    MarkedCommentExpectation,
    body_digest,
)
from perk.backends.linear import (
    LinearIssueBackend,
    LinearObjectiveStore,
    LinearProjectObjectiveStore,
)
from perk.backends.linear import attachments as linear_attachments
from perk.backends.linear import client as linear_client
from perk.backends.linear._helpers import to_linear_markdown
from perk.backends.linear.client import LinearGraphQLError
from perk.backends.objective_store import ObjectiveStoreError, RefinementTargetReadError
from perk.objective.refinement import codec, service
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementDocument,
    RefinementError,
    RefinementErrorCode,
    RefinementIdentity,
    RefinementProvenance,
    RefinementSaveRequest,
    RefinementSource,
    RefinementTarget,
    SavedRefinement,
)
from perk.substrate import git

REPO = Path("/repo")
OBJ_RUN = "01OBJRUN"
HEAD = "b" * 40
TS = "2026-09-07T12:00:00Z"

Hook = Callable[[str, dict[str, object]], None]

# --------------------------------------------------------------------------- harness


def _harness(
    ws: FakeLinearWorkspace | None = None,
) -> tuple[FakeLinearWorkspace, LinearProjectObjectiveStore, LinearIssueBackend]:
    workspace = ws if ws is not None else FakeLinearWorkspace()
    store = LinearProjectObjectiveStore(workspace, team_key=_TEAM_KEY, repo_root=REPO)
    issues = LinearIssueBackend(workspace, team_key=_TEAM_KEY, repo_root=REPO)
    return workspace, store, issues


def _node(
    node_id: str,
    description: str,
    *,
    status: objective.NodeStatus = objective.NodeStatus.PENDING,
    depends_on: tuple[str, ...] | None = None,
    slug: str | None = None,
    comment: str | None = None,
) -> objective.ObjectiveNode:
    return objective.ObjectiveNode(
        id=node_id,
        description=description,
        status=status,
        depends_on=depends_on,
        slug=slug,
        comment=comment,
    )


def _default_nodes() -> list[objective.ObjectiveNode]:
    return [
        _node("1.1", "Predecessor work", slug="predecessor"),
        _node("1.2", "Refine me", slug="refine-me", comment="author note"),
        _node("1.10", "Tenth node"),
        _node("2.1", "Far future", depends_on=("1.10",)),
    ]


def _seed(
    store: LinearProjectObjectiveStore,
    *,
    nodes: list[objective.ObjectiveNode] | None = None,
    delivery: objective.DeliveryPolicy | None = None,
) -> str:
    ref = store.create_objective(
        title="Objective",
        body="# Objective\n\nProse.\n\n### Phase 1: One\n\n### Phase 2: Two\n",
        run_id=OBJ_RUN,
        roadmap_nodes=nodes if nodes is not None else _default_nodes(),
        delivery=delivery,
        delivery_lineage="01LINEAGE" if delivery is objective.DeliveryPolicy.STACKED else None,
    )
    return ref.id


def _provenance(run_id: str = "01AUTHRUN") -> RefinementProvenance:
    return RefinementProvenance(
        authoring_run_id=run_id,
        authored_at=TS,
        code_basis=RefinementCodeBasis(head_sha=HEAD, dirty=False, captured_at=TS),
    )


def _node_issue(ws: FakeLinearWorkspace, obj_id: str, node_id: str) -> dict[str, object]:
    for issue in ws.issues.values():
        if issue.get("project_id") != obj_id:
            continue
        att = linear_attachments.find_perk_attachment(
            ws.attachment_nodes_of(issue), kind=linear_attachments.OBJECTIVE_NODE_KIND
        )
        if att is not None and att.payload.get("id") == node_id:
            return issue
    raise AssertionError(f"no node-issue {node_id!r} on {obj_id!r}")


def _sentinel(ws: FakeLinearWorkspace, obj_id: str) -> dict[str, object]:
    for issue in ws.issues.values():
        if issue.get("project_id") == obj_id and linear_attachments.has_perk_attachment(
            ws.attachment_nodes_of(issue), kind=linear_attachments.OBJECTIVE_HEADER_KIND
        ):
            return issue
    raise AssertionError("no sentinel")


def _attachment_key(
    ws: FakeLinearWorkspace, issue: dict[str, object], kind: str
) -> tuple[str, str]:
    for (iid, url), value in ws.attachments.items():
        if iid != issue["id"]:
            continue
        metadata = value.get("metadata")
        if isinstance(metadata, dict) and cast("dict[str, object]", metadata).get("kind") == kind:
            return (iid, url)
    raise AssertionError(f"no {kind} attachment on {issue['identifier']}")


def _mutations(ws: FakeLinearWorkspace, start: int = 0) -> list[tuple[str, dict[str, object]]]:
    return [(q, v) for q, v in ws.requests[start:] if q.lstrip().startswith("mutation")]


def _mutation_names(ws: FakeLinearWorkspace, start: int = 0) -> list[str]:
    names: list[str] = []
    for query, _v in _mutations(ws, start):
        body = query.split("{", 1)[1]
        names.append(body.split("(", 1)[0].strip())
    return names


def _non_comment_state(ws: FakeLinearWorkspace) -> dict[str, object]:
    """Everything except comment lists — the surface refinement must never touch."""
    issues = {
        uuid: {k: copy.deepcopy(v) for k, v in issue.items() if k != "comments"}
        for uuid, issue in ws.issues.items()
    }
    return {
        "issues": issues,
        "attachments": copy.deepcopy(ws.attachments),
        "relations": list(ws.relations),
        "milestones": copy.deepcopy(ws.milestones),
        "projects": copy.deepcopy(ws.projects),
        "labels": dict(ws.labels),
    }


def _target(store: LinearProjectObjectiveStore, obj_id: str, node_id: str) -> RefinementTarget:
    snapshot = store.read_node_refinement_targets(objective_id=obj_id)
    assert snapshot is not None
    return next(t for t in snapshot.targets if t.identity.node_id == node_id)


def _document(
    target: RefinementTarget, markdown: str = "## Approach\n\nCarefully.\n"
) -> RefinementDocument:
    return codec.document_for_target(target, markdown=markdown, provenance=_provenance())


def _plan_header_fields(run_id: str, objective_id: str) -> dict[str, object]:
    return plan.render_plan_header_fields(
        plan.PlanHeader(run_id=run_id, created=TS, objective_id=objective_id)
    )


def _err(fn: Callable[[], object], code: RefinementErrorCode, **attrs: object) -> RefinementError:
    with pytest.raises(RefinementError) as info:
        fn()
    assert info.value.code is code, str(info.value)
    for key, value in attrs.items():
        assert getattr(info.value, key) == value, (key, getattr(info.value, key))
    return info.value


def _guard_err(fn: Callable[[], object], code: str, **attrs: object) -> MarkedCommentError:
    with pytest.raises(MarkedCommentError) as info:
        fn()
    assert info.value.code == code, str(info.value)
    for key, value in attrs.items():
        assert getattr(info.value, key) == value, (key, getattr(info.value, key))
    return info.value


LONG_MARKDOWN = (
    "## Approach\n\n"
    + "\n".join(f"- step {i}: do the thing with care and detail — ünïcödé 東京" for i in range(80))
    + "\n\n```python\nx = {'a': 1}\n# <!-- not a perk marker -->\n```\n\n"
    "| col | val |\n|---|---|\n| a | b |\n\n"
    + plan.render_plan_body("# Embedded plan example\n\n1. step", style="inline-code")
    + "\n\n\n"
)


# --------------------------------------------------------------------------- the store read


class TestSnapshotRead:
    def test_all_nodes_natural_order_identity_source_and_eligibility(self) -> None:
        ws, store, _issues = _harness()
        obj_id = _seed(store)
        store.update_objective_node(
            objective_id=obj_id, node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
        )
        store.update_objective_node(
            objective_id=obj_id, node_id="2.1", status=objective.NodeStatus.BLOCKED
        )
        before = len(ws.requests)
        snapshot = store.read_node_refinement_targets(objective_id=obj_id)
        assert snapshot is not None
        assert _mutations(ws, before) == []  # a pure read
        assert snapshot.backend == "linear"
        assert snapshot.objective_id == obj_id
        assert snapshot.objective_run_id == OBJ_RUN
        assert snapshot.objective_url == ws.projects[obj_id]["url"]
        assert [t.identity.node_id for t in snapshot.targets] == ["1.1", "1.2", "1.10", "2.1"]
        assert [t.status for t in snapshot.targets] == [
            objective.NodeStatus.IN_PROGRESS,
            objective.NodeStatus.PENDING,
            objective.NodeStatus.PENDING,
            objective.NodeStatus.BLOCKED,
        ]
        assert [t.eligible for t in snapshot.targets] == [False, True, True, True]
        t12 = snapshot.targets[1]
        issue = _node_issue(ws, obj_id, "1.2")
        assert t12.identity.carrier_id == issue["id"]  # the UUID, not the identifier
        assert t12.identity.objective_id == obj_id and t12.identity.backend == "linear"
        assert t12.carrier_identifier == issue["identifier"]
        assert t12.carrier_url == issue["url"]
        assert t12.source.description == "Refine me"
        assert t12.source.slug == "refine-me" and t12.source.comment == "author note"
        assert t12.source.issue_description == issue["description"]
        assert t12.plan_ref is None and t12.has_plan_metadata is False
        assert t12.source_digest == codec.source_digest(t12.source)
        # Observed dependencies from blocking relations (the explicit edge only; the
        # empty→None loss is retained); effective ones via the shared graph inference.
        deps = {t.identity.node_id: t.source.depends_on for t in snapshot.targets}
        assert deps == {"1.1": None, "1.2": None, "1.10": None, "2.1": ("1.10",)}
        effective = {t.identity.node_id: t.source.effective_depends_on for t in snapshot.targets}
        assert effective == {"1.1": (), "1.2": (), "1.10": (), "2.1": ("1.10",)}
        # Identity keys are distinct per node (1.1 / 1.10 / 1.2 never collide).
        assert len({codec.target_key(t.identity) for t in snapshot.targets}) == 4

    def test_sequential_inference_when_no_explicit_edges(self) -> None:
        _ws, store, _issues = _harness()
        obj_id = _seed(store, nodes=[_node("1.1", "a"), _node("1.2", "b"), _node("2.1", "c")])
        snapshot = store.read_node_refinement_targets(objective_id=obj_id)
        assert snapshot is not None
        effective = {t.identity.node_id: t.source.effective_depends_on for t in snapshot.targets}
        assert effective == {"1.1": (), "1.2": ("1.1",), "2.1": ("1.2",)}
        assert all(t.source.depends_on is None for t in snapshot.targets)

    def test_plan_metadata_presence_backlink_and_corrupt_payload(self) -> None:
        ws, store, _issues = _harness()
        obj_id = _seed(store)
        store.save_node_plan(
            objective_id=obj_id,
            node_id="1.2",
            header_fields=_plan_header_fields("01PLANRUN", obj_id),
            plan_markdown="# Plan\n\n1. step\n",
        )
        t12 = _target(store, obj_id, "1.2")
        issue = _node_issue(ws, obj_id, "1.2")
        assert t12.has_plan_metadata is True
        assert t12.plan_ref == objective.canonical_pr(str(issue["identifier"]))
        assert t12.status is objective.NodeStatus.PENDING and t12.eligible is False
        # A corrupt plan payload is still PRESENCE (no plan parse needed to disqualify).
        key = _attachment_key(ws, issue, linear_attachments.PLAN_HEADER_KIND)
        metadata = cast("dict[str, object]", ws.attachments[key]["metadata"])
        metadata["payload_json"] = "{not json"
        corrupt = _target(store, obj_id, "1.2")
        assert corrupt.has_plan_metadata is True and corrupt.eligible is False
        # A second plan-header attachment (multiple presence) still reads, still present.
        ws.attachments[(key[0], "https://perk.invalid/plan/other")] = copy.deepcopy(
            ws.attachments[key]
        )
        assert _target(store, obj_id, "1.2").has_plan_metadata is True

    def test_native_cancellation_projects_skipped(self) -> None:
        ws, store, _issues = _harness()
        obj_id = _seed(store)
        _node_issue(ws, obj_id, "1.10")["state_id"] = "st-canceled"
        t = _target(store, obj_id, "1.10")
        assert t.status is objective.NodeStatus.SKIPPED and t.eligible is False
        # Persisted status untouched by the read.
        payload = linear_attachments.find_perk_attachment(
            ws.attachment_nodes_of(_node_issue(ws, obj_id, "1.10")),
            kind=linear_attachments.OBJECTIVE_NODE_KIND,
        )
        assert payload is not None and payload.payload["status"] == "pending"

    def test_missing_non_perk_and_empty_objectives(self) -> None:
        ws, store, _issues = _harness()
        assert store.read_node_refinement_targets(objective_id="proj-nope") is None
        obj_id = _seed(store)
        # An empty roadmap is a SUPPORTED objective (targets == ()), not unsupported.
        for node_id in ("1.1", "1.2", "1.10", "2.1"):
            ws.delete_issue(str(_node_issue(ws, obj_id, node_id)["id"]))
        snapshot = store.read_node_refinement_targets(objective_id=obj_id)
        assert snapshot is not None and snapshot.targets == ()
        # No objective-header carrier: not a perk objective.
        ws.delete_issue(str(_sentinel(ws, obj_id)["id"]))
        assert store.read_node_refinement_targets(objective_id=obj_id) is None

    def test_duplicate_identity_metadata_is_ambiguous(self) -> None:
        ws, store, _issues = _harness()
        obj_id = _seed(store)
        sentinel = _sentinel(ws, obj_id)
        header_key = _attachment_key(ws, sentinel, linear_attachments.OBJECTIVE_HEADER_KIND)
        # (a) a second sentinel-like carrier
        extra = ws._create_issue({"title": "dup", "projectId": obj_id})
        ws.attachments[(str(extra["id"]), header_key[1])] = copy.deepcopy(
            ws.attachments[header_key]
        )
        with pytest.raises(RefinementTargetReadError) as info:
            store.read_node_refinement_targets(objective_id=obj_id)
        assert info.value.code == "ambiguous_target"
        del ws.attachments[(str(extra["id"]), header_key[1])]
        # (b) two objective-header attachments on one sentinel
        ws.attachments[(header_key[0], "https://perk.invalid/objective/other")] = copy.deepcopy(
            ws.attachments[header_key]
        )
        with pytest.raises(RefinementTargetReadError) as info_b:
            store.read_node_refinement_targets(objective_id=obj_id)
        assert info_b.value.code == "ambiguous_target"
        del ws.attachments[(header_key[0], "https://perk.invalid/objective/other")]
        # (c) two carriers claiming node 1.2
        node12 = _node_issue(ws, obj_id, "1.2")
        node_key = _attachment_key(ws, node12, linear_attachments.OBJECTIVE_NODE_KIND)
        ws.attachments[(str(extra["id"]), "https://perk.invalid/node/X")] = copy.deepcopy(
            ws.attachments[node_key]
        )
        with pytest.raises(RefinementTargetReadError) as info_c:
            store.read_node_refinement_targets(objective_id=obj_id)
        assert info_c.value.code == "ambiguous_target" and "1.2" in str(info_c.value)
        del ws.attachments[(str(extra["id"]), "https://perk.invalid/node/X")]
        # (d) two node attachments on one carrier
        ws.attachments[(node_key[0], "https://perk.invalid/node/Y")] = copy.deepcopy(
            ws.attachments[node_key]
        )
        with pytest.raises(RefinementTargetReadError) as info_d:
            store.read_node_refinement_targets(objective_id=obj_id)
        assert info_d.value.code == "ambiguous_target"

    def test_malformed_metadata_is_malformed_target(self) -> None:
        ws, store, _issues = _harness()
        obj_id = _seed(store)
        node12 = _node_issue(ws, obj_id, "1.2")
        node_key = _attachment_key(ws, node12, linear_attachments.OBJECTIVE_NODE_KIND)
        metadata = cast("dict[str, object]", ws.attachments[node_key]["metadata"])
        original = metadata["payload_json"]

        def expect_malformed() -> RefinementTargetReadError:
            with pytest.raises(RefinementTargetReadError) as info:
                store.read_node_refinement_targets(objective_id=obj_id)
            assert info.value.code == "malformed_target"
            assert isinstance(info.value, ObjectiveStoreError)
            return info.value

        metadata["payload_json"] = "{not json"
        expect_malformed()
        metadata["payload_json"] = '{"id": "1.2", "status": "bogus", "description": "x"}'
        expect_malformed()
        metadata["payload_json"] = '{"status": "pending", "description": "x"}'
        expect_malformed()
        metadata["payload_json"] = original
        # An unreadable perk envelope identity on the carrier cannot prove plan absence.
        ws.attachments[(node_key[0], "https://perk.invalid/mystery")] = {
            "id": "att-mystery",
            "title": "?",
            "subtitle": None,
            "metadata": {"source": "perk", "payload_json": "{}"},
        }
        expect_malformed()
        del ws.attachments[(node_key[0], "https://perk.invalid/mystery")]
        # A foreign (non-perk) attachment, e.g. a PR card, is fine.
        ws.attachments[(node_key[0], "https://github.com/o/r/pull/1")] = {
            "id": "att-pr",
            "title": "GitHub PR #1",
            "subtitle": "OPEN",
            "metadata": None,
        }
        assert store.read_node_refinement_targets(objective_id=obj_id) is not None
        # The objective-header without a readable run id.
        sentinel = _sentinel(ws, obj_id)
        header_key = _attachment_key(ws, sentinel, linear_attachments.OBJECTIVE_HEADER_KIND)
        header_meta = cast("dict[str, object]", ws.attachments[header_key]["metadata"])
        header_meta["payload_json"] = '{"status": "active"}'
        expect_malformed()

    def test_incomplete_or_unsignalled_attachment_connection_refuses(self) -> None:
        class _Truncating(FakeLinearWorkspace):
            def __init__(self) -> None:
                super().__init__()
                self.page_info: dict[str, object] | None = {"hasNextPage": True}

            def _project_issue_node(
                self,
                issue: dict[str, object],
                *,
                with_milestone: bool = False,
                with_attachment_page_info: bool = False,
            ) -> dict[str, object]:
                node = super()._project_issue_node(
                    issue, with_milestone=with_milestone, with_attachment_page_info=False
                )
                if with_attachment_page_info and self.page_info is not None:
                    cast("dict[str, object]", node["attachments"])["pageInfo"] = self.page_info
                return node

        ws = _Truncating()
        _ws, store, _issues = _harness(ws)
        obj_id = _seed(store)
        # The read asks for the completeness signal (a focused safety assertion, not a snapshot).
        store.get_objective(objective_id=obj_id)
        with pytest.raises(RefinementTargetReadError) as info:
            store.read_node_refinement_targets(objective_id=obj_id)
        assert info.value.code == "malformed_target" and "incomplete" in str(info.value)
        refinement_queries = [q for q, _v in ws.requests if "pageInfo { hasNextPage }" in q]
        assert refinement_queries and all("attachments(first: 50)" in q for q in refinement_queries)
        # No completeness signal at all: refused too (never inferred).
        ws.page_info = None
        with pytest.raises(RefinementTargetReadError) as info2:
            store.read_node_refinement_targets(objective_id=obj_id)
        assert info2.value.code == "malformed_target"
        ws.page_info = {"hasNextPage": "no"}
        with pytest.raises(RefinementTargetReadError):
            store.read_node_refinement_targets(objective_id=obj_id)
        # The ordinary projection read never asked for (and never needs) the signal.
        assert store.get_objective(objective_id=obj_id) is not None

    def test_transport_failure_stays_a_plain_store_error(self) -> None:
        ws, store, _issues = _harness()
        obj_id = _seed(store)

        def fail_issue_pages(query: str, _v: dict[str, object]) -> None:
            if "issues(first" in query and "project(id" in query:
                raise LinearGraphQLError(
                    "Linear GraphQL error: rate limited", codes=("RATELIMITED",)
                )

        ws.before_request.append(fail_issue_pages)
        with pytest.raises(ObjectiveStoreError) as info:
            store.read_node_refinement_targets(objective_id=obj_id)
        assert not isinstance(info.value, RefinementTargetReadError)
        assert "rate limited" in str(info.value)

    def test_unsupported_stores_refuse_before_network(self, tmp_path: Path) -> None:
        github_store = GitHubObjectiveStore(tmp_path)
        with pytest.raises(RefinementTargetReadError) as info:
            github_store.read_node_refinement_targets(objective_id="")
        assert info.value.code == "unsupported_backend"
        ws = FakeLinearWorkspace()
        dormant = LinearObjectiveStore(ws, team_key=_TEAM_KEY, repo_root=REPO)
        with pytest.raises(RefinementTargetReadError) as info2:
            dormant.read_node_refinement_targets(objective_id="ENG-1")
        assert info2.value.code == "unsupported_backend"
        assert ws.requests == []
        # Through the service: no capability flag, no dummy-node request, no comment read.
        err = _err(
            lambda: service.select_refinement_target(
                github_store, GitHubIssueBackend(tmp_path), objective_id="1"
            ),
            RefinementErrorCode.UNSUPPORTED_BACKEND,
            write_attempted=False,
        )
        assert isinstance(err.__cause__, RefinementTargetReadError)


# --------------------------------------------------------------------------- guarded upsert


MARKER = "<!-- perk:test-guard:v1:abc -->"


def _bare_issue(ws: FakeLinearWorkspace) -> dict[str, object]:
    return ws._create_issue({"title": "bare", "description": ""})


def _body(text: str) -> str:
    return f"{MARKER}\n\n{text}"


class TestGuardedUpsert:
    def test_first_save_creates_replacement_updates_convergence_skips(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        absent = MarkedCommentExpectation(None, None)
        long_body = _body("line one\n" * 50 + "<!-- perk:other:x -->\n")
        start = len(ws.requests)
        result = issues.upsert_marked_comment(
            issue_id=iid, marker=MARKER, body=long_body, expected=absent
        )
        assert result.posted is True and result.verified_comment is not None
        verified = result.verified_comment
        [comment] = ws.comments_of(issue)
        assert verified.id == comment["id"]
        assert verified.body == to_linear_markdown(long_body) == comment["body"]
        assert verified.created_at == comment["createdAt"] and verified.edited_at is None
        assert verified.author.kind == "perk"
        assert _mutation_names(ws, start) == ["commentCreate"]
        # The create targeted the resolved issue id.
        [(_q, variables)] = _mutations(ws, start)
        assert cast("dict[str, object]", variables["input"])["issueId"] == iid

        # Replacement with a SHORTER body: same comment id, old tail gone, edited_at set.
        start = len(ws.requests)
        short_body = _body("short")
        expected = MarkedCommentExpectation(verified.id, body_digest(verified.body))
        replaced = issues.upsert_marked_comment(
            issue_id=iid, marker=MARKER, body=short_body, expected=expected
        )
        assert replaced.verified_comment is not None
        assert replaced.verified_comment.id == verified.id
        assert replaced.verified_comment.body == to_linear_markdown(short_body)
        assert "line one" not in replaced.verified_comment.body
        assert replaced.verified_comment.edited_at is not None
        assert _mutation_names(ws, start) == ["commentUpdate"]
        [(_q, variables)] = _mutations(ws, start)
        assert variables["id"] == verified.id  # the observed comment UUID

        # Convergence: the same body again, even with the ORIGINAL absent expectation → no write.
        start = len(ws.requests)
        again = issues.upsert_marked_comment(
            issue_id=iid, marker=MARKER, body=short_body, expected=absent
        )
        assert again.posted is True and again.verified_comment == replaced.verified_comment
        assert _mutations(ws, start) == []

    def test_stale_expectations_refuse_without_writing(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        first = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v1"),
            expected=MarkedCommentExpectation(None, None),
        )
        assert first.verified_comment is not None
        cid = first.verified_comment.id
        start = len(ws.requests)
        # Expected absence, but present with other content.
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v2"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "stale_comment",
            comment_ids=(cid,),
            write_attempted=False,
        )
        # Expected a different digest (a competing edit landed before this save).
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v2"),
                expected=MarkedCommentExpectation(cid, "0" * 64),
            ),
            "stale_comment",
            write_attempted=False,
        )
        # Expected a comment that is now absent.
        ws.comments_of(issue).clear()
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v2"),
                expected=MarkedCommentExpectation(cid, body_digest("x")),
            ),
            "stale_comment",
            comment_ids=(),
        )
        assert _mutations(ws, start) == []

    def test_duplicates_and_misplaced_markers_refuse_across_pages(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        identifier = str(issue["identifier"])
        # > one page of noise, then the owned comment on the LAST page: found (converges).
        for i in range(5):
            ws.add_foreign_comment(identifier, f"linkback {i}")
        owned = to_linear_markdown(_body("v1"))
        first_id = ws.add_foreign_comment(identifier, owned)
        start = len(ws.requests)
        result = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v1"),
            expected=MarkedCommentExpectation(None, None),
        )
        assert result.verified_comment is not None and result.verified_comment.id == first_id
        assert _mutations(ws, start) == []
        # An identical duplicate on a later page: ambiguous, ids reported, nothing written.
        second_id = ws.add_foreign_comment(identifier, owned)
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v1"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "ambiguous_comment",
            comment_ids=(first_id, second_id),
            write_attempted=False,
        )
        ws.comments_of(issue).pop()
        # A misplaced marker (not the first line) elsewhere: malformed; a repeated one: malformed.
        misplaced = ws.add_foreign_comment(identifier, "note\n" + to_linear_markdown(MARKER))
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v1"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "malformed_comment",
            comment_ids=(misplaced,),
        )
        ws.comments_of(issue).pop()
        ws.comment_by_id(first_id)["body"] = owned + "\n" + to_linear_markdown(MARKER)
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v1"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "malformed_comment",
            comment_ids=(first_id,),
        )
        assert _mutations(ws, start) == []

    def test_dry_run_and_input_validation_touch_no_network(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        start = len(ws.requests)
        result = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("x"),
            dry_run=True,
            expected=MarkedCommentExpectation(None, None),
        )
        assert result.posted is False and result.verified_comment is None
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("x"),
                dry_run=True,
                expected=MarkedCommentExpectation("c", None),
            ),
            "invalid_input",
        )
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body="intro\n" + MARKER,
                expected=MarkedCommentExpectation(None, None),
            ),
            "invalid_input",
        )
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("x") + "\n" + MARKER,
                expected=MarkedCommentExpectation(None, None),
            ),
            "invalid_input",
        )
        assert ws.requests[start:] == []

    def test_ordinary_upsert_is_unchanged(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        # Substring semantics, first hit, no verification, verified_comment stays None.
        ws.add_foreign_comment(str(issue["identifier"]), "prefix " + to_linear_markdown(MARKER))
        result = issues.upsert_marked_comment(issue_id=iid, marker=MARKER, body=_body("v"))
        assert result == CommentResult(posted=True)
        [comment] = ws.comments_of(issue)
        assert comment["body"] == to_linear_markdown(_body("v"))
        assert (
            issues.upsert_marked_comment(
                issue_id=iid, marker=MARKER, body=_body("v"), dry_run=True
            ).verified_comment
            is None
        )

    def test_github_guarded_arm_refuses_before_any_operation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from perk.backends.github import plans

        calls: list[object] = []
        monkeypatch.setattr(
            plans, "upsert_marked_comment", lambda **k: calls.append(k) or _Posted()
        )
        backend = GitHubIssueBackend(tmp_path)
        for dry in (True, False):
            _guard_err(
                lambda d=dry: backend.upsert_marked_comment(
                    issue_id="1",
                    marker=MARKER,
                    body=_body("x"),
                    dry_run=d,
                    expected=MarkedCommentExpectation(None, None),
                ),
                "unsupported_backend",
                write_attempted=False,
            )
        assert calls == []
        # Ordinary forwarding unchanged.
        result = backend.upsert_marked_comment(issue_id="1", marker=MARKER, body=_body("x"))
        assert result.posted is True and result.verified_comment is None and len(calls) == 1

    def test_mutation_landed_then_raised_is_success(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])

        def raise_after(query: str, _v: dict[str, object]) -> None:
            if "commentCreate(" in query or "commentUpdate(" in query:
                raise IssueBackendError("Linear API request failed: connection reset")

        ws.after_request.append(raise_after)
        result = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v1"),
            expected=MarkedCommentExpectation(None, None),
        )
        assert result.posted is True and result.verified_comment is not None
        assert len(ws.comments_of(issue)) == 1
        verified = result.verified_comment
        replaced = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v2"),
            expected=MarkedCommentExpectation(verified.id, body_digest(verified.body)),
        )
        assert replaced.verified_comment is not None
        assert replaced.verified_comment.body == to_linear_markdown(_body("v2"))
        assert len(ws.comments_of(issue)) == 1

    def test_failed_mutation_with_proven_baseline_is_backend_error_keeping_the_diagnostic(
        self,
    ) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        huge = _body("x" * 200_000)

        def native_size_error(query: str, _v: dict[str, object]) -> None:
            if "commentCreate(" in query:
                raise LinearGraphQLError(
                    "Linear GraphQL error: Argument Validation Error (body too long)",
                    codes=("INVALID_INPUT",),
                )

        ws.before_request.append(native_size_error)
        start = len(ws.requests)
        err = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=huge,
                expected=MarkedCommentExpectation(None, None),
            ),
            "backend_error",
            write_attempted=True,
            comment_ids=(),
        )
        assert isinstance(err.__cause__, LinearGraphQLError) and "too long" in str(err)
        assert ws.comments_of(issue) == []
        # Exactly one attempt, the FULL content (never shortened), no retry.
        attempts = [v for q, v in _mutations(ws, start) if "commentCreate(" in q]
        assert len(attempts) == 1
        assert cast("dict[str, object]", attempts[0]["input"])["body"] == to_linear_markdown(huge)
        # The update twin: an existing comment, failed update, baseline unchanged.
        ws.before_request.clear()
        first = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v1"),
            expected=MarkedCommentExpectation(None, None),
        )
        first_verified = first.verified_comment
        assert first_verified is not None

        def fail_update(query: str, _v: dict[str, object]) -> None:
            if "commentUpdate(" in query:
                raise IssueBackendError("Linear API request failed with HTTP 502")

        ws.before_request.append(fail_update)
        err2 = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v2"),
                expected=MarkedCommentExpectation(
                    first_verified.id, body_digest(first_verified.body)
                ),
            ),
            "backend_error",
            write_attempted=True,
        )
        assert "502" in str(err2)
        [comment] = ws.comments_of(issue)
        assert comment["body"] == to_linear_markdown(_body("v1"))

    def test_unreadable_verification_is_write_unverified(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        armed = {"after_write": False}

        def arm(query: str, _v: dict[str, object]) -> None:
            if "commentCreate(" in query:
                armed["after_write"] = True

        def fail_scan(query: str, _v: dict[str, object]) -> None:
            if armed["after_write"] and "comments(first" in query:
                raise IssueBackendError("Linear API request failed: timeout")

        ws.after_request.append(arm)
        ws.before_request.append(fail_scan)
        err = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v1"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "write_unverified",
            write_attempted=True,
        )
        assert "timeout" in str(err)
        assert len(ws.comments_of(issue)) == 1  # landed, but never reported as success

    def test_server_alteration_and_competing_edit_after_write_are_stale(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        first = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v1"),
            expected=MarkedCommentExpectation(None, None),
        )
        assert first.verified_comment is not None
        expected = MarkedCommentExpectation(
            first.verified_comment.id, body_digest(first.verified_comment.body)
        )

        def truncate(query: str, v: dict[str, object]) -> None:
            if "commentUpdate(" in query:
                comment = ws.comment_by_id(str(v["id"]))
                comment["body"] = str(comment["body"])[:-3]  # server truncation / a competing edit

        ws.after_request.append(truncate)
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid, marker=MARKER, body=_body("v2 long"), expected=expected
            ),
            "stale_comment",
            comment_ids=(first.verified_comment.id,),
            write_attempted=True,
        )

    def test_nominal_success_with_unchanged_baseline_is_write_unverified(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        first = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v1"),
            expected=MarkedCommentExpectation(None, None),
        )
        first_verified = first.verified_comment
        assert first_verified is not None
        old_body = first_verified.body

        def revert(query: str, v: dict[str, object]) -> None:
            if "commentUpdate(" in query:
                ws.comment_by_id(str(v["id"]))["body"] = old_body

        ws.after_request.append(revert)
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v2"),
                expected=MarkedCommentExpectation(first_verified.id, body_digest(old_body)),
            ),
            "write_unverified",
            write_attempted=True,
        )
        # Absent after a nominal create: the same outcome.
        ws.after_request.clear()
        ws.comments_of(issue).clear()

        def vanish(query: str, _v: dict[str, object]) -> None:
            if "commentCreate(" in query:
                ws.comments_of(issue).clear()

        ws.after_request.append(vanish)
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v1"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "write_unverified",
            write_attempted=True,
        )

    def test_concurrent_first_saves_yield_ambiguity_even_with_equal_bodies(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        identifier = str(issue["identifier"])
        desired = to_linear_markdown(_body("v1"))

        def competitor(query: str, _v: dict[str, object]) -> None:
            if "commentCreate(" in query and len(ws.comments_of(issue)) == 0:
                ws.add_foreign_comment(identifier, desired)  # the other writer lands first

        ws.before_request.append(competitor)
        err = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v1"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "ambiguous_comment",
            write_attempted=True,
        )
        assert len(err.comment_ids) == 2 and len(ws.comments_of(issue)) == 2
        # No automatic deletion: both remain; a retry keeps refusing (never rewrites either).
        ws.before_request.clear()
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v1"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "ambiguous_comment",
            write_attempted=False,
        )
        assert len(ws.comments_of(issue)) == 2

    def test_writer_after_final_verification_is_the_documented_residual(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        iid = str(issue["id"])
        result = issues.upsert_marked_comment(
            issue_id=iid,
            marker=MARKER,
            body=_body("v1"),
            expected=MarkedCommentExpectation(None, None),
        )
        verified = result.verified_comment
        assert verified is not None
        # The returned value is an honest observation of what was verified …
        [comment] = ws.comments_of(issue)
        assert verified.body == comment["body"]
        # … a later human edit is invisible to that result and surfaces on the next guarded save.
        comment["body"] = str(comment["body"]) + "\nhuman addendum"
        _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=iid,
                marker=MARKER,
                body=_body("v2"),
                expected=MarkedCommentExpectation(verified.id, body_digest(verified.body)),
            ),
            "stale_comment",
            write_attempted=False,
        )


class _Posted:
    posted = True


# --------------------------------------------------------------------------- service over Linear


class TestServiceOverLinear:
    def test_select_save_read_replace_and_retry(self) -> None:
        ws, store, issues = _harness()
        obj_id = _seed(store)
        state_before = _non_comment_state(ws)

        read = service.select_refinement_target(store, issues, objective_id=obj_id)
        assert read.target.identity.node_id == "1.1" and read.saved is None  # readiness ignored
        explicit = service.select_refinement_target(
            store, issues, objective_id=obj_id, node_id="2.1"
        )
        assert explicit.target.identity.node_id == "2.1"

        start = len(ws.requests)
        document = _document(read.target, LONG_MARKDOWN)
        saved = service.save_node_refinement(
            store, issues, request=RefinementSaveRequest(document=document, expected=read.expected)
        )
        assert isinstance(saved, SavedRefinement)
        assert _mutation_names(ws, start) == ["commentCreate"]
        node_issue = _node_issue(ws, obj_id, "1.1")
        [comment] = ws.comments_of(node_issue)
        assert saved.comment.id == comment["id"]
        assert comment["body"] == to_linear_markdown(codec.render_refinement(document))
        # Full content round trip (the transcoder is the identity on this Markdown) + provenance.
        assert saved.document.markdown == LONG_MARKDOWN
        assert saved.document.provenance == _provenance()
        assert saved.document.source == read.target.source
        assert saved.saved_at == comment["createdAt"]
        assert _non_comment_state(ws) == state_before  # comment-only

        again = service.read_node_refinement(store, issues, objective_id=obj_id, node_id="1.1")
        assert again.saved == saved and again.source_changed is False
        nxt = service.select_refinement_target(store, issues, objective_id=obj_id)
        assert nxt.target.identity.node_id == "1.2"  # 1.1 now carries a valid record
        re_refine = service.select_refinement_target(
            store, issues, objective_id=obj_id, node_id="1.1"
        )
        assert re_refine.saved == saved

        # Replacement: shorter Markdown, same comment id, old tail gone, provenance preserved.
        start = len(ws.requests)
        shorter = codec.document_for_target(
            re_refine.target, markdown="## Shorter\n", provenance=_provenance("01SECOND")
        )
        request = RefinementSaveRequest(document=shorter, expected=re_refine.expected)
        replaced = service.save_node_refinement(store, issues, request=request)
        assert replaced.comment.id == saved.comment.id
        assert _mutation_names(ws, start) == ["commentUpdate"]
        assert "step 79" not in replaced.comment.body
        assert replaced.document.provenance.authoring_run_id == "01SECOND"
        assert (
            replaced.comment.edited_at is not None
            and replaced.saved_at == replaced.comment.edited_at
        )

        # An explicit retry of the SAME request converges: same verified comment, no mutation.
        start = len(ws.requests)
        retried = service.save_node_refinement(store, issues, request=request)
        assert retried == replaced
        assert _mutations(ws, start) == []
        assert _non_comment_state(ws) == state_before

    def test_pre_write_changes_refuse_without_mutation(self) -> None:
        ws, store, issues = _harness()
        obj_id = _seed(store)
        read = service.select_refinement_target(store, issues, objective_id=obj_id, node_id="1.2")
        request = RefinementSaveRequest(document=_document(read.target), expected=read.expected)

        def attempt() -> object:
            return service.save_node_refinement(store, issues, request=request)

        # Sibling progress alone never stales the source.
        store.update_objective_node(
            objective_id=obj_id, node_id="1.1", status=objective.NodeStatus.DONE
        )
        assert _target(store, obj_id, "1.2").source_digest == read.target.source_digest
        # A description edit stales it.
        store.update_objective_node(objective_id=obj_id, node_id="1.2", description="Edited")
        start = len(ws.requests)
        _err(attempt, RefinementErrorCode.STALE_SOURCE, write_attempted=False)
        store.update_objective_node(objective_id=obj_id, node_id="1.2", description="Refine me")
        # A human edit of the carrier description stales it too.
        node_issue = _node_issue(ws, obj_id, "1.2")
        original_desc = node_issue["description"]
        node_issue["description"] = str(original_desc) + "\n\nhuman addendum"
        _err(attempt, RefinementErrorCode.STALE_SOURCE)
        node_issue["description"] = original_desc
        # A claim makes the node ineligible; so does native cancellation; so does plan metadata.
        store.update_objective_node(
            objective_id=obj_id, node_id="1.2", status=objective.NodeStatus.PLANNING
        )
        _err(attempt, RefinementErrorCode.NODE_INELIGIBLE)
        store.update_objective_node(
            objective_id=obj_id, node_id="1.2", status=objective.NodeStatus.PENDING
        )
        node_issue["state_id"] = "st-canceled"
        _err(attempt, RefinementErrorCode.NODE_INELIGIBLE)
        node_issue["state_id"] = "st-todo"
        # Every refusal above was mutation-free on the refinement side (the node updates that
        # staged the scenarios are the only writes in this window).
        assert not any(
            "commentCreate" in q or "commentUpdate" in q for q, _v in _mutations(ws, start)
        )
        # A prior refinement that appeared meanwhile: the retained absent expectation is stale.
        service.save_node_refinement(
            store,
            issues,
            request=RefinementSaveRequest(
                document=_document(read.target, "## Other session\n"), expected=read.expected
            ),
        )
        start = len(ws.requests)
        _err(attempt, RefinementErrorCode.STALE_REFINEMENT, write_attempted=False)
        assert _mutations(ws, start) == []
        # Identity moved (a superseding objective run): stale_source.
        sentinel = _sentinel(ws, obj_id)
        header_key = _attachment_key(ws, sentinel, linear_attachments.OBJECTIVE_HEADER_KIND)
        meta = cast("dict[str, object]", ws.attachments[header_key]["metadata"])
        meta["payload_json"] = str(meta["payload_json"]).replace(OBJ_RUN, "01NEWRUN")
        _err(attempt, RefinementErrorCode.STALE_SOURCE)

    def test_coexistence_with_real_plan_and_plan_comment_exclusion(self) -> None:
        ws, store, issues = _harness()
        obj_id = _seed(store)
        read = service.select_refinement_target(store, issues, objective_id=obj_id, node_id="1.2")
        # The refinement embeds a COMPLETE plan-body example.
        saved = service.save_node_refinement(
            store,
            issues,
            request=RefinementSaveRequest(
                document=_document(read.target, LONG_MARKDOWN), expected=read.expected
            ),
        )
        node_issue = _node_issue(ws, obj_id, "1.2")
        identifier = str(node_issue["identifier"])
        assert issues.get_plan_body(issue_id=identifier) is None  # never read as the plan
        refinement_state_before = _non_comment_state(ws)

        # Planning after refinement: the real plan lands beside it.
        store.update_objective_node(
            objective_id=obj_id, node_id="1.2", status=objective.NodeStatus.PLANNING
        )
        plan_start = len(ws.requests)
        store.save_node_plan(
            objective_id=obj_id,
            node_id="1.2",
            header_fields=_plan_header_fields("01PLANRUN", obj_id),
            plan_markdown="# Real plan\n\nprose\n",
        )
        plan_mutations = _mutation_names(ws, plan_start)
        assert "commentCreate" in plan_mutations and "commentUpdate" not in plan_mutations
        comments = ws.comments_of(node_issue)
        assert len(comments) == 2
        assert comments[0]["id"] == saved.comment.id and comments[0]["body"] == saved.comment.body
        assert issues.get_plan_body(issue_id=identifier) == "# Real plan\n\nprose"
        assert _non_comment_state(ws) != refinement_state_before  # the plan DID write metadata

        # Historical refinement reads stay available; new refinement saves refuse.
        after = service.read_node_refinement(store, issues, objective_id=obj_id, node_id="1.2")
        assert after.saved is not None and after.saved.document == saved.document
        assert after.target.has_plan_metadata is True and after.target.eligible is False
        start = len(ws.requests)
        _err(
            lambda: service.save_node_refinement(
                store,
                issues,
                request=RefinementSaveRequest(
                    document=_document(after.target, "## Late\n"), expected=after.expected
                ),
            ),
            RefinementErrorCode.NODE_INELIGIBLE,
        )
        assert _mutations(ws, start) == []

        # Plan re-save and the issue-tier plan update patch the PLAN comment, never the refinement.
        store.save_node_plan(
            objective_id=obj_id,
            node_id="1.2",
            header_fields=_plan_header_fields("01PLANRUN", obj_id),
            plan_markdown="# Real plan v2\n",
        )
        issues.update_plan_issue(
            issue_id=identifier,
            title="t",
            body_comment=plan.render_plan_body("# Real plan v3\n", style="inline-code"),
        )
        comments = ws.comments_of(node_issue)
        assert len(comments) == 2 and comments[0]["body"] == saved.comment.body
        assert issues.get_plan_body(issue_id=identifier) == "# Real plan v3"
        # A corrupted refinement header is STILL excluded from plan selection.
        comments[0]["body"] = str(comments[0]["body"]).replace("```json\n{", "```json\n{{", 1)
        assert issues.get_plan_body(issue_id=identifier) == "# Real plan v3"
        # A real plan comment with later marker discussion remains the plan.
        other_key = codec.target_key(
            RefinementIdentity(
                backend="linear",
                objective_id="x",
                objective_run_id="y",
                node_id="9.9",
                carrier_id="z",
            )
        )
        comments[1]["body"] = (
            str(comments[1]["body"])
            + "\n\nDiscussion of perk:objective-refinement:v1 markers, e.g. "
            + codec.inline_marker(other_key)
        )
        plan_body = issues.get_plan_body(issue_id=identifier)
        assert plan_body is not None and plan_body.startswith("# Real plan v3")
        # Human prose + unrelated comments survive alongside both artifacts.
        ws.add_human_comment(identifier, "Looks good to me.")
        assert len(ws.comments_of(node_issue)) == 3
        assert "perk impl" in str(node_issue["description"])  # the plan callout is intact

    def test_adoption_never_overwrites_a_refinement_carrying_a_plan_example(self) -> None:
        ws, _store, issues = _harness()
        issue = _bare_issue(ws)
        identifier = str(issue["identifier"])
        # A refinement-owned comment with a complete plan-body example (and a damaged header).
        rendered = codec.render_refinement(
            RefinementDocument(
                identity=_standalone_identity(),
                source=_standalone_source(),
                source_digest=codec.source_digest(_standalone_source()),
                provenance=_provenance(),
                markdown=LONG_MARKDOWN,
            )
        )
        damaged = to_linear_markdown(rendered).replace("```json\n{", "```json\n{{", 1)
        refinement_id = ws.add_foreign_comment(identifier, damaged)
        issues.adopt_issue_as_plan(
            issue_id=identifier,
            header_fields=_plan_header_fields("01ADOPT", "obj"),
            plan_markdown="# Adopted\n",
            callout="callout",
            command="perk impl X",
        )
        comments = ws.comments_of(issue)
        assert len(comments) == 2 and comments[0]["id"] == refinement_id
        assert comments[0]["body"] == damaged
        assert issues.get_plan_body(issue_id=identifier) == "# Adopted"

    def test_planning_after_the_final_check_leaves_an_inert_late_refinement(self) -> None:
        ws, store, issues = _harness()
        obj_id = _seed(store)
        read = service.select_refinement_target(store, issues, objective_id=obj_id, node_id="1.2")
        request = RefinementSaveRequest(document=_document(read.target), expected=read.expected)

        def plan_lands_first(query: str, _v: dict[str, object]) -> None:
            if "commentCreate(" in query:
                ws.before_request.clear()
                store.save_node_plan(
                    objective_id=obj_id,
                    node_id="1.2",
                    header_fields=_plan_header_fields("01PLANRUN", obj_id),
                    plan_markdown="# Plan first\n",
                )

        ws.before_request.append(plan_lands_first)
        saved = service.save_node_refinement(store, issues, request=request)  # not atomic: lands
        node_issue = _node_issue(ws, obj_id, "1.2")
        bodies = [c["body"] for c in ws.comments_of(node_issue)]
        assert saved.comment.body in bodies and len(bodies) == 2
        # No rollback, no plan update: the plan stays exactly as saved; the refinement is inert.
        assert issues.get_plan_body(issue_id=str(node_issue["identifier"])) == "# Plan first"
        after = service.read_node_refinement(store, issues, objective_id=obj_id, node_id="1.2")
        assert after.saved is not None and after.target.eligible is False


def _standalone_identity() -> RefinementIdentity:
    return RefinementIdentity(
        backend="linear", objective_id="p", objective_run_id="r", node_id="1.1", carrier_id="c"
    )


def _standalone_source() -> RefinementSource:
    return RefinementSource(
        description="d",
        slug=None,
        comment=None,
        depends_on=None,
        effective_depends_on=(),
        issue_description="d",
    )


# --------------------------------------------------------------------------- the Phase-1 gate


def _scaffold_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@x.io"], cwd=root, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True, timeout=30)
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, timeout=30)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, timeout=30)
    cfg = root / ".perk"
    cfg.mkdir()
    (cfg / "config.toml").write_text(
        f'[issues]\nbackend = "linear"\nteam = "{_TEAM_KEY}"\n', encoding="utf-8"
    )


@pytest.mark.parametrize(
    "delivery", [None, objective.DeliveryPolicy.STACKED], ids=["incremental", "stacked"]
)
def test_phase1_gate_linear_refinement_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: objective.DeliveryPolicy | None
) -> None:
    """The named offline Phase-1 persistence gate (contracts.md §8.67): real resolvers, real
    store + adapter + service over ONE fake workspace, a real temp checkout as the code basis."""
    root = tmp_path / "repo"
    root.mkdir()
    _scaffold_repo(root)
    ws = FakeLinearWorkspace()
    monkeypatch.setattr(linear_client, "client_from_env", lambda *a, **k: ws)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    store = resolve.resolve_objective_store(root)
    issues = resolve.resolve_issue_backend(root)
    assert isinstance(store, LinearProjectObjectiveStore)
    assert isinstance(issues, LinearIssueBackend)

    # An objective with an unfinished (claimed + planned) predecessor and a blocked future node.
    obj_id = _seed(store, delivery=delivery)
    store.update_objective_node(
        objective_id=obj_id, node_id="1.1", status=objective.NodeStatus.PLANNING
    )
    store.save_node_plan(
        objective_id=obj_id,
        node_id="1.1",
        header_fields=_plan_header_fields("01PREDRUN", obj_id),
        plan_markdown="# Predecessor plan\n",
    )
    store.update_objective_node(
        objective_id=obj_id, node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
    )
    store.update_objective_node(
        objective_id=obj_id, node_id="2.1", status=objective.NodeStatus.BLOCKED
    )
    roadmap_before = store.get_objective(objective_id=obj_id)
    assert roadmap_before is not None
    sentinel = _sentinel(ws, obj_id)
    manifest_key = _attachment_key(ws, sentinel, linear_attachments.OBJECTIVE_MANIFEST_KIND)
    manifest_before = copy.deepcopy(ws.attachments[manifest_key])
    state_before = _non_comment_state(ws)
    sentinel_comments_before = len(ws.comments_of(sentinel))

    # The actual temp-checkout code basis (the producers the authoring caller uses).
    head_sha = git.resolve_commit(root, "HEAD")
    assert head_sha is not None
    (root / "scratch.txt").write_text(
        "wip\n", encoding="utf-8"
    )  # a dirty tree is recorded, not refused
    captured_at = plan.now_iso()
    provenance = RefinementProvenance(
        authoring_run_id="01GATEAUTH",
        authored_at=plan.now_iso(),
        code_basis=RefinementCodeBasis(
            head_sha=head_sha, dirty=git.is_dirty(root), captured_at=captured_at
        ),
    )
    assert provenance.code_basis.dirty is True

    # Select (default): the predecessor is ineligible, 1.2 is the first eligible absence.
    read = service.select_refinement_target(store, issues, objective_id=obj_id)
    assert read.target.identity.node_id == "1.2" and read.saved is None
    blocked = service.select_refinement_target(store, issues, objective_id=obj_id, node_id="2.1")
    assert blocked.target.status is objective.NodeStatus.BLOCKED and blocked.target.eligible

    # Save a long refinement.
    refine_start = len(ws.requests)
    document = codec.document_for_target(read.target, markdown=LONG_MARKDOWN, provenance=provenance)
    saved = service.save_node_refinement(
        store, issues, request=RefinementSaveRequest(document=document, expected=read.expected)
    )
    node_issue = _node_issue(ws, obj_id, "1.2")
    assert saved.document.markdown == LONG_MARKDOWN and len(LONG_MARKDOWN) > 1500
    assert saved.document.provenance == provenance
    assert saved.comment.id == ws.comments_of(node_issue)[0]["id"]

    # Read back, then replace (same comment id), then retry the replacement (no mutation).
    back = service.read_node_refinement(store, issues, objective_id=obj_id, node_id="1.2")
    assert back.saved == saved and back.source_changed is False
    replacement = codec.document_for_target(
        back.target, markdown="## Replaced\n\nShorter.\n", provenance=provenance
    )
    request = RefinementSaveRequest(document=replacement, expected=back.expected)
    replaced = service.save_node_refinement(store, issues, request=request)
    assert replaced.comment.id == saved.comment.id
    assert replaced.document.provenance == provenance  # preserved, never regenerated
    assert "step 1:" not in replaced.comment.body
    retry_start = len(ws.requests)
    assert service.save_node_refinement(store, issues, request=request) == replaced
    assert _mutations(ws, retry_start) == []
    # Refinement's mutation log: comment-only, on the node-issue, one create + one update.
    refinement_mutations = _mutation_names(ws, refine_start)
    assert refinement_mutations == ["commentCreate", "commentUpdate"]
    assert len(ws.comments_of(node_issue)) == 1

    # Unchanged concise roadmap/manifest and every non-comment surface; no delivery operations.
    assert store.get_objective(objective_id=obj_id) == roadmap_before
    assert ws.attachments[manifest_key] == manifest_before
    assert _non_comment_state(ws) == state_before
    assert len(ws.comments_of(sentinel)) == sentinel_comments_before  # no journal writes
    assert all(name in ("commentCreate", "commentUpdate") for name in refinement_mutations)

    # Then claim + save the real plan into the refined node.
    plan_start = len(ws.requests)
    store.update_objective_node(
        objective_id=obj_id, node_id="1.2", status=objective.NodeStatus.PLANNING
    )
    store.save_node_plan(
        objective_id=obj_id,
        node_id="1.2",
        header_fields=_plan_header_fields("01PLANRUN", obj_id),
        plan_markdown="# Node 1.2 plan\n",
    )
    plan_mutations = _mutation_names(ws, plan_start)
    assert "attachmentCreate" in plan_mutations  # the plan's own expected metadata writes
    # Historical refinement reads remain available; new saves refuse; nothing else mutates.
    historical = service.read_node_refinement(store, issues, objective_id=obj_id, node_id="1.2")
    assert historical.saved is not None
    assert historical.saved.document == replaced.document
    assert historical.saved.comment.id == replaced.comment.id
    assert historical.target.eligible is False and historical.target.has_plan_metadata is True
    refuse_start = len(ws.requests)
    _err(
        lambda: service.save_node_refinement(
            store,
            issues,
            request=RefinementSaveRequest(
                document=codec.document_for_target(
                    historical.target, markdown="## Too late\n", provenance=provenance
                ),
                expected=historical.expected,
            ),
        ),
        RefinementErrorCode.NODE_INELIGIBLE,
        write_attempted=False,
    )
    assert _mutations(ws, refuse_start) == []
    assert issues.get_plan_body(issue_id=str(node_issue["identifier"])) == "# Node 1.2 plan"
    after = store.get_objective(objective_id=obj_id)
    assert after is not None
    statuses = {n.id: n.status for n in after.nodes}
    assert (
        statuses["1.2"] is objective.NodeStatus.PLANNING
        and statuses["2.1"] is objective.NodeStatus.BLOCKED
    )
    header = after.header
    assert (header.get("delivery") == "stacked") is (delivery is objective.DeliveryPolicy.STACKED)
