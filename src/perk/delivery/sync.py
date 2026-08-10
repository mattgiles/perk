"""The delivery **sync** operation — published-suffix synchronization (contracts.md §8.48).

The transactional cascade `perk objective stack sync` routes through: change a published
stacked layer (or re-anchor the whole train onto an advanced objective base) and move every
published successor with it — candidates computed by rebase in an isolated worktree, approved
as one rendered cascade, journaled first, then pushed as ONE atomic multi-ref operation under
exact leases, verified, and checkpointed bottom→top. Every effectful callable is
keyword-injectable with production defaults (the ``publish.py`` pattern; tests pass fakes).

The concurrency contract mirrors publish's: mutations are strictly serialized in-process; the
cross-machine serialization is the one-unresolved-operation journal gate plus the exact push
leases — the remote itself arbitrates competing writers. Failures after the prepared record
leave the operation **unresolved** (recoverable); refusals before it write nothing. The one
deliberately retained failure state is the mid-rebase conflict: the conflicted worktree stays
in place under a continuation manifest (:mod:`perk.delivery.continuation`) and a fresh sync
refuses until it is cleared.
"""

import contextlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from perk import plan
from perk.delivery import continuation, observe
from perk.delivery.capability import probe_atomic_push_urls
from perk.delivery.journal import (
    EventRole,
    JournalFold,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
    mint_operation_id,
)
from perk.delivery.persistence import (
    AppendResult,
    UnresolvedOperationError,
    resolve_train_persistence,
)
from perk.delivery.train import DeliveryTrain, LayerWriter, NoDeliveryTrain, TrainStatus
from perk.github import GitHubError, stacks
from perk.substrate import git as git_mod

# The bounded PR settle poll (publish's `_converge_stack` pattern): GitHub's PR-head
# propagation lags a push, so postcondition verification observes up to N times before any
# mismatch classifies as drift.
_SETTLE_ATTEMPTS = 5
_SETTLE_DELAY_SECONDS = 2.0


class SyncError(Exception):
    """A suffix synchronization failed or refused. ``error_type`` is the stable machine code
    the CLI boundary maps onto its failure envelope."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # not_stacked | unresolved_operation | sync_conflict_pending
        # | claimed_prefix_malformed | active_writer | dirty_worktree
        # | writer_observation_unavailable | remote_drift | pr_drift | membership_drift
        # | stale_parent | base_unobserved | multiple_push_urls | atomic_push_unsupported
        # | rebase_conflict | push_rejected | sync_drift | postcondition_unverified
        # | invalid_input | git_error | github_error (contracts.md §8.48 declares the full
        # bounded set; git_error/github_error are the CLI's mapping of raw infra raises)
    ) -> None:
        super().__init__(message)
        self.error_type = error_type


class WriterObservationError(Exception):
    """A :class:`RemoteWriterProbe` could not observe the active remote writers. Sync maps it
    to the typed refusal ``writer_observation_unavailable`` — a mutation gate never treats an
    unreadable observation as "no active writer"."""


class RemoteWriterProbe(Protocol):
    """The narrow remote-writer preflight surface (declared here; wired by the CLI).

    ``active_plan_ids`` returns the subset of ``plan_ids`` that currently have an active
    remote writer (a queued/in-progress remote implementation run). Implementations raise
    :class:`WriterObservationError` on ANY observation failure — never an empty set.
    """

    def active_plan_ids(self, plan_ids: Sequence[str]) -> frozenset[str]: ...


@dataclass(frozen=True)
class SyncedLayer:
    """One affected layer's before→after movement (bottom→top order in the containers)."""

    node_id: str
    plan_id: str
    branch: str
    pr_number: int
    before_sha: str
    after_sha: str


@dataclass(frozen=True)
class SyncCascade:
    """What the approval gate renders: the full ordered per-ref movement plus the base facts.

    ``base_before``/``base_after`` are the bottom layer's re-anchoring (the stored parent
    edge → the observed base head) and are ``None`` unless the cascade includes the base.
    """

    objective_id: str
    base_branch: str
    include_base: bool
    base_before: str | None
    base_after: str | None
    layers: tuple[SyncedLayer, ...]


@dataclass(frozen=True)
class SyncResult:
    """The verified outcome of one sync invocation (the §8.48 result-arm table).

    Invariant: ``operation_id`` is non-null ⟺ a prepared record was journaled by (or resumed
    by) this invocation — the no-op and declined arms never touch the journal.
    ``abandoned_operation_id`` names the previously unresolved operation this invocation
    abandoned-with-proof before preparing fresh. ``base_advanced`` is the status notice (the
    CLI's ``--base`` hint), independent of whether this run cascaded the base.
    """

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
    affected: tuple[SyncedLayer, ...]


# ----------------------------------------------------------------- injected-seam protocols


class SyncPersistence(Protocol):
    """The narrow train-persistence surface sync needs (structurally satisfied by
    :func:`resolve_train_persistence`'s adapter)."""

    def read_journal(self, objective_id: str) -> JournalFold: ...

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult: ...

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult: ...

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None: ...


class _PrFactsRead(Protocol):
    def __call__(self, *, number: int, repo_root: Path) -> stacks.PrDeliveryFacts | None: ...


class _StackRead(Protocol):
    def __call__(self, *, number: int, repo_root: Path) -> stacks.StackRestFacts | None: ...


class _RebaseOnto(Protocol):
    def __call__(self, worktree: Path, *, onto: str, upstream: str) -> git_mod.RebaseOutcome: ...


def _default_fetch(repo: Path, refspecs: list[str]) -> None:
    git_mod.fetch_refspecs(repo, refspecs)


def _default_is_ancestor(repo: Path, ancestor_sha: str, head_sha: str) -> bool:
    """Ancestry via ``merge-base`` over fetched objects — **fail closed** (an unresolvable
    commit or missing merge base reads as not-an-ancestor; the downstream ``stale_parent``
    gate then refuses honestly rather than cascading unknowable evidence)."""
    ancestor = git_mod.resolve_commit(repo, ancestor_sha)
    head = git_mod.resolve_commit(repo, head_sha)
    if ancestor is None or head is None:
        return False
    return git_mod.merge_base(repo, ancestor, head) == ancestor


def _default_atomic_push_probe(repo: Path, push_url: str, branch: str, sha: str) -> None:
    git_mod.probe_atomic_push(repo, push_url=push_url, base_branch=branch, base_sha=sha)


def _default_worktree_remove(repo: Path, path: Path) -> None:
    git_mod.worktree_remove(repo, path, force=True)


