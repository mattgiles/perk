"""Hermetic fake-driven tests for the replan transfer protocol (contracts.md §8.53).

Mirrors ``test_delivery_publish.py``'s stateful in-memory world: ONE ``_World`` owns the
objectives, the plan headers, the journal, the PR/worktree/writer observation, and a fake
train reconstruction that derives its answer from the CURRENT world state — so
post-execution verification genuinely reflects the ownership/identity writes the transfer
applied (and an interrupted rerun genuinely converges instead of asserting against a
scripted answer). Fail-once injection points sit AFTER each internal write (`boom`), so the
interruption matrix proves run_id-keyed convergence without duplicate effects. OFFLINE — no
git / gh / network.
"""

import contextlib
import copy
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import pytest

from perk import objective
from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import ObjectiveRef, ObjectiveState
from perk.delivery import oplock, transfer
from perk.delivery import sync as sync_mod
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalEvent,
    JournalFold,
    JournalRecordTooLarge,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
    canonical_payload,
    mint_operation_id,
)
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    NoDeliveryTrain,
    TrainFinding,
    TrainLayer,
    TrainReconstructionError,
    WorktreeFacts,
)
from perk.delivery.writers import WriterObservationError
from perk.github.stacks import PrDeliveryFacts

ROOT = Path("/repo")
PRED = "500"
LINEAGE = "01LINEAGE"
NOW = "2026-03-03T00:00:00Z"
RUN = "01RUNNEW"
SHA_A = "a" * 40
SHA_B = "b" * 40


class _Boom(Exception):
    """The injected infra failure (never a TransferError — it must propagate raw)."""


def _node(
    node_id: str, *, pr: str | None = None, depends_on: tuple[str, ...] | None = None
) -> objective.ObjectiveNode:
    return objective.ObjectiveNode(
        id=node_id,
        description=f"work {node_id}",
        status=objective.NodeStatus.PENDING,
        pr=pr,
        depends_on=depends_on,
    )


@dataclass
class _Objective:
    url: str
    title: str
    header: dict[str, object]
    nodes: list[objective.ObjectiveNode]
    closed: bool = False


