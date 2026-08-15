"""The Linear partial-transfer interruption lane (contracts.md §8.53 over §8.43's carrier).

Composes ``transfer.run_transfer`` / ``recover.recover_operations`` over the REAL
``LinearProjectObjectiveStore`` + ``LinearIssueBackend`` + ``TrainPersistence`` driven by the
stateful ``FakeLinearWorkspace``, with fail-once injection at **GraphQL-mutation granularity**
(the store-internal write granularity). A raise from the client IS the faithful death
simulation here: ``run_transfer`` performs no exception-path cleanup — every window's raise
leaves exactly the durable workspace + journal state a killed process would.

The four interruption windows: pre-sentinel (die after Project creation, before the sentinel
identity attachment), partial plan-ownership rewrite, interrupted fresh-node attachment (the
found-arm's fingerprint recovery), and the interrupted journal append on the Project metadata
sentinel (the read-back / one-bounded-retry discipline). Throughout: no duplicated objectives,
plans, comments, or journal events. The unified Linear node↔plan model applies: a carried
"plan" IS its node-issue (the plan-header attachment rides it), and carry_map maps successor
node ids onto predecessor node-issue identifiers.
"""

import contextlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import FakeLinearWorkspace

from perk import objective
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import LinearIssueBackend, LinearProjectObjectiveStore
from perk.backends.linear.client import LinearGraphQLError
from perk.backends.objective_store import ObjectiveStoreError
from perk.delivery import continuation, recover, transfer
from perk.delivery.journal import EventRole
from perk.delivery.persistence import TrainPersistence
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    NoDeliveryTrain,
    TrainLayer,
    TrainReconstructionError,
)

ROOT = Path("/repo")
WT_ROOT = Path("/wt")
LINEAGE = "01JB0000000000000000000000"
OLD_RUN = "01JROLD0000000000000000000"
NEW_RUN = "01JRNEW0000000000000000000"
NOW = "2026-03-03T00:00:00Z"

# The predecessor's node-issues (create order: sentinel ENG-1, then nodes by sort key).
NODE_A = "ENG-2"  # node 1.1 — carried onto successor node 9.1
NODE_B = "ENG-3"  # node 1.2 — carried onto successor node 9.3
SENTINEL = "ENG-1"


def _nth(predicate: Callable[[str, dict[str, object]], bool], n: int):
    """Trigger on the n-th query matching ``predicate`` (1-based)."""
    seen = {"count": 0}

    def check(query: str, variables: dict[str, object]) -> bool:
        if predicate(query, variables):
            seen["count"] += 1
            return seen["count"] == n
        return False

    return check


def _attachment_url_contains(needle: str) -> Callable[[str, dict[str, object]], bool]:
    def check(query: str, variables: dict[str, object]) -> bool:
        if "attachmentCreate(" not in query:
            return False
        payload = variables.get("input")
        if not isinstance(payload, dict):
            return False
        url = cast("dict[str, object]", payload).get("url")
        return needle in str(url or "")

    return check


