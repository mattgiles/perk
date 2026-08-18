"""Contract tests for the compact ``perk.delivery`` status/Prepare façade."""

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import Any, Literal, cast

import pytest

import perk.delivery as delivery_pkg
from perk.backends.issue_backend import IssueBackendError, PlanHeaderUpdate, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.delivery import facade as facade_mod
from perk.delivery import observe
from perk.delivery import publish as publish_mod
from perk.delivery._fakes import FakeDeliveryGit, FakeDeliveryGitHub, FakeDeliveryPersistence
from perk.delivery.facade import (
    Delivery,
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    LandRequest,
    LandResult,
    PrepareRequest,
    PrepareResult,
    PublishRequest,
    PublishResult,
    RecoverRequest,
    RecoverResult,
    StatusRequest,
    StatusResult,
    SyncRequest,
    SyncResult,
    TransferRequest,
    TransferResult,
)
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalFold,
    JournalRecordTooLarge,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
)
from perk.delivery.layer import LayerError
from perk.delivery.persistence import AppendResult, TrainPersistenceError
from perk.delivery.train import (
    BaseHeadObservation,
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
    StackView,
    TrainFinding,
    TrainLayer,
    TrainReconstructionError,
    WorktreeFacts,
)
from perk.github import GitHubError, prs, stacks
from perk.objective import NodeStatus, ObjectiveNode
from perk.substrate import config as config_mod
from perk.substrate import git as git_mod

_DELIVERY_ERROR_TYPES = {
    "capability_unsupported",
    "objective_not_found",
    "invalid_delivery_policy",
    "invalid_train",
    "git_error",
    "github_error",
    "supersession_corruption",
    "invalid_input",
    "missing_lineage",
    "stacked_predecessor_missing",
    "unknown_layer",
    "node_not_build_ready",
    "parent_missing",
    "parent_unverified",
    "not_stacked",
    "unresolved_operation",
    "sync_conflict_pending",
    "claimed_prefix_malformed",
    "active_writer",
    "dirty_worktree",
    "writer_observation_unavailable",
    "remote_drift",
    "pr_drift",
    "membership_drift",
    "stale_parent",
    "base_unobserved",
    "multiple_push_urls",
    "atomic_push_unsupported",
    "rebase_conflict",
    "push_rejected",
    "sync_drift",
    "postcondition_unverified",
    "adopt_blocked",
    "no_continuation",
    "continuation_stale",
    "continuation_invalid",
    "rebase_in_progress",
    "operation_in_progress",
    "operation_ambiguous",
    "operation_not_found",
    "abandon_blocked",
    "accept_blocked",
    "unsupported_operation_kind",
    "journal_corruption",
    "journal_record_too_large",
    "invalid_config",
    "delivery_error",
    "stack_capability_lost",
    "pr_already_merged",
    "remote_settling_timeout",
    "stack_registration_drift",
    "stack_registration_failed",
    "publication_drift",
    "no_pr",
    "pr_not_open",
    "layer_not_published",
    "structural_blockers",
    "policy_immutable",
    "base_immutable",
    "prefix_mismatch",
    "dropped_open_pr",
    "pr_exists",
    "transfer_incomplete",
    "transfer_unverified",
    "transfer_manifest_oversize",
    "objective_not_open",
    "invalid_roadmap",
    "supersede_unsupported",
    "stacked_plan",
    "plan_not_found",
}
_STATUS_ERROR_TYPES = {
    "objective_not_found",
    "invalid_delivery_policy",
    "invalid_train",
    "git_error",
    "github_error",
    "supersession_corruption",
}
_RETIRED_EXPORTS = {
    "DeliveryOperationFacts",
    "LayerBodyFacts",
    "PublicationError",
    "PublicationResult",
    "TrainRowFacts",
    "publish_layer",
    "NO_TRAIN_INCREMENTAL_REASON",
    "STRUCTURAL_BLOCKER_CODES",
    "BaseHeadObservation",
    "BuildReadiness",
    "DeliveryTrain",
    "FindingKind",
    "GatewayGitHubProbe",
    "GitHubProbe",
    "GitProbe",
    "JournalReader",
    "LayerFinalization",
    "LayerGit",
    "LayerIntent",
    "LayerMembership",
    "LayerPr",
    "LayerPublication",
    "LayerWriter",
    "NoDeliveryTrain",
    "ObjectiveReader",
    "PlanReader",
    "PrFactsView",
    "RepoGitProbe",
    "StackEntryView",
    "StackView",
    "TrainFinding",
    "TrainLayer",
    "TrainReads",
    "TrainReconstructionError",
    "TrainStatus",
    "UnresolvedOperationFacts",
    "WorktreeFacts",
    "reconstruct_repo_train",
    "reconstruct_train",
    "resolve_train_reads",
    "CapabilityCheck",
    "CapabilityReport",
    "preflight_stacked_authoring",
    "LayerContext",
    "LayerContextOut",
    "LayerError",
    "PreparedLayerStart",
    "derive_layer_context",
    "prepare_layer_start",
    "require_ready_layer",
    "require_reviewable_layer",
    "ClaimedLayer",
    "SyncCascade",
    "SyncError",
    "SyncedLayer",
    "derive_claimed_prefix",
    "synchronize_train",
    "probe_atomic_push_urls",
    "ContinuationLayer",
    "ContinuationManifest",
    "PendingContinuation",
    "continuations_dir",
    "manifest_path",
    "pending_continuation",
    "write_manifest",
    "RemoteWriterProbe",
    "WriterObservationError",
    "RecoverError",
    "recover_operations",
    "MergedPrefixRow",
    "RemainderPrRow",
    "LandedLayerRow",
    "OperationRow",
    "SweepFailure",
    "AbandonPreview",
    "AcceptPrefixPreview",
    "LandedPlan",
    "LandFinalization",
    "LearnConsumeUpdate",
    "ObjectiveLandUpdate",
    "finalize_landed_plan",
    "squash_commit_message",
}
_NEW_EXPORTS = {
    "Delivery",
    "DeliveryPersistence",
    "DeliveryGit",
    "DeliveryGitHub",
    "DeliveryError",
    "PrepareRequest",
    "PrepareResult",
    "StatusRequest",
    "StatusResult",
    "PublishRequest",
    "PublishResult",
    "RecoverRequest",
    "RecoverResult",
    "SyncRequest",
    "SyncResult",
    "TransferRequest",
    "TransferResult",
    "LandRequest",
    "LandResult",
    "resolve_delivery",
}
_RETAINED_EXPORTS = {
    "JOURNAL_EVENT_MAX_CHARS",
    "JOURNAL_SCHEMA_VERSION",
    "AppendResult",
    "EventRole",
    "JournalAppendAmbiguous",
    "JournalCorruptionError",
    "JournalEvent",
    "JournalFold",
    "JournalRecordTooLarge",
    "OperationKind",
    "OperationState",
    "OutcomeRecord",
    "PreparedRecord",
    "TrainPersistence",
    "TrainPersistenceError",
    "UnresolvedOperationError",
    "canonical_payload",
    "ensure_event_size",
    "fold_events",
    "mint_operation_id",
    "parse_journal_comment",
    "render_event",
    "resolve_train_persistence",
    "CheckView",
    "GatewayLandObservations",
    "LandDisposition",
    "LandError",
    "LandLayerReadiness",
    "LandObservationError",
    "LandObservations",
    "LandOutcome",
    "LandPlan",
    "LandPlanLayer",
    "LandReadiness",
    "LandedLayer",
    "MergeRulesView",
    "PrLandView",
    "assess_land_readiness",
    "land_train",
}


def _objective(
    objective_id: str = "10",
    *,
    header: dict[str, object] | None = None,
    title: str = "Objective",
    nodes: tuple[ObjectiveNode, ...] = (),
) -> ObjectiveState:
    return ObjectiveState(
        id=objective_id,
        url=f"fake://objective/{objective_id}",
        title=title,
        header=dict(header or {}),
        nodes=nodes,
    )


def _plan(plan_id: str = "101") -> PlanState:
    return PlanState(
        id=plan_id,
        url=f"fake://plan/{plan_id}",
        title="Plan",
        header={},
        pr=None,
        state="OPEN",
    )


def _train() -> DeliveryTrain:
    return DeliveryTrain(
        objective_id="10",
        objective_url="fake://objective/10",
        delivery_lineage="lineage",
        base="main",
        redirected_from=None,
        layers=(),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=BuildReadiness(
            next_node_id=None,
            ready=False,
            reason="the train has no layers (all skipped/empty)",
        ),
    )


def _train_layer(
    node_id: str,
    plan_id: str | None,
    branch: str | None,
    *,
    remote_head: str | None = None,
) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=branch,
        pr_number=None,
        intent=LayerIntent.PLANNED if plan_id is not None else LayerIntent.UNPLANNED,
        publication=LayerPublication.UNPUBLISHED,
        git=LayerGit.ABSENT,
        pr=LayerPr.ABSENT,
        membership=LayerMembership.NOT_APPLICABLE,
        writer=LayerWriter.FREE,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=None,
        published_head_sha=None,
        observed_remote_head_sha=remote_head,
        observed_pr_base=None,
        expected_pr_base=None,
    )


def _planning_train(
    *,
    nodes: tuple[ObjectiveNode, ...],
    layers: tuple[TrainLayer, ...],
    candidate: str | None,
    ready: bool = True,
    reason: str | None = None,
    objective_id: str = "10",
    redirected_from: str | None = None,
) -> DeliveryTrain:
    return DeliveryTrain(
        objective_id=objective_id,
        objective_url=f"fake://objective/{objective_id}",
        delivery_lineage="lineage",
        base="main",
        redirected_from=redirected_from,
        layers=layers,
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=BuildReadiness(
            next_node_id=candidate,
            ready=ready,
            reason=reason,
        ),
        objective_title="Captured objective",
        objective_nodes=nodes,
    )


class _StatusDelivery(Delivery):
    def __init__(
        self,
        result: StatusResult,
        *,
        persistence: DeliveryPersistence | None = None,
        git: DeliveryGit | None = None,
        github: DeliveryGitHub | None = None,
    ) -> None:
        super().__init__(
            persistence=persistence or FakeDeliveryPersistence(),
            git=git or FakeDeliveryGit(),
            github=github or FakeDeliveryGitHub(),
        )
        self.result = result
        self.status_calls: list[StatusRequest] = []

    def status(self, request: StatusRequest) -> StatusResult:
        self.status_calls.append(request)
        return self.result

    def _status_with_store(
        self,
        request: StatusRequest,
        *,
        store,
    ) -> StatusResult:
        del store
        self.status_calls.append(request)
        return self.result


def _delivery(
    persistence: DeliveryPersistence | None = None,
    git: DeliveryGit | None = None,
    github: DeliveryGitHub | None = None,
) -> Delivery:
    return Delivery(
        persistence=persistence or FakeDeliveryPersistence(),
        git=git or FakeDeliveryGit(),
        github=github or FakeDeliveryGitHub(),
    )


def _transfer_request(
    *,
    delivery: Literal["incremental", "stacked"] = "incremental",
    roadmap_nodes: tuple[ObjectiveNode, ...] | None = None,
    carry_map: tuple[tuple[str, str], ...] = (),
) -> TransferRequest:
    return TransferRequest(
        predecessor_id="10",
        run_id="01RUN",
        title="Successor",
        prose="prose",
        base=None,
        roadmap_nodes=roadmap_nodes
        or (ObjectiveNode("1.1", "work", NodeStatus.PENDING, pr="#101"),),
        carry_map=carry_map,
        delivery=delivery,
    )


def test_transfer_values_are_frozen_intent_without_constructor_normalization() -> None:
    request = TransferRequest(
        predecessor_id=" #10 ",
        run_id=" ",
        title=" ",
        prose="prose",
        base=" ",
        roadmap_nodes=(),
        carry_map=((" ", " "),),
        delivery="incremental",
    )
    result = TransferResult(
        predecessor_id="10",
        successor=facade_mod.ObjectiveRef(id="11", url="u/11", existed=False),
        operation_id=None,
        abandoned_operation_id=None,
        rolled_forward=False,
        journaled=False,
    )
    assert request.predecessor_id == " #10 " and result.operation_id is None
    with pytest.raises(FrozenInstanceError):
        type(request).__setattr__(request, "title", "changed")


def _forbid_transfer_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    from perk.delivery import transfer as transfer_mod

    def forbidden(_root: Path):
        raise AssertionError("invalid transfer intent reached the operation lock")

    runtime = replace(transfer_mod._DEFAULT_TRANSFER_RUNTIME, operation_lock=forbidden)
    monkeypatch.setattr(transfer_mod, "_DEFAULT_TRANSFER_RUNTIME", runtime)


def test_transfer_intent_validation_precedes_lock_and_all_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_transfer_lock(monkeypatch)
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()
    request = _transfer_request(roadmap_nodes=())
    request = replace(request, roadmap_nodes=())

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, git, github).transfer(request)

    assert excinfo.value.error_type == "invalid_roadmap"
    assert persistence.calls == [] and git.calls == [] and github.calls == []


@pytest.mark.parametrize(
    ("mutate", "error_type"),
    (
        (lambda request: replace(request, delivery=cast(Any, "future")), "invalid_input"),
        (
            lambda request: replace(
                request,
                roadmap_nodes=(
                    ObjectiveNode("1.1", "one", NodeStatus.PENDING),
                    ObjectiveNode("1.1", "duplicate", NodeStatus.PENDING),
                ),
            ),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(
                request,
                roadmap_nodes=(
                    ObjectiveNode(
                        "1.1", "unknown dependency", NodeStatus.PENDING, depends_on=("9.9",)
                    ),
                ),
            ),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(
                request,
                roadmap_nodes=(
                    ObjectiveNode("1.1", "one", NodeStatus.PENDING, depends_on=("1.2",)),
                    ObjectiveNode("1.2", "two", NodeStatus.PENDING, depends_on=("1.1",)),
                ),
            ),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(
                request,
                carry_map=(("1.1", "ENG-1"), ("1.1", "ENG-1")),
            ),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(request, carry_map=((" ", "ENG-1"),)),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(request, carry_map=cast(Any, ((7, "ENG-1"),))),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(request, carry_map=(("9.9", "ENG-1"),)),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(request, carry_map=(("1.1", " "),)),
            "invalid_roadmap",
        ),
        (
            lambda request: replace(
                request,
                carry_map=cast(Any, (("1.1", 7),)),
            ),
            "invalid_roadmap",
        ),
    ),
)
def test_transfer_intent_recoverability_matrix_fails_before_io(
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    error_type: str,
) -> None:
    _forbid_transfer_lock(monkeypatch)
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, git, github).transfer(mutate(_transfer_request()))

    assert excinfo.value.error_type == error_type
    assert persistence.calls == [] and git.calls == [] and github.calls == []


def test_plain_incremental_transfer_is_locked_and_uses_raw_carries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import nullcontext

    from perk.backends.objective_store import ObjectiveRef
    from perk.delivery import transfer as transfer_mod

    predecessor = _objective(header={})
    successor = ObjectiveRef(id="11", url="u/11", existed=False)
    persistence = FakeDeliveryPersistence(
        objectives={"10": predecessor},
        successors_by_run={"01RUN": successor},
        preserve_transfer_carries=True,
    )
    runtime = replace(
        transfer_mod._DEFAULT_TRANSFER_RUNTIME,
        operation_lock=lambda _root: nullcontext(),
    )
    monkeypatch.setattr(transfer_mod, "_DEFAULT_TRANSFER_RUNTIME", runtime)
    request = _transfer_request(carry_map=(("1.1", "ENG-1"),))

    result = _delivery(persistence).transfer(request)

    assert result.successor is successor and result.operation_id is None
    assert persistence.calls[0] == ("get_objective", "10")
    assert all(
        call[0] not in {"read_journal", "normalize_transfer_carry_map"}
        for call in persistence.calls
    )
    supersede = next(call for call in persistence.calls if call[0] == "supersede_objective")
    carries = cast(tuple[tuple[str, str], ...], supersede[8])
    assert ("1.1", "ENG-1") in carries
    assert supersede[-2:] == (True, False)


@pytest.mark.parametrize(
    ("predecessor_delivery", "successor_delivery", "uses_transfer_core"),
    (
        ("incremental", "incremental", False),
        ("incremental", "stacked", True),
        ("stacked", "incremental", True),
        ("stacked", "stacked", True),
    ),
)
def test_transfer_facade_routes_all_policy_pairs(
    monkeypatch: pytest.MonkeyPatch,
    predecessor_delivery: str,
    successor_delivery: str,
    uses_transfer_core: bool,
) -> None:
    from contextlib import nullcontext

    from perk.backends.objective_store import ObjectiveRef
    from perk.delivery import transfer as transfer_mod

    header: dict[str, object] = (
        {}
        if predecessor_delivery == "incremental"
        else {"delivery": "stacked", "delivery_lineage": "lineage"}
    )
    successor = ObjectiveRef(id="11", url="u/11", existed=False)
    persistence = FakeDeliveryPersistence(
        objectives={"10": _objective(header=header)},
        successors_by_run={"01RUN": successor},
        preserve_transfer_carries=True,
    )
    routed: list[tuple[object, ...]] = []

    def run_core(fresh, request, **kwargs):
        routed.append((fresh, request, kwargs["predecessor_policy"]))
        return TransferResult(
            predecessor_id="10",
            successor=successor,
            operation_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            abandoned_operation_id=None,
            rolled_forward=False,
            journaled=predecessor_delivery == "stacked",
        )

    runtime = replace(
        transfer_mod._DEFAULT_TRANSFER_RUNTIME,
        operation_lock=lambda _root: nullcontext(),
    )
    monkeypatch.setattr(transfer_mod, "_DEFAULT_TRANSFER_RUNTIME", runtime)
    monkeypatch.setattr(transfer_mod, "_run", run_core)

    result = _delivery(persistence).transfer(
        _transfer_request(delivery=cast(Any, successor_delivery))
    )

    assert result.successor is successor
    assert bool(routed) is uses_transfer_core
    assert persistence.calls.count(("get_objective", "10")) == 1
    normalized = [call for call in persistence.calls if call[0] == "normalize_transfer_carry_map"]
    assert bool(normalized) is uses_transfer_core


@pytest.mark.parametrize(
    ("source", "expected_type", "expected_message"),
    (
        (
            TrainReconstructionError("domain reconstruction", error_type="invalid_train"),
            "invalid_train",
            "domain reconstruction",
        ),
        (
            TrainReconstructionError("git infrastructure", error_type="git_error"),
            "git_error",
            "git infrastructure",
        ),
        (
            ObjectiveStoreError("objective unavailable"),
            "github_error",
            "objective create failed\nobjective unavailable",
        ),
    ),
)
def test_transfer_status_bridge_restores_declared_causes(
    monkeypatch: pytest.MonkeyPatch,
    source: Exception,
    expected_type: str,
    expected_message: str,
) -> None:
    from contextlib import nullcontext

    from perk.delivery import transfer as transfer_mod

    class _CauseStatusDelivery(Delivery):
        def status(self, request: StatusRequest) -> StatusResult:
            del request
            try:
                raise source
            except Exception as cause:
                raise DeliveryError("status wrapper", error_type="github_error") from cause

    predecessor = _objective(
        header={"delivery": "stacked", "delivery_lineage": "lineage"},
        nodes=(ObjectiveNode("1.1", "work", NodeStatus.PENDING),),
    )
    persistence = FakeDeliveryPersistence(objectives={"10": predecessor})
    runtime = replace(
        transfer_mod._DEFAULT_TRANSFER_RUNTIME,
        operation_lock=lambda _root: nullcontext(),
    )
    monkeypatch.setattr(transfer_mod, "_DEFAULT_TRANSFER_RUNTIME", runtime)
    service = _CauseStatusDelivery(
        persistence=persistence,
        git=FakeDeliveryGit(),
        github=FakeDeliveryGitHub(),
    )

    with pytest.raises(DeliveryError) as excinfo:
        service.transfer(
            _transfer_request(
                delivery="stacked",
                roadmap_nodes=(ObjectiveNode("1.1", "work", NodeStatus.PENDING),),
            )
        )

    assert excinfo.value.error_type == expected_type
    assert str(excinfo.value) == expected_message


