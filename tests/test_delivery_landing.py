"""Hermetic fake-driven tests for the delivery landing operation (contracts.md §8.56).

Every effectful seam of ``land_train`` is injected (the ``test_delivery_sync.py`` style):
a faked assessment returning a scripted :class:`LandReadiness`, a recording persistence
fake, scripted gateway outcomes (submit/poll/direct-merge/evidence/facts), Protocol-sized
issue-backend/store fakes, and one interleaved ops log pinning the load-bearing ordering
(assess → approve → re-observe → prepared → submit → accepted → poll → verify → completed →
finalize bottom→top → aggregate close). OFFLINE — no git / gh / network; injected
``now``/``sleep`` make the 60-tick poll deterministic.
"""

import contextlib
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from perk import objective
from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.delivery import land, land_records, landing, oplock, train
from perk.delivery.finalize import LandFinalization, LearnConsumeUpdate, ObjectiveLandUpdate
from perk.delivery.journal import (
    EventRole,
    JournalEvent,
    JournalFold,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
    canonical_payload,
)
from perk.delivery.persistence import AppendResult, JournalAppendAmbiguous
from perk.github import GitHubError
from perk.github.stacks import (
    DirectMergeOutcome,
    MergeAsyncResult,
    MergeAsyncSubmitOutcome,
    PrDeliveryFacts,
    PrMergedEvidence,
)

ROOT = Path("/repo")
OBJECTIVE = "500"
URL = "https://github.com/o/r/issues/500"
LINEAGE = "01LINEAGE"
B0 = "0" * 40  # the objective base head (layer 1's parent checkpoint)
H1 = "1" * 40  # layer-1 published head
H2 = "2" * 40  # layer-2 published head (the top pin)
MC1 = "a" * 40  # layer-1 merge commit
MC2 = "b" * 40  # layer-2 merge commit (the final base SHA)


def _train(lineage: str | None = LINEAGE) -> train.DeliveryTrain:
    return train.DeliveryTrain(
        objective_id=OBJECTIVE,
        objective_url=URL,
        delivery_lineage=lineage,
        base="main",
        redirected_from=None,
        layers=(),  # the faked assessment never reads them
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=train.BuildReadiness(next_node_id=None, ready=False, reason="x"),
    )


def _row(
    node_id: str, plan_id: str, pr_number: int, branch: str, base_ref: str, head_sha: str
) -> land.LandLayerReadiness:
    return land.LandLayerReadiness(
        node_id=node_id,
        plan_id=plan_id,
        pr_number=pr_number,
        branch=branch,
        expected_base_ref=base_ref,
        expected_head_sha=head_sha,
        base_sha=B0,
        assessed=True,
        observed_state="OPEN",
        observed_is_draft=False,
        observed_base_ref=base_ref,
        observed_head_ref=branch,
        observed_head_sha=head_sha,
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
        review_decision=None,
        required_checks_failed=(),
        required_checks_pending=(),
        optional_checks_failed=(),
        unresolved_thread_count=0,
    )


_ROWS = (
    _row("1.1", "101", 501, "plan-101", "main", H1),
    _row("1.2", "102", 502, "plan-102", "plan-101", H2),
)
_PLAN_LAYERS = (
    land.LandPlanLayer(node_id="1.1", plan_id="101", pr_number=501, base_sha=B0, head_sha=H1),
    land.LandPlanLayer(node_id="1.2", plan_id="102", pr_number=502, base_sha=H1, head_sha=H2),
)


def _readiness(
    *,
    disposition: land.LandDisposition = land.LandDisposition.READY,
    layers: tuple[land.LandLayerReadiness, ...] = _ROWS,
    findings: tuple[train.TrainFinding, ...] = (),
    plan_value: land.LandPlan | None = None,
) -> land.LandReadiness:
    return land.LandReadiness(
        objective_id=OBJECTIVE,
        objective_url=URL,
        delivery_lineage=LINEAGE,
        base="main",
        disposition=disposition,
        rules=land.MergeRulesView(squash_allowed=True, merge_queue_required=False),
        native_stack_capability=True,
        layers=layers,
        findings=findings,
        plan=plan_value,
    )


def _stack_plan() -> land.LandPlan:
    return land.LandPlan(
        mode="stack_merge_async",
        merge_method="squash",
        top_pr_number=502,
        top_head_sha=H2,
        layers=_PLAN_LAYERS,
    )


def _singleton_plan() -> land.LandPlan:
    return land.LandPlan(
        mode="singleton_squash",
        merge_method="squash",
        top_pr_number=501,
        top_head_sha=H1,
        layers=(_PLAN_LAYERS[0],),
    )


def _pending_submit(
    status: int = 202,
    uuid: str = "u-1",
    method: str = "squash",
    action: str = "direct_merge",
    expected: str = H2,
) -> MergeAsyncSubmitOutcome:
    return MergeAsyncSubmitOutcome(
        status=status,
        state="pending",
        uuid=uuid,
        merge_method=method,
        merge_action=action,
        expected_head_sha=expected,
        retry_after_seconds=None,
        rate_limited=False,
        raw_detail="",
    )


def _submit(status: int | None, state: str | None, detail: str = "") -> MergeAsyncSubmitOutcome:
    return MergeAsyncSubmitOutcome(
        status=status,
        state=state,
        uuid=None,
        merge_method=None,
        merge_action=None,
        expected_head_sha=None,
        retry_after_seconds=None,
        rate_limited=False,
        raw_detail=detail,
    )


def _direct(status: int | None, merged: bool, sha: str | None = None, detail: str = ""):
    return DirectMergeOutcome(
        status=status,
        merged=merged,
        sha=sha,
        retry_after_seconds=None,
        rate_limited=False,
        raw_detail=detail,
    )