@dataclass(frozen=True)
class _Sync:
    """The per-invocation bundle: repo, call parameters, and every injected seam."""

    repo_root: Path
    run_id: str
    include_base: bool
    approve: Callable[[SyncCascade], bool] | None
    remote_writers: RemoteWriterProbe
    worktree_root: Path
    persistence: SyncPersistence
    reconstruct: Callable[[Path, str], TrainStatus]
    pr_facts: _PrFactsRead
    stack_read: _StackRead
    fetch: Callable[[Path, list[str]], None]
    remote_head: Callable[[Path, str], str | None]
    local_head: Callable[[Path, str], str | None]
    is_ancestor: Callable[[Path, str, str], bool]
    push_urls: Callable[[Path], list[str]]
    atomic_push_probe: Callable[[Path, str, str, str], None]
    push_atomic: Callable[[Path, list[git_mod.RefUpdate]], None]
    update_ref: Callable[[Path, str, str], None]
    delete_ref: Callable[[Path, str], None]
    list_refs: Callable[[Path, str], list[str]]
    worktree_add: Callable[[Path, Path, str], None]
    worktree_remove: Callable[[Path, Path], None]
    checkout_detached: Callable[[Path, str], None]
    rebase_onto: _RebaseOnto
    pending_read: Callable[[Path, str], continuation.PendingContinuation | None]
    manifest_write: Callable[[Path, continuation.ContinuationManifest], Path]
    sleep: Callable[[float], None]
    now: Callable[[], str]


def synchronize_train(
    repo_root: Path,
    *,
    objective_id: str,
    run_id: str,
    remote_writers: RemoteWriterProbe,
    worktree_root: Path,
    include_base: bool = False,
    approve: Callable[[SyncCascade], bool] | None = None,
    reconstruct: Callable[[Path, str], TrainStatus] = observe.reconstruct_repo_train,
    persistence_factory: Callable[[Path], SyncPersistence] = resolve_train_persistence,
    pr_facts: _PrFactsRead = stacks.pr_delivery_facts,
    stack_read: _StackRead = stacks.stack_for_pr,
    fetch: Callable[[Path, list[str]], None] = _default_fetch,
    remote_head: Callable[[Path, str], str | None] = git_mod.remote_branch_head,
    local_head: Callable[[Path, str], str | None] = git_mod.resolve_commit,
    is_ancestor: Callable[[Path, str, str], bool] = _default_is_ancestor,
    push_urls: Callable[[Path], list[str]] = git_mod.push_urls,
    atomic_push_probe: Callable[[Path, str, str, str], None] = _default_atomic_push_probe,
    push_atomic: Callable[[Path, list[git_mod.RefUpdate]], None] = git_mod.push_atomic_with_leases,
    update_ref: Callable[[Path, str, str], None] = git_mod.update_ref,
    delete_ref: Callable[[Path, str], None] = git_mod.delete_ref,
    list_refs: Callable[[Path, str], list[str]] = git_mod.list_refs,
    worktree_add: Callable[[Path, Path, str], None] = git_mod.worktree_add_detached,
    worktree_remove: Callable[[Path, Path], None] = _default_worktree_remove,
    checkout_detached: Callable[[Path, str], None] = git_mod.checkout_detached,
    rebase_onto: _RebaseOnto = git_mod.rebase_onto,
    pending_read: Callable[
        [Path, str], continuation.PendingContinuation | None
    ] = continuation.pending_continuation,
    manifest_write: Callable[
        [Path, continuation.ContinuationManifest], Path
    ] = continuation.write_manifest,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = plan.now_iso,
) -> SyncResult:
    """Synchronize the published suffix of ``objective_id``'s train (the §8.48 operation).

    ``approve`` is the cascade approval gate (``None`` = auto-approve); ``remote_writers`` is
    the required fail-closed writer preflight — there is deliberately no default.
    ``worktree_root`` hosts the disposable isolated calculation worktree
    (``<worktree_root>/sync-<operation_id>``). Raises :class:`SyncError` on every typed
    refusal; infra errors (``GitError``/``GitHubError``) propagate for the CLI boundary's
    arms, always leaving any prepared operation unresolved (recoverable).
    """
    sync = _Sync(
        repo_root=repo_root,
        run_id=run_id,
        include_base=include_base,
        approve=approve,
        remote_writers=remote_writers,
        worktree_root=worktree_root,
        persistence=persistence_factory(repo_root),
        reconstruct=reconstruct,
        pr_facts=pr_facts,
        stack_read=stack_read,
        fetch=fetch,
        remote_head=remote_head,
        local_head=local_head,
        is_ancestor=is_ancestor,
        push_urls=push_urls,
        atomic_push_probe=atomic_push_probe,
        push_atomic=push_atomic,
        update_ref=update_ref,
        delete_ref=delete_ref,
        list_refs=list_refs,
        worktree_add=worktree_add,
        worktree_remove=worktree_remove,
        checkout_detached=checkout_detached,
        rebase_onto=rebase_onto,
        pending_read=pending_read,
        manifest_write=manifest_write,
        sleep=sleep,
        now=now,
    )
    train = sync.reconstruct(repo_root, objective_id)
    if isinstance(train, NoDeliveryTrain):
        raise SyncError(
            f"objective {train.objective_id} has no delivery train ({train.reason})",
            error_type="not_stacked",
        )
    lineage = _require_lineage(train)
    _gate_continuation(sync, lineage)
    fold = sync.persistence.read_journal(train.objective_id)
    if fold.unresolved:
        op = fold.unresolved[0]
        record = op.prepared.record
        if op.kind is OperationKind.SYNC and isinstance(record, PreparedRecord):
            return _resume(sync, train, record)
        raise SyncError(
            f"operation {op.operation_id} ({op.kind.value}) is unresolved on lineage "
            f"{fold.delivery_lineage} — recover or abandon it before synchronizing",
            error_type="unresolved_operation",
        )
    return _fresh(sync, train, abandoned_operation_id=None)


# ----------------------------------------------------------------- gates + shared checks


def _require_lineage(train: DeliveryTrain) -> str:
    if train.delivery_lineage is None:
        raise SyncError(
            f"objective {train.objective_id} carries no delivery_lineage — synchronization "
            "cannot be journaled",
            error_type="not_stacked",
        )
    return train.delivery_lineage


def _gate_continuation(sync: _Sync, lineage: str) -> None:
    """The fail-closed conflict gate: ANY manifest for this lineage — parseable or not —
    refuses a fresh cascade over retained residue (clearing it is manual until the
    continue/abort surface exists)."""
    pending = sync.pending_read(sync.repo_root, lineage)
    if pending is None:
        return
    if pending.manifest is None:
        raise SyncError(
            f"a sync continuation manifest exists for this lineage at {pending.path} but "
            "could not be parsed — refusing a fresh cascade over retained conflict residue; "
            "resolve or remove the retained state manually, then delete the manifest",
            error_type="sync_conflict_pending",
        )
    raise SyncError(
        f"operation {pending.manifest.operation_id} stopped mid-conflict on node "
        f"{pending.manifest.conflict_node_id}: the conflicted worktree is retained at "
        f"{pending.manifest.worktree_path} under the manifest {pending.path} — resolve or "
        "discard the retained state manually (remove the worktree and temp refs, delete the "
        "manifest), then rerun sync",
        error_type="sync_conflict_pending",
    )


