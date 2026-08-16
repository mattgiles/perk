"""The canonical repository-scoped delivery status and Prepare façade.

``Delivery`` composes three nominal aggregate authorities. ``status`` delegates its pure
projection to :mod:`perk.delivery.train`; ``prepare`` owns authoring capability, plan identity,
stacked-planning classification, and executable layer-start preparation; ``sync`` dispatches the
private transactional engine. Construction remains assignment-only and pure derivation stays in
this module.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk import objective
from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.delivery import capability, train
from perk.delivery import layer as layer_mod
from perk.delivery.journal import (
    JournalCorruptionError,
    JournalFold,
    JournalRecordTooLarge,
    OutcomeRecord,
    PreparedRecord,
)
from perk.delivery.persistence import AppendResult, TrainPersistenceError
from perk.github import GitHubError
from perk.objective import NodeStatus, ObjectiveNode
from perk.substrate import git as git_mod

_DELIVERY_ERROR_TYPES = frozenset(
    {
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
    }
)

# Status remains the exact bounded subset established by the status slice. Prepare may use the
# wider façade vocabulary without accidentally widening train-error passthrough.
_STATUS_ERROR_TYPES = frozenset(
    {
        "objective_not_found",
        "invalid_delivery_policy",
        "invalid_train",
        "git_error",
        "github_error",
        "supersession_corruption",
    }
)


type PrepareKind = Literal["authoring", "plan_identity", "layer_start"]
type PrepareMode = Literal["strict", "best_effort", "planning", "execution"]
type PlanningDecisionKind = Literal[
    "ready",
    "build_blocked",
    "in_flight",
    "wrong_candidate",
    "complete",
    "node_not_found",
    "terminal",
    "blocked",
    "no_actionable",
]


def _nonblank(value: str | None) -> bool:
    return value is not None and bool(value.strip())


@dataclass(frozen=True)
class PrepareRequest:
    """Request the live preflight for one delivery operation family."""

    kind: PrepareKind
    base: str | None = None
    mode: PrepareMode | None = None
    objective_id: str | None = None
    node_id: str | None = None
    plan_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("authoring", "plan_identity", "layer_start"):
            raise ValueError(f"unknown prepare kind: {self.kind!r}")
        if self.kind == "authoring":
            if any(
                value is not None
                for value in (self.mode, self.objective_id, self.node_id, self.plan_id)
            ):
                raise ValueError("authoring prepare accepts only base")
            return
        if self.kind == "plan_identity":
            if self.mode not in ("strict", "best_effort"):
                raise ValueError("plan_identity prepare requires strict or best_effort mode")
            if (
                self.base is not None
                or self.plan_id is not None
                or not _nonblank(self.objective_id)
            ):
                raise ValueError("invalid plan_identity prepare fields")
            if self.node_id is not None and not _nonblank(self.node_id):
                raise ValueError("plan_identity node_id must be nonblank when present")
            if self.mode == "strict" and self.node_id is None:
                raise ValueError("strict plan_identity prepare requires node_id")
            return
        if self.mode == "planning":
            if (
                self.base is not None
                or self.plan_id is not None
                or not _nonblank(self.objective_id)
            ):
                raise ValueError("invalid planning layer_start fields")
            if self.node_id is not None and not _nonblank(self.node_id):
                raise ValueError("planning node_id must be nonblank when present")
            return
        if self.mode == "execution":
            if self.base is not None or self.node_id is not None or not _nonblank(self.plan_id):
                raise ValueError("invalid execution layer_start fields")
            if self.objective_id is not None and not _nonblank(self.objective_id):
                raise ValueError("execution objective_id must be nonblank when present")
            return
        raise ValueError("layer_start prepare requires planning or execution mode")


@dataclass(frozen=True)
class PrepareResult:
    """The flat result family for all Prepare operation variants."""

    @dataclass(frozen=True)
    class PlanIdentity:
        objective_node_id: str
        delivery_lineage: str
        predecessor_plan_id: str | None

        def __post_init__(self) -> None:
            if not _nonblank(self.objective_node_id) or not _nonblank(self.delivery_lineage):
                raise ValueError("plan identity fields must be nonblank")
            if self.predecessor_plan_id is not None and not _nonblank(self.predecessor_plan_id):
                raise ValueError("predecessor_plan_id must be nonblank when present")

    @dataclass(frozen=True)
    class PlanningNode:
        id: str
        description: str
        status: NodeStatus
        pr: str | None

        def __post_init__(self) -> None:
            if not _nonblank(self.id):
                raise ValueError("planning node id must be nonblank")

    @dataclass(frozen=True)
    class PlanningContext:
        position: int
        layer_count: int
        delivery_lineage: str | None
        base: str
        predecessor_node_id: str | None
        predecessor_plan_id: str | None
        parent_branch: str
        observed_parent_head_sha: str | None

        def __post_init__(self) -> None:
            if self.position < 1 or self.layer_count < 1 or self.position > self.layer_count:
                raise ValueError("planning context position must be within the layer count")
            if not _nonblank(self.base) or not _nonblank(self.parent_branch):
                raise ValueError("planning context branches must be nonblank")
            if (self.predecessor_node_id is None) != (self.predecessor_plan_id is None):
                raise ValueError("planning context predecessor identity must be complete")

    @dataclass(frozen=True)
    class PlanningDecision:
        kind: PlanningDecisionKind
        objective_id: str
        objective_title: str
        objective_url: str
        requested_node_id: str | None
        node: "PrepareResult.PlanningNode | None" = None
        reason: str | None = None
        skipped_claim_ids: tuple[str, ...] | None = None
        context: "PrepareResult.PlanningContext | None" = None

        def __post_init__(self) -> None:
            allowed = {
                "ready",
                "build_blocked",
                "in_flight",
                "wrong_candidate",
                "complete",
                "node_not_found",
                "terminal",
                "blocked",
                "no_actionable",
            }
            if self.kind not in allowed:
                raise ValueError(f"unknown planning decision kind: {self.kind!r}")
            node_kinds = {"ready", "in_flight", "wrong_candidate", "terminal", "blocked"}
            if (self.node is not None) != (self.kind in node_kinds):
                raise ValueError("planning decision node does not match kind")
            if (self.reason is not None) != (self.kind == "build_blocked"):
                raise ValueError("planning decision reason exists only for build_blocked")
            if (self.skipped_claim_ids is not None) != (self.kind == "ready"):
                raise ValueError("planning decision skipped claims exist only for ready")
            if self.context is not None and self.kind != "ready":
                raise ValueError("planning context exists only for ready")
            if not _nonblank(self.objective_id):
                raise ValueError("planning objective id must be nonblank")

    kind: PrepareKind
    mode: PrepareMode | None = None
    base: str | None = None
    identity: PlanIdentity | None = None
    planning: PlanningDecision | None = None
    layer: layer_mod.LayerContext | None = None
    parent_sha: str | None = None
    notice: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("authoring", "plan_identity", "layer_start"):
            raise ValueError(f"unknown prepare kind: {self.kind!r}")
        if self.kind == "authoring":
            if (
                self.mode is not None
                or not _nonblank(self.base)
                or any(
                    value is not None
                    for value in (
                        self.identity,
                        self.planning,
                        self.layer,
                        self.parent_sha,
                        self.notice,
                    )
                )
            ):
                raise ValueError("invalid authoring prepare result")
            return
        if self.kind == "plan_identity":
            if self.mode not in ("strict", "best_effort") or any(
                value is not None for value in (self.planning, self.layer, self.parent_sha)
            ):
                raise ValueError("invalid plan_identity prepare result")
            if self.base is not None and not _nonblank(self.base):
                raise ValueError("plan_identity base must be nonblank when present")
            if self.mode == "strict" and self.notice is not None:
                raise ValueError("strict plan_identity result cannot carry notice")
            if self.notice is not None and (self.base is not None or self.identity is not None):
                raise ValueError("best-effort read failure cannot carry base or identity")
            return
        if self.mode == "planning":
            if self.planning is None or any(
                value is not None
                for value in (self.base, self.identity, self.layer, self.parent_sha, self.notice)
            ):
                raise ValueError("invalid planning layer_start result")
            return
        if self.mode == "execution":
            if (
                self.layer is None
                or not _nonblank(self.parent_sha)
                or any(
                    value is not None
                    for value in (self.base, self.identity, self.planning, self.notice)
                )
            ):
                raise ValueError("invalid execution layer_start result")
            return
        raise ValueError("layer_start result requires planning or execution mode")


@dataclass(frozen=True)
class SyncRequest:
    """Request one published-suffix synchronization operation."""

    mode: Literal["cascade", "continue", "abort"]
    objective_id: str
    run_id: str | None = None
    include_base: bool = False
    dry_run: bool = False
    adopt_node: str | None = None
    trigger_plan_id: str | None = None
    trigger_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("cascade", "continue", "abort"):
            raise ValueError(f"unknown sync mode: {self.mode!r}")
        if not _nonblank(self.objective_id):
            raise ValueError("sync objective_id must be nonblank")
        for name, value in (
            ("run_id", self.run_id),
            ("adopt_node", self.adopt_node),
            ("trigger_plan_id", self.trigger_plan_id),
            ("trigger_run_id", self.trigger_run_id),
        ):
            if value is not None and not _nonblank(value):
                raise ValueError(f"sync {name} must be nonblank when present")
        if self.mode == "cascade":
            if self.run_id is None:
                raise ValueError("cascade sync requires run_id")
            if self.include_base and self.adopt_node is not None:
                raise ValueError(
                    "--adopt and --base are mutually exclusive — adopt the layer first, then "
                    "rerun with --base (sequential invocations reach the same state)"
                )
            if self.trigger_plan_id is not None and (
                self.include_base or self.adopt_node is not None
            ):
                raise ValueError(
                    "trigger-scoped synchronization cannot compose with --base or --adopt — "
                    "run those operations sequentially"
                )
            if self.trigger_run_id is not None and self.trigger_plan_id is None:
                raise ValueError("sync trigger_run_id requires trigger_plan_id")
            return
        if (
            self.run_id is not None
            or self.include_base
            or self.dry_run
            or self.adopt_node is not None
            or self.trigger_plan_id is not None
            or self.trigger_run_id is not None
        ):
            raise ValueError(f"{self.mode} sync accepts only objective_id")


@dataclass(frozen=True)
class SyncResult:
    """The flat result family for cascade, continue, and abort operations."""

    @dataclass(frozen=True)
    class Layer:
        node_id: str
        plan_id: str
        branch: str
        pr_number: int
        before_sha: str
        after_sha: str

    @dataclass(frozen=True)
    class Cascade:
        objective_id: str
        base_branch: str
        include_base: bool
        base_before: str | None
        base_after: str | None
        layers: tuple["SyncResult.Layer", ...]

    @dataclass(frozen=True)
    class AbortPreview:
        manifest_path: Path
        parseable: bool
        contained: bool
        operation_id: str | None
        conflict_node_id: str | None
        worktree_path: str | None

    objective_id: str
    objective_url: str
    redirected_from: str | None
    operation_id: str | None
    abandoned_operation_id: str | None
    no_op: bool
    declined: bool
    resumed: bool
    base_cascaded: bool
    base_advanced: bool
    affected: tuple[Layer, ...]
    dry_run: bool = False
    adopted_node: str | None = None
    continued: bool = False
    aborted: bool = False
    notes: tuple[str, ...] = ()


type _SyncConsent = Callable[[SyncResult.Cascade | SyncResult.AbortPreview], bool]


@dataclass(frozen=True)
class StatusRequest:
    """Request one objective's current delivery status."""

    objective_id: str


