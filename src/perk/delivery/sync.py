"""The delivery **sync** operation — published-suffix synchronization (contracts.md §8.49).

The transactional cascade `perk objective stack sync` routes through: change a published
stacked layer (or re-anchor the whole train onto an advanced objective base) and move every
published successor with it — candidates computed by rebase in an isolated worktree, approved
as one rendered cascade, journaled first, then pushed as ONE atomic multi-ref operation under
exact leases, verified, and checkpointed bottom→top. Every effectful callable is
keyword-injectable with production defaults (the ``publish.py`` pattern; tests pass fakes).

The concurrency contract mirrors publish's: mutations are strictly serialized in-process; the
cross-machine serialization is the one-unresolved-operation journal gate plus the exact push
leases — the remote itself arbitrates competing writers. Failures after the prepared record
leave the operation **unresolved** (recoverable) — with one proven exception: a rejected push
whose refetch confirms EVERY ref still at its before state is abandoned-with-proof (a
terminal outcome; the remedy is a rerun). Refusals before the record write nothing. The one
deliberately retained failure state is the mid-rebase conflict: the conflicted worktree stays
in place under a continuation manifest (:mod:`perk.delivery.continuation`) and a fresh sync
refuses until the human resumes it (:func:`continue_train_sync`, ``sync --continue``) or
discards it (:func:`abort_train_sync`, ``sync --abort``). A machine-local advisory lock
(:mod:`perk.delivery.oplock`) serializes the mutating entries (fresh/resume, continue, abort)
with the recover operation; a busy lock is the typed refusal ``operation_in_progress``.
"""

import contextlib
import itertools
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast

from perk import plan
from perk.delivery import continuation, observe, oplock
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
        # | invalid_input | adopt_blocked | no_continuation | continuation_stale
        # | continuation_invalid | rebase_in_progress | operation_in_progress
        # | git_error | github_error (contracts.md §8.49 declares the full bounded set;
        # git_error/github_error are the CLI's mapping of raw infra raises)
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
    """The verified outcome of one sync invocation (the §8.49 result-arm table).

    Invariant: ``operation_id`` is non-null ⟺ a PREPARED record was journaled by (or resumed
    by) this invocation — the no-op, declined, dry-run, and abort arms never journal one.
    ``abandoned_operation_id`` names the previously unresolved operation this invocation
    abandoned-with-proof (that abandon IS journaled, under the old id) before re-running the
    fresh protocol — whose no-op and declined arms are therefore reachable with a null
    ``operation_id`` and a non-null ``abandoned_operation_id``. ``base_advanced`` is the
    status notice (the CLI's ``--base`` hint), independent of whether this run cascaded the
    base.

    Additive arms (contracts.md §8.49): ``dry_run`` marks the strictly side-effect-free
    preview (``affected`` carries the computed cascade, nothing journaled/pushed);
    ``adopted_node`` names the layer whose remote head this invocation adopted (or
    previewed adopting); ``continued`` marks a continuation resume (``declined`` composes:
    a declined continue retains everything); ``aborted`` marks a discarded continuation
    (``aborted: False, declined: True`` is the declined-abort success). ``notes`` are
    loud human-facing detail lines (cleanup/retirement failures) — never failures.
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
    dry_run: bool = False
    adopted_node: str | None = None
    continued: bool = False
    aborted: bool = False
    notes: tuple[str, ...] = ()


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


def _default_path_exists(path: Path) -> bool:
    return path.exists()


class SyncRecordSeams(Protocol):
    """The narrow read/persist seam bundle the SYNC/ADOPT record-recovery core consumes —
    structurally satisfied by :class:`_Sync` and by the recover operation's bundle
    (contracts.md §8.51 shares sync's complete resume validation + conclusion pipeline)."""

    @property
    def repo_root(self) -> Path: ...
    @property
    def persistence(self) -> SyncPersistence: ...
    @property
    def pr_facts(self) -> _PrFactsRead: ...
    @property
    def stack_read(self) -> _StackRead: ...
    @property
    def fetch(self) -> Callable[[Path, list[str]], None]: ...
    @property
    def remote_head(self) -> Callable[[Path, str], str | None]: ...
    @property
    def sleep(self) -> Callable[[float], None]: ...
    @property
    def now(self) -> Callable[[], str]: ...


@dataclass(frozen=True)
class _Sync:
    """The per-invocation bundle: repo, call parameters, and every injected seam."""

    repo_root: Path
    run_id: str
    include_base: bool
    dry_run: bool
    adopt_node: str | None
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
    worktree_prune: Callable[[Path], None]
    checkout_detached: Callable[[Path, str], None]
    rebase_onto: _RebaseOnto
    pending_read: Callable[[Path, str], continuation.PendingContinuation | None]
    manifest_write: Callable[[Path, continuation.ContinuationManifest], Path]
    manifest_clear: Callable[[Path, str], None]
    path_exists: Callable[[Path], bool]
    rebase_in_progress: Callable[[Path], bool]
    worktree_dirty: Callable[[Path], bool]
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
    dry_run: bool = False,
    adopt_node: str | None = None,
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
    worktree_prune: Callable[[Path], None] = git_mod.worktree_prune,
    checkout_detached: Callable[[Path, str], None] = git_mod.checkout_detached,
    rebase_onto: _RebaseOnto = git_mod.rebase_onto,
    pending_read: Callable[
        [Path, str], continuation.PendingContinuation | None
    ] = continuation.pending_continuation,
    manifest_write: Callable[
        [Path, continuation.ContinuationManifest], Path
    ] = continuation.write_manifest,
    manifest_clear: Callable[[Path, str], None] = continuation.clear_manifest,
    path_exists: Callable[[Path], bool] = _default_path_exists,
    rebase_in_progress: Callable[[Path], bool] = git_mod.rebase_in_progress,
    worktree_dirty: Callable[[Path], bool] = git_mod.is_dirty,
    lock: Callable[[Path], AbstractContextManager[None]] = oplock.stack_operation_lock,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = plan.now_iso,
) -> SyncResult:
    """Synchronize the published suffix of ``objective_id``'s train (the §8.49 operation).

    ``approve`` is the cascade approval gate (``None`` = auto-approve); ``remote_writers`` is
    the required fail-closed writer preflight — there is deliberately no default.
    ``worktree_root`` hosts the disposable isolated calculation worktree
    (``<worktree_root>/sync-<operation_id>``). ``dry_run`` stops at the approval boundary
    (strictly side-effect-free); ``adopt_node`` adopts one layer's out-of-band remote head
    as its new source (journal kind ADOPT). Raises :class:`SyncError` on every typed
    refusal; infra errors (``GitError``/``GitHubError``) propagate for the CLI boundary's
    arms, always leaving any prepared operation unresolved (recoverable).
    """
    if adopt_node is not None and include_base:
        # Flag validation lives at the CLI boundary; this is the defensive assert-guard for
        # the impossible combination reaching the operation directly.
        raise SyncError(
            "--adopt and --base are mutually exclusive — adopt the layer first, then rerun "
            "with --base (sequential invocations reach the same state)",
            error_type="invalid_input",
        )
    sync = _make_sync(
        repo_root,
        run_id=run_id,
        include_base=include_base,
        dry_run=dry_run,
        adopt_node=adopt_node,
        approve=approve,
        remote_writers=remote_writers,
        worktree_root=worktree_root,
        persistence_factory=persistence_factory,
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
        worktree_prune=worktree_prune,
        checkout_detached=checkout_detached,
        rebase_onto=rebase_onto,
        pending_read=pending_read,
        manifest_write=manifest_write,
        manifest_clear=manifest_clear,
        path_exists=path_exists,
        rebase_in_progress=rebase_in_progress,
        worktree_dirty=worktree_dirty,
        sleep=sleep,
        now=now,
    )
    with _held_operation_lock(lock, repo_root):
        return _synchronize(sync, objective_id)


def _make_sync(
    repo_root: Path,
    *,
    run_id: str,
    include_base: bool,
    dry_run: bool,
    adopt_node: str | None,
    approve: Callable[[SyncCascade], bool] | None,
    remote_writers: RemoteWriterProbe,
    worktree_root: Path,
    persistence_factory: Callable[[Path], SyncPersistence],
    reconstruct: Callable[[Path, str], TrainStatus],
    pr_facts: _PrFactsRead,
    stack_read: _StackRead,
    fetch: Callable[[Path, list[str]], None],
    remote_head: Callable[[Path, str], str | None],
    local_head: Callable[[Path, str], str | None],
    is_ancestor: Callable[[Path, str, str], bool],
    push_urls: Callable[[Path], list[str]],
    atomic_push_probe: Callable[[Path, str, str, str], None],
    push_atomic: Callable[[Path, list[git_mod.RefUpdate]], None],
    update_ref: Callable[[Path, str, str], None],
    delete_ref: Callable[[Path, str], None],
    list_refs: Callable[[Path, str], list[str]],
    worktree_add: Callable[[Path, Path, str], None],
    worktree_remove: Callable[[Path, Path], None],
    worktree_prune: Callable[[Path], None],
    checkout_detached: Callable[[Path, str], None],
    rebase_onto: _RebaseOnto,
    pending_read: Callable[[Path, str], continuation.PendingContinuation | None],
    manifest_write: Callable[[Path, continuation.ContinuationManifest], Path],
    manifest_clear: Callable[[Path, str], None],
    path_exists: Callable[[Path], bool],
    rebase_in_progress: Callable[[Path], bool],
    worktree_dirty: Callable[[Path], bool],
    sleep: Callable[[float], None],
    now: Callable[[], str],
) -> _Sync:
    """The shared per-invocation bundle construction (sync / continue / abort)."""
    return _Sync(
        repo_root=repo_root,
        run_id=run_id,
        include_base=include_base,
        dry_run=dry_run,
        adopt_node=adopt_node,
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
        worktree_prune=worktree_prune,
        checkout_detached=checkout_detached,
        rebase_onto=rebase_onto,
        pending_read=pending_read,
        manifest_write=manifest_write,
        manifest_clear=manifest_clear,
        path_exists=path_exists,
        rebase_in_progress=rebase_in_progress,
        worktree_dirty=worktree_dirty,
        sleep=sleep,
        now=now,
    )