@dataclass
class _World:
    """The injectable stateful world for one or more `run_transfer` invocations."""

    objectives: dict[str, _Objective] = field(default_factory=dict)
    plans: dict[str, dict[str, object]] = field(default_factory=dict)
    pr_state: dict[int, str] = field(default_factory=dict)
    dirty_branches: set[str] = field(default_factory=set)
    worktree_branch_names: list[str] = field(default_factory=list)
    active_writers: frozenset[str] = frozenset()
    writer_boom: bool = False
    oversize: bool = False
    lock_busy: bool = False
    locked: bool = False
    boom: set[str] = field(default_factory=set)
    timeline: list[tuple] = field(default_factory=list)
    prepared: list[PreparedRecord] = field(default_factory=list)
    outcomes: list[OutcomeRecord] = field(default_factory=list)
    supersede_calls: list[dict] = field(default_factory=list)
    next_objective_id: int = 600

    def _maybe_boom(self, step: str) -> None:
        if step in self.boom:
            self.boom.discard(step)
            raise _Boom(f"injected failure after {step}")

    # ------------------------------------------------------------- store (TransferStore)

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        obj = self.objectives.get(objective_id)
        if obj is None:
            return None
        return ObjectiveState(
            id=objective_id,
            url=obj.url,
            title=obj.title,
            header=dict(obj.header),
            nodes=tuple(obj.nodes),
        )

    def find_objective(self, *, run_id: str) -> ObjectiveRef | None:
        self.timeline.append(("find_objective", run_id, self.locked))
        for oid, obj in self.objectives.items():
            if obj.header.get("run_id") == run_id:
                return ObjectiveRef(id=oid, url=obj.url, existed=True)
        return None

    def supersede_objective(self, **kwargs) -> ObjectiveRef | None:
        self.timeline.append(("supersede", kwargs["run_id"]))
        self.supersede_calls.append(kwargs)
        for oid, obj in self.objectives.items():
            if obj.header.get("run_id") == kwargs["run_id"]:
                self._maybe_boom("supersede_found_return")
                return ObjectiveRef(id=oid, url=obj.url, existed=True)
        oid = str(self.next_objective_id)
        self.next_objective_id += 1
        header: dict[str, object] = {
            "run_id": kwargs["run_id"],
            "supersedes": kwargs["old_objective_id"],
            "status": "active",
        }
        if kwargs.get("base"):
            header["base"] = kwargs["base"]
        if kwargs.get("delivery") is not None:
            header["delivery"] = kwargs["delivery"].value
        if kwargs.get("delivery_lineage"):
            header["delivery_lineage"] = kwargs["delivery_lineage"]
        carry_map: dict[str, str] = dict(kwargs.get("carry_map") or {})
        nodes = [
            # The store materializes a carried node's plan backlink (Linear: the MOVE makes
            # the node-issue the plan; GitHub: `pr` is authored directly and carry_map empty).
            replace(n, pr=carry_map.get(n.id, n.pr))
            for n in kwargs["roadmap_nodes"]
        ]
        self.objectives[oid] = _Objective(
            url=f"u/{oid}", title=kwargs["title"], header=header, nodes=nodes
        )
        self._maybe_boom("supersede_return")  # created, then crashed before returning
        return ObjectiveRef(id=oid, url=f"u/{oid}", existed=False)

    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool:
        self.timeline.append(("finalize", old_objective_id, new_objective_id))
        old = self.objectives[old_objective_id]
        stamped = old.header.get("superseded_by")
        if stamped is not None and str(stamped) != new_objective_id:
            raise _Boom(f"conflicting superseded_by stamp: {stamped!r}")
        old.header["superseded_by"] = new_objective_id
        self._maybe_boom("finalize_close")  # stamped, then crashed before the close
        old.closed = True
        return True

    # ------------------------------------------------------------- issues (TransferIssues)

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        header = self.plans.get(issue_id)
        if header is None:
            return None
        return PlanState(
            id=issue_id, url="u/p", title="plan", header=dict(header), pr=None, state="OPEN"
        )

    # ------------------------------------------------------------- persistence

    def read_journal(self, objective_id: str) -> JournalFold:
        self.timeline.append(("fold", objective_id, self.locked))
        resolved = {o.operation_id for o in self.outcomes}
        ops: dict[str, OperationState] = {}
        for record in self.prepared:
            event = JournalEvent(
                record=record,
                role=EventRole.PREPARED,
                operation_id=record.operation_id,
                canonical_payload=canonical_payload(record),
                comment_id="c1",
                created_at=record.created,
            )
            outcome = next(
                (o for o in self.outcomes if o.operation_id == record.operation_id), None
            )
            outcome_event = (
                JournalEvent(
                    record=outcome,
                    role=outcome.role,
                    operation_id=outcome.operation_id,
                    canonical_payload=canonical_payload(outcome),
                    comment_id="c2",
                    created_at=outcome.created,
                )
                if outcome is not None
                else None
            )
            ops[record.operation_id] = OperationState(
                operation_id=record.operation_id,
                kind=record.operation_kind,
                prepared=event,
                accepted=None,
                outcome=outcome_event,
            )
        unresolved = tuple(op for op in ops.values() if op.operation_id not in resolved)
        return JournalFold(
            events=(), operations=ops, unresolved=unresolved, delivery_lineage=LINEAGE
        )

    def append_prepared(self, objective_id: str, record: PreparedRecord):
        if self.oversize:
            raise JournalRecordTooLarge("prepared payload exceeds 60000 chars")
        self.timeline.append(("prepared", record.operation_id))
        self.prepared.append(record)
        self._maybe_boom("prepare")  # journaled, then crashed before creation
        return None

    def append_outcome(self, objective_id: str, record: OutcomeRecord):
        if record.role is EventRole.COMPLETED:
            self._maybe_boom("completed")  # crashed BEFORE the completion write
        self.timeline.append(("outcome", record.role.value, record.operation_id))
        self.outcomes.append(record)
        return None

    def transfer_plan_ownership(
        self, plan_id: str, *, objective_id: str, objective_node_id: str
    ) -> None:
        self.timeline.append(("ownership", plan_id, objective_id, objective_node_id))
        header = self.plans[plan_id]
        header["objective_id"] = objective_id
        header["objective_node_id"] = objective_node_id
        self._maybe_boom("ownership")

    def stamp_layer_identity(
        self, plan_id: str, *, delivery_lineage: str, predecessor_plan_id: str | None
    ) -> None:
        self.timeline.append(("identity", plan_id, delivery_lineage, predecessor_plan_id))
        header = self.plans[plan_id]
        header["delivery_lineage"] = delivery_lineage
        header["predecessor_plan_id"] = predecessor_plan_id
        self._maybe_boom("identity")

    def clear_delivery_metadata(self, plan_id: str) -> None:
        self.timeline.append(("clear", plan_id))
        header = self.plans[plan_id]
        for key in (
            "delivery_lineage",
            "predecessor_plan_id",
            "parent_checkpoint_sha",
            "published_head_sha",
        ):
            header[key] = None
        self._maybe_boom("clear")

    # ------------------------------------------------------------- observation seams

    def reconstruct(self, root: Path, objective_id: str):
        self.timeline.append(("reconstruct", objective_id, self.locked))
        self._maybe_boom("reconstruct")
        obj = self.objectives.get(objective_id)
        if obj is None:
            raise TrainReconstructionError(
                f"objective {objective_id} not found", error_type="objective_not_found"
            )
        if obj.header.get("delivery") != "stacked":
            return NoDeliveryTrain(
                objective_id=objective_id,
                objective_url=obj.url,
                redirected_from=None,
                reason="objective is incremental",
            )
        lineage = obj.header.get("delivery_lineage")
        findings: list[TrainFinding] = []
        if not isinstance(lineage, str) or not lineage:
            findings.append(
                TrainFinding(
                    kind=FindingKind.BLOCKER,
                    code="missing_lineage",
                    message=f"objective {objective_id} has delivery: stacked but no lineage",
                )
            )
            lineage = None
        layers: list[TrainLayer] = []
        for node in objective.delivery_order(list(obj.nodes)):
            cited = node.pr.removeprefix("#") if node.pr else None
            header = self.plans.get(cited) if cited is not None else None
            plan_id = cited if header is not None else None
            branch_value = (header or {}).get("branch")
            branch = (
                branch_value
                if isinstance(branch_value, str) and branch_value
                else (f"plan-{plan_id}" if plan_id else None)
            )
            pr_ref = (header or {}).get("pr")
            pr_number = int(str(pr_ref).removeprefix("#")) if pr_ref else None
            pr_axis = LayerPr.ABSENT
            if pr_number is not None:
                pr_axis = {
                    "OPEN": LayerPr.READY,
                    "MERGED": LayerPr.MERGED,
                    "CLOSED": LayerPr.CLOSED,
                }.get(self.pr_state.get(pr_number, ""), LayerPr.ABSENT)
            if header is not None:
                owner = header.get("objective_id")
                if owner is not None and str(owner).removeprefix("#") != objective_id:
                    findings.append(
                        TrainFinding(
                            kind=FindingKind.BLOCKER,
                            code="wrong_owner",
                            message=f"plan #{plan_id} records objective {owner}, "
                            f"expected {objective_id}",
                            plan_id=plan_id,
                        )
                    )
                node_link = header.get("objective_node_id")
                if node_link is not None and node_link != node.id:
                    findings.append(
                        TrainFinding(
                            kind=FindingKind.BLOCKER,
                            code="node_link_mismatch",
                            message=f"plan #{plan_id} records node {node_link}, expected {node.id}",
                            plan_id=plan_id,
                        )
                    )
                plan_lineage = header.get("delivery_lineage")
                if plan_lineage is not None and plan_lineage != lineage:
                    findings.append(
                        TrainFinding(
                            kind=FindingKind.BLOCKER,
                            code="wrong_lineage",
                            message=f"plan #{plan_id} records lineage {plan_lineage}, "
                            f"expected {lineage}",
                            plan_id=plan_id,
                        )
                    )
            parent_sha = (header or {}).get("parent_checkpoint_sha")
            head_sha = (header or {}).get("published_head_sha")
            layers.append(
                TrainLayer(
                    node_id=node.id,
                    plan_id=plan_id,
                    branch=branch,
                    pr_number=pr_number,
                    intent=LayerIntent.PLANNED,
                    publication=LayerPublication.UNPUBLISHED,
                    git=LayerGit.UNKNOWN,
                    pr=pr_axis,
                    membership=LayerMembership.NOT_APPLICABLE,
                    writer=(
                        LayerWriter.DIRTY if branch in self.dirty_branches else LayerWriter.FREE
                    ),
                    finalization=LayerFinalization.NOT_MERGED,
                    parent_checkpoint_sha=(parent_sha if isinstance(parent_sha, str) else None),
                    published_head_sha=head_sha if isinstance(head_sha, str) else None,
                    observed_remote_head_sha=None,
                    observed_pr_base=None,
                    expected_pr_base=None,
                )
            )
        base = obj.header.get("base")
        return DeliveryTrain(
            objective_id=objective_id,
            objective_url=obj.url,
            delivery_lineage=lineage,
            base=base if isinstance(base, str) and base else "main",
            redirected_from=None,
            layers=tuple(layers),
            published_prefix_len=0,
            unresolved_operation=None,
            findings=tuple(findings),
            build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="veto"),
            observed_base_head_sha="m" * 40,
        )

    def pr_facts(self, *, number: int, repo_root: Path) -> PrDeliveryFacts | None:
        self.timeline.append(("pr_facts", number, self.locked))
        state = self.pr_state.get(number)
        if state is None:
            return None
        return PrDeliveryFacts(
            number=number,
            state=state,
            is_draft=False,
            base_ref="main",
            head_ref="h",
            head_sha="9" * 40,
        )

    def worktree_branches(self, root: Path) -> tuple[WorktreeFacts, ...]:
        self.timeline.append(("worktrees", self.locked))
        return tuple(
            WorktreeFacts(path=f"/wt/{b}", branch=b, dirty=b in self.dirty_branches)
            for b in self.worktree_branch_names
        )

    def active_plan_ids(self, plan_ids: Sequence[str]) -> frozenset[str]:
        self.timeline.append(("writer_probe", tuple(plan_ids), self.locked))
        if self.writer_boom:
            raise WriterObservationError("gh api failed")
        return frozenset(p for p in plan_ids if p in self.active_writers)

    @contextlib.contextmanager
    def _lock(self, root: Path) -> Iterator[None]:
        if self.lock_busy:
            raise oplock.OperationLockBusy("another stack operation holds the lock")
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    # ------------------------------------------------------------- driving

    def run(
        self,
        nodes: Sequence[objective.ObjectiveNode],
        *,
        predecessor: str = PRED,
        run_id: str = RUN,
        base: str | None = None,
        carry_map: dict[str, str] | None = None,
        stacked: bool = True,
        reconstruct=None,
    ) -> transfer.TransferResult:
        predecessor_state = self.get_objective(objective_id=predecessor)
        if predecessor_state is None:
            raise transfer.TransferError(
                f"objective {predecessor} not found", error_type="objective_not_found"
            )
        try:
            predecessor_policy = objective.delivery_policy(predecessor_state.header)
        except ValueError as exc:
            raise transfer.TransferError(str(exc), error_type="invalid_delivery_policy") from exc
        return transfer.run_transfer(
            ROOT,
            predecessor=predecessor_state,
            predecessor_policy=predecessor_policy,
            predecessor_id=predecessor,
            run_id=run_id,
            title="Successor",
            prose="successor prose",
            base=base,
            roadmap_nodes=list(nodes),
            carry_map=carry_map or {},
            stacked=stacked,
            remote_writers=self,
            store_factory=lambda root: self,
            issues_factory=lambda root: self,
            persistence_factory=lambda root: self,
            reconstruct=reconstruct if reconstruct is not None else self.reconstruct,
            pr_facts=self.pr_facts,
            worktree_branches=self.worktree_branches,
            trunk=lambda root: "main",
            lock=self._lock,
            now=lambda: NOW,
        )

    def events(self, kind: str) -> list[tuple]:
        return [t for t in self.timeline if t[0] == kind]

    def assert_no_writes(self) -> None:
        assert self.supersede_calls == []
        assert self.prepared == [] and self.outcomes == []
        for kind in ("ownership", "identity", "clear", "finalize"):
            assert self.events(kind) == [], kind