@dataclass(frozen=True)
class StatusResult:
    """Exactly one explicit status branch: a train or the successful no-train reason."""

    objective_id: str
    objective_url: str
    redirected_from: str | None
    train: train.DeliveryTrain | None
    no_train_reason: str | None

    def __post_init__(self) -> None:
        if (self.train is None) == (self.no_train_reason is None):
            raise ValueError("exactly one of train and no_train_reason must be non-None")


class DeliveryError(Exception):
    """A bounded delivery-façade failure with a stable machine ``error_type``."""

    def __init__(self, message: str, *, error_type: str) -> None:
        if error_type not in _DELIVERY_ERROR_TYPES:
            allowed = ", ".join(sorted(_DELIVERY_ERROR_TYPES))
            raise ValueError(f"unknown delivery error type {error_type!r} (allowed: {allowed})")
        super().__init__(message)
        self.error_type = error_type


class DeliveryPersistence(ABC):
    """Aggregate status authority over objective, plan, and journal persistence."""

    @abstractmethod
    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        """Read one objective by backend-owned id."""
        ...

    @abstractmethod
    def get_plan(self, *, issue_id: str) -> PlanState | None:
        """Read one plan by backend-owned id."""
        ...

    @abstractmethod
    def read_journal(self, objective_id: str) -> JournalFold:
        """Read the succession-folded delivery journal."""
        ...

    @abstractmethod
    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        """Append one prepared operation record through the aligned persistence."""
        ...

    @abstractmethod
    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        """Append one terminal operation outcome through the aligned persistence."""
        ...

    @abstractmethod
    def write_checkpoints(
        self,
        plan_id: str,
        *,
        parent_checkpoint_sha: str,
        published_head_sha: str,
    ) -> None:
        """Write one layer's verified checkpoint pair atomically."""
        ...