@contextlib.contextmanager
def _held_operation_lock(
    lock: Callable[[Path], AbstractContextManager[None]], repo_root: Path
) -> Iterator[None]:
    """Hold the machine-local operation lock for the body; a busy lock is the typed
    ``operation_in_progress`` refusal (decision: the mutating stack operations serialize
    per machine — status never locks)."""
    try:
        with lock(repo_root):
            yield
    except oplock.OperationLockBusy as exc:
        raise SyncError(str(exc), error_type="operation_in_progress") from exc


def _synchronize(sync: _Sync, objective_id: str) -> SyncResult:
    train = sync.reconstruct(sync.repo_root, objective_id)
    if isinstance(train, NoDeliveryTrain):
        raise SyncError(
            f"objective {train.objective_id} has no delivery train ({train.reason})",
            error_type="not_stacked",
        )
    lineage = _require_lineage(train)
    refuse_structural_blockers(train)
    _gate_continuation(sync, lineage)
    fold = sync.persistence.read_journal(train.objective_id)
    if fold.unresolved:
        op = fold.unresolved[0]
        record = op.prepared.record
        resumable = op.kind in (OperationKind.SYNC, OperationKind.ADOPT)
        if sync.dry_run:
            # A dry run never resumes — the kind-aware message names what a real sync (or
            # recover) would do with the unresolved operation.
            hint = (
                "a real sync would resume it (roll forward, or abandon-with-proof + recompute)"
                if resumable
                else "conclude it via `perk objective stack recover` or the owning command"
            )
            raise SyncError(
                f"operation {op.operation_id} ({op.kind.value}) is unresolved on lineage "
                f"{fold.delivery_lineage} — {hint}",
                error_type="unresolved_operation",
            )
        if resumable and isinstance(record, PreparedRecord):
            return _resume(sync, train, record)
        raise SyncError(
            f"operation {op.operation_id} ({op.kind.value}) is unresolved on lineage "
            f"{fold.delivery_lineage} — conclude it via `perk objective stack recover` or "
            "the owning command before synchronizing",
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
    if not continuation.is_safe_lineage(train.delivery_lineage):
        # The lineage is stored objective metadata (an arbitrary string at the trust
        # boundary) AND names filesystem residue (the continuation manifest) — a hostile
        # value must never reach a path derivation.
        raise SyncError(
            f"objective {train.objective_id} carries a malformed delivery_lineage "
            f"{train.delivery_lineage!r} (not a path-safe token) — repair the objective "
            "metadata before synchronizing",
            error_type="invalid_input",
        )
    return train.delivery_lineage


# The reconstruction blocker codes that impeach the train's IDENTITY/TOPOLOGY authority — a
# claimed layer owned by a foreign objective, a broken plan join, a corrupt journal fold.
# Sync refuses these before any candidate work: its own preflight re-observes only the
# OPERATIONAL axes (remote/PR/membership drift, writers), so without this gate a structurally
# mis-linked plan could pass the live checks and have step 14 write checkpoints into it.
# (`missing_lineage` is deliberately absent: a lineage-less train is already refused by
# `_require_lineage` as `not_stacked` before this gate can fire.)
_STRUCTURAL_BLOCKER_CODES = frozenset(
    {
        "missing_plan",
        "duplicate_plan_link",
        "wrong_owner",
        "node_link_mismatch",
        "wrong_lineage",
        "lineage_checkpoint_conflict",
        "malformed_plan_header",
        "predecessor_mismatch",
        "journal_corruption",
    }
)


def refuse_structural_blockers(train: DeliveryTrain) -> None:
    """Fail closed on identity/topology blockers before ANY route (fresh or resume) — the
    operational drift blockers (checkpoint/PR/stack axes) deliberately pass through: sync's
    own preflight re-observes those fresh and refuses with the specific typed error."""
    hits = [f for f in train.blockers if f.code in _STRUCTURAL_BLOCKER_CODES]
    if hits:
        detail = "; ".join(f"[{f.code}] {f.message}" for f in hits)
        raise SyncError(
            "the reconstructed train carries structural identity/topology blockers — "
            f"refusing to mutate: {detail} — inspect `perk objective stack status` and "
            "repair before synchronizing",
            error_type="claimed_prefix_malformed",
        )


def _gate_continuation(sync: _Sync, lineage: str) -> None:
    """The fail-closed conflict gate: ANY manifest for this lineage — parseable or not —
    refuses a fresh cascade over retained residue (the remedies are ``sync --continue`` /
    ``sync --abort``)."""
    pending = sync.pending_read(sync.repo_root, lineage)
    if pending is None:
        return
    if pending.manifest is None:
        raise SyncError(
            f"a sync continuation manifest exists for this lineage at {pending.path} but "
            "could not be parsed — refusing a fresh cascade over retained conflict residue; "
            "discard it with `perk objective stack sync --abort`",
            error_type="sync_conflict_pending",
        )
    raise SyncError(
        f"operation {pending.manifest.operation_id} stopped mid-conflict on node "
        f"{pending.manifest.conflict_node_id}: the conflicted worktree is retained at "
        f"{pending.manifest.worktree_path} under the manifest {pending.path} — resolve the "
        "conflict there and run `perk objective stack sync --continue`, or discard the "
        "retained state with `perk objective stack sync --abort`",
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
    """Sync's operation universe (§8.49): the maximal contiguous bottom run of layers carrying
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
    adopted_heads: Mapping[str, str] | None = None,
) -> None:
    """The lease-input observation shared by the step-5 preflight and the step-10
    post-approval re-observation: every claimed remote head at its checkpoint, every claimed
    PR OPEN onto its expected base at its checkpoint head, and (≥ 2 PRs) exact native
    membership. ``adopted_heads`` overrides the expected head per branch (the ``--adopt``
    exception: the adopted layer's remote head is EXPECTED to differ from its checkpoint —
    its captured observed head is the lease input instead). The preflight names the specific
    drift per axis (``collapse=None``); the re-observation collapses ANY difference to
    ``remote_drift`` (no prepared record exists yet — the remedy is always "rerun sync")."""
    overrides = adopted_heads or {}
    drifted: list[tuple[_ClaimedLayer, str, str | None]] = []
    for layer in claimed:
        expected_head = overrides.get(layer.branch, layer.published_head_sha)
        observed = sync.remote_head(sync.repo_root, layer.branch)
        if observed != expected_head:
            drifted.append((layer, expected_head, observed))
    if drifted:
        detail = "; ".join(
            f"branch {layer.branch!r} (layer {layer.node_id}) observed at "
            f"{observed or '<absent>'}, expected {expected}"
            for layer, expected, observed in drifted
        )
        raise SyncError(
            f"remote branches drifted out-of-band: {detail}{when} — an intentional "
            "out-of-band edit is adopted with `perk objective stack sync --adopt NODE`; "
            "rerun sync after reconciling",
            error_type=collapse or "remote_drift",
        )
    for index, layer in enumerate(claimed):
        expected_base = _expected_pr_base(claimed, index, train.base)
        expected_head = overrides.get(layer.branch, layer.published_head_sha)
        facts = sync.pr_facts(number=layer.pr_number, repo_root=sync.repo_root)
        if (
            facts is None
            or facts.state != "OPEN"
            or facts.base_ref != expected_base
            or facts.head_sha != expected_head
        ):
            observed_desc = (
                f"state={facts.state} base={facts.base_ref!r} head={facts.head_sha}"
                if facts is not None
                else "absent"
            )
            raise SyncError(
                f"PR #{layer.pr_number} (layer {layer.node_id}) observed as {observed_desc}, "
                f"expected OPEN onto {expected_base!r} at {expected_head}{when}",
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


def _preflight(
    sync: _Sync,
    train: DeliveryTrain,
    claimed: Sequence[_ClaimedLayer],
    *,
    adopted_heads: Mapping[str, str] | None = None,
) -> None:
    """Step 5: every refusal before any candidate work. Remote/PR/membership drift (the
    specific typed refusals), then the writer axes — a DIRTY checked-out worktree refuses; a
    clean ACTIVE one does not (the normal state of the just-amended layer; sync never touches
    local worktrees); the remote-writer probe fails closed."""
    _check_claimed_world(sync, train, claimed, collapse=None, when="", adopted_heads=adopted_heads)
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


@dataclass(frozen=True)
class _AdoptedLayer:
    """The resolved ``--adopt`` target: its claimed-prefix index and the observed remote
    head (the adopted source — the one deliberate exception to checkpoint-exact leases)."""

    index: int
    layer: _ClaimedLayer
    remote_head: str


def _resolve_adopted(sync: _Sync, claimed: Sequence[_ClaimedLayer]) -> _AdoptedLayer:
    """Resolve ``adopt_node`` against the claimed prefix and observe the adopted head. The
    node must name a claimed layer (``invalid_input`` otherwise); an unmoved head has
    nothing to adopt and an absent remote branch cannot be adopted (``adopt_blocked``)."""
    node = sync.adopt_node
    index = next((i for i, layer in enumerate(claimed) if layer.node_id == node), None)
    if index is None:
        names = ", ".join(layer.node_id for layer in claimed) or "<none>"
        raise SyncError(
            f"--adopt {node!r} does not name a claimed (published, checkpointed) layer — "
            f"claimed node ids: {names}",
            error_type="invalid_input",
        )
    layer = claimed[index]
    observed = sync.remote_head(sync.repo_root, layer.branch)
    if observed is None:
        raise SyncError(
            f"branch {layer.branch!r} (layer {layer.node_id}) has no remote head — there is "
            "no out-of-band edit to adopt",
            error_type="adopt_blocked",
        )
    if observed == layer.published_head_sha:
        raise SyncError(
            f"branch {layer.branch!r} (layer {layer.node_id}) is exactly at its "
            f"published-head checkpoint {observed} — nothing to adopt",
            error_type="adopt_blocked",
        )
    return _AdoptedLayer(index=index, layer=layer, remote_head=observed)


def _check_capability(sync: _Sync, *, ref_branch: str, ref_sha: str) -> None:
    """Step 7: one receiving repository, then the no-op atomic dry-run probe pinned to the
    bottom affected layer's branch at its verified remote head."""
    urls = sync.push_urls(sync.repo_root)
    if len(urls) > 1:
        raise SyncError(
            f"origin has {len(urls)} push URLs ({urls}) — `--atomic` is atomic within one "
            "receiving repository; refusing to pretend distributed atomicity across mirrors",
            error_type="multiple_push_urls",
        )
    checks = probe_atomic_push_urls(
        sync.repo_root,
        ref_branch=ref_branch,
        ref_sha=ref_sha,
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


def _fresh(sync: _Sync, train: DeliveryTrain, *, abandoned_operation_id: str | None) -> SyncResult:
    """Steps 4-14 (the full fresh protocol). ``abandoned_operation_id`` is carried when this
    fresh preparation follows an all-``before`` resume abandon in the same invocation."""
    lineage = _require_lineage(train)
    claimed = _claimed_prefix(train)
    adopted: _AdoptedLayer | None = None
    if sync.adopt_node is not None:
        adopted = _resolve_adopted(sync, claimed)
    if claimed:
        adopted_heads = {adopted.layer.branch: adopted.remote_head} if adopted is not None else None
        _preflight(sync, train, claimed, adopted_heads=adopted_heads)
    if adopted is not None and not sync.is_ancestor(
        sync.repo_root, adopted.layer.parent_checkpoint_sha, adopted.remote_head
    ):
        # The adopted head must still contain the layer's stored parent edge — an
        # out-of-band edit that rewrote ancestry cannot be transplanted onto the train.
        raise SyncError(
            f"the observed remote head {adopted.remote_head} of branch "
            f"{adopted.layer.branch!r} (layer {adopted.layer.node_id}) does not contain the "
            f"stored parent edge {adopted.layer.parent_checkpoint_sha} — the remote edit "
            "rewrote the layer's ancestry; repair the branch before adopting",
            error_type="adopt_blocked",
        )

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
    if adopted is not None:
        if changed[adopted.index]:
            raise SyncError(
                f"layer {adopted.layer.node_id} ({adopted.layer.branch!r}) is ALSO locally "
                f"changed (local {local_heads[adopted.layer.branch]}, remote "
                f"{adopted.remote_head}) — an ambiguous source; reconcile the local branch "
                "before adopting the remote head",
                error_type="adopt_blocked",
            )
        # The adopted layer becomes a trigger whose source is the OBSERVED remote head.
        local_heads[adopted.layer.branch] = adopted.remote_head
        changed[adopted.index] = True
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
            dry_run=sync.dry_run,
        )
    # Every candidate SOURCE must contain its stored parent edge — the edge becomes the
    # rebase `upstream`, so an unchecked corrupt checkpoint would replay the wrong commit
    # range. Changed layers check their local head (the actionable stale_parent arm);
    # unchanged layers check the internal consistency of their own verified stored pair.
    # (The adopted layer rides the changed arm — its ancestry was already verified above.)
    for index, layer in enumerate(claimed):
        if changed[index]:
            head = local_heads[layer.branch]
            if not sync.is_ancestor(sync.repo_root, layer.parent_checkpoint_sha, head):
                raise SyncError(
                    f"local branch {layer.branch!r} at {head} does not contain its stored "
                    f"parent checkpoint {layer.parent_checkpoint_sha} — rebase "
                    f"{layer.branch!r} onto its parent branch and rerun sync",
                    error_type="stale_parent",
                )
        elif not sync.is_ancestor(
            sync.repo_root, layer.parent_checkpoint_sha, layer.published_head_sha
        ):
            raise SyncError(
                f"layer {layer.node_id}'s verified published head {layer.published_head_sha} "
                f"does not contain its stored parent checkpoint "
                f"{layer.parent_checkpoint_sha} — broken stored state; inspect "
                "`perk objective stack status` and repair before synchronizing",
                error_type="claimed_prefix_malformed",
            )
    affected = claimed[trigger:]

    # Each affected layer's OBSERVED before state — the exact lease. The checkpoint for
    # every layer except the adopted one, whose lease is its observed remote head.
    observed_before = {layer.branch: layer.published_head_sha for layer in affected}
    if adopted is not None:
        observed_before[adopted.layer.branch] = adopted.remote_head

    _check_capability(
        sync, ref_branch=affected[0].branch, ref_sha=observed_before[affected[0].branch]
    )

    # Steps 8-14 under the centralized cleanup guard: on EVERY exit — success, refusal,
    # decline, error, post-prepare failure — best-effort delete this operation's temp refs
    # and remove its isolated worktree (then prune the worktree-admin records). Disarmed in
    # exactly one case: the continuation manifest was durably written (the conflict arm).
    # Post-push arms never need the temp refs: an applied push holds the candidates
    # remotely; an unapplied push's resume arm abandons and recomputes fresh.
    operation_id = mint_operation_id()
    worktree = sync.worktree_root / f"sync-{operation_id}"
    ref_prefix = f"refs/perk/sync/{operation_id}/"
    disarmed = False
    try:
        result = _execute(
            sync,
            train,
            claimed,
            affected,
            local_heads=local_heads,
            changed=changed[trigger:],
            base_after=base_after,
            observed_before=observed_before,
            adopted=adopted,
            operation_id=operation_id,
            abandoned_operation_id=abandoned_operation_id,
            worktree=worktree,
            ref_prefix=ref_prefix,
            lineage=lineage,
        )
    except _ConflictRetained as stop:
        disarmed = True
        raise stop.error from None
    except _DryRunStop as stop:
        # The dry-run preview stops at the approval boundary; the guard's cleanup runs
        # eagerly here so a cleanup failure can surface as a loud result note (the honest
        # bound of "side-effect-free" — leftover residue is ordinary orphan-sweep territory).
        disarmed = True
        notes = _cleanup(sync, ref_prefix, worktree)
        return replace(stop.result, notes=tuple(notes))
    else:
        # Success paths (synced/declined): clean eagerly so a cleanup failure surfaces as a
        # loud result note instead of vanishing in the guard.
        disarmed = True
        notes = _cleanup(sync, ref_prefix, worktree)
        return replace(result, notes=result.notes + tuple(notes))
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
    observed_before: Mapping[str, str],
    adopted: _AdoptedLayer | None,
    operation_id: str,
    abandoned_operation_id: str | None,
    worktree: Path,
    ref_prefix: str,
    lineage: str,
) -> SyncResult:
    """Steps 8-14 straight-line (the caller owns the cleanup guard): candidates → approval →
    post-approval re-observation → prepared record → one atomic push → verification →
    checkpoints bottom→top → completed. A dry run stops at the approval boundary (raises
    :class:`_DryRunStop` so the caller can clean with notes)."""
    candidates = _calculate_candidates(
        sync,
        affected,
        local_heads=local_heads,
        changed=changed,
        base_after=base_after,
        observed_before=observed_before,
        operation_id=operation_id,
        worktree=worktree,
        ref_prefix=ref_prefix,
        objective_id=train.objective_id,
        lineage=lineage,
    )

    layers = tuple(
        SyncedLayer(
            node_id=layer.node_id,
            plan_id=layer.plan_id,
            branch=layer.branch,
            pr_number=layer.pr_number,
            before_sha=observed_before[layer.branch],
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

    # The dry-run boundary: everything through candidate calculation ran; nothing effectful
    # follows — no approval, no re-observation, no journal record, no push, no checkpoints.
    if sync.dry_run:
        raise _DryRunStop(
            SyncResult(
                objective_id=train.objective_id,
                objective_url=train.objective_url,
                redirected_from=train.redirected_from,
                operation_id=None,
                abandoned_operation_id=abandoned_operation_id,
                no_op=False,
                declined=False,
                resumed=False,
                base_cascaded=False,
                base_advanced=_base_advanced(train),
                affected=layers,
                dry_run=True,
                adopted_node=sync.adopt_node,
            )
        )

    # Step 9: the approval gate. Declined → the guard cleans; nothing was journaled.
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
    adopted_heads = {adopted.layer.branch: adopted.remote_head} if adopted is not None else None
    _reobserve(sync, train, claimed, base_after=base_after, adopted_heads=adopted_heads)

    # Step 11: the prepared record, journal-first (the §8.43 read-back discipline).
    new_parents = _new_parent_edges(affected, candidates, base_after=base_after)
    adopted_payload = (
        {
            "node_id": adopted.layer.node_id,
            "plan_id": adopted.layer.plan_id,
            "remote_head": adopted.remote_head,
        }
        if adopted is not None
        else None
    )
    record = PreparedRecord(
        operation_id=operation_id,
        operation_kind=OperationKind.ADOPT if adopted is not None else OperationKind.SYNC,
        delivery_lineage=lineage,
        objective_id=train.objective_id,
        run_id=sync.run_id,
        created=sync.now(),
        affected_plans=tuple(layer.plan_id for layer in affected),
        before=_before_payload(
            sync, train, claimed, affected, base_after=base_after, observed_before=observed_before
        ),
        after=_after_payload(
            train,
            claimed,
            affected,
            candidates,
            base_after=base_after,
            adopted=adopted_payload,
        ),
    )
    try:
        sync.persistence.append_prepared(train.objective_id, record)
    except UnresolvedOperationError as exc:
        raise SyncError(str(exc), error_type="unresolved_operation") from exc

    # Step 12: ONE atomic push, every affected ref under its exact lease (no-op refs —
    # candidate == observed before — are excluded: git's send-pack omits up-to-date refs, so
    # an included no-op update could never carry a lease; a top-layer adoption with no lower
    # trigger therefore pushes nothing).
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
        adopted_node=sync.adopt_node,
    )


def _base_advanced(train: DeliveryTrain) -> bool:
    return any(finding.code == "base_advanced" for finding in train.findings)


class _ConflictRetained(Exception):
    """Internal control flow: the conflict arm retained its residue (manifest written) —
    the cleanup guard must disarm before the typed ``rebase_conflict`` propagates."""

    def __init__(self, error: SyncError) -> None:
        super().__init__(str(error))
        self.error = error


class _DryRunStop(Exception):
    """Internal control flow: the dry-run preview stopped at the approval boundary — the
    caller cleans the residue (collecting notes) and returns the carried result."""

    def __init__(self, result: SyncResult) -> None:
        super().__init__("dry run stopped at the approval boundary")
        self.result = result


class _CleanupSeams(Protocol):
    """The small residue-removal seam shared by sync's guard and explicit abort."""

    repo_root: Path
    list_refs: Callable[[Path, str], list[str]]
    delete_ref: Callable[[Path, str], None]
    worktree_remove: Callable[[Path, Path], None]
    worktree_prune: Callable[[Path], None]


def _cleanup(sync: _CleanupSeams, ref_prefix: str, worktree: Path) -> list[str]:
    """Best-effort residue removal (never raises): every temp ref under this operation's
    namespace, then the isolated worktree, then one worktree-admin prune (the rmtree
    fallback of ``worktree_remove`` leaves a stale admin entry the prune clears). EVERY
    failure — the ref listing, each individual ref, the worktree, the prune — becomes a
    human-facing note; the success paths thread the notes onto ``SyncResult.notes``
    (refusal/error exits clean silently — leftover residue is orphan-sweep territory
    either way)."""
    notes: list[str] = []
    refs: list[str] = []
    try:
        refs = sync.list_refs(sync.repo_root, ref_prefix)
    except (git_mod.GitError, OSError) as exc:
        notes.append(f"could not list the temp refs under {ref_prefix} ({exc})")
    for ref in refs:
        try:
            sync.delete_ref(sync.repo_root, ref)
        except (git_mod.GitError, OSError) as exc:
            notes.append(f"could not delete the temp ref {ref} ({exc})")
    # No existence pre-check: the remove seam itself tolerates an absent worktree (its
    # error is suppressed), which keeps the guard observable through the injected seam.
    try:
        sync.worktree_remove(sync.repo_root, worktree)
    except (git_mod.GitError, OSError) as exc:
        notes.append(f"could not remove the isolated worktree {worktree} ({exc})")
    try:
        sync.worktree_prune(sync.repo_root)
    except (git_mod.GitError, OSError) as exc:
        notes.append(f"could not prune the worktree records ({exc})")
    if notes:
        notes.append("leftover residue is swept by `perk objective stack recover`")
    return notes


# ----------------------------------------------------------------- candidate calculation


def _calculate_candidates(
    sync: _Sync,
    affected: Sequence[_ClaimedLayer],
    *,
    local_heads: Mapping[str, str],
    changed: Sequence[bool],
    base_after: str | None,
    observed_before: Mapping[str, str],
    operation_id: str,
    worktree: Path,
    ref_prefix: str,
    objective_id: str,
    lineage: str,
) -> list[str]:
    """Step 8: bottom-up candidate transplants in ONE isolated worktree.

    Per layer: source = the local head when locally changed (the observed remote head for
    an adopted layer), else the verified published head; new parent edge = the observed
    base head (bottom, cascading) / the unchanged stored edge (bottom, lowest-changed
    trigger) / the predecessor's fresh candidate; edges equal → candidate = source (fast
    path, no rebase). Each candidate lands in a disposable temp ref. A rebase conflict
    writes the continuation manifest, disarms the guard (via :class:`_ConflictRetained`),
    and raises ``rebase_conflict`` — no remote ref and no journal record exists at that
    point. A DRY-RUN conflict retains nothing: no manifest is written, the guard stays
    armed, and the typed error notes this was a preview.
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
                if sync.dry_run:
                    # Strictly side-effect-free: NO manifest write, the guard stays armed
                    # (the conflicted worktree and temp refs are cleaned like any refusal).
                    raise SyncError(
                        f"the candidate rebase for layer {layer.node_id} "
                        f"({layer.branch!r} onto {new_parent}) hit a conflict — this was a "
                        "dry-run preview, so nothing was retained; a real sync would retain "
                        "the conflicted worktree here under a continuation manifest",
                        error_type="rebase_conflict",
                    )
                manifest_layers.append(
                    continuation.ContinuationLayer(
                        node_id=layer.node_id,
                        plan_id=layer.plan_id,
                        branch=layer.branch,
                        before_sha=observed_before[layer.branch],
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
                        before_sha=observed_before[rest.branch],
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
                    adopted_node=sync.adopt_node,
                )
                try:
                    path = sync.manifest_write(sync.repo_root, manifest)
                except OSError as write_exc:
                    # The conflict happened AND retention failed (permissions/disk): the
                    # guard stays armed — residue is cleaned — and the failure stays inside
                    # the typed boundary. Nothing was pushed or journaled.
                    raise SyncError(
                        f"the candidate rebase for layer {layer.node_id} hit a conflict AND "
                        f"the continuation manifest could not be written ({write_exc}) — the "
                        "conflicted state was NOT retained (residue cleaned); no remote ref "
                        "and no journal record was created. Fix the filesystem issue and "
                        "rerun sync.",
                        error_type="rebase_conflict",
                    ) from write_exc
                raise _ConflictRetained(
                    SyncError(
                        f"the candidate rebase for layer {layer.node_id} "
                        f"({layer.branch!r} onto {new_parent}) hit a conflict — the "
                        f"conflicted worktree is retained at {worktree} under the "
                        f"continuation manifest {path}; no remote ref and no journal record "
                        "was created. Resolve the conflict in the retained worktree "
                        "(`git rebase --continue`) and run "
                        "`perk objective stack sync --continue`, or discard it with "
                        "`perk objective stack sync --abort`.",
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
                before_sha=observed_before[layer.branch],
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
    *,
    base_after: str | None,
    adopted_heads: Mapping[str, str] | None = None,
) -> None:
    """Step 10: re-read every lease input after the (arbitrarily long) approval pause — the
    claimed world plus the base head when cascading. Any difference from the captured
    before-set is ``remote_drift`` with no prepared record written (rerun sync)."""
    when = " (re-observed after approval)"
    _check_claimed_world(
        sync, train, claimed, collapse="remote_drift", when=when, adopted_heads=adopted_heads
    )
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
    observed_before: Mapping[str, str],
) -> dict[str, object]:
    """The sync-kind ``before`` shape (§8.49): the exact observed lease values — base present
    iff cascading, the affected branches at their observed heads (the checkpoint for every
    layer except an adopted one), their PRs, and the claimed stack membership (``None``
    below two PRs)."""
    offset = len(claimed) - len(affected)
    prs = [
        {
            "number": layer.pr_number,
            "head_sha": observed_before[layer.branch],
            "base": _expected_pr_base(claimed, offset + pos, train.base),
        }
        for pos, layer in enumerate(affected)
    ]
    stack_payload: dict[str, object] | None = None
    if len(claimed) >= 2:
        stack_payload = {"members": [layer.pr_number for layer in claimed]}
    return {
        "base": {"branch": train.base, "sha": base_after} if base_after is not None else None,
        "branches": [
            {"ref": layer.branch, "sha": observed_before[layer.branch]} for layer in affected
        ],
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
    adopted: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """The sync-kind ``after`` shape (§8.49): the candidates. PR bases are unchanged by
    construction — sync moves heads, never branch names. The ADOPT kind additionally
    carries the kind-owned ``adopted`` mapping (``{node_id, plan_id, remote_head}``) — the
    strict journal envelope is untouched (kind data lives inside ``after``)."""
    offset = len(claimed) - len(affected)
    payload: dict[str, object] = {
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
    if adopted is not None:
        payload["adopted"] = dict(adopted)
    return payload


# ----------------------------------------------------------------- push + verification


def _push(
    sync: _Sync,
    objective_id: str,
    operation_id: str,
    layers: Sequence[SyncedLayer],
) -> None:
    """Step 12: one atomic exact-leased multi-ref push. Refs whose candidate EQUALS their
    observed before state are excluded (decision 16): git's send-pack omits up-to-date
    refs, so including one would pretend a lease that cannot exist — the residual race on
    an excluded (typically adopted) ref is detected by step-13 verification, the same
    posture as the unleased objective-base head in a ``--base`` cascade. An empty push set
    (a checkpoint-only top-layer adoption) skips the push entirely. A rejection is
    classified by refetching every affected head: all-at-before confirmed →
    abandon-with-proof + ``push_rejected`` (retry = rerun sync); an unreadable refetch →
    ``postcondition_unverified`` (unresolved); a mixed observation → ``sync_drift``
    (unresolved, fail closed). Individual refs are NEVER retried."""
    updates = [
        git_mod.RefUpdate(
            branch=layer.branch, expected_remote_sha=layer.before_sha, new_sha=layer.after_sha
        )
        for layer in layers
        if layer.after_sha != layer.before_sha
    ]
    if not updates:
        return
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
    sync: SyncRecordSeams,
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
    sync: SyncRecordSeams, layer: _ClaimedLayer, *, expected_base: str, candidate: str
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
    sync: SyncRecordSeams,
    train: DeliveryTrain,
    layers: Sequence[SyncedLayer],
    *,
    new_parents: Sequence[str],
    operation_id: str,
    abandoned_operation_id: str | None,
    resumed: bool,
    base_cascaded: bool,
    adopted_node: str | None = None,
    continued: bool = False,
    notes: tuple[str, ...] = (),
) -> SyncResult:
    """Step 14 (publish's step-12 ordering): checkpoints bottom→top, then the ``completed``
    outcome. A crash between the checkpoint writes and completion reconstructs as
    roll-forward — merge-writes + idempotent byte-identical appends."""
    _persist_completion(
        sync, train.objective_id, layers, new_parents=new_parents, operation_id=operation_id
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
        adopted_node=adopted_node,
        continued=continued,
        notes=notes,
    )


def _persist_completion(
    sync: SyncRecordSeams,
    objective_id: str,
    layers: Sequence[SyncedLayer],
    *,
    new_parents: Sequence[str],
    operation_id: str,
) -> None:
    """The step-14 effects: per-layer checkpoints bottom→top, then the ``completed``
    outcome (shared by the fresh tail, the resume roll-forward, and recover's)."""
    for pos, layer in enumerate(layers):
        sync.persistence.write_checkpoints(
            layer.plan_id,
            parent_checkpoint_sha=new_parents[pos],
            published_head_sha=layer.after_sha,
        )
    sync.persistence.append_outcome(
        objective_id,
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


# --------------------------------------------- the SYNC/ADOPT record-recovery core (§8.51)
# Shared by sync's resume path and the recover operation: strict payload decode,
# fresh-authority corroboration, ref observation, and the record-driven roll-forward tail.


@dataclass(frozen=True)
class _RecordedLayer:
    """One affected layer as the prepared record captured it (parallel arrays decoded)."""

    plan_id: str
    branch: str
    before_sha: str
    after_sha: str
    pr_number: int
    pr_base: str


@dataclass(frozen=True)
class SyncRecordFacts:
    """The validated, fresh-authority-corroborated view of one unresolved SYNC/ADOPT
    prepared record — everything the observation/conclusion steps need."""

    recorded: tuple[_RecordedLayer, ...]
    base_parent: str | None
    recorded_members: tuple[int, ...] | None
    matched: tuple[_ClaimedLayer, ...]
    adopted_node: str | None


def validate_sync_record(train: DeliveryTrain, record: PreparedRecord) -> SyncRecordFacts:
    """Strict decode + fresh-authority corroboration of a SYNC/ADOPT prepared record
    (lineage, parallel-array shape, base/stack payload consistency, the ADOPT-kind
    ``after.adopted`` field, contiguous plan slice, branches, PR numbers/bases re-derived
    from the fresh train, full checkpoint pairs). Raises :class:`SyncError`
    (``sync_drift``) on ANY disagreement — a record the operation cannot account for is
    never concluded."""
    lineage = _require_lineage(train)
    if record.delivery_lineage != lineage:
        raise _resume_drift(
            record.operation_id,
            "delivery_lineage",
            expected=record.delivery_lineage,
            derived=lineage,
        )
    recorded = _decode_record(record)
    adopted_node = _decode_adopted(record)
    base_parent = _decode_base(record)
    recorded_members = _recorded_members(record)
    matched = _corroborate_record(train, record, recorded)
    _corroborate_membership(record, recorded_members, matched)
    return SyncRecordFacts(
        recorded=tuple(recorded),
        base_parent=base_parent,
        recorded_members=tuple(recorded_members) if recorded_members is not None else None,
        matched=tuple(matched),
        adopted_node=adopted_node,
    )


def observe_sync_record(seams: SyncRecordSeams, facts: SyncRecordFacts) -> tuple[str | None, ...]:
    """The recorded refs' fresh remote heads (the classification observation)."""
    return tuple(seams.remote_head(seams.repo_root, entry.branch) for entry in facts.recorded)


def classify_sync_observation(
    facts: SyncRecordFacts, observed: Sequence[str | None]
) -> str:  # all_after | all_before | mixed
    """Classify an observation against the record's before/after sets — fail closed: only
    the exact all-``after`` / all-``before`` sets classify; anything else is ``mixed``."""
    if all(sha == entry.after_sha for sha, entry in zip(observed, facts.recorded, strict=True)):
        return "all_after"
    if all(sha == entry.before_sha for sha, entry in zip(observed, facts.recorded, strict=True)):
        return "all_before"
    return "mixed"


def roll_forward_sync_record(
    seams: SyncRecordSeams,
    train: DeliveryTrain,
    record: PreparedRecord,
    facts: SyncRecordFacts,
) -> tuple[SyncedLayer, ...]:
    """The record-driven roll-forward tail (steps 13-14 under the SAME operation): verify
    postconditions against the recorded expectations, write checkpoints bottom→top with the
    record-derived parent edges, append the ``completed`` outcome."""
    candidates = [entry.after_sha for entry in facts.recorded]
    new_parents = _recorded_parent_edges(facts.base_parent, facts.recorded, facts.matched)
    _verify_postconditions(
        seams,
        train,
        facts.matched,
        facts.matched,
        candidates,
        expected_bases=[entry.pr_base for entry in facts.recorded],
        expected_members=list(facts.recorded_members)
        if facts.recorded_members is not None
        else None,
    )
    layers = tuple(
        SyncedLayer(
            node_id=facts.matched[pos].node_id,
            plan_id=facts.matched[pos].plan_id,
            branch=entry.branch,
            pr_number=entry.pr_number,
            before_sha=entry.before_sha,
            after_sha=entry.after_sha,
        )
        for pos, entry in enumerate(facts.recorded)
    )
    _persist_completion(
        seams,
        train.objective_id,
        layers,
        new_parents=new_parents,
        operation_id=record.operation_id,
    )
    return layers


def abandon_sync_record(
    seams: SyncRecordSeams,
    objective_id: str,
    record: PreparedRecord,
    facts: SyncRecordFacts,
    observed: Sequence[str | None],
) -> None:
    """Append the ``abandoned`` outcome with the all-``before`` observation as proof."""
    seams.persistence.append_outcome(
        objective_id,
        OutcomeRecord(
            operation_id=record.operation_id,
            role=EventRole.ABANDONED,
            created=seams.now(),
            observed={
                "branches": [
                    {"ref": entry.branch, "sha": sha}
                    for sha, entry in zip(observed, facts.recorded, strict=True)
                ]
            },
        ),
    )


# ----------------------------------------------------------------- the resume path


def _resume(sync: _Sync, train: DeliveryTrain, record: PreparedRecord) -> SyncResult:
    """An unresolved SYNC/ADOPT on this lineage: re-derive the expected states from the
    prepared record, corroborate the fresh reconstruction, then observe every recorded ref —
    all-at-``after`` → roll forward (steps 13-14 under the same operation); all-at-``before``
    → abandon-with-proof + a FRESH preparation in the same invocation, carrying the
    invocation's own flags (a deliberate deviation from publish's same-operation retry:
    sync's candidates live in disposable temp refs that do not survive a crash, and a
    recomputed rebase yields different SHAs); mixed/unrelated → ``sync_drift``, unresolved,
    fail closed."""
    facts = validate_sync_record(train, record)
    observed = observe_sync_record(sync, facts)
    classification = classify_sync_observation(facts, observed)
    if classification == "all_after":
        layers = roll_forward_sync_record(sync, train, record, facts)
        return SyncResult(
            objective_id=train.objective_id,
            objective_url=train.objective_url,
            redirected_from=train.redirected_from,
            operation_id=record.operation_id,
            abandoned_operation_id=None,
            no_op=False,
            declined=False,
            resumed=True,
            base_cascaded=facts.base_parent is not None,
            base_advanced=_base_advanced(train),
            affected=layers,
            adopted_node=facts.adopted_node,
        )
    if classification == "all_before":
        abandon_sync_record(sync, train.objective_id, record, facts, observed)
        return _fresh(sync, train, abandoned_operation_id=record.operation_id)
    raise SyncError(
        f"operation {record.operation_id}'s recorded refs verified in a MIXED state "
        f"({[(e.branch, sha) for sha, e in zip(observed, facts.recorded, strict=True)]}), "
        "matching neither the "
        "prepared before nor after set — refusing to guess; the operation stays unresolved",
        error_type="sync_drift",
    )


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
    train: DeliveryTrain,
    record: PreparedRecord,
    recorded: Sequence[_RecordedLayer],
) -> list[_ClaimedLayer]:
    """The fresh reconstruction must still agree with the record — each recorded plan maps to
    a train layer whose branch and PR number match, the affected plans remain CONTIGUOUS in
    delivery order, and each recorded PR base still equals the base re-derived from the fresh
    train's topology (the predecessor layer's branch; the objective base at the bottom).
    Authority drift while the operation was unresolved — a retargeted base, a reordered
    roadmap — is ``sync_drift``, never silently rolled forward under the stale record."""
    matched: list[_ClaimedLayer] = []
    by_plan = {
        layer.plan_id: (index, layer)
        for index, layer in enumerate(train.layers)
        if layer.plan_id is not None
    }
    previous_index: int | None = None
    for entry in recorded:
        found = by_plan.get(entry.plan_id)
        if found is None:
            raise _resume_drift(
                record.operation_id, "affected plan", expected=entry.plan_id, derived="absent"
            )
        index, layer = found
        if previous_index is not None and index != previous_index + 1:
            raise _resume_drift(
                record.operation_id,
                "affected order",
                expected="a contiguous bottom→top run in delivery order",
                derived=f"plan #{entry.plan_id} at layer index {index} "
                f"(predecessor at {previous_index})",
            )
        previous_index = index
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
        derived_base = train.layers[index - 1].branch if index >= 1 else train.base
        if derived_base != entry.pr_base:
            raise _resume_drift(
                record.operation_id,
                f"PR base for plan #{entry.plan_id}",
                expected=entry.pr_base,
                derived=derived_base,
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
    base_parent: str | None,
    recorded: Sequence[_RecordedLayer],
    matched: Sequence[_ClaimedLayer],
) -> list[str]:
    """The roll-forward parent edges: the bottom affected layer's is the VALIDATED recorded
    ``base_parent`` when the operation cascaded the base (else its stored, unchanged parent
    edge — idempotent under a partial step-14 crash because a non-cascading bottom never
    changes it); every higher layer's is the predecessor's candidate."""
    edges: list[str] = []
    for pos in range(len(recorded)):
        if pos >= 1:
            edges.append(recorded[pos - 1].after_sha)
        elif base_parent is not None:
            edges.append(base_parent)
        else:
            edges.append(matched[pos].parent_checkpoint_sha)
    return edges


def _decode_adopted(record: PreparedRecord) -> str | None:
    """The ADOPT-kind ``after.adopted`` mapping, decoded STRICTLY: an ADOPT record must carry
    ``{node_id, plan_id, remote_head}`` strings (else ``sync_drift``); a SYNC record's
    ``after`` is not inspected for it. Returns the adopted node id (``None`` for SYNC)."""
    if record.operation_kind is not OperationKind.ADOPT:
        return None
    adopted = _opt_mapping(record.after.get("adopted"))
    node_id = adopted.get("node_id") if adopted is not None else None
    plan_id = adopted.get("plan_id") if adopted is not None else None
    remote_head = adopted.get("remote_head") if adopted is not None else None
    if (
        not isinstance(node_id, str)
        or not isinstance(plan_id, str)
        or not isinstance(remote_head, str)
    ):
        raise _resume_drift(
            record.operation_id,
            "adopted payload",
            expected='an ADOPT record with after.adopted = {"node_id", "plan_id", "remote_head"}',
            derived=record.after.get("adopted"),
        )
    return node_id


def _decode_base(record: PreparedRecord) -> str | None:
    """The validated base-cascade fields — ``before.base`` and ``after.base_parent`` must be
    MUTUALLY consistent: both absent (no base cascade), or a ``{branch, sha}`` capture with
    ``base_parent == sha``. Sync payloads are opaque at the journal-envelope layer, so any
    other shape fails closed (``sync_drift``) — an unvalidated ``base_parent`` would
    otherwise be persisted verbatim as the bottom layer's parent checkpoint."""
    base = record.before.get("base")
    base_parent = record.after.get("base_parent")
    if base is None:
        if base_parent is not None:
            raise _resume_drift(
                record.operation_id,
                "base payload",
                expected="base_parent null without a captured base",
                derived=base_parent,
            )
        return None
    mapping = _opt_mapping(base)
    branch = mapping.get("branch") if mapping is not None else None
    sha = mapping.get("sha") if mapping is not None else None
    if not isinstance(branch, str) or not isinstance(sha, str) or base_parent != sha:
        raise _resume_drift(
            record.operation_id,
            "base payload",
            expected="a {branch, sha} capture with base_parent == sha",
            derived={"base": base, "base_parent": base_parent},
        )
    return sha


def _recorded_members(record: PreparedRecord) -> list[int] | None:
    """The recorded claimed-stack membership, decoded STRICTLY: ``None`` only when the record
    captured no stack (``stack: null`` — below two claimed PRs at prepare time); a present
    stack must be exactly ``{"members": [int, …]}``. Anything else is ``sync_drift`` — a
    silently-degraded membership would skip the native-stack verification entirely."""
    stack = record.before.get("stack")
    if stack is None:
        return None
    mapping = _opt_mapping(stack)
    members = mapping.get("members") if mapping is not None else None
    if (
        mapping is None
        or not isinstance(members, list)
        or not members
        or not all(isinstance(member, int) for member in members)
    ):
        raise _resume_drift(
            record.operation_id,
            "stack payload",
            expected='null or {"members": [int, …]}',
            derived=stack,
        )
    return [member for member in members if isinstance(member, int)]


def _corroborate_membership(
    record: PreparedRecord,
    recorded_members: list[int] | None,
    matched: Sequence[_ClaimedLayer],
) -> None:
    """The recorded membership must still account for the affected set: a multi-layer cascade
    without a recorded stack is impossible (claimed ≥ affected ≥ 2 records members), and a
    recorded membership must END with exactly the affected PR run bottom→top — otherwise the
    roll-forward would verify a stack unrelated to what it is about to checkpoint."""
    if recorded_members is None:
        if len(matched) >= 2:
            raise _resume_drift(
                record.operation_id,
                "stack payload",
                expected="a recorded membership for a multi-layer cascade",
                derived=None,
            )
        return
    suffix = [layer.pr_number for layer in matched]
    if recorded_members[-len(suffix) :] != suffix:
        raise _resume_drift(
            record.operation_id,
            "recorded membership",
            expected=f"a members list ending with the affected PRs {suffix}",
            derived=recorded_members,
        )


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


# ----------------------------------------------------------------- continue (§8.49)


def _rewrite_manifest_or_refuse(sync: _Sync, manifest: continuation.ContinuationManifest) -> Path:
    """An in-continue manifest progress rewrite, kept inside the typed boundary: a write
    failure (permissions/disk) raises ``GitError`` — the CLI maps it to ``git_error`` —
    while the PREVIOUS durable snapshot stays retained and valid (progress recomputes from
    it on the next ``--continue``)."""
    try:
        return sync.manifest_write(sync.repo_root, manifest)
    except OSError as exc:
        raise git_mod.GitError(
            f"could not rewrite the continuation manifest ({exc}) — the previous snapshot "
            "stays retained and valid; fix the filesystem issue and rerun "
            "`perk objective stack sync --continue`"
        ) from exc


def _stale(message: str) -> SyncError:
    return SyncError(
        f"{message} — the retained continuation no longer matches the fresh authorities; "
        "discard it with `perk objective stack sync --abort` and rerun sync",
        error_type="continuation_stale",
    )


def _validated_targets_or_refuse(
    manifest: continuation.ContinuationManifest, worktree_root: Path
) -> continuation.ValidatedTargets:
    """Decision 14: manifest data is never deletion authority by itself — a containment
    violation is the non-destructive typed refusal ``continuation_invalid``."""
    try:
        return continuation.validated_targets(manifest, worktree_root)
    except continuation.ContainmentViolation as exc:
        raise SyncError(
            f"the continuation manifest failed containment validation ({exc}) — nothing was "
            "deleted; discard the manifest with `perk objective stack sync --abort`",
            error_type="continuation_invalid",
        ) from exc


def _match_manifest_layers(
    manifest: continuation.ContinuationManifest, claimed: Sequence[_ClaimedLayer]
) -> list[_ClaimedLayer]:
    """Map the manifest's affected layers onto the FRESH claimed prefix: identity must match
    exactly and the affected set must still be the contiguous top suffix — the world the
    conflict stopped in must still be the world (else ``continuation_stale``)."""
    if not manifest.layers:
        raise _stale("the continuation manifest records no layers")
    indices: list[int] = []
    for m_layer in manifest.layers:
        index = next(
            (
                i
                for i, c_layer in enumerate(claimed)
                if c_layer.node_id == m_layer.node_id
                and c_layer.plan_id == m_layer.plan_id
                and c_layer.branch == m_layer.branch
            ),
            None,
        )
        if index is None:
            raise _stale(
                f"manifest layer {m_layer.node_id} (plan #{m_layer.plan_id}, "
                f"{m_layer.branch!r}) no longer matches a claimed layer"
            )
        indices.append(index)
    contiguous = all(b == a + 1 for a, b in itertools.pairwise(indices))
    if not contiguous or indices[-1] != len(claimed) - 1:
        raise _stale(
            f"the manifest's affected layers map to claimed indices {indices}, expected the "
            "contiguous top suffix of the claimed prefix"
        )
    return [claimed[i] for i in indices]


def _manifest_adopted_heads(manifest: continuation.ContinuationManifest) -> dict[str, str]:
    """The adopted-layer expected-head override for an ADOPT continuation ({} for plain
    sync): the adopted layer's lease is its captured observed head, never its checkpoint."""
    if manifest.adopted_node is None:
        return {}
    layer = next(
        (entry for entry in manifest.layers if entry.node_id == manifest.adopted_node), None
    )
    if layer is None:
        raise _stale(
            f"the manifest records adopted_node {manifest.adopted_node!r} but no manifest "
            "layer carries that node id"
        )
    return {layer.branch: layer.before_sha}


def continue_train_sync(
    repo_root: Path,
    *,
    objective_id: str,
    remote_writers: RemoteWriterProbe,
    worktree_root: Path,
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
    worktree_prune: Callable[[Path], None] = git_mod.worktree_prune,
    checkout_detached: Callable[[Path, str], None] = git_mod.checkout_detached,
    rebase_onto: _RebaseOnto = git_mod.rebase_onto,
    pending_read: Callable[
        [Path, str], continuation.PendingContinuation | None
    ] = continuation.pending_continuation,
    manifest_write: Callable[
        [Path, continuation.ContinuationManifest], Path
    ] = continuation.write_manifest,
    manifest_clear: Callable[[Path, str], None] = continuation.clear_manifest,
    path_exists: Callable[[Path], bool] = _default_path_exists,
    rebase_in_progress: Callable[[Path], bool] = git_mod.rebase_in_progress,
    worktree_dirty: Callable[[Path], bool] = git_mod.is_dirty,
    lock: Callable[[Path], AbstractContextManager[None]] = oplock.stack_operation_lock,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = plan.now_iso,
) -> SyncResult:
    """Resume a retained conflict stop (``sync --continue``, contracts.md §8.49).

    The retention boundary (decision 12): everything up to and including the approval gate
    is pre-journal — refusals and declines retain the manifest + worktree + temp refs; once
    the prepared record is appended (under the MANIFEST's operation id and run id) the
    manifest is retired and the journal is the sole authority. Expects the human to have
    finished the rebase (``git rebase --continue``) in the retained worktree — perk never
    drives conflict resolution.
    """
    sync = _make_sync(
        repo_root,
        run_id="",  # a continue journals under the MANIFEST's captured run identity
        include_base=False,
        dry_run=False,
        adopt_node=None,
        approve=approve,
        remote_writers=remote_writers,
        worktree_root=worktree_root,
        persistence_factory=persistence_factory,
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
        worktree_prune=worktree_prune,
        checkout_detached=checkout_detached,
        rebase_onto=rebase_onto,
        pending_read=pending_read,
        manifest_write=manifest_write,
        manifest_clear=manifest_clear,
        path_exists=path_exists,
        rebase_in_progress=rebase_in_progress,
        worktree_dirty=worktree_dirty,
        sleep=sleep,
        now=now,
    )
    with _held_operation_lock(lock, repo_root):
        return _continue(sync, objective_id)


def _continue(sync: _Sync, objective_id: str) -> SyncResult:
    """The continue protocol (steps per contracts.md §8.49): load + containment-validate the
    manifest, resolve the resume point, revalidate against fresh authority, resume candidate
    calculation with per-candidate manifest rewrites, then the approval gate and the normal
    journal-first tail under the manifest's operation identity."""
    train = sync.reconstruct(sync.repo_root, objective_id)
    if isinstance(train, NoDeliveryTrain):
        raise SyncError(
            f"objective {train.objective_id} has no delivery train ({train.reason})",
            error_type="not_stacked",
        )
    lineage = _require_lineage(train)
    refuse_structural_blockers(train)
    pending = sync.pending_read(sync.repo_root, lineage)
    if pending is None:
        raise SyncError(
            f"no continuation manifest exists for lineage {lineage} — nothing to continue",
            error_type="no_continuation",
        )
    manifest = pending.manifest
    if manifest is None:
        raise SyncError(
            f"the continuation manifest at {pending.path} could not be parsed — discard it "
            "with `perk objective stack sync --abort`",
            error_type="continuation_invalid",
        )
    # Step 2: containment validation (decision 14) — manifest data is never deletion or
    # mutation authority by itself.
    targets = _validated_targets_or_refuse(manifest, sync.worktree_root)
    if manifest.objective_id != train.objective_id or manifest.delivery_lineage != lineage:
        raise SyncError(
            f"the continuation manifest names objective {manifest.objective_id!r} / lineage "
            f"{manifest.delivery_lineage!r}, but the reconstruction derives "
            f"{train.objective_id!r} / {lineage!r} — nothing was deleted; discard the "
            "manifest with `perk objective stack sync --abort`",
            error_type="continuation_invalid",
        )

    # Step 3: resume-point resolution (decision 13) — the pending layer is the FIRST layer
    # whose candidate is null; all-non-null is the declined-after-complete state that
    # re-enters at the approval gate.
    layers_list = list(manifest.layers)
    pending_idx = next(
        (i for i, layer in enumerate(layers_list) if layer.candidate_sha is None), None
    )
    completed_upto = pending_idx if pending_idx is not None else len(layers_list)
    for layer in layers_list[:completed_upto]:
        if layer.candidate_sha is None:  # unreachable by construction; fail closed
            raise _stale(f"manifest layer {layer.node_id} records no candidate")
        if sync.local_head(sync.repo_root, layer.candidate_temp_ref) != layer.candidate_sha:
            raise _stale(
                f"temp ref {layer.candidate_temp_ref} no longer resolves to the recorded "
                f"candidate {layer.candidate_sha}"
            )
    pending_candidate: str | None = None
    if pending_idx is not None:
        if not sync.path_exists(targets.worktree):
            raise _stale(f"the retained worktree {targets.worktree} no longer exists")
        if sync.rebase_in_progress(targets.worktree):
            raise SyncError(
                f"the rebase in the retained worktree {targets.worktree} is still in "
                f"progress — finish it (`git -C {targets.worktree} rebase --continue`) and "
                "rerun `perk objective stack sync --continue`; perk never drives conflict "
                "resolution",
                error_type="rebase_in_progress",
            )
        if sync.worktree_dirty(targets.worktree):
            raise _stale(f"the rebase in {targets.worktree} finished but the worktree is dirty")
        pending_candidate = sync.local_head(targets.worktree, "HEAD")
        if pending_candidate is None:
            raise _stale(f"the retained worktree {targets.worktree} has no resolvable HEAD")
        # The resolved HEAD must be a real continuation of the recorded rebase: it must
        # contain the recorded new parent edge. A clean worktree alone proves nothing —
        # `git rebase --abort` leaves exactly a clean worktree at the ORIGINAL source, and
        # adopting that head would checkpoint a candidate that does not contain its parent.
        pending_parent = layers_list[pending_idx].new_parent_edge
        if pending_parent is None:  # unreachable: a conflict layer always records its edge
            raise _stale(
                f"manifest layer {layers_list[pending_idx].node_id} records no new parent edge"
            )
        if not sync.is_ancestor(sync.repo_root, pending_parent, pending_candidate):
            raise _stale(
                f"the resolved HEAD {pending_candidate} in {targets.worktree} does not "
                f"contain the recorded new parent {pending_parent} — the rebase was aborted "
                "or reset rather than finished"
            )

    # Step 4: full revalidation against fresh authority (no new manifest captures).
    claimed = _claimed_prefix(train)
    matched = _match_manifest_layers(manifest, claimed)
    adopted_heads = _manifest_adopted_heads(manifest)
    for m_layer, c_layer in zip(layers_list, matched, strict=True):
        expected_before = adopted_heads.get(m_layer.branch, c_layer.published_head_sha)
        if m_layer.before_sha != expected_before:
            raise _stale(
                f"manifest layer {m_layer.node_id} captured before_sha {m_layer.before_sha} "
                f"but the stored checkpoint expects {expected_before}"
            )
        if m_layer.old_parent_edge != c_layer.parent_checkpoint_sha:
            raise _stale(
                f"manifest layer {m_layer.node_id} captured old parent edge "
                f"{m_layer.old_parent_edge} but the fresh stored checkpoint pair records "
                f"{c_layer.parent_checkpoint_sha}"
            )
        observed = sync.remote_head(sync.repo_root, m_layer.branch)
        if observed != m_layer.before_sha:
            raise _stale(
                f"branch {m_layer.branch!r} observed at {observed or '<absent>'}, but the "
                f"manifest captured {m_layer.before_sha}"
            )
    if manifest.include_base and train.observed_base_head_sha != manifest.captured_base_head:
        raise _stale(
            f"the objective base {train.base!r} observed at "
            f"{train.observed_base_head_sha or '<absent>'}, but the manifest captured "
            f"{manifest.captured_base_head}"
        )
    _preflight(sync, train, claimed, adopted_heads=adopted_heads or None)
    _check_capability(sync, ref_branch=layers_list[0].branch, ref_sha=layers_list[0].before_sha)

    # Step 5: resume candidate calculation bottom-up from the pending layer, rewriting the
    # manifest after EVERY completed candidate (atomic write, same operation id) — a decline
    # then re-enters at the approval gate with every candidate durably recorded.
    if pending_idx is not None and pending_candidate is not None:
        sync.update_ref(
            sync.repo_root, layers_list[pending_idx].candidate_temp_ref, pending_candidate
        )
        layers_list[pending_idx] = replace(
            layers_list[pending_idx], candidate_sha=pending_candidate
        )
        manifest = replace(manifest, layers=tuple(layers_list))
        _rewrite_manifest_or_refuse(sync, manifest)
        for pos in range(pending_idx + 1, len(layers_list)):
            layer = layers_list[pos]
            predecessor = layers_list[pos - 1].candidate_sha
            if predecessor is None:  # unreachable by construction; fail closed
                raise _stale(f"manifest layer {layers_list[pos - 1].node_id} has no candidate")
            new_parent = predecessor
            old_parent = layer.old_parent_edge
            if new_parent == old_parent:
                candidate = layer.source_sha
            else:
                sync.checkout_detached(targets.worktree, layer.source_sha)
                outcome = sync.rebase_onto(targets.worktree, onto=new_parent, upstream=old_parent)
                if isinstance(outcome, git_mod.RebaseConflict):
                    layers_list[pos] = replace(layer, new_parent_edge=new_parent)
                    manifest = replace(
                        manifest, layers=tuple(layers_list), conflict_node_id=layer.node_id
                    )
                    try:
                        path = sync.manifest_write(sync.repo_root, manifest)
                    except OSError as write_exc:
                        # A NEW conflict was hit AND the progress rewrite failed: the
                        # previous snapshot stays durable and valid, and the worktree sits
                        # mid-rebase — finish or abort THAT rebase, fix the filesystem, and
                        # rerun; the failure stays inside the typed boundary.
                        raise SyncError(
                            f"the candidate rebase for layer {layer.node_id} hit a NEW "
                            f"conflict AND the continuation manifest could not be rewritten "
                            f"({write_exc}) — the previous snapshot stays retained; resolve "
                            f"the rebase in {targets.worktree}, fix the filesystem issue, "
                            "and rerun `perk objective stack sync --continue`",
                            error_type="rebase_conflict",
                        ) from write_exc
                    raise SyncError(
                        f"the candidate rebase for layer {layer.node_id} ({layer.branch!r} "
                        f"onto {new_parent}) hit a NEW conflict — the conflicted worktree "
                        f"stays retained at {targets.worktree} under the manifest {path} "
                        f"(same operation {manifest.operation_id}); resolve and rerun "
                        "`perk objective stack sync --continue`",
                        error_type="rebase_conflict",
                    )
                candidate = outcome.head_sha
            sync.update_ref(sync.repo_root, layer.candidate_temp_ref, candidate)
            layers_list[pos] = replace(layer, new_parent_edge=new_parent, candidate_sha=candidate)
            manifest = replace(manifest, layers=tuple(layers_list))
            _rewrite_manifest_or_refuse(sync, manifest)

    candidates: list[str] = []
    new_parents: list[str] = []
    for layer in layers_list:
        if layer.candidate_sha is None or layer.new_parent_edge is None:
            raise _stale(f"manifest layer {layer.node_id} is missing candidate/parent facts")
        candidates.append(layer.candidate_sha)
        new_parents.append(layer.new_parent_edge)

    # Step 6: the approval gate. Declined → retain EVERYTHING (the manifest now carries
    # every candidate; re-entry lands here again).
    synced = tuple(
        SyncedLayer(
            node_id=matched[pos].node_id,
            plan_id=matched[pos].plan_id,
            branch=matched[pos].branch,
            pr_number=matched[pos].pr_number,
            before_sha=layers_list[pos].before_sha,
            after_sha=candidates[pos],
        )
        for pos in range(len(layers_list))
    )
    cascade = SyncCascade(
        objective_id=train.objective_id,
        base_branch=train.base,
        include_base=manifest.include_base,
        base_before=matched[0].parent_checkpoint_sha if manifest.include_base else None,
        base_after=manifest.captured_base_head if manifest.include_base else None,
        layers=synced,
    )
    if sync.approve is not None and not sync.approve(cascade):
        return SyncResult(
            objective_id=train.objective_id,
            objective_url=train.objective_url,
            redirected_from=train.redirected_from,
            operation_id=None,
            abandoned_operation_id=None,
            no_op=False,
            declined=True,
            resumed=False,
            base_cascaded=False,
            base_advanced=_base_advanced(train),
            affected=(),
            continued=True,
        )

    # Step 7: post-approval re-observation, then the prepared record under the MANIFEST's
    # operation id + run id, then manifest retirement, then the normal tail.
    base_after = manifest.captured_base_head if manifest.include_base else None
    _reobserve(sync, train, claimed, base_after=base_after, adopted_heads=adopted_heads or None)
    observed_before = {layer.branch: layer.before_sha for layer in layers_list}
    adopted_payload: dict[str, object] | None = None
    if manifest.adopted_node is not None:
        adopted_layer = next(
            layer for layer in layers_list if layer.node_id == manifest.adopted_node
        )
        adopted_payload = {
            "node_id": adopted_layer.node_id,
            "plan_id": adopted_layer.plan_id,
            "remote_head": adopted_layer.before_sha,
        }
    record = PreparedRecord(
        operation_id=manifest.operation_id,
        operation_kind=(
            OperationKind.ADOPT if manifest.adopted_node is not None else OperationKind.SYNC
        ),
        delivery_lineage=lineage,
        objective_id=train.objective_id,
        run_id=manifest.run_id,
        created=sync.now(),
        affected_plans=tuple(layer.plan_id for layer in layers_list),
        before=_before_payload(
            sync, train, claimed, matched, base_after=base_after, observed_before=observed_before
        ),
        after=_after_payload(
            train, claimed, matched, candidates, base_after=base_after, adopted=adopted_payload
        ),
    )
    try:
        sync.persistence.append_prepared(train.objective_id, record)
    except UnresolvedOperationError as exc:
        raise SyncError(str(exc), error_type="unresolved_operation") from exc

    # Decision 12: the manifest is retired the moment the prepared record is durable — the
    # journal is the sole authority from here (a second --continue finds no_continuation);
    # a deletion failure is a loud note, never a refusal.
    notes: list[str] = []
    try:
        sync.manifest_clear(sync.repo_root, lineage)
    except OSError as exc:
        notes.append(
            f"could not retire the continuation manifest ({exc}) — the operation proceeds "
            "under the journal; clear the stale file with `perk objective stack sync --abort`"
        )
    try:
        _push(sync, train.objective_id, manifest.operation_id, synced)
        _verify_postconditions(sync, train, claimed, matched, candidates)
        result = _complete(
            sync,
            train,
            synced,
            new_parents=new_parents,
            operation_id=manifest.operation_id,
            abandoned_operation_id=None,
            resumed=False,
            base_cascaded=manifest.include_base,
            adopted_node=manifest.adopted_node,
            continued=True,
            notes=tuple(notes),
        )
    finally:
        # The journal owns the operation now: the retained worktree/temp refs are residue on
        # every exit (success or a post-prepare failure that resumes via sync/recover).
        cleanup_notes = _cleanup(sync, targets.ref_prefix, targets.worktree)
    # Only reached on success — a cleanup failure surfaces as a loud result note.
    return replace(result, notes=result.notes + tuple(cleanup_notes))


# ----------------------------------------------------------------- abort (§8.49)


@dataclass(frozen=True)
class AbortPreview:
    """What the abort confirmation renders: the manifest identity and exactly what an
    affirmative answer will delete (``contained`` = the full residue; otherwise only the
    manifest file — the un-matched residue is left for recover's pattern-based sweep)."""

    manifest_path: Path
    parseable: bool
    contained: bool
    operation_id: str | None
    conflict_node_id: str | None
    worktree_path: str | None


@dataclass(frozen=True)
class _Abort:
    """The focused abort dependencies — no publish/authority/candidate machinery."""

    repo_root: Path
    worktree_root: Path
    reconstruct: Callable[[Path, str], TrainStatus]
    delete_ref: Callable[[Path, str], None]
    list_refs: Callable[[Path, str], list[str]]
    worktree_remove: Callable[[Path, Path], None]
    worktree_prune: Callable[[Path], None]
    pending_read: Callable[[Path, str], continuation.PendingContinuation | None]
    manifest_clear: Callable[[Path, str], None]


def abort_train_sync(
    repo_root: Path,
    *,
    objective_id: str,
    worktree_root: Path,
    approve: Callable[[AbortPreview], bool] | None = None,
    reconstruct: Callable[[Path, str], TrainStatus] = observe.reconstruct_repo_train,
    delete_ref: Callable[[Path, str], None] = git_mod.delete_ref,
    list_refs: Callable[[Path, str], list[str]] = git_mod.list_refs,
    worktree_remove: Callable[[Path, Path], None] = _default_worktree_remove,
    worktree_prune: Callable[[Path], None] = git_mod.worktree_prune,
    pending_read: Callable[
        [Path, str], continuation.PendingContinuation | None
    ] = continuation.pending_continuation,
    manifest_clear: Callable[[Path, str], None] = continuation.clear_manifest,
    lock: Callable[[Path], AbstractContextManager[None]] = oplock.stack_operation_lock,
) -> SyncResult:
    """Discard a retained conflict stop (``sync --abort``, contracts.md §8.49).

    Confirmation-gated (the ``approve`` callback; ``None`` = auto-approve): a valid manifest
    deletes the retained worktree, the operation's temp refs, and the manifest; an invalid
    or unparseable one deletes ONLY the manifest file (the un-matched residue is left for
    recover's pattern-based sweep). A declined confirmation is the success envelope
    ``aborted: False, declined: True`` with nothing deleted. No journal writes on any arm —
    no remote boundary was crossed.
    """
    abort = _Abort(
        repo_root=repo_root,
        worktree_root=worktree_root,
        reconstruct=reconstruct,
        delete_ref=delete_ref,
        list_refs=list_refs,
        worktree_remove=worktree_remove,
        worktree_prune=worktree_prune,
        pending_read=pending_read,
        manifest_clear=manifest_clear,
    )
    with _held_operation_lock(lock, repo_root):
        return _abort(abort, objective_id, approve)


def _abort(
    abort: _Abort, objective_id: str, approve: Callable[[AbortPreview], bool] | None
) -> SyncResult:
    train = abort.reconstruct(abort.repo_root, objective_id)
    if isinstance(train, NoDeliveryTrain):
        raise SyncError(
            f"objective {train.objective_id} has no delivery train ({train.reason})",
            error_type="not_stacked",
        )
    lineage = _require_lineage(train)
    pending = abort.pending_read(abort.repo_root, lineage)
    if pending is None:
        raise SyncError(
            f"no continuation manifest exists for lineage {lineage} — nothing to abort",
            error_type="no_continuation",
        )
    manifest = pending.manifest

    def _result(*, aborted: bool, declined: bool, notes: tuple[str, ...] = ()) -> SyncResult:
        return SyncResult(
            objective_id=train.objective_id,
            objective_url=train.objective_url,
            redirected_from=train.redirected_from,
            operation_id=None,  # nothing journaled by any abort arm
            abandoned_operation_id=None,
            no_op=False,
            declined=declined,
            resumed=False,
            base_cascaded=False,
            base_advanced=_base_advanced(train),
            affected=(),
            aborted=aborted,
            notes=notes,
        )

    targets: continuation.ValidatedTargets | None = None
    contained = False
    if manifest is not None:
        try:
            targets = continuation.validated_targets(manifest, abort.worktree_root)
            contained = (
                manifest.objective_id == train.objective_id and manifest.delivery_lineage == lineage
            )
        except continuation.ContainmentViolation:
            targets = None
    preview = AbortPreview(
        manifest_path=pending.path,
        parseable=manifest is not None,
        contained=contained and targets is not None,
        operation_id=manifest.operation_id if manifest is not None else None,
        conflict_node_id=manifest.conflict_node_id if manifest is not None else None,
        worktree_path=manifest.worktree_path if manifest is not None else None,
    )
    if approve is not None and not approve(preview):
        return _result(aborted=False, declined=True)

    notes: list[str] = []
    if preview.contained and targets is not None:
        cleanup_notes = _cleanup(abort, targets.ref_prefix, targets.worktree)
        notes.extend(cleanup_notes)
        if cleanup_notes:
            notes.append(
                f"operation {targets.operation_id} was aborted and its manifest retired "
                "despite incomplete cleanup"
            )
        else:
            notes.append(f"discarded operation {targets.operation_id}'s retained residue")
    elif manifest is not None:
        notes.append(
            "the manifest-named targets failed containment validation — only the manifest "
            "file was deleted; un-matched residue is left for "
            "`perk objective stack recover`'s pattern-based sweep"
        )
    else:
        notes.append(
            "the manifest was unparseable — only the manifest file was deleted; any retained "
            "residue is left for `perk objective stack recover`'s pattern-based sweep"
        )
    try:
        abort.manifest_clear(abort.repo_root, lineage)
    except OSError as exc:
        cleanup_detail = f" Cleanup report: {'; '.join(notes)}." if notes else ""
        raise SyncError(
            f"could not delete the continuation manifest at {pending.path} ({exc}) — the "
            f"manifest remains authoritative; fix the filesystem issue and rerun "
            f"`perk objective stack sync --abort`.{cleanup_detail}",
            error_type="git_error",
        ) from exc
    return _result(aborted=True, declined=False, notes=tuple(notes))