@dataclass(frozen=True)
class _ClaimedLayer:
    """One layer of the checkpoint-claimed prefix, with every claim field narrowed non-null."""

    node_id: str
    plan_id: str
    branch: str
    pr_number: int
    parent_checkpoint_sha: str
    published_head_sha: str
    writer: LayerWriter


def _claimed_prefix(train: DeliveryTrain) -> list[_ClaimedLayer]:
    """Sync's operation universe (§8.48): the maximal contiguous bottom run of layers carrying
    plan identity, a branch, a PR number, and the FULL checkpoint pair.

    Deliberately NOT ``published_prefix_len``: the train classifier truncates its verified
    prefix on exactly the discrepancies sync exists to diagnose, which would make the drift
    refusals unreachable. Malformed claims are the typed refusal ``claimed_prefix_malformed``.
    """
    claimed: list[_ClaimedLayer] = []
    boundary_hit = False
    for layer in train.layers:
        parent = layer.parent_checkpoint_sha
        head = layer.published_head_sha
        if (parent is None) != (head is None):
            raise SyncError(
                f"layer {layer.node_id} stores half a checkpoint pair "
                f"(parent={parent}, published={head}) — broken stored state; inspect "
                "`perk objective stack status` and repair before synchronizing",
                error_type="claimed_prefix_malformed",
            )
        if parent is None or head is None:
            boundary_hit = True
            continue
        if layer.plan_id is None or layer.branch is None or layer.pr_number is None:
            raise SyncError(
                f"layer {layer.node_id} stores checkpoints but is missing plan/branch/PR "
                "identity — broken stored state; inspect `perk objective stack status` and "
                "repair before synchronizing",
                error_type="claimed_prefix_malformed",
            )
        if boundary_hit:
            raise SyncError(
                f"layer {layer.node_id} stores checkpoints above an unclaimed layer — the "
                "claimed prefix must be contiguous from the bottom; inspect "
                "`perk objective stack status` and repair before synchronizing",
                error_type="claimed_prefix_malformed",
            )
        claimed.append(
            _ClaimedLayer(
                node_id=layer.node_id,
                plan_id=layer.plan_id,
                branch=layer.branch,
                pr_number=layer.pr_number,
                parent_checkpoint_sha=parent,
                published_head_sha=head,
                writer=layer.writer,
            )
        )
    return claimed


def _expected_pr_base(claimed: Sequence[_ClaimedLayer], index: int, base: str) -> str:
    """A claimed layer's expected PR base: the predecessor's branch (the objective base for
    the bottom layer). Branch names are stable under sync — bases never change."""
    return claimed[index - 1].branch if index >= 1 else base


def _check_claimed_world(
    sync: _Sync,
    train: DeliveryTrain,
    claimed: Sequence[_ClaimedLayer],
    *,
    collapse: str | None,
    when: str,
) -> None:
    """The lease-input observation shared by the step-5 preflight and the step-10
    post-approval re-observation: every claimed remote head at its checkpoint, every claimed
    PR OPEN onto its expected base at its checkpoint head, and (≥ 2 PRs) exact native
    membership. The preflight names the specific drift per axis (``collapse=None``); the
    re-observation collapses ANY difference to ``remote_drift`` (no prepared record exists
    yet — the remedy is always "rerun sync")."""
    for layer in claimed:
        observed = sync.remote_head(sync.repo_root, layer.branch)
        if observed != layer.published_head_sha:
            raise SyncError(
                f"branch {layer.branch!r} (layer {layer.node_id}) observed at "
                f"{observed or '<absent>'}, but the published-head checkpoint records "
                f"{layer.published_head_sha}{when} — the remote drifted out-of-band "
                "(adoption is a later recovery surface); rerun sync after reconciling",
                error_type=collapse or "remote_drift",
            )
    for index, layer in enumerate(claimed):
        expected_base = _expected_pr_base(claimed, index, train.base)
        facts = sync.pr_facts(number=layer.pr_number, repo_root=sync.repo_root)
        if (
            facts is None
            or facts.state != "OPEN"
            or facts.base_ref != expected_base
            or facts.head_sha != layer.published_head_sha
        ):
            observed_desc = (
                f"state={facts.state} base={facts.base_ref!r} head={facts.head_sha}"
                if facts is not None
                else "absent"
            )
            raise SyncError(
                f"PR #{layer.pr_number} (layer {layer.node_id}) observed as {observed_desc}, "
                f"expected OPEN onto {expected_base!r} at {layer.published_head_sha}{when}",
                error_type=collapse or "pr_drift",
            )
    if len(claimed) >= 2:
        desired = [layer.pr_number for layer in claimed]
        observed_stack = sync.stack_read(number=desired[0], repo_root=sync.repo_root)
        observed_members = (
            list(observed_stack.member_numbers) if observed_stack is not None else None
        )
        if observed_members != desired:
            raise SyncError(
                f"the native stack carries {observed_members}, expected exactly the claimed "
                f"prefix {desired}{when}",
                error_type=collapse or "membership_drift",
            )


def _preflight(sync: _Sync, train: DeliveryTrain, claimed: Sequence[_ClaimedLayer]) -> None:
    """Step 5: every refusal before any candidate work. Remote/PR/membership drift (the
    specific typed refusals), then the writer axes — a DIRTY checked-out worktree refuses; a
    clean ACTIVE one does not (the normal state of the just-amended layer; sync never touches
    local worktrees); the remote-writer probe fails closed."""
    _check_claimed_world(sync, train, claimed, collapse=None, when="")
    # Localize the verified remote objects (checkpoints == observed heads, so every refspec
    # exists): the ancestry checks and the rebase sources need them present locally.
    sync.fetch(sync.repo_root, [layer.branch for layer in claimed])
    dirty = [layer for layer in claimed if layer.writer is LayerWriter.DIRTY]
    if dirty:
        names = ", ".join(f"{layer.node_id} ({layer.branch})" for layer in dirty)
        raise SyncError(
            f"claimed layer worktrees carry uncommitted changes: {names} — commit or stash "
            "before synchronizing",
            error_type="dirty_worktree",
        )
    plan_ids = [layer.plan_id for layer in claimed]
    try:
        active = sync.remote_writers.active_plan_ids(plan_ids)
    except WriterObservationError as exc:
        raise SyncError(
            f"could not observe the active remote writers ({exc}) — refusing to cascade "
            "under an unreadable writer preflight",
            error_type="writer_observation_unavailable",
        ) from exc
    blocked = [layer for layer in claimed if layer.plan_id in active]
    if blocked:
        names = ", ".join(f"{layer.node_id} (plan #{layer.plan_id})" for layer in blocked)
        raise SyncError(
            f"active remote writers hold claimed layers: {names} — wait for the runs to "
            "finish before synchronizing",
            error_type="active_writer",
        )