class _InjectingWorkspace(FakeLinearWorkspace):
    """``FakeLinearWorkspace`` with one-shot GraphQL-mutation-granularity failure injection.

    ``arm(predicate, mode)``: on the first matching request, ``"before"`` raises WITHOUT
    executing the mutation (the write never landed — the process died mid-flight) while
    ``"after"`` executes the mutation THEN raises (the ambiguous landed-POST arm). One shot:
    the trigger disarms itself, so reruns proceed against the surviving durable state.
    """

    def __init__(self) -> None:
        super().__init__()
        self._trigger: tuple[Callable[[str, dict[str, object]], bool], str] | None = None

    def arm(
        self, predicate: Callable[[str, dict[str, object]], bool], *, mode: str = "before"
    ) -> None:
        assert mode in ("before", "after")
        self._trigger = (predicate, mode)

    def request(self, query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        trigger = self._trigger
        if trigger is not None and trigger[0](query, variables or {}):
            self._trigger = None
            if trigger[1] == "after":
                super().request(query, variables)
                raise LinearGraphQLError("injected transport failure (the write landed)", codes=())
            raise LinearGraphQLError(
                "injected transport failure (the write never landed)", codes=()
            )
        return super().request(query, variables)


class _Writers:
    def active_plan_ids(self, plan_ids) -> frozenset[str]:
        return frozenset()


class _Lane:
    """One composed world: the workspace, the REAL store/backend/persistence over it, a
    live-read train reconstruction (derived from CURRENT store state, so post-crash reruns
    genuinely converge), and the run/recover drivers."""

    def __init__(self) -> None:
        self.ws = _InjectingWorkspace()
        self.store = LinearProjectObjectiveStore(self.ws, team_key="ENG", repo_root=ROOT)
        self.issues = LinearIssueBackend(self.ws, team_key="ENG", repo_root=ROOT)
        self.persistence = TrainPersistence(self.store, self.issues)
        self.pred_id = ""

    # ------------------------------------------------------------- seeding

    def seed(self) -> None:
        nodes = [
            objective.ObjectiveNode(
                id="1.1", description="one", status=objective.NodeStatus.PENDING
            ),
            objective.ObjectiveNode(
                id="1.2", description="two", status=objective.NodeStatus.PENDING
            ),
        ]
        ref = self.store.create_objective(
            title="Old",
            body="# Old\n\nprose",
            run_id=OLD_RUN,
            roadmap_nodes=nodes,
            delivery=objective.DeliveryPolicy.STACKED,
            delivery_lineage=LINEAGE,
        )
        self.pred_id = ref.id
        # The unified node↔plan model: a plan was saved into each node-issue — the
        # plan-header attachment IS the plan identity the transfer's ownership writes target.
        # Seeded via `save_node_plan` (the node-plan unification writer, the sanctioned Linear
        # plan-header creation seam — `update_plan_header` is merge-only and refuses to create).
        for node_id, plan_run in (
            ("1.1", "01JPLANA000000000000000000"),
            ("1.2", "01JPLANB000000000000000000"),
        ):
            self.store.save_node_plan(
                objective_id=self.pred_id,
                node_id=node_id,
                header_fields={
                    "run_id": plan_run,
                    "objective_id": self.pred_id,
                    "objective_node_id": node_id,
                    "delivery_lineage": LINEAGE,
                },
                plan_markdown=f"# Node {node_id} plan\n",
            )

    # ------------------------------------------------------------- live-read reconstruction

    def _reconstruct(self, root: Path, objective_id: str):
        state = self.store.get_objective(objective_id=objective_id)
        if state is None:
            raise TrainReconstructionError(
                f"objective {objective_id} not found", error_type="objective_not_found"
            )
        if state.header.get("delivery") != "stacked":
            return NoDeliveryTrain(
                objective_id=objective_id,
                objective_url=state.url,
                redirected_from=None,
                reason="objective is incremental",
            )
        layers = []
        for node in objective.delivery_order(list(state.nodes)):
            plan_id = node.pr.removeprefix("#") if node.pr else None
            layers.append(
                TrainLayer(
                    node_id=node.id,
                    plan_id=plan_id,
                    branch=f"plan-{plan_id}" if plan_id else None,
                    pr_number=None,
                    intent=LayerIntent.PLANNED,
                    publication=LayerPublication.UNPUBLISHED,
                    git=LayerGit.UNKNOWN,
                    pr=LayerPr.ABSENT,
                    membership=LayerMembership.NOT_APPLICABLE,
                    writer=LayerWriter.FREE,
                    finalization=LayerFinalization.NOT_MERGED,
                    parent_checkpoint_sha=None,
                    published_head_sha=None,
                    observed_remote_head_sha=None,
                    observed_pr_base=None,
                    expected_pr_base=None,
                )
            )
        lineage = state.header.get("delivery_lineage")
        return DeliveryTrain(
            objective_id=objective_id,
            objective_url=state.url,
            delivery_lineage=lineage if isinstance(lineage, str) else None,
            base="main",
            redirected_from=None,
            layers=tuple(layers),
            published_prefix_len=0,
            unresolved_operation=None,
            findings=(),
            build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="veto"),
            observed_base_head_sha="m" * 40,
        )

    # ------------------------------------------------------------- driving

    @contextlib.contextmanager
    def _lock(self, root: Path) -> Iterator[None]:
        yield

    def _successor_nodes(self) -> list[objective.ObjectiveNode]:
        pending = objective.NodeStatus.PENDING
        return [
            objective.ObjectiveNode(id="9.1", description="one", status=pending),
            objective.ObjectiveNode(id="9.2", description="fresh", status=pending),
            objective.ObjectiveNode(id="9.3", description="two", status=pending),
        ]

    def run(self, *, run_id: str = NEW_RUN) -> transfer.TransferResult:
        state = self.store.get_objective(objective_id=self.pred_id)
        assert state is not None
        policy = objective.delivery_policy(state.header)
        return transfer.run_transfer(
            ROOT,
            predecessor=state,
            predecessor_policy=policy,
            predecessor_id=self.pred_id,
            run_id=run_id,
            title="Successor",
            prose="successor prose",
            base=None,
            roadmap_nodes=self._successor_nodes(),
            carry_map={"9.1": NODE_A, "9.3": NODE_B},
            stacked=True,
            remote_writers=_Writers(),
            store_factory=lambda root: self.store,
            issues_factory=lambda root: self.issues,
            persistence_factory=lambda root: self.persistence,
            reconstruct=self._reconstruct,
            pr_facts=lambda **kwargs: None,
            worktree_branches=lambda root: (),
            trunk=lambda root: "main",
            lock=self._lock,
            now=lambda: NOW,
        )

    def recover(self) -> recover.RecoverResult:
        return recover.recover_operations(
            ROOT,
            objective_id=self.pred_id,
            worktree_root=WT_ROOT,
            persistence_factory=lambda root: self.persistence,
            transfer_seams_factory=lambda root: transfer.TransferSeams(
                repo_root=root,
                store=self.store,
                issues=self.issues,
                persistence=self.persistence,
                reconstruct=self._reconstruct,
                now=lambda: NOW,
            ),
            issues_factory=lambda root: self.issues,
            store_factory=lambda root: self.store,
            list_refs=lambda root, prefix: [],
            worktree_prune=lambda root: None,
            iter_manifests=lambda root: continuation.ManifestScan(manifests=(), unparseable=()),
            worktree_dirs=lambda root: [],
            worktree_admin_dirs=lambda root: [],
            lock=self._lock,
            now=lambda: NOW,
        )

    # ------------------------------------------------------------- assertion helpers

    def journal_comments(self) -> list[str]:
        sentinel = self.ws.issue_by_identifier(SENTINEL)
        return [
            str(c["body"])
            for c in self.ws.comments_of(sentinel)
            if "perk:stack-operation-event" in str(c["body"])
        ]

    def plan_header(self, identifier: str) -> dict[str, object]:
        state = self.issues.get_plan(issue_id=identifier)
        assert state is not None
        return state.header

    def assert_converged(self, successor_id: str, *, projects: int = 2) -> None:
        """The shared no-duplicate invariant: one perk-identified successor, both carried
        plans owned exactly once, exactly one resolved TRANSFER in the fold (prepared +
        completed), the predecessor stamped + completed."""
        assert len(self.ws.projects) == projects
        found = self.store.find_objective(run_id=NEW_RUN)
        assert found is not None and found.id == successor_id
        for identifier, node_id in ((NODE_A, "9.1"), (NODE_B, "9.3")):
            header = self.plan_header(identifier)
            assert header["objective_id"] == successor_id
            assert header["objective_node_id"] == node_id
            assert header["delivery_lineage"] == LINEAGE
            issue = self.ws.issue_by_identifier(identifier)
            assert issue["project_id"] == successor_id  # moved exactly into the successor
            # Cardinality: ONE plan-header attachment (the same-URL upsert replaced in place).
            plan_atts = [
                url
                for (_iid, url), _v in self.ws.attachments.items()
                if _iid == issue["id"] and "/plan/" in url
            ]
            assert len(plan_atts) == 1
        fold = self.persistence.read_journal(self.pred_id)
        assert fold.unresolved == ()
        completed = [
            op
            for op in fold.operations.values()
            if op.outcome is not None and op.outcome.role is EventRole.COMPLETED
        ]
        assert len(completed) == 1
        pred = self.store.get_objective(objective_id=self.pred_id)
        assert pred is not None
        assert pred.header.get("superseded_by") == successor_id
        assert pred.state == "closed"
        assert self.ws.project_state(self.pred_id) == "completed"

    def successor_issue_titles(self, successor_id: str) -> list[str]:
        return sorted(
            str(issue["title"])
            for issue in self.ws.issues.values()
            if issue.get("project_id") == successor_id
        )


