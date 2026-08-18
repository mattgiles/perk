"""The canonical repository-scoped delivery façade.

``Delivery`` composes three nominal aggregate authorities. ``status`` delegates its pure
projection to :mod:`perk.delivery.train`; ``prepare`` owns authoring capability, replan facts,
plan identity, stacked-planning classification, and executable layer-start preparation;
``transfer`` owns replan routing and mutation; ``publish`` owns layer publication and
draft-to-ready routing; ``sync`` dispatches the suffix transaction engine; and ``recover`` owns
operation conclusion plus the narrow cancellation-metadata repair. Construction remains
assignment-only and pure derivation stays in this module.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from perk.delivery.diagnostics import NativeCancellationMetadataWriter
    from perk.delivery.landing import LandEvidence

from perk import objective
from perk.backends.issue_backend import IssueBackendError, PlanHeaderUpdate, PlanState
from perk.backends.objective_store import ObjectiveRef, ObjectiveState, ObjectiveStoreError
from perk.delivery import capability, train
from perk.delivery import layer as layer_mod
from perk.delivery.journal import (
    JournalCorruptionError,
    JournalFold,
    JournalRecordTooLarge,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
)
from perk.delivery.persistence import AppendResult, TrainPersistenceError
from perk.github import GitHubError, prs, stacks
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


type PrepareKind = Literal["authoring", "plan_identity", "layer_start", "replan"]
type PrepareMode = Literal["strict", "best_effort", "planning", "execution"]
type PublishKind = Literal["layer", "ready"]
type PublishDelivery = Literal["incremental", "stacked"]
type RecoverKind = Literal["operation_conclusion", "cancellation_metadata"]
type RecoverAction = Literal["report", "abandon", "accept_prefix"]
type DeliveryPhase = Literal["layer", "cascade", "ready"]
type DeliveryOrigin = Literal["domain", "git", "github", "delivery"]
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
        if self.kind not in ("authoring", "plan_identity", "layer_start", "replan"):
            raise ValueError(f"unknown prepare kind: {self.kind!r}")
        if self.kind == "replan":
            if not _nonblank(self.objective_id) or any(
                value is not None for value in (self.base, self.mode, self.node_id, self.plan_id)
            ):
                raise ValueError("replan prepare accepts only a nonblank objective_id")
            return
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
    class ReplanClaim:
        node_id: str
        plan_id: str
        branch: str
        pr_number: int

    @dataclass(frozen=True)
    class ReplanContext:
        objective_id: str
        objective_url: str
        objective_title: str
        nodes: tuple[ObjectiveNode, ...]
        delivery: Literal["incremental", "stacked"]
        base: str | None
        delivery_lineage: str | None
        claimed: tuple["PrepareResult.ReplanClaim", ...]
        open_pr_plans: tuple[tuple[str, int], ...]

        @property
        def published(self) -> bool:
            return bool(self.claimed)

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
    replan: ReplanContext | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("authoring", "plan_identity", "layer_start", "replan"):
            raise ValueError(f"unknown prepare kind: {self.kind!r}")
        if self.kind == "replan":
            if self.replan is None or any(
                value is not None
                for value in (
                    self.mode,
                    self.base,
                    self.identity,
                    self.planning,
                    self.layer,
                    self.parent_sha,
                    self.notice,
                )
            ):
                raise ValueError("invalid replan prepare result")
            return
        if self.replan is not None:
            raise ValueError("replan context exists only for replan prepare")
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
class TransferRequest:
    """Immutable successor intent for an objective replan transfer."""

    predecessor_id: str
    run_id: str
    title: str
    prose: str
    base: str | None
    roadmap_nodes: tuple[objective.ObjectiveNode, ...]
    carry_map: tuple[tuple[str, str], ...]
    delivery: Literal["incremental", "stacked"]


@dataclass(frozen=True)
class TransferResult:
    """The outcome of one :meth:`Delivery.transfer` invocation."""

    predecessor_id: str
    successor: ObjectiveRef
    operation_id: str | None
    abandoned_operation_id: str | None
    rolled_forward: bool
    journaled: bool


def _normalize_publish_plan_id(plan_id: str) -> str:
    """Normalize the request's optional hash prefix and surrounding whitespace."""
    return plan_id.strip().removeprefix("#").strip()