# ----------------------------------------------------------------- the fresh protocol


def _fresh(sync: _Sync, train: DeliveryTrain, *, abandoned_operation_id: str | None) -> SyncResult:
    """Steps 4-14 (the full fresh protocol). ``abandoned_operation_id`` is carried when this
    fresh preparation follows an all-``before`` resume abandon in the same invocation."""
    lineage = _require_lineage(train)
    claimed = _claimed_prefix(train)
    if claimed:
        _preflight(sync, train, claimed)

    base_after: str | None = None
    if sync.include_base:
        base_after = train.observed_base_head_sha
        if base_after is None:
            raise SyncError(
                f"--base requested but the objective base {train.base!r} was not positively "
                "observed — the mutator fails closed where status stays tolerant; check the "
                "remote and rerun",
                error_type="base_unobserved",
            )

    # Step 6: the affected set. Locally changed ⟺ the local head exists, differs from the
    # published checkpoint, and is NOT an ancestor of it (a stale local branch is
    # information, never a revert source).
    local_heads: dict[str, str] = {}
    changed: list[bool] = []
    for layer in claimed:
        head = sync.local_head(sync.repo_root, layer.branch)
        if head is not None:
            local_heads[layer.branch] = head
        changed.append(
            head is not None
            and head != layer.published_head_sha
            and not sync.is_ancestor(sync.repo_root, head, layer.published_head_sha)
        )
    if sync.include_base:
        trigger = 0 if claimed else None
    else:
        trigger = next((i for i, moved in enumerate(changed) if moved), None)
    if trigger is None:
        return SyncResult(
            objective_id=train.objective_id,
            objective_url=train.objective_url,
            redirected_from=train.redirected_from,
            operation_id=None,
            abandoned_operation_id=abandoned_operation_id,
            no_op=True,
            declined=False,
            resumed=False,
            base_cascaded=False,
            base_advanced=_base_advanced(train),
            affected=(),
        )
    for index, layer in enumerate(claimed):
        if not changed[index]:
            continue
        head = local_heads[layer.branch]
        if not sync.is_ancestor(sync.repo_root, layer.parent_checkpoint_sha, head):
            raise SyncError(
                f"local branch {layer.branch!r} at {head} does not contain its stored parent "
                f"checkpoint {layer.parent_checkpoint_sha} — rebase {layer.branch!r} onto its "
                "parent branch and rerun sync",
                error_type="stale_parent",
            )
    affected = claimed[trigger:]

    # Step 7: capability — one receiving repository, then the no-op atomic dry-run probe
    # pinned to the bottom affected layer's branch at its verified remote head.
    urls = sync.push_urls(sync.repo_root)
    if len(urls) > 1:
        raise SyncError(
            f"origin has {len(urls)} push URLs ({urls}) — `--atomic` is atomic within one "
            "receiving repository; refusing to pretend distributed atomicity across mirrors",
            error_type="multiple_push_urls",
        )
    checks = probe_atomic_push_urls(
        sync.repo_root,
        ref_branch=affected[0].branch,
        ref_sha=affected[0].published_head_sha,
        push_urls_probe=sync.push_urls,
        atomic_push_probe=sync.atomic_push_probe,
    )
    failing = [check for check in checks if not check.ok]
    if failing:
        details = "; ".join(check.detail for check in failing)
        raise SyncError(
            f"the atomic-push capability probe failed: {details}",
            error_type="atomic_push_unsupported",
        )

    # Steps 8-14 under the centralized cleanup guard: on EVERY exit — success, refusal,
    # decline, error, post-prepare failure — best-effort delete this operation's temp refs
    # and remove its isolated worktree. Disarmed in exactly one case: the continuation
    # manifest was durably written (the conflict arm). Post-push arms never need the temp
    # refs: an applied push holds the candidates remotely; an unapplied push's resume arm
    # abandons and recomputes fresh.
    operation_id = mint_operation_id()
    worktree = sync.worktree_root / f"sync-{operation_id}"
    ref_prefix = f"refs/perk/sync/{operation_id}/"
    disarmed = False
    try:
        return _execute(
            sync,
            train,
            claimed,
            affected,
            local_heads=local_heads,
            changed=changed[trigger:],
            base_after=base_after,
            operation_id=operation_id,
            abandoned_operation_id=abandoned_operation_id,
            worktree=worktree,
            ref_prefix=ref_prefix,
            lineage=lineage,
        )
    except _ConflictRetained as stop:
        disarmed = True
        raise stop.error from None
    finally:
        if not disarmed:
            _cleanup(sync, ref_prefix, worktree)


def _execute(
    sync: _Sync,
    train: DeliveryTrain,
    claimed: Sequence[_ClaimedLayer],
    affected: Sequence[_ClaimedLayer],
    *,
    local_heads: Mapping[str, str],
    changed: Sequence[bool],
    base_after: str | None,
    operation_id: str,
    abandoned_operation_id: str | None,
    worktree: Path,
    ref_prefix: str,
    lineage: str,
) -> SyncResult:
    """Steps 8-14 straight-line (the caller owns the cleanup guard): candidates → approval →
    post-approval re-observation → prepared record → one atomic push → verification →
    checkpoints bottom→top → completed."""
    candidates = _calculate_candidates(
        sync,
        affected,
        local_heads=local_heads,
        changed=changed,
        base_after=base_after,
        operation_id=operation_id,
        worktree=worktree,
        ref_prefix=ref_prefix,
        objective_id=train.objective_id,
        lineage=lineage,
    )

    # Step 9: the approval gate. Declined → the guard cleans; nothing was journaled.
    layers = tuple(
        SyncedLayer(
            node_id=layer.node_id,
            plan_id=layer.plan_id,
            branch=layer.branch,
            pr_number=layer.pr_number,
            before_sha=layer.published_head_sha,
            after_sha=candidates[pos],
        )
        for pos, layer in enumerate(affected)
    )
    cascade = SyncCascade(
        objective_id=train.objective_id,
        base_branch=train.base,
        include_base=sync.include_base,
        base_before=affected[0].parent_checkpoint_sha if sync.include_base else None,
        base_after=base_after,
        layers=layers,
    )
    if sync.approve is not None and not sync.approve(cascade):
        return SyncResult(
            objective_id=train.objective_id,
            objective_url=train.objective_url,
            redirected_from=train.redirected_from,
            operation_id=None,
            abandoned_operation_id=abandoned_operation_id,
            no_op=False,
            declined=True,
            resumed=False,
            base_cascaded=False,
            base_advanced=_base_advanced(train),
            affected=(),
        )

    # Step 10: post-approval re-observation — the approval pause is arbitrary, so every
    # lease input is re-read before the journal write; ANY difference from the captured
    # before-set is remote_drift with no prepared record written.
    _reobserve(sync, train, claimed, affected, base_after=base_after)

    # Step 11: the prepared record, journal-first (the §8.43 read-back discipline).
    new_parents = _new_parent_edges(affected, candidates, base_after=base_after)
    record = PreparedRecord(
        operation_id=operation_id,
        operation_kind=OperationKind.SYNC,
        delivery_lineage=lineage,
        objective_id=train.objective_id,
        run_id=sync.run_id,
        created=sync.now(),
        affected_plans=tuple(layer.plan_id for layer in affected),
        before=_before_payload(sync, train, claimed, affected, base_after=base_after),
        after=_after_payload(train, claimed, affected, candidates, base_after=base_after),
    )
    try:
        sync.persistence.append_prepared(train.objective_id, record)
    except UnresolvedOperationError as exc:
        raise SyncError(str(exc), error_type="unresolved_operation") from exc

    # Step 12: ONE atomic push, every affected ref under its exact lease.
    _push(sync, train.objective_id, operation_id, layers)

    # Steps 13-14.
    _verify_postconditions(sync, train, claimed, affected, candidates)
    return _complete(
        sync,
        train,
        layers,
        new_parents=new_parents,
        operation_id=operation_id,
        abandoned_operation_id=abandoned_operation_id,
        resumed=False,
        base_cascaded=sync.include_base,
    )


