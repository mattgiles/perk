"""The delivery **publish** operation — stacked layer publication (contracts.md §8.47).

The gateway-touching delivery leaf `/submit` routes a stacked plan through (alongside
``observe.py`` / ``capability.py`` / ``layer.py``, contracts.md §8.44): exact-lease branch
publication, PR create/converge onto the expected parent, native stack create/append with
prepared-operation idempotency, a full remote refetch, and checkpoints written only **after**
verification. The private engine is bound to one façade-owned aggregate context and one immutable
non-authority runtime. Automatic suffix propagation calls that same ``Delivery`` instance's bound
``sync`` method with raw trigger context; publication itself acquires no operation lock.

The concurrency contract: mutations are strictly serialized in-process (sequential); the
cross-machine serialization is the one-unresolved-operation journal gate plus the exact push
lease — the remote itself arbitrates competing writers. Failures leave the prepared operation
**unresolved** (recoverable, blocking successor readiness) rather than guessing; only the pure
no-op convergence returns without touching the journal.
"""

import contextlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Never, Protocol, cast

from perk import plan
from perk.backends.issue_backend import IssueBackendError, PlanHeaderUpdate, PlanState
from perk.delivery import sync as sync_mod
from perk.delivery.facade import (
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    PublishRequest,
    PublishResult,
    StatusRequest,
    StatusResult,
    SyncRequest,
    SyncResult,
    _normalize_publish_plan_id,
)
from perk.delivery.journal import (
    EventRole,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
    mint_operation_id,
)
from perk.delivery.layer import (
    LayerContext,
    LayerError,
    derive_layer_context,
    prepare_layer_start,
    require_ready_layer,
    require_reviewable_layer,
)
from perk.delivery.persistence import (
    UnresolvedOperationError,
)
from perk.delivery.train import (
    DeliveryTrain,
    NoDeliveryTrain,
    PrFactsView,
    TrainReconstructionError,
    TrainStatus,
)
from perk.github import GitHubError, prs, stacks
from perk.substrate import git as git_mod

# The post-mutation settling interval before the one bounded mutation retry.
_SETTLE_SECONDS = 2.0
# The pre-mutation convergence wait: attempts x delay before `remote_settling_timeout`.
_CONVERGE_ATTEMPTS = 5
_CONVERGE_DELAY_SECONDS = 2.0
# `Retry-After` is honored once, capped (a rate limiter asking for more waits too long for an
# interactive submit — the operation stays recoverable either way).
_RETRY_AFTER_CAP_SECONDS = 60


class PublicationError(Exception):
    """A layer publication failed or refused. ``error_type`` is the stable machine code the
    submit boundary maps onto its failure envelope (the ``LayerError`` shape)."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # not_stacked | unresolved_operation | node_not_build_ready
        # | stack_capability_lost | remote_drift | stale_parent
        # | push_rejected | pr_already_merged | remote_settling_timeout
        # | stack_registration_drift | stack_registration_failed | postcondition_unverified
        # | publication_drift | git_error | github_error — plus the §8.46 layer codes passed
        # through verbatim: parent_missing | parent_unverified | stacked_predecessor_missing
        # (contracts.md §8.47 declares the full bounded set)
    ) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class _TrainRowFacts:
    """One train-context row the PR-body composer renders (bottom→top order)."""

    node_id: str
    plan_id: str | None
    pr_number: int | None
    current: bool


@dataclass(frozen=True)
class _LayerBodyFacts:
    """What the stacked PR-body composer receives: this layer's 1-based ``position`` in the
    ``total``-layer train, its parent branch, the objective integration base, and one row per
    layer bottom→top. Non-authoritative presentation material — the train is the authority."""

    node_id: str
    position: int
    total: int
    parent_branch: str
    objective_base: str
    objective_id: str
    rows: tuple[_TrainRowFacts, ...]


# ----------------------------------------------------------------- injected-seam protocols
# The gateway callables are keyword-only, so plain `Callable` cannot type them — each seam
# gets a minimal Protocol (production defaults satisfy them; tests pass fakes).


class _PrFactsRead(Protocol):
    def __call__(self, *, number: int, repo_root: Path) -> stacks.PrDeliveryFacts | None: ...


class _FindPrForBranch(Protocol):
    def __call__(self, *, branch: str, repo_root: Path) -> prs.PullRequest | None: ...


class _StackRead(Protocol):
    def __call__(self, *, number: int, repo_root: Path) -> stacks.StackRestFacts | None: ...


class _ValidateBody(Protocol):
    def __call__(self, body: str, *, pr_number: int) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class _PublishRuntime:
    """The replaceable non-authority runtime used by publication tests."""

    mint_operation_id: Callable[[], str]
    now: Callable[[], str]
    sleep: Callable[[float], None]
    validate_pr_body: _ValidateBody


_DEFAULT_PUBLISH_RUNTIME = _PublishRuntime(
    mint_operation_id=mint_operation_id,
    now=plan.now_iso,
    sleep=time.sleep,
    validate_pr_body=prs.validate_pr_body,
)


@dataclass(frozen=True)
class _PublishContext:
    """One façade-bound publication context over the three aggregate authorities."""

    repo_root: Path
    persistence: DeliveryPersistence
    git: DeliveryGit
    github: DeliveryGitHub
    status: Callable[[StatusRequest], StatusResult]
    sync: Callable[..., SyncResult]


def _raw_git_failure(exc: Exception) -> Never:
    if isinstance(exc, TrainReconstructionError) and isinstance(exc.__cause__, git_mod.GitError):
        raise exc.__cause__
    raise exc


def _raw_github_failure(exc: Exception) -> Never:
    if isinstance(exc, TrainReconstructionError) and isinstance(exc.__cause__, GitHubError):
        raise exc.__cause__
    raise exc


@dataclass(frozen=True)
class _Publication:
    """One request's immutable state; effects stay on its aggregate context and runtime."""

    context: _PublishContext
    runtime: _PublishRuntime
    plan_id: str
    run_id: str
    trigger_run_id: str | None
    plan_state: PlanState
    plan_body: str | None


def _compose_body(pub: _Publication, facts: _LayerBodyFacts, pr_number: int | None) -> str:
    return _compose_stacked_pr_body(
        issue=pub.plan_id,
        plan_body=pub.plan_body,
        facts=facts,
        pr_number=pr_number,
    )


def _header_fields(pub: _Publication, pr_number: int) -> dict[str, object]:
    fields: dict[str, object] = {
        "branch": f"plan-{pub.plan_id}",
        "pr": str(pr_number),
        "lifecycle_stage": plan.LifecycleStage.IMPL.value,
    }
    if pub.trigger_run_id is not None:
        merged = plan.merge_untrusted_str_list(
            pub.plan_state.header.get("impl_run_ids"), pub.trigger_run_id
        )
        fields["impl_run_ids"] = list(merged)
    return fields


def _reconstruct(pub: _Publication, objective_id: str) -> TrainStatus:
    try:
        result = pub.context.status(StatusRequest(objective_id=objective_id))
    except DeliveryError as exc:
        raise DeliveryError(
            str(exc),
            error_type="delivery_error",
            phase="layer",
            origin="delivery",
        ) from exc
    if result.train is not None:
        return result.train
    return NoDeliveryTrain(
        objective_id=result.objective_id,
        objective_url=result.objective_url,
        redirected_from=result.redirected_from,
        reason=result.no_train_reason or "unknown",
    )


def _pr_facts(pub: _Publication, number: int) -> PrFactsView | None:
    try:
        return pub.context.github.pr_facts(number)
    except TrainReconstructionError as exc:
        _raw_github_failure(exc)


def _stack_read(pub: _Publication, number: int) -> stacks.StackRestFacts | None:
    try:
        return pub.context.github.strict_stack(number)
    except TrainReconstructionError as exc:
        _raw_github_failure(exc)


def _fetch(pub: _Publication, refs: tuple[str, ...]) -> None:
    try:
        pub.context.git.fetch_refs(refs)
    except TrainReconstructionError as exc:
        _raw_git_failure(exc)


def _remote_head(pub: _Publication, branch: str) -> str | None:
    try:
        return pub.context.git.remote_branch_sha(branch)
    except TrainReconstructionError as exc:
        _raw_git_failure(exc)


def _local_head(pub: _Publication, ref: str) -> str | None:
    try:
        return pub.context.git.resolve_commit(ref)
    except TrainReconstructionError as exc:
        _raw_git_failure(exc)