@dataclass(frozen=True)
class PublishRequest:
    """Request layer publication or the deliberate draft-to-ready gesture."""

    kind: PublishKind
    plan_id: str
    dry_run: bool = False
    delivery: PublishDelivery | None = None
    objective_id: str | None = None
    run_id: str | None = None
    trigger_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("layer", "ready"):
            raise ValueError(f"unknown publish kind: {self.kind!r}")
        normalized_plan_id = _normalize_publish_plan_id(self.plan_id)
        if not normalized_plan_id or "#" in normalized_plan_id:
            raise ValueError("publish plan_id must be a nonblank issue id")
        if self.dry_run:
            if any(
                value is not None
                for value in (
                    self.delivery,
                    self.objective_id,
                    self.run_id,
                    self.trigger_run_id,
                )
            ):
                raise ValueError("dry-run publish accepts only kind, plan_id, and dry_run")
            return
        if self.kind == "layer":
            if not _nonblank(self.run_id):
                raise ValueError("layer publish requires run_id")
            if self.trigger_run_id is not None and not _nonblank(self.trigger_run_id):
                raise ValueError("layer publish trigger_run_id must be nonblank when present")
            if self.delivery is not None or self.objective_id is not None:
                raise ValueError("layer publish rejects delivery and objective_id")
            return
        if self.delivery not in ("incremental", "stacked"):
            raise ValueError("ready publish requires incremental or stacked delivery")
        if self.run_id is not None or self.trigger_run_id is not None:
            raise ValueError("ready publish rejects run fields")
        if self.delivery == "incremental" and self.objective_id is not None:
            raise ValueError("incremental ready rejects objective_id")
        if self.objective_id is not None and not _nonblank(self.objective_id):
            raise ValueError("stacked ready objective_id must be nonblank when present")


