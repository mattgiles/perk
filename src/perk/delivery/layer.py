"""``LayerContext`` + the one parent-preparation path (contracts.md §8.46).

The internal immutable layer-start core backs execution Prepare and deferred publication:
derive one frozen :class:`LayerContext` from the reconstructed
:class:`~perk.delivery.train.DeliveryTrain`, require the layer to be the readiness-derived
candidate, then fetch and verify the **latest** parent head (:func:`prepare_layer_start` — always
the live remote head, never a stored checkpoint; later movement of the parent is a normal
implementation danger, not a pinned SHA).

The parent-preparation helper is callback-driven and has no repository/global defaults:
execution supplies aggregate Git methods while deferred publication supplies closures over its
injected seams. :class:`LayerContextOut` is the serialization boundary of the session-scoped
operational record ``.perk/workflow/layer-context.json``
(written by ``perk.state.cache.write_layer_context``) — NEVER authoritative: publication
re-verifies live, and the durable checkpoint pair stays publication-owned.
"""

from collections.abc import Callable
from dataclasses import dataclass

from perk.boundary import OutputModel
from perk.delivery.train import (
    STRUCTURAL_BLOCKER_CODES,
    DeliveryTrain,
    LayerPublication,
    TrainLayer,
)
from perk.substrate import git as git_mod


class LayerError(Exception):
    """A layer derivation or parent preparation failed. ``error_type`` is the stable machine
    code the consumers map onto their failure envelopes."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # unknown_layer | stacked_predecessor_missing | node_not_build_ready
        # | layer_not_published | unresolved_operation | structural_blockers
        # | parent_missing | parent_unverified | git_error
    ) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class LayerContext:
    """One stacked layer's immutable start facts, derived fresh from the train projection.

    ``base`` is the objective integration branch; ``parent_branch`` equals ``base`` for the
    bottom layer and the predecessor layer's branch for a child (the train's branch
    resolution: plan-header ``branch`` else the ``plan-<plan-id>`` convention); ``branch`` is
    this layer's own canonical ``plan-<plan_id>`` branch — the branch creation actually makes.
    """

    objective_id: str
    node_id: str
    plan_id: str
    delivery_lineage: str | None
    predecessor_plan_id: str | None
    base: str
    parent_branch: str
    branch: str


@dataclass(frozen=True)
class PreparedLayerStart:
    """The verified layer start: the context plus the parent head commit the layer branches
    from (resolved locally after the fetch — a real commit, not a moving ref)."""

    context: LayerContext
    parent_sha: str


class LayerContextOut(OutputModel):
    """The ``.perk/workflow/layer-context.json`` serialization boundary (the session-scoped
    operational parent-checkpoint record; contracts.md §8.46). Field order load-bearing."""

    objective_id: str
    node_id: str
    plan_id: str
    delivery_lineage: str | None
    predecessor_plan_id: str | None
    base: str
    parent_branch: str
    branch: str
    parent_sha: str
    prepared_at: str

    @classmethod
    def from_domain(
        cls, ctx: LayerContext, *, parent_sha: str, prepared_at: str
    ) -> "LayerContextOut":
        """Project the frozen :class:`LayerContext` + the verified parent SHA onto the
        boundary."""
        return cls(
            objective_id=ctx.objective_id,
            node_id=ctx.node_id,
            plan_id=ctx.plan_id,
            delivery_lineage=ctx.delivery_lineage,
            predecessor_plan_id=ctx.predecessor_plan_id,
            base=ctx.base,
            parent_branch=ctx.parent_branch,
            branch=ctx.branch,
            parent_sha=parent_sha,
            prepared_at=prepared_at,
        )


def _bare(identifier: str) -> str:
    """Strip one leading ``#`` (the canonical-rendering normalization for id comparisons)."""
    return identifier.removeprefix("#")


def derive_layer_context(train: DeliveryTrain, *, plan_id: str) -> LayerContext:
    """Derive the :class:`LayerContext` for the layer whose plan is ``plan_id``. Pure.

    Raises :class:`LayerError` (``unknown_layer``) when the plan is not a layer of the train,
    and (``stacked_predecessor_missing``) when a non-bottom layer's predecessor carries no
    plan/branch to parent from.
    """
    wanted = _bare(plan_id)
    for index, layer in enumerate(train.layers):
        if layer.plan_id is None or _bare(layer.plan_id) != wanted:
            continue
        if index == 0:
            parent_branch = train.base
        else:
            predecessor = train.layers[index - 1]
            if predecessor.branch is None:
                raise LayerError(
                    f"layer {layer.node_id} (plan #{wanted}) has no parent branch: its "
                    f"predecessor layer {predecessor.node_id} carries no plan/branch",
                    error_type="stacked_predecessor_missing",
                )
            parent_branch = predecessor.branch
        return LayerContext(
            objective_id=train.objective_id,
            node_id=layer.node_id,
            plan_id=wanted,
            delivery_lineage=train.delivery_lineage,
            predecessor_plan_id=None if index == 0 else train.layers[index - 1].plan_id,
            base=train.base,
            parent_branch=parent_branch,
            # This layer's branch is CANONICAL (`plan-<plan_id>`): both creation gestures
            # create exactly that branch, so the context must describe it — only the
            # PREDECESSOR's parent_branch uses the train's header-or-convention resolution
            # (an already-published branch is observed, never created).
            branch=f"plan-{wanted}",
        )
    raise LayerError(
        f"plan #{wanted} is not a layer of objective {train.objective_id}'s delivery train",
        error_type="unknown_layer",
    )