def _lane() -> _Lane:
    lane = _Lane()
    lane.seed()
    return lane


# ----------------------------------------------------------------- the baseline


def test_uninterrupted_transfer_converges_over_the_real_linear_stack() -> None:
    # The no-injection baseline the windows diff against: one invocation runs
    # prepare → create → stamp → verify → finalize → complete over the real store.
    lane = _lane()
    result = lane.run()
    assert result.journaled is True and result.rolled_forward is False
    lane.assert_converged(result.successor.id)
    assert len(lane.journal_comments()) == 2  # prepared + completed, nothing else


# ----------------------------------------------------------------- window 1: pre-sentinel


def test_pre_sentinel_death_leaves_an_inert_project_and_the_rerun_stays_safe() -> None:
    # Die after Project creation, BEFORE the sentinel identity attachment (the sentinel
    # issueCreate is the first issueCreate of the run). The successor is undiscoverable by
    # run_id, so the rerun proves all-before (creation is the first post-prepare effect),
    # abandons with proof, and completes fresh — the inert non-perk Project is tolerated,
    # never adopted.
    lane = _lane()
    lane.ws.arm(lambda query, variables: "issueCreate(" in query)
    with pytest.raises(ObjectiveStoreError, match="injected transport failure"):
        lane.run()
    # Post-crash durable state: the prepared record is journaled; the orphan project exists
    # but carries no sentinel — no predecessor-touching write happened.
    assert len(lane.journal_comments()) == 1
    assert len(lane.ws.projects) == 2  # predecessor + the inert orphan
    assert lane.store.find_objective(run_id=NEW_RUN) is None
    pred = lane.store.get_objective(objective_id=lane.pred_id)
    assert pred is not None and pred.state == "open"
    assert pred.header.get("superseded_by") is None

    result = lane.run()  # the rerun (same run id)
    assert result.abandoned_operation_id is not None
    assert result.operation_id is not None
    assert result.abandoned_operation_id != result.operation_id
    # Exactly ONE perk-identified successor; the orphan is tolerated, never adopted.
    lane.assert_converged(result.successor.id, projects=3)
    orphan_ids = set(lane.ws.projects) - {lane.pred_id, result.successor.id}
    (orphan_id,) = orphan_ids
    orphan_issues = [
        issue for issue in lane.ws.issues.values() if issue.get("project_id") == orphan_id
    ]
    assert orphan_issues == []  # inert: no sentinel, no node-issues, never mutated again
    # The journal: abandoned(op1) + prepared/completed(op2) — four events, in order.
    bodies = lane.journal_comments()
    assert len(bodies) == 4
    assert "prepared" in bodies[0] and result.abandoned_operation_id in bodies[0]
    assert "abandoned" in bodies[1] and result.abandoned_operation_id in bodies[1]
    assert "prepared" in bodies[2] and result.operation_id in bodies[2]
    assert "completed" in bodies[3] and result.operation_id in bodies[3]