def _pr_for_branch(pub: _Publication, branch: str) -> prs.PullRequest | None:
    try:
        return pub.context.github.pr_for_branch(branch)
    except TrainReconstructionError as exc:
        _raw_github_failure(exc)


@dataclass(frozen=True)
class _PublishProofAdapter:
    """Adapt aggregate reads only to the narrow recovery-proof protocol."""

    publication: _Publication

    @property
    def repo_root(self) -> Path:
        return self.publication.context.repo_root

    @property
    def pr_facts(self) -> _PrFactsRead:
        return self._pr_facts

    @property
    def stack_read(self) -> _StackRead:
        return self._stack_read

    @property
    def remote_head(self) -> Callable[[Path, str], str | None]:
        return self._remote_head

    @property
    def pr_for_branch(self) -> _FindPrForBranch:
        return self._pr_for_branch

    def _pr_facts(self, *, number: int, repo_root: Path) -> stacks.PrDeliveryFacts | None:
        del repo_root
        facts = _pr_facts(self.publication, number)
        if facts is None:
            return None
        return stacks.PrDeliveryFacts(
            number=facts.number,
            state=facts.state,
            is_draft=facts.is_draft,
            base_ref=facts.base_ref,
            head_ref=facts.head_ref,
            head_sha=facts.head_sha,
        )

    def _stack_read(self, *, number: int, repo_root: Path) -> stacks.StackRestFacts | None:
        del repo_root
        return _stack_read(self.publication, number)

    def _remote_head(self, repo_root: Path, branch: str) -> str | None:
        del repo_root
        return _remote_head(self.publication, branch)

    def _pr_for_branch(self, *, branch: str, repo_root: Path) -> prs.PullRequest | None:
        del repo_root
        return _pr_for_branch(self.publication, branch)