class DeliveryGit(ABC):
    """Aggregate Git authority for status, Prepare, and synchronization."""

    @dataclass(frozen=True)
    class PushUrlsResult:
        urls: tuple[str, ...]

    @dataclass(frozen=True)
    class AtomicPushResult:
        pass

    @dataclass(frozen=True)
    class ProbeError:
        message: str

    @property
    @abstractmethod
    def repo_root(self) -> Path:
        """The repository root this authority is bound to; zero-I/O."""
        ...

    @abstractmethod
    def trunk_branch(self) -> str:
        """Resolve the repository trunk when the objective does not pin a base."""
        ...

    @abstractmethod
    def fetch(self) -> None:
        """Fetch the delivery observation remote."""
        ...

    @abstractmethod
    def fetch_refs(self, refs: tuple[str, ...]) -> None:
        """Fetch exactly the named remote branch refs."""
        ...

    @abstractmethod
    def resolve_commit(self, ref: str, *, cwd: Path | None = None) -> str | None:
        """Resolve a ref in the bound repository or an explicitly retained worktree."""
        ...

    @abstractmethod
    def remote_branch_sha(self, branch: str) -> str | None:
        """Observe one remote branch head."""
        ...

    @abstractmethod
    def push_urls(self) -> PushUrlsResult | ProbeError:
        """Resolve every configured push URL or return the expected Git failure."""
        ...

    @abstractmethod
    def probe_atomic_push(
        self,
        *,
        push_url: str,
        base_branch: str,
        base_sha: str,
    ) -> AtomicPushResult | ProbeError:
        """Run one no-op atomic push probe or return the expected Git failure."""
        ...

    @abstractmethod
    def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool | None:
        """Classify ancestry, or return ``None`` when Git cannot answer."""
        ...

    @abstractmethod
    def worktree_branches(self) -> tuple[train.WorktreeFacts, ...]:
        """Observe branches occupied by local worktrees."""
        ...

    @abstractmethod
    def base_head(self, branch: str) -> train.BaseHeadObservation:
        """Observe the authoritative live base head tolerantly."""
        ...

    @abstractmethod
    def push_atomic(self, updates: tuple[git_mod.RefUpdate, ...]) -> None:
        """Push one non-empty exact-leased multi-ref update atomically."""
        ...

    @abstractmethod
    def update_ref(self, ref: str, sha: str) -> None:
        """Create or replace one local ref."""
        ...

    @abstractmethod
    def delete_ref(self, ref: str) -> None:
        """Delete one local ref."""
        ...

    @abstractmethod
    def list_refs(self, prefix: str) -> tuple[str, ...]:
        """List local refs under a prefix."""
        ...

    @abstractmethod
    def add_detached_worktree(self, path: Path, commit: str) -> None:
        """Create a detached isolated worktree."""
        ...

    @abstractmethod
    def remove_worktree(self, path: Path) -> None:
        """Force-remove one isolated worktree."""
        ...

    @abstractmethod
    def prune_worktrees(self) -> None:
        """Prune stale worktree administration entries."""
        ...

    @abstractmethod
    def checkout_detached(self, worktree: Path, sha: str) -> None:
        """Checkout one commit detached in an isolated worktree."""
        ...

    @abstractmethod
    def rebase_onto(self, worktree: Path, *, onto: str, upstream: str) -> git_mod.RebaseOutcome:
        """Transplant the current detached range onto a new parent."""
        ...

    @abstractmethod
    def rebase_in_progress(self, worktree: Path) -> bool:
        """Whether a retained worktree has an unfinished rebase."""
        ...

    @abstractmethod
    def worktree_dirty(self, worktree: Path) -> bool:
        """Whether a retained worktree carries uncommitted changes."""
        ...