def require_ready_layer(train: DeliveryTrain, *, plan_id: str) -> LayerContext:
    """Derive the layer context AND require the layer to BE the readiness-derived candidate.

    The shared creation gate (contracts.md §8.46): a layer may only start when the train's
    build readiness is ``ready`` and names exactly this layer's node — else a typed
    ``node_not_build_ready`` :class:`LayerError` carrying the exact veto.
    """
    ctx = derive_layer_context(train, plan_id=plan_id)
    readiness = train.build_readiness
    if not readiness.ready:
        raise LayerError(
            f"layer {ctx.node_id} (plan #{ctx.plan_id}) is not build-ready: {readiness.reason}",
            error_type="node_not_build_ready",
        )
    if readiness.next_node_id != ctx.node_id:
        raise LayerError(
            f"layer {ctx.node_id} (plan #{ctx.plan_id}) is not the build-ready candidate — "
            f"the next build-ready layer is {readiness.next_node_id}",
            error_type="node_not_build_ready",
        )
    return ctx


def require_reviewable_layer(train: DeliveryTrain, *, plan_id: str, mutating: bool) -> TrainLayer:
    """Require the target layer to be a verified publication before opening review.

    A mutation additionally requires no unresolved train operation and no structural
    identity/topology blocker. Operational drift on other layers is intentionally ignored;
    the target's publication classification already incorporates every target-local axis.
    """
    ctx = derive_layer_context(train, plan_id=plan_id)
    target = next(layer for layer in train.layers if layer.node_id == ctx.node_id)
    if target.publication is not LayerPublication.PUBLISHED:
        axes = (
            f"publication={target.publication.value}, git={target.git.value}, "
            f"pr={target.pr.value}, membership={target.membership.value}"
        )
        findings = [
            finding
            for finding in train.findings
            if finding.node_id == target.node_id
            or (finding.plan_id is not None and finding.plan_id.removeprefix("#") == ctx.plan_id)
        ]
        detail = "; ".join(f"[{finding.code}] {finding.message}" for finding in findings)
        suffix = f"; findings: {detail}" if detail else "; findings: none"
        raise LayerError(
            f"layer {target.node_id} (plan #{ctx.plan_id}) is not a verified publication "
            f"({axes}{suffix})",
            error_type="layer_not_published",
        )
    if not mutating:
        return target
    if train.unresolved_operations:
        detail = "; ".join(
            f"{operation.operation_id} ({operation.kind}, prepared {operation.prepared_created})"
            for operation in train.unresolved_operations
        )
        raise LayerError(
            f"review publication is blocked by unresolved operation(s): {detail}",
            error_type="unresolved_operation",
        )
    structural = [finding for finding in train.blockers if finding.code in STRUCTURAL_BLOCKER_CODES]
    if structural:
        detail = "; ".join(f"[{finding.code}] {finding.message}" for finding in structural)
        raise LayerError(
            f"review publication is blocked by structural train findings: {detail}",
            error_type="structural_blockers",
        )
    return target


def prepare_layer_start(
    ctx: LayerContext,
    *,
    fetch: Callable[[tuple[str, ...]], None],
    remote_head: Callable[[str], str | None],
    resolve_commit: Callable[[str], str | None],
) -> PreparedLayerStart:
    """Fetch and verify the **latest** parent head the layer starts from.

    Fetches exactly the parent ref, reads the live remote head, and verifies the commit
    resolves locally after the fetch — always the LATEST head, never a stored checkpoint. An
    absent remote parent branch is a typed ``parent_missing`` error naming the expected ref;
    a head that fails to resolve locally after the fetch is ``parent_unverified``; a Git
    infra failure is ``git_error``.
    """
    try:
        fetch((ctx.parent_branch,))
        sha = remote_head(ctx.parent_branch)
    except git_mod.GitError as exc:
        raise LayerError(
            f"could not observe the parent branch refs/heads/{ctx.parent_branch} on origin: {exc}",
            error_type="git_error",
        ) from exc
    if sha is None:
        raise LayerError(
            f"expected the parent branch refs/heads/{ctx.parent_branch} on origin; observed "
            f"no such remote branch — layer {ctx.node_id} cannot start without its parent",
            error_type="parent_missing",
        )
    resolved = resolve_commit(sha)
    if resolved is None:
        raise LayerError(
            f"the parent head {sha} (refs/heads/{ctx.parent_branch}) does not resolve "
            "locally after the fetch — cannot verify the layer start commit",
            error_type="parent_unverified",
        )
    return PreparedLayerStart(context=ctx, parent_sha=resolved)