def test_transfer_lock_serializes_d1_and_second_contender_observes_finalized_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from contextlib import contextmanager

    from perk.backends.objective_store import ObjectiveRef
    from perk.delivery import oplock
    from perk.delivery import transfer as transfer_mod

    first_entered = threading.Event()
    release_first = threading.Event()
    operation_lock = threading.Lock()
    first_successor = ObjectiveRef(id="11", url="u/11", existed=False)

    class _ContendedPersistence(FakeDeliveryPersistence):
        def __init__(self) -> None:
            super().__init__(
                objectives={"10": _objective()},
                successors_by_run={"01FIRST": first_successor},
            )
            self.observed_superseded_by: list[object] = []

        def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
            state = super().get_objective(objective_id=objective_id)
            self.observed_superseded_by.append(
                state.header.get("superseded_by") if state is not None else None
            )
            return state

        def supersede_objective(self, **kwargs) -> ObjectiveRef | None:
            if kwargs["run_id"] != "01FIRST":
                raise AssertionError("the second contender must refuse before mutation")
            first_entered.set()
            assert release_first.wait(timeout=5)
            state = self._objectives["10"]
            header = dict(state.header)
            header["superseded_by"] = first_successor.id
            self._objectives["10"] = replace(state, header=header, state="closed")
            return first_successor

    @contextmanager
    def held(_root: Path):
        if not operation_lock.acquire(blocking=False):
            raise oplock.OperationLockBusy("another stack operation is in progress")
        try:
            yield
        finally:
            operation_lock.release()

    persistence = _ContendedPersistence()
    runtime = replace(transfer_mod._DEFAULT_TRANSFER_RUNTIME, operation_lock=held)
    monkeypatch.setattr(transfer_mod, "_DEFAULT_TRANSFER_RUNTIME", runtime)
    service = _delivery(persistence)
    results: dict[str, object] = {}

    def invoke_first() -> None:
        results["first"] = service.transfer(replace(_transfer_request(), run_id="01FIRST"))

    first = threading.Thread(target=invoke_first)
    first.start()
    assert first_entered.wait(timeout=5)

    with pytest.raises(DeliveryError) as busy:
        service.transfer(replace(_transfer_request(), run_id="01SECOND"))
    assert busy.value.error_type == "operation_in_progress"
    assert persistence.observed_superseded_by == [None]

    release_first.set()
    first.join(timeout=5)
    assert isinstance(results["first"], TransferResult)

    with pytest.raises(DeliveryError) as finalized:
        service.transfer(replace(_transfer_request(), run_id="01SECOND"))
    assert finalized.value.error_type == "objective_not_open"
    assert persistence.observed_superseded_by == [None, "11"]


def test_replan_prepare_incremental_projects_one_objective_snapshot() -> None:
    nodes = (ObjectiveNode("1.1", "work", NodeStatus.PENDING),)
    persistence = FakeDeliveryPersistence(
        objectives={"10": _objective(header={"base": "main"}, nodes=nodes)}
    )

    result = _delivery(persistence).prepare(PrepareRequest(kind="replan", objective_id="10"))

    assert result.replan == PrepareResult.ReplanContext(
        objective_id="10",
        objective_url="fake://objective/10",
        objective_title="Objective",
        nodes=nodes,
        delivery="incremental",
        base="main",
        delivery_lineage=None,
        claimed=(),
        open_pr_plans=(),
    )
    assert persistence.calls == [("get_objective", "10")]


def test_replan_prepare_stacked_projects_claims_and_open_prs_from_bound_status() -> None:
    nodes = (ObjectiveNode("1.1", "work", NodeStatus.IN_PROGRESS, pr="#101"),)
    persistence = FakeDeliveryPersistence(
        objectives={
            "10": _objective(
                header={"delivery": "stacked", "delivery_lineage": "lineage"},
                nodes=nodes,
            )
        }
    )
    layer = replace(
        _train_layer("1.1", "101", "plan-101"),
        pr_number=42,
        pr=LayerPr.READY,
        parent_checkpoint_sha="a" * 40,
        published_head_sha="b" * 40,
    )
    status = _planning_train(nodes=nodes, layers=(layer,), candidate=None)
    service = _StatusDelivery(
        StatusResult(
            objective_id="10",
            objective_url="fake://objective/10",
            redirected_from=None,
            train=status,
            no_train_reason=None,
        ),
        persistence=persistence,
    )

    result = service.prepare(PrepareRequest(kind="replan", objective_id="10"))

    assert result.replan is not None
    assert result.replan.claimed == (PrepareResult.ReplanClaim("1.1", "101", "plan-101", 42),)
    assert result.replan.open_pr_plans == (("101", 42),)
    assert service.status_calls == [StatusRequest(objective_id="10")]
    assert persistence.calls == [("get_objective", "10"), ("read_journal", "10")]


def test_replan_prepare_stacked_production_status_reuses_the_objective_snapshot() -> None:
    persistence = FakeDeliveryPersistence(
        objectives={"10": _objective(header={"delivery": "stacked", "delivery_lineage": "lineage"})}
    )
    git = FakeDeliveryGit(base_heads={"main": BaseHeadObservation(sha="a" * 40)})

    result = _delivery(persistence, git).prepare(PrepareRequest(kind="replan", objective_id="10"))

    assert result.replan is not None and result.replan.delivery == "stacked"
    assert persistence.calls.count(("get_objective", "10")) == 1
    assert persistence.calls == [
        ("get_objective", "10"),
        ("read_journal", "10"),
        ("read_journal", "10"),
    ]
    assert git.calls == [
        ("fetch",),
        ("trunk_branch",),
        ("worktree_branches",),
        ("base_head", "main"),
    ]


@pytest.mark.parametrize(
    ("state", "header", "error_type"),
    (
        (None, {}, "objective_not_found"),
        (
            _objective(
                header={},
                nodes=(),
            ),
            {"state": "closed"},
            "objective_not_open",
        ),
        (_objective(header={"superseded_by": "11"}), {}, "objective_not_open"),
        (_objective(header={"delivery": "bogus"}), {}, "invalid_delivery_policy"),
    ),
)
def test_replan_prepare_refuses_missing_closed_superseded_and_junk_policy(
    state: ObjectiveState | None,
    header: dict[str, str],
    error_type: str,
) -> None:
    if state is not None and header.get("state") == "closed":
        state = replace(state, state="closed")
    persistence = FakeDeliveryPersistence(objectives={"10": state} if state is not None else {})
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence).prepare(PrepareRequest(kind="replan", objective_id="10"))
    assert excinfo.value.error_type == error_type


@pytest.mark.parametrize(
    ("kind", "error_type", "message_fragment"),
    (
        (OperationKind.TRANSFER, "transfer_incomplete", "interrupted replan transfer"),
        (OperationKind.SYNC, "unresolved_operation", "(sync) is unresolved"),
    ),
)
def test_replan_prepare_refuses_unresolved_journal_operations(
    kind: OperationKind,
    error_type: str,
    message_fragment: str,
) -> None:
    operation = OperationState(
        operation_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        kind=kind,
        prepared=cast(Any, object()),
        accepted=None,
        outcome=None,
    )
    persistence = FakeDeliveryPersistence(
        objectives={
            "10": _objective(header={"delivery": "stacked", "delivery_lineage": "lineage"})
        },
        journals={
            "10": JournalFold(
                events=(),
                operations={operation.operation_id: operation},
                unresolved=(operation,),
                delivery_lineage="lineage",
            )
        },
    )

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence).prepare(PrepareRequest(kind="replan", objective_id="10"))

    assert excinfo.value.error_type == error_type
    assert message_fragment in str(excinfo.value)
    assert persistence.calls == [("get_objective", "10"), ("read_journal", "10")]


@pytest.mark.parametrize(
    ("train_mutation", "error_type"),
    (
        (
            lambda status: replace(
                status,
                findings=(
                    TrainFinding(
                        FindingKind.BLOCKER,
                        "wrong_owner",
                        "plan ownership does not match",
                    ),
                ),
            ),
            "claimed_prefix_malformed",
        ),
        (
            lambda status: replace(
                status,
                layers=(replace(status.layers[0], parent_checkpoint_sha="a" * 40),),
            ),
            "claimed_prefix_malformed",
        ),
    ),
)
def test_replan_prepare_preserves_structural_and_prefix_refusals(
    train_mutation,
    error_type: str,
) -> None:
    nodes = (ObjectiveNode("1.1", "work", NodeStatus.IN_PROGRESS, pr="#101"),)
    status = _planning_train(
        nodes=nodes,
        layers=(replace(_train_layer("1.1", "101", "plan-101"), pr_number=42),),
        candidate=None,
    )
    status = train_mutation(status)
    persistence = FakeDeliveryPersistence(
        objectives={
            "10": _objective(
                header={"delivery": "stacked", "delivery_lineage": "lineage"},
                nodes=nodes,
            )
        }
    )
    service = _StatusDelivery(
        StatusResult("10", "fake://objective/10", None, status, None),
        persistence=persistence,
    )

    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(PrepareRequest(kind="replan", objective_id="10"))

    assert excinfo.value.error_type == error_type


def test_replan_prepare_translates_journal_persistence_failures() -> None:
    failure = TrainPersistenceError("journal unavailable")
    persistence = FakeDeliveryPersistence(
        objectives={
            "10": _objective(header={"delivery": "stacked", "delivery_lineage": "lineage"})
        },
        errors={("read_journal", "10"): failure},
    )

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence).prepare(PrepareRequest(kind="replan", objective_id="10"))

    assert excinfo.value.error_type == "github_error"
    assert str(excinfo.value) == "journal unavailable"


def test_replan_prepare_maps_journal_corruption_and_missing_train() -> None:
    state = _objective(header={"delivery": "stacked", "delivery_lineage": "lineage"})
    corrupt = FakeDeliveryPersistence(
        objectives={"10": state},
        errors={("read_journal", "10"): JournalCorruptionError("bad event")},
    )
    with pytest.raises(DeliveryError) as corruption:
        _delivery(corrupt).prepare(PrepareRequest(kind="replan", objective_id="10"))
    assert corruption.value.error_type == "journal_corruption"
    assert str(corruption.value) == "bad event"

    persistence = FakeDeliveryPersistence(objectives={"10": state})
    service = _StatusDelivery(
        StatusResult("10", "fake://objective/10", None, None, "missing train"),
        persistence=persistence,
    )
    with pytest.raises(DeliveryError) as missing:
        service.prepare(PrepareRequest(kind="replan", objective_id="10"))
    assert missing.value.error_type == "invalid_train"
    assert "classified stacked but reconstructs no delivery train" in str(missing.value)


def test_publish_request_accepts_the_complete_legal_matrix() -> None:
    valid = (
        PublishRequest(kind="layer", plan_id=" #101 ", dry_run=True),
        PublishRequest(kind="ready", plan_id="101", dry_run=True),
        PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
        PublishRequest(kind="layer", plan_id="101", run_id="01RUN", trigger_run_id="01TRIGGER"),
        PublishRequest(kind="ready", plan_id="101", delivery="incremental"),
        PublishRequest(kind="ready", plan_id="101", delivery="stacked"),
        PublishRequest(kind="ready", plan_id="101", delivery="stacked", objective_id="500"),
    )
    assert tuple(request.kind for request in valid) == (
        "layer",
        "ready",
        "layer",
        "layer",
        "ready",
        "ready",
        "ready",
    )


@pytest.mark.parametrize(
    "build",
    (
        lambda: PublishRequest(kind=cast("Literal['layer']", "future"), plan_id="101"),
        lambda: PublishRequest(kind="layer", plan_id=" ", dry_run=True),
        lambda: PublishRequest(kind="layer", plan_id="#", dry_run=True),
        lambda: PublishRequest(kind="layer", plan_id="##101", dry_run=True),
        lambda: PublishRequest(kind="layer", plan_id="10#1", dry_run=True),
        lambda: PublishRequest(kind="layer", plan_id="101"),
        lambda: PublishRequest(kind="layer", plan_id="101", run_id=" "),
        lambda: PublishRequest(kind="layer", plan_id="101", run_id="01RUN", delivery="stacked"),
        lambda: PublishRequest(kind="layer", plan_id="101", run_id="01RUN", objective_id="500"),
        lambda: PublishRequest(kind="layer", plan_id="101", dry_run=True, run_id="01RUN"),
        lambda: PublishRequest(kind="ready", plan_id="101"),
        lambda: PublishRequest(
            kind="ready", plan_id="101", delivery="incremental", objective_id="500"
        ),
        lambda: PublishRequest(kind="ready", plan_id="101", delivery="stacked", objective_id=" "),
        lambda: PublishRequest(kind="ready", plan_id="101", delivery="stacked", run_id="01RUN"),
    ),
)
def test_publish_request_rejects_every_illegal_shape(build) -> None:
    with pytest.raises(ValueError):
        build()


def _publish_pr(*, existed: bool = True) -> prs.PullRequest:
    return prs.PullRequest(
        number=42,
        url="u/42",
        is_draft=True,
        state="OPEN",
        existed=existed,
        base_ref="main",
        head_ref="plan-101",
    )


def _real_publish_result(*, cascade: SyncResult | None = None) -> PublishResult:
    no_op = cascade.no_op if cascade is not None else False
    operation_id = cascade.operation_id if cascade is not None else "01OP"
    return PublishResult(
        kind="layer",
        plan_id="101",
        dry_run=False,
        layer=PublishResult.Layer(
            pr=_publish_pr(),
            branch="plan-101",
            header_update=PlanHeaderUpdate(
                fields_updated=("branch", "pr", "lifecycle_stage"), dry_run=False
            ),
            plan_embedded=True,
            pr_checked=True,
            parent_branch="main",
            operation_id=operation_id,
            stack_number=None,
            stack_size=None,
            stack_position=None,
            parent_checkpoint_sha="a" * 40,
            published_head_sha="b" * 40,
            resumed=cascade.resumed if cascade is not None else False,
            converged_noop=no_op,
            cascade=cascade,
        ),
    )


def test_publish_result_exact_nested_shapes_are_frozen_and_validated() -> None:
    result = _real_publish_result()
    assert result.layer is not None and result.layer.pr.number == 42
    with pytest.raises(FrozenInstanceError):
        type(result.layer).__setattr__(result.layer, "branch", "changed")

    for invalid_plan_id in ("#101", " 101 ", "10#1"):
        with pytest.raises(ValueError, match="canonical bare"):
            PublishResult(
                kind="ready",
                plan_id=invalid_plan_id,
                dry_run=False,
                ready=PublishResult.Ready(pr=_publish_pr(), was_draft=True),
            )


def _real_publish_layer() -> PublishResult.Layer:
    layer = _real_publish_result().layer
    assert layer is not None
    return layer


def _publish_sync(
    *, operation_id: str | None = "01SYNC", no_op: bool = False, resumed: bool = True
) -> SyncResult:
    return SyncResult(
        objective_id="10",
        objective_url="fake://objective/10",
        redirected_from=None,
        operation_id=operation_id,
        abandoned_operation_id=None,
        no_op=no_op,
        declined=False,
        resumed=resumed,
        base_cascaded=False,
        base_advanced=False,
        affected=(),
    )


def _cascade_publish_layer() -> PublishResult.Layer:
    cascade = _publish_sync()
    return replace(
        _real_publish_layer(),
        operation_id=cascade.operation_id,
        resumed=cascade.resumed,
        converged_noop=cascade.no_op,
        cascade=cascade,
    )