class DeliveryGitHub(ABC):
    """Aggregate GitHub authority for status, Prepare, and synchronization."""

    @dataclass(frozen=True)
    class MergeRules:
        squash_allowed: bool
        merge_queue_required: bool

    @dataclass(frozen=True)
    class ProbeError:
        message: str

    @abstractmethod
    def stack_capability(self) -> bool:
        """Whether the host schema exposes native stacks, failing closed to ``False``."""
        ...

    @abstractmethod
    def base_merge_rules(self, base: str) -> MergeRules | ProbeError:
        """Read direct-merge rules for ``base`` or return the expected gateway failure."""
        ...

    @abstractmethod
    def pr_facts(self, number: int) -> train.PrFactsView | None:
        """Read stable delivery facts for one PR."""
        ...

    @abstractmethod
    def pr_stack(self, number: int) -> train.StackView:
        """Read tolerant native-stack membership for one PR."""
        ...

    @abstractmethod
    def pr_for_branch(self, branch: str) -> train.BranchPrView | None:
        """Read an all-state PR by head branch."""
        ...

    @abstractmethod
    def strict_stack_members(self, number: int) -> tuple[int, ...] | None:
        """Read strict native-stack membership for one PR."""
        ...

    @abstractmethod
    def active_writer_plan_ids(
        self,
        plan_ids: tuple[str, ...],
        *,
        trigger_plan_id: str | None,
        trigger_run_id: str | None,
    ) -> frozenset[str]:
        """Observe active remote writers with optional corroborated self-exclusion."""
        ...