def _error(world: _World, nodes, **kwargs) -> transfer.TransferError:
    with pytest.raises(transfer.TransferError) as excinfo:
        world.run(nodes, **kwargs)
    return excinfo.value


# ----------------------------------------------------------------- world builders


def _plan(
    plan_id: str,
    *,
    node_id: str,
    objective_id: str = PRED,
    lineage: str | None = LINEAGE,
    predecessor: str | None = None,
    pr: str | None = None,
    published: bool = False,
) -> dict[str, object]:
    header: dict[str, object] = {
        "branch": f"plan-{plan_id}",
        "objective_id": objective_id,
        "objective_node_id": node_id,
    }
    if lineage is not None:
        header["delivery_lineage"] = lineage
    if predecessor is not None:
        header["predecessor_plan_id"] = predecessor
    if pr is not None:
        header["pr"] = pr
    if published:
        header["parent_checkpoint_sha"] = SHA_A
        header["published_head_sha"] = SHA_B
    return header


def _stacked_world(*, published: bool) -> _World:
    """The stacked predecessor: node 1.1 → plan 101 (published when asked: PR 201 + the
    checkpoint pair), node 1.2 → plan 102 (unpublished), node 1.3 fresh. Non-identity
    carrier ids throughout (node 1.x / plan 10x / PR 20x)."""
    world = _World()
    world.objectives[PRED] = _Objective(
        url=f"u/{PRED}",
        title="Old",
        header={"run_id": "01OLD", "delivery": "stacked", "delivery_lineage": LINEAGE},
        nodes=[_node("1.1", pr="#101"), _node("1.2", pr="#102"), _node("1.3")],
    )
    world.plans["101"] = _plan(
        "101", node_id="1.1", pr="#201" if published else None, published=published
    )
    world.plans["102"] = _plan("102", node_id="1.2", predecessor="101")
    if published:
        world.pr_state[201] = "OPEN"
    return world