@pytest.mark.parametrize(
    ("build", "message"),
    (
        (
            lambda: PublishResult(
                kind=cast("Literal['layer']", "future"),
                plan_id="101",
                dry_run=False,
                layer=_real_publish_layer(),
            ),
            "unknown publish result kind",
        ),
        (
            lambda: PublishResult(kind="layer", plan_id="101", dry_run=False),
            "detail must match",
        ),
        (
            lambda: PublishResult(
                kind="ready",
                plan_id="101",
                dry_run=False,
                layer=_real_publish_layer(),
                ready=PublishResult.Ready(pr=_publish_pr(), was_draft=True),
            ),
            "detail must match",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(
                    _real_publish_layer(), stack_number=1, stack_size=None, stack_position=1
                ),
            ),
            "stack facts",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(
                    _real_publish_layer(), stack_number=1, stack_size=1, stack_position=2
                ),
            ),
            "position must be within",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=True,
                layer=_real_publish_layer(),
            ),
            "invalid dry-run layer",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(_real_publish_layer(), parent_checkpoint_sha=None),
            ),
            "invalid real layer",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(_real_publish_layer(), operation_id=None, converged_noop=False),
            ),
            "operation id must be absent exactly",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(_real_publish_layer(), operation_id="01OP", converged_noop=True),
            ),
            "operation id must be absent exactly",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(
                    _cascade_publish_layer(), stack_number=1, stack_size=1, stack_position=1
                ),
            ),
            "cascade publish result carries no stack triple",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(_cascade_publish_layer(), operation_id="01DIFFERENT"),
            ),
            "cascade publish fields must mirror",
        ),
        (
            lambda: PublishResult(
                kind="layer",
                plan_id="101",
                dry_run=False,
                layer=replace(
                    _real_publish_layer(),
                    operation_id=None,
                    resumed=False,
                    converged_noop=False,
                    cascade=_publish_sync(operation_id=None, no_op=False, resumed=False),
                ),
            ),
            "cascade publish fields must mirror",
        ),
        (
            lambda: PublishResult(
                kind="ready",
                plan_id="101",
                dry_run=True,
                ready=PublishResult.Ready(pr=_publish_pr(), was_draft=False),
            ),
            "invalid dry-run ready",
        ),
    ),
)
def test_publish_result_rejects_every_invalid_shape(build, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build()


def test_publish_dry_runs_are_exact_and_call_no_authority() -> None:
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()
    service = _delivery(persistence, git, github)

    layer = service.publish(PublishRequest(kind="layer", plan_id=" #101 ", dry_run=True))
    ready = service.publish(PublishRequest(kind="ready", plan_id="101", dry_run=True))

    assert layer == PublishResult(
        kind="layer",
        plan_id="101",
        dry_run=True,
        layer=PublishResult.Layer(
            pr=prs.PullRequest(0, "(dry-run)", True, "OPEN", False),
            branch="plan-101",
            header_update=PlanHeaderUpdate(
                fields_updated=("branch", "pr", "lifecycle_stage"), dry_run=True
            ),
            plan_embedded=False,
            pr_checked=False,
            parent_branch="",
            operation_id=None,
            stack_number=None,
            stack_size=None,
            stack_position=None,
            parent_checkpoint_sha=None,
            published_head_sha=None,
            resumed=False,
            converged_noop=False,
        ),
    )
    assert ready == PublishResult(
        kind="ready",
        plan_id="101",
        dry_run=True,
        ready=PublishResult.Ready(
            pr=prs.PullRequest(0, "(dry-run)", True, "OPEN", True), was_draft=True
        ),
    )
    assert persistence.calls == [] and git.calls == [] and github.calls == []


def test_stacked_ready_without_objective_is_typed_and_mutation_free() -> None:
    github = FakeDeliveryGitHub()
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(github=github).publish(
            PublishRequest(kind="ready", plan_id="101", delivery="stacked")
        )
    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == (
        "not_stacked",
        "ready",
        "domain",
    )
    assert github.calls == []


def test_stacked_ready_without_train_is_typed_and_mutation_free() -> None:
    github = FakeDeliveryGitHub()
    service = _StatusDelivery(
        StatusResult(
            objective_id="10",
            objective_url="fake://objective/10",
            redirected_from=None,
            train=None,
            no_train_reason="objective is incremental",
        ),
        github=github,
    )
    with pytest.raises(DeliveryError) as excinfo:
        service.publish(
            PublishRequest(kind="ready", plan_id="101", delivery="stacked", objective_id="10")
        )
    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == (
        "not_stacked",
        "ready",
        "domain",
    )
    assert github.calls == []


def test_stacked_ready_without_staged_pr_is_typed_and_mutation_free() -> None:
    github = FakeDeliveryGitHub()
    train = _planning_train(
        nodes=(),
        layers=(_train_layer("1.1", "101", "plan-101"),),
        candidate="1.1",
    )
    service = _StatusDelivery(
        StatusResult(
            objective_id="10",
            objective_url="fake://objective/10",
            redirected_from=None,
            train=train,
            no_train_reason=None,
        ),
        github=github,
    )
    with pytest.raises(DeliveryError) as excinfo:
        service.publish(
            PublishRequest(kind="ready", plan_id="101", delivery="stacked", objective_id="10")
        )
    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == (
        "no_pr",
        "ready",
        "domain",
    )
    assert github.calls == []


@pytest.mark.parametrize("backend", ["github", "linear"])
def test_resolved_publish_dry_runs_ignore_committed_backend_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    config = tmp_path / ".perk" / "config.toml"
    config.parent.mkdir()
    team = '\nteam = "ENG"' if backend == "linear" else ""
    config.write_text(f'[issues]\nbackend = "{backend}"{team}\n', encoding="utf-8")
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    calls: list[str] = []

    def unexpected(name: str):
        def fail(*_args: object, **_kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"dry-run reached {name}")

        return fail

    monkeypatch.setattr(observe, "resolve_objective_store", unexpected("objective resolver"))
    monkeypatch.setattr(observe, "resolve_issue_backend", unexpected("issue resolver"))
    monkeypatch.setattr(config_mod, "load_committed_issues_backend", unexpected("backend config"))
    monkeypatch.setattr(observe.git_mod, "fetch_refspecs", unexpected("git fetch"))
    monkeypatch.setattr(observe.prs, "find_pr_for_branch", unexpected("GitHub PR read"))
    monkeypatch.setattr(observe.prs, "merge_pr", unexpected("GitHub merge"))

    service = observe.resolve_delivery(tmp_path)
    service.publish(PublishRequest(kind="layer", plan_id="#101", dry_run=True))
    service.publish(PublishRequest(kind="ready", plan_id="101", dry_run=True))
    service.land(
        LandRequest(
            kind="plan",
            plan_id="101",
            branch="plan-101",
            objective_id=None,
            consumed_learn=(),
            delivery_lineage=None,
            dry_run=True,
        )
    )

    assert calls == []


def test_delivery_publish_builds_one_bound_context_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import publish as publish_mod

    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit(repo_root=Path("/bound-repo"))
    github = FakeDeliveryGitHub()
    service = Delivery(persistence=persistence, git=git, github=github)
    request = PublishRequest(kind="layer", plan_id="101", run_id="01RUN")
    expected = _real_publish_result()
    captured: list[tuple[Any, PublishRequest, object]] = []

    def dispatch(context, actual_request, *, runtime):
        captured.append((context, actual_request, runtime))
        return expected

    monkeypatch.setattr(publish_mod, "_dispatch", dispatch)
    assert service.publish(request) is expected
    ((context, actual_request, runtime),) = captured
    assert context.repo_root == Path("/bound-repo")
    assert context.persistence is persistence and context.git is git and context.github is github
    assert context.status.__self__ is service and context.sync.__self__ is service
    assert actual_request is request and runtime is publish_mod._DEFAULT_PUBLISH_RUNTIME


def test_contextual_delivery_error_requires_joint_valid_metadata() -> None:
    contextual = DeliveryError(
        "failed", error_type="delivery_error", phase="layer", origin="delivery"
    )
    assert (contextual.phase, contextual.origin) == ("layer", "delivery")
    with pytest.raises(ValueError, match="jointly present"):
        DeliveryError("failed", error_type="delivery_error", phase="layer")


@pytest.mark.parametrize(
    ("publish_request", "source", "expected"),
    (
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            publish_mod.PublicationError("domain failed", error_type="publication_drift"),
            ("publication_drift", "layer", "domain"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            DeliveryError("status failed", error_type="invalid_train"),
            ("delivery_error", "layer", "delivery"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            git_mod.PushRejectedError("push rejected"),
            ("push_rejected", "layer", "git"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            git_mod.GitError("git failed"),
            ("git_error", "layer", "git"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            GitHubError("github failed"),
            ("github_error", "layer", "github"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            IssueBackendError("issues failed"),
            ("github_error", "layer", "github"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            TrainPersistenceError("persistence failed"),
            ("delivery_error", "layer", "delivery"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            JournalCorruptionError("journal failed"),
            ("delivery_error", "layer", "delivery"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            TrainReconstructionError("train failed", error_type="invalid_train"),
            ("delivery_error", "layer", "delivery"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            JournalRecordTooLarge("record failed"),
            ("journal_record_too_large", "layer", "delivery"),
        ),
        (
            PublishRequest(kind="layer", plan_id="101", run_id="01RUN"),
            ObjectiveStoreError("objective failed"),
            ("delivery_error", "layer", "delivery"),
        ),
        (
            PublishRequest(kind="ready", plan_id="101", delivery="incremental"),
            LayerError("no PR", error_type="no_pr"),
            ("no_pr", "ready", "domain"),
        ),
        (
            PublishRequest(kind="ready", plan_id="101", delivery="incremental"),
            GitHubError("github failed"),
            ("github_error", "ready", "github"),
        ),
        (
            PublishRequest(kind="ready", plan_id="101", delivery="incremental"),
            IssueBackendError("issues failed"),
            ("github_error", "ready", "github"),
        ),
        (
            PublishRequest(kind="ready", plan_id="101", delivery="incremental"),
            ObjectiveStoreError("objective failed"),
            ("github_error", "ready", "github"),
        ),
        (
            PublishRequest(kind="ready", plan_id="101", delivery="incremental"),
            TrainPersistenceError("persistence failed"),
            ("github_error", "ready", "github"),
        ),
        (
            PublishRequest(kind="ready", plan_id="101", delivery="incremental"),
            JournalCorruptionError("journal failed"),
            ("github_error", "ready", "github"),
        ),
    ),
)
def test_delivery_publish_maps_declared_infrastructure_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    publish_request: PublishRequest,
    source: Exception,
    expected: tuple[str, str, str],
) -> None:
    from perk.delivery import publish as publish_mod

    def dispatch(context, actual_request, *, runtime):
        raise source

    monkeypatch.setattr(publish_mod, "_dispatch", dispatch)
    with pytest.raises(DeliveryError) as excinfo:
        _delivery().publish(publish_request)
    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == expected
    assert str(excinfo.value) == str(source)


@pytest.mark.parametrize(
    ("cause", "expected", "message"),
    (
        (
            TrainReconstructionError("train cause", error_type="invalid_train"),
            ("invalid_train", "ready", "domain"),
            "train cause",
        ),
        (
            IssueBackendError("issue cause"),
            ("github_error", "ready", "github"),
            "status wrapper",
        ),
        (
            ObjectiveStoreError("objective cause"),
            ("github_error", "ready", "github"),
            "status wrapper",
        ),
        (
            TrainPersistenceError("persistence cause"),
            ("github_error", "ready", "github"),
            "status wrapper",
        ),
    ),
)
def test_delivery_publish_maps_ready_status_error_causes(
    monkeypatch: pytest.MonkeyPatch,
    cause: Exception,
    expected: tuple[str, str, str],
    message: str,
) -> None:
    try:
        raise cause
    except Exception as caught:
        try:
            raise DeliveryError("status wrapper", error_type="github_error") from caught
        except DeliveryError as wrapped:
            source = wrapped

    def dispatch(context, request, *, runtime):
        raise source

    monkeypatch.setattr(publish_mod, "_dispatch", dispatch)
    with pytest.raises(DeliveryError) as excinfo:
        _delivery().publish(PublishRequest(kind="ready", plan_id="101", delivery="stacked"))
    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == expected
    assert str(excinfo.value) == message


def test_delivery_publish_preserves_contextual_errors_and_propagates_programmer_bugs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import publish as publish_mod

    contextual = DeliveryError(
        "cascade failed", error_type="remote_drift", phase="cascade", origin="delivery"
    )

    def contextual_failure(context, request, *, runtime):
        raise contextual

    monkeypatch.setattr(publish_mod, "_dispatch", contextual_failure)
    with pytest.raises(DeliveryError) as excinfo:
        _delivery().publish(PublishRequest(kind="layer", plan_id="101", run_id="01RUN"))
    assert excinfo.value is contextual

    unexpected = RuntimeError("programmer bug")

    def explode(context, request, *, runtime):
        raise unexpected

    monkeypatch.setattr(publish_mod, "_dispatch", explode)
    with pytest.raises(RuntimeError) as raw:
        _delivery().publish(PublishRequest(kind="ready", plan_id="101", delivery="stacked"))
    assert raw.value is unexpected


def test_sync_request_accepts_the_complete_legal_matrix() -> None:
    valid = (
        SyncRequest(mode="cascade", objective_id="10", run_id="01RUN"),
        SyncRequest(mode="cascade", objective_id="10", run_id="01RUN", include_base=True),
        SyncRequest(
            mode="cascade", objective_id="10", run_id="01RUN", include_base=True, dry_run=True
        ),
        SyncRequest(
            mode="cascade", objective_id="10", run_id="01RUN", dry_run=True, adopt_node="1.2"
        ),
        SyncRequest(
            mode="cascade",
            objective_id="10",
            run_id="01JOURNAL",
            dry_run=True,
            trigger_plan_id="101",
            trigger_run_id="01TRIGGER",
        ),
        SyncRequest(mode="continue", objective_id="10"),
        SyncRequest(mode="abort", objective_id="10"),
    )

    assert tuple(request.mode for request in valid) == (
        "cascade",
        "cascade",
        "cascade",
        "cascade",
        "cascade",
        "continue",
        "abort",
    )


@pytest.mark.parametrize(
    "build",
    (
        lambda: SyncRequest(mode=cast("Literal['cascade']", "future"), objective_id="10"),
        lambda: SyncRequest(mode="cascade", objective_id=" ", run_id="01RUN"),
        lambda: SyncRequest(mode="cascade", objective_id="10"),
        lambda: SyncRequest(mode="cascade", objective_id="10", run_id=" "),
        lambda: SyncRequest(
            mode="cascade", objective_id="10", run_id="01RUN", include_base=True, adopt_node="1"
        ),
        lambda: SyncRequest(
            mode="cascade",
            objective_id="10",
            run_id="01RUN",
            include_base=True,
            trigger_plan_id="101",
        ),
        lambda: SyncRequest(
            mode="cascade",
            objective_id="10",
            run_id="01RUN",
            trigger_run_id="01TRIGGER",
        ),
        lambda: SyncRequest(mode="continue", objective_id="10", run_id="01RUN"),
        lambda: SyncRequest(mode="continue", objective_id="10", dry_run=True),
        lambda: SyncRequest(mode="abort", objective_id="10", adopt_node="1.2"),
        lambda: SyncRequest(mode="abort", objective_id="10", trigger_plan_id="101"),
    ),
)
def test_sync_request_rejects_every_illegal_shape(build) -> None:
    with pytest.raises(ValueError):
        build()


def test_sync_result_nested_records_are_frozen_data_without_combination_guards() -> None:
    layer = SyncResult.Layer("1.1", "101", "plan-101", 42, "a", "b")
    cascade = SyncResult.Cascade("10", "main", False, None, None, (layer,))
    abort = SyncResult.AbortPreview(Path("manifest.json"), True, True, "01OP", "1.1", "/wt")
    result = SyncResult(
        objective_id="10",
        objective_url="fake://objective/10",
        redirected_from=None,
        operation_id=None,
        abandoned_operation_id="01OLD",
        no_op=True,
        declined=True,
        resumed=True,
        base_cascaded=True,
        base_advanced=True,
        affected=(layer,),
        dry_run=True,
        adopted_node="1.1",
        continued=True,
        aborted=True,
        notes=("residue",),
    )

    assert cascade.layers == (layer,)
    assert abort.operation_id == "01OP"
    assert result.affected == (layer,)
    assert SyncResult.Layer.__qualname__ == "SyncResult.Layer"
    with pytest.raises(FrozenInstanceError):
        type(layer).__setattr__(layer, "node_id", "changed")


def _sync_result() -> SyncResult:
    return SyncResult(
        objective_id="10",
        objective_url="fake://objective/10",
        redirected_from=None,
        operation_id=None,
        abandoned_operation_id=None,
        no_op=True,
        declined=False,
        resumed=False,
        base_cascaded=False,
        base_advanced=False,
        affected=(),
    )


@pytest.mark.parametrize("mode", ("cascade", "continue", "abort"))
def test_delivery_sync_builds_one_authority_context_and_dispatches(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from perk.delivery import sync as sync_mod

    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit(repo_root=Path("/bound-repo"))
    github = FakeDeliveryGitHub()
    delivery = Delivery(persistence=persistence, git=git, github=github)
    request = (
        SyncRequest(mode="cascade", objective_id="10", run_id="01RUN")
        if mode == "cascade"
        else SyncRequest(mode=cast("Literal['continue', 'abort']", mode), objective_id="10")
    )

    def consent(preview) -> bool:
        return True

    captured: list[tuple[Any, SyncRequest, object]] = []

    def dispatch(context, actual_request, *, consent):
        captured.append((context, actual_request, consent))
        return _sync_result()

    monkeypatch.setattr(sync_mod, "_dispatch", dispatch)

    assert delivery.sync(request, consent=consent) == _sync_result()
    ((context, actual_request, actual_consent),) = captured
    assert context.repo_root == Path("/bound-repo")
    assert context.persistence is persistence and context.git is git and context.github is github
    assert context.status.__self__ is delivery
    assert context.runtime is sync_mod._DEFAULT_SYNC_RUNTIME
    assert actual_request is request and actual_consent is consent


def test_delivery_sync_requires_an_explicit_consent_policy() -> None:
    consent = inspect.signature(Delivery.sync).parameters["consent"]
    assert consent.kind is inspect.Parameter.KEYWORD_ONLY
    assert consent.default is inspect.Parameter.empty


@pytest.mark.parametrize(
    ("source", "error_type"),
    (
        (git_mod.GitError("git failed"), "git_error"),
        (GitHubError("github failed"), "github_error"),
        (TrainReconstructionError("bad train", error_type="invalid_train"), "invalid_train"),
        (JournalCorruptionError("bad journal"), "journal_corruption"),
        (JournalRecordTooLarge("10001 exceeds cap 10000"), "journal_record_too_large"),
        (IssueBackendError("issues failed"), "github_error"),
        (ObjectiveStoreError("objectives failed"), "github_error"),
        (TrainPersistenceError("persistence failed"), "github_error"),
    ),
)
def test_delivery_sync_maps_expected_boundary_failures(
    monkeypatch: pytest.MonkeyPatch, source: Exception, error_type: str
) -> None:
    from perk.delivery import sync as sync_mod

    def dispatch(context, request, *, consent):
        raise source

    monkeypatch.setattr(sync_mod, "_dispatch", dispatch)

    with pytest.raises(DeliveryError) as excinfo:
        _delivery().sync(
            SyncRequest(mode="cascade", objective_id="10", run_id="01RUN"), consent=None
        )

    assert excinfo.value.error_type == error_type
    assert str(excinfo.value) == str(source)


def test_delivery_sync_maps_private_config_failure_and_propagates_unexpected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import sync as sync_mod

    def invalid_config(context, request, *, consent):
        raise sync_mod.SyncConfigurationError("could not load worktree configuration: bad")

    monkeypatch.setattr(sync_mod, "_dispatch", invalid_config)
    with pytest.raises(DeliveryError) as excinfo:
        _delivery().sync(
            SyncRequest(mode="cascade", objective_id="10", run_id="01RUN"), consent=None
        )
    assert excinfo.value.error_type == "invalid_config"

    unexpected = RuntimeError("programmer bug")

    def explode(context, request, *, consent):
        raise unexpected

    monkeypatch.setattr(sync_mod, "_dispatch", explode)
    with pytest.raises(RuntimeError) as raw:
        _delivery().sync(
            SyncRequest(mode="cascade", objective_id="10", run_id="01RUN"), consent=None
        )
    assert raw.value is unexpected


def test_recover_request_accepts_the_complete_closed_matrix() -> None:
    valid = (
        RecoverRequest(kind="operation_conclusion", objective_id="10"),
        RecoverRequest(kind="operation_conclusion", objective_id="10", dry_run=True),
        RecoverRequest(kind="operation_conclusion", objective_id="10", action="abandon"),
        RecoverRequest(kind="operation_conclusion", objective_id="10", action="accept_prefix"),
        RecoverRequest(kind="operation_conclusion", objective_id="10", operation_id=""),
        RecoverRequest(kind="cancellation_metadata", objective_id="10"),
        RecoverRequest(kind="cancellation_metadata", objective_id="10", dry_run=True),
    )

    assert tuple(request.action for request in valid) == (
        "report",
        "report",
        "abandon",
        "accept_prefix",
        "report",
        "report",
        "report",
    )
    assert valid[4].operation_id == ""
    assert valid[-1].dry_run is True and valid[-1].operation_id is None


@pytest.mark.parametrize(
    "build",
    (
        lambda: RecoverRequest(
            kind=cast("Literal['operation_conclusion']", "future"), objective_id="10"
        ),
        lambda: RecoverRequest(
            kind="operation_conclusion",
            objective_id="10",
            action=cast("Literal['report']", "future"),
        ),
        lambda: RecoverRequest(kind="operation_conclusion", objective_id=" "),
        lambda: RecoverRequest(
            kind="operation_conclusion", objective_id="10", action="abandon", dry_run=True
        ),
        lambda: RecoverRequest(
            kind="operation_conclusion",
            objective_id="10",
            action="accept_prefix",
            dry_run=True,
        ),
        lambda: RecoverRequest(kind="cancellation_metadata", objective_id=" "),
        lambda: RecoverRequest(kind="cancellation_metadata", objective_id="10", action="abandon"),
        lambda: RecoverRequest(
            kind="cancellation_metadata", objective_id="10", action="accept_prefix"
        ),
        lambda: RecoverRequest(
            kind="cancellation_metadata", objective_id="10", operation_id="01OP"
        ),
        lambda: RecoverRequest(kind="cancellation_metadata", objective_id="10", operation_id=""),
    ),
)
def test_recover_request_rejects_every_illegal_shape(build) -> None:
    with pytest.raises(ValueError):
        build()


def _recover_result() -> RecoverResult:
    return RecoverResult(
        kind="operation_conclusion",
        operation_conclusion=RecoverResult.OperationConclusion(
            objective_id="10",
            objective_url="fake://objective/10",
            redirected_from=None,
            dry_run=False,
            selection_required=False,
            operations=(),
            swept_worktrees=(),
            swept_refs=(),
            sweep_failures=(),
            sweep_skipped=None,
        ),
    )


def test_recover_result_nested_records_are_frozen_without_combination_guards() -> None:
    merged = RecoverResult.MergedPrefix("1.1", 42, "a" * 40)
    remainder = RecoverResult.RemainderPr(43, "OPEN", "b" * 40)
    landed = RecoverResult.LandedLayer("1.1", "101", 42, "a" * 40, "b", "c", None)
    operation = RecoverResult.Operation(
        "01OP",
        "land",
        "2026-01-01T00:00:00Z",
        "mixed",
        "accepted_prefix",
        "intentionally additive",
        (merged,),
        (remainder,),
    )
    failure = RecoverResult.SweepFailure("ref", "failed")
    abandon = RecoverResult.AbandonPreview("01OP", "sync", "created", "detail")
    accept = RecoverResult.AcceptPrefixPreview("01OP", "created", (merged,), (remainder,), "d")
    conclusion = RecoverResult.OperationConclusion(
        objective_id="10",
        objective_url="u",
        redirected_from="9",
        dry_run=True,
        selection_required=True,
        operations=(operation,),
        swept_worktrees=("wt",),
        swept_refs=("ref",),
        sweep_failures=(failure,),
        sweep_skipped="skip",
        landed_layers=(landed,),
        objective_closed=True,
        notes=("note",),
    )
    result = RecoverResult(kind="operation_conclusion", operation_conclusion=conclusion)

    assert result.operation_conclusion is conclusion
    assert conclusion.operations == (operation,)
    assert accept.merged_layers == (merged,) and abandon.kind == "sync"
    assert RecoverResult.Operation.__qualname__ == "RecoverResult.Operation"
    with pytest.raises(FrozenInstanceError):
        type(operation).__setattr__(operation, "action", "reported")
    with pytest.raises(FrozenInstanceError):
        type(conclusion).__setattr__(conclusion, "objective_closed", False)


def test_recover_result_is_a_strict_two_variant_wrapper() -> None:
    conclusion = _recover_result().operation_conclusion
    assert conclusion is not None
    action = RecoverResult.CancellationAction(
        code="canceled_unpublished_projected", node_id="1.3", outcome="applied"
    )
    detail = RecoverResult.CancellationMetadata(
        objective_id="10",
        actions=(action,),
        failed=None,
        aborted=False,
        dry_run=False,
        unavailable=None,
    )
    cancellation = RecoverResult(kind="cancellation_metadata", cancellation_metadata=detail)

    assert cancellation.cancellation_metadata is detail
    assert cancellation.operation_conclusion is None
    assert action.error is None
    # The nested cancellation records are frozen data.
    with pytest.raises(FrozenInstanceError):
        type(action).__setattr__(action, "outcome", "failed")
    with pytest.raises(FrozenInstanceError):
        type(detail).__setattr__(detail, "aborted", True)
    # No old top-level forwarding fields survive on the wrapper.
    wrapper_fields = {f.name for f in fields(RecoverResult)}
    assert wrapper_fields == {"kind", "operation_conclusion", "cancellation_metadata"}
    # Exactly the detail matching kind: every cross-variant/empty combination is rejected.
    for build in (
        lambda: RecoverResult(kind="operation_conclusion"),
        lambda: RecoverResult(kind="cancellation_metadata"),
        lambda: RecoverResult(kind="operation_conclusion", cancellation_metadata=detail),
        lambda: RecoverResult(kind="cancellation_metadata", operation_conclusion=conclusion),
        lambda: RecoverResult(
            kind="operation_conclusion",
            operation_conclusion=conclusion,
            cancellation_metadata=detail,
        ),
        lambda: RecoverResult(
            kind=cast("Literal['operation_conclusion']", "future"),
            operation_conclusion=conclusion,
        ),
    ):
        with pytest.raises(ValueError):
            build()


def test_delivery_recover_binds_the_same_authorities_and_one_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import recover as recover_mod

    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit(repo_root=Path("/bound-repo"))
    github = FakeDeliveryGitHub()
    delivery = Delivery(persistence=persistence, git=git, github=github)
    request = RecoverRequest(kind="operation_conclusion", objective_id="10")
    captured: list[tuple[Any, RecoverRequest, object]] = []

    def consent(preview) -> bool:
        return True

    def dispatch(context, actual_request, *, consent):
        captured.append((context, actual_request, consent))
        return _recover_result()

    monkeypatch.setattr(recover_mod, "_dispatch", dispatch)

    assert delivery.recover(request, consent=consent) == _recover_result()
    ((context, actual_request, actual_consent),) = captured
    assert context.repo_root == Path("/bound-repo")
    assert context.persistence is persistence and context.git is git and context.github is github
    assert context.reconstruct.__self__ is delivery
    assert context.runtime is recover_mod._DEFAULT_RECOVER_RUNTIME
    assert actual_request is request and actual_consent is consent

    captured.clear()
    assert delivery.recover(request) == _recover_result()
    assert captured[0][2] is None
    parameter = inspect.signature(Delivery.recover).parameters["consent"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None


def test_recover_resolves_config_before_one_lock_held_through_consent_and_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from perk.delivery import recover as recover_mod
    from perk.delivery import sync as sync_mod

    events: list[str] = []
    held = False

    def worktree_root(repo_root: Path) -> Path:
        assert repo_root == Path("/bound-repo") and held is False
        events.append("config")
        return Path("/worktrees")

    @contextmanager
    def operation_lock(repo_root: Path):
        nonlocal held
        assert repo_root == Path("/bound-repo") and held is False
        held = True
        events.append("lock-enter")
        try:
            yield
        finally:
            events.append("lock-exit")
            held = False

    def core(context, seams, request, *, worktree_root, consent):
        assert held is True and worktree_root == Path("/worktrees")
        assert seams.context is context
        events.append("core")
        assert consent is not None
        assert consent(
            RecoverResult.AbandonPreview("01OP", "sync", "2026-01-01T00:00:00Z", "proof")
        )
        events.append("sweep")
        return _recover_result()

    def consent(preview: RecoverResult.AbandonPreview | RecoverResult.AcceptPrefixPreview) -> bool:
        assert held is True and isinstance(preview, RecoverResult.AbandonPreview)
        events.append("consent")
        return True

    runtime = replace(
        recover_mod._DEFAULT_RECOVER_RUNTIME,
        worktree_root=worktree_root,
        operation_lock=operation_lock,
    )
    monkeypatch.setattr(recover_mod, "_DEFAULT_RECOVER_RUNTIME", runtime)
    monkeypatch.setattr(recover_mod, "_recover", core)
    delivery = Delivery(
        persistence=FakeDeliveryPersistence(),
        git=FakeDeliveryGit(repo_root=Path("/bound-repo")),
        github=FakeDeliveryGitHub(),
    )

    assert (
        delivery.recover(
            RecoverRequest(kind="operation_conclusion", objective_id="10", action="abandon"),
            consent=consent,
        )
        == _recover_result()
    )
    assert events == ["config", "lock-enter", "core", "consent", "sweep", "lock-exit"]

    events.clear()

    def bad_config(repo_root: Path) -> Path:
        events.append("config-error")
        raise sync_mod.SyncConfigurationError("bad worktree config")

    monkeypatch.setattr(
        recover_mod,
        "_DEFAULT_RECOVER_RUNTIME",
        replace(runtime, worktree_root=bad_config),
    )
    with pytest.raises(DeliveryError) as excinfo:
        delivery.recover(RecoverRequest(kind="operation_conclusion", objective_id="10"))
    assert excinfo.value.error_type == "invalid_config"
    assert events == ["config-error"]


def test_recover_preserves_operation_lock_busy_raised_after_lock_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from perk.delivery import oplock
    from perk.delivery import recover as recover_mod

    entered = False
    failure = oplock.OperationLockBusy("operation body reported lock contention")

    @contextmanager
    def operation_lock(repo_root: Path):
        nonlocal entered
        assert repo_root == Path("/bound-repo")
        entered = True
        try:
            yield
        finally:
            entered = False

    def core(context, seams, request, *, worktree_root, consent):
        assert entered is True
        raise failure

    monkeypatch.setattr(
        recover_mod,
        "_DEFAULT_RECOVER_RUNTIME",
        replace(
            recover_mod._DEFAULT_RECOVER_RUNTIME,
            worktree_root=lambda repo_root: Path("/worktrees"),
            operation_lock=operation_lock,
        ),
    )
    monkeypatch.setattr(recover_mod, "_recover", core)
    delivery = Delivery(
        persistence=FakeDeliveryPersistence(),
        git=FakeDeliveryGit(repo_root=Path("/bound-repo")),
        github=FakeDeliveryGitHub(),
    )

    with pytest.raises(oplock.OperationLockBusy) as excinfo:
        delivery.recover(RecoverRequest(kind="operation_conclusion", objective_id="10"))
    assert excinfo.value is failure
    assert entered is False


@pytest.mark.parametrize(
    ("source", "error_type"),
    (
        (git_mod.GitError("git failed"), "git_error"),
        (GitHubError("github failed"), "github_error"),
        (TrainReconstructionError("bad train", error_type="invalid_train"), "invalid_train"),
        (JournalCorruptionError("bad journal"), "journal_corruption"),
        (JournalRecordTooLarge("10001 exceeds cap 10000"), "journal_record_too_large"),
        (IssueBackendError("issues failed"), "github_error"),
        (ObjectiveStoreError("objectives failed"), "github_error"),
        (TrainPersistenceError("persistence failed"), "github_error"),
    ),
)
def test_delivery_recover_maps_expected_boundary_failures(
    monkeypatch: pytest.MonkeyPatch, source: Exception, error_type: str
) -> None:
    from perk.delivery import recover as recover_mod

    def dispatch(context, request, *, consent):
        raise source

    monkeypatch.setattr(recover_mod, "_dispatch", dispatch)
    with pytest.raises(DeliveryError) as excinfo:
        _delivery().recover(RecoverRequest(kind="operation_conclusion", objective_id="10"))
    assert excinfo.value.error_type == error_type
    assert str(excinfo.value) == str(source)


def test_delivery_recover_preserves_delivery_errors_and_maps_config_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import recover as recover_mod
    from perk.delivery import sync as sync_mod

    existing = DeliveryError("blocked", error_type="accept_blocked")

    def blocked(context, request, *, consent):
        raise existing

    monkeypatch.setattr(recover_mod, "_dispatch", blocked)
    with pytest.raises(DeliveryError) as excinfo:
        _delivery().recover(RecoverRequest(kind="operation_conclusion", objective_id="10"))
    assert excinfo.value is existing

    def invalid_config(context, request, *, consent):
        raise sync_mod.SyncConfigurationError("bad worktree config")

    monkeypatch.setattr(recover_mod, "_dispatch", invalid_config)
    with pytest.raises(DeliveryError) as config_error:
        _delivery().recover(RecoverRequest(kind="operation_conclusion", objective_id="10"))
    assert config_error.value.error_type == "invalid_config"

    unexpected = OSError("unclassified filesystem failure")

    def explode(context, request, *, consent):
        raise unexpected

    monkeypatch.setattr(recover_mod, "_dispatch", explode)
    with pytest.raises(OSError) as raw:
        _delivery().recover(RecoverRequest(kind="operation_conclusion", objective_id="10"))
    assert raw.value is unexpected


def test_recover_cancellation_rejects_consent_before_dispatch_or_authority_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import recover as recover_mod

    dispatched: list[RecoverRequest] = []

    def dispatch(context, request, *, consent):
        dispatched.append(request)
        return _recover_result()

    monkeypatch.setattr(recover_mod, "_dispatch", dispatch)
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()
    delivery = _delivery(persistence, git, github)

    with pytest.raises(ValueError, match="no confirmation boundary"):
        delivery.recover(
            RecoverRequest(kind="cancellation_metadata", objective_id="10"),
            consent=lambda preview: True,
        )
    assert dispatched == []
    assert persistence.calls == [] and git.calls == [] and github.calls == []


def test_recover_cancellation_unsupported_backend_is_an_empty_pass_without_reconstruction() -> None:
    persistence = FakeDeliveryPersistence(
        objectives={"10": _objective(header={"delivery": "stacked", "delivery_lineage": "L"})}
    )
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()

    result = _delivery(persistence, git, github).recover(
        RecoverRequest(kind="cancellation_metadata", objective_id="10", dry_run=True)
    )

    assert result.kind == "cancellation_metadata" and result.operation_conclusion is None
    detail = result.cancellation_metadata
    assert detail == RecoverResult.CancellationMetadata(
        objective_id="10",
        actions=(),
        failed=None,
        aborted=False,
        dry_run=True,
        unavailable=None,
    )
    # The unsupported arm answers before any reconstruction: one capability lookup, no
    # objective/journal/Git/GitHub reads.
    assert persistence.calls == [("native_cancellation_metadata_writer",)]
    assert git.calls == [] and github.calls == []


@pytest.mark.parametrize("dry_run", (False, True))
def test_recover_cancellation_maps_the_repair_pass_through_nested_records(
    monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    from perk.delivery import diagnostics

    persistence = FakeDeliveryPersistence(cancellation_writer_supported=True)
    delivery = _delivery(persistence)
    captured: list[dict[str, Any]] = []
    scripted = diagnostics.CancellationRepairResult(
        actions=(
            diagnostics.CancellationRepairAction(
                code="canceled_unpublished_projected", node_id="1.2", outcome="applied"
            ),
            diagnostics.CancellationRepairAction(
                code="canceled_unpublished_projected",
                node_id="1.3",
                outcome="skipped",
                error="stale",
            ),
        ),
        failed=diagnostics.CancellationRepairAction(
            code="canceled_unpublished_projected",
            node_id="1.4",
            outcome="failed",
            error="post-write drift",
        ),
        aborted=True,
        dry_run=dry_run,
        unavailable="proof gone",
    )

    def repair(objective_id, *, writer, reconstruct, dry_run=False):
        captured.append(
            {
                "objective_id": objective_id,
                "writer": writer,
                "reconstruct": reconstruct,
                "dry_run": dry_run,
            }
        )
        return scripted

    monkeypatch.setattr(diagnostics, "repair_projected_cancellations", repair)

    result = delivery.recover(
        RecoverRequest(kind="cancellation_metadata", objective_id="10", dry_run=dry_run)
    )

    (call,) = captured
    assert call["objective_id"] == "10" and call["dry_run"] is dry_run
    assert call["writer"] is persistence  # the exact capability-returned writer
    detail = result.cancellation_metadata
    assert detail == RecoverResult.CancellationMetadata(
        objective_id="10",
        actions=(
            RecoverResult.CancellationAction(
                code="canceled_unpublished_projected", node_id="1.2", outcome="applied"
            ),
            RecoverResult.CancellationAction(
                code="canceled_unpublished_projected",
                node_id="1.3",
                outcome="skipped",
                error="stale",
            ),
        ),
        failed=RecoverResult.CancellationAction(
            code="canceled_unpublished_projected",
            node_id="1.4",
            outcome="failed",
            error="post-write drift",
        ),
        aborted=True,
        dry_run=dry_run,
        unavailable="proof gone",
    )


def test_recover_cancellation_normalizes_expected_reads_onto_the_unavailable_arm() -> None:
    # An expected store outage inside the fresh proof becomes the diagnostics core's modeled
    # unavailable arm (the retired doctor helper's normalization) — never a new escape path.
    persistence = FakeDeliveryPersistence(
        cancellation_writer_supported=True,
        errors={("get_objective", "10"): ObjectiveStoreError("store down")},
    )

    result = _delivery(persistence).recover(
        RecoverRequest(kind="cancellation_metadata", objective_id="10")
    )

    detail = result.cancellation_metadata
    assert detail is not None
    assert detail.aborted is True and detail.actions == () and detail.failed is None
    assert detail.unavailable is not None and "store down" in detail.unavailable


def test_recover_cancellation_is_isolated_from_operation_conclusion_machinery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import recover as recover_mod

    def forbidden_config(repo_root: Path) -> Path:
        raise AssertionError("cancellation repair must never resolve worktree config")

    def forbidden_lock(repo_root: Path):
        raise AssertionError("cancellation repair must never take the operation lock")

    monkeypatch.setattr(
        recover_mod,
        "_DEFAULT_RECOVER_RUNTIME",
        replace(
            recover_mod._DEFAULT_RECOVER_RUNTIME,
            worktree_root=forbidden_config,
            operation_lock=forbidden_lock,
        ),
    )
    persistence = FakeDeliveryPersistence(
        cancellation_writer_supported=True,
        objectives={
            "10": _objective(header={"delivery": "stacked", "delivery_lineage": "lineage"})
        },
    )
    git = FakeDeliveryGit(base_heads={"main": BaseHeadObservation(sha="a" * 40)})
    github = FakeDeliveryGitHub()
    delivery = _delivery(persistence, git, github)

    result = delivery.recover(RecoverRequest(kind="cancellation_metadata", objective_id="10"))

    detail = result.cancellation_metadata
    assert detail is not None and detail.aborted is False and detail.actions == ()
    # The same persistence authority answered the capability; the reconstruction-driven
    # journal/Git reads are expected and permitted (they ARE the fresh safety proof)…
    assert persistence.calls == [
        ("native_cancellation_metadata_writer",),
        ("get_objective", "10"),
        ("read_journal", "10"),
    ]
    assert ("fetch",) in git.calls
    # …while every operation-conclusion effect stays untouched: no journal mutation, no
    # checkpoints, no close, and no sweep effects.
    effect_names = {
        "append_prepared",
        "append_outcome",
        "write_checkpoints",
        "close_objective",
    }
    assert not [call for call in persistence.calls if call[0] in effect_names]
    sweep_names = {"delete_ref", "remove_worktree", "prune_worktrees"}
    assert not [call for call in git.calls if call[0] in sweep_names]


def test_recover_cancellation_capability_failure_is_bounded_and_unexpected_propagates() -> None:
    bounded = FakeDeliveryPersistence(
        errors={("native_cancellation_metadata_writer",): ObjectiveStoreError("resolve failed")}
    )
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(bounded).recover(RecoverRequest(kind="cancellation_metadata", objective_id="10"))
    assert excinfo.value.error_type == "github_error"
    assert "resolve failed" in str(excinfo.value)

    unexpected = RuntimeError("programmer bug")
    broken = FakeDeliveryPersistence(errors={("native_cancellation_metadata_writer",): unexpected})
    with pytest.raises(RuntimeError) as raw:
        _delivery(broken).recover(RecoverRequest(kind="cancellation_metadata", objective_id="10"))
    assert raw.value is unexpected


def test_persistence_cancellation_writer_capability_defaults_to_none() -> None:
    # The ABC method is a concrete neutral default, not a new abstract requirement…
    assert "native_cancellation_metadata_writer" not in DeliveryPersistence.__abstractmethods__
    fake = FakeDeliveryPersistence(cancellation_writer_supported=True)
    assert DeliveryPersistence.native_cancellation_metadata_writer(fake) is None
    # …and the owned fake's override is constructor-configured posture.
    assert fake.native_cancellation_metadata_writer() is fake
    assert FakeDeliveryPersistence().native_cancellation_metadata_writer() is None


def test_facade_needs_no_runtime_diagnostics_import() -> None:
    # The capability annotation is a quoted TYPE_CHECKING-only forward reference: the
    # façade module's runtime namespace never binds the diagnostics Protocol (importing
    # the façade would NameError otherwise), and the concrete default's return annotation
    # stays the unevaluated string.
    assert "NativeCancellationMetadataWriter" not in vars(facade_mod)
    method = DeliveryPersistence.native_cancellation_metadata_writer
    assert method.__annotations__["return"] == "NativeCancellationMetadataWriter | None"


def test_prepare_request_and_result_validate_the_authoring_discriminator() -> None:
    assert PrepareRequest(kind="authoring", base=None).base is None
    assert PrepareResult(kind="authoring", base="main").base == "main"

    unknown = cast(Literal["authoring"], "future")
    with pytest.raises(ValueError, match=r"^unknown prepare kind: 'future'$"):
        PrepareRequest(kind=unknown, base=None)
    with pytest.raises(ValueError, match=r"^unknown prepare kind: 'future'$"):
        PrepareResult(kind=unknown, base="main")


def test_prepare_request_rejects_illegal_known_variant_shapes() -> None:
    valid = (
        PrepareRequest(kind="authoring", base=None),
        PrepareRequest(kind="replan", objective_id="10"),
        PrepareRequest(kind="plan_identity", mode="strict", objective_id="10", node_id="1.1"),
        PrepareRequest(kind="plan_identity", mode="best_effort", objective_id="10"),
        PrepareRequest(kind="layer_start", mode="planning", objective_id="10"),
        PrepareRequest(kind="layer_start", mode="execution", plan_id="101"),
    )
    assert tuple(request.kind for request in valid) == (
        "authoring",
        "replan",
        "plan_identity",
        "plan_identity",
        "layer_start",
        "layer_start",
    )
    invalid = (
        lambda: PrepareRequest(kind="authoring", base="main", mode="strict"),
        lambda: PrepareRequest(kind="replan", objective_id=" "),
        lambda: PrepareRequest(kind="replan", objective_id="10", base="main"),
        lambda: PrepareRequest(kind="plan_identity", mode="strict", objective_id="10"),
        lambda: PrepareRequest(
            kind="plan_identity", mode="best_effort", objective_id="10", base="main"
        ),
        lambda: PrepareRequest(
            kind="layer_start", mode="planning", objective_id="10", plan_id="101"
        ),
        lambda: PrepareRequest(kind="layer_start", mode="execution", plan_id="101", node_id="1.1"),
    )
    for build in invalid:
        with pytest.raises(ValueError):
            build()


def test_prepare_result_and_nested_decision_shapes_are_pinned() -> None:
    node = PrepareResult.PlanningNode(
        id="1.1", description="First", status=NodeStatus.PENDING, pr=None
    )
    context = PrepareResult.PlanningContext(
        position=1,
        layer_count=2,
        delivery_lineage="lineage",
        base="main",
        predecessor_node_id=None,
        predecessor_plan_id=None,
        parent_branch="main",
        observed_parent_head_sha=None,
    )
    decision = PrepareResult.PlanningDecision(
        kind="ready",
        objective_id="10",
        objective_title="Objective",
        objective_url="u/10",
        requested_node_id=None,
        node=node,
        skipped_claim_ids=(),
        context=context,
    )
    assert (
        PrepareResult(kind="layer_start", mode="planning", planning=decision).planning is decision
    )
    assert PrepareResult(kind="plan_identity", mode="best_effort", notice="").notice == ""
    replan = PrepareResult.ReplanContext(
        objective_id="10",
        objective_url="u/10",
        objective_title="Objective",
        nodes=(ObjectiveNode("1.1", "work", NodeStatus.PENDING),),
        delivery="incremental",
        base=None,
        delivery_lineage=None,
        claimed=(),
        open_pr_plans=(),
    )
    assert PrepareResult(kind="replan", replan=replan).replan is replan

    with pytest.raises(ValueError):
        PrepareResult(kind="authoring", base=None)
    with pytest.raises(ValueError):
        PrepareResult(kind="replan")
    with pytest.raises(ValueError):
        PrepareResult(kind="authoring", base="main", replan=replan)
    with pytest.raises(ValueError):
        PrepareResult(kind="plan_identity", mode="best_effort", base="main", notice="failed")
    with pytest.raises(ValueError):
        PrepareResult.PlanningDecision(
            kind="ready",
            objective_id="10",
            objective_title="Objective",
            objective_url="u/10",
            requested_node_id=None,
            node=node,
            skipped_claim_ids=None,
        )
    with pytest.raises(ValueError):
        PrepareResult.PlanningDecision(
            kind="complete",
            objective_id="10",
            objective_title="Objective",
            objective_url="u/10",
            requested_node_id=None,
            node=node,
        )


def test_prepare_explicit_base_checks_every_push_url_without_persistence() -> None:
    sha = "a" * 40
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit(
        branches={"develop": sha},
        push_urls=("fake://origin", "fake://mirror"),
    )
    github = FakeDeliveryGitHub()

    result = _delivery(persistence, git, github).prepare(
        PrepareRequest(kind="authoring", base="develop")
    )

    assert result == PrepareResult(kind="authoring", base="develop")
    assert persistence.calls == []
    assert github.calls == [("stack_capability",), ("base_merge_rules", "develop")]
    assert git.calls == [
        ("remote_branch_sha", "develop"),
        ("push_urls",),
        ("probe_atomic_push", "fake://origin", "develop", sha),
        ("probe_atomic_push", "fake://mirror", "develop", sha),
    ]


def test_prepare_resolves_trunk_lazily_and_returns_the_effective_base() -> None:
    sha = "a" * 40
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit(trunk="main", branches={"main": sha})
    github = FakeDeliveryGitHub()

    result = _delivery(persistence, git, github).prepare(
        PrepareRequest(kind="authoring", base=None)
    )

    assert result == PrepareResult(kind="authoring", base="main")
    assert persistence.calls == []
    assert git.calls == [
        ("trunk_branch",),
        ("remote_branch_sha", "main"),
        ("push_urls",),
        ("probe_atomic_push", "fake://origin", "main", sha),
    ]
    assert github.calls == [("stack_capability",), ("base_merge_rules", "main")]


@pytest.mark.parametrize(
    ("git", "github", "detail"),
    [
        (
            FakeDeliveryGit(branches={"main": "a" * 40}),
            FakeDeliveryGitHub(stack_capable=False),
            "expected a PullRequest.stack field",
        ),
        (
            FakeDeliveryGit(branches={"main": "a" * 40}),
            FakeDeliveryGitHub(
                merge_rules=DeliveryGitHub.MergeRules(
                    squash_allowed=False, merge_queue_required=False
                )
            ),
            "observed squash merge disallowed",
        ),
        (
            FakeDeliveryGit(branches={"main": "a" * 40}),
            FakeDeliveryGitHub(
                merge_rules=DeliveryGitHub.MergeRules(
                    squash_allowed=True, merge_queue_required=True
                )
            ),
            "merge queue required",
        ),
        (
            FakeDeliveryGit(branches={"main": "a" * 40}),
            FakeDeliveryGitHub(merge_rules_error="HTTP 500"),
            "can't verify ⇒ don't promise): HTTP 500",
        ),
        (
            FakeDeliveryGit(),
            FakeDeliveryGitHub(),
            "observed no such remote branch",
        ),
        (
            FakeDeliveryGit(branches={"main": "a" * 40}, push_urls_error="no remote"),
            FakeDeliveryGitHub(),
            "could not resolve the push URLs for origin: no remote",
        ),
        (
            FakeDeliveryGit(branches={"main": "a" * 40}, push_urls=()),
            FakeDeliveryGitHub(),
            "observed none",
        ),
        (
            FakeDeliveryGit(
                branches={"main": "a" * 40},
                push_urls=("fake://origin", "fake://mirror"),
                atomic_push_errors={"fake://mirror": "atomic unsupported"},
            ),
            FakeDeliveryGitHub(),
            "fake://mirror failed",
        ),
    ],
)
def test_prepare_rejects_each_capability_failure_arm(
    git: FakeDeliveryGit,
    github: FakeDeliveryGitHub,
    detail: str,
) -> None:
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(git=git, github=github).prepare(PrepareRequest(kind="authoring", base="main"))

    assert excinfo.value.error_type == "capability_unsupported"
    assert detail in str(excinfo.value)


def test_prepare_aggregates_independent_failures_and_skips_push_without_a_sha() -> None:
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub(stack_capable=False, merge_rules_error="HTTP 500")

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(git=git, github=github).prepare(PrepareRequest(kind="authoring", base="main"))

    assert excinfo.value.error_type == "capability_unsupported"
    assert str(excinfo.value) == (
        "This repository cannot take a stacked delivery train against base 'main':\n"
        "- native-stack: expected a PullRequest.stack field in the GraphQL schema; observed "
        "none (or introspection failed) — native stacks are unavailable on this GitHub host\n"
        "- merge-rules: could not verify the merge rules for base 'main' "
        "(can't verify ⇒ don't promise): HTTP 500\n"
        "- remote-base: expected refs/heads/main on origin; observed no such remote branch — "
        "a stacked train needs a real remote base to publish against"
    )
    assert github.calls == [("stack_capability",), ("base_merge_rules", "main")]
    assert git.calls == [("remote_branch_sha", "main")]


def test_prepare_aggregates_earlier_failures_and_still_probes_every_push_url() -> None:
    sha = "a" * 40
    git = FakeDeliveryGit(
        branches={"main": sha},
        push_urls=("fake://origin", "fake://mirror", "fake://backup"),
        atomic_push_errors={"fake://mirror": "atomic unsupported"},
    )
    github = FakeDeliveryGitHub(stack_capable=False, merge_rules_error="HTTP 500")

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(git=git, github=github).prepare(PrepareRequest(kind="authoring", base="main"))

    assert excinfo.value.error_type == "capability_unsupported"
    assert str(excinfo.value) == (
        "This repository cannot take a stacked delivery train against base 'main':\n"
        "- native-stack: expected a PullRequest.stack field in the GraphQL schema; observed "
        "none (or introspection failed) — native stacks are unavailable on this GitHub host\n"
        "- merge-rules: could not verify the merge rules for base 'main' "
        "(can't verify ⇒ don't promise): HTTP 500\n"
        "- atomic-push: the no-op --atomic --dry-run push to fake://mirror failed "
        "(proves server capability and authentication, not branch write permission): "
        "atomic unsupported"
    )
    assert github.calls == [("stack_capability",), ("base_merge_rules", "main")]
    assert git.calls == [
        ("remote_branch_sha", "main"),
        ("push_urls",),
        ("probe_atomic_push", "fake://origin", "main", sha),
        ("probe_atomic_push", "fake://mirror", "main", sha),
        ("probe_atomic_push", "fake://backup", "main", sha),
    ]


def test_prepare_remote_git_error_is_a_failed_row_with_raw_detail() -> None:
    failure = TrainReconstructionError("wrapped status detail", error_type="git_error")
    git = FakeDeliveryGit(errors={("remote_branch_sha", "main"): failure})

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(git=git).prepare(PrepareRequest(kind="authoring", base="main"))

    assert excinfo.value.error_type == "capability_unsupported"
    assert str(excinfo.value).endswith(
        "- remote-base: could not observe refs/heads/main on origin "
        "(can't verify ⇒ don't promise): wrapped status detail"
    )
    assert git.calls == [("remote_branch_sha", "main")]


def test_prepare_base_resolution_normalizes_only_git_errors() -> None:
    wrapped = TrainReconstructionError("injected wrapper", error_type="git_error")
    git = FakeDeliveryGit(errors={("trunk_branch",): wrapped})
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(git=git).prepare(PrepareRequest(kind="authoring", base=None))
    assert excinfo.value.error_type == "git_error"
    assert str(excinfo.value) == "injected wrapper"

    unexpected = TrainReconstructionError("future", error_type="future_operation_error")
    git = FakeDeliveryGit(errors={("trunk_branch",): unexpected})
    with pytest.raises(TrainReconstructionError) as unexpected_info:
        _delivery(git=git).prepare(PrepareRequest(kind="authoring", base=None))
    assert unexpected_info.value is unexpected


def test_plan_identity_strict_reads_once_and_returns_base_and_full_trio() -> None:
    nodes = (
        ObjectiveNode(id="1.1", description="Bottom", status=NodeStatus.IN_PROGRESS, pr="#101"),
        ObjectiveNode(
            id="1.2",
            description="Child",
            status=NodeStatus.PLANNING,
            pr=None,
            depends_on=("1.1",),
        ),
    )
    persistence = FakeDeliveryPersistence(
        objectives={
            "10": _objective(
                header={
                    "delivery": "stacked",
                    "delivery_lineage": " lineage ",
                    "base": " release ",
                },
                nodes=nodes,
            )
        }
    )
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()

    result = _delivery(persistence, git, github).prepare(
        PrepareRequest(
            kind="plan_identity",
            mode="strict",
            objective_id="#10",
            node_id="1.2",
        )
    )

    assert result == PrepareResult(
        kind="plan_identity",
        mode="strict",
        base="release",
        identity=PrepareResult.PlanIdentity(
            objective_node_id="1.2",
            delivery_lineage="lineage",
            predecessor_plan_id="101",
        ),
    )
    assert persistence.calls == [("get_objective", "10")]
    assert git.calls == [] and github.calls == []


@pytest.mark.parametrize(
    "source",
    [ObjectiveStoreError(""), IssueBackendError("issue down"), TrainPersistenceError("mismatch")],
)
def test_plan_identity_best_effort_expected_read_failure_returns_exact_notice(
    source: Exception,
) -> None:
    persistence = FakeDeliveryPersistence(errors={("get_objective", "10"): source})
    result = _delivery(persistence).prepare(
        PrepareRequest(kind="plan_identity", mode="best_effort", objective_id="10")
    )
    assert result == PrepareResult(kind="plan_identity", mode="best_effort", notice=str(source))
    assert result.notice is not None


def test_plan_identity_propagates_unexpected_read_failures() -> None:
    failure = RuntimeError("unexpected")
    persistence = FakeDeliveryPersistence(errors={("get_objective", "10"): failure})
    with pytest.raises(RuntimeError) as excinfo:
        _delivery(persistence).prepare(
            PrepareRequest(kind="plan_identity", mode="best_effort", objective_id="10")
        )
    assert excinfo.value is failure


def test_plan_identity_objective_only_returns_base_without_validating_policy() -> None:
    persistence = FakeDeliveryPersistence(
        objectives={"10": _objective(header={"base": " release ", "delivery": "junk"})}
    )
    result = _delivery(persistence).prepare(
        PrepareRequest(kind="plan_identity", mode="best_effort", objective_id="10")
    )
    assert result == PrepareResult(kind="plan_identity", mode="best_effort", base="release")


@pytest.mark.parametrize(
    ("header", "nodes", "node_id", "strict_error"),
    (
        (
            {"delivery": "junk", "base": " release "},
            (ObjectiveNode(id="1.1", description="Layer", status=NodeStatus.PENDING),),
            "1.1",
            "invalid_delivery_policy",
        ),
        (
            {"delivery": "stacked", "base": " release "},
            (ObjectiveNode(id="1.1", description="Layer", status=NodeStatus.PENDING),),
            "1.1",
            "missing_lineage",
        ),
        (
            {"delivery": "stacked", "delivery_lineage": "lineage", "base": " release "},
            (
                ObjectiveNode(
                    id="1.1",
                    description="First",
                    status=NodeStatus.PENDING,
                    depends_on=("1.2",),
                ),
                ObjectiveNode(
                    id="1.2",
                    description="Second",
                    status=NodeStatus.PENDING,
                    depends_on=("1.1",),
                ),
            ),
            "1.1",
            "invalid_train",
        ),
        (
            {"delivery": "stacked", "delivery_lineage": "lineage", "base": " release "},
            (ObjectiveNode(id="1.1", description="Layer", status=NodeStatus.PENDING),),
            "missing",
            "invalid_input",
        ),
        (
            {"delivery": "stacked", "delivery_lineage": "lineage", "base": " release "},
            (ObjectiveNode(id="1.1", description="Skipped", status=NodeStatus.SKIPPED),),
            "1.1",
            "invalid_input",
        ),
    ),
)
def test_plan_identity_strict_refuses_while_best_effort_retains_base(
    header: dict[str, object],
    nodes: tuple[ObjectiveNode, ...],
    node_id: str,
    strict_error: str,
) -> None:
    persistence = FakeDeliveryPersistence(objectives={"10": _objective(header=header, nodes=nodes)})
    service = _delivery(persistence)

    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(
            PrepareRequest(
                kind="plan_identity",
                mode="strict",
                objective_id="10",
                node_id=node_id,
            )
        )
    assert excinfo.value.error_type == strict_error

    assert service.prepare(
        PrepareRequest(
            kind="plan_identity",
            mode="best_effort",
            objective_id="10",
            node_id=node_id,
        )
    ) == PrepareResult(kind="plan_identity", mode="best_effort", base="release")


def test_plan_identity_missing_predecessor_refuses_even_best_effort() -> None:
    nodes = (
        ObjectiveNode(id="1.1", description="Bottom", status=NodeStatus.PENDING),
        ObjectiveNode(id="1.2", description="Child", status=NodeStatus.PENDING),
    )
    persistence = FakeDeliveryPersistence(
        objectives={
            "10": _objective(
                header={"delivery": "stacked", "delivery_lineage": "lineage"},
                nodes=nodes,
            )
        }
    )
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence).prepare(
            PrepareRequest(
                kind="plan_identity",
                mode="best_effort",
                objective_id="10",
                node_id="1.2",
            )
        )
    assert excinfo.value.error_type == "stacked_predecessor_missing"


def test_planning_prepare_uses_one_status_snapshot_and_never_probes_parent() -> None:
    nodes = (
        ObjectiveNode(id="1.1", description="Bottom", status=NodeStatus.IN_PROGRESS, pr="#101"),
        ObjectiveNode(
            id="1.2", description="Captured child", status=NodeStatus.PENDING, depends_on=("1.1",)
        ),
    )
    status = _planning_train(
        nodes=nodes,
        layers=(
            _train_layer("1.1", "101", "plan-101", remote_head="a" * 40),
            _train_layer("1.2", None, None),
        ),
        candidate="1.2",
    )
    git = FakeDeliveryGit()
    service = _StatusDelivery(StatusResult("10", status.objective_url, None, status, None), git=git)

    result = service.prepare(PrepareRequest(kind="layer_start", mode="planning", objective_id="10"))

    decision = result.planning
    assert decision is not None and decision.kind == "ready"
    assert decision.objective_title == "Captured objective"
    assert decision.node is not None and decision.node.description == "Captured child"
    assert decision.context == PrepareResult.PlanningContext(
        position=2,
        layer_count=2,
        delivery_lineage="lineage",
        base="main",
        predecessor_node_id="1.1",
        predecessor_plan_id="101",
        parent_branch="plan-101",
        observed_parent_head_sha="a" * 40,
    )
    assert service.status_calls == [StatusRequest(objective_id="10")]
    assert git.calls == []


def test_planning_candidate_readiness_and_roadmap_membership_vetoes() -> None:
    node = ObjectiveNode(id="1.1", description="Candidate", status=NodeStatus.PENDING)
    blocked = _planning_train(
        nodes=(node,),
        layers=(_train_layer("1.1", None, None),),
        candidate="1.1",
        ready=False,
        reason="[prefix_gap] child published before parent",
    )
    blocked_result = _StatusDelivery(
        StatusResult("10", blocked.objective_url, None, blocked, None)
    ).prepare(PrepareRequest(kind="layer_start", mode="planning", objective_id="10"))
    assert blocked_result.planning == PrepareResult.PlanningDecision(
        kind="build_blocked",
        objective_id="10",
        objective_title="Captured objective",
        objective_url="fake://objective/10",
        requested_node_id=None,
        reason="[prefix_gap] child published before parent",
    )

    missing = _planning_train(
        nodes=(),
        layers=(_train_layer("1.1", None, None),),
        candidate="1.1",
    )
    missing_result = _StatusDelivery(
        StatusResult("10", missing.objective_url, None, missing, None)
    ).prepare(PrepareRequest(kind="layer_start", mode="planning", objective_id="10"))
    assert missing_result.planning is not None
    assert missing_result.planning.kind == "build_blocked"
    assert missing_result.planning.reason == "the readiness candidate 1.1 is not on the roadmap"


@pytest.mark.parametrize(
    ("status", "pr", "requested", "expected"),
    (
        (NodeStatus.PLANNING, None, None, "ready"),
        (NodeStatus.PENDING, None, "other", "wrong_candidate"),
        (NodeStatus.IN_PROGRESS, "#101", "other", "in_flight"),
        (NodeStatus.PLANNING, "#101", "other", "in_flight"),
        (NodeStatus.DONE, "#101", None, "build_blocked"),
    ),
)
def test_planning_candidate_status_matrix(
    status: NodeStatus,
    pr: str | None,
    requested: str | None,
    expected: str,
) -> None:
    node = ObjectiveNode(id="1.1", description="Candidate", status=status, pr=pr)
    train = _planning_train(
        nodes=(node,),
        layers=(_train_layer("1.1", "101" if pr else None, "plan-101" if pr else None),),
        candidate="1.1",
    )
    result = _StatusDelivery(StatusResult("10", train.objective_url, None, train, None)).prepare(
        PrepareRequest(
            kind="layer_start",
            mode="planning",
            objective_id="10",
            node_id=requested,
        )
    )

    assert result.planning is not None and result.planning.kind == expected
    if expected == "wrong_candidate":
        assert result.planning.requested_node_id == "other"
        assert result.planning.node is not None and result.planning.node.id == "1.1"
    if expected == "in_flight":
        assert result.planning.node is not None and result.planning.node.status is status
    if expected == "build_blocked":
        assert result.planning.reason == (
            f"the next build-ready layer 1.1 is {status.value} — not plannable in that status"
        )


def test_planning_ready_decision_carries_other_resumable_claims() -> None:
    nodes = (
        ObjectiveNode(id="1.1", description="Candidate", status=NodeStatus.PENDING, depends_on=()),
        ObjectiveNode(
            id="1.2", description="Claim", status=NodeStatus.PLANNING, pr=None, depends_on=()
        ),
    )
    train = _planning_train(
        nodes=nodes,
        layers=(
            _train_layer("1.1", None, None),
            _train_layer("1.2", None, None),
        ),
        candidate="1.1",
    )
    result = _StatusDelivery(StatusResult("10", train.objective_url, None, train, None)).prepare(
        PrepareRequest(kind="layer_start", mode="planning", objective_id="10")
    )

    assert result.planning is not None and result.planning.kind == "ready"
    assert result.planning.skipped_claim_ids == ("1.2",)


@pytest.mark.parametrize(
    ("nodes", "expected"),
    (
        (
            (ObjectiveNode(id="1.1", description="Ready", status=NodeStatus.PENDING),),
            "ready",
        ),
        (
            (
                ObjectiveNode(
                    id="1.1", description="In flight", status=NodeStatus.IN_PROGRESS, pr="#101"
                ),
            ),
            "in_flight",
        ),
        (
            (ObjectiveNode(id="1.1", description="Done", status=NodeStatus.DONE),),
            "complete",
        ),
        (
            (ObjectiveNode(id="1.1", description="Blocked", status=NodeStatus.BLOCKED),),
            "no_actionable",
        ),
    ),
)
def test_planning_graph_fallback_classifies_automatic_selection(
    nodes: tuple[ObjectiveNode, ...], expected: str
) -> None:
    train = _planning_train(nodes=nodes, layers=(), candidate=None, ready=False, reason="done")
    result = _StatusDelivery(StatusResult("10", train.objective_url, None, train, None)).prepare(
        PrepareRequest(kind="layer_start", mode="planning", objective_id="10")
    )

    assert result.planning is not None and result.planning.kind == expected
    if expected in {"ready", "in_flight"}:
        assert result.planning.node is not None and result.planning.node.id == "1.1"
    if expected == "ready":
        assert result.planning.context is None


@pytest.mark.parametrize(
    ("requested", "nodes", "expected"),
    [
        (
            "missing",
            (ObjectiveNode(id="1.1", description="Done", status=NodeStatus.DONE),),
            "node_not_found",
        ),
        (
            "1.1",
            (ObjectiveNode(id="1.1", description="Done", status=NodeStatus.DONE),),
            "terminal",
        ),
        (
            "1.2",
            (
                ObjectiveNode(id="1.1", description="Pending", status=NodeStatus.PENDING),
                ObjectiveNode(
                    id="1.2",
                    description="Blocked",
                    status=NodeStatus.PENDING,
                    depends_on=("1.1",),
                ),
            ),
            "blocked",
        ),
    ],
)
def test_planning_graph_fallback_classifies_explicit_nodes(
    requested: str, nodes: tuple[ObjectiveNode, ...], expected: str
) -> None:
    status = _planning_train(nodes=nodes, layers=(), candidate=None, ready=False, reason="done")
    service = _StatusDelivery(StatusResult("10", status.objective_url, None, status, None))
    result = service.prepare(
        PrepareRequest(
            kind="layer_start",
            mode="planning",
            objective_id="10",
            node_id=requested,
        )
    )
    assert result.planning is not None and result.planning.kind == expected


def test_planning_redirect_precedes_no_train_and_normalized_id_is_not_redirect() -> None:
    redirected = _StatusDelivery(StatusResult("11", "u/11", "10", None, "incremental delivery"))
    with pytest.raises(DeliveryError) as excinfo:
        redirected.prepare(PrepareRequest(kind="layer_start", mode="planning", objective_id="10"))
    assert excinfo.value.error_type == "invalid_train"
    assert str(excinfo.value) == (
        "objective #10 redirected to active objective #11 during planning preparation; "
        "rerun against #11"
    )

    nodes = (ObjectiveNode(id="1.1", description="Ready", status=NodeStatus.PENDING),)
    status = _planning_train(
        objective_id="7",
        nodes=nodes,
        layers=(_train_layer("1.1", None, None),),
        candidate="1.1",
    )
    normalized = _StatusDelivery(StatusResult("7", status.objective_url, None, status, None))
    result = normalized.prepare(
        PrepareRequest(kind="layer_start", mode="planning", objective_id="007")
    )
    assert result.planning is not None and result.planning.objective_id == "7"


def test_planning_hard_failures_cover_unknown_candidate_and_missing_parent() -> None:
    node = ObjectiveNode(id="1.2", description="Child", status=NodeStatus.PENDING)
    unknown = _planning_train(nodes=(node,), layers=(), candidate="1.2")
    with pytest.raises(DeliveryError) as unknown_info:
        _StatusDelivery(StatusResult("10", unknown.objective_url, None, unknown, None)).prepare(
            PrepareRequest(kind="layer_start", mode="planning", objective_id="10")
        )
    assert unknown_info.value.error_type == "unknown_layer"

    missing_parent = _planning_train(
        nodes=(node,),
        layers=(_train_layer("1.1", None, None), _train_layer("1.2", None, None)),
        candidate="1.2",
    )
    with pytest.raises(DeliveryError) as parent_info:
        _StatusDelivery(
            StatusResult("10", missing_parent.objective_url, None, missing_parent, None)
        ).prepare(PrepareRequest(kind="layer_start", mode="planning", objective_id="10"))
    assert parent_info.value.error_type == "stacked_predecessor_missing"
    assert str(parent_info.value) == (
        "planning layer 1.2 has no parent branch: predecessor layer 1.1 carries no plan/branch"
    )


def test_execution_prepare_verifies_parent_in_exact_aggregate_order() -> None:
    parent_sha = "a" * 40
    nodes = (
        ObjectiveNode(id="1.1", description="Bottom", status=NodeStatus.IN_PROGRESS, pr="#101"),
        ObjectiveNode(id="1.2", description="Child", status=NodeStatus.PENDING, pr="#102"),
    )
    status = _planning_train(
        nodes=nodes,
        layers=(
            _train_layer("1.1", "101", "plan-101"),
            _train_layer("1.2", "102", "plan-102"),
        ),
        candidate="1.2",
    )
    git = FakeDeliveryGit(branches={"plan-101": parent_sha}, resolutions={parent_sha: parent_sha})
    service = _StatusDelivery(StatusResult("10", status.objective_url, None, status, None), git=git)

    result = service.prepare(
        PrepareRequest(kind="layer_start", mode="execution", objective_id="10", plan_id="102")
    )

    assert result.layer is not None and result.layer.parent_branch == "plan-101"
    assert result.parent_sha == parent_sha
    assert git.calls == [
        ("fetch_refs", "plan-101"),
        ("remote_branch_sha", "plan-101"),
        ("resolve_commit", parent_sha),
    ]


def test_execution_no_train_is_a_bounded_invalid_train_refusal() -> None:
    service = _StatusDelivery(StatusResult("10", "u/10", None, None, "incremental delivery"))

    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(
            PrepareRequest(
                kind="layer_start",
                mode="execution",
                objective_id="10",
                plan_id="101",
            )
        )

    assert excinfo.value.error_type == "invalid_train"
    assert str(excinfo.value) == (
        "plan #101 carries delivery_lineage but objective #10 has no delivery train "
        "(incremental delivery)."
    )


@pytest.mark.parametrize(
    ("plan_id", "ready", "git", "error_type", "message"),
    (
        (
            "999",
            True,
            FakeDeliveryGit(),
            "unknown_layer",
            "plan #999 is not a layer of objective 10's delivery train",
        ),
        (
            "101",
            False,
            FakeDeliveryGit(),
            "node_not_build_ready",
            "layer 1.1 (plan #101) is not build-ready: blocked by drift",
        ),
        (
            "101",
            True,
            FakeDeliveryGit(),
            "parent_missing",
            "expected the parent branch refs/heads/main on origin; observed no such remote "
            "branch — layer 1.1 cannot start without its parent",
        ),
        (
            "101",
            True,
            FakeDeliveryGit(branches={"main": "a" * 40}),
            "parent_unverified",
            f"the parent head {'a' * 40} (refs/heads/main) does not resolve locally after the "
            "fetch — cannot verify the layer start commit",
        ),
    ),
)
def test_execution_translates_layer_and_parent_refusals(
    plan_id: str,
    ready: bool,
    git: FakeDeliveryGit,
    error_type: str,
    message: str,
) -> None:
    node = ObjectiveNode(id="1.1", description="Layer", status=NodeStatus.PENDING, pr="#101")
    train = _planning_train(
        nodes=(node,),
        layers=(_train_layer("1.1", "101", "plan-101"),),
        candidate="1.1",
        ready=ready,
        reason=None if ready else "blocked by drift",
    )
    service = _StatusDelivery(StatusResult("10", train.objective_url, None, train, None), git=git)

    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(
            PrepareRequest(
                kind="layer_start",
                mode="execution",
                objective_id="10",
                plan_id=plan_id,
            )
        )

    assert excinfo.value.error_type == error_type
    assert str(excinfo.value) == message


def test_execution_normalizes_aggregate_git_failure() -> None:
    failure = TrainReconstructionError(
        "git fetch failed for refs ('main',): offline", error_type="git_error"
    )
    git = FakeDeliveryGit(errors={("fetch_refs", "main"): failure})
    node = ObjectiveNode(id="1.1", description="Layer", status=NodeStatus.PENDING, pr="#101")
    train = _planning_train(
        nodes=(node,),
        layers=(_train_layer("1.1", "101", "plan-101"),),
        candidate="1.1",
    )
    service = _StatusDelivery(StatusResult("10", train.objective_url, None, train, None), git=git)

    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(
            PrepareRequest(
                kind="layer_start",
                mode="execution",
                objective_id="10",
                plan_id="101",
            )
        )

    assert excinfo.value.error_type == "git_error"
    assert str(excinfo.value) == (
        "could not observe the parent branch refs/heads/main on origin: "
        "git fetch failed for refs ('main',): offline"
    )


def test_execution_missing_objective_refuses_before_status() -> None:
    status = StatusResult("10", "u/10", None, None, "incremental")
    service = _StatusDelivery(status)
    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(PrepareRequest(kind="layer_start", mode="execution", plan_id="102"))
    assert excinfo.value.error_type == "invalid_train"
    assert service.status_calls == []


def test_nominal_abcs_and_keyword_only_delivery_construction() -> None:
    for authority in (DeliveryPersistence, DeliveryGit, DeliveryGitHub):
        incomplete = type(f"Incomplete{authority.__name__}", (authority,), {})
        with pytest.raises(TypeError):
            incomplete()

    signature = inspect.signature(Delivery)
    assert tuple(signature.parameters) == ("persistence", "git", "github")
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()
    service = Delivery(persistence=persistence, git=git, github=github)
    assert service.__dict__ == {
        "_persistence": persistence,
        "_git": git,
        "_github": github,
    }


def test_status_result_requires_exactly_one_branch() -> None:
    status = _train()
    assert StatusResult("10", "u", None, status, None).train is status
    assert StatusResult("10", "u", None, None, "incremental").no_train_reason == "incremental"
    with pytest.raises(ValueError, match="exactly one"):
        StatusResult("10", "u", None, None, None)
    with pytest.raises(ValueError, match="exactly one"):
        StatusResult("10", "u", None, status, "incremental")


def test_status_returns_incremental_without_git_or_github_observation() -> None:
    persistence = FakeDeliveryPersistence(objectives={"10": _objective()})
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()

    result = _delivery(persistence, git, github).status(StatusRequest(objective_id="10"))

    assert result.objective_id == "10"
    assert result.objective_url == "fake://objective/10"
    assert result.train is None
    assert result.no_train_reason is not None and "incremental delivery" in result.no_train_reason
    assert persistence.calls == [("get_objective", "10")]
    assert git.calls == []
    assert github.calls == []


def test_status_returns_stacked_projection_through_aggregate_fakes() -> None:
    persistence = FakeDeliveryPersistence(
        objectives={"10": _objective(header={"delivery": "stacked", "delivery_lineage": "lineage"})}
    )
    git = FakeDeliveryGit(base_heads={"main": BaseHeadObservation(sha="a" * 40)})
    github = FakeDeliveryGitHub()

    result = _delivery(persistence, git, github).status(StatusRequest(objective_id="10"))

    assert result.no_train_reason is None
    assert result.train is not None
    assert result.train.objective_id == "10"
    assert result.train.base == "main"
    assert persistence.calls == [("get_objective", "10"), ("read_journal", "10")]
    assert git.calls == [
        ("fetch",),
        ("trunk_branch",),
        ("worktree_branches",),
        ("base_head", "main"),
    ]
    assert github.calls == []


def test_delivery_error_accepts_exactly_the_bounded_code_vocabulary() -> None:
    assert frozenset(_DELIVERY_ERROR_TYPES) == facade_mod._DELIVERY_ERROR_TYPES
    assert frozenset(_STATUS_ERROR_TYPES) == facade_mod._STATUS_ERROR_TYPES
    assert {
        DeliveryError("message", error_type=error_type).error_type
        for error_type in _DELIVERY_ERROR_TYPES
    } == _DELIVERY_ERROR_TYPES


@pytest.mark.parametrize("error_type", sorted(_STATUS_ERROR_TYPES))
def test_delivery_error_vocabulary_and_train_code_passthrough(error_type: str) -> None:
    source = TrainReconstructionError("source message", error_type=error_type)
    persistence = FakeDeliveryPersistence(errors={("get_objective", "10"): source})

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence).status(StatusRequest(objective_id="10"))

    assert excinfo.value.error_type == error_type
    assert str(excinfo.value) == "source message"


def test_delivery_error_rejects_unknown_code_and_unknown_train_code_propagates() -> None:
    with pytest.raises(ValueError, match="unknown delivery error type"):
        DeliveryError("bad", error_type="future_operation_error")

    for error_type in (
        "future_operation_error",
        "capability_unsupported",
        "invalid_input",
        "missing_lineage",
        "stacked_predecessor_missing",
        "unknown_layer",
        "node_not_build_ready",
        "parent_missing",
        "parent_unverified",
    ):
        source = TrainReconstructionError("future", error_type=error_type)
        persistence = FakeDeliveryPersistence(errors={("get_objective", "10"): source})
        with pytest.raises(TrainReconstructionError) as excinfo:
            _delivery(persistence).status(StatusRequest(objective_id="10"))
        assert excinfo.value is source


@pytest.mark.parametrize(
    "source",
    [
        IssueBackendError("issue unavailable"),
        ObjectiveStoreError("objective unavailable"),
        TrainPersistenceError("journal unavailable"),
    ],
)
def test_expected_persistence_failures_normalize_to_github_error(source: Exception) -> None:
    persistence = FakeDeliveryPersistence(errors={("get_objective", "10"): source})
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence).status(StatusRequest(objective_id="10"))
    assert excinfo.value.error_type == "github_error"
    assert str(excinfo.value) == str(source)


def test_resolve_delivery_is_zero_io_until_status_requires_persistence(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / ".perk" / "config.toml"
    config.parent.mkdir()
    config.write_text('[issues]\nbackend = "linear"\nteam = "ENG"\n', encoding="utf-8")
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)

    resolver_calls: list[tuple[str, Path]] = []
    config_calls: list[tuple[str, Path]] = []
    unexpected_calls: list[str] = []
    original_store_resolver = observe.resolve_objective_store
    original_issue_resolver = observe.resolve_issue_backend
    original_backend_read = config_mod.load_committed_issues_backend
    original_team_read = config_mod.load_committed_issues_team

    def resolve_store(repo_root: Path):
        resolver_calls.append(("objective", repo_root))
        return original_store_resolver(repo_root)

    def resolve_issues(repo_root: Path):
        resolver_calls.append(("issues", repo_root))
        return original_issue_resolver(repo_root)

    def read_backend(repo_root: Path):
        config_calls.append(("backend", repo_root))
        return original_backend_read(repo_root)

    def read_team(repo_root: Path):
        config_calls.append(("team", repo_root))
        return original_team_read(repo_root)

    def unexpected(name: str):
        def fail(*_args: object, **_kwargs: object) -> None:
            unexpected_calls.append(name)
            raise AssertionError(f"unexpected {name} I/O")

        return fail

    monkeypatch.setattr(observe, "resolve_objective_store", resolve_store)
    monkeypatch.setattr(observe, "resolve_issue_backend", resolve_issues)
    monkeypatch.setattr(config_mod, "load_committed_issues_backend", read_backend)
    monkeypatch.setattr(config_mod, "load_committed_issues_team", read_team)
    monkeypatch.setattr(observe.git_mod, "detect_trunk_branch", unexpected("trunk"))
    monkeypatch.setattr(observe.git_mod, "fetch", unexpected("fetch"))
    monkeypatch.setattr(observe.git_mod, "push_urls", unexpected("push_urls"))
    monkeypatch.setattr(observe.git_mod, "probe_atomic_push", unexpected("atomic_push"))
    monkeypatch.setattr(observe.stacks, "stack_capability", unexpected("stack_capability"))
    monkeypatch.setattr(observe.stacks, "base_merge_rules", unexpected("merge_rules"))
    monkeypatch.setattr(observe.stacks, "pr_delivery_facts", unexpected("pr_facts"))
    monkeypatch.setattr(observe.stacks, "pr_stack", unexpected("pr_stack"))
    monkeypatch.setattr(observe.prs, "find_pr_for_branch", unexpected("branch_pr"))

    service = observe.resolve_delivery(tmp_path)
    assert isinstance(service, Delivery)
    assert resolver_calls == []
    assert config_calls == []
    assert unexpected_calls == []

    with pytest.raises(DeliveryError) as excinfo:
        service.status(StatusRequest(objective_id="ENG-1"))
    assert excinfo.value.error_type == "github_error"
    assert "LINEAR_API_KEY" in str(excinfo.value)
    assert resolver_calls == [("objective", tmp_path)]
    assert config_calls == [("backend", tmp_path), ("team", tmp_path)]
    assert unexpected_calls == []


def test_prepare_with_real_git_adapter_preserves_raw_remote_failure(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_remote(*_args: object, **_kwargs: object) -> str:
        raise git_mod.GitError("ls-remote timed out")

    monkeypatch.setattr(git_mod, "remote_branch_head", fail_remote)
    service = Delivery(
        persistence=FakeDeliveryPersistence(),
        git=observe.RepoDeliveryGit(tmp_path),
        github=FakeDeliveryGitHub(),
    )

    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(PrepareRequest(kind="authoring", base="main"))

    assert excinfo.value.error_type == "capability_unsupported"
    assert str(excinfo.value) == (
        "This repository cannot take a stacked delivery train against base 'main':\n"
        "- remote-base: could not observe refs/heads/main on origin "
        "(can't verify ⇒ don't promise): ls-remote timed out"
    )
    assert "git ls-remote failed for branch" not in str(excinfo.value)


def test_real_git_adapter_fetch_refs_translates_only_expected_git_error(
    tmp_path: Path, monkeypatch
) -> None:
    expected = git_mod.GitError("fetch failed")

    def fail_fetch(*_args: object, **_kwargs: object) -> None:
        raise expected

    monkeypatch.setattr(git_mod, "fetch_refspecs", fail_fetch)
    adapter = observe.RepoDeliveryGit(tmp_path)
    with pytest.raises(TrainReconstructionError) as excinfo:
        adapter.fetch_refs(("plan-101",))
    assert excinfo.value.error_type == "git_error"
    assert excinfo.value.__cause__ is expected

    unexpected = RuntimeError("unexpected")

    def fail_unexpected(*_args: object, **_kwargs: object) -> None:
        raise unexpected

    monkeypatch.setattr(git_mod, "fetch_refspecs", fail_unexpected)
    with pytest.raises(RuntimeError) as unexpected_info:
        adapter.fetch_refs(("plan-101",))
    assert unexpected_info.value is unexpected


@pytest.mark.parametrize("seam", ("trunk", "worktrees", "pr_facts"))
def test_transfer_real_aggregate_failures_keep_stable_delivery_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    from contextlib import nullcontext

    from perk.delivery import transfer as transfer_mod

    node = ObjectiveNode("1.1", "work", NodeStatus.PENDING)
    plans: dict[str, PlanState] = {}
    git: DeliveryGit = FakeDeliveryGit()
    github: DeliveryGitHub = FakeDeliveryGitHub()
    expected_type = "git_error"
    expected_message = "adapter failed"

    if seam == "trunk":

        def fail_trunk(*_args: object, **_kwargs: object) -> str:
            raise git_mod.GitError(expected_message)

        monkeypatch.setattr(git_mod, "detect_trunk_branch", fail_trunk)
        monkeypatch.setattr(git_mod, "worktree_list", lambda _root: [])
        git = observe.RepoDeliveryGit(tmp_path)
    elif seam == "worktrees":
        node = replace(node, pr="#101")
        plans["101"] = replace(
            _plan("101"),
            header={"branch": "plan-101", "objective_id": "10"},
        )

        def fail_worktrees(*_args: object, **_kwargs: object) -> object:
            raise git_mod.GitError(expected_message)

        monkeypatch.setattr(git_mod, "worktree_list", fail_worktrees)
        git = observe.RepoDeliveryGit(tmp_path)
    else:
        node = replace(node, pr="#101")
        plans["101"] = replace(
            _plan("101"),
            header={"branch": "plan-101", "objective_id": "10", "pr": "#42"},
        )
        expected_type = "github_error"

        def fail_pr_facts(*_args: object, **_kwargs: object) -> object:
            raise GitHubError(expected_message)

        monkeypatch.setattr(observe.stacks, "pr_delivery_facts", fail_pr_facts)
        github = observe.RepoDeliveryGitHub(tmp_path)

    persistence = FakeDeliveryPersistence(
        objectives={"10": _objective(nodes=(node,))},
        plans=plans,
    )
    runtime = replace(
        transfer_mod._DEFAULT_TRANSFER_RUNTIME,
        operation_lock=lambda _root: nullcontext(),
    )
    monkeypatch.setattr(transfer_mod, "_DEFAULT_TRANSFER_RUNTIME", runtime)

    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, git, github).transfer(
            _transfer_request(delivery="stacked", roadmap_nodes=(node,))
        )

    assert excinfo.value.error_type == expected_type
    assert str(excinfo.value).endswith(expected_message)


def test_prepare_with_real_git_adapter_preserves_raw_trunk_failure(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_trunk(*_args: object, **_kwargs: object) -> str:
        raise git_mod.GitError("no trunk")

    monkeypatch.setattr(git_mod, "detect_trunk_branch", fail_trunk)
    service = Delivery(
        persistence=FakeDeliveryPersistence(),
        git=observe.RepoDeliveryGit(tmp_path),
        github=FakeDeliveryGitHub(),
    )

    with pytest.raises(DeliveryError) as excinfo:
        service.prepare(PrepareRequest(kind="authoring", base=None))

    assert excinfo.value.error_type == "git_error"
    assert str(excinfo.value) == "no trunk"
    assert "git trunk detection failed" not in str(excinfo.value)


class _ResolvedStore:
    def __init__(self, backend_id: str = "github") -> None:
        self.backend_id = backend_id
        self.calls: list[object] = []

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        self.calls.append(objective_id)
        return _objective(objective_id)

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        self.calls.append(("close_objective", objective_id, dry_run))
        return True


class _ResolvedIssues:
    def __init__(self, backend_id: str = "github") -> None:
        self.backend_id = backend_id
        self.calls: list[tuple[object, ...]] = []

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        self.calls.append(("get_plan", issue_id))
        return _plan(issue_id)

    def get_plan_body(self, *, issue_id: str) -> str | None:
        self.calls.append(("get_plan_body", issue_id))
        return f"body {issue_id}"

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> PlanHeaderUpdate:
        self.calls.append(("update_plan_header", issue_id, dict(fields), dry_run))
        return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=dry_run)


def test_lazy_persistence_reuses_only_a_complete_successful_resolution(
    tmp_path: Path, monkeypatch
) -> None:
    store = _ResolvedStore()
    issues = _ResolvedIssues()
    resolved = {"store": 0, "issues": 0}

    def store_resolver(_root: Path):
        resolved["store"] += 1
        return store

    def issues_resolver(_root: Path):
        resolved["issues"] += 1
        return issues

    monkeypatch.setattr(observe, "resolve_objective_store", store_resolver)
    monkeypatch.setattr(observe, "resolve_issue_backend", issues_resolver)
    persistence = observe.RepoDeliveryPersistence(tmp_path)

    assert persistence.get_objective(objective_id="10") == _objective("10")
    assert persistence.close_objective(objective_id="10", dry_run=True) is True
    assert persistence.get_plan(issue_id="101") == _plan("101")
    assert persistence.get_plan_body(issue_id="101") == "body 101"
    assert persistence.update_plan_header(
        issue_id="101", fields={"branch": "plan-101"}
    ) == PlanHeaderUpdate(fields_updated=("branch",), dry_run=False)
    assert resolved == {"store": 1, "issues": 1}
    assert store.calls == ["10", ("close_objective", "10", True)]
    assert issues.calls == [
        ("get_plan", "101"),
        ("get_plan_body", "101"),
        ("update_plan_header", "101", {"branch": "plan-101"}, False),
    ]


def test_lazy_persistence_mutations_delegate_exactly_and_reuse_the_cached_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _ResolvedStore()
    issues = _ResolvedIssues()
    resolved = {"store": 0, "issues": 0}
    adapters: list[Any] = []

    def store_resolver(_root: Path):
        resolved["store"] += 1
        return store

    def issues_resolver(_root: Path):
        resolved["issues"] += 1
        return issues

    prepared_result = AppendResult(
        operation_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", role=EventRole.PREPARED, existed=False
    )
    outcome_result = AppendResult(
        operation_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", role=EventRole.COMPLETED, existed=True
    )

    class _RecordingPersistence:
        def __init__(self, actual_store, actual_issues) -> None:
            assert actual_store is store and actual_issues is issues
            self.calls: list[tuple[object, ...]] = []
            adapters.append(self)

        def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
            self.calls.append(("append_prepared", objective_id, record))
            return prepared_result

        def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
            self.calls.append(("append_outcome", objective_id, record))
            return outcome_result

        def write_checkpoints(
            self,
            plan_id: str,
            *,
            parent_checkpoint_sha: str,
            published_head_sha: str,
        ) -> None:
            self.calls.append(
                (
                    "write_checkpoints",
                    plan_id,
                    parent_checkpoint_sha,
                    published_head_sha,
                )
            )

    monkeypatch.setattr(observe, "resolve_objective_store", store_resolver)
    monkeypatch.setattr(observe, "resolve_issue_backend", issues_resolver)
    monkeypatch.setattr(observe, "TrainPersistence", _RecordingPersistence)
    persistence = observe.RepoDeliveryPersistence(tmp_path)
    prepared = PreparedRecord(
        operation_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        operation_kind=OperationKind.SYNC,
        delivery_lineage="01LINEAGE",
        objective_id="10",
        run_id="01RUN",
        created="2026-01-01T00:00:00Z",
        affected_plans=("101",),
        before={},
        after={},
    )
    outcome = OutcomeRecord(
        operation_id=prepared.operation_id,
        role=EventRole.COMPLETED,
        created="2026-01-01T00:01:00Z",
        observed={},
    )

    assert persistence.append_prepared("10", prepared) == prepared_result
    assert persistence.append_outcome("10", outcome) == outcome_result
    persistence.write_checkpoints(
        "101", parent_checkpoint_sha="a" * 40, published_head_sha="b" * 40
    )

    assert resolved == {"store": 1, "issues": 1}
    assert len(adapters) == 1
    assert adapters[0].calls == [
        ("append_prepared", "10", prepared),
        ("append_outcome", "10", outcome),
        ("write_checkpoints", "101", "a" * 40, "b" * 40),
    ]


def test_lazy_persistence_resolver_failure_is_uncached(tmp_path: Path, monkeypatch) -> None:
    resolved = {"store": 0, "issues": 0}

    def store_resolver(_root: Path):
        resolved["store"] += 1
        return _ResolvedStore()

    def issues_resolver(_root: Path):
        resolved["issues"] += 1
        raise IssueBackendError("resolver failed")

    monkeypatch.setattr(observe, "resolve_objective_store", store_resolver)
    monkeypatch.setattr(observe, "resolve_issue_backend", issues_resolver)
    persistence = observe.RepoDeliveryPersistence(tmp_path)

    for _ in range(2):
        with pytest.raises(IssueBackendError, match="resolver failed"):
            persistence.get_objective(objective_id="10")
    assert resolved == {"store": 2, "issues": 2}


def test_lazy_persistence_backend_mismatch_is_exact_and_uncached(
    tmp_path: Path, monkeypatch
) -> None:
    resolved = {"store": 0, "issues": 0}

    def store_resolver(_root: Path):
        resolved["store"] += 1
        return _ResolvedStore("github")

    def issues_resolver(_root: Path):
        resolved["issues"] += 1
        return _ResolvedIssues("linear")

    monkeypatch.setattr(observe, "resolve_objective_store", store_resolver)
    monkeypatch.setattr(observe, "resolve_issue_backend", issues_resolver)
    persistence = observe.RepoDeliveryPersistence(tmp_path)
    expected = "delivery backend mismatch: objective store is 'github', issue backend is 'linear'"

    for _ in range(2):
        with pytest.raises(TrainPersistenceError, match=expected):
            persistence.get_objective(objective_id="10")
    assert resolved == {"store": 2, "issues": 2}


def test_real_and_fake_adapters_are_nominal_authorities(tmp_path: Path) -> None:
    assert isinstance(observe.RepoDeliveryPersistence(tmp_path), DeliveryPersistence)
    assert isinstance(observe.RepoDeliveryGit(tmp_path), DeliveryGit)
    assert isinstance(observe.RepoDeliveryGitHub(tmp_path), DeliveryGitHub)
    assert isinstance(FakeDeliveryPersistence(), DeliveryPersistence)
    assert isinstance(FakeDeliveryGit(), DeliveryGit)
    assert isinstance(FakeDeliveryGitHub(), DeliveryGitHub)


def test_fake_defaults_copy_inputs_and_log_calls_before_return() -> None:
    objective_seed = {"10": _objective("10")}
    plan_seed = {"101": _plan("101")}
    worktree = WorktreeFacts(path="/tmp/wt", branch="plan-101", dirty=False)
    atomic_errors = {"fake://mirror": "no atomic"}
    body_seed = {"101": "Plan body"}
    persistence = FakeDeliveryPersistence(
        objectives=objective_seed, plans=plan_seed, plan_bodies=body_seed
    )
    admin_path = Path("/tmp/stale-wt")
    git = FakeDeliveryGit(
        worktrees=(worktree,),
        worktree_admin_paths=(admin_path,),
        resolutions={"head": "a" * 40, "plan-101": "b" * 40},
        push_urls=("fake://origin", "fake://mirror"),
        atomic_push_errors=atomic_errors,
    )
    rich_pr = _publish_pr()
    strict_stack = stacks.StackRestFacts(
        number=9,
        size=1,
        entries=(stacks.StackRestEntry(42, "open", True, False, "plan-101", "b" * 40),),
    )
    merge_probe = stacks.MergeAsyncProbe(state="merged", sha="d" * 40, message="merged")
    merged_evidence = stacks.PrMergedEvidence(
        number=42,
        state="MERGED",
        base_ref="main",
        head_ref="plan-101",
        head_sha="b" * 40,
        merge_commit_sha="d" * 40,
    )
    github = FakeDeliveryGitHub(
        pull_requests={42: rich_pr},
        branch_prs={"plan-101": rich_pr},
        strict_stacks={42: strict_stack},
        merge_probes={(42, "01HANDLE"): merge_probe},
        merged_evidence={42: merged_evidence},
    )
    objective_seed.clear()
    plan_seed.clear()
    body_seed.clear()
    atomic_errors.clear()

    assert persistence.get_objective(objective_id="10") == _objective("10")
    assert persistence.get_plan(issue_id="101") == _plan("101")
    assert persistence.get_plan_body(issue_id="101") == "Plan body"
    assert persistence.update_plan_header(
        issue_id="101", fields={"branch": "plan-101", "impl_run_ids": ["01RUN"]}
    ) == PlanHeaderUpdate(fields_updated=("branch", "impl_run_ids"), dry_run=False)
    updated_plan = persistence.get_plan(issue_id="101")
    assert updated_plan is not None
    assert updated_plan.header["impl_run_ids"] == ["01RUN"]
    fold = persistence.read_journal("10")
    assert fold.delivery_lineage is None
    assert persistence.get_objective(objective_id="missing") is None
    assert persistence.close_objective(objective_id="10") is True
    closed = persistence.get_objective(objective_id="10")
    assert closed is not None and closed.state == "closed"
    assert persistence.calls == [
        ("get_objective", "10"),
        ("get_plan", "101"),
        ("get_plan_body", "101"),
        (
            "update_plan_header",
            "101",
            (("branch", "plan-101"), ("impl_run_ids", ("01RUN",))),
        ),
        ("get_plan", "101"),
        ("read_journal", "10"),
        ("get_objective", "missing"),
        ("close_objective", "10", False),
        ("get_objective", "10"),
    ]

    assert git.trunk_branch() == "main"
    assert git.fetch() is None
    assert git.fetch_refs(("main",)) is None
    assert git.resolve_commit("head") == "a" * 40
    assert git.remote_branch_sha("missing") is None
    git.push_with_exact_lease("plan-101", expected_remote_sha=None)
    assert git.remote_branch_sha("plan-101") == "b" * 40
    assert git.push_urls() == DeliveryGit.PushUrlsResult(urls=("fake://origin", "fake://mirror"))
    assert (
        git.probe_atomic_push(push_url="fake://origin", base_branch="main", base_sha="a")
        == DeliveryGit.AtomicPushResult()
    )
    assert git.probe_atomic_push(
        push_url="fake://mirror", base_branch="main", base_sha="a"
    ) == DeliveryGit.ProbeError(message="no atomic")
    assert git.is_ancestor("a", "a") is True
    assert git.is_ancestor("a", "b") is None
    assert git.worktree_branches() == (worktree,)
    assert git.worktree_admin_paths() == (admin_path,)
    assert git.base_head("main") == BaseHeadObservation(sha=None, failure=None)
    assert git.calls == [
        ("trunk_branch",),
        ("fetch",),
        ("fetch_refs", "main"),
        ("resolve_commit", "head"),
        ("remote_branch_sha", "missing"),
        ("push_with_exact_lease", "plan-101", None),
        ("remote_branch_sha", "plan-101"),
        ("push_urls",),
        ("probe_atomic_push", "fake://origin", "main", "a"),
        ("probe_atomic_push", "fake://mirror", "main", "a"),
        ("is_ancestor", "a", "a"),
        ("is_ancestor", "a", "b"),
        ("worktree_branches",),
        ("worktree_admin_paths",),
        ("base_head", "main"),
    ]

    assert github.stack_capability() is True
    assert github.base_merge_rules("main") == DeliveryGitHub.MergeRules(
        squash_allowed=True, merge_queue_required=False
    )
    assert github.pr_facts(42) is None
    assert github.pr_for_branch("plan-101") == rich_pr
    assert github.strict_stack(42) == strict_stack
    assert github.merge_async_probe(42, uuid="01HANDLE") is merge_probe
    assert github.merged_evidence(42) is merged_evidence
    assert github.get_pr(42) == rich_pr
    assert github.pr_stack(42) == StackView(available=True, stacked=False)
    assert github.calls == [
        ("stack_capability",),
        ("base_merge_rules", "main"),
        ("pr_facts", 42),
        ("pr_for_branch", "plan-101"),
        ("strict_stack", 42),
        ("merge_async_probe", 42, "01HANDLE"),
        ("merged_evidence", 42),
        ("get_pr", 42),
        ("pr_stack", 42),
    ]


def test_new_fake_probe_failures_are_constructor_discriminants() -> None:
    git = FakeDeliveryGit(
        push_urls_error="no remote",
        atomic_push_errors={"fake://origin": "no atomic"},
    )
    github = FakeDeliveryGitHub(merge_rules_error="HTTP 500", stack_capable=False)

    assert git.push_urls() == DeliveryGit.ProbeError(message="no remote")
    assert git.probe_atomic_push(
        push_url="fake://origin", base_branch="main", base_sha="a"
    ) == DeliveryGit.ProbeError(message="no atomic")
    assert github.stack_capability() is False
    assert github.base_merge_rules("main") == DeliveryGitHub.ProbeError(message="HTTP 500")
    assert git.calls == [
        ("push_urls",),
        ("probe_atomic_push", "fake://origin", "main", "a"),
    ]
    assert github.calls == [("stack_capability",), ("base_merge_rules", "main")]


def test_fake_failure_injection_logs_before_raising() -> None:
    failure = RuntimeError("injected")
    persistence = FakeDeliveryPersistence(
        errors={("get_plan", "101"): failure, ("close_objective", "10", False): failure}
    )
    git = FakeDeliveryGit(errors={("fetch",): failure, ("worktree_admin_paths",): failure})
    github = FakeDeliveryGitHub(
        errors={
            ("pr_stack", 42): failure,
            ("merge_async_probe", 42, "01HANDLE"): failure,
            ("merged_evidence", 42): failure,
        }
    )

    with pytest.raises(RuntimeError) as persistence_error:
        persistence.get_plan(issue_id="101")
    with pytest.raises(RuntimeError) as git_error:
        git.fetch()
    with pytest.raises(RuntimeError) as github_error:
        github.pr_stack(42)
    with pytest.raises(RuntimeError) as close_error:
        persistence.close_objective(objective_id="10")
    with pytest.raises(RuntimeError) as admin_error:
        git.worktree_admin_paths()
    with pytest.raises(RuntimeError) as probe_error:
        github.merge_async_probe(42, uuid="01HANDLE")
    with pytest.raises(RuntimeError) as evidence_error:
        github.merged_evidence(42)
    assert persistence_error.value is failure
    assert git_error.value is failure
    assert github_error.value is failure
    assert close_error.value is failure
    assert admin_error.value is failure
    assert probe_error.value is failure
    assert evidence_error.value is failure
    assert persistence.calls == [("get_plan", "101"), ("close_objective", "10", False)]
    assert git.calls == [("fetch",), ("worktree_admin_paths",)]
    assert github.calls == [
        ("pr_stack", 42),
        ("merge_async_probe", 42, "01HANDLE"),
        ("merged_evidence", 42),
    ]


def test_public_export_cut_is_exact() -> None:
    exported = set(delivery_pkg.__all__)
    assert exported >= _NEW_EXPORTS
    assert _RETIRED_EXPORTS.isdisjoint(exported)
    assert exported == _NEW_EXPORTS | _RETAINED_EXPORTS
    assert len(delivery_pkg.__all__) == 59
    assert not hasattr(delivery_pkg, "DeliveryTrain")
    for finalize_name in (
        "finalize_landed_plan",
        "LandedPlan",
        "LandFinalization",
        "ObjectiveLandUpdate",
        "LearnConsumeUpdate",
        "squash_commit_message",
    ):
        assert not hasattr(delivery_pkg, finalize_name)
    for retired in {
        "DeliveryOperationFacts",
        "LayerBodyFacts",
        "PublicationError",
        "PublicationResult",
        "TrainRowFacts",
        "publish_layer",
        "RecoverError",
        "recover_operations",
        "MergedPrefixRow",
        "RemainderPrRow",
        "LandedLayerRow",
        "OperationRow",
        "SweepFailure",
        "AbandonPreview",
        "AcceptPrefixPreview",
    }:
        assert not hasattr(delivery_pkg, retired)

    from perk.delivery import recover as recover_mod

    assert not hasattr(recover_mod, "RecoverError")
    assert not hasattr(recover_mod, "recover_operations")


# --- the Land family (the incremental plan variant) -------------------------------------------


_STACKED_LAND_MESSAGE = (
    "plan #7 carries stacked delivery lineage — stacked layers land only as one "
    "atomic train, never individually\n"
    "Landing one layer merges into its parent branch and tears the train. "
    "Inspect the train with: perk objective stack status"
)


def _land_request(**over: Any) -> LandRequest:
    fields: dict[str, Any] = {
        "kind": "plan",
        "plan_id": "7",
        "branch": "plan-7",
        "objective_id": None,
        "consumed_learn": (),
        "delivery_lineage": None,
    }
    fields.update(over)
    return LandRequest(**fields)


def _land_plan_state(
    *, title: str = "My Feature", header: dict[str, object] | None = None
) -> PlanState:
    return PlanState(
        id="7",
        url="fake://plan/7",
        title=title,
        header=dict(header or {}),
        pr=None,
        state="OPEN",
    )


def _branch_pr(*, is_draft: bool = False, state: str = "OPEN", base_ref: str = "main"):
    return prs.PullRequest(
        number=42,
        url="u/pr/42",
        is_draft=is_draft,
        state=state,
        existed=True,
        base_ref=base_ref,
    )


def _recording_land_runtime(monkeypatch: pytest.MonkeyPatch, fin: Any | None = None):
    """Bind a recording finalize into the module-level land runtime the façade reads."""
    from perk.delivery import land_plan as land_plan_mod
    from perk.delivery.finalize import LandFinalization, LearnConsumeUpdate, ObjectiveLandUpdate

    calls: list[dict[str, Any]] = []
    result = fin or LandFinalization(
        learn_state="pending",
        plan_issue_closed=False,
        objective=ObjectiveLandUpdate(None, (), "no_objective_link"),
        learn=LearnConsumeUpdate((), "no_consumed_learn"),
    )

    def finalize(repo_root, *, landed, pr_base, close_objective_on_complete=True):
        calls.append(
            {
                "repo_root": repo_root,
                "landed": landed,
                "pr_base": pr_base,
                "close_objective_on_complete": close_objective_on_complete,
            }
        )
        return result

    monkeypatch.setattr(
        land_plan_mod, "_DEFAULT_LAND_RUNTIME", land_plan_mod._LandRuntime(finalize=finalize)
    )
    return calls


def test_land_request_guards_kind_and_nonblank_identity() -> None:
    request = _land_request()
    assert (request.objective_id, request.consumed_learn) == (None, ())
    assert (request.delivery_lineage, request.dry_run) == (None, False)
    # plan_id is carried verbatim — no #-normalization (refusal bytes use it as-is).
    assert _land_request(plan_id="#7").plan_id == "#7"
    # The plan-ref-derived intent fields carry NO defaults: forgetting to reconstruct one
    # (e.g. the stacked discriminator) fails at construction, never lands silently weaker.
    with pytest.raises(TypeError):
        LandRequest(kind="plan", plan_id="7", branch="plan-7")  # ty: ignore[missing-argument]
    with pytest.raises(ValueError, match="unknown land kind"):
        _land_request(kind=cast(Any, "objective"))
    with pytest.raises(ValueError, match="plan_id must be nonblank"):
        _land_request(plan_id="  ")
    with pytest.raises(ValueError, match="branch must be nonblank"):
        _land_request(branch="")
    with pytest.raises(FrozenInstanceError):
        request.dry_run = True  # ty: ignore[invalid-assignment]


def test_land_result_is_a_strict_kind_detail_wrapper() -> None:
    detail = LandResult.Plan(
        dry_run=False,
        pr=LandResult.PrSummary(number=42, state="MERGED"),
        objective=LandResult.ObjectiveUpdate("10", ("1.1",), None, closed=True),
        learn=LandResult.LearnUpdate(("45",), None),
        plan_issue_closed=True,
        learn_state="pending",
    )
    result = LandResult(kind="plan", plan=detail)
    assert result.plan is detail
    with pytest.raises(ValueError, match="unknown land result kind"):
        LandResult(kind=cast(Any, "objective"), plan=detail)
    with pytest.raises(ValueError, match="detail must match kind exactly"):
        LandResult(kind="plan")
    for frozen in cast(
        "tuple[Any, ...]", (detail, detail.pr, detail.objective, detail.learn, result)
    ):
        with pytest.raises(FrozenInstanceError):
            type(frozen).__setattr__(frozen, "kind", "x")
    # The nested update records default like the internal finalize records they mirror.
    assert LandResult.ObjectiveUpdate(None, (), "dry_run").closed is False
    assert (
        LandResult.Plan(
            dry_run=True,
            pr=LandResult.PrSummary(0, "OPEN"),
            objective=LandResult.ObjectiveUpdate(None, (), "dry_run"),
            learn=LandResult.LearnUpdate((), "dry_run"),
        ).learn_state
        is None
    )


def test_delivery_land_builds_one_bound_context_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery import land_plan as land_plan_mod

    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit(repo_root=Path("/bound-repo"))
    github = FakeDeliveryGitHub()
    service = Delivery(persistence=persistence, git=git, github=github)
    request = _land_request()
    expected = LandResult(
        kind="plan",
        plan=LandResult.Plan(
            dry_run=False,
            pr=LandResult.PrSummary(42, "MERGED"),
            objective=LandResult.ObjectiveUpdate(None, (), "no_objective_link"),
            learn=LandResult.LearnUpdate((), "no_consumed_learn"),
        ),
    )
    captured: list[tuple[Any, LandRequest, object]] = []

    def dispatch(context, actual_request, *, runtime):
        captured.append((context, actual_request, runtime))
        return expected

    monkeypatch.setattr(land_plan_mod, "_dispatch", dispatch)
    assert service.land(request) is expected
    ((context, actual_request, runtime),) = captured
    assert context.persistence is persistence and context.git is git and context.github is github
    assert actual_request is request and runtime is land_plan_mod._DEFAULT_LAND_RUNTIME


@pytest.mark.parametrize("dry_run", [False, True])
def test_land_refuses_cached_stacked_lineage_before_everything(dry_run: bool) -> None:
    # The cached half refuses with ZERO authority access — even on --dry-run (a would-merge
    # preview for a stacked plan would be a lie), and before the dry-run early return.
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, git, github).land(
            _land_request(delivery_lineage="01LINEAGE", dry_run=dry_run)
        )
    assert excinfo.value.error_type == "stacked_plan"
    assert (excinfo.value.phase, excinfo.value.origin) == ("land", "domain")
    assert str(excinfo.value) == _STACKED_LAND_MESSAGE
    assert persistence.calls == [] and git.calls == [] and github.calls == []


def test_land_dry_run_is_offline_and_exact() -> None:
    persistence = FakeDeliveryPersistence()
    git = FakeDeliveryGit()
    github = FakeDeliveryGitHub()

    result = _delivery(persistence, git, github).land(_land_request(dry_run=True))

    assert result == LandResult(
        kind="plan",
        plan=LandResult.Plan(
            dry_run=True,
            pr=LandResult.PrSummary(number=0, state="OPEN"),
            objective=LandResult.ObjectiveUpdate(None, (), "dry_run"),
            learn=LandResult.LearnUpdate((), "dry_run"),
        ),
    )
    assert persistence.calls == [] and git.calls == [] and github.calls == []


def test_land_plan_not_found_refuses_before_any_mutation() -> None:
    persistence = FakeDeliveryPersistence()
    github = FakeDeliveryGitHub()
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, github=github).land(_land_request())
    assert excinfo.value.error_type == "plan_not_found"
    assert (excinfo.value.phase, excinfo.value.origin) == ("land", "domain")
    assert str(excinfo.value) == "Plan issue #7 not found"
    assert persistence.calls == [("get_plan", "7")]
    assert github.calls == []


def test_land_header_half_stacked_refusal_wins_over_stale_ref() -> None:
    # A stale cached ref WITHOUT the lineage still refuses once the authoritative plan header
    # shows it — refused after the pre-merge read, before any mutation.
    persistence = FakeDeliveryPersistence(
        plans={"7": _land_plan_state(header={"delivery_lineage": "01LINEAGE"})}
    )
    github = FakeDeliveryGitHub()
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, github=github).land(_land_request())
    assert excinfo.value.error_type == "stacked_plan"
    assert str(excinfo.value) == _STACKED_LAND_MESSAGE
    assert github.calls == []


def test_land_whitespace_header_lineage_is_not_stacked(monkeypatch: pytest.MonkeyPatch) -> None:
    # The isinstance/strip guard: a whitespace-only header lineage is not stacked — lands.
    _recording_land_runtime(monkeypatch)
    persistence = FakeDeliveryPersistence(
        plans={"7": _land_plan_state(header={"delivery_lineage": "  "})}
    )
    github = FakeDeliveryGitHub(branch_prs={"plan-7": _branch_pr()})

    result = _delivery(persistence, github=github).land(_land_request())

    detail = result.plan
    assert detail is not None and detail.pr == LandResult.PrSummary(42, "MERGED")
    assert ("merge_pr", 42, "My Feature\n\nCloses #7") in github.calls


def test_land_no_pr_refusal_names_the_branch() -> None:
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state()})
    github = FakeDeliveryGitHub()
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, github=github).land(_land_request())
    assert excinfo.value.error_type == "no_pr"
    assert (excinfo.value.phase, excinfo.value.origin) == ("land", "domain")
    assert str(excinfo.value) == "No PR found for branch 'plan-7'\nRun /submit first."
    assert github.calls == [("pr_for_branch", "plan-7")]


@pytest.mark.parametrize(
    "source",
    (
        IssueBackendError("issues failed"),
        GitHubError("github failed"),
        ObjectiveStoreError("objectives failed"),
        TrainPersistenceError("persistence failed"),
        TrainReconstructionError("gateway failed", error_type="github_error"),
    ),
)
def test_land_maps_expected_boundary_failures(source: Exception) -> None:
    persistence = FakeDeliveryPersistence(errors={("get_plan", "7"): source})
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence).land(_land_request())
    assert excinfo.value.error_type == "github_error"
    assert (excinfo.value.phase, excinfo.value.origin) == ("land", "github")
    assert str(excinfo.value) == str(source)


def test_land_production_pr_lookup_wrapper_translates_at_the_boundary() -> None:
    # The production pr_for_branch adapter wraps GitHubError into TrainReconstructionError
    # (same message text); the façade translates it to the github_error land failure.
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state()})
    github = FakeDeliveryGitHub(
        errors={
            ("pr_for_branch", "plan-7"): TrainReconstructionError(
                "gh pr list failed", error_type="github_error"
            )
        }
    )
    with pytest.raises(DeliveryError) as excinfo:
        _delivery(persistence, github=github).land(_land_request())
    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == (
        "github_error",
        "land",
        "github",
    )
    assert str(excinfo.value) == "gh pr list failed"