def _base_advanced(train: DeliveryTrain) -> bool:
    return any(finding.code == "base_advanced" for finding in train.findings)


class _ConflictRetained(Exception):
    """Internal control flow: the conflict arm retained its residue (manifest written) —
    the cleanup guard must disarm before the typed ``rebase_conflict`` propagates."""

    def __init__(self, error: SyncError) -> None:
        super().__init__(str(error))
        self.error = error


def _cleanup(sync: _Sync, ref_prefix: str, worktree: Path) -> None:
    """Best-effort residue removal (never raises): every temp ref under this operation's
    namespace, then the isolated worktree."""
    with contextlib.suppress(git_mod.GitError, OSError):
        for ref in sync.list_refs(sync.repo_root, ref_prefix):
            with contextlib.suppress(git_mod.GitError):
                sync.delete_ref(sync.repo_root, ref)
    # No existence pre-check: the remove seam itself tolerates an absent worktree (its
    # error is suppressed), which keeps the guard observable through the injected seam.
    with contextlib.suppress(git_mod.GitError, OSError):
        sync.worktree_remove(sync.repo_root, worktree)


# ----------------------------------------------------------------- candidate calculation


def _calculate_candidates(
    sync: _Sync,
    affected: Sequence[_ClaimedLayer],
    *,
    local_heads: Mapping[str, str],
    changed: Sequence[bool],
    base_after: str | None,
    operation_id: str,
    worktree: Path,
    ref_prefix: str,
    objective_id: str,
    lineage: str,
) -> list[str]:
    """Step 8: bottom-up candidate transplants in ONE isolated worktree.

    Per layer: source = the local head when locally changed, else the verified published
    head; new parent edge = the observed base head (bottom, cascading) / the unchanged
    stored edge (bottom, lowest-changed trigger) / the predecessor's fresh candidate;
    edges equal → candidate = source (fast path, no rebase). Each candidate lands in a
    disposable temp ref. A rebase conflict writes the continuation manifest, disarms the
    guard (via :class:`_ConflictRetained`), and raises ``rebase_conflict`` — no remote ref
    and no journal record exists at that point.
    """
    sources = [
        local_heads[layer.branch] if changed[pos] else layer.published_head_sha
        for pos, layer in enumerate(affected)
    ]
    sync.worktree_add(sync.repo_root, worktree, sources[0])
    candidates: list[str] = []
    manifest_layers: list[continuation.ContinuationLayer] = []
    for pos, layer in enumerate(affected):
        source = sources[pos]
        if pos == 0:
            new_parent = base_after if base_after is not None else layer.parent_checkpoint_sha
        else:
            new_parent = candidates[pos - 1]
        old_parent = layer.parent_checkpoint_sha
        temp_ref = f"{ref_prefix}{layer.branch}"
        if new_parent == old_parent:
            candidate = source
        else:
            sync.checkout_detached(worktree, source)
            outcome = sync.rebase_onto(worktree, onto=new_parent, upstream=old_parent)
            if isinstance(outcome, git_mod.RebaseConflict):
                manifest_layers.append(
                    continuation.ContinuationLayer(
                        node_id=layer.node_id,
                        plan_id=layer.plan_id,
                        branch=layer.branch,
                        before_sha=layer.published_head_sha,
                        old_parent_edge=old_parent,
                        source_sha=source,
                        new_parent_edge=new_parent,
                        candidate_temp_ref=temp_ref,
                        candidate_sha=None,
                    )
                )
                manifest_layers.extend(
                    continuation.ContinuationLayer(
                        node_id=rest.node_id,
                        plan_id=rest.plan_id,
                        branch=rest.branch,
                        before_sha=rest.published_head_sha,
                        old_parent_edge=rest.parent_checkpoint_sha,
                        source_sha=sources[rest_pos],
                        new_parent_edge=None,
                        candidate_temp_ref=f"{ref_prefix}{rest.branch}",
                        candidate_sha=None,
                    )
                    for rest_pos, rest in enumerate(affected)
                    if rest_pos > pos
                )
                manifest = continuation.ContinuationManifest(
                    operation_id=operation_id,
                    objective_id=objective_id,
                    delivery_lineage=lineage,
                    run_id=sync.run_id,
                    include_base=sync.include_base,
                    captured_base_head=base_after,
                    layers=tuple(manifest_layers),
                    conflict_node_id=layer.node_id,
                    worktree_path=str(worktree),
                    created=sync.now(),
                )
                path = sync.manifest_write(sync.repo_root, manifest)
                raise _ConflictRetained(
                    SyncError(
                        f"the candidate rebase for layer {layer.node_id} "
                        f"({layer.branch!r} onto {new_parent}) hit a conflict — the "
                        f"conflicted worktree is retained at {worktree} under the "
                        f"continuation manifest {path}; no remote ref and no journal record "
                        "was created. Resolve or discard the retained state manually, delete "
                        "the manifest, then rerun sync.",
                        error_type="rebase_conflict",
                    )
                )
            candidate = outcome.head_sha
        sync.update_ref(sync.repo_root, temp_ref, candidate)
        candidates.append(candidate)
        manifest_layers.append(
            continuation.ContinuationLayer(
                node_id=layer.node_id,
                plan_id=layer.plan_id,
                branch=layer.branch,
                before_sha=layer.published_head_sha,
                old_parent_edge=old_parent,
                source_sha=source,
                new_parent_edge=new_parent,
                candidate_temp_ref=temp_ref,
                candidate_sha=candidate,
            )
        )
    return candidates