def _incremental_world() -> _World:
    """The incremental predecessor: nodes 1.1/1.2 with plan backlinks, no lineage anywhere."""
    world = _World()
    world.objectives[PRED] = _Objective(
        url=f"u/{PRED}",
        title="Old",
        header={"run_id": "01OLD"},
        nodes=[_node("1.1", pr="#101"), _node("1.2", pr="#102")],
    )
    world.plans["101"] = _plan("101", node_id="1.1", lineage=None)
    world.plans["102"] = _plan("102", node_id="1.2", lineage=None)
    world.worktree_branch_names = ["plan-101", "plan-102"]
    return world


def _successor_nodes() -> list[objective.ObjectiveNode]:
    """The default reshape: claimed plan 101 stays first; a NEW fresh node lands between the
    carried plans (so 102's predecessor becomes an explicit null); every node id changes."""
    return [_node("9.1", pr="#101"), _node("9.2"), _node("9.3", pr="#102")]


# ----------------------------------------------------------------- happy paths


def test_transfer_imports_writer_error_directly_not_through_sync() -> None:
    assert not hasattr(sync_mod, "WriterObservationError")
    assert transfer.WriterObservationError is WriterObservationError


def test_stacked_to_stacked_post_publication_transfers_and_verifies():
    world = _stacked_world(published=True)
    result = world.run(_successor_nodes())

    assert result.journaled is True and result.rolled_forward is False
    assert result.operation_id is not None and result.abandoned_operation_id is None
    successor = result.successor.id

    # The successor stored the stacked policy + the carried lineage; deferred close.
    (call,) = world.supersede_calls
    assert call["close_predecessor"] is False
    assert call["delivery"] is objective.DeliveryPolicy.STACKED
    assert call["delivery_lineage"] == LINEAGE

    # Ownership moved to the successor with the NEW node ids; the claimed plan kept its
    # identity fields; the carried-unpublished plan re-chained onto the explicit null
    # (the fresh node below it is unplanned).
    assert world.plans["101"]["objective_id"] == successor
    assert world.plans["101"]["objective_node_id"] == "9.1"
    assert world.plans["101"]["delivery_lineage"] == LINEAGE
    assert world.plans["101"]["parent_checkpoint_sha"] == SHA_A  # untouched
    assert world.plans["102"]["objective_id"] == successor
    assert world.plans["102"]["objective_node_id"] == "9.3"
    assert world.events("identity") == [("identity", "102", LINEAGE, None)]

    # Predecessor closed LAST, after verification; completion journaled on the predecessor.
    assert world.objectives[PRED].header["superseded_by"] == successor
    assert world.objectives[PRED].closed is True
    (outcome,) = world.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert outcome.observed == {"successor_objective_id": successor, "run_id": RUN}

    # Ordering: prepare → create → stamp → verify (successor reconstruction) → finalize →
    # complete, with the fold/probes under the lock.
    kinds = [t[0] for t in world.timeline]
    assert kinds.index("prepared") < kinds.index("supersede")
    assert kinds.index("supersede") < kinds.index("ownership")
    successor_reconstructs = [
        i for i, t in enumerate(world.timeline) if t[0] == "reconstruct" and t[1] == successor
    ]
    assert successor_reconstructs, "verification must reconstruct the successor"
    assert (
        max(i for i, k in enumerate(kinds) if k in ("ownership", "identity"))
        < (successor_reconstructs[0])
    )
    assert successor_reconstructs[0] < kinds.index("finalize")
    assert kinds.index("finalize") < kinds.index("outcome")
    assert all(t[-1] is True for t in world.events("fold")), "fold runs under the lock"
    assert all(t[-1] is True for t in world.events("writer_probe"))

    # The recorded manifest is the complete successor materialization intent (D7).
    (record,) = world.prepared
    assert record.operation_kind is OperationKind.TRANSFER
    assert record.objective_id == PRED and record.run_id == RUN
    assert record.before["delivery_lineage"] == LINEAGE
    claimed = record.before["claimed_prefix"]
    assert claimed == [
        {
            "node_id": "1.1",
            "plan_id": "101",
            "branch": "plan-101",
            "parent_checkpoint_sha": SHA_A,
            "published_head_sha": SHA_B,
            "pr_number": 201,
        }
    ]
    assert record.before["carried_unpublished"] == [{"node_id": "1.2", "plan_id": "102"}]
    assert record.after["title"] == "Successor" and record.after["delivery"] == "stacked"
    # The record round-trips through the strict manifest decode (the recover entry point).
    manifest = transfer.decode_transfer_record(record)
    assert [n.id for n in manifest.after.roadmap_nodes] == ["9.1", "9.2", "9.3"]
    assert transfer.manifest_projection(manifest.after) == (
        ("9.1", "101"),
        ("9.2", None),
        ("9.3", "102"),
    )


def test_manifest_decode_rejects_internally_inconsistent_records_before_recovery():
    world = _stacked_world(published=True)
    world.run(_successor_nodes())
    record = world.prepared[0]

    before_plan = copy.deepcopy(dict(record.before))
    before_carried = cast("list[dict[str, object]]", before_plan["carried_unpublished"])
    before_carried[0]["plan_id"] = "999"
    after_lineage = copy.deepcopy(dict(record.after))
    after_lineage["delivery_lineage"] = "01FOREIGNLINEAGE0000000000"
    after_prefix = copy.deepcopy(dict(record.after))
    after_nodes = cast("list[dict[str, object]]", after_prefix["roadmap_nodes"])
    after_nodes[0]["pr"] = "#102"
    after_carry = copy.deepcopy(dict(record.after))
    after_carry["carry_map"] = {"9.2": "999"}

    corruptions = (
        replace(record, objective_id="999"),
        replace(record, affected_plans=("101",)),
        replace(record, before=before_plan),
        replace(record, after=after_lineage),
        replace(record, after=after_prefix),
        replace(record, after=after_carry),
    )
    for corrupted in corruptions:
        with pytest.raises(JournalCorruptionError):
            transfer.decode_transfer_record(corrupted)