def _evidence(
    pr_number: int,
    *,
    state: str = "MERGED",
    base_ref: str | None = None,
    head_ref: str | None = None,
    head_sha: str | None = None,
    merge_commit_sha: str | None = "default",
) -> PrMergedEvidence:
    """Post-merge evidence agreeing with the layer's approved identity unless overridden."""
    row = next(r for r in _ROWS if r.pr_number == pr_number)
    default_commit = MC1 if pr_number == 501 else MC2
    return PrMergedEvidence(
        number=pr_number,
        state=state,
        base_ref=base_ref if base_ref is not None else str(row.expected_base_ref),
        head_ref=head_ref if head_ref is not None else str(row.branch),
        head_sha=head_sha if head_sha is not None else str(row.expected_head_sha),
        merge_commit_sha=default_commit if merge_commit_sha == "default" else merge_commit_sha,
    )


def _fin(plan_id: str) -> LandFinalization:
    return LandFinalization(
        learn_state="pending",
        plan_issue_closed=False,
        objective=ObjectiveLandUpdate(OBJECTIVE, (f"node-of-{plan_id}",), None),
        learn=LearnConsumeUpdate((), "no_consumed_learn"),
    )


def _plan_state(plan_id: str, *, consumed: tuple[str, ...] = ()) -> PlanState:
    header: dict[str, object] = {"run_id": "01RUN"}
    if consumed:
        header["consumed_learn"] = list(consumed)
    return PlanState(
        id=plan_id,
        url=f"https://github.com/o/r/issues/{plan_id}",
        title=f"Plan {plan_id}",
        header=header,
        pr=None,
        state="OPEN",
    )


def _node(node_id: str, status: objective.NodeStatus) -> objective.ObjectiveNode:
    return objective.ObjectiveNode(id=node_id, description="d", status=status)


class _Probe:
    def active_plan_ids(self, plan_ids) -> frozenset[str]:
        return frozenset()


class _Harness:
    """The injected world: scripted seams + the shared interleaved ops log."""

    def __init__(self, readiness: land.LandReadiness, *, lineage: str | None = LINEAGE) -> None:
        self.ops: list[tuple] = []
        self.readiness = readiness
        self.train: train.TrainStatus = _train(lineage)
        # journal
        self.prepared: list[PreparedRecord] = []
        self.outcomes: list[OutcomeRecord] = []
        self.outcome_boom: dict[EventRole, Exception] = {}
        # gateway scripts
        self.submits: list[MergeAsyncSubmitOutcome] = []
        self.polls: list[MergeAsyncResult | Exception] = []
        self.directs: list[DirectMergeOutcome] = []
        self.facts_queue: list[PrDeliveryFacts | Exception | None] = []
        self.evidence: dict[int, PrMergedEvidence | Exception | None] = {
            501: _evidence(501),
            502: _evidence(502),
        }
        # backends
        self.plans: dict[str, PlanState] = {"101": _plan_state("101"), "102": _plan_state("102")}
        self.plan_boom: Exception | None = None
        self.backend_id = "github"
        self.nodes: list[objective.ObjectiveNode] = [
            _node("1.1", objective.NodeStatus.DONE),
            _node("1.2", objective.NodeStatus.DONE),
        ]
        self.objective_missing = False
        self.objective_state = "open"
        self.store_boom: Exception | None = None
        self.close_boom: Exception | None = None
        self.closed: list[str] = []
        # finalize
        self.finalize_boom: dict[str, Exception] = {}
        self.sleeps: list[float] = []
        self.lock_busy = False

    # --- seams -------------------------------------------------------------------------

    def reconstruct(self, _root: Path, objective_id: str) -> train.TrainStatus:
        self.ops.append(("reconstruct", objective_id))
        return self.train

    def observations_factory(self, _root: Path, base: str) -> land.LandObservations:
        self.ops.append(("observations", base))
        # Opaque — the faked assessment never touches it.
        return cast("land.LandObservations", object())

    def assess(self, train_projection, *, observations, remote_writers):
        self.ops.append(("assess",))
        assert train_projection is self.train
        return self.readiness

    def approve(self, readiness: land.LandReadiness) -> bool:
        self.ops.append(("approve", readiness.disposition.value))
        return True

    def decline(self, readiness: land.LandReadiness) -> bool:
        self.ops.append(("approve", readiness.disposition.value))
        return False

    @property
    def persistence(self) -> "_Harness":
        return self

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        self.ops.append(("prepared", record.operation_id))
        assert objective_id == OBJECTIVE
        self.prepared.append(record)
        return AppendResult(
            operation_id=record.operation_id, role=EventRole.PREPARED, existed=False
        )

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        self.ops.append((record.role.value,))
        boom = self.outcome_boom.get(record.role)
        if boom is not None:
            raise boom
        self.outcomes.append(record)
        return AppendResult(operation_id=record.operation_id, role=record.role, existed=False)

    def read_journal(self, objective_id: str) -> JournalFold:
        """The fresh-fold read the reconcile-evidence assembly consumes: folded live from
        everything THIS harness has recorded (same-invocation appends are visible)."""
        self.ops.append(("read_journal", objective_id))
        operations: dict[str, OperationState] = {}
        for record in self.prepared:
            prepared_event = JournalEvent(
                record=record,
                role=EventRole.PREPARED,
                operation_id=record.operation_id,
                canonical_payload=canonical_payload(record),
                comment_id="c1",
                created_at=record.created,
                carrier_objective_id=OBJECTIVE,
            )
            accepted = None
            outcome = None
            for out in self.outcomes:
                if out.operation_id != record.operation_id:
                    continue
                event = JournalEvent(
                    record=out,
                    role=out.role,
                    operation_id=out.operation_id,
                    canonical_payload=canonical_payload(out),
                    comment_id="c2",
                    created_at=out.created,
                    carrier_objective_id=OBJECTIVE,
                )
                if out.role is EventRole.ACCEPTED:
                    accepted = event
                else:
                    outcome = event
            operations[record.operation_id] = OperationState(
                operation_id=record.operation_id,
                kind=record.operation_kind,
                prepared=prepared_event,
                accepted=accepted,
                outcome=outcome,
            )
        return JournalFold(
            events=(),
            operations=operations,
            unresolved=tuple(op for op in operations.values() if not op.resolved),
            delivery_lineage=LINEAGE,
        )

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        self.ops.append(("get_plan", issue_id))
        if self.plan_boom is not None:
            raise self.plan_boom
        return self.plans.get(issue_id)

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        self.ops.append(("get_objective", objective_id))
        if self.store_boom is not None:
            raise self.store_boom
        if self.objective_missing:
            return None
        return ObjectiveState(
            id=objective_id,
            url=URL,
            title="t",
            header={},
            nodes=tuple(self.nodes),
            state="closed" if self.objective_state == "closed" else "open",
        )

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        self.ops.append(("close", objective_id))
        if self.close_boom is not None:
            raise self.close_boom
        self.closed.append(objective_id)
        return True

    def pr_facts(self, *, number: int, repo_root: Path) -> PrDeliveryFacts | None:
        self.ops.append(("pr_facts", number))
        if self.facts_queue:
            entry = self.facts_queue.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return entry
        return self._good_facts(number)

    def _good_facts(self, number: int) -> PrDeliveryFacts:
        row = next(r for r in _ROWS if r.pr_number == number)
        assert row.branch is not None and row.expected_base_ref is not None
        assert row.expected_head_sha is not None
        return PrDeliveryFacts(
            number=number,
            state="OPEN",
            is_draft=False,
            base_ref=row.expected_base_ref,
            head_ref=row.branch,
            head_sha=row.expected_head_sha,
        )

    def submit_async(self, *, number: int, sha: str, repo_root: Path) -> MergeAsyncSubmitOutcome:
        self.ops.append(("submit", number, sha))
        return self.submits.pop(0)

    def poll_async(self, *, number: int, uuid: str, repo_root: Path) -> MergeAsyncResult:
        self.ops.append(("poll", uuid))
        entry = self.polls.pop(0) if self.polls else MergeAsyncResult("pending", None, "")
        if isinstance(entry, Exception):
            raise entry
        return entry

    def merge_direct(
        self, *, number: int, sha: str, commit_message: str | None, repo_root: Path
    ) -> DirectMergeOutcome:
        self.ops.append(("merge_direct", number, sha, commit_message))
        return self.directs.pop(0)

    def merged_evidence(self, *, number: int, repo_root: Path) -> PrMergedEvidence | None:
        self.ops.append(("evidence", number))
        entry = self.evidence.get(number)
        if isinstance(entry, Exception):
            raise entry
        return entry

    def finalize(self, repo_root: Path, *, landed, pr_base: str, close_objective_on_complete=True):
        self.ops.append(("finalize", landed.plan_id, pr_base, landed.consumed_learn))
        assert close_objective_on_complete is False
        boom = self.finalize_boom.get(landed.plan_id)
        if boom is not None:
            raise boom
        return _fin(landed.plan_id)

    @contextlib.contextmanager
    def lock(self, _root: Path):
        if self.lock_busy:
            raise oplock.OperationLockBusy("another stack operation holds the lock")
        self.ops.append(("lock",))
        yield

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def run(self, *, approve="approve", objective_id: str = OBJECTIVE) -> landing.LandOutcome:
        callback = None
        if approve == "approve":
            callback = self.approve
        elif approve == "decline":
            callback = self.decline
        return landing.land_train(
            ROOT,
            objective_id=objective_id,
            run_id="01RUN",
            remote_writers=_Probe(),
            approve=callback,
            reconstruct=self.reconstruct,
            observations_factory=self.observations_factory,
            assess=self.assess,
            persistence_factory=lambda _root: self.persistence,
            issues_factory=lambda _root: self,
            store_factory=lambda _root: self,
            pr_facts=self.pr_facts,
            submit_async=self.submit_async,
            poll_async=self.poll_async,
            merge_direct=self.merge_direct,
            merged_evidence=self.merged_evidence,
            finalize=self.finalize,
            lock=self.lock,
            sleep=self.sleep,
            now=lambda: "T0",
        )