def _new_parent_edges(
    affected: Sequence[_ClaimedLayer], candidates: Sequence[str], *, base_after: str | None
) -> list[str]:
    """Each affected layer's NEW parent edge — what step 14 writes as its
    ``parent_checkpoint_sha``: the observed base head (bottom, cascading) / the unchanged
    stored edge (bottom otherwise) / the predecessor's candidate."""
    edges: list[str] = []
    for pos, layer in enumerate(affected):
        if pos == 0:
            edges.append(base_after if base_after is not None else layer.parent_checkpoint_sha)
        else:
            edges.append(candidates[pos - 1])
    return edges


# ----------------------------------------------------------------- re-observation + payloads


def _reobserve(
    sync: _Sync,
    train: DeliveryTrain,
    claimed: Sequence[_ClaimedLayer],
    affected: Sequence[_ClaimedLayer],
    *,
    base_after: str | None,
) -> None:
    """Step 10: re-read every lease input after the (arbitrarily long) approval pause — the
    claimed world plus the base head when cascading. Any difference from the captured
    before-set is ``remote_drift`` with no prepared record written (rerun sync)."""
    when = " (re-observed after approval)"
    _check_claimed_world(sync, train, claimed, collapse="remote_drift", when=when)
    if base_after is not None:
        observed = sync.remote_head(sync.repo_root, train.base)
        if observed != base_after:
            raise SyncError(
                f"the objective base {train.base!r} moved to {observed or '<absent>'} while "
                f"approval was pending (captured {base_after}) — no prepared record was "
                "written; rerun sync",
                error_type="remote_drift",
            )


def _before_payload(
    sync: _Sync,
    train: DeliveryTrain,
    claimed: Sequence[_ClaimedLayer],
    affected: Sequence[_ClaimedLayer],
    *,
    base_after: str | None,
) -> dict[str, object]:
    """The sync-kind ``before`` shape (§8.48): the exact observed lease values — base present
    iff cascading, the affected branches at their checkpoints, their PRs, and the claimed
    stack membership (``None`` below two PRs)."""
    offset = len(claimed) - len(affected)
    prs = [
        {
            "number": layer.pr_number,
            "head_sha": layer.published_head_sha,
            "base": _expected_pr_base(claimed, offset + pos, train.base),
        }
        for pos, layer in enumerate(affected)
    ]
    stack_payload: dict[str, object] | None = None
    if len(claimed) >= 2:
        stack_payload = {"members": [layer.pr_number for layer in claimed]}
    return {
        "base": {"branch": train.base, "sha": base_after} if base_after is not None else None,
        "branches": [{"ref": layer.branch, "sha": layer.published_head_sha} for layer in affected],
        "prs": prs,
        "stack": stack_payload,
    }


def _after_payload(
    train: DeliveryTrain,
    claimed: Sequence[_ClaimedLayer],
    affected: Sequence[_ClaimedLayer],
    candidates: Sequence[str],
    *,
    base_after: str | None,
) -> dict[str, object]:
    """The sync-kind ``after`` shape (§8.48): the candidates. PR bases are unchanged by
    construction — sync moves heads, never branch names."""
    offset = len(claimed) - len(affected)
    return {
        "branches": [
            {"ref": layer.branch, "sha": candidates[pos]} for pos, layer in enumerate(affected)
        ],
        "prs": [
            {
                "number": layer.pr_number,
                "head_sha": candidates[pos],
                "base": _expected_pr_base(claimed, offset + pos, train.base),
            }
            for pos, layer in enumerate(affected)
        ],
        "base_parent": base_after,
    }


# ----------------------------------------------------------------- push + verification


def _push(
    sync: _Sync,
    objective_id: str,
    operation_id: str,
    layers: Sequence[SyncedLayer],
) -> None:
    """Step 12: one atomic exact-leased multi-ref push. A rejection is classified by
    refetching every affected head: all-at-before confirmed → abandon-with-proof +
    ``push_rejected`` (retry = rerun sync); an unreadable refetch →
    ``postcondition_unverified`` (unresolved); a mixed observation → ``sync_drift``
    (unresolved, fail closed). Individual refs are NEVER retried."""
    updates = [
        git_mod.RefUpdate(
            branch=layer.branch, expected_remote_sha=layer.before_sha, new_sha=layer.after_sha
        )
        for layer in layers
    ]
    try:
        sync.push_atomic(sync.repo_root, updates)
    except git_mod.PushRejectedError as exc:
        try:
            observed = [
                (layer.branch, sync.remote_head(sync.repo_root, layer.branch)) for layer in layers
            ]
        except git_mod.GitError as refetch_exc:
            raise SyncError(
                f"the atomic push was rejected AND the verifying refetch failed "
                f"({refetch_exc}) — the operation stays unresolved",
                error_type="postcondition_unverified",
            ) from refetch_exc
        if all(sha == layer.before_sha for (_, sha), layer in zip(observed, layers, strict=True)):
            sync.persistence.append_outcome(
                objective_id,
                OutcomeRecord(
                    operation_id=operation_id,
                    role=EventRole.ABANDONED,
                    created=sync.now(),
                    observed={
                        "branches": [{"ref": branch, "sha": sha} for branch, sha in observed]
                    },
                ),
            )
            raise SyncError(
                f"the atomic push was rejected (a lease no longer held) and every affected "
                f"branch verified at its before state — the operation was abandoned with "
                f"proof; rerun sync to retry\n{exc}",
                error_type="push_rejected",
            ) from exc
        raise SyncError(
            f"the atomic push was rejected and the affected branches verified in a MIXED "
            f"state ({[(b, s) for b, s in observed]}) — refusing to guess; the operation "
            "stays unresolved for recovery",
            error_type="sync_drift",
        ) from exc