def test_stacked_to_stacked_pre_publication_reorders_the_unpublished_suffix():
    world = _stacked_world(published=False)
    # Nothing is claimed, so even the bottom plan may move: 102 first, then 101.
    result = world.run([_node("9.1", pr="#102"), _node("9.2", pr="#101")])
    successor = result.successor.id
    assert world.plans["102"]["objective_id"] == successor
    assert world.plans["102"]["objective_node_id"] == "9.1"
    assert world.plans["101"]["objective_node_id"] == "9.2"
    # The re-chain follows the NEW delivery order: 102 bottoms out; 101 sits on 102.
    assert ("identity", "102", LINEAGE, None) in world.timeline
    assert ("identity", "101", LINEAGE, "102") in world.timeline
    assert world.objectives[PRED].closed is True


def test_stacked_to_incremental_clears_delivery_metadata_and_verifies_by_direct_reads():
    world = _stacked_world(published=False)
    result = world.run([_node("9.1", pr="#101"), _node("9.2", pr="#102")], stacked=False)
    successor = result.successor.id
    assert result.journaled is True  # the predecessor is stacked → journaled protocol
    (call,) = world.supersede_calls
    # §8.42 absence rule: an incremental successor stores NO delivery/delivery_lineage.
    assert call["delivery"] is None and call["delivery_lineage"] is None
    for plan_id in ("101", "102"):
        assert world.plans[plan_id]["objective_id"] == successor
        for key in (
            "delivery_lineage",
            "predecessor_plan_id",
            "parent_checkpoint_sha",
            "published_head_sha",
        ):
            assert world.plans[plan_id][key] is None
    assert world.events("clear") == [("clear", "101"), ("clear", "102")]
    # No train exists for the successor: verification never reconstructs it.
    assert [t for t in world.events("reconstruct") if t[1] == successor] == []
    assert world.objectives[PRED].closed is True
    (outcome,) = world.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_incremental_to_stacked_converts_without_a_journal():
    world = _incremental_world()
    result = world.run([_node("9.1", pr="#101"), _node("9.2", pr="#102"), _node("9.3")])
    successor = result.successor.id
    assert result.journaled is False and result.operation_id is None
    assert world.prepared == [] and world.outcomes == []  # the non-journaled arm (D1)
    (call,) = world.supersede_calls
    assert call["delivery"] is objective.DeliveryPolicy.STACKED
    minted = call["delivery_lineage"]
    assert isinstance(minted, str) and len(minted) == 26  # a freshly-minted ULID
    # The D13 direct-observation preflight ran: plan reads + PR facts absent + worktrees +
    # the writer probe over the affected plans.
    assert world.events("worktrees") != []
    assert world.events("writer_probe") == [("writer_probe", ("101", "102"), True)]
    # Full layer identity stamped under the minted lineage, chained in delivery order.
    assert ("identity", "101", minted, None) in world.timeline
    assert ("identity", "102", minted, "101") in world.timeline
    assert world.plans["101"]["objective_id"] == successor
    # Stacked verification reconstructed the successor train.
    assert [t for t in world.events("reconstruct") if t[1] == successor] != []
    assert world.objectives[PRED].closed is True


def test_incremental_to_stacked_reuses_a_stored_predecessor_lineage():
    world = _incremental_world()
    world.objectives[PRED].header["delivery_lineage"] = "01STOREDLINEAGE"
    world.run([_node("9.1", pr="#101"), _node("9.2", pr="#102")])
    (call,) = world.supersede_calls
    assert call["delivery_lineage"] == "01STOREDLINEAGE"  # §8.45 copy-or-mint


def test_carry_map_identity_wins_over_the_pr_backlink():
    # Linear: the carried plan IS the node-issue named by carry_map; `pr` may be unset.
    world = _stacked_world(published=False)
    result = world.run(
        [_node("9.1"), _node("9.2")],
        carry_map={"9.1": "101", "9.2": "102"},
    )
    successor = result.successor.id
    assert world.plans["101"]["objective_node_id"] == "9.1"
    assert world.plans["102"]["objective_node_id"] == "9.2"
    assert world.plans["101"]["objective_id"] == successor


# ----------------------------------------------------------------- refusals (D3-D6)


def _published_pair_world() -> _World:
    """Both plans published (claimed prefix = [101, 102])."""
    world = _stacked_world(published=True)
    world.plans["102"]["pr"] = "#202"
    world.plans["102"]["parent_checkpoint_sha"] = SHA_B
    world.plans["102"]["published_head_sha"] = "c" * 40
    world.pr_state[202] = "OPEN"
    return world


def test_prefix_mismatch_on_reorder():
    world = _published_pair_world()
    error = _error(world, [_node("9.1", pr="#102"), _node("9.2", pr="#101")])
    assert error.error_type == "prefix_mismatch"
    assert "['101', '102']" in str(error) and "['102', '101']" in str(error)
    world.assert_no_writes()


def test_prefix_mismatch_on_dropped_claimed_plan():
    world = _published_pair_world()
    error = _error(world, [_node("9.1", pr="#102")])
    assert error.error_type == "prefix_mismatch"
    world.assert_no_writes()


def test_prefix_mismatch_on_duplicate_carry():
    world = _stacked_world(published=False)
    error = _error(world, [_node("9.1", pr="#101"), _node("9.2", pr="#101")])
    assert error.error_type == "prefix_mismatch"
    assert "bijective" in str(error)
    world.assert_no_writes()


def test_prefix_mismatch_on_foreign_plan():
    world = _stacked_world(published=False)
    error = _error(world, [_node("9.1", pr="#999")])
    assert error.error_type == "prefix_mismatch"
    assert "999" in str(error) and "do not exist" in str(error)
    world.assert_no_writes()