def _outcome_roles(h: _Harness) -> list[str]:
    return [record.role.value for record in h.outcomes]


# --- the happy paths ------------------------------------------------------------------


def test_happy_multi_layer_order_pinned():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert outcome.operation_id is not None and outcome.merge_async_uuid == "u-1"
    assert outcome.objective_closed is True and outcome.notes == ()
    assert [layer.pr_number for layer in outcome.landed_layers] == [501, 502]
    assert [layer.merge_commit_sha for layer in outcome.landed_layers] == [MC1, MC2]
    assert all(layer.finalization is not None for layer in outcome.landed_layers)
    # The load-bearing ordering (the interleaved ops log).
    kinds = [op[0] for op in h.ops]
    assert kinds == [
        "lock",
        "reconstruct",
        "observations",
        "assess",
        "approve",
        "pr_facts",  # re-observe 501
        "pr_facts",  # re-observe 502
        "prepared",
        "submit",
        "accepted",
        "poll",
        "evidence",  # verify 501
        "evidence",  # verify 502
        "completed",
        "get_plan",  # consumed_learn 101
        "finalize",  # bottom
        "get_plan",  # consumed_learn 102
        "finalize",  # top
        "get_objective",
        "close",
        "read_journal",  # the fresh-fold reconcile-evidence assembly on the close
    ]
    # The close transition carries the fresh-fold reconcile evidence.
    evidence = outcome.reconcile_evidence
    assert evidence is not None and evidence.partial is False
    assert [(row.pr_number, row.merge_commit_sha) for row in evidence.layers] == [
        (501, MC1),
        (502, MC2),
    ]
    assert [(row.base_sha, row.head_sha) for row in evidence.layers] == [(B0, H1), (H1, H2)]
    assert evidence.final_base_sha == MC2
    assert [(layer.base_sha, layer.head_sha) for layer in outcome.landed_layers] == [
        (B0, H1),
        (H1, H2),
    ]
    # The prepared payload is exactly the LandPlan evidence + base.
    (prepared,) = h.prepared
    assert prepared.operation_kind.value == "land"
    assert prepared.delivery_lineage == LINEAGE
    assert prepared.affected_plans == ("101", "102")
    assert prepared.before == {
        "mode": "stack_merge_async",
        "merge_method": "squash",
        "base": "main",
        "top_pr_number": 502,
        "top_head_sha": H2,
        "layers": [
            {"node_id": "1.1", "plan_id": "101", "pr_number": 501, "base_sha": B0, "head_sha": H1},
            {"node_id": "1.2", "plan_id": "102", "pr_number": 502, "base_sha": H1, "head_sha": H2},
        ],
    }
    assert prepared.after == {"merged_pr_numbers": [501, 502], "base": "main"}
    # accepted carries the VERIFIED options; completed carries the per-PR proof + the
    # final-base-SHA fact (the top layer's merge commit).
    accepted, completed = h.outcomes
    assert accepted.role is EventRole.ACCEPTED
    assert accepted.observed == {
        "uuid": "u-1",
        "merge_method": "squash",
        "merge_action": "direct_merge",
        "expected_head_sha": H2,
        "http_status": 202,
    }
    assert completed.role is EventRole.COMPLETED
    assert completed.observed == {
        "layers": [
            {"pr_number": 501, "merge_commit_sha": MC1},
            {"pr_number": 502, "merge_commit_sha": MC2},
        ],
        "reported_sha": "d" * 40,
        "final_base_sha": MC2,
    }
    # Finalize rode each layer's verified expected base, close_objective_on_complete=False.
    assert ("finalize", "101", "main", ()) in h.ops
    assert ("finalize", "102", "plan-101", ()) in h.ops
    assert h.closed == [OBJECTIVE]