@dataclass(frozen=True)
class PublishResult:
    """The exact layer/ready result family returned by :meth:`Delivery.publish`."""

    @dataclass(frozen=True)
    class Layer:
        pr: prs.PullRequest
        branch: str
        header_update: PlanHeaderUpdate
        plan_embedded: bool
        pr_checked: bool
        parent_branch: str
        operation_id: str | None
        stack_number: int | None
        stack_size: int | None
        stack_position: int | None
        parent_checkpoint_sha: str | None
        published_head_sha: str | None
        resumed: bool
        converged_noop: bool
        cascade: "SyncResult | None" = None

    @dataclass(frozen=True)
    class Ready:
        pr: prs.PullRequest
        was_draft: bool

    kind: PublishKind
    plan_id: str
    dry_run: bool
    layer: Layer | None = None
    ready: Ready | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("layer", "ready"):
            raise ValueError(f"unknown publish result kind: {self.kind!r}")
        if (
            self.plan_id != _normalize_publish_plan_id(self.plan_id)
            or not self.plan_id
            or "#" in self.plan_id
        ):
            raise ValueError("publish result plan_id must be a canonical bare id")
        if (self.layer is not None) != (self.kind == "layer") or (
            (self.ready is not None) != (self.kind == "ready")
        ):
            raise ValueError("publish result detail must match kind exactly")
        if self.layer is not None:
            self._validate_layer(self.layer)
        elif self.ready is not None:
            self._validate_ready(self.ready)

    def _validate_layer(self, detail: Layer) -> None:
        triple = (detail.stack_number, detail.stack_size, detail.stack_position)
        if any(value is not None for value in triple):
            if not all(type(value) is int and value > 0 for value in triple):
                raise ValueError("publish stack facts must be all positive integers or all null")
            if (
                detail.stack_position is not None
                and detail.stack_size is not None
                and detail.stack_position > detail.stack_size
            ):
                raise ValueError("publish stack position must be within stack size")
        if self.dry_run:
            expected_pr = prs.PullRequest(
                number=0,
                url="(dry-run)",
                is_draft=True,
                state="OPEN",
                existed=False,
            )
            expected_update = PlanHeaderUpdate(
                fields_updated=("branch", "pr", "lifecycle_stage"), dry_run=True
            )
            if (
                detail.pr != expected_pr
                or detail.branch != f"plan-{self.plan_id}"
                or detail.header_update != expected_update
                or detail.plan_embedded
                or detail.pr_checked
                or detail.parent_branch != ""
                or detail.operation_id is not None
                or any(value is not None for value in triple)
                or detail.parent_checkpoint_sha is not None
                or detail.published_head_sha is not None
                or detail.resumed
                or detail.converged_noop
                or detail.cascade is not None
            ):
                raise ValueError("invalid dry-run layer publish result")
            return
        if (
            not _nonblank(detail.branch)
            or not _nonblank(detail.parent_branch)
            or detail.header_update.dry_run
            or not detail.pr_checked
            or not _nonblank(detail.parent_checkpoint_sha)
            or not _nonblank(detail.published_head_sha)
        ):
            raise ValueError("invalid real layer publish result")
        if detail.cascade is None:
            if (detail.operation_id is None) != detail.converged_noop:
                raise ValueError("direct publish operation id must be absent exactly on no-op")
            return
        if any(value is not None for value in triple):
            raise ValueError("cascade publish result carries no stack triple")
        if (
            detail.operation_id != detail.cascade.operation_id
            or detail.resumed != detail.cascade.resumed
            or detail.converged_noop != detail.cascade.no_op
            or (detail.operation_id is None and not detail.cascade.no_op)
        ):
            raise ValueError("cascade publish fields must mirror the nested sync result")

    def _validate_ready(self, detail: Ready) -> None:
        if not self.dry_run:
            return
        expected = prs.PullRequest(
            number=0,
            url="(dry-run)",
            is_draft=True,
            state="OPEN",
            existed=True,
        )
        if detail.pr != expected or not detail.was_draft:
            raise ValueError("invalid dry-run ready publish result")


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
class RecoverRequest:
    """Request one Recover variant: operation conclusion or the cancellation-metadata repair."""

    kind: RecoverKind
    objective_id: str
    action: RecoverAction = "report"
    dry_run: bool = False
    operation_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("operation_conclusion", "cancellation_metadata"):
            raise ValueError(f"unknown recover kind: {self.kind!r}")
        if self.action not in ("report", "abandon", "accept_prefix"):
            raise ValueError(f"unknown recover action: {self.action!r}")
        if not _nonblank(self.objective_id):
            raise ValueError("recover objective_id must be nonblank")
        if self.kind == "cancellation_metadata":
            # The repair variant has no operation target and no generic action verb.
            if self.action != "report":
                raise ValueError("cancellation_metadata recover accepts only the report action")
            if self.operation_id is not None:
                raise ValueError("cancellation_metadata recover accepts no operation target")
            return
        if self.dry_run and self.action != "report":
            raise ValueError("dry-run recover cannot request an acting conclusion")