def test_base_immutable_after_publication():
    world = _stacked_world(published=True)
    error = _error(world, _successor_nodes(), base="develop")
    assert error.error_type == "base_immutable"
    assert "'main'" in str(error) and "'develop'" in str(error)
    world.assert_no_writes()


def test_base_change_allowed_pre_publication():
    world = _stacked_world(published=False)
    world.run(_successor_nodes(), base="develop")
    (call,) = world.supersede_calls
    assert call["base"] == "develop"


def test_policy_immutable_after_publication():
    world = _stacked_world(published=True)
    error = _error(world, _successor_nodes(), stacked=False)
    assert error.error_type == "policy_immutable"
    world.assert_no_writes()


def test_missing_lineage_fails_closed():
    world = _stacked_world(published=False)
    world.objectives[PRED].header["delivery_lineage"] = ""
    error = _error(world, _successor_nodes())
    assert error.error_type == "missing_lineage"
    assert "''" in str(error)
    world.assert_no_writes()


def test_dropped_open_pr_refuses():
    # Plan 102 has an OPEN PR but no checkpoint pair — not claimed, still mandatory-carry.
    world = _stacked_world(published=False)
    world.plans["102"]["pr"] = "#202"
    world.pr_state[202] = "OPEN"
    error = _error(world, [_node("9.1", pr="#101")])
    assert error.error_type == "dropped_open_pr"
    assert "plan #102 (PR #202)" in str(error)
    world.assert_no_writes()


def test_stacked_to_incremental_conversion_refuses_carried_open_prs():
    world = _stacked_world(published=False)
    world.plans["101"]["pr"] = "#201"
    world.pr_state[201] = "OPEN"
    error = _error(world, [_node("9.1", pr="#101"), _node("9.2", pr="#102")], stacked=False)
    assert error.error_type == "pr_exists"
    assert "plan #101 (PR #201)" in str(error)
    world.assert_no_writes()


def test_incremental_to_stacked_conversion_refuses_carried_open_prs():
    world = _incremental_world()
    world.plans["101"]["pr"] = "#201"
    world.pr_state[201] = "OPEN"
    error = _error(world, [_node("9.1", pr="#101"), _node("9.2", pr="#102")])
    assert error.error_type == "pr_exists"
    world.assert_no_writes()


@pytest.mark.parametrize("malformed", [17, "", "#", "zero", "#0", "#-2"])
def test_incremental_to_stacked_malformed_pr_metadata_refuses_fail_closed(malformed):
    world = _incremental_world()
    world.plans["101"]["pr"] = malformed
    error = _error(world, [_node("9.1", pr="#101"), _node("9.2", pr="#102")])
    assert error.error_type == "pr_exists"
    assert repr(malformed) in str(error)
    world.assert_no_writes()


def test_incremental_to_stacked_dropped_open_pr_refuses():
    world = _incremental_world()
    world.plans["102"]["pr"] = "#202"
    world.pr_state[202] = "OPEN"
    error = _error(world, [_node("9.1", pr="#101")])
    assert error.error_type == "dropped_open_pr"
    world.assert_no_writes()


def test_merged_prs_do_not_gate():
    world = _stacked_world(published=False)
    world.plans["102"]["pr"] = "#202"
    world.pr_state[202] = "MERGED"
    world.run([_node("9.1", pr="#101")])  # dropping a MERGED-PR plan is fine
    assert world.objectives[PRED].closed is True


def test_dirty_worktree_refuses_on_the_stacked_path():
    world = _stacked_world(published=False)
    world.dirty_branches.add("plan-102")
    error = _error(world, _successor_nodes())
    assert error.error_type == "dirty_worktree"
    assert "plan-102" in str(error)
    world.assert_no_writes()


def test_dirty_worktree_refuses_on_the_incremental_path():
    world = _incremental_world()
    world.dirty_branches.add("plan-101")
    error = _error(world, [_node("9.1", pr="#101"), _node("9.2", pr="#102")])
    assert error.error_type == "dirty_worktree"
    assert "plan #101" in str(error)
    world.assert_no_writes()


def test_active_writer_refuses():
    world = _stacked_world(published=False)
    world.active_writers = frozenset({"102"})
    error = _error(world, _successor_nodes())
    assert error.error_type == "active_writer"
    assert "plan #102" in str(error)
    world.assert_no_writes()


def test_writer_observation_unavailable_fails_closed():
    world = _stacked_world(published=False)
    world.writer_boom = True
    error = _error(world, _successor_nodes())
    assert error.error_type == "writer_observation_unavailable"
    world.assert_no_writes()


def test_oversize_manifest_refuses_with_nothing_written():
    world = _stacked_world(published=False)
    world.oversize = True
    error = _error(world, _successor_nodes())
    assert error.error_type == "transfer_manifest_oversize"
    assert "shorten" in str(error)
    world.assert_no_writes()


def test_lock_contention_is_operation_in_progress():
    world = _stacked_world(published=False)
    world.lock_busy = True
    error = _error(world, _successor_nodes())
    assert error.error_type == "operation_in_progress"
    world.assert_no_writes()


def test_predecessor_not_found():
    world = _World()
    error = _error(world, _successor_nodes(), predecessor="999")
    assert error.error_type == "objective_not_found"


def test_already_superseded_predecessor_refuses():
    world = _stacked_world(published=False)
    world.objectives[PRED].header["superseded_by"] = "777"
    error = _error(world, _successor_nodes())
    assert error.error_type == "objective_not_open"
    assert "777" in str(error)


def test_junk_delivery_policy_fails_closed():
    world = _stacked_world(published=False)
    world.objectives[PRED].header["delivery"] = "bogus"
    error = _error(world, _successor_nodes())
    assert error.error_type == "invalid_delivery_policy"


def test_incremental_to_incremental_never_routes_here():
    world = _incremental_world()
    error = _error(world, [_node("9.1", pr="#101")], stacked=False)
    assert error.error_type == "invalid_input"