def test_singleton_happy_path_no_accepted_ever():
    h = _Harness(_readiness(layers=(_ROWS[0],), plan_value=_singleton_plan()))
    h.plans["101"] = _plan_state("101", consumed=("7", "9"))
    h.directs = [_direct(200, True, sha="d" * 40)]
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert outcome.merge_async_uuid is None
    assert _outcome_roles(h) == ["completed"]  # NO accepted event ever — there is no handle
    # The squash message is the moved pure helper's exact bytes, from the step-6 read.
    merge_call = next(op for op in h.ops if op[0] == "merge_direct")
    assert merge_call == ("merge_direct", 501, H1, "Plan 101\n\nCloses #101")
    # The step-6 read is reused for consumed_learn — no second get_plan.
    assert [op for op in h.ops if op[0] == "get_plan"] == [("get_plan", "101")]
    assert ("finalize", "101", "main", ("7", "9")) in h.ops
    completed = h.outcomes[0]
    assert completed.observed["reported_sha"] == "d" * 40
    assert completed.observed["final_base_sha"] == MC1


def test_singleton_missing_plan_is_plan_not_found():
    h = _Harness(_readiness(layers=(_ROWS[0],), plan_value=_singleton_plan()))
    h.plans.pop("101")
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "plan_not_found"
    assert h.prepared == [] and h.outcomes == []


# --- consent + refusals ---------------------------------------------------------------


def test_declined_journals_nothing():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    outcome = h.run(approve="decline")
    assert outcome.outcome == "declined"
    assert outcome.operation_id is None
    assert h.prepared == [] and h.outcomes == []
    assert not any(op[0] in ("submit", "pr_facts") for op in h.ops)


def test_nothing_to_land_approved_closes_the_objective():
    h = _Harness(_readiness(disposition=land.LandDisposition.NOTHING_TO_LAND, layers=()))
    outcome = h.run()
    assert outcome.outcome == "completed_without_merge"
    assert outcome.objective_closed is True
    assert h.closed == [OBJECTIVE]
    assert h.prepared == [] and h.outcomes == []  # no journal — no remote train mutation
    # The close transition assembles the fresh-fold evidence — all-skipped ⇒ empty layers.
    assert outcome.reconcile_evidence is not None
    assert outcome.reconcile_evidence.layers == ()


def test_nothing_to_land_revalidates_node_terminality_after_the_pause():
    # The approval pause is a race boundary: a node added (or reopened) between the
    # NOTHING_TO_LAND assessment and the confirmed close is `land_drift` — a stale snapshot
    # never closes an incomplete objective, and nothing was closed.
    h = _Harness(_readiness(disposition=land.LandDisposition.NOTHING_TO_LAND, layers=()))
    h.nodes.append(_node("1.3", objective.NodeStatus.PENDING))
    with pytest.raises(landing.LandError) as excinfo:
        h.run()
    assert excinfo.value.error_type == "land_drift"
    assert "non-terminal node(s) 1.3" in str(excinfo.value)
    assert h.closed == []


def test_nothing_to_land_on_a_closed_objective_reports_no_transition():
    # State-aware (§8.44's lifecycle read): a rerun on an already-closed objective is a
    # real-transition report of False — no close write, no evidence assembly.
    h = _Harness(_readiness(disposition=land.LandDisposition.NOTHING_TO_LAND, layers=()))
    h.objective_state = "closed"
    outcome = h.run()
    assert outcome.outcome == "completed_without_merge"
    assert outcome.objective_closed is False
    assert h.closed == []
    assert outcome.reconcile_evidence is None
    assert any("already closed" in note for note in outcome.notes)


def test_aggregate_close_on_a_closed_objective_reports_no_transition():
    # The merged-path aggregate close is state-aware too: nodes terminal but the objective
    # already closed ⇒ objective_closed: false, close never re-issued.
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.objective_state = "closed"
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert outcome.objective_closed is False
    assert h.closed == []
    assert any("already closed" in note for note in outcome.notes)
    assert outcome.reconcile_evidence is None