def _dispatch(
    context: _PublishContext,
    request: PublishRequest,
    *,
    runtime: _PublishRuntime,
) -> PublishResult:
    """Dispatch one closed Publish request before touching any authority on dry-run arms."""
    wanted = _normalize_publish_plan_id(request.plan_id)
    if request.dry_run:
        if request.kind == "layer":
            return PublishResult(
                kind="layer",
                plan_id=wanted,
                dry_run=True,
                layer=PublishResult.Layer(
                    pr=prs.PullRequest(
                        number=0,
                        url="(dry-run)",
                        is_draft=True,
                        state="OPEN",
                        existed=False,
                    ),
                    branch=f"plan-{wanted}",
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
        return PublishResult(
            kind="ready",
            plan_id=wanted,
            dry_run=True,
            ready=PublishResult.Ready(
                pr=prs.PullRequest(
                    number=0,
                    url="(dry-run)",
                    is_draft=True,
                    state="OPEN",
                    existed=True,
                ),
                was_draft=True,
            ),
        )
    if request.kind == "ready":
        return _ready(context, request)

    plan_state = context.persistence.get_plan(issue_id=wanted)
    if plan_state is None:
        raise PublicationError(
            f"plan #{wanted} not found — nothing to publish", error_type="not_stacked"
        )
    objective_id = plan_state.header.get("objective_id")
    if not isinstance(objective_id, str) or not objective_id.strip():
        raise PublicationError(
            f"plan #{wanted} carries delivery_lineage but no objective_id — a stacked layer "
            "always belongs to an objective",
            error_type="not_stacked",
        )
    try:
        plan_body = context.persistence.get_plan_body(issue_id=wanted)
    except IssueBackendError:
        plan_body = None
    if request.run_id is None:
        raise ValueError("validated layer request lost run_id")
    publication = _Publication(
        context=context,
        runtime=runtime,
        plan_id=wanted,
        run_id=request.run_id,
        trigger_run_id=request.trigger_run_id,
        plan_state=plan_state,
        plan_body=plan_body,
    )
    result = _route(publication, objective_id.strip(), allow_resume=True)
    return PublishResult(kind="layer", plan_id=wanted, dry_run=False, layer=result)


def _ready(context: _PublishContext, request: PublishRequest) -> PublishResult:
    wanted = _normalize_publish_plan_id(request.plan_id)
    if request.delivery == "incremental":
        branch = f"plan-{wanted}"
        try:
            pr = context.github.pr_for_branch(branch)
        except TrainReconstructionError as exc:
            _raw_github_failure(exc)
        if pr is None:
            raise LayerError(
                f"No PR found for branch {branch!r}\nRun /submit first.", error_type="no_pr"
            )
        was_draft = pr.is_draft
        if was_draft:
            context.github.mark_pr_ready(pr.number)
        return PublishResult(
            kind="ready",
            plan_id=wanted,
            dry_run=False,
            ready=PublishResult.Ready(pr=pr, was_draft=was_draft),
        )
    objective_id = request.objective_id
    if objective_id is None:
        raise LayerError(
            f"plan #{wanted} carries delivery_lineage but no objective_id — a stacked layer "
            "always belongs to an objective",
            error_type="not_stacked",
        )
    status = context.status(StatusRequest(objective_id=objective_id))
    train = status.train
    if train is None:
        raise LayerError(
            f"objective {status.objective_id} has no delivery train ({status.no_train_reason})",
            error_type="not_stacked",
        )
    layer_context = derive_layer_context(train, plan_id=wanted)
    layer = next(item for item in train.layers if item.node_id == layer_context.node_id)
    if layer.pr_number is None:
        raise LayerError(f"layer {layer.node_id} (plan #{wanted}) stages no PR", error_type="no_pr")
    pr = context.github.get_pr(layer.pr_number)
    if pr is None:
        raise LayerError(
            f"No PR found for published layer {layer.node_id} (expected #{layer.pr_number})",
            error_type="no_pr",
        )
    require_reviewable_layer(train, plan_id=wanted, mutating=False)
    if pr.state.upper() != "OPEN":
        raise LayerError(
            f"PR #{pr.number} for published layer {layer.node_id} is {pr.state}, not OPEN",
            error_type="pr_not_open",
        )
    was_draft = pr.is_draft
    if was_draft:
        require_reviewable_layer(train, plan_id=wanted, mutating=True)
        context.github.mark_pr_ready(pr.number)
    return PublishResult(
        kind="ready",
        plan_id=wanted,
        dry_run=False,
        ready=PublishResult.Ready(pr=pr, was_draft=was_draft),
    )


# ----------------------------------------------------------------- routing


def _route(pub: _Publication, objective_id: str, *, allow_resume: bool) -> PublishResult.Layer:
    """Reconstruct fresh and route: resume an unresolved PUBLISH for this plan, refuse a
    foreign unresolved operation, gate the candidate, then execute. Re-entered exactly once
    after an abandon (``allow_resume=False`` — a second unresolved hit is drift, never a
    loop)."""
    train = _reconstruct(pub, objective_id)
    if isinstance(train, NoDeliveryTrain):
        raise PublicationError(
            f"objective {train.objective_id} has no delivery train ({train.reason})",
            error_type="not_stacked",
        )
    index = _layer_index(train, pub.plan_id)
    claimed = sync_mod.derive_claimed_prefix(train)
    claimed_index = next(
        (
            position
            for position, layer in enumerate(claimed)
            if layer.plan_id.removeprefix("#") == pub.plan_id
        ),
        None,
    )
    if claimed_index is not None and claimed_index < len(claimed) - 1:
        # Sync owns journal routing for a lower-layer propagation: an unresolved SYNC/ADOPT
        # must resume through its kind-aware protocol before publish's fold gate can preempt it.
        return _cascade(pub, objective_id)
    fold = pub.context.persistence.read_journal(train.objective_id)
    if fold.unresolved:
        op = fold.unresolved[0]
        record = op.prepared.record
        if (
            op.kind is OperationKind.PUBLISH
            and isinstance(record, PreparedRecord)
            and tuple(record.affected_plans) == (pub.plan_id,)
        ):
            if not allow_resume:
                raise PublicationError(
                    f"operation {op.operation_id} is still unresolved after an abandon — "
                    "refusing to loop; inspect the journal",
                    error_type="publication_drift",
                )
            return _resume(pub, train, index, record, objective_id)
        raise PublicationError(
            f"operation {op.operation_id} ({op.kind.value}) is unresolved on lineage "
            f"{fold.delivery_lineage} — recover or abandon it before publishing",
            error_type="unresolved_operation",
        )
    if train.published_prefix_len >= 1 and index == train.published_prefix_len - 1:
        return _republish(pub, train, index)
    try:
        ctx = require_ready_layer(train, plan_id=pub.plan_id)
    except LayerError as exc:
        raise PublicationError(str(exc), error_type=exc.error_type) from exc
    # Early capability recheck on the fresh route — ONLY when this publish will mutate the
    # native stack (position ≥ 2), and BEFORE any effect (journal append, push). The seam in
    # `_converge_stack` re-checks right before an actual mutation, covering the resume and
    # republish routes too. The atomic-push dry-run is deliberately NOT rerun (§8.47's
    # recorded deviation): the single-ref exact-lease push fails honestly on its own; the
    # multi-ref atomic probe belongs to the suffix-sync node.
    if index >= 1 and not pub.context.github.stack_capability():
        raise _capability_lost()
    before_branch_sha = _observe_own_branch(pub, ctx)
    return _run_protocol(pub, train, ctx, index, before_branch_sha=before_branch_sha)


def _cascade(pub: _Publication, objective_id: str) -> PublishResult.Layer:
    """Synchronize the claimed suffix from this lower published layer."""
    try:
        result = pub.context.sync(
            SyncRequest(
                mode="cascade",
                objective_id=objective_id,
                run_id=pub.run_id,
                trigger_plan_id=pub.plan_id,
                trigger_run_id=pub.trigger_run_id,
            ),
            consent=None,
        )
    except DeliveryError as exc:
        raise DeliveryError(
            str(exc),
            error_type=exc.error_type,
            phase="cascade",
            origin="delivery",
        ) from exc
    # A trigger resume may first roll an older all-after operation forward and then discover
    # that the new trigger is already converged. Reconstruct after sync so this result never
    # falls back to the pre-roll-forward checkpoint snapshot.
    updated = _reconstruct(pub, objective_id)
    if isinstance(updated, NoDeliveryTrain):
        raise PublicationError(
            f"objective {updated.objective_id} has no delivery train after suffix propagation "
            f"({updated.reason})",
            error_type="publication_drift",
        )
    ctx = _derive_ctx(pub, updated)
    layer = updated.layers[_layer_index(updated, pub.plan_id)]
    if layer.pr_number is None:
        raise PublicationError(
            f"layer {layer.node_id} (plan #{pub.plan_id}) stages no PR after suffix propagation",
            error_type="publication_drift",
        )
    try:
        pr = pub.context.github.get_pr(layer.pr_number)
    except GitHubError as exc:
        raise PublicationError(
            f"could not re-read PR #{layer.pr_number} after suffix propagation ({exc})",
            error_type="github_error",
        ) from exc
    if pr is None:
        raise PublicationError(
            f"PR #{layer.pr_number} disappeared after suffix propagation",
            error_type="github_error",
        )
    parent_checkpoint = layer.parent_checkpoint_sha
    published_head = layer.published_head_sha
    if not result.no_op:
        affected = next(
            (
                affected
                for affected in result.affected
                if affected.plan_id.removeprefix("#") == pub.plan_id
            ),
            None,
        )
        if affected is None:
            raise PublicationError(
                f"suffix propagation did not report plan #{pub.plan_id} in its affected set",
                error_type="publication_drift",
            )
        published_head = affected.after_sha
        if layer.published_head_sha != published_head:
            raise PublicationError(
                f"suffix propagation reported {published_head} for plan #{pub.plan_id}, but "
                f"fresh reconstruction carries {layer.published_head_sha or 'no checkpoint'}",
                error_type="publication_drift",
            )
    if parent_checkpoint is None or published_head is None:
        raise PublicationError(
            f"layer {layer.node_id} has no complete checkpoint pair after suffix propagation",
            error_type="publication_drift",
        )
    header_update = PlanHeaderUpdate(fields_updated=(), dry_run=False)
    if pub.trigger_run_id is not None:
        merged = plan.merge_untrusted_str_list(
            pub.plan_state.header.get("impl_run_ids"), pub.trigger_run_id
        )
        header_update = pub.context.persistence.update_plan_header(
            issue_id=pub.plan_id, fields={"impl_run_ids": list(merged)}
        )
    return PublishResult.Layer(
        pr=pr,
        branch=ctx.branch,
        header_update=header_update,
        plan_embedded=pub.plan_body is not None,
        pr_checked=True,
        parent_branch=ctx.parent_branch,
        operation_id=result.operation_id,
        stack_number=None,
        stack_size=None,
        stack_position=None,
        parent_checkpoint_sha=parent_checkpoint,
        published_head_sha=published_head,
        resumed=result.resumed,
        converged_noop=result.no_op,
        cascade=result,
    )


def _layer_index(train: DeliveryTrain, plan_id: str) -> int:
    for i, layer in enumerate(train.layers):
        if layer.plan_id is not None and layer.plan_id.removeprefix("#") == plan_id:
            return i
    raise PublicationError(
        f"plan #{plan_id} is not a layer of objective {train.objective_id}'s delivery train",
        error_type="not_stacked",
    )


def _derive_ctx(pub: _Publication, train: DeliveryTrain) -> LayerContext:
    try:
        return derive_layer_context(train, plan_id=pub.plan_id)
    except LayerError as exc:
        raise PublicationError(str(exc), error_type=exc.error_type) from exc


# ----------------------------------------------------------------- the fresh/republish protocol


def _run_protocol(
    pub: _Publication,
    train: DeliveryTrain,
    ctx: LayerContext,
    index: int,
    *,
    before_branch_sha: str | None,
) -> PublishResult.Layer:
    """Steps 5-12 under a freshly minted operation: verify the parent + candidate ancestry,
    append the prepared record (journal-first — before ANY remote mutation), push under the
    exact lease, then complete."""
    parent_sha = _prepare_parent(pub, ctx)
    candidate = _local_head(pub, ctx.branch)
    if candidate is None:
        raise PublicationError(
            f"local branch {ctx.branch!r} does not resolve — nothing to publish",
            error_type="git_error",
        )
    if pub.context.git.is_ancestor(parent_sha, candidate) is not True:
        raise PublicationError(
            f"branch {ctx.branch!r} at {candidate} does not contain the parent branch "
            f"{ctx.parent_branch!r}'s fresh head {parent_sha} — rebase onto "
            f"{ctx.parent_branch!r} and re-submit",
            error_type="stale_parent",
        )
    lineage = _require_lineage(train)
    record = PreparedRecord(
        operation_id=pub.runtime.mint_operation_id(),
        operation_kind=OperationKind.PUBLISH,
        delivery_lineage=lineage,
        objective_id=train.objective_id,
        run_id=pub.run_id,
        created=pub.runtime.now(),
        affected_plans=(pub.plan_id,),
        before=_before_payload(pub, train, index, ctx.branch, before_branch_sha),
        after=_after_payload(train, ctx, index, candidate),
    )
    try:
        pub.context.persistence.append_prepared(train.objective_id, record)
    except UnresolvedOperationError as exc:
        raise PublicationError(str(exc), error_type="unresolved_operation") from exc
    _push_with_lease(pub, ctx, before_branch_sha)
    return _complete_publication(
        pub,
        train,
        ctx,
        index,
        operation_id=record.operation_id,
        parent_sha=parent_sha,
        candidate_sha=candidate,
        resumed=False,
    )


def _prepare_parent(pub: _Publication, ctx: LayerContext) -> str:
    """Fetch + verify the LATEST parent head (never a stored checkpoint) via the shared
    ``prepare_layer_start`` path; typed ``LayerError``s map onto the publication vocabulary."""
    try:
        prepared = prepare_layer_start(
            ctx,
            fetch=lambda refs: _fetch(pub, tuple(refs)),
            remote_head=lambda branch: _remote_head(pub, branch),
            resolve_commit=lambda ref: _local_head(pub, ref),
        )
    except LayerError as exc:
        raise PublicationError(str(exc), error_type=exc.error_type) from exc
    return prepared.parent_sha


def _observe_own_branch(pub: _Publication, ctx: LayerContext) -> str | None:
    """The exact lease observation: the remote head of the layer's own branch (``None`` =
    the absence lease). The fetch is best-effort object localization (an absent remote branch
    makes an explicit-refspec fetch fail — that is not an observation failure)."""
    with contextlib.suppress(git_mod.GitError):
        _fetch(pub, (ctx.branch,))
    return _remote_head(pub, ctx.branch)


def _push_with_lease(pub: _Publication, ctx: LayerContext, expected_remote_sha: str | None) -> None:
    try:
        pub.context.git.push_with_exact_lease(ctx.branch, expected_remote_sha=expected_remote_sha)
    except git_mod.PushRejectedError as exc:
        raise PublicationError(
            f"the exact-lease push of {ctx.branch!r} was rejected (expected the remote at "
            f"{expected_remote_sha or '<absent>'}) — another writer moved the branch; the "
            f"prepared operation stays unresolved for recovery\n{exc}",
            error_type="push_rejected",
        ) from exc


def _capability_lost() -> PublicationError:
    return PublicationError(
        "the native-stack API surface is no longer available on this host — cannot "
        "register the layer in the stack (capability was present at authoring)",
        error_type="stack_capability_lost",
    )


def _require_lineage(train: DeliveryTrain) -> str:
    if train.delivery_lineage is None:
        raise PublicationError(
            f"objective {train.objective_id} carries no delivery_lineage — publication "
            "cannot be journaled",
            error_type="not_stacked",
        )
    return train.delivery_lineage


# ----------------------------------------------------------------- journal payload shapes


def _before_payload(
    pub: _Publication,
    train: DeliveryTrain,
    index: int,
    branch: str,
    before_branch_sha: str | None,
) -> dict[str, object]:
    """The publish-kind ``before`` shape (§8.47): the exact branch lease observation, the
    layer's PR facts when the train projection already knows its number, and the observed
    stack containing the prefix (``members: null`` when none is observable)."""
    layer = train.layers[index]
    pr_payload: dict[str, object] = {"number": None, "base": None, "head_sha": None, "state": None}
    if layer.pr_number is not None:
        facts = _pr_facts(pub, layer.pr_number)
        pr_payload = {
            "number": layer.pr_number,
            "base": facts.base_ref if facts is not None else None,
            "head_sha": facts.head_sha if facts is not None else None,
            "state": facts.state if facts is not None else None,
        }
    stack_payload: dict[str, object] = {"members": None}
    if index >= 1:
        bottom = train.layers[0].pr_number
        observed = _stack_read(pub, bottom) if bottom is not None else None
        stack_payload = {"members": list(observed.member_numbers) if observed is not None else None}
    return {
        "branch": {"ref": branch, "sha": before_branch_sha},
        "pr": pr_payload,
        "stack": stack_payload,
    }


def _after_payload(
    train: DeliveryTrain, ctx: LayerContext, index: int, candidate: str
) -> dict[str, object]:
    """The publish-kind ``after`` shape (§8.47). The bottom layer records
    ``stack: {not_applicable: true}``; a child layer records the desired bottom→top members
    with this layer's not-yet-known own PR as the ``"self"`` sentinel (recovery resolves it
    through the unique PR by exact head selector)."""
    stack_payload: dict[str, object]
    if index == 0:
        stack_payload = {"not_applicable": True}
    else:
        layer = train.layers[index]
        own: int | str = layer.pr_number if layer.pr_number is not None else "self"
        stack_payload = {"members": [*_prefix_pr_numbers(train, index), own]}
    return {
        "branch": {"ref": ctx.branch, "sha": candidate},
        "pr": {"base": ctx.parent_branch, "head_sha": candidate},
        "stack": stack_payload,
    }


def _prefix_pr_numbers(train: DeliveryTrain, index: int) -> list[int]:
    """The concrete PR numbers of layers 0..index-1 (published layers always stage a PR —
    an absent number is broken stored state, refused as drift)."""
    numbers: list[int] = []
    for layer in train.layers[:index]:
        if layer.pr_number is None:
            raise PublicationError(
                f"layer {layer.node_id} below the candidate stages no PR — the published "
                "prefix is incomplete",
                error_type="publication_drift",
            )
        numbers.append(layer.pr_number)
    return numbers


# ----------------------------------------------------------------- completion (steps 9-12)


def _complete_publication(
    pub: _Publication,
    train: DeliveryTrain,
    ctx: LayerContext,
    index: int,
    *,
    operation_id: str,
    parent_sha: str,
    candidate_sha: str,
    resumed: bool,
    expected_pr_number: int | None = None,
) -> PublishResult.Layer:
    """PR create/converge → stack membership convergence → the full postcondition refetch →
    persist (identity → checkpoint pair → ``completed``). Every failure before the outcome
    append leaves the operation unresolved (roll-forward territory). ``expected_pr_number``
    is the resume arms' recorded own-PR pin: when the prepared record named a concrete PR,
    the head-selector lookup must rediscover exactly it (else ``publication_drift``)."""
    facts = _body_facts(train, ctx, index)
    pr = pub.context.github.create_pr(
        head=ctx.branch,
        base=ctx.parent_branch,
        title=pub.plan_state.title,
        body=_compose_body(pub, facts, None),
        draft=True,
    )
    if expected_pr_number is not None and pr.number != expected_pr_number:
        raise PublicationError(
            f"the prepared operation recorded PR #{expected_pr_number} for branch "
            f"{ctx.branch!r} but the head selector discovered PR #{pr.number} — mixed "
            "remote state; refusing to complete the recorded operation",
            error_type="publication_drift",
        )
    if pr.existed and pr.state == "MERGED":
        raise PublicationError(
            f"PR #{pr.number} for branch {ctx.branch} has already merged — there is nothing "
            "to publish; start a fresh plan/branch for new work",
            error_type="pr_already_merged",
        )
    if pr.existed and pr.state == "CLOSED":
        pub.context.github.reopen_pr(pr.number)
    if pr.existed and pr.base_ref and pr.base_ref != ctx.parent_branch:
        # The base converge: an existing PR (create_pr is idempotent by head, base-blind) may
        # target a stale parent. Draft state is never touched on an existing PR — draft-by-
        # default is for creation only; `/ready` stays the separate per-layer gesture.
        pub.context.github.update_pr_base(pr.number, base=ctx.parent_branch)
    body = _compose_body(pub, facts, pr.number)
    pub.context.github.update_pr_body(pr.number, body=body)
    errors = pub.runtime.validate_pr_body(body, pr_number=pr.number)
    if errors:
        raise PublicationError(
            "PR body check failed after the create-then-update pass:\n  " + "\n  ".join(errors),
            error_type="postcondition_unverified",
        )
    desired: list[int] | None = None
    if index >= 1:
        desired = [*_prefix_pr_numbers(train, index), pr.number]
        _converge_stack(pub, ctx, pr.number, desired, candidate_sha)
    observed_stack = _verify_postconditions(pub, ctx, pr.number, candidate_sha, desired)
    # Persist, then complete: (a) the submit-owned identity fields; (b) the checkpoint pair
    # (one write, only after verification); (c) the terminal outcome. A crash between (a)-(c)
    # reconstructs as roll-forward — all three are merge-writes / idempotent appends.
    header_update = pub.context.persistence.update_plan_header(
        issue_id=pub.plan_id, fields=_header_fields(pub, pr.number)
    )
    pub.context.persistence.write_checkpoints(
        pub.plan_id, parent_checkpoint_sha=parent_sha, published_head_sha=candidate_sha
    )
    pub.context.persistence.append_outcome(
        train.objective_id,
        OutcomeRecord(
            operation_id=operation_id,
            role=EventRole.COMPLETED,
            created=pub.runtime.now(),
            observed={
                "branch_sha": candidate_sha,
                "pr": pr.number,
                "stack": list(desired) if desired is not None else None,
            },
        ),
    )
    return PublishResult.Layer(
        pr=pr,
        branch=ctx.branch,
        header_update=header_update,
        plan_embedded=pub.plan_body is not None,
        pr_checked=True,
        parent_branch=ctx.parent_branch,
        operation_id=operation_id,
        stack_number=observed_stack.number if observed_stack is not None else None,
        stack_size=observed_stack.size if observed_stack is not None else None,
        stack_position=index + 1 if observed_stack is not None else None,
        parent_checkpoint_sha=parent_sha,
        published_head_sha=candidate_sha,
        resumed=resumed,
        converged_noop=False,
    )


def _body_facts(train: DeliveryTrain, ctx: LayerContext, index: int) -> _LayerBodyFacts:
    rows = tuple(
        _TrainRowFacts(
            node_id=layer.node_id,
            plan_id=layer.plan_id,
            pr_number=layer.pr_number,
            current=(i == index),
        )
        for i, layer in enumerate(train.layers)
    )
    return _LayerBodyFacts(
        node_id=ctx.node_id,
        position=index + 1,
        total=len(train.layers),
        parent_branch=ctx.parent_branch,
        objective_base=train.base,
        objective_id=train.objective_id,
        rows=rows,
    )


def _compose_stacked_pr_body(
    *,
    issue: str,
    plan_body: str | None,
    facts: _LayerBodyFacts,
    pr_number: int | None = None,
) -> str:
    """Compose the informational stacked body; the reconstructed train stays authoritative."""
    objective = facts.objective_id.removeprefix("#")
    this_layer = (
        "### This layer\n\n"
        f"> Informational — the delivery train on objective #{objective} is authoritative; "
        "refreshed only at publication.\n\n"
        f"Layer {facts.position} of {facts.total} (node {facts.node_id}) — targets "
        f"`{facts.parent_branch}`; the train lands atomically into `{facts.objective_base}`."
    )
    rows = ["| # | node | plan | PR |", "| - | - | - | - |"]
    for position, row in enumerate(facts.rows, start=1):
        plan_cell = f"#{row.plan_id}" if row.plan_id is not None else "—"
        if row.current:
            pr_cell = f"#{pr_number} (this PR)" if pr_number is not None else "(this PR)"
        else:
            pr_cell = f"#{row.pr_number}" if row.pr_number is not None else "—"
        rows.append(f"| {position} | {row.node_id} | {plan_cell} | {pr_cell} |")
    train_context = "### Train context\n\n" + "\n".join(rows)
    parts = [f"Closes #{issue}", f"Plan: #{issue}", this_layer, train_context]
    if plan_body:
        parts.append(f"<details><summary>Plan #{issue}</summary>\n\n{plan_body}\n\n</details>")
    if pr_number is not None:
        parts.append(f"`gh pr checkout {pr_number}`")
    return "\n\n".join(parts) + "\n"


# ----------------------------------------------------------------- stack membership convergence


def _converge_stack(
    pub: _Publication,
    ctx: LayerContext,
    pr_number: int,
    desired: list[int],
    candidate_sha: str,
) -> None:
    """Converge the native stack onto exactly ``desired`` (bottom→top).

    Pre-mutation convergence wait (the PR must reflect the pushed head + converged base
    before the stack API will accept it), then classify observed-before: exact desired →
    already converged; nothing observed at position 2 → create; the exact prefix + this PR
    stackless → append the missing suffix; anything else → drift. Post-mutation: honor
    ``Retry-After`` once (capped), refetch, and classify exact-after / unchanged-before (one
    bounded retry after the settling interval) / drift. Mutations are strictly serialized —
    sequential in-process; cross-machine serialization is the one-unresolved-operation gate
    plus the exact push lease.
    """
    for _attempt in range(_CONVERGE_ATTEMPTS):
        facts = _pr_facts(pub, pr_number)
        if (
            facts is not None
            and facts.head_sha == candidate_sha
            and facts.base_ref == ctx.parent_branch
        ):
            break
        pub.runtime.sleep(_CONVERGE_DELAY_SECONDS)
    else:
        raise PublicationError(
            f"PR #{pr_number} did not settle at head {candidate_sha} / base "
            f"{ctx.parent_branch!r} after {_CONVERGE_ATTEMPTS} observations — the stack "
            "mutation would race remote convergence; re-run /submit to resume",
            error_type="remote_settling_timeout",
        )
    bottom = desired[0]
    observed = _stack_read(pub, bottom)
    observed_members = list(observed.member_numbers) if observed is not None else None
    if observed is not None and observed_members == desired:
        return  # already converged — no mutation
    own = _stack_read(pub, pr_number)
    if own is not None:
        raise PublicationError(
            f"PR #{pr_number} already belongs to native stack #{own.number} "
            f"({list(own.member_numbers)}) which is not the desired composition {desired} — "
            "refusing to mutate",
            error_type="stack_registration_drift",
        )
    if observed is None:
        if len(desired) != 2:
            raise PublicationError(
                f"expected the published prefix {desired[:-1]} in a native stack, observed "
                "none — the stack registration has drifted",
                error_type="stack_registration_drift",
            )

        def mutate() -> stacks.StackMutationOutcome:
            return pub.context.github.create_stack(tuple(desired))

    elif observed_members == desired[:-1]:
        stack_number = observed.number

        def mutate() -> stacks.StackMutationOutcome:
            return pub.context.github.append_stack(stack_number, pull_requests=(pr_number,))

    else:
        raise PublicationError(
            f"native stack #{observed.number} carries {observed_members} but the train "
            f"expects the prefix {desired[:-1]} (desired {desired}) — refusing to mutate",
            error_type="stack_registration_drift",
        )
    # The mutation-seam capability recheck: fires only when a create/append is actually
    # about to be issued (an already-converged membership never probes), so the resume and
    # republish routes are covered as well as the fresh one (which also checks early, before
    # any effect).
    if not pub.context.github.stack_capability():
        raise _capability_lost()
    for attempt in range(2):
        outcome = mutate()
        if outcome.rate_limited and outcome.retry_after_seconds is not None:
            pub.runtime.sleep(min(outcome.retry_after_seconds, _RETRY_AFTER_CAP_SECONDS))
        try:
            refetched = _stack_read(pub, bottom)
        except GitHubError as exc:
            raise PublicationError(
                f"the post-mutation stack refetch failed ({exc}) — the mutation outcome is "
                "unverifiable; the operation stays unresolved",
                error_type="postcondition_unverified",
            ) from exc
        refetched_members = list(refetched.member_numbers) if refetched is not None else None
        if refetched_members == desired:
            return  # exact-after → success (regardless of the raw mutation status)
        if refetched_members == observed_members:
            if attempt == 0:
                pub.runtime.sleep(_SETTLE_SECONDS)
                continue
            raise PublicationError(
                f"the stack mutation did not take effect after one retry (observed "
                f"{refetched_members}, desired {desired}; last status "
                f"{outcome.status}): {outcome.raw_detail}",
                error_type="stack_registration_failed",
            )
        raise PublicationError(
            f"the stack composition moved to {refetched_members} (desired {desired}) — "
            "a foreign writer or partial registration; refusing to continue",
            error_type="stack_registration_drift",
        )


def _verify_postconditions(
    pub: _Publication,
    ctx: LayerContext,
    pr_number: int,
    candidate_sha: str,
    desired: list[int] | None,
) -> stacks.StackRestFacts | None:
    """The full remote refetch: branch head, PR facts, and (position ≥ 2) exact stack
    membership. A refetch that raises is ``postcondition_unverified`` (fail closed — the
    operation stays unresolved); a mismatch is the matching drift type."""
    try:
        head = _remote_head(pub, ctx.branch)
    except git_mod.GitError as exc:
        raise PublicationError(
            f"could not re-observe branch {ctx.branch!r} after publication ({exc})",
            error_type="postcondition_unverified",
        ) from exc
    if head != candidate_sha:
        raise PublicationError(
            f"branch {ctx.branch!r} verified at {head}, expected the pushed candidate "
            f"{candidate_sha} — a foreign writer moved the branch",
            error_type="publication_drift",
        )
    try:
        facts = _pr_facts(pub, pr_number)
    except GitHubError as exc:
        raise PublicationError(
            f"could not re-observe PR #{pr_number} after publication ({exc})",
            error_type="postcondition_unverified",
        ) from exc
    if (
        facts is None
        or facts.state != "OPEN"
        or facts.base_ref != ctx.parent_branch
        or facts.head_sha != candidate_sha
    ):
        observed_desc = (
            f"state={facts.state} base={facts.base_ref!r} head={facts.head_sha}"
            if facts is not None
            else "absent"
        )
        raise PublicationError(
            f"PR #{pr_number} verified as {observed_desc}, expected OPEN onto "
            f"{ctx.parent_branch!r} at {candidate_sha}",
            error_type="publication_drift",
        )
    if desired is None:
        return None
    try:
        observed = _stack_read(pub, desired[0])
    except GitHubError as exc:
        raise PublicationError(
            f"could not re-observe the native stack after publication ({exc})",
            error_type="postcondition_unverified",
        ) from exc
    if observed is None or list(observed.member_numbers) != desired:
        raise PublicationError(
            f"native stack verified as "
            f"{list(observed.member_numbers) if observed is not None else None}, expected "
            f"exactly {desired}",
            error_type="stack_registration_drift",
        )
    return observed


# ----------------------------------------------------------------- the republish/converge arm


def _republish(pub: _Publication, train: DeliveryTrain, index: int) -> PublishResult.Layer:
    """The TOP published layer: verify the remote against the recorded checkpoint (invariant:
    an already-published head that moved out-of-band is ``remote_drift`` — adoption is a later
    node), then either the pure no-op convergence (no journal event) or the full protocol
    under a checkpoint-matching lease. Rewriting the top layer is safe — no published
    successor exists above it; lower claimed layers route through the automatic cascade."""
    ctx = _derive_ctx(pub, train)
    layer = train.layers[index]
    checkpoint = layer.published_head_sha
    if checkpoint is None or layer.pr_number is None:
        raise PublicationError(
            f"layer {layer.node_id} classifies as published but stores no checkpoint/PR — "
            "broken stored state",
            error_type="publication_drift",
        )
    observed = _remote_head(pub, ctx.branch)
    if observed != checkpoint:
        raise PublicationError(
            f"branch {ctx.branch!r} observed at {observed}, but the published-head checkpoint "
            f"records {checkpoint} — the remote drifted out-of-band (adoption is a later "
            "recovery surface)",
            error_type="remote_drift",
        )
    candidate = _local_head(pub, ctx.branch)
    if candidate is None:
        raise PublicationError(
            f"local branch {ctx.branch!r} does not resolve — nothing to publish",
            error_type="git_error",
        )
    if candidate == checkpoint:
        converged = _noop_converged(pub, train, ctx, index, layer.pr_number, checkpoint)
        if converged is not None:
            return converged
    if train.blockers:
        detail = "; ".join(f"[{f.code}] {f.message}" for f in train.blockers)
        raise PublicationError(
            f"the train carries blocker findings — republish refuses: {detail}",
            error_type="publication_drift",
        )
    return _run_protocol(pub, train, ctx, index, before_branch_sha=checkpoint)


def _noop_converged(
    pub: _Publication,
    train: DeliveryTrain,
    ctx: LayerContext,
    index: int,
    pr_number: int,
    checkpoint: str,
) -> PublishResult.Layer | None:
    """The pure no-op convergence check: candidate == published head AND the PR + membership
    already match desired → return the observed facts without any write; ``None`` when
    anything needs converging (the caller falls through to the full protocol)."""
    facts = _pr_facts(pub, pr_number)
    if (
        facts is None
        or facts.state != "OPEN"
        or facts.base_ref != ctx.parent_branch
        or facts.head_sha != checkpoint
    ):
        return None
    observed_stack: stacks.StackRestFacts | None = None
    if index >= 1:
        desired = [*_prefix_pr_numbers(train, index), pr_number]
        observed_stack = _stack_read(pub, desired[0])
        if observed_stack is None or list(observed_stack.member_numbers) != desired:
            return None
    pr = pub.context.github.get_pr(pr_number)
    if pr is None:
        return None
    parent_checkpoint = train.layers[index].parent_checkpoint_sha
    if parent_checkpoint is None:
        raise PublicationError(
            f"layer {train.layers[index].node_id} classifies as published but stores no "
            "parent checkpoint — broken stored state",
            error_type="publication_drift",
        )
    return PublishResult.Layer(
        pr=pr,
        branch=ctx.branch,
        header_update=PlanHeaderUpdate(fields_updated=(), dry_run=False),
        plan_embedded=pub.plan_body is not None,
        pr_checked=True,
        parent_branch=ctx.parent_branch,
        operation_id=None,
        stack_number=observed_stack.number if observed_stack is not None else None,
        stack_size=observed_stack.size if observed_stack is not None else None,
        stack_position=index + 1 if observed_stack is not None else None,
        parent_checkpoint_sha=parent_checkpoint,
        published_head_sha=checkpoint,
        resumed=False,
        converged_noop=True,
    )


# ----------------------------------------------------------------- the resume path


def _resume(
    pub: _Publication,
    train: DeliveryTrain,
    index: int,
    record: PreparedRecord,
    objective_id: str,
) -> PublishResult.Layer:
    """Same-layer resume: re-derive the expected states from the prepared record, observe
    fresh, and converge in place — roll forward from ``after``, retry from an all-``before``
    world with an unchanged candidate, abandon-with-proof + prepare fresh when the candidate
    moved, and fail closed (``publication_drift``) on anything mixed/unrelated."""
    ctx = _derive_ctx(pub, train)
    after_sha = _payload_branch_sha(record.after)
    if after_sha is None:
        raise PublicationError(
            f"operation {record.operation_id}'s prepared record has no readable "
            "after.branch.sha — cannot resume",
            error_type="publication_drift",
        )
    expected_pr_number = _validate_resume_context(
        train, branch=ctx.branch, parent_branch=ctx.parent_branch, index=index, record=record
    )
    before_sha = _payload_branch_sha(record.before)
    observed = _remote_head(pub, ctx.branch)
    if observed == after_sha:
        # Roll forward: the push landed; complete steps 9-12 under the same operation. The
        # recorded `"self"` member resolves through the unique PR discovered/created by head.
        parent_sha = _prepare_parent(pub, ctx)
        if pub.context.git.is_ancestor(parent_sha, after_sha) is not True:
            raise PublicationError(
                f"the pushed candidate {after_sha} no longer contains the parent branch "
                f"{ctx.parent_branch!r}'s fresh head {parent_sha} — rebase onto "
                f"{ctx.parent_branch!r} and re-submit",
                error_type="stale_parent",
            )
        return _complete_publication(
            pub,
            train,
            ctx,
            index,
            operation_id=record.operation_id,
            parent_sha=parent_sha,
            candidate_sha=after_sha,
            resumed=True,
            expected_pr_number=expected_pr_number,
        )
    if observed == before_sha:
        _require_all_before(_PublishProofAdapter(pub), record)
        local = _local_head(pub, ctx.branch)
        if local == after_sha:
            # Unchanged inputs: retry under the same operation from the push step.
            parent_sha = _prepare_parent(pub, ctx)
            if pub.context.git.is_ancestor(parent_sha, after_sha) is not True:
                raise PublicationError(
                    f"the candidate {after_sha} does not contain the parent branch "
                    f"{ctx.parent_branch!r}'s fresh head {parent_sha} — rebase onto "
                    f"{ctx.parent_branch!r} and re-submit",
                    error_type="stale_parent",
                )
            _push_with_lease(pub, ctx, before_sha)
            return _complete_publication(
                pub,
                train,
                ctx,
                index,
                operation_id=record.operation_id,
                parent_sha=parent_sha,
                candidate_sha=after_sha,
                resumed=True,
                expected_pr_number=expected_pr_number,
            )
        # The local candidate moved: abandon with proof (every effect verified at its before
        # state), then prepare FRESH in the same invocation.
        pub.context.persistence.append_outcome(
            train.objective_id,
            OutcomeRecord(
                operation_id=record.operation_id,
                role=EventRole.ABANDONED,
                created=pub.runtime.now(),
                observed={
                    "branch": {"ref": ctx.branch, "sha": observed},
                    "pr": dict(_opt_mapping(record.before.get("pr")) or {}),
                    "stack": dict(_opt_mapping(record.before.get("stack")) or {}),
                },
            ),
        )
        return _route(pub, objective_id, allow_resume=False)
    raise PublicationError(
        f"branch {ctx.branch!r} observed at {observed}, matching neither the prepared "
        f"operation's before ({before_sha}) nor after ({after_sha}) state — mixed/unrelated "
        "remote state; refusing to guess",
        error_type="publication_drift",
    )


def _resume_drift(
    operation_id: str, what: str, *, expected: object, derived: object
) -> PublicationError:
    return PublicationError(
        f"operation {operation_id}'s prepared record no longer matches the reconstructed "
        f"train: recorded {what} {expected!r}, derived {derived!r} — the authorities "
        "drifted while the operation was unresolved; refusing to complete it",
        error_type="publication_drift",
    )


def _validate_resume_context(
    train: DeliveryTrain,
    *,
    branch: str,
    parent_branch: str,
    index: int,
    record: PreparedRecord,
) -> int | None:
    """The resume arms complete the ORIGINAL operation, so the freshly reconstructed context
    must still agree with the prepared record's recorded desired state — lineage, branch,
    parent base, and the desired stack composition. Authority drift while the operation was
    unresolved (a superseded roadmap, a retargeted parent, changed prefix PR identities) is
    ``publication_drift``, never silently re-derived. Returns the recorded own-PR number when
    the record pinned a concrete one (``"self"`` → ``None``; the head-selector discovery is
    checked against a concrete pin inside ``_complete_publication``)."""
    op = record.operation_id
    lineage = _require_lineage(train)
    if record.delivery_lineage != lineage:
        raise _resume_drift(
            op, "delivery_lineage", expected=record.delivery_lineage, derived=lineage
        )
    after_branch = _opt_mapping(record.after.get("branch"))
    recorded_ref = after_branch.get("ref") if after_branch is not None else None
    if recorded_ref != branch:
        raise _resume_drift(op, "branch ref", expected=recorded_ref, derived=branch)
    after_pr = _opt_mapping(record.after.get("pr"))
    recorded_base = after_pr.get("base") if after_pr is not None else None
    if recorded_base != parent_branch:
        raise _resume_drift(op, "PR base", expected=recorded_base, derived=parent_branch)
    after_stack = _opt_mapping(record.after.get("stack"))
    if index == 0:
        if after_stack is None or after_stack.get("not_applicable") is not True:
            raise _resume_drift(
                op,
                "stack shape",
                expected=dict(after_stack or {}),
                derived="not_applicable (bottom layer)",
            )
        return None
    members = after_stack.get("members") if after_stack is not None else None
    if not isinstance(members, list) or not members:
        raise _resume_drift(
            op, "stack members", expected=members, derived="a non-empty bottom→top list"
        )
    prefix = _prefix_pr_numbers(train, index)
    if list(members[:-1]) != prefix:
        raise _resume_drift(op, "stack prefix", expected=members[:-1], derived=prefix)
    last = members[-1]
    if last == "self":
        return None
    if isinstance(last, int):
        return last
    raise _resume_drift(op, "own stack member", expected=last, derived='an int or "self"')


class PublishProofSeams(Protocol):
    """The narrow observation bundle the PUBLISH record proof consumes — satisfied
    structurally by the aggregate publication bridge and recover's bundle (contracts.md §8.51)."""

    @property
    def repo_root(self) -> Path: ...
    @property
    def pr_facts(self) -> _PrFactsRead: ...
    @property
    def stack_read(self) -> _StackRead: ...
    @property
    def remote_head(self) -> Callable[[Path, str], str | None]: ...
    @property
    def pr_for_branch(self) -> _FindPrForBranch: ...


@dataclass(frozen=True)
class _PublishBefore:
    """The strictly decoded, positively observable PUBLISH ``before`` state."""

    branch_ref: str
    branch_sha: str | None
    pr_number: int | None
    pr_base: str | None
    pr_head_sha: str | None
    pr_state: str | None
    stack_members: tuple[int, ...] | None


def _record_shape_error(record: PreparedRecord, detail: str) -> PublicationError:
    return PublicationError(
        f"operation {record.operation_id}'s prepared record is unreadable: {detail} — "
        "mixed remote state",
        error_type="publication_drift",
    )


def _decode_publish_before(record: PreparedRecord, *, expected_branch: str) -> _PublishBefore:
    """Strictly decode the complete canonical before shape. ``None`` is meaningful only in
    an explicitly present field; a missing/malformed field is unknown, never absence proof."""
    branch = _opt_mapping(record.before.get("branch"))
    if branch is None or "ref" not in branch or "sha" not in branch:
        raise _record_shape_error(record, "before.branch must carry ref and sha")
    branch_ref = branch.get("ref")
    branch_sha = branch.get("sha")
    if not isinstance(branch_ref, str) or not branch_ref or branch_ref != expected_branch:
        raise _record_shape_error(
            record, f"before.branch.ref must equal the recorded branch {expected_branch!r}"
        )
    if branch_sha is not None and (not isinstance(branch_sha, str) or not branch_sha):
        raise _record_shape_error(record, "before.branch.sha must be a non-empty string or null")

    pr = _opt_mapping(record.before.get("pr"))
    pr_fields = ("number", "base", "head_sha", "state")
    if pr is None or any(field not in pr for field in pr_fields):
        raise _record_shape_error(record, "before.pr must carry number/base/head_sha/state")
    number = pr.get("number")
    base = pr.get("base")
    head_sha = pr.get("head_sha")
    state = pr.get("state")
    if number is None:
        if any(value is not None for value in (base, head_sha, state)):
            raise _record_shape_error(
                record, "a null before.pr.number requires null base/head_sha/state"
            )
    elif type(number) is not int or not all(
        isinstance(value, str) and value for value in (base, head_sha, state)
    ):
        raise _record_shape_error(
            record, "a numbered before.pr requires non-empty base/head_sha/state strings"
        )
    decoded_base = cast("str", base) if number is not None else None
    decoded_head_sha = cast("str", head_sha) if number is not None else None
    decoded_state = cast("str", state) if number is not None else None

    stack = _opt_mapping(record.before.get("stack"))
    if stack is None or "members" not in stack:
        raise _record_shape_error(record, "before.stack must carry members")
    raw_members = stack.get("members")
    if raw_members is None:
        members = None
    elif (
        not isinstance(raw_members, list)
        or not raw_members
        or any(type(member) is not int for member in raw_members)
    ):
        raise _record_shape_error(
            record, "before.stack.members must be null or a non-empty integer list"
        )
    else:
        typed_members: list[int] = []
        for member in raw_members:
            if type(member) is int:
                typed_members.append(member)
        members = tuple(typed_members)
    return _PublishBefore(
        branch_ref=branch_ref,
        branch_sha=cast("str | None", branch_sha),
        pr_number=number,
        pr_base=decoded_base,
        pr_head_sha=decoded_head_sha,
        pr_state=decoded_state,
        stack_members=members,
    )


def _after_stack_members(record: PreparedRecord) -> list[int | str] | None:
    stack = _opt_mapping(record.after.get("stack"))
    if stack is None:
        raise _record_shape_error(record, "after.stack must be a mapping")
    if stack.get("not_applicable") is True:
        return None
    raw_members = stack.get("members")
    if (
        not isinstance(raw_members, list)
        or not raw_members
        or any(
            type(member) is not int and not (member == "self" and index == len(raw_members) - 1)
            for index, member in enumerate(raw_members)
        )
    ):
        raise _record_shape_error(
            record, 'after.stack.members must be a non-empty integer list ending in int or "self"'
        )
    typed_members: list[int | str] = []
    for member in raw_members:
        if type(member) is int or member == "self":
            typed_members.append(cast("int | str", member))
    return typed_members


def _require_all_before(
    pub: PublishProofSeams,
    record: PreparedRecord,
    *,
    decoded: _PublishBefore | None = None,
) -> None:
    """Positively prove every complete ``before`` fact exactly; unknown is never absence."""
    after_branch = _opt_mapping(record.after.get("branch"))
    branch_ref = after_branch.get("ref") if after_branch is not None else None
    if not isinstance(branch_ref, str):
        raise _record_shape_error(record, "after.branch.ref is unreadable")
    before = decoded or _decode_publish_before(record, expected_branch=branch_ref)
    if before.pr_number is None:
        existing = pub.pr_for_branch(branch=branch_ref, repo_root=pub.repo_root)
        if existing is not None:
            raise PublicationError(
                f"the prepared record captured no pre-operation PR, but the {existing.state} "
                f"PR #{existing.number} exists for branch {branch_ref!r} — the operation's "
                "PR effect persists; mixed remote state",
                error_type="publication_drift",
            )
    else:
        facts = pub.pr_facts(number=before.pr_number, repo_root=pub.repo_root)
        expected = {
            "base": before.pr_base,
            "head_sha": before.pr_head_sha,
            "state": before.pr_state,
        }
        observed = {
            "base": facts.base_ref if facts is not None else None,
            "head_sha": facts.head_sha if facts is not None else None,
            "state": facts.state if facts is not None else None,
        }
        if observed != expected:
            raise PublicationError(
                f"PR #{before.pr_number} no longer matches the prepared operation's before "
                f"state (expected {expected}, observed {observed}) — mixed remote state",
                error_type="publication_drift",
            )

    desired = _after_stack_members(record)
    if desired is None:
        if before.stack_members is not None:
            raise _record_shape_error(
                record, "a bottom-layer record requires null before.stack.members"
            )
        return
    probe_number = next((member for member in desired if type(member) is int), None)
    if probe_number is None:
        raise _record_shape_error(record, "after.stack.members has no concrete probe member")
    observed_stack = pub.stack_read(number=probe_number, repo_root=pub.repo_root)
    observed_members = tuple(observed_stack.member_numbers) if observed_stack is not None else None
    if observed_members != before.stack_members:
        raise PublicationError(
            f"the native stack no longer matches the prepared operation's before state "
            f"(expected members {before.stack_members}, observed {observed_members}) — "
            "mixed remote state",
            error_type="publication_drift",
        )


def _require_all_after(
    pub: PublishProofSeams, record: PreparedRecord, *, branch: str, after_sha: str
) -> None:
    """Read-only equivalent of publish's postcondition: exact PR + native-stack proof."""
    after_pr = _opt_mapping(record.after.get("pr"))
    if after_pr is None or "base" not in after_pr or "head_sha" not in after_pr:
        raise _record_shape_error(record, "after.pr must carry base and head_sha")
    base = after_pr.get("base")
    pr_head_sha = after_pr.get("head_sha")
    if not isinstance(base, str) or not base or pr_head_sha != after_sha:
        raise _record_shape_error(
            record, "after.pr requires a non-empty base and the recorded after branch SHA"
        )
    pr = pub.pr_for_branch(branch=branch, repo_root=pub.repo_root)
    if pr is None or pr.state != "OPEN":
        raise PublicationError(
            f"branch {branch!r} has no OPEN PR at the prepared after state — mixed remote state",
            error_type="publication_drift",
        )
    facts = pub.pr_facts(number=pr.number, repo_root=pub.repo_root)
    if (
        facts is None
        or facts.state != "OPEN"
        or facts.base_ref != base
        or facts.head_sha != after_sha
    ):
        observed = (
            {"base": facts.base_ref, "head_sha": facts.head_sha, "state": facts.state}
            if facts is not None
            else None
        )
        raise PublicationError(
            f"PR #{pr.number} no longer matches the prepared operation's after state "
            f"(expected base={base!r}, head_sha={after_sha}, state=OPEN; observed "
            f"{observed}) — mixed remote state",
            error_type="publication_drift",
        )

    desired = _after_stack_members(record)
    if desired is None:
        return
    if desired[-1] == "self":
        desired[-1] = pr.number
    elif desired[-1] != pr.number:
        raise PublicationError(
            f"the prepared operation pins PR #{desired[-1]} but branch {branch!r} resolves "
            f"to PR #{pr.number} — mixed remote state",
            error_type="publication_drift",
        )
    expected_members = [member for member in desired if type(member) is int]
    observed_stack = pub.stack_read(number=expected_members[0], repo_root=pub.repo_root)
    observed_members = list(observed_stack.member_numbers) if observed_stack is not None else None
    if observed_members != expected_members:
        raise PublicationError(
            f"the native stack no longer matches the prepared operation's after state "
            f"(expected members {expected_members}, observed {observed_members}) — mixed "
            "remote state",
            error_type="publication_drift",
        )


def _payload_branch_sha(payload: Mapping[str, object]) -> str | None:
    branch = _opt_mapping(payload.get("branch"))
    if branch is None:
        return None
    sha = branch.get("sha")
    return sha if isinstance(sha, str) else None


# ------------------------------------------- the PUBLISH record proof (recover, §8.51)


@dataclass(frozen=True)
class PublishRecordProof:
    """One unresolved PUBLISH record's classification for the recover operation: fresh
    authority + the complete branch/PR/native-stack proof are required for BOTH conclusive
    states. Any disagreement fails closed to ``mixed`` (reported, never concluded)."""

    classification: str  # all_after | all_before | mixed
    branch: str | None
    observed_sha: str | None
    detail: str


def classify_publish_record(
    seams: PublishProofSeams, train: DeliveryTrain, record: PreparedRecord
) -> PublishRecordProof:
    """Classify an unresolved PUBLISH prepared record for recover (conclude-only: recover
    never rolls a PUBLISH forward — ``/submit``'s own resume owns that). Built on the same
    payload decode + fresh-train corroboration (``_validate_resume_context``: lineage,
    branch, parent base, desired stack), then exact after postconditions or a strictly
    decoded positive before proof. A record that no longer agrees with the fresh train
    classifies ``mixed`` (fail closed, reported), so ``--abandon`` can never conclude a stale record
    from record-relative remote facts alone. Infra read failures (GitHub) propagate —
    recover fails whole rather than mis-classifying."""
    after_branch = _opt_mapping(record.after.get("branch"))
    branch = after_branch.get("ref") if after_branch is not None else None
    after_sha = _payload_branch_sha(record.after)
    if not isinstance(branch, str) or after_sha is None:
        return PublishRecordProof(
            classification="mixed",
            branch=None,
            observed_sha=None,
            detail="the prepared record has no readable after.branch — cannot classify",
        )
    mismatch = _corroborate_record_train(train, record)
    if mismatch is not None:
        return PublishRecordProof(
            classification="mixed",
            branch=branch,
            observed_sha=None,
            detail=f"corroboration against fresh authority failed: {mismatch}",
        )
    try:
        before = _decode_publish_before(record, expected_branch=branch)
    except PublicationError as exc:
        return PublishRecordProof(
            classification="mixed",
            branch=branch,
            observed_sha=None,
            detail=str(exc),
        )
    observed = seams.remote_head(seams.repo_root, branch)
    if observed == after_sha:
        try:
            _require_all_after(seams, record, branch=branch, after_sha=after_sha)
        except PublicationError as exc:
            return PublishRecordProof(
                classification="mixed",
                branch=branch,
                observed_sha=observed,
                detail=str(exc),
            )
        return PublishRecordProof(
            classification="all_after",
            branch=branch,
            observed_sha=observed,
            detail=(
                f"branch {branch!r}, its PR, and native stack verified at the prepared "
                f"after state {after_sha}"
            ),
        )
    before_sha = before.branch_sha
    if observed == before_sha:
        try:
            _require_all_before(seams, record, decoded=before)
        except PublicationError as exc:
            return PublishRecordProof(
                classification="mixed",
                branch=branch,
                observed_sha=observed,
                detail=str(exc),
            )
        return PublishRecordProof(
            classification="all_before",
            branch=branch,
            observed_sha=observed,
            detail=(
                f"branch {branch!r} verified at the prepared before state "
                f"{before_sha or '<absent>'} with the PR and stack observations corroborated"
            ),
        )
    return PublishRecordProof(
        classification="mixed",
        branch=branch,
        observed_sha=observed,
        detail=(
            f"branch {branch!r} observed at {observed or '<absent>'}, matching neither the "
            f"prepared before ({before_sha or '<absent>'}) nor after ({after_sha}) state"
        ),
    )


def _corroborate_record_train(train: DeliveryTrain, record: PreparedRecord) -> str | None:
    """Corroborate a PUBLISH record against the FRESHLY reconstructed train: the affected
    plan must still be a layer, and the record's lineage / branch / parent base / desired
    stack must agree with the fresh topology (the same ``_validate_resume_context`` publish's
    own resume applies). Returns the mismatch description (→ ``mixed``), ``None`` when the
    record corroborates."""
    if len(record.affected_plans) != 1:
        return f"the record names {len(record.affected_plans)} affected plans, expected one"
    plan_id = record.affected_plans[0]
    try:
        index = _layer_index(train, plan_id)
    except PublicationError as exc:
        return str(exc)
    layer = train.layers[index]
    branch = layer.branch if layer.branch is not None else f"plan-{plan_id}"
    if index == 0:
        parent_branch = train.base
    else:
        predecessor = train.layers[index - 1]
        pred_plan = (predecessor.plan_id or "").removeprefix("#")
        parent_branch = (
            predecessor.branch if predecessor.branch is not None else f"plan-{pred_plan}"
        )
    try:
        _validate_resume_context(
            train, branch=branch, parent_branch=parent_branch, index=index, record=record
        )
    except PublicationError as exc:
        return str(exc)
    return None


def publish_abandon_observation(
    record: PreparedRecord, proof: PublishRecordProof
) -> dict[str, object]:
    """The abandoned-outcome proof payload for a PUBLISH record (the same shape publish's
    own abandon arm writes): the post-confirmation branch observation plus the recorded
    before PR/stack observations the proof corroborated."""
    return {
        "branch": {"ref": proof.branch, "sha": proof.observed_sha},
        "pr": dict(_opt_mapping(record.before.get("pr")) or {}),
        "stack": dict(_opt_mapping(record.before.get("stack")) or {}),
    }


def _opt_mapping(value: object) -> Mapping[str, object] | None:
    """A journal-payload field read as a mapping, else ``None`` (tolerant). The ``cast``
    confines the documented ty isinstance-narrowing quirk to this leaf (mirroring
    ``github._exec._opt_dict``)."""
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else None