def test_structural_blockers_on_the_predecessor_refuse():
    world = _stacked_world(published=False)
    world.plans["102"]["objective_id"] = "444"  # wrong_owner on the predecessor train
    error = _error(world, _successor_nodes())
    assert error.error_type == "claimed_prefix_malformed"  # sync's shared structural gate
    assert "wrong_owner" in str(error)
    world.assert_no_writes()


# ----------------------------------------------------------------- rerun routing (D11)


def _interrupt(world: _World, step: str, nodes=None) -> transfer.TransferError | _Boom:
    world.boom.add(step)
    with pytest.raises(_Boom) as excinfo:
        world.run(nodes if nodes is not None else _successor_nodes())
    return excinfo.value


def test_rerun_same_run_rolls_forward_from_the_recorded_manifest():
    world = _stacked_world(published=True)
    _interrupt(world, "supersede_return")  # successor created; nothing stamped
    assert world.objectives[PRED].closed is False

    result = world.run(_successor_nodes())  # the SAME run re-invoked
    assert result.rolled_forward is True and result.journaled is True
    successor = result.successor.id
    # ONE successor objective exists; the rerun's create converged on the found arm.
    assert len(world.objectives) == 2
    assert len(world.prepared) == 1  # no second prepared record
    assert result.operation_id == world.prepared[0].operation_id
    # Every ownership write applied exactly once across both invocations.
    assert [t[1] for t in world.events("ownership")] == ["101", "102"]
    (outcome,) = world.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert world.objectives[PRED].header["superseded_by"] == successor
    assert world.objectives[PRED].closed is True


def test_rerun_different_run_with_a_live_successor_refuses_transfer_incomplete():
    world = _stacked_world(published=True)
    _interrupt(world, "supersede_return")
    old_operation = world.prepared[0].operation_id

    error = _error(world, _successor_nodes(), run_id="01RUNOTHER")
    assert error.error_type == "transfer_incomplete"
    assert old_operation in str(error)
    assert f"perk objective stack recover {PRED}" in str(error)  # names the predecessor
    assert len(world.objectives) == 2 and world.outcomes == []


def test_rerun_with_no_successor_abandons_with_proof_then_completes_fresh():
    world = _stacked_world(published=True)
    _interrupt(world, "prepare")  # journaled, crashed before creation
    old_operation = world.prepared[0].operation_id

    result = world.run(_successor_nodes(), run_id="01RUNOTHER")
    assert result.abandoned_operation_id == old_operation
    assert result.rolled_forward is False
    assert result.operation_id is not None and result.operation_id != old_operation
    roles = [(o.role, o.operation_id) for o in world.outcomes]
    assert roles == [
        (EventRole.ABANDONED, old_operation),
        (EventRole.COMPLETED, result.operation_id),
    ]
    (abandoned, _) = world.outcomes
    assert abandoned.observed == {
        "proof": "successor_absent",
        "run_id": RUN,
        "predecessor_objective_id": PRED,
    }
    assert len(world.objectives) == 2


def test_unresolved_foreign_kind_refuses_with_the_owning_resume():
    world = _stacked_world(published=False)
    world.prepared.append(
        PreparedRecord(
            operation_id=mint_operation_id(),
            operation_kind=OperationKind.PUBLISH,
            delivery_lineage=LINEAGE,
            objective_id=PRED,
            run_id="01RUNPUB",
            created=NOW,
            affected_plans=("101",),
            before={"x": 1},
            after={"x": 2},
        )
    )
    error = _error(world, _successor_nodes())
    assert error.error_type == "unresolved_operation"
    assert "publish" in str(error)
    assert world.supersede_calls == []


def test_unresolved_corrupt_transfer_manifest_fails_closed_at_the_save():
    world = _stacked_world(published=False)
    world.prepared.append(
        PreparedRecord(
            operation_id=mint_operation_id(),
            operation_kind=OperationKind.TRANSFER,
            delivery_lineage=LINEAGE,
            objective_id=PRED,
            run_id="01RUNX",
            created=NOW,
            affected_plans=(),
            before={"junk": True},
            after={"junk": True},
        )
    )
    with pytest.raises(JournalCorruptionError):
        world.run(_successor_nodes())
    assert world.supersede_calls == []


def test_found_successor_with_a_foreign_supersedes_fails_closed():
    world = _stacked_world(published=True)
    _interrupt(world, "supersede_return")
    successor_id = next(oid for oid in world.objectives if oid != PRED)
    world.objectives[successor_id].header["supersedes"] = "888"  # a foreign objective

    error = _error(world, _successor_nodes())
    assert error.error_type == "transfer_incomplete"
    assert "refusing to adopt" in str(error)
    assert world.outcomes == []


# ----------------------------------------------------------------- interruption matrix


@pytest.mark.parametrize(
    "step",
    ["prepare", "supersede_return", "ownership", "identity", "finalize_close", "completed"],
)
def test_interrupted_transfer_reruns_to_completion_without_duplicates(step: str):
    world = _stacked_world(published=True)
    _interrupt(world, step)
    assert world.objectives[PRED].closed is False or step == "completed"

    result = world.run(_successor_nodes())
    successor = result.successor.id
    # Converged: one successor, one COMPLETED outcome, the predecessor closed once.
    assert len(world.objectives) == 2
    completed = [o for o in world.outcomes if o.role is EventRole.COMPLETED]
    assert len(completed) == 1
    assert world.objectives[PRED].header["superseded_by"] == successor
    assert world.objectives[PRED].closed is True
    # No duplicate header effects: each plan's ownership/identity write ran at most once
    # per target value (the skip-if-match rerun applied only what was missing).
    ownership = [t for t in world.events("ownership")]
    assert sorted({t[1] for t in ownership}) == ["101", "102"]
    assert len(ownership) == len({t[1] for t in ownership})
    identity = world.events("identity")
    assert len(identity) == len({t[1] for t in identity})
    assert world.plans["101"]["objective_id"] == successor
    assert world.plans["102"]["objective_node_id"] == "9.3"