def test_nothing_to_land_declined():
    h = _Harness(_readiness(disposition=land.LandDisposition.NOTHING_TO_LAND, layers=()))
    outcome = h.run(approve="decline")
    assert outcome.outcome == "declined"
    assert h.closed == []


def test_nothing_to_land_close_failure_is_a_typed_store_error():
    # The close is this arm's PRIMARY effect — never fail-open.
    h = _Harness(_readiness(disposition=land.LandDisposition.NOTHING_TO_LAND, layers=()))
    h.close_boom = ObjectiveStoreError("api down")
    with pytest.raises(ObjectiveStoreError):
        h.run()


def test_blocked_raises_land_blocked_with_readiness_attached():
    blocker = train.TrainFinding(
        kind=train.FindingKind.BLOCKER, code="pr_behind", message="PR #501 is BEHIND"
    )
    readiness = _readiness(disposition=land.LandDisposition.BLOCKED, findings=(blocker,))
    h = _Harness(readiness)
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "land_blocked"
    assert exc.value.readiness is readiness
    assert "pr_behind" in str(exc.value)
    assert h.prepared == [] and h.outcomes == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda facts: None,  # the PR vanished
        lambda facts: replace(facts, state="CLOSED"),  # not OPEN
        lambda facts: replace(facts, base_ref="other-base"),  # wrong merge target
        lambda facts: replace(facts, head_ref="other-branch"),  # not the published branch
        lambda facts: replace(facts, head_sha="f" * 40),  # head moved after approval
    ],
)
def test_reobserve_drift_is_land_drift_with_nothing_journaled(mutate):
    # Every re-observation predicate individually refuses — with nothing journaled and no
    # submission attempted.
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.facts_queue = [mutate(h._good_facts(501))]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "land_drift"
    assert h.prepared == [] and h.outcomes == []
    assert not any(op[0] in ("submit", "merge_direct") for op in h.ops)


def test_reobserve_read_failure_is_land_drift():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.facts_queue = [GitHubError("boom")]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "land_drift"
    assert h.prepared == []


def test_oplock_busy_is_operation_in_progress():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.lock_busy = True
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "operation_in_progress"
    assert h.ops == []  # refused before any read


def test_null_lineage_refuses_not_stacked():
    h = _Harness(_readiness(plan_value=_stack_plan()), lineage=None)
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "not_stacked"


def test_no_delivery_train_refuses_not_stacked():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.train = train.NoDeliveryTrain(
        objective_id=OBJECTIVE, objective_url=URL, redirected_from=None, reason="incremental"
    )
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "not_stacked"


# --- submit classification ------------------------------------------------------------


def test_submit_404_abandons_with_proof_then_merge_async_unavailable():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(404, None, "Not Found")]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "merge_async_unavailable"
    (abandoned,) = h.outcomes
    assert abandoned.role is EventRole.ABANDONED
    assert abandoned.observed["reason"] == "submit_404"
    assert abandoned.observed["reobserved"] == [
        {"pr_number": 501, "state": "OPEN", "head_sha": H1},
        {"pr_number": 502, "state": "OPEN", "head_sha": H2},
    ]


@pytest.mark.parametrize(
    "submitted,reason",
    [
        (_submit(400, "failed", "closed"), "submit_failed"),
        (_submit(422, None, "validation"), "submit_rejected"),
    ],
)
def test_submit_rejection_abandons_then_land_failed(submitted, reason):
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [submitted]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "land_failed"
    (abandoned,) = h.outcomes
    assert abandoned.observed["reason"] == reason


def test_poll_failed_abandons_then_land_failed():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("failed", None, "merge conflict")]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "land_failed"
    assert _outcome_roles(h) == ["accepted", "abandoned"]
    assert h.outcomes[1].observed["reason"] == "poll_failed"
    assert h.outcomes[1].observed["detail"] == "merge conflict"


def test_abandon_proof_contradiction_appends_nothing_and_stays_pending():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(404, None, "Not Found")]
    # Re-observe (2 good calls) passes; the abandon proof's first re-read contradicts.
    h.facts_queue = [
        h._good_facts(501),
        h._good_facts(502),
        replace(h._good_facts(501), state="CLOSED"),
    ]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert _outcome_roles(h) == []  # never claim before-state without proof
    assert any("unresolved" in note for note in outcome.notes)


def test_abandon_proof_read_failure_appends_nothing_and_stays_pending():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(400, "failed", "closed")]
    h.facts_queue = [h._good_facts(501), h._good_facts(502), GitHubError("read down")]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert _outcome_roles(h) == []


@pytest.mark.parametrize(
    "reply",
    [
        _pending_submit(status=502),  # a 5xx carrying a parseable MATCHING pending body
        _pending_submit(status=200),  # a pending body on a non-202/409 status
        _submit(500, "failed", "boom"),  # a 5xx carrying a parseable failed body
        _submit(502, "merged", "boom"),  # a 5xx carrying a parseable merged body
        _submit(400, None, "bad request"),  # a 400 without the protocol's failed body
    ],
)
def test_discordant_submit_replies_stay_ambiguous(reply):
    # Only the exact protocol status/state pairs classify; a discordant combination — even
    # one carrying matching options — must never reach accepted/abandoned/terminal.
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [reply, reply]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert len([op for op in h.ops if op[0] == "submit"]) == 2  # the one bounded retry
    assert _outcome_roles(h) == []


@pytest.mark.parametrize(
    "retry_reply",
    [
        _submit(404, None, "Not Found"),
        _submit(400, "failed", "closed"),
        _submit(422, None, "validation"),
    ],
)
def test_retry_side_rejection_never_abandons_a_possibly_applied_first_attempt(retry_reply):
    # A timed-out first request may already have created the async job — a retry-side
    # terminal rejection proves nothing about it, so the operation stays pending (never
    # abandoned, never a typed terminal failure).
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(None, None, "timeout"), retry_reply]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert _outcome_roles(h) == []
    assert any("unproven" in note for note in outcome.notes)