@dataclass(frozen=True)
class RecoverResult:
    """The strict two-variant result family returned by :meth:`Delivery.recover`: exactly the
    detail matching ``kind`` is present — the operation-conclusion report or the
    cancellation-metadata repair pass."""

    @dataclass(frozen=True)
    class MergedPrefix:
        node_id: str
        pr_number: int
        merge_commit_sha: str

    @dataclass(frozen=True)
    class RemainderPr:
        pr_number: int
        state: str
        head_sha: str

    @dataclass(frozen=True)
    class LandedLayer:
        node_id: str
        plan_id: str
        pr_number: int
        merge_commit_sha: str
        base_sha: str
        head_sha: str
        finalized: bool | None

    @dataclass(frozen=True)
    class Operation:
        operation_id: str
        kind: str
        prepared_created: str
        classification: str
        action: str
        detail: str
        merged_layers: tuple["RecoverResult.MergedPrefix", ...] = ()
        remainder: tuple["RecoverResult.RemainderPr", ...] = ()

    @dataclass(frozen=True)
    class SweepFailure:
        target: str
        error: str

    @dataclass(frozen=True)
    class AbandonPreview:
        operation_id: str
        kind: str
        prepared_created: str
        detail: str

    @dataclass(frozen=True)
    class AcceptPrefixPreview:
        operation_id: str
        prepared_created: str
        merged_layers: tuple["RecoverResult.MergedPrefix", ...]
        remainder: tuple["RecoverResult.RemainderPr", ...]
        detail: str

    @dataclass(frozen=True)
    class OperationConclusion:
        """The operation-conclusion report: additive operation-produced data — deliberately
        no combination guards."""

        objective_id: str
        objective_url: str
        redirected_from: str | None
        dry_run: bool
        selection_required: bool
        operations: tuple["RecoverResult.Operation", ...]
        swept_worktrees: tuple[str, ...]
        swept_refs: tuple[str, ...]
        sweep_failures: tuple["RecoverResult.SweepFailure", ...]
        sweep_skipped: str | None
        landed_layers: tuple["RecoverResult.LandedLayer", ...] = ()
        objective_closed: bool = False
        reconcile_evidence: "LandEvidence | None" = None
        notes: tuple[str, ...] = ()

    @dataclass(frozen=True)
    class CancellationAction:
        """One per-candidate repair outcome: ``applied | would_apply | skipped | failed``."""

        code: str
        node_id: str
        outcome: str
        error: str | None = None

    @dataclass(frozen=True)
    class CancellationMetadata:
        """The cancellation-metadata repair pass. ``failed`` names the aborting action and
        stays separate from ``actions``; ``unavailable`` carries the fresh-proof failure."""

        objective_id: str
        actions: tuple["RecoverResult.CancellationAction", ...]
        failed: "RecoverResult.CancellationAction | None"
        aborted: bool
        dry_run: bool
        unavailable: str | None = None

    kind: RecoverKind
    operation_conclusion: OperationConclusion | None = None
    cancellation_metadata: CancellationMetadata | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("operation_conclusion", "cancellation_metadata"):
            raise ValueError(f"unknown recover result kind: {self.kind!r}")
        if (self.operation_conclusion is not None) != (self.kind == "operation_conclusion") or (
            (self.cancellation_metadata is not None) != (self.kind == "cancellation_metadata")
        ):
            raise ValueError("recover result detail must match kind exactly")


type _RecoverConsent = Callable[
    [RecoverResult.AbandonPreview | RecoverResult.AcceptPrefixPreview], bool
]


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
    """A bounded delivery-façade failure with stable code and optional operation context."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        phase: DeliveryPhase | None = None,
        origin: DeliveryOrigin | None = None,
    ) -> None:
        if error_type not in _DELIVERY_ERROR_TYPES:
            allowed = ", ".join(sorted(_DELIVERY_ERROR_TYPES))
            raise ValueError(f"unknown delivery error type {error_type!r} (allowed: {allowed})")
        if (phase is None) != (origin is None):
            raise ValueError("delivery error phase and origin must be jointly present or absent")
        if phase is not None and phase not in ("layer", "cascade", "ready"):
            raise ValueError(f"unknown delivery error phase: {phase!r}")
        if origin is not None and origin not in ("domain", "git", "github", "delivery"):
            raise ValueError(f"unknown delivery error origin: {origin!r}")
        super().__init__(message)
        self.error_type = error_type
        self.phase = phase
        self.origin = origin


class DeliveryPersistence(ABC):
    """Aggregate status authority over objective, plan, and journal persistence."""

    @abstractmethod
    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        """Read one objective by backend-owned id."""
        ...

    @abstractmethod
    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Close one completed aggregate objective."""
        ...

    @abstractmethod
    def get_plan(self, *, issue_id: str) -> PlanState | None:
        """Read one plan by backend-owned id."""
        ...

    @abstractmethod
    def get_plan_body(self, *, issue_id: str) -> str | None:
        """Read one plan's verbatim body block."""
        ...

    @abstractmethod
    def update_plan_header(self, *, issue_id: str, fields: dict[str, object]) -> PlanHeaderUpdate:
        """Merge publication-owned fields into one plan header."""
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
    def normalize_transfer_carry_map(
        self, carry_map: tuple[tuple[str, str], ...]
    ) -> dict[str, str]:
        """Normalize raw transfer carries for the selected objective backend."""
        ...

    @abstractmethod
    def find_objective(self, *, run_id: str) -> ObjectiveRef | None:
        """Find one objective by its idempotence run id."""
        ...

    @abstractmethod
    def supersede_objective(
        self,
        *,
        old_objective_id: str,
        title: str,
        prose: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode],
        carry_map: dict[str, str],
        delivery: objective.DeliveryPolicy | None = None,
        delivery_lineage: str | None = None,
        close_predecessor: bool = True,
        dry_run: bool = False,
    ) -> ObjectiveRef | None:
        """Create or find the successor objective for one supersession."""
        ...

    @abstractmethod
    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool:
        """Finalize and close one converged predecessor/successor pair."""
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

    def native_cancellation_metadata_writer(self) -> "NativeCancellationMetadataWriter | None":
        """Expose the optional attachment-only cancellation writer (§8.54).

        A concrete neutral default — ``None`` IS the unsupported-backend posture, so only
        the persistence implementations that can actually offer the conditional writer
        override it. The returned Protocol stays package-internal: it is a capability of
        this authority, never a fourth public aggregate.
        """
        return None