def _derive_plan_identity(
    state: ObjectiveState, *, node_id: str, strict: bool
) -> PrepareResult.PlanIdentity | None:
    """Purely derive one plan's stacked identity from an objective snapshot."""
    try:
        policy = objective.delivery_policy(state.header)
    except ValueError as exc:
        if strict:
            raise DeliveryError(str(exc), error_type="invalid_delivery_policy") from exc
        return None
    if policy is not objective.DeliveryPolicy.STACKED:
        return None

    raw_lineage = state.header.get("delivery_lineage")
    lineage = raw_lineage.strip() if isinstance(raw_lineage, str) else None
    if not lineage:
        if strict:
            raise DeliveryError(
                f"objective #{state.id} is stacked but carries no valid delivery_lineage — "
                "a stacked layer cannot be saved without its train identity (the plan would "
                "silently route down the incremental path).",
                error_type="missing_lineage",
            )
        return None
    try:
        order = objective.delivery_order(list(state.nodes))
    except ValueError as exc:
        if strict:
            raise DeliveryError(
                f"no canonical delivery order exists: {exc}", error_type="invalid_train"
            ) from exc
        return None
    index = next((i for i, node in enumerate(order) if node.id == node_id), None)
    if index is None:
        if strict:
            raise DeliveryError(
                f"node {node_id} is not a layer of objective #{state.id}'s delivery train "
                "(unknown or skipped) — a stacked node-linked save must name a layer.",
                error_type="invalid_input",
            )
        return None
    predecessor: str | None = None
    if index > 0:
        predecessor_node = order[index - 1]
        if predecessor_node.pr is None:
            raise DeliveryError(
                f"node {node_id} is not the bottom layer and its delivery-order predecessor "
                f"{predecessor_node.id} has no linked plan — plan the predecessor first "
                f"(`perk objective plan {state.id} --node {predecessor_node.id}`).",
                error_type="stacked_predecessor_missing",
            )
        predecessor = str(predecessor_node.pr).lstrip("#")
    return PrepareResult.PlanIdentity(
        objective_node_id=node_id,
        delivery_lineage=lineage,
        predecessor_plan_id=predecessor,
    )


def _planning_node(node: ObjectiveNode) -> PrepareResult.PlanningNode:
    """Project one objective node into the flat Prepare result vocabulary."""
    return PrepareResult.PlanningNode(
        id=node.id,
        description=node.description,
        status=node.status,
        pr=node.pr,
    )


def _derive_planning_context(
    status: train.DeliveryTrain, *, node_id: str
) -> PrepareResult.PlanningContext:
    """Derive planning presentation facts entirely from one immutable train snapshot."""
    index = next(
        (i for i, candidate in enumerate(status.layers) if candidate.node_id == node_id),
        None,
    )
    if index is None:
        raise DeliveryError(
            f"build-readiness candidate node {node_id} is absent from objective "
            f"#{status.objective_id}'s delivery train",
            error_type="unknown_layer",
        )
    if index == 0:
        return PrepareResult.PlanningContext(
            position=1,
            layer_count=len(status.layers),
            delivery_lineage=status.delivery_lineage,
            base=status.base,
            predecessor_node_id=None,
            predecessor_plan_id=None,
            parent_branch=status.base,
            observed_parent_head_sha=None,
        )
    predecessor = status.layers[index - 1]
    if predecessor.plan_id is None or predecessor.branch is None:
        raise DeliveryError(
            f"planning layer {node_id} has no parent branch: predecessor layer "
            f"{predecessor.node_id} carries no plan/branch",
            error_type="stacked_predecessor_missing",
        )
    return PrepareResult.PlanningContext(
        position=index + 1,
        layer_count=len(status.layers),
        delivery_lineage=status.delivery_lineage,
        base=status.base,
        predecessor_node_id=predecessor.node_id,
        predecessor_plan_id=predecessor.plan_id,
        parent_branch=predecessor.branch,
        observed_parent_head_sha=predecessor.observed_remote_head_sha,
    )


def _ready_decision(
    status: train.DeliveryTrain,
    *,
    requested_node_id: str | None,
    node: ObjectiveNode,
    graph: objective.DependencyGraph,
    context: PrepareResult.PlanningContext | None,
) -> PrepareResult.PlanningDecision:
    skipped_claims = tuple(claim.id for claim in graph.resumable_claims() if claim.id != node.id)
    return PrepareResult.PlanningDecision(
        kind="ready",
        objective_id=status.objective_id,
        objective_title=status.objective_title,
        objective_url=status.objective_url,
        requested_node_id=requested_node_id,
        node=_planning_node(node),
        skipped_claim_ids=skipped_claims,
        context=context,
    )