def test_land_unexpected_programming_errors_propagate() -> None:
    boom = RuntimeError("bug")
    persistence = FakeDeliveryPersistence(errors={("get_plan", "7"): boom})
    with pytest.raises(RuntimeError) as excinfo:
        _delivery(persistence).land(_land_request())
    assert excinfo.value is boom


def test_land_draft_pr_marks_ready_then_merges_then_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _recording_land_runtime(monkeypatch)
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state()})
    git = FakeDeliveryGit(repo_root=Path("/repo"))
    github = FakeDeliveryGitHub(branch_prs={"plan-7": _branch_pr(is_draft=True)})

    result = _delivery(persistence, git, github).land(
        _land_request(objective_id="10", consumed_learn=("45",))
    )

    assert github.calls == [
        ("pr_for_branch", "plan-7"),
        ("mark_pr_ready", 42),
        ("merge_pr", 42, "My Feature\n\nCloses #7"),
    ]
    assert persistence.calls == [("get_plan", "7"), ("backend_id",)]
    from perk.delivery.finalize import LandedPlan

    assert calls == [
        {
            "repo_root": Path("/repo"),
            "landed": LandedPlan(plan_id="7", objective_id="10", consumed_learn=("45",)),
            "pr_base": "main",
            "close_objective_on_complete": True,
        }
    ]
    detail = result.plan
    assert detail is not None
    assert detail.pr == LandResult.PrSummary(number=42, state="MERGED")
    assert detail.dry_run is False


