"""``LayerContext`` + the one parent-preparation path (contracts.md §8.46).

The shared immutable layer-start contract both execution paths consume — local worktree
creation (``perk.run.launch.worktree.resolve_worktree``) and remote positioning
(``perk.run.run_worker.position_branch``): derive one frozen :class:`LayerContext` from the
reconstructed :class:`~perk.delivery.train.DeliveryTrain`, require the layer to be the
readiness-derived candidate, then fetch and verify the **latest** parent head
(:func:`prepare_layer_start` — always the live remote head, never a stored checkpoint; later
movement of the parent is a normal implementation danger, not a pinned SHA).

A delivery leaf touching ``perk.substrate.git`` (alongside ``observe.py`` + ``capability.py``,
contracts.md §8.44); the probe callables are keyword-injectable (production defaults; tests
pass fakes — the ``capability.py`` precedent). :class:`LayerContextOut` is the serialization
boundary of the session-scoped operational record ``.perk/workflow/layer-context.json``
(written by ``perk.state.cache.write_layer_context``) — NEVER authoritative: publication
re-verifies live, and the durable checkpoint pair stays publication-owned.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk.boundary import OutputModel
from perk.delivery.train import DeliveryTrain
from perk.substrate import git as git_mod


class LayerError(Exception):
    """A layer derivation or parent preparation failed. ``error_type`` is the stable machine
    code the consumers map onto their failure envelopes."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # unknown_layer | stacked_predecessor_missing | node_not_build_ready
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
    this layer's own ``plan-<plan_id>`` branch.
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
            branch=layer.branch if layer.branch is not None else f"plan-{wanted}",
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


def _default_fetch(repo: Path, refspecs: list[str]) -> None:
    git_mod.fetch_refspecs(repo, refspecs)


def prepare_layer_start(
    repo_root: Path,
    ctx: LayerContext,
    *,
    fetch: Callable[[Path, list[str]], None] = _default_fetch,
    remote_head: Callable[[Path, str], str | None] = git_mod.remote_branch_head,
    resolve_commit: Callable[[Path, str], str | None] = git_mod.resolve_commit,
) -> PreparedLayerStart:
    """Fetch and verify the **latest** parent head the layer starts from.

    Fetches exactly the parent ref, reads the live remote head, and verifies the commit
    resolves locally after the fetch — always the LATEST head, never a stored checkpoint. An
    absent remote parent branch is a typed ``parent_missing`` error naming the expected ref;
    a head that fails to resolve locally after the fetch is ``parent_unverified``; a Git
    infra failure is ``git_error``.
    """
    try:
        fetch(repo_root, [ctx.parent_branch])
        sha = remote_head(repo_root, ctx.parent_branch)
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
    resolved = resolve_commit(repo_root, sha)
    if resolved is None:
        raise LayerError(
            f"the parent head {sha} (refs/heads/{ctx.parent_branch}) does not resolve "
            "locally after the fetch — cannot verify the layer start commit",
            error_type="parent_unverified",
        )
    return PreparedLayerStart(context=ctx, parent_sha=resolved)