def test_retry_side_merged_recovers_the_ambiguous_first_attempt():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(None, None, "timeout"), _submit(200, "merged")]
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert _outcome_roles(h) == ["completed"]


def test_ambiguous_submit_retries_exactly_once_then_409_recovers_the_handle():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(None, None, "timeout"), _pending_submit(status=409)]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    outcome = h.run()
    assert outcome.outcome == "merged"
    submits = [op for op in h.ops if op[0] == "submit"]
    assert submits == [("submit", 502, H2), ("submit", 502, H2)]  # ONE identical retry
    assert _outcome_roles(h)[0] == "accepted"


def test_still_ambiguous_submit_stays_pending():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(None, None, "timeout"), _submit(502, None, "bad gateway")]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert len([op for op in h.ops if op[0] == "submit"]) == 2
    assert h.prepared != [] and _outcome_roles(h) == []  # unresolved; recovery concludes
    assert any("ambiguous" in note for note in outcome.notes)


def test_unparseable_2xx_submit_is_ambiguous_not_success():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(202, None, "junk"), _submit(202, None, "junk")]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert _outcome_roles(h) == []


def test_foreign_409_options_are_merge_request_conflict_without_accepted():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit(status=409, uuid="u-foreign", expected="f" * 40)]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "merge_request_conflict"
    assert "u-foreign" in str(exc.value)
    assert _outcome_roles(h) == []  # no accepted; the prepared operation stays unresolved
    assert h.prepared != []


def test_submit_200_merged_skips_the_poll():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_submit(200, "merged")]
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert outcome.merge_async_uuid is None
    assert not any(op[0] == "poll" for op in h.ops)
    assert _outcome_roles(h) == ["completed"]
    assert h.outcomes[0].observed["reported_sha"] is None


# --- the poll -------------------------------------------------------------------------


def test_poll_timeout_stays_pending_with_accepted_and_no_terminal():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = []  # the fake returns pending forever
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert outcome.merge_async_uuid == "u-1"
    assert _outcome_roles(h) == ["accepted"]
    assert len([op for op in h.ops if op[0] == "poll"]) == 60
    assert h.sleeps == [1.0] * 59
    assert any("still pending" in note for note in outcome.notes)


def test_enqueued_stops_immediately_as_unexpected_enqueued():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [
        MergeAsyncResult("pending", None, ""),
        MergeAsyncResult("enqueued", None, ""),
    ]
    outcome = h.run()
    assert outcome.outcome == "unexpected_enqueued"
    assert len([op for op in h.ops if op[0] == "poll"]) == 2
    assert _outcome_roles(h) == ["accepted"]  # unresolved — recovery concludes
    assert any("ENQUEUED" in note for note in outcome.notes)


def test_per_tick_poll_failures_are_tolerated_within_budget():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [
        GitHubError("tick down"),
        GitHubError("tick down"),
        MergeAsyncResult("merged", "d" * 40, ""),
    ]
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert len([op for op in h.ops if op[0] == "poll"]) == 3


# --- verification + bookkeeping (invariant 20) -----------------------------------------


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        _evidence(502, merge_commit_sha=None),
        _evidence(502, state="CLOSED", merge_commit_sha=None),
        _evidence(502, head_sha="f" * 40),  # a force-pushed layer merged the wrong head
        _evidence(502, head_ref="other-branch"),  # not the published branch
        _evidence(502, base_ref="unrelated"),  # merged into neither parent nor objective base
        GitHubError("read down"),
    ],
)
def test_merged_but_verification_fails_stays_pending_without_completed(evidence):
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.evidence[502] = evidence
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert _outcome_roles(h) == ["accepted"]  # no completed without full per-PR proof
    assert not any(op[0] == "finalize" for op in h.ops)
    assert any("verification failed" in note for note in outcome.notes)


def test_verification_tolerates_retarget_to_the_objective_base():
    # GitHub retargets a dependent PR onto the base when its parent branch is deleted at
    # merge — landing onto the objective base is a legitimate landing of the approved train.
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.evidence[502] = _evidence(502, base_ref="main")
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert _outcome_roles(h) == ["accepted", "completed"]


def test_completed_append_store_failure_degrades_to_merged_with_note():
    # The journal adapter's carrier read can raise the store's expected failures — after
    # verification that degrades to a note (invariant 20); finalization still runs.
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.outcome_boom[EventRole.COMPLETED] = ObjectiveStoreError("store outage")
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert any("could not be journaled" in note for note in outcome.notes)
    assert len([op for op in h.ops if op[0] == "finalize"]) == 2


def test_completed_append_failure_degrades_to_merged_with_note():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.outcome_boom[EventRole.COMPLETED] = JournalAppendAmbiguous("append ambiguous")
    outcome = h.run()
    assert outcome.outcome == "merged"  # invariant 20: a confirmed merge never reads unmerged
    assert any("could not be journaled" in note for note in outcome.notes)
    assert [layer.pr_number for layer in outcome.landed_layers] == [501, 502]
    # The close is DEFERRED (a close before the completion is durable would carry EMPTY
    # reconcile evidence and permanently suppress the drive) — recover converges it.
    assert outcome.objective_closed is False
    assert outcome.reconcile_evidence is None
    assert any("close deferred" in note for note in outcome.notes)
    assert all(op[0] != "close_objective" for op in h.ops)


def test_finalize_failure_notes_and_remaining_layers_still_finalize():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.finalize_boom["101"] = RuntimeError("backend exploded")
    outcome = h.run()
    assert outcome.outcome == "merged"
    bottom, top = outcome.landed_layers
    assert bottom.finalization is None and top.finalization is not None
    assert any("finalize failed for plan #101" in note for note in outcome.notes)
    assert len([op for op in h.ops if op[0] == "finalize"]) == 2


def test_consumed_learn_read_failure_finalizes_without_it():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.plan_boom = IssueBackendError("api down")
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert ("finalize", "101", "main", ()) in h.ops
    assert any("consumed_learn" in note for note in outcome.notes)