def test_land_ready_pr_skips_mark_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _recording_land_runtime(monkeypatch)
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state()})
    github = FakeDeliveryGitHub(branch_prs={"plan-7": _branch_pr(is_draft=False)})

    _delivery(persistence, github=github).land(_land_request())

    assert github.calls == [
        ("pr_for_branch", "plan-7"),
        ("merge_pr", 42, "My Feature\n\nCloses #7"),
    ]


def test_land_already_merged_is_idempotent_and_still_finalizes_with_real_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _recording_land_runtime(monkeypatch)
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state()})
    github = FakeDeliveryGitHub(
        branch_prs={"plan-7": _branch_pr(state="MERGED", base_ref="release")}
    )

    result = _delivery(persistence, github=github).land(_land_request())

    # already MERGED → no mark-ready, no merge call, no backend-identity read…
    assert github.calls == [("pr_for_branch", "plan-7")]
    assert persistence.calls == [("get_plan", "7")]
    # …but finalization still runs with the REAL pre-merge base_ref.
    assert calls[0]["pr_base"] == "release"
    detail = result.plan
    assert detail is not None and detail.pr == LandResult.PrSummary(42, "MERGED")


def test_land_base_ref_is_captured_before_the_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    # The synthetic merged PullRequest carries no base_ref; finalize must see the pre-merge one.
    calls = _recording_land_runtime(monkeypatch)
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state()})
    github = FakeDeliveryGitHub(branch_prs={"plan-7": _branch_pr(base_ref="release")})

    _delivery(persistence, github=github).land(_land_request())

    assert calls[0]["pr_base"] == "release"