def _verify_postconditions(
    sync: _Sync,
    train: DeliveryTrain,
    claimed: Sequence[_ClaimedLayer],
    affected: Sequence[_ClaimedLayer],
    candidates: Sequence[str],
    *,
    expected_bases: Sequence[str] | None = None,
    expected_members: Sequence[int] | None = None,
) -> None:
    """Step 13: refetch every affected branch — head == candidate; PR facts through the
    bounded settle poll (GitHub's PR-head propagation lags a push) before any mismatch
    classifies; membership must still be exact. Failed arms leave the operation unresolved
    (recoverable). The resume roll-forward passes recorded ``expected_bases``/``members``."""
    try:
        sync.fetch(sync.repo_root, [layer.branch for layer in affected])
        heads = [sync.remote_head(sync.repo_root, layer.branch) for layer in affected]
    except git_mod.GitError as exc:
        raise SyncError(
            f"could not re-observe the affected branches after the push ({exc}) — the "
            "operation stays unresolved",
            error_type="postcondition_unverified",
        ) from exc
    for pos, layer in enumerate(affected):
        if heads[pos] != candidates[pos]:
            raise SyncError(
                f"branch {layer.branch!r} verified at {heads[pos]}, expected the pushed "
                f"candidate {candidates[pos]} — a foreign writer moved the branch; the "
                "operation stays unresolved",
                error_type="sync_drift",
            )
    offset = len(claimed) - len(affected)
    for pos, layer in enumerate(affected):
        expected_base = (
            expected_bases[pos]
            if expected_bases is not None
            else _expected_pr_base(claimed, offset + pos, train.base)
        )
        _settle_poll_pr(sync, layer, expected_base=expected_base, candidate=candidates[pos])
    desired = (
        list(expected_members)
        if expected_members is not None
        else [layer.pr_number for layer in claimed]
    )
    if len(desired) >= 2:
        try:
            observed_stack = sync.stack_read(number=desired[0], repo_root=sync.repo_root)
        except GitHubError as exc:
            raise SyncError(
                f"could not re-observe the native stack after the push ({exc}) — the "
                "operation stays unresolved",
                error_type="postcondition_unverified",
            ) from exc
        observed_members = (
            list(observed_stack.member_numbers) if observed_stack is not None else None
        )
        if observed_members != desired:
            raise SyncError(
                f"the native stack verified as {observed_members}, expected exactly "
                f"{desired} — the operation stays unresolved",
                error_type="membership_drift",
            )


def _settle_poll_pr(
    sync: _Sync, layer: _ClaimedLayer, *, expected_base: str, candidate: str
) -> None:
    """The bounded PR settle poll: up to ``_SETTLE_ATTEMPTS`` observations before a mismatch
    classifies as ``pr_drift``; an unreadable read is ``postcondition_unverified``."""
    facts: stacks.PrDeliveryFacts | None = None
    for attempt in range(_SETTLE_ATTEMPTS):
        try:
            facts = sync.pr_facts(number=layer.pr_number, repo_root=sync.repo_root)
        except GitHubError as exc:
            raise SyncError(
                f"could not re-observe PR #{layer.pr_number} after the push ({exc}) — the "
                "operation stays unresolved",
                error_type="postcondition_unverified",
            ) from exc
        if (
            facts is not None
            and facts.state == "OPEN"
            and facts.base_ref == expected_base
            and facts.head_sha == candidate
        ):
            return
        if attempt < _SETTLE_ATTEMPTS - 1:
            sync.sleep(_SETTLE_DELAY_SECONDS)
    observed_desc = (
        f"state={facts.state} base={facts.base_ref!r} head={facts.head_sha}"
        if facts is not None
        else "absent"
    )
    raise SyncError(
        f"PR #{layer.pr_number} verified as {observed_desc} after {_SETTLE_ATTEMPTS} "
        f"observations, expected OPEN onto {expected_base!r} at {candidate} — the operation "
        "stays unresolved",
        error_type="pr_drift",
    )


def _complete(
    sync: _Sync,
    train: DeliveryTrain,
    layers: Sequence[SyncedLayer],
    *,
    new_parents: Sequence[str],
    operation_id: str,
    abandoned_operation_id: str | None,
    resumed: bool,
    base_cascaded: bool,
) -> SyncResult:
    """Step 14 (publish's step-12 ordering): checkpoints bottom→top, then the ``completed``
    outcome. A crash between the checkpoint writes and completion reconstructs as
    roll-forward — merge-writes + idempotent byte-identical appends."""
    for pos, layer in enumerate(layers):
        sync.persistence.write_checkpoints(
            layer.plan_id,
            parent_checkpoint_sha=new_parents[pos],
            published_head_sha=layer.after_sha,
        )
    sync.persistence.append_outcome(
        train.objective_id,
        OutcomeRecord(
            operation_id=operation_id,
            role=EventRole.COMPLETED,
            created=sync.now(),
            observed={
                "branches": [{"ref": layer.branch, "sha": layer.after_sha} for layer in layers],
                "prs": [
                    {"number": layer.pr_number, "head_sha": layer.after_sha} for layer in layers
                ],
            },
        ),
    )
    return SyncResult(
        objective_id=train.objective_id,
        objective_url=train.objective_url,
        redirected_from=train.redirected_from,
        operation_id=operation_id,
        abandoned_operation_id=abandoned_operation_id,
        no_op=False,
        declined=False,
        resumed=resumed,
        base_cascaded=base_cascaded,
        base_advanced=_base_advanced(train),
        affected=tuple(layers),
    )


# ----------------------------------------------------------------- the resume path


def _resume(sync: _Sync, train: DeliveryTrain, record: PreparedRecord) -> SyncResult:
    """An unresolved SYNC on this lineage: re-derive the expected states from the prepared
    record, corroborate the fresh reconstruction, then observe every recorded ref —
    all-at-``after`` → roll forward (steps 13-14 under the same operation); all-at-``before``
    → abandon-with-proof + a FRESH preparation in the same invocation (a deliberate deviation
    from publish's same-operation retry: sync's candidates live in disposable temp refs that
    do not survive a crash, and a recomputed rebase yields different SHAs); mixed/unrelated →
    ``sync_drift``, unresolved, fail closed."""
    lineage = _require_lineage(train)
    if record.delivery_lineage != lineage:
        raise _resume_drift(
            record.operation_id,
            "delivery_lineage",
            expected=record.delivery_lineage,
            derived=lineage,
        )
    recorded = _decode_record(record)
    matched = _corroborate_record(sync, train, record, recorded)
    observed: list[str | None] = [
        sync.remote_head(sync.repo_root, entry.branch) for entry in recorded
    ]
    if all(sha == entry.after_sha for sha, entry in zip(observed, recorded, strict=True)):
        candidates = [entry.after_sha for entry in recorded]
        new_parents = _recorded_parent_edges(record, recorded, matched)
        _verify_postconditions(
            sync,
            train,
            matched,
            matched,
            candidates,
            expected_bases=[entry.pr_base for entry in recorded],
            expected_members=_recorded_members(record),
        )
        layers = tuple(
            SyncedLayer(
                node_id=matched[pos].node_id,
                plan_id=matched[pos].plan_id,
                branch=entry.branch,
                pr_number=entry.pr_number,
                before_sha=entry.before_sha,
                after_sha=entry.after_sha,
            )
            for pos, entry in enumerate(recorded)
        )
        return _complete(
            sync,
            train,
            layers,
            new_parents=new_parents,
            operation_id=record.operation_id,
            abandoned_operation_id=None,
            resumed=True,
            base_cascaded=_record_base(record) is not None,
        )
    if all(sha == entry.before_sha for sha, entry in zip(observed, recorded, strict=True)):
        sync.persistence.append_outcome(
            train.objective_id,
            OutcomeRecord(
                operation_id=record.operation_id,
                role=EventRole.ABANDONED,
                created=sync.now(),
                observed={
                    "branches": [
                        {"ref": entry.branch, "sha": sha}
                        for sha, entry in zip(observed, recorded, strict=True)
                    ]
                },
            ),
        )
        return _fresh(sync, train, abandoned_operation_id=record.operation_id)
    raise SyncError(
        f"operation {record.operation_id}'s recorded refs verified in a MIXED state "
        f"({[(e.branch, sha) for sha, e in zip(observed, recorded, strict=True)]}), matching "
        "neither the "
        "prepared before nor after set — refusing to guess; the operation stays unresolved",
        error_type="sync_drift",
    )


