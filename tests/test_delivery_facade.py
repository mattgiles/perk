"""Contract tests for the compact ``perk.delivery`` status façade."""

import inspect
from pathlib import Path

import pytest

import perk.delivery as delivery_pkg
from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.delivery import observe
from perk.delivery._fakes import FakeDeliveryGit, FakeDeliveryGitHub, FakeDeliveryPersistence
from perk.delivery.facade import (
    Delivery,
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    StatusRequest,
    StatusResult,
)
from perk.delivery.persistence import TrainPersistenceError
from perk.delivery.train import (
    BaseHeadObservation,
    BuildReadiness,
    DeliveryTrain,
    StackView,
    TrainReconstructionError,
    WorktreeFacts,
)
from perk.substrate import config as config_mod

_STATUS_ERROR_TYPES = {
    "objective_not_found",
    "invalid_delivery_policy",
    "invalid_train",
    "git_error",
    "github_error",
    "supersession_corruption",
}
_RETIRED_EXPORTS = {
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
}
_NEW_EXPORTS = {
    "Delivery",
    "DeliveryPersistence",
    "DeliveryGit",
    "DeliveryGitHub",
    "DeliveryError",
    "StatusRequest",
    "StatusResult",
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
    "CapabilityCheck",
    "CapabilityReport",
    "preflight_stacked_authoring",
    "probe_atomic_push_urls",
    "ContinuationLayer",
    "ContinuationManifest",
    "PendingContinuation",
    "continuations_dir",
    "manifest_path",
    "pending_continuation",
    "write_manifest",
    "LayerContext",
    "LayerContextOut",
    "LayerError",
    "PreparedLayerStart",
    "derive_layer_context",
    "prepare_layer_start",
    "require_ready_layer",
    "require_reviewable_layer",
    "DeliveryOperationFacts",
    "LayerBodyFacts",
    "PublicationError",
    "PublicationResult",
    "TrainRowFacts",
    "publish_layer",
    "ClaimedLayer",
    "SyncCascade",
    "SyncError",
    "SyncResult",
    "SyncedLayer",
    "derive_claimed_prefix",
    "synchronize_train",
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
    "RemoteWriterProbe",
    "WriterObservationError",
    "assess_land_readiness",
    "land_train",
    "squash_commit_message",
}


def _objective(
    objective_id: str = "10",
    *,
    header: dict[str, object] | None = None,
) -> ObjectiveState:
    return ObjectiveState(
        id=objective_id,
        url=f"fake://objective/{objective_id}",
        title="Objective",
        header=dict(header or {}),
        nodes=(),
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

    source = TrainReconstructionError("future", error_type="future_operation_error")
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
        self.calls: list[str] = []

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        self.calls.append(issue_id)
        return _plan(issue_id)


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
    assert resolved == {"store": 1, "issues": 1}
    assert store.calls == ["10"]
    assert issues.calls == ["101"]


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
    persistence = FakeDeliveryPersistence(objectives=objective_seed, plans=plan_seed)
    git = FakeDeliveryGit(worktrees=(worktree,))
    github = FakeDeliveryGitHub()
    objective_seed.clear()
    plan_seed.clear()

    assert persistence.get_objective(objective_id="10") == _objective("10")
    assert persistence.get_plan(issue_id="101") == _plan("101")
    fold = persistence.read_journal("10")
    assert fold.delivery_lineage is None
    assert persistence.get_objective(objective_id="missing") is None
    assert persistence.calls == [
        ("get_objective", "10"),
        ("get_plan", "101"),
        ("read_journal", "10"),
        ("get_objective", "missing"),
    ]

    assert git.trunk_branch() == "main"
    assert git.fetch() is None
    assert git.remote_branch_sha("missing") is None
    assert git.is_ancestor("a", "a") is True
    assert git.is_ancestor("a", "b") is None
    assert git.worktree_branches() == (worktree,)
    assert git.base_head("main") == BaseHeadObservation(sha=None, failure=None)
    assert git.calls == [
        ("trunk_branch",),
        ("fetch",),
        ("remote_branch_sha", "missing"),
        ("is_ancestor", "a", "a"),
        ("is_ancestor", "a", "b"),
        ("worktree_branches",),
        ("base_head", "main"),
    ]

    assert github.pr_facts(42) is None
    assert github.pr_for_branch("plan-101") is None
    assert github.pr_stack(42) == StackView(available=True, stacked=False)
    assert github.calls == [
        ("pr_facts", 42),
        ("pr_for_branch", "plan-101"),
        ("pr_stack", 42),
    ]


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
    assert not hasattr(delivery_pkg, "DeliveryTrain")