def test_land_squash_message_composes_from_the_authoritative_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Non-github backends get the `Plan: <id> — <url>` footer from the authoritative
    # PlanState.url (not a cached ref); GitHub keeps `Closes #N`.
    _recording_land_runtime(monkeypatch)
    persistence = FakeDeliveryPersistence(
        plans={"7": _land_plan_state(title="  Ship it  ")}, backend_id="linear"
    )
    github = FakeDeliveryGitHub(branch_prs={"plan-7": _branch_pr()})

    _delivery(persistence, github=github).land(_land_request())

    assert ("merge_pr", 42, "Ship it\n\nPlan: 7 — fake://plan/7") in github.calls
    assert ("backend_id",) in persistence.calls


def test_land_empty_title_falls_back_to_the_bare_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _recording_land_runtime(monkeypatch)
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state(title="")})
    github = FakeDeliveryGitHub(branch_prs={"plan-7": _branch_pr()})

    _delivery(persistence, github=github).land(_land_request())

    assert ("merge_pr", 42, "Closes #7") in github.calls


def test_land_result_maps_the_finalization_field_for_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perk.delivery.finalize import LandFinalization, LearnConsumeUpdate, ObjectiveLandUpdate

    fin = LandFinalization(
        learn_state="skipped",
        plan_issue_closed=True,
        objective=ObjectiveLandUpdate("10", ("1.1", "1.2"), None, closed=True),
        learn=LearnConsumeUpdate(("45", "50"), "failed: #51"),
    )
    _recording_land_runtime(monkeypatch, fin)
    persistence = FakeDeliveryPersistence(plans={"7": _land_plan_state()})
    github = FakeDeliveryGitHub(branch_prs={"plan-7": _branch_pr()})

    result = _delivery(persistence, github=github).land(_land_request())

    assert result == LandResult(
        kind="plan",
        plan=LandResult.Plan(
            dry_run=False,
            pr=LandResult.PrSummary(number=42, state="MERGED"),
            objective=LandResult.ObjectiveUpdate("10", ("1.1", "1.2"), None, closed=True),
            learn=LandResult.LearnUpdate(("45", "50"), "failed: #51"),
            plan_issue_closed=True,
            learn_state="skipped",
        ),
    )


def test_land_fake_authority_defaults_mirror_production() -> None:
    persistence = FakeDeliveryPersistence()
    assert persistence.backend_id() == "github"
    assert persistence.calls == [("backend_id",)]
    github = FakeDeliveryGitHub()
    merged = github.merge_pr(42, commit_message="msg")
    assert merged == prs.PullRequest(
        number=42, url="", is_draft=False, state="MERGED", existed=True
    )
    assert merged.base_ref == ""
    assert github.calls == [("merge_pr", 42, "msg")]