def _classify_planning(
    status: train.DeliveryTrain, *, requested_node_id: str | None
) -> PrepareResult.PlanningDecision:
    """Classify one stacked planning action from a single captured train snapshot. Pure."""
    nodes = list(status.objective_nodes)
    graph = objective.build_graph(nodes)
    readiness = status.build_readiness
    candidate_id = readiness.next_node_id
    if candidate_id is not None:
        if not readiness.ready:
            return PrepareResult.PlanningDecision(
                kind="build_blocked",
                objective_id=status.objective_id,
                objective_title=status.objective_title,
                objective_url=status.objective_url,
                requested_node_id=requested_node_id,
                reason=readiness.reason,
            )
        candidate = next((node for node in nodes if node.id == candidate_id), None)
        if candidate is None:
            return PrepareResult.PlanningDecision(
                kind="build_blocked",
                objective_id=status.objective_id,
                objective_title=status.objective_title,
                objective_url=status.objective_url,
                requested_node_id=requested_node_id,
                reason=f"the readiness candidate {candidate_id} is not on the roadmap",
            )
        if candidate.status is NodeStatus.PENDING or (
            candidate.status is NodeStatus.PLANNING and candidate.pr is None
        ):
            if requested_node_id is not None and requested_node_id != candidate.id:
                return PrepareResult.PlanningDecision(
                    kind="wrong_candidate",
                    objective_id=status.objective_id,
                    objective_title=status.objective_title,
                    objective_url=status.objective_url,
                    requested_node_id=requested_node_id,
                    node=_planning_node(candidate),
                )
            return _ready_decision(
                status,
                requested_node_id=requested_node_id,
                node=candidate,
                graph=graph,
                context=_derive_planning_context(status, node_id=candidate.id),
            )
        if candidate.status is NodeStatus.IN_PROGRESS or (
            candidate.status is NodeStatus.PLANNING and candidate.pr is not None
        ):
            return PrepareResult.PlanningDecision(
                kind="in_flight",
                objective_id=status.objective_id,
                objective_title=status.objective_title,
                objective_url=status.objective_url,
                requested_node_id=requested_node_id,
                node=_planning_node(candidate),
            )
        return PrepareResult.PlanningDecision(
            kind="build_blocked",
            objective_id=status.objective_id,
            objective_title=status.objective_title,
            objective_url=status.objective_url,
            requested_node_id=requested_node_id,
            reason=(
                f"the next build-ready layer {candidate.id} is {candidate.status.value} — "
                "not plannable in that status"
            ),
        )

    if requested_node_id is not None:
        requested = next((node for node in graph.nodes if node.id == requested_node_id), None)
        if requested is None:
            return PrepareResult.PlanningDecision(
                kind="node_not_found",
                objective_id=status.objective_id,
                objective_title=status.objective_title,
                objective_url=status.objective_url,
                requested_node_id=requested_node_id,
            )
        if requested in graph.plannable_nodes():
            return _ready_decision(
                status,
                requested_node_id=requested_node_id,
                node=requested,
                graph=graph,
                context=None,
            )
        if requested in graph.in_flight_nodes():
            kind: PlanningDecisionKind = "in_flight"
        elif requested.status in objective.TERMINAL:
            kind = "terminal"
        else:
            kind = "blocked"
        return PrepareResult.PlanningDecision(
            kind=kind,
            objective_id=status.objective_id,
            objective_title=status.objective_title,
            objective_url=status.objective_url,
            requested_node_id=requested_node_id,
            node=_planning_node(requested),
        )

    selection = graph.classify_for_planning()
    if selection.kind == "plannable":
        selected = selection.node
        if selected is None:
            raise ValueError("plannable graph selection must carry a node")
        return _ready_decision(
            status,
            requested_node_id=None,
            node=selected,
            graph=graph,
            context=None,
        )
    if selection.kind == "in_flight":
        selected = selection.node
        if selected is None:
            raise ValueError("in_flight graph selection must carry a node")
        return PrepareResult.PlanningDecision(
            kind="in_flight",
            objective_id=status.objective_id,
            objective_title=status.objective_title,
            objective_url=status.objective_url,
            requested_node_id=None,
            node=_planning_node(selected),
        )
    kind = "complete" if selection.kind == "complete" else "no_actionable"
    return PrepareResult.PlanningDecision(
        kind=kind,
        objective_id=status.objective_id,
        objective_title=status.objective_title,
        objective_url=status.objective_url,
        requested_node_id=None,
    )


def _raw_prepare_git_error(exc: git_mod.GitError | train.TrainReconstructionError) -> str:
    """Preserve the old Prepare paths' raw Git detail when status adapters are reused."""
    if isinstance(exc, train.TrainReconstructionError):
        cause = exc.__cause__
        if isinstance(cause, git_mod.GitError):
            return str(cause)
    return str(exc)