# ----------------------------------------------------------------- window 2: partial ownership


def test_partial_ownership_death_rolls_forward_via_recover_without_duplicates() -> None:
    # Die mid plan-ownership rewrite: the first plan is fully stamped (ownership +
    # identity), the second untouched. `recover` classifies all_after (successor exists +
    # corroborates) and rolls forward through the recorded manifest — every carried plan
    # ends owned exactly once, no duplicate journal events or comments.
    lane = _lane()
    # Plan-header attachmentCreates during the run: NODE_A ownership (1), then NODE_B
    # ownership (2) — the identity stamps are skip-if-match (the seeded lineage already
    # reads back). Die BEFORE the second ownership write lands.
    lane.ws.arm(_nth(_attachment_url_contains("/plan/"), 2))
    # The ownership write dies on the ISSUE-backend seam (no store translation) — the raw
    # IssueBackendError propagates, leaving the prepared operation unresolved.
    with pytest.raises(IssueBackendError, match="injected transport failure"):
        lane.run()
    # Post-crash: NODE_A carries successor ownership; NODE_B still the predecessor's.
    found = lane.store.find_objective(run_id=NEW_RUN)
    assert found is not None
    assert lane.plan_header(NODE_A)["objective_id"] == found.id
    assert lane.plan_header(NODE_B)["objective_id"] == lane.pred_id
    assert len(lane.journal_comments()) == 1  # prepared only; the op reads unresolved

    result = lane.recover()
    (row,) = result.operations
    assert row.kind == "transfer"
    assert row.classification == "all_after" and row.action == "rolled_forward"
    lane.assert_converged(found.id)
    assert len(lane.journal_comments()) == 2  # prepared + completed, never duplicated


