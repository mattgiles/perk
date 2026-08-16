"""Contract tests for the compact ``perk.delivery`` status/Prepare façade."""

import inspect
from pathlib import Path
from typing import Literal, cast

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
    PrepareRequest,
    PrepareResult,
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
from perk.substrate import git as git_mod

_DELIVERY_ERROR_TYPES = {
    "capability_unsupported",
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
    "CapabilityCheck",
    "CapabilityReport",
    "preflight_stacked_authoring",
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


def test_prepare_request_and_result_validate_the_authoring_discriminator() -> None:
    assert PrepareRequest(kind="authoring", base=None).base is None
    assert PrepareResult(kind="authoring", base="main").base == "main"

    unknown = cast(Literal["authoring"], "future")
    with pytest.raises(ValueError, match=r"^unknown prepare kind: 'future'$"):
        PrepareRequest(kind=unknown, base=None)
    with pytest.raises(ValueError, match=r"^unknown prepare kind: 'future'$"):
        PrepareResult(kind=unknown, base="main")


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


def test_delivery_error_accepts_exactly_the_seven_code_vocabulary() -> None:
    assert {
        DeliveryError("message", error_type=error_type).error_type
        for error_type in _DELIVERY_ERROR_TYPES
    } == _DELIVERY_ERROR_TYPES


@pytest.mark.parametrize("error_type", sorted(_DELIVERY_ERROR_TYPES - {"capability_unsupported"}))
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

    for error_type in ("future_operation_error", "capability_unsupported"):
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
    atomic_errors = {"fake://mirror": "no atomic"}
    persistence = FakeDeliveryPersistence(objectives=objective_seed, plans=plan_seed)
    git = FakeDeliveryGit(
        worktrees=(worktree,),
        push_urls=("fake://origin", "fake://mirror"),
        atomic_push_errors=atomic_errors,
    )
    github = FakeDeliveryGitHub()
    objective_seed.clear()
    plan_seed.clear()
    atomic_errors.clear()

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
        ("remote_branch_sha", "missing"),
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
    assert github.pr_for_branch("plan-101") is None
    assert github.pr_stack(42) == StackView(available=True, stacked=False)
    assert github.calls == [
        ("stack_capability",),
        ("base_merge_rules", "main"),
        ("pr_facts", 42),
        ("pr_for_branch", "plan-101"),
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
    assert not hasattr(delivery_pkg, "DeliveryTrain")