class Delivery:
    """Repository-scoped delivery status, Prepare, and synchronization operations."""

    def __init__(
        self,
        *,
        persistence: DeliveryPersistence,
        git: DeliveryGit,
        github: DeliveryGitHub,
    ) -> None:
        self._persistence = persistence
        self._git = git
        self._github = github

    def sync(self, request: SyncRequest, *, consent: _SyncConsent | None = None) -> SyncResult:
        """Synchronize a published suffix through the private transactional engine."""
        from perk.delivery import sync as sync_mod  # noqa: PLC0415 — avoids facade↔engine cycle

        context = sync_mod._SyncContext(
            repo_root=self._git.repo_root,
            persistence=self._persistence,
            git=self._git,
            github=self._github,
            status=self.status,
            runtime=sync_mod._DEFAULT_SYNC_RUNTIME,
        )
        try:
            return sync_mod._dispatch(context, request, consent=consent)
        except DeliveryError:
            raise
        except git_mod.GitError as exc:
            raise DeliveryError(str(exc), error_type="git_error") from exc
        except GitHubError as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc
        except train.TrainReconstructionError as exc:
            code = exc.error_type if exc.error_type in _DELIVERY_ERROR_TYPES else "github_error"
            raise DeliveryError(str(exc), error_type=code) from exc
        except JournalCorruptionError as exc:
            raise DeliveryError(str(exc), error_type="journal_corruption") from exc
        except JournalRecordTooLarge as exc:
            raise DeliveryError(str(exc), error_type="journal_record_too_large") from exc
        except sync_mod.SyncConfigurationError as exc:
            raise DeliveryError(str(exc), error_type="invalid_config") from exc
        except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc

    def prepare(self, request: PrepareRequest) -> PrepareResult:
        """Prepare one operation family or return one bounded refusal."""
        if request.kind == "authoring":
            return self._prepare_authoring(request)
        if request.kind == "plan_identity":
            return self._prepare_plan_identity(request)
        if request.mode == "planning":
            return self._prepare_planning(request)
        return self._prepare_execution(request)

    def _prepare_authoring(self, request: PrepareRequest) -> PrepareResult:
        effective_base = request.base
        if effective_base is None:
            try:
                effective_base = self._git.trunk_branch()
            except train.TrainReconstructionError as exc:
                if exc.error_type != "git_error":
                    raise
                raise DeliveryError(_raw_prepare_git_error(exc), error_type="git_error") from exc
            except git_mod.GitError as exc:
                raise DeliveryError(str(exc), error_type="git_error") from exc

        checks: list[capability._CapabilityCheck] = [
            capability._native_stack_check(self._github.stack_capability())
        ]

        rules = self._github.base_merge_rules(effective_base)
        if isinstance(rules, DeliveryGitHub.ProbeError):
            checks.append(capability._merge_rules_check(effective_base, error=rules.message))
        else:
            checks.append(
                capability._merge_rules_check(
                    effective_base,
                    squash_allowed=rules.squash_allowed,
                    merge_queue_required=rules.merge_queue_required,
                )
            )

        base_sha: str | None
        try:
            base_sha = self._git.remote_branch_sha(effective_base)
        except train.TrainReconstructionError as exc:
            if exc.error_type != "git_error":
                raise
            base_sha = None
            checks.append(
                capability._remote_base_check(effective_base, error=_raw_prepare_git_error(exc))
            )
        except git_mod.GitError as exc:
            base_sha = None
            checks.append(capability._remote_base_check(effective_base, error=str(exc)))
        else:
            checks.append(capability._remote_base_check(effective_base, sha=base_sha))

        if base_sha is not None:
            push_urls = self._git.push_urls()
            if isinstance(push_urls, DeliveryGit.ProbeError):
                checks.append(capability._push_urls_error_check(push_urls.message))
            elif not push_urls.urls:
                checks.append(capability._empty_push_urls_check())
            else:
                for push_url in push_urls.urls:
                    probe = self._git.probe_atomic_push(
                        push_url=push_url,
                        base_branch=effective_base,
                        base_sha=base_sha,
                    )
                    error = probe.message if isinstance(probe, DeliveryGit.ProbeError) else None
                    checks.append(capability._atomic_push_check(push_url, error=error))

        failures = tuple(check for check in checks if not check.ok)
        if failures:
            details = "\n".join(f"- {check.name}: {check.detail}" for check in failures)
            raise DeliveryError(
                f"This repository cannot take a stacked delivery train against base "
                f"{effective_base!r}:\n{details}",
                error_type="capability_unsupported",
            )
        return PrepareResult(kind="authoring", base=effective_base)

    def _prepare_plan_identity(self, request: PrepareRequest) -> PrepareResult:
        objective_id = request.objective_id
        if objective_id is None:
            raise ValueError("validated plan_identity request lost objective_id")
        bare = objective_id.lstrip("#")
        strict = request.mode == "strict"
        try:
            state = self._persistence.get_objective(objective_id=bare)
        except (ObjectiveStoreError, IssueBackendError, TrainPersistenceError) as exc:
            if strict:
                raise DeliveryError(
                    f"objective #{bare} read failed — a node-linked save reads its objective "
                    f"strictly (the delivery policy must not be guessed)\n{exc}",
                    error_type="github_error",
                ) from exc
            return PrepareResult(kind="plan_identity", mode="best_effort", notice=str(exc))
        if state is None:
            if strict:
                raise DeliveryError(
                    f"Objective #{bare} not found — a node-linked save reads its objective "
                    "strictly (a save that cannot determine the delivery policy must not "
                    "proceed unstamped).",
                    error_type="objective_not_found",
                )
            return PrepareResult(kind="plan_identity", mode="best_effort")

        raw_base = state.header.get("base")
        objective_base = (
            raw_base.strip() if isinstance(raw_base, str) and raw_base.strip() else None
        )
        if request.node_id is None:
            return PrepareResult(
                kind="plan_identity",
                mode=request.mode,
                base=objective_base,
            )
        identity = _derive_plan_identity(state, node_id=request.node_id, strict=strict)
        return PrepareResult(
            kind="plan_identity",
            mode=request.mode,
            base=objective_base,
            identity=identity,
        )

    def _prepare_planning(self, request: PrepareRequest) -> PrepareResult:
        objective_id = request.objective_id
        if objective_id is None:
            raise ValueError("validated planning request lost objective_id")
        result = self.status(StatusRequest(objective_id=objective_id))
        if result.redirected_from is not None:
            raise DeliveryError(
                f"objective #{result.redirected_from} redirected to active objective "
                f"#{result.objective_id} during planning preparation; rerun against "
                f"#{result.objective_id}",
                error_type="invalid_train",
            )
        status = result.train
        if status is None:
            raise DeliveryError(
                f"objective #{result.objective_id} has no delivery train "
                f"({result.no_train_reason})",
                error_type="invalid_train",
            )
        candidate_id = status.build_readiness.next_node_id
        if candidate_id is not None and all(
            candidate.node_id != candidate_id for candidate in status.layers
        ):
            raise DeliveryError(
                f"build-readiness candidate node {candidate_id} is absent from objective "
                f"#{status.objective_id}'s delivery train",
                error_type="unknown_layer",
            )
        return PrepareResult(
            kind="layer_start",
            mode="planning",
            planning=_classify_planning(status, requested_node_id=request.node_id),
        )

    def _prepare_execution(self, request: PrepareRequest) -> PrepareResult:
        plan_id = request.plan_id
        if plan_id is None:
            raise ValueError("validated execution request lost plan_id")
        objective_id = request.objective_id
        if objective_id is None:
            raise DeliveryError(
                f"plan #{plan_id} carries delivery_lineage but no objective_id — its "
                "delivery train cannot be reconstructed.",
                error_type="invalid_train",
            )
        result = self.status(StatusRequest(objective_id=objective_id))
        status = result.train
        if status is None:
            raise DeliveryError(
                f"plan #{plan_id} carries delivery_lineage but objective #{objective_id} has "
                f"no delivery train ({result.no_train_reason}).",
                error_type="invalid_train",
            )
        try:
            context = layer_mod.require_ready_layer(status, plan_id=plan_id)
            prepared = layer_mod.prepare_layer_start(
                context,
                fetch=self._git.fetch_refs,
                remote_head=self._git.remote_branch_sha,
                resolve_commit=self._git.resolve_commit,
            )
        except layer_mod.LayerError as exc:
            raise DeliveryError(str(exc), error_type=exc.error_type) from exc
        except train.TrainReconstructionError as exc:
            if exc.error_type != "git_error":
                raise
            raise DeliveryError(
                f"could not observe the parent branch refs/heads/{context.parent_branch} on "
                f"origin: {_raw_prepare_git_error(exc)}",
                error_type="git_error",
            ) from exc
        return PrepareResult(
            kind="layer_start",
            mode="execution",
            layer=prepared.context,
            parent_sha=prepared.parent_sha,
        )

    def status(self, request: StatusRequest) -> StatusResult:
        """Reconstruct one delivery status and expose its train/no-train branches explicitly."""
        try:
            status = train.reconstruct_train(
                request.objective_id,
                store=self._persistence,
                issues=self._persistence,
                persistence=self._persistence,
                git=self._git,
                github=self._github,
            )
        except train.TrainReconstructionError as exc:
            if exc.error_type not in _STATUS_ERROR_TYPES:
                raise
            raise DeliveryError(str(exc), error_type=exc.error_type) from exc
        except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc

        if isinstance(status, train.DeliveryTrain):
            return StatusResult(
                objective_id=status.objective_id,
                objective_url=status.objective_url,
                redirected_from=status.redirected_from,
                train=status,
                no_train_reason=None,
            )
        return StatusResult(
            objective_id=status.objective_id,
            objective_url=status.objective_url,
            redirected_from=status.redirected_from,
            train=None,
            no_train_reason=status.reason,
        )