def test_aggregate_close_fail_open():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.close_boom = ObjectiveStoreError("api down")
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert outcome.objective_closed is False
    assert any("close failed" in note for note in outcome.notes)


def test_aggregate_close_skipped_while_nodes_remain():
    h = _Harness(_readiness(plan_value=_stack_plan()))
    h.submits = [_pending_submit()]
    h.polls = [MergeAsyncResult("merged", "d" * 40, "")]
    h.nodes.append(_node("1.3", objective.NodeStatus.PENDING))
    outcome = h.run()
    assert outcome.outcome == "merged"
    assert outcome.objective_closed is False
    assert h.closed == []
    assert any("non-terminal node(s): 1.3" in note for note in outcome.notes)


# --- the singleton's failure arms ------------------------------------------------------


def test_singleton_rejection_abandons_then_land_failed():
    h = _Harness(_readiness(layers=(_ROWS[0],), plan_value=_singleton_plan()))
    h.directs = [_direct(405, False, detail="Head branch was modified")]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "land_failed"
    (abandoned,) = h.outcomes
    assert abandoned.role is EventRole.ABANDONED
    assert abandoned.observed["reobserved"] == [{"pr_number": 501, "state": "OPEN", "head_sha": H1}]


def test_singleton_404_is_land_failed_not_unavailable():
    # The legacy endpoint exists everywhere — a missing PR is drift, not availability.
    h = _Harness(_readiness(layers=(_ROWS[0],), plan_value=_singleton_plan()))
    h.directs = [_direct(404, False, detail="Not Found")]
    with pytest.raises(landing.LandError) as exc:
        h.run()
    assert exc.value.error_type == "land_failed"


def test_singleton_ambiguous_retries_once_then_already_merged_recovers():
    h = _Harness(_readiness(layers=(_ROWS[0],), plan_value=_singleton_plan()))
    h.directs = [_direct(None, False, detail="timeout"), _direct(405, True, detail="already")]
    outcome = h.run()
    assert outcome.outcome == "merged"
    merges = [op for op in h.ops if op[0] == "merge_direct"]
    assert len(merges) == 2 and merges[0] == merges[1]  # the IDENTICAL retry
    assert outcome.landed_layers[0].merge_commit_sha == MC1  # verification re-read the commit


def test_singleton_still_ambiguous_stays_pending():
    h = _Harness(_readiness(layers=(_ROWS[0],), plan_value=_singleton_plan()))
    h.directs = [_direct(502, False, detail="bad gateway"), _direct(None, False, detail="t/o")]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert _outcome_roles(h) == []


def test_singleton_retry_side_rejection_never_abandons():
    # An applied-but-unconfirmed first merge surfaces on the retry as "already merged";
    # any other retry-side rejection proves nothing about the first attempt — pending.
    h = _Harness(_readiness(layers=(_ROWS[0],), plan_value=_singleton_plan()))
    h.directs = [
        _direct(None, False, detail="timeout"),
        _direct(405, False, detail="not mergeable"),
    ]
    outcome = h.run()
    assert outcome.outcome == "pending"
    assert _outcome_roles(h) == []
    assert any("unproven" in note for note in outcome.notes)


# --- the strict LAND payload read models (§8.56 read side) ------------------------------


def _prepared_record(
    op_id: str = "01JA0000000000000000000001",
    *,
    layers: list[dict] | None = None,
    mode: str = "stack_merge_async",
) -> PreparedRecord:
    rows = layers or [
        {"node_id": "1.1", "plan_id": "101", "pr_number": 501, "base_sha": B0, "head_sha": H1},
        {"node_id": "1.2", "plan_id": "102", "pr_number": 502, "base_sha": H1, "head_sha": H2},
    ]
    return PreparedRecord(
        operation_id=op_id,
        operation_kind=landing.OperationKind.LAND,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="T0",
        affected_plans=tuple(str(row["plan_id"]) for row in rows),
        before={
            "mode": mode,
            "merge_method": "squash",
            "base": "main",
            "top_pr_number": rows[-1]["pr_number"],
            "top_head_sha": rows[-1]["head_sha"],
            "layers": rows,
        },
        after={"merged_pr_numbers": [row["pr_number"] for row in rows], "base": "main"},
    )


def test_strict_prepared_models_round_trip():
    prepared = land_records.decode_land_prepared(_prepared_record())
    assert prepared.before.mode == "stack_merge_async"
    assert prepared.before.merge_method == "squash"
    assert prepared.before.top_pr_number == 502 and prepared.before.top_head_sha == H2
    assert [layer.node_id for layer in prepared.before.layers] == ["1.1", "1.2"]
    assert prepared.after == land_records.LandPreparedAfter(
        merged_pr_numbers=(501, 502), base="main"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"mode": "yolo"},  # unknown mode
        {"merge_method": "rebase"},  # unknown method
        {"extra": True},  # extra-forbid
        {"layers": [{"node_id": "1.1"}]},  # missing layer fields
    ],
)
def test_strict_prepared_junk_raises(mutation):
    record = _prepared_record()
    before = {**dict(record.before), **mutation}
    from dataclasses import replace as dc_replace

    from perk.delivery.journal import JournalCorruptionError

    with pytest.raises(JournalCorruptionError):
        land_records.decode_land_prepared(dc_replace(record, before=before))


def test_strict_prepared_wrong_kind_raises():
    from dataclasses import replace as dc_replace

    from perk.delivery.journal import JournalCorruptionError, OperationKind

    record = dc_replace(_prepared_record(), operation_kind=OperationKind.SYNC)
    with pytest.raises(JournalCorruptionError, match="not land"):
        land_records.decode_land_prepared(record)


