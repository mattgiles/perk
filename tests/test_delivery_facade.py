"""Contract tests for the compact ``perk.delivery`` status/Prepare façade."""

import inspect
from dataclasses import FrozenInstanceError
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
    PrepareRequest,
    PrepareResult,
    PublishRequest,
    PublishResult,
    StatusRequest,
    StatusResult,
    SyncRequest,
    SyncResult,
)
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalRecordTooLarge,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
)
from perk.delivery.layer import LayerError
from perk.delivery.persistence import AppendResult, TrainPersistenceError
from perk.delivery.train import (
    BaseHeadObservation,
    BuildReadiness,
    DeliveryTrain,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    StackView,
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
    "SyncRequest",
    "SyncResult",
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
    "LandedPlan",
    "LandFinalization",
    "LearnConsumeUpdate",
    "ObjectiveLandUpdate",
    "finalize_landed_plan",
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
    "squash_commit_message",
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
    def __init__(self, result: StatusResult, *, git: DeliveryGit | None = None) -> None:
        super().__init__(
            persistence=FakeDeliveryPersistence(),
            git=git or FakeDeliveryGit(),
            github=FakeDeliveryGitHub(),
        )
        self.result = result
        self.status_calls: list[StatusRequest] = []

    def status(self, request: StatusRequest) -> StatusResult:
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
    with pytest.raises(ValueError, match="stack facts"):
        PublishResult(
            kind="layer",
            plan_id="101",
            dry_run=False,
            layer=PublishResult.Layer(
                pr=_publish_pr(),
                branch="plan-101",
                header_update=PlanHeaderUpdate(fields_updated=(), dry_run=False),
                plan_embedded=False,
                pr_checked=True,
                parent_branch="main",
                operation_id="01OP",
                stack_number=1,
                stack_size=None,
                stack_position=1,
                parent_checkpoint_sha="a",
                published_head_sha="b",
                resumed=False,
                converged_noop=False,
            ),
        )


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

    service = observe.resolve_delivery(tmp_path)
    service.publish(PublishRequest(kind="layer", plan_id="#101", dry_run=True))
    service.publish(PublishRequest(kind="ready", plan_id="101", dry_run=True))

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
        PrepareRequest(kind="plan_identity", mode="strict", objective_id="10", node_id="1.1"),
        PrepareRequest(kind="plan_identity", mode="best_effort", objective_id="10"),
        PrepareRequest(kind="layer_start", mode="planning", objective_id="10"),
        PrepareRequest(kind="layer_start", mode="execution", plan_id="101"),
    )
    assert tuple(request.kind for request in valid) == (
        "authoring",
        "plan_identity",
        "plan_identity",
        "layer_start",
        "layer_start",
    )
    invalid = (
        lambda: PrepareRequest(kind="authoring", base="main", mode="strict"),
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

    with pytest.raises(ValueError):
        PrepareResult(kind="authoring", base=None)
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
        self.calls: list[str] = []

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        self.calls.append(objective_id)
        return _objective(objective_id)


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
    assert persistence.get_plan(issue_id="101") == _plan("101")
    assert persistence.get_plan_body(issue_id="101") == "body 101"
    assert persistence.update_plan_header(
        issue_id="101", fields={"branch": "plan-101"}
    ) == PlanHeaderUpdate(fields_updated=("branch",), dry_run=False)
    assert resolved == {"store": 1, "issues": 1}
    assert store.calls == ["10"]
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
    git = FakeDeliveryGit(
        worktrees=(worktree,),
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
    github = FakeDeliveryGitHub(
        pull_requests={42: rich_pr},
        branch_prs={"plan-101": rich_pr},
        strict_stacks={42: strict_stack},
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
        ("base_head", "main"),
    ]

    assert github.stack_capability() is True
    assert github.base_merge_rules("main") == DeliveryGitHub.MergeRules(
        squash_allowed=True, merge_queue_required=False
    )
    assert github.pr_facts(42) is None
    assert github.pr_for_branch("plan-101") == rich_pr
    assert github.strict_stack(42) == strict_stack
    assert github.get_pr(42) == rich_pr
    assert github.pr_stack(42) == StackView(available=True, stacked=False)
    assert github.calls == [
        ("stack_capability",),
        ("base_merge_rules", "main"),
        ("pr_facts", 42),
        ("pr_for_branch", "plan-101"),
        ("strict_stack", 42),
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
    persistence = FakeDeliveryPersistence(errors={("get_plan", "101"): failure})
    git = FakeDeliveryGit(errors={("fetch",): failure})
    github = FakeDeliveryGitHub(errors={("pr_stack", 42): failure})

    with pytest.raises(RuntimeError) as persistence_error:
        persistence.get_plan(issue_id="101")
    with pytest.raises(RuntimeError) as git_error:
        git.fetch()
    with pytest.raises(RuntimeError) as github_error:
        github.pr_stack(42)
    assert persistence_error.value is failure
    assert git_error.value is failure
    assert github_error.value is failure
    assert persistence.calls == [("get_plan", "101")]
    assert git.calls == [("fetch",)]
    assert github.calls == [("pr_stack", 42)]


def test_public_export_cut_is_exact() -> None:
    exported = set(delivery_pkg.__all__)
    assert exported >= _NEW_EXPORTS
    assert _RETIRED_EXPORTS.isdisjoint(exported)
    assert exported == _NEW_EXPORTS | _RETAINED_EXPORTS
    assert len(delivery_pkg.__all__) == 59
    assert not hasattr(delivery_pkg, "DeliveryTrain")
    for retired in {
        "DeliveryOperationFacts",
        "LayerBodyFacts",
        "PublicationError",
        "PublicationResult",
        "TrainRowFacts",
        "publish_layer",
    }:
        assert not hasattr(delivery_pkg, retired)