@dataclass(frozen=True)
class _RecordedLayer:
    """One affected layer as the prepared record captured it (parallel arrays decoded)."""

    plan_id: str
    branch: str
    before_sha: str
    after_sha: str
    pr_number: int
    pr_base: str


def _resume_drift(operation_id: str, what: str, *, expected: object, derived: object) -> SyncError:
    return SyncError(
        f"operation {operation_id}'s prepared record no longer matches the reconstructed "
        f"train: recorded {what} {expected!r}, derived {derived!r} — the authorities drifted "
        "while the operation was unresolved; refusing to complete it",
        error_type="sync_drift",
    )


def _decode_record(record: PreparedRecord) -> list[_RecordedLayer]:
    """Decode the parallel before/after arrays into per-layer entries; any structural hole is
    ``sync_drift`` (a record this operation cannot account for is never resumed)."""
    before_branches = _seq_of_mappings(record.before.get("branches"))
    after_branches = _seq_of_mappings(record.after.get("branches"))
    after_prs = _seq_of_mappings(record.after.get("prs"))
    plans = record.affected_plans
    if (
        before_branches is None
        or after_branches is None
        or after_prs is None
        or not (len(plans) == len(before_branches) == len(after_branches) == len(after_prs))
        or not plans
    ):
        raise _resume_drift(
            record.operation_id,
            "payload shape",
            expected="parallel affected_plans/branches/prs arrays",
            derived="a structurally incomplete record",
        )
    entries: list[_RecordedLayer] = []
    for pos, plan_id in enumerate(plans):
        ref = before_branches[pos].get("ref")
        before_sha = before_branches[pos].get("sha")
        after_ref = after_branches[pos].get("ref")
        after_sha = after_branches[pos].get("sha")
        number = after_prs[pos].get("number")
        base = after_prs[pos].get("base")
        if (
            not isinstance(ref, str)
            or not isinstance(before_sha, str)
            or after_ref != ref
            or not isinstance(after_sha, str)
            or not isinstance(number, int)
            or not isinstance(base, str)
        ):
            raise _resume_drift(
                record.operation_id,
                f"layer entry {pos}",
                expected="matching ref/sha/pr fields",
                derived={"ref": ref, "after_ref": after_ref, "number": number, "base": base},
            )
        entries.append(
            _RecordedLayer(
                plan_id=plan_id,
                branch=ref,
                before_sha=before_sha,
                after_sha=after_sha,
                pr_number=number,
                pr_base=base,
            )
        )
    return entries


def _corroborate_record(
    sync: _Sync,
    train: DeliveryTrain,
    record: PreparedRecord,
    recorded: Sequence[_RecordedLayer],
) -> list[_ClaimedLayer]:
    """The fresh reconstruction must still agree with the record — each recorded plan maps to
    a train layer whose branch and PR number match. Any disagreement is ``sync_drift``."""
    matched: list[_ClaimedLayer] = []
    by_plan = {layer.plan_id: layer for layer in train.layers if layer.plan_id is not None}
    for entry in recorded:
        layer = by_plan.get(entry.plan_id)
        if layer is None:
            raise _resume_drift(
                record.operation_id, "affected plan", expected=entry.plan_id, derived="absent"
            )
        if layer.branch != entry.branch:
            raise _resume_drift(
                record.operation_id,
                f"branch for plan #{entry.plan_id}",
                expected=entry.branch,
                derived=layer.branch,
            )
        if layer.pr_number != entry.pr_number:
            raise _resume_drift(
                record.operation_id,
                f"PR for plan #{entry.plan_id}",
                expected=entry.pr_number,
                derived=layer.pr_number,
            )
        if layer.parent_checkpoint_sha is None or layer.published_head_sha is None:
            raise _resume_drift(
                record.operation_id,
                f"checkpoints for plan #{entry.plan_id}",
                expected="a full stored checkpoint pair",
                derived=(layer.parent_checkpoint_sha, layer.published_head_sha),
            )
        matched.append(
            _ClaimedLayer(
                node_id=layer.node_id,
                plan_id=entry.plan_id,
                branch=entry.branch,
                pr_number=entry.pr_number,
                parent_checkpoint_sha=layer.parent_checkpoint_sha,
                published_head_sha=layer.published_head_sha,
                writer=layer.writer,
            )
        )
    return matched


def _recorded_parent_edges(
    record: PreparedRecord,
    recorded: Sequence[_RecordedLayer],
    matched: Sequence[_ClaimedLayer],
) -> list[str]:
    """The roll-forward parent edges, re-derived from the record: the bottom affected layer's
    is the recorded ``base_parent`` when the operation cascaded the base (else its stored,
    unchanged parent edge — idempotent under a partial step-14 crash because a non-cascading
    bottom never changes it); every higher layer's is the predecessor's candidate."""
    base_parent = record.after.get("base_parent")
    edges: list[str] = []
    for pos in range(len(recorded)):
        if pos >= 1:
            edges.append(recorded[pos - 1].after_sha)
        elif isinstance(base_parent, str):
            edges.append(base_parent)
        else:
            edges.append(matched[pos].parent_checkpoint_sha)
    return edges


def _record_base(record: PreparedRecord) -> Mapping[str, object] | None:
    return _opt_mapping(record.before.get("base"))


def _recorded_members(record: PreparedRecord) -> list[int] | None:
    """The recorded claimed-stack membership (``None`` when the record captured no stack —
    below two claimed PRs)."""
    stack = _opt_mapping(record.before.get("stack"))
    if stack is None:
        return None
    members = stack.get("members")
    if not isinstance(members, list):
        return None
    return [m for m in members if isinstance(m, int)]


def _opt_mapping(value: object) -> Mapping[str, object] | None:
    """A journal-payload field read as a mapping, else ``None`` (tolerant). The ``cast``
    confines the documented ty isinstance-narrowing quirk to this leaf (mirroring
    ``publish._opt_mapping``)."""
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else None


def _seq_of_mappings(value: object) -> list[Mapping[str, object]] | None:
    if not isinstance(value, list):
        return None
    items = [_opt_mapping(item) for item in value]
    narrowed = [item for item in items if item is not None]
    if len(narrowed) != len(items):
        return None
    return narrowed