class DeliveryGit(ABC):
    """Aggregate Git authority for status, Prepare, Transfer, and synchronization."""

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
    def push_with_exact_lease(self, branch: str, *, expected_remote_sha: str | None) -> None:
        """Push one branch under the exact observed remote lease."""
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
    def worktree_admin_paths(self) -> tuple[Path, ...]:
        """Return every path in Git's worktree administration inventory."""
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
    """Aggregate GitHub authority for status, Prepare, Transfer, and synchronization."""

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
    def pr_for_branch(self, branch: str) -> prs.PullRequest | None:
        """Read an all-state PR by head branch."""
        ...

    @abstractmethod
    def strict_stack(self, number: int) -> stacks.StackRestFacts | None:
        """Read the strict native stack containing one PR."""
        ...

    @abstractmethod
    def merge_async_probe(self, number: int, *, uuid: str) -> stacks.MergeAsyncProbe:
        """Probe one recorded asynchronous merge handle."""
        ...

    @abstractmethod
    def merged_evidence(self, number: int) -> stacks.PrMergedEvidence | None:
        """Read strict post-merge evidence for one PR."""
        ...

    @abstractmethod
    def get_pr(self, number: int) -> prs.PullRequest | None:
        """Read one PR by number."""
        ...

    @abstractmethod
    def create_pr(
        self, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> prs.PullRequest:
        """Create or find the PR for one branch."""
        ...

    @abstractmethod
    def update_pr_body(self, number: int, *, body: str) -> prs.PrBodyUpdate:
        """Replace one PR body."""
        ...

    @abstractmethod
    def update_pr_base(self, number: int, *, base: str) -> None:
        """Retarget one PR."""
        ...

    @abstractmethod
    def reopen_pr(self, number: int) -> None:
        """Reopen one closed PR."""
        ...

    @abstractmethod
    def mark_pr_ready(self, number: int) -> None:
        """Convert one draft PR to ready-for-review."""
        ...

    @abstractmethod
    def create_stack(self, pull_requests: tuple[int, ...]) -> stacks.StackMutationOutcome:
        """Create a native stack with members in bottom-to-top order."""
        ...

    @abstractmethod
    def append_stack(
        self, stack_number: int, *, pull_requests: tuple[int, ...]
    ) -> stacks.StackMutationOutcome:
        """Append one suffix to an existing native stack."""
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


@dataclass(frozen=True)
class _SnapshotObjectiveReader:
    """Serve the captured replan objective while delegating any unexpected identity read."""

    objective_id: str
    state: ObjectiveState
    fallback: DeliveryPersistence

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        requested = objective_id.strip().lstrip("#").strip()
        captured_ids = {self.objective_id, self.state.id.strip().lstrip("#").strip()}
        if requested in captured_ids:
            return self.state
        return self.fallback.get_objective(objective_id=objective_id)


class Delivery:
    """Repository-scoped delivery operations over three aggregate authorities."""

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

    def _reconstruct_train_status(self, _repo_root: Path, objective_id: str) -> train.TrainStatus:
        """Recover the original reconstruction cause where transfer/recover need it."""
        try:
            result = self.status(StatusRequest(objective_id=objective_id))
        except DeliveryError as exc:
            cause = exc.__cause__
            if isinstance(
                cause,
                (
                    train.TrainReconstructionError,
                    ObjectiveStoreError,
                    IssueBackendError,
                    TrainPersistenceError,
                ),
            ):
                raise cause from exc
            raise
        if result.train is not None:
            return result.train
        return train.NoDeliveryTrain(
            objective_id=result.objective_id,
            objective_url=result.objective_url,
            redirected_from=result.redirected_from,
            reason=result.no_train_reason or "no delivery train",
        )

    def transfer(self, request: TransferRequest) -> TransferResult:
        """Transfer one objective replan intent behind the aggregate authorities."""
        from perk.delivery import transfer as transfer_mod  # noqa: PLC0415 — façade/engine cycle

        runtime = transfer_mod._DEFAULT_TRANSFER_RUNTIME
        seams = transfer_mod.TransferSeams(
            repo_root=self._git.repo_root,
            store=self._persistence,
            issues=self._persistence,
            persistence=self._persistence,
            reconstruct=self._reconstruct_train_status,
            now=runtime.now,
        )
        fresh = transfer_mod._FreshTransfer(
            seams=seams,
            git=self._git,
            github=self._github,
            normalize_transfer_carry_map=self._persistence.normalize_transfer_carry_map,
        )
        try:
            return transfer_mod._dispatch(fresh, request, runtime=runtime)
        except DeliveryError:
            raise
        except train.TrainReconstructionError as exc:
            raise DeliveryError(str(exc), error_type=exc.error_type) from exc
        except JournalCorruptionError as exc:
            raise DeliveryError(str(exc), error_type="journal_corruption") from exc
        except git_mod.GitError as exc:
            raise DeliveryError(str(exc), error_type="git_error") from exc
        except (GitHubError, IssueBackendError, TrainPersistenceError) as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc
        except ObjectiveStoreError as exc:
            raise DeliveryError(
                f"objective create failed\n{exc}", error_type="github_error"
            ) from exc

    def recover(
        self,
        request: RecoverRequest,
        *,
        consent: _RecoverConsent | None = None,
    ) -> RecoverResult:
        """Conclude interrupted operations — or run the isolated cancellation-metadata
        repair — through the aggregate delivery authorities."""
        from perk.delivery import recover as recover_mod  # noqa: PLC0415 — façade/engine cycle
        from perk.delivery import sync as sync_mod  # noqa: PLC0415 — shared runtime error

        if request.kind == "cancellation_metadata" and consent is not None:
            raise ValueError(
                "cancellation_metadata recover has no confirmation boundary — consent must be None"
            )
        context = recover_mod._RecoverContext(
            repo_root=self._git.repo_root,
            persistence=self._persistence,
            git=self._git,
            github=self._github,
            reconstruct=self._reconstruct_train_status,
            runtime=recover_mod._DEFAULT_RECOVER_RUNTIME,
        )
        try:
            return recover_mod._dispatch(context, request, consent=consent)
        except DeliveryError:
            raise
        except train.TrainReconstructionError as exc:
            code = exc.error_type if exc.error_type in _DELIVERY_ERROR_TYPES else "github_error"
            raise DeliveryError(str(exc), error_type=code) from exc
        except JournalCorruptionError as exc:
            raise DeliveryError(str(exc), error_type="journal_corruption") from exc
        except JournalRecordTooLarge as exc:
            raise DeliveryError(str(exc), error_type="journal_record_too_large") from exc
        except git_mod.GitError as exc:
            raise DeliveryError(str(exc), error_type="git_error") from exc
        except sync_mod.SyncConfigurationError as exc:
            raise DeliveryError(str(exc), error_type="invalid_config") from exc
        except (GitHubError, IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc

    def publish(self, request: PublishRequest) -> PublishResult:
        """Publish one layer or open one layer's PR for review."""
        from perk.delivery import publish as publish_mod  # noqa: PLC0415 — façade/engine cycle

        context = publish_mod._PublishContext(
            repo_root=self._git.repo_root,
            persistence=self._persistence,
            git=self._git,
            github=self._github,
            status=self.status,
            sync=self.sync,
        )
        try:
            return publish_mod._dispatch(
                context, request, runtime=publish_mod._DEFAULT_PUBLISH_RUNTIME
            )
        except DeliveryError as exc:
            if exc.phase is not None:
                raise
            if request.kind == "layer":
                raise DeliveryError(
                    str(exc),
                    error_type="delivery_error",
                    phase="layer",
                    origin="delivery",
                ) from exc
            cause = exc.__cause__
            if isinstance(cause, train.TrainReconstructionError):
                raise DeliveryError(
                    str(cause),
                    error_type=cause.error_type,
                    phase="ready",
                    origin="domain",
                ) from exc
            if isinstance(cause, (IssueBackendError, ObjectiveStoreError, TrainPersistenceError)):
                raise DeliveryError(
                    str(exc),
                    error_type="github_error",
                    phase="ready",
                    origin="github",
                ) from exc
            raise DeliveryError(
                str(exc),
                error_type="delivery_error",
                phase="ready",
                origin="delivery",
            ) from exc
        except publish_mod.PublicationError as exc:
            raise DeliveryError(
                str(exc),
                error_type=exc.error_type,
                phase="layer",
                origin="domain",
            ) from exc
        except layer_mod.LayerError as exc:
            if request.kind != "ready":
                raise
            raise DeliveryError(
                str(exc),
                error_type=exc.error_type,
                phase="ready",
                origin="domain",
            ) from exc
        except git_mod.PushRejectedError as exc:
            raise DeliveryError(
                str(exc),
                error_type="push_rejected",
                phase="layer",
                origin="git",
            ) from exc
        except git_mod.GitError as exc:
            raise DeliveryError(
                str(exc), error_type="git_error", phase="layer", origin="git"
            ) from exc
        except (GitHubError, IssueBackendError) as exc:
            phase: DeliveryPhase = "layer" if request.kind == "layer" else "ready"
            raise DeliveryError(
                str(exc), error_type="github_error", phase=phase, origin="github"
            ) from exc
        except ObjectiveStoreError as exc:
            if request.kind == "layer":
                raise DeliveryError(
                    str(exc),
                    error_type="delivery_error",
                    phase="layer",
                    origin="delivery",
                ) from exc
            raise DeliveryError(
                str(exc), error_type="github_error", phase="ready", origin="github"
            ) from exc
        except train.TrainReconstructionError as exc:
            if request.kind != "layer":
                raise
            raise DeliveryError(
                str(exc),
                error_type="delivery_error",
                phase="layer",
                origin="delivery",
            ) from exc
        except (TrainPersistenceError, JournalCorruptionError) as exc:
            if request.kind == "layer":
                raise DeliveryError(
                    str(exc),
                    error_type="delivery_error",
                    phase="layer",
                    origin="delivery",
                ) from exc
            raise DeliveryError(
                str(exc), error_type="github_error", phase="ready", origin="github"
            ) from exc
        except JournalRecordTooLarge as exc:
            if request.kind != "layer":
                raise
            raise DeliveryError(
                str(exc),
                error_type="journal_record_too_large",
                phase="layer",
                origin="delivery",
            ) from exc

    def sync(self, request: SyncRequest, *, consent: _SyncConsent | None) -> SyncResult:
        """Synchronize a published suffix with an explicitly selected consent policy."""
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
        if request.kind == "replan":
            return self._prepare_replan(request)
        if request.kind == "plan_identity":
            return self._prepare_plan_identity(request)
        if request.mode == "planning":
            return self._prepare_planning(request)
        return self._prepare_execution(request)

    def _prepare_replan(self, request: PrepareRequest) -> PrepareResult:
        from perk.delivery import sync as sync_mod  # noqa: PLC0415 — façade/engine cycle

        objective_id = request.objective_id
        if objective_id is None:
            raise ValueError("validated replan request lost objective_id")
        bare = objective_id.strip().lstrip("#").strip()
        try:
            state = self._persistence.get_objective(objective_id=bare)
        except (ObjectiveStoreError, IssueBackendError, TrainPersistenceError) as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc
        if state is None:
            raise DeliveryError(f"Objective {bare} not found", error_type="objective_not_found")
        superseded_by = state.header.get("superseded_by")
        if superseded_by:
            raise DeliveryError(
                f"Objective {bare} is already superseded by {superseded_by}; "
                "replan its successor instead.",
                error_type="objective_not_open",
            )
        if state.state != "open":
            raise DeliveryError(
                f"Objective {bare} is not open (state={state.state}); replan re-authors an "
                "OPEN objective. Create a fresh objective instead.",
                error_type="objective_not_open",
            )
        try:
            policy = objective.delivery_policy(state.header)
        except ValueError as exc:
            raise DeliveryError(str(exc), error_type="invalid_delivery_policy") from exc

        raw_base = state.header.get("base")
        base = raw_base if isinstance(raw_base, str) and raw_base else None
        raw_lineage = state.header.get("delivery_lineage")
        lineage = raw_lineage if isinstance(raw_lineage, str) and raw_lineage else None
        if policy is objective.DeliveryPolicy.INCREMENTAL:
            context = PrepareResult.ReplanContext(
                objective_id=state.id,
                objective_url=state.url,
                objective_title=state.title,
                nodes=state.nodes,
                delivery="incremental",
                base=base,
                delivery_lineage=lineage,
                claimed=(),
                open_pr_plans=(),
            )
            return PrepareResult(kind="replan", replan=context)

        try:
            fold = self._persistence.read_journal(bare)
        except JournalCorruptionError as exc:
            raise DeliveryError(str(exc), error_type="journal_corruption") from exc
        except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc
        if fold.unresolved:
            op = fold.unresolved[0]
            if op.kind is OperationKind.TRANSFER:
                raise DeliveryError(
                    f"An interrupted replan transfer (operation {op.operation_id}) is "
                    f"unresolved on objective {bare} — conclude it with "
                    f"`perk objective stack recover {bare}` before replanning.",
                    error_type="transfer_incomplete",
                )
            raise DeliveryError(
                f"Operation {op.operation_id} ({op.kind.value}) is unresolved on objective "
                f"{bare} — conclude it via `perk objective stack recover {bare}` or the "
                "owning command before replanning.",
                error_type="unresolved_operation",
            )

        status_result = self._status_with_store(
            StatusRequest(objective_id=bare),
            store=_SnapshotObjectiveReader(bare, state, self._persistence),
        )
        status = status_result.train
        if status is None:
            raise DeliveryError(
                f"Objective {bare} classified stacked but reconstructs no delivery train "
                f"({status_result.no_train_reason}) — broken stored state; repair before "
                "replanning.",
                error_type="invalid_train",
            )
        try:
            sync_mod.refuse_structural_blockers(status)
            claimed = sync_mod.derive_claimed_prefix(status)
        except sync_mod.SyncError as exc:
            raise DeliveryError(str(exc), error_type=exc.error_type) from exc
        context = PrepareResult.ReplanContext(
            objective_id=state.id,
            objective_url=state.url,
            objective_title=state.title,
            nodes=state.nodes,
            delivery="stacked",
            base=status.base,
            delivery_lineage=status.delivery_lineage,
            claimed=tuple(
                PrepareResult.ReplanClaim(
                    node_id=layer.node_id,
                    plan_id=layer.plan_id,
                    branch=layer.branch,
                    pr_number=layer.pr_number,
                )
                for layer in claimed
            ),
            open_pr_plans=tuple(
                (layer.plan_id, layer.pr_number)
                for layer in status.layers
                if layer.plan_id is not None
                and layer.pr_number is not None
                and layer.pr in (train.LayerPr.DRAFT, train.LayerPr.READY, train.LayerPr.WRONG_BASE)
            ),
        )
        return PrepareResult(kind="replan", replan=context)

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
        return self._status_with_store(request, store=self._persistence)

    def _status_with_store(
        self,
        request: StatusRequest,
        *,
        store: train.ObjectiveReader,
    ) -> StatusResult:
        """Run the shared status boundary with an explicit objective-read authority."""
        try:
            status = train.reconstruct_train(
                request.objective_id,
                store=store,
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