def test_non_journaled_conversion_interrupted_mid_ownership_converges_by_construction():
    # The incremental→stacked arm has NO journal: convergence is run_id-keyed creation +
    # the same-run successor's stored lineage (a fresh mint would fork the train identity)
    # + idempotent merge-writes + close-last.
    world = _incremental_world()
    nodes = [_node("9.1", pr="#101"), _node("9.2", pr="#102")]
    world.boom.add("ownership")
    with pytest.raises(_Boom):
        world.run(nodes)
    assert world.prepared == []  # nothing journaled on this arm
    first_lineage = world.supersede_calls[0]["delivery_lineage"]

    result = world.run(nodes)
    assert result.journaled is False and world.prepared == [] and world.outcomes == []
    assert len(world.objectives) == 2
    # The rerun reused the stored successor's lineage instead of minting a fork.
    assert world.supersede_calls[1]["delivery_lineage"] == first_lineage
    assert world.plans["101"]["delivery_lineage"] == first_lineage
    assert world.plans["102"]["delivery_lineage"] == first_lineage
    # Each ownership write applied exactly once across both invocations (skip-if-match).
    ownership = world.events("ownership")
    assert len(ownership) == len({t[1] for t in ownership}) == 2
    assert world.objectives[PRED].closed is True


def test_non_journaled_conversion_interrupted_after_the_finalize_stamp_re_finalizes():
    # Stamped-but-open predecessor + a same-run successor: the rerun re-finalizes
    # idempotently (ensures the close) instead of refusing objective_not_open.
    world = _incremental_world()
    nodes = [_node("9.1", pr="#101"), _node("9.2", pr="#102")]
    world.boom.add("finalize_close")
    with pytest.raises(_Boom):
        world.run(nodes)
    successor_id = next(oid for oid in world.objectives if oid != PRED)
    assert world.objectives[PRED].header["superseded_by"] == successor_id
    assert world.objectives[PRED].closed is False

    result = world.run(nodes)
    assert result.rolled_forward is True and result.successor.id == successor_id
    assert world.objectives[PRED].closed is True
    # The convergent tail is finalize-only: no second create attempt.
    assert len(world.supersede_calls) == 1


def test_a_foreign_stamp_still_refuses_objective_not_open():
    world = _stacked_world(published=False)
    world.objectives[PRED].header["superseded_by"] = "777"
    # A same-run successor exists but is NOT the stamped one — never converge onto it.
    world.objectives["777x"] = _Objective(
        url="u/777x",
        title="Other",
        header={"run_id": RUN, "supersedes": PRED},
        nodes=[],
    )
    error = _error(world, _successor_nodes())
    assert error.error_type == "objective_not_open"


def test_interrupted_conversion_rerun_converges_the_clear_writes():
    world = _stacked_world(published=False)
    nodes = [_node("9.1", pr="#101"), _node("9.2", pr="#102")]
    world.boom.add("clear")
    with pytest.raises(_Boom):
        world.run(nodes, stacked=False)
    result = world.run(nodes, stacked=False)
    assert result.rolled_forward is True
    # The first clear applied before the crash; the rerun skipped it and cleared the rest.
    assert world.events("clear") == [("clear", "101"), ("clear", "102")]
    assert world.objectives[PRED].closed is True


def test_predecessor_observation_infra_failure_precedes_every_write():
    world = _stacked_world(published=True)
    world.boom.add("reconstruct")  # consumed by the PREDECESSOR observation
    with pytest.raises(_Boom):
        world.run(_successor_nodes())
    world.assert_no_writes()


def test_infra_failure_during_verification_propagates_and_stays_unresolved():
    # A git infra error during the SUCCESSOR verification reconstruct must propagate raw
    # (never transfer_unverified), leaving the operation unresolved; the same-run rerun
    # rolls forward to completion.
    world = _stacked_world(published=True)
    original = world.reconstruct

    def flaky(root: Path, objective_id: str):
        if objective_id != PRED:
            raise TrainReconstructionError("git worktree list failed", error_type="git_error")
        return original(root, objective_id)

    with pytest.raises(TrainReconstructionError) as excinfo:
        world.run(_successor_nodes(), reconstruct=flaky)
    assert excinfo.value.error_type == "git_error"
    assert world.events("finalize") == [] and world.outcomes == []
    assert world.objectives[PRED].closed is False

    result = world.run(_successor_nodes())  # the same run, healthy observation
    assert result.rolled_forward is True
    assert world.objectives[PRED].closed is True


# ----------------------------------------------------------------- verification (D12)


def test_verification_catches_a_never_materialized_carried_plan():
    world = _stacked_world(published=True)
    _interrupt(world, "supersede_return")
    del world.plans["102"]  # the carried plan vanishes before the rerun

    error = _error(world, _successor_nodes())
    assert error.error_type == "transfer_unverified"
    # Fail closed: no finalize, no completion, the predecessor stays open + unresolved.
    assert world.events("finalize") == [] and world.outcomes == []
    assert world.objectives[PRED].closed is False
    assert "superseded_by" not in world.objectives[PRED].header


def test_verification_catches_a_diverged_successor_projection():
    world = _stacked_world(published=True)
    _interrupt(world, "supersede_return")
    successor_id = next(oid for oid in world.objectives if oid != PRED)
    # The successor's stored roadmap loses a node between prepare and the rerun.
    world.objectives[successor_id].nodes = [_node("9.1", pr="#101"), _node("9.3", pr="#102")]

    error = _error(world, _successor_nodes())
    assert error.error_type == "transfer_unverified"
    assert "diverges" in str(error)
    assert world.events("finalize") == [] and world.outcomes == []
    assert world.objectives[PRED].closed is False


def test_incremental_verification_catches_a_missing_backlink():
    world = _stacked_world(published=False)
    nodes = [_node("9.1", pr="#101"), _node("9.2", pr="#102")]
    world.boom.add("clear")
    with pytest.raises(_Boom):
        world.run(nodes, stacked=False)
    successor_id = next(oid for oid in world.objectives if oid != PRED)
    world.objectives[successor_id].nodes = [_node("9.1"), _node("9.2", pr="#102")]

    error = _error(world, nodes, stacked=False)
    assert error.error_type == "transfer_unverified"
    assert world.objectives[PRED].closed is False