def test_strict_accepted_and_abandoned_round_trip():
    accepted = land_records.decode_land_accepted(
        {
            "uuid": "u-1",
            "merge_method": "squash",
            "merge_action": "direct_merge",
            "expected_head_sha": H2,
            "http_status": 202,
        },
        operation_id="01JA0000000000000000000001",
    )
    assert accepted.uuid == "u-1" and accepted.http_status == 202
    abandoned = land_records.decode_land_abandoned(
        {
            "reason": "recovered_before_state",
            "detail": "d",
            "reobserved": [{"pr_number": 501, "state": "OPEN", "head_sha": H1}],
        },
        operation_id="01JA0000000000000000000001",
    )
    assert abandoned.reason == "recovered_before_state"
    assert abandoned.reobserved[0].pr_number == 501


@pytest.mark.parametrize(
    "reason", ["submit_404", "submit_failed", "submit_rejected", "poll_failed"]
)
def test_strict_abandoned_accepts_every_legacy_reason(reason):
    abandoned = land_records.decode_land_abandoned(
        {"reason": reason, "detail": "", "reobserved": []},
        operation_id="01JA0000000000000000000001",
    )
    assert abandoned.reason == reason


def test_strict_completed_pre_existing_records_decode_with_breach_defaults():
    # A §8.56-era record carries no breach fields — the additive defaults decode it.
    completed = land_records.decode_land_completed(
        {
            "layers": [{"pr_number": 501, "merge_commit_sha": MC1}],
            "reported_sha": None,
            "final_base_sha": MC1,
        },
        operation_id="01JA0000000000000000000001",
    )
    assert completed.external_prefix is False and completed.remainder == ()


def test_strict_completed_breach_round_trip_and_junk_raises():
    completed = land_records.decode_land_completed(
        {
            "layers": [{"pr_number": 501, "merge_commit_sha": MC1}],
            "reported_sha": None,
            "final_base_sha": MC1,
            "external_prefix": True,
            "remainder": [{"pr_number": 502, "state": "OPEN", "head_sha": H2}],
        },
        operation_id="01JA0000000000000000000001",
    )
    assert completed.external_prefix is True
    assert completed.remainder[0] == land_records.LandRemainderPr(
        pr_number=502, state="OPEN", head_sha=H2
    )
    from perk.delivery.journal import JournalCorruptionError

    with pytest.raises(JournalCorruptionError):
        land_records.decode_land_completed(
            {"layers": [], "final_base_sha": MC1},  # reported_sha is required-but-nullable
            operation_id="01JA0000000000000000000001",
        )


# --- the reconcile-evidence assembler (§8.56 W6b) ---------------------------------------


def _fold_of(*ops) -> JournalFold:
    operations = {op.operation_id: op for op in ops}
    return JournalFold(
        events=(),
        operations=operations,
        unresolved=tuple(op for op in operations.values() if not op.resolved),
        delivery_lineage=LINEAGE,
    )


def _completed_op(record: PreparedRecord, observed: dict) -> OperationState:
    prepared_event = JournalEvent(
        record=record,
        role=EventRole.PREPARED,
        operation_id=record.operation_id,
        canonical_payload=canonical_payload(record),
        comment_id="c1",
        created_at=record.created,
    )
    outcome_record = OutcomeRecord(
        operation_id=record.operation_id,
        role=EventRole.COMPLETED,
        created="T1",
        observed=observed,
    )
    outcome_event = JournalEvent(
        record=outcome_record,
        role=EventRole.COMPLETED,
        operation_id=record.operation_id,
        canonical_payload=canonical_payload(outcome_record),
        comment_id="c2",
        created_at="T1",
    )
    return OperationState(
        operation_id=record.operation_id,
        kind=record.operation_kind,
        prepared=prepared_event,
        accepted=None,
        outcome=outcome_event,
    )


def test_assemble_land_evidence_orders_breach_prefix_then_remainder():
    # Operation 1: the accepted external prefix (layer 1 only, breach-marked). Operation 2:
    # the landed remainder (layer 2). Fold order is delivery order by construction.
    breach = _completed_op(
        _prepared_record("01JA0000000000000000000001"),
        {
            "layers": [{"pr_number": 501, "merge_commit_sha": MC1}],
            "reported_sha": None,
            "final_base_sha": MC1,
            "external_prefix": True,
            "remainder": [{"pr_number": 502, "state": "OPEN", "head_sha": H2}],
        },
    )
    remainder = _completed_op(
        _prepared_record(
            "01JA0000000000000000000002",
            layers=[
                {
                    "node_id": "1.2",
                    "plan_id": "102",
                    "pr_number": 502,
                    "base_sha": H1,
                    "head_sha": H2,
                }
            ],
            mode="singleton_squash",
        ),
        {
            "layers": [{"pr_number": 502, "merge_commit_sha": MC2}],
            "reported_sha": MC2,
            "final_base_sha": MC2,
        },
    )
    evidence = landing.assemble_land_evidence(_fold_of(breach, remainder))
    assert evidence.partial is False and evidence.notes == ()
    assert [(row.node_id, row.pr_number, row.merge_commit_sha) for row in evidence.layers] == [
        ("1.1", 501, MC1),
        ("1.2", 502, MC2),
    ]
    assert [(row.base_sha, row.head_sha) for row in evidence.layers] == [(B0, H1), (H1, H2)]
    # final_base_sha comes from the LAST completed record.
    assert evidence.final_base_sha == MC2


def test_assemble_land_evidence_marks_undecodable_records_partial():
    good = _completed_op(
        _prepared_record("01JA0000000000000000000001"),
        {
            "layers": [{"pr_number": 501, "merge_commit_sha": MC1}],
            "reported_sha": None,
            "final_base_sha": MC1,
        },
    )
    bad = _completed_op(
        _prepared_record("01JA0000000000000000000002"),
        {"layers": "junk"},
    )
    evidence = landing.assemble_land_evidence(_fold_of(good, bad))
    assert evidence.partial is True
    assert any("undecodable" in note for note in evidence.notes)
    assert [row.pr_number for row in evidence.layers] == [501]