# ----------------------------------------------------------------- window 3: node attachment


def test_interrupted_fresh_node_attachment_is_resumed_by_the_found_arm() -> None:
    # Die between the fresh node-issue's create and its objective-node attachment (the
    # non-atomic pair). The rerun's found-arm recovers the interrupted issue by its
    # create-time fingerprint and resumes the attachment write — no duplicate issue.
    lane = _lane()
    # Objective-node attachmentCreates during the run: 9.1's carried re-stamp (1), 9.2's
    # fresh attach (2) — die BEFORE the fresh node's attachment lands.
    lane.ws.arm(_nth(_attachment_url_contains("/node/"), 2))
    with pytest.raises(ObjectiveStoreError, match="injected transport failure"):
        lane.run()
    found = lane.store.find_objective(run_id=NEW_RUN)
    assert found is not None
    fresh_title = objective.node_issue_title(
        objective.ObjectiveNode(id="9.2", description="fresh", status=objective.NodeStatus.PENDING)
    )
    # The interrupted issue exists (create landed) but is attachment-less — invisible to
    # the roadmap read; 9.3's move never ran (the death killed the whole pass).
    state = lane.store.get_objective(objective_id=found.id)
    assert state is not None and [n.id for n in state.nodes] == ["9.1"]
    assert lane.successor_issue_titles(found.id).count(fresh_title) == 1

    result = lane.run()  # the same-run rerun resumes through the found-arm
    assert result.rolled_forward is True and result.journaled is True
    lane.assert_converged(result.successor.id)
    # Exactly ONE issue for node 9.2 — resumed, never re-minted.
    assert lane.successor_issue_titles(found.id).count(fresh_title) == 1
    state = lane.store.get_objective(objective_id=found.id)
    assert state is not None and [n.id for n in state.nodes] == ["9.1", "9.2", "9.3"]


# ----------------------------------------------------------------- window 4: journal append


def test_journal_append_post_failure_earns_the_one_bounded_retry() -> None:
    # The prepared append's POST raises WITHOUT landing: the rescan proves absence, the one
    # bounded retry re-POSTs, the read-back verifies — end-to-end through the Project
    # metadata sentinel and the real transcoder, within a single invocation.
    lane = _lane()
    lane.ws.arm(lambda query, variables: "commentCreate(" in query)
    result = lane.run()
    lane.assert_converged(result.successor.id)
    assert len(lane.journal_comments()) == 2  # exactly one prepared + one completed


def test_journal_append_landed_but_raised_is_proven_present_never_duplicated() -> None:
    # The ambiguous arm: the POST landed but the reply was lost. The rescan proves the
    # event present (byte-identical canonical payload), so no second POST happens — the
    # sentinel carries exactly one prepared event.
    lane = _lane()
    lane.ws.arm(lambda query, variables: "commentCreate(" in query, mode="after")
    result = lane.run()
    lane.assert_converged(result.successor.id)
    assert len(lane.journal_comments()) == 2  # never a duplicated prepared event
