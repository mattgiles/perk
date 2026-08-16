"""The delivery **transfer** operation — objective replan transfer (contracts.md §8.53).

`perk objective create --supersedes` routes here whenever a replan touches stacked delivery
(a stacked predecessor, or an incremental predecessor converting to a stacked successor): the
§8.32 close-old/create-new supersede becomes the architecture's 9-step convergence protocol —
preserve the exact published plan prefix, transfer plan objective/node ownership to the
successor, allow arbitrary unpublished-suffix reshaping, verify the successor projection, and
close the predecessor only after convergence. Every effectful callable is keyword-injectable
with production defaults (the ``publish.py``/``sync.py`` pattern; tests pass fakes).

Interruption tolerance is run_id-keyed convergence, not a backend transaction: the
predecessor-carried ``PreparedRecord`` IS the durable **transfer manifest** (sufficient to
re-drive creation cross-session — a recover process has no session artifacts), successor
creation is find-then-return idempotent on ``run_id`` with a convergent found-arm
(``close_predecessor=False``), every ownership/identity write is an idempotent merge-write
skipped when the stored values already match, and the predecessor closes LAST — only after the
successor projection verifies (D12). The one non-journaled arm is incremental→stacked (the
predecessor stores no lineage, so the append gate structurally refuses; tolerance there is
by-construction — convergent creation + idempotent writes + close-last), whose cross-session
abandonment is deliberately not journal-discoverable (a flagged residual).

Locking mirrors sync's lock-first shape (D15): :func:`run_transfer` acquires
``oplock.stack_operation_lock`` before the journal fold, planning, and probes, holding it
through prepare → create → stamp → verify → finalize → complete; :func:`roll_forward_transfer`
is the lock-assumed inner core recover calls while already holding the same lock. Import
direction stays §8.44's: delivery imports the backend contracts + gateway one-directionally.
"""

import contextlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BeforeValidator

from perk import objective, plan
from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import ObjectiveRef, ObjectiveState
from perk.backends.resolve import resolve_issue_backend, resolve_objective_store
from perk.boundary import StrictInputModel, StrTuple, translate_validation_errors
from perk.delivery import observe, oplock, sync
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalFold,
    JournalRecordTooLarge,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
    mint_operation_id,
)
from perk.delivery.persistence import AppendResult, resolve_train_persistence
from perk.delivery.train import (
    STRUCTURAL_BLOCKER_CODES,
    LayerPr,
    LayerWriter,
    NoDeliveryTrain,
    TrainReconstructionError,
    TrainStatus,
    WorktreeFacts,
)
from perk.delivery.writers import RemoteWriterProbe, WriterObservationError
from perk.github import stacks
from perk.substrate import git as git_mod


class TransferError(Exception):
    """A replan transfer failed or refused. ``error_type`` is the stable machine code the CLI
    boundary maps onto its failure envelope."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # policy_immutable | base_immutable | prefix_mismatch
        # | dropped_open_pr | pr_exists | missing_lineage | transfer_incomplete
        # | transfer_unverified | transfer_manifest_oversize | unresolved_operation
        # | dirty_worktree | active_writer | writer_observation_unavailable
        # | claimed_prefix_malformed | operation_in_progress | objective_not_found
        # | objective_not_open | invalid_delivery_policy | invalid_roadmap
        # | supersede_unsupported | invalid_input (contracts.md §8.53 declares the bounded
        # set; infra raises — GitError/GitHubError/store errors — propagate for the CLI's
        # own mapping, always leaving any prepared operation unresolved)
    ) -> None:
        super().__init__(message)
        self.error_type = error_type


def _bare(identifier: str) -> str:
    """Strip one leading ``#`` (the canonical-rendering normalization for id comparisons)."""
    return identifier.removeprefix("#")


# ----------------------------------------------------------------- the transfer manifest (D7)
# The predecessor-carried PreparedRecord's `before`/`after` mappings ARE the durable manifest.
# The edge models are STRICT (extra="forbid", every key required — machine-authored payloads,
# mirroring journal.PreparedRecordModel per workflow/pydantic-boundary-models), converted
# field-by-field to frozen dataclasses.


@dataclass(frozen=True)
class ClaimedPrefixEntry:
    """One checkpoint-claimed predecessor layer (the D2 published definition), recorded with
    its PREDECESSOR node id (node ids may change freely across the transfer)."""

    node_id: str
    plan_id: str
    branch: str
    parent_checkpoint_sha: str
    published_head_sha: str
    pr_number: int | None


@dataclass(frozen=True)
class CarriedPlan:
    """One carried plan outside the claimed prefix, with its PREDECESSOR node id."""

    node_id: str
    plan_id: str


@dataclass(frozen=True)
class TransferBefore:
    """The recorded predecessor facts (`before`)."""

    predecessor_objective_id: str
    base: str
    delivery: str
    delivery_lineage: str | None
    claimed_prefix: tuple[ClaimedPrefixEntry, ...]
    carried_unpublished: tuple[CarriedPlan, ...]


@dataclass(frozen=True)
class TransferAfter:
    """The complete successor materialization intent (`after`) — sufficient to re-drive
    creation cross-session."""

    title: str
    prose: str
    base: str | None
    delivery: str
    delivery_lineage: str | None
    roadmap_nodes: tuple[objective.ObjectiveNode, ...]
    carry_map: Mapping[str, str]


@dataclass(frozen=True)
class TransferManifest:
    """The decoded transfer manifest (one prepared record's `before` + `after`)."""

    before: TransferBefore
    after: TransferAfter


def _seq_to_tuple(value: object) -> object:
    """The journal read-back materializes YAML sequences as lists; list→tuple is the one
    allowlisted container coercion under strict (mirrors ``boundary.StrTuple``)."""
    return tuple(value) if isinstance(value, list) else value


class _ClaimedPrefixEntryModel(StrictInputModel):
    node_id: str
    plan_id: str
    branch: str
    parent_checkpoint_sha: str
    published_head_sha: str
    pr_number: int | None

    def to_domain(self) -> ClaimedPrefixEntry:
        return ClaimedPrefixEntry(
            node_id=self.node_id,
            plan_id=self.plan_id,
            branch=self.branch,
            parent_checkpoint_sha=self.parent_checkpoint_sha,
            published_head_sha=self.published_head_sha,
            pr_number=self.pr_number,
        )


class _CarriedPlanModel(StrictInputModel):
    node_id: str
    plan_id: str

    def to_domain(self) -> CarriedPlan:
        return CarriedPlan(node_id=self.node_id, plan_id=self.plan_id)


class _TransferBeforeModel(StrictInputModel):
    predecessor_objective_id: str
    base: str
    delivery: Literal["incremental", "stacked"]
    delivery_lineage: str | None
    claimed_prefix: Annotated[tuple[_ClaimedPrefixEntryModel, ...], BeforeValidator(_seq_to_tuple)]
    carried_unpublished: Annotated[tuple[_CarriedPlanModel, ...], BeforeValidator(_seq_to_tuple)]

    def to_domain(self) -> TransferBefore:
        return TransferBefore(
            predecessor_objective_id=self.predecessor_objective_id,
            base=self.base,
            delivery=self.delivery,
            delivery_lineage=self.delivery_lineage,
            claimed_prefix=tuple(entry.to_domain() for entry in self.claimed_prefix),
            carried_unpublished=tuple(entry.to_domain() for entry in self.carried_unpublished),
        )


class _ManifestNodeModel(StrictInputModel):
    """One full roadmap-node dump. ``adopt_issue`` rides per node for readability; the
    authoritative carry mapping is ``after.carry_map``."""

    id: str
    slug: str | None
    description: str
    status: str
    pr: str | None
    depends_on: StrTuple | None
    adopt_issue: str | None
    comment: str | None

    def to_domain(self) -> objective.ObjectiveNode:
        try:
            status = objective.NodeStatus(self.status)
        except ValueError as exc:
            raise ValueError(f"node {self.id!r} carries unknown status {self.status!r}") from exc
        return objective.ObjectiveNode(
            id=self.id,
            description=self.description,
            status=status,
            pr=self.pr,
            depends_on=self.depends_on,
            slug=self.slug,
            comment=self.comment,
        )


class _TransferAfterModel(StrictInputModel):
    title: str
    prose: str
    base: str | None
    delivery: Literal["incremental", "stacked"]
    delivery_lineage: str | None
    roadmap_nodes: Annotated[tuple[_ManifestNodeModel, ...], BeforeValidator(_seq_to_tuple)]
    carry_map: dict[str, str]

    def to_domain(self) -> TransferAfter:
        return TransferAfter(
            title=self.title,
            prose=self.prose,
            base=self.base,
            delivery=self.delivery,
            delivery_lineage=self.delivery_lineage,
            roadmap_nodes=tuple(node.to_domain() for node in self.roadmap_nodes),
            carry_map=dict(self.carry_map),
        )


def decode_transfer_record(record: PreparedRecord) -> TransferManifest:
    """Strict-decode and cross-check a TRANSFER prepared record's manifest.

    Shape validation alone is insufficient because journal events are mutable backend state. The
    envelope, predecessor observation, and successor intent must describe one internally coherent
    transfer before recovery is allowed to perform any write. Any mismatch is corruption, never a
    lenient re-interpretation of the manifest's authority.
    """
    if record.operation_kind is not OperationKind.TRANSFER:
        raise JournalCorruptionError(
            f"operation {record.operation_id} is {record.operation_kind.value}, not transfer"
        )
    where = f"transfer manifest of operation {record.operation_id}"
    with translate_validation_errors(JournalCorruptionError, source=where):
        before_model = _TransferBeforeModel.model_validate(dict(record.before))
        after_model = _TransferAfterModel.model_validate(dict(record.after))
    try:
        manifest = TransferManifest(before=before_model.to_domain(), after=after_model.to_domain())
        _validate_transfer_record(record, manifest, after_model=after_model)
    except ValueError as exc:
        raise JournalCorruptionError(f"{where}: {exc}") from exc
    return manifest


def _validate_transfer_record(
    record: PreparedRecord,
    manifest: TransferManifest,
    *,
    after_model: _TransferAfterModel,
) -> None:
    """Cross-check the TRANSFER envelope and both manifest halves before recovery writes."""
    before = manifest.before
    after = manifest.after
    if _bare(record.objective_id) != _bare(before.predecessor_objective_id):
        raise ValueError(
            f"envelope objective {record.objective_id!r} does not match predecessor "
            f"{before.predecessor_objective_id!r}"
        )
    if before.delivery != objective.DeliveryPolicy.STACKED.value:
        raise ValueError(
            f"journaled transfer predecessor policy must be 'stacked', observed {before.delivery!r}"
        )
    lineage = before.delivery_lineage
    if not lineage or record.delivery_lineage != lineage:
        raise ValueError(
            f"envelope lineage {record.delivery_lineage!r} does not match predecessor lineage "
            f"{lineage!r}"
        )
    if after.delivery == objective.DeliveryPolicy.STACKED.value:
        if after.delivery_lineage != lineage:
            raise ValueError(
                f"stacked successor lineage {after.delivery_lineage!r} does not match "
                f"predecessor lineage {lineage!r}"
            )
    elif after.delivery_lineage is not None:
        raise ValueError(
            f"incremental successor must not carry a delivery lineage, observed "
            f"{after.delivery_lineage!r}"
        )

    node_ids = [node.id for node in after.roadmap_nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError(f"successor roadmap carries duplicate node ids: {node_ids!r}")
    unknown_carry_nodes = sorted(set(after.carry_map) - set(node_ids))
    if unknown_carry_nodes:
        raise ValueError(f"carry_map names unknown successor nodes {unknown_carry_nodes!r}")
    invalid_carries = sorted(
        node_id
        for node_id, plan_id in after.carry_map.items()
        if not isinstance(plan_id, str) or not plan_id.strip()
    )
    if invalid_carries:
        raise ValueError(f"carry_map has blank plan identities for nodes {invalid_carries!r}")
    for node_model in after_model.roadmap_nodes:
        expected = after.carry_map.get(node_model.id)
        if node_model.adopt_issue != expected:
            raise ValueError(
                f"node {node_model.id!r} records adopt_issue={node_model.adopt_issue!r} but "
                f"carry_map records {expected!r}"
            )

    claimed = tuple(entry.plan_id for entry in before.claimed_prefix)
    carried = tuple(entry.plan_id for entry in before.carried_unpublished)
    predecessor_plan_ids = claimed + carried
    if len(predecessor_plan_ids) != len(set(predecessor_plan_ids)):
        raise ValueError(f"predecessor manifest repeats carried plans {predecessor_plan_ids!r}")
    predecessor_node_ids = tuple(
        entry.node_id for entry in (*before.claimed_prefix, *before.carried_unpublished)
    )
    if len(predecessor_node_ids) != len(set(predecessor_node_ids)):
        raise ValueError(f"predecessor manifest repeats carried node ids {predecessor_node_ids!r}")

    projection = manifest_projection(after)
    projected_plans = tuple(plan_id for _, plan_id in projection if plan_id is not None)
    projected_prefix = tuple(plan_id for _, plan_id in projection[: len(claimed)])
    if projected_prefix != claimed:
        raise ValueError(
            f"successor claimed prefix {projected_prefix!r} does not match predecessor prefix "
            f"{claimed!r}"
        )
    if projected_plans != predecessor_plan_ids:
        raise ValueError(
            f"successor carried plans {projected_plans!r} do not match predecessor plans "
            f"{predecessor_plan_ids!r}"
        )
    if record.affected_plans != projected_plans:
        raise ValueError(
            f"envelope affected_plans {record.affected_plans!r} does not match successor "
            f"projection {projected_plans!r}"
        )
    if after.delivery == objective.DeliveryPolicy.INCREMENTAL.value and claimed:
        raise ValueError("incremental successor cannot carry a checkpoint-claimed prefix")


def manifest_projection(after: TransferAfter) -> tuple[tuple[str, str | None], ...]:
    """The successor's recorded delivery-order ``(node_id, carried plan id | None)``
    projection — computed from the manifest only, never live re-derivation while unresolved.

    A node's carried plan identity is its ``carry_map`` entry when present (Linear — the plan
    IS the node-issue) else its ``pr`` backlink (GitHub), bare-normalized. Fresh nodes carry
    ``None``. Raises ``ValueError`` when no delivery order exists (a corrupt roadmap dump).
    """
    order = objective.delivery_order(list(after.roadmap_nodes))
    projection: list[tuple[str, str | None]] = []
    for node in order:
        identity = after.carry_map.get(node.id) or node.pr
        projection.append((node.id, _bare(identity) if identity else None))
    return tuple(projection)


def _before_payload(before: TransferBefore) -> dict[str, object]:
    """The `before` mapping's canonical plain-type serialization (YAML-safe)."""
    return {
        "predecessor_objective_id": before.predecessor_objective_id,
        "base": before.base,
        "delivery": before.delivery,
        "delivery_lineage": before.delivery_lineage,
        "claimed_prefix": [
            {
                "node_id": entry.node_id,
                "plan_id": entry.plan_id,
                "branch": entry.branch,
                "parent_checkpoint_sha": entry.parent_checkpoint_sha,
                "published_head_sha": entry.published_head_sha,
                "pr_number": entry.pr_number,
            }
            for entry in before.claimed_prefix
        ],
        "carried_unpublished": [
            {"node_id": entry.node_id, "plan_id": entry.plan_id}
            for entry in before.carried_unpublished
        ],
    }


def _after_payload(after: TransferAfter) -> dict[str, object]:
    """The `after` mapping's canonical plain-type serialization (YAML-safe)."""
    return {
        "title": after.title,
        "prose": after.prose,
        "base": after.base,
        "delivery": after.delivery,
        "delivery_lineage": after.delivery_lineage,
        "roadmap_nodes": [
            {
                "id": node.id,
                "slug": node.slug,
                "description": node.description,
                "status": node.status.value,
                "pr": node.pr,
                "depends_on": list(node.depends_on) if node.depends_on is not None else None,
                "adopt_issue": after.carry_map.get(node.id),
                "comment": node.comment,
            }
            for node in after.roadmap_nodes
        ],
        "carry_map": dict(after.carry_map),
    }


# ----------------------------------------------------------------- injected-seam protocols


class TransferStore(Protocol):
    """The narrow objective-store surface the transfer consumes (structurally satisfied by
    every concrete :class:`~perk.backends.objective_store.ObjectiveStore`)."""

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None: ...

    def find_objective(self, *, run_id: str) -> ObjectiveRef | None: ...

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
    ) -> ObjectiveRef | None: ...

    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool: ...


class TransferIssues(Protocol):
    """The narrow issue-backend surface (the carried-plan header reads)."""

    def get_plan(self, *, issue_id: str) -> PlanState | None: ...


class TransferPersistence(Protocol):
    """The narrow train-persistence surface (journal + typed writers; structurally satisfied
    by :func:`resolve_train_persistence`'s adapter)."""

    def read_journal(self, objective_id: str) -> JournalFold: ...

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult: ...

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult: ...

    def transfer_plan_ownership(
        self, plan_id: str, *, objective_id: str, objective_node_id: str
    ) -> None: ...

    def stamp_layer_identity(
        self, plan_id: str, *, delivery_lineage: str, predecessor_plan_id: str | None
    ) -> None: ...

    def clear_delivery_metadata(self, plan_id: str) -> None: ...


class _PrFactsRead(Protocol):
    def __call__(self, *, number: int, repo_root: Path) -> stacks.PrDeliveryFacts | None: ...


@dataclass(frozen=True)
class TransferSeams:
    """The roll-forward core's seam bundle — everything create→stamp→verify→finalize→complete
    needs. Recover composes one of these (already holding the operation lock) to conclude an
    unresolved TRANSFER; :func:`run_transfer` wraps it with the fresh-pass preflight seams."""

    repo_root: Path
    store: TransferStore
    issues: TransferIssues
    persistence: TransferPersistence
    reconstruct: Callable[[Path, str], TrainStatus]
    now: Callable[[], str]


def resolve_transfer_seams(
    repo_root: Path,
    *,
    reconstruct: Callable[[Path, str], TrainStatus] = observe.reconstruct_repo_train,
    now: Callable[[], str] = plan.now_iso,
) -> TransferSeams:
    """Compose the production roll-forward seams from the committed ``[issues]`` selection."""
    return TransferSeams(
        repo_root=repo_root,
        store=resolve_objective_store(repo_root),
        issues=resolve_issue_backend(repo_root),
        persistence=resolve_train_persistence(repo_root),
        reconstruct=reconstruct,
        now=now,
    )


@dataclass(frozen=True)
class _Transfer:
    """The full fresh-pass bundle: the roll-forward seams plus the D13 preflight probes."""

    seams: TransferSeams
    remote_writers: RemoteWriterProbe
    pr_facts: _PrFactsRead
    worktree_branches: Callable[[Path], tuple[WorktreeFacts, ...]]
    trunk: Callable[[Path], str]


@dataclass(frozen=True)
class TransferResult:
    """The outcome of one :func:`run_transfer` invocation.

    ``operation_id`` is non-null ⟺ a TRANSFER record was journaled by (or rolled forward by)
    this invocation (the non-journaled incremental→stacked arm carries ``None``).
    ``abandoned_operation_id`` names the previously unresolved operation this invocation
    abandoned-with-proof before running the fresh protocol. ``rolled_forward`` marks the
    same-run rerun that completed an interrupted transfer from its recorded manifest.
    """

    predecessor_id: str
    successor: ObjectiveRef
    operation_id: str | None
    abandoned_operation_id: str | None
    rolled_forward: bool
    journaled: bool


@dataclass(frozen=True)
class TransferRequest:
    """The successor authoring intent the save carries into planning."""

    predecessor_id: str
    title: str
    prose: str
    base: str | None
    roadmap_nodes: tuple[objective.ObjectiveNode, ...]
    carry_map: Mapping[str, str]
    stacked: bool


@dataclass(frozen=True)
class TransferPlan:
    """The frozen preflight product: the manifest to journal/execute plus the journal arm."""

    manifest: TransferManifest
    journaled: bool


def _default_worktree_branches(repo_root: Path) -> tuple[WorktreeFacts, ...]:
    return observe.RepoDeliveryGit(repo_root).worktree_branches()


# ----------------------------------------------------------------- the public entry (D15)


def run_transfer(
    repo_root: Path,
    *,
    predecessor: ObjectiveState,
    predecessor_policy: objective.DeliveryPolicy,
    predecessor_id: str,
    run_id: str,
    title: str,
    prose: str,
    base: str | None,
    roadmap_nodes: Sequence[objective.ObjectiveNode],
    carry_map: Mapping[str, str],
    stacked: bool,
    remote_writers: RemoteWriterProbe,
    store_factory: Callable[[Path], TransferStore] = resolve_objective_store,
    issues_factory: Callable[[Path], TransferIssues] = resolve_issue_backend,
    persistence_factory: Callable[[Path], TransferPersistence] = resolve_train_persistence,
    reconstruct: Callable[[Path, str], TrainStatus] = observe.reconstruct_repo_train,
    pr_facts: _PrFactsRead = stacks.pr_delivery_facts,
    worktree_branches: Callable[[Path], tuple[WorktreeFacts, ...]] = _default_worktree_branches,
    trunk: Callable[[Path], str] = git_mod.detect_trunk_branch,
    lock: Callable[[Path], AbstractContextManager[None]] = oplock.stack_operation_lock,
    now: Callable[[], str] = plan.now_iso,
) -> TransferResult:
    """Run the replan transfer protocol for a superseding save (contracts.md §8.53).

    The save boundary supplies the predecessor state + policy from D1's sole fail-closed
    classification read. Lock-first (D15): the machine-local operation lock is acquired before
    the journal fold, the D11 rerun routing, the D13/D3-D6 planning + probes, and held through
    prepare → create → stamp → verify → finalize → complete. ``stacked`` is the successor's
    reviewed delivery choice; ``base`` is the save's resolved base intent (post-publication the
    successor stores the predecessor's stored base verbatim instead — D3). Raises
    :class:`TransferError` on
    every typed refusal; infra errors propagate for the CLI boundary, always leaving any
    prepared operation unresolved (recoverable via ``perk objective stack recover``).
    """
    seams = TransferSeams(
        repo_root=repo_root,
        store=store_factory(repo_root),
        issues=issues_factory(repo_root),
        persistence=persistence_factory(repo_root),
        reconstruct=reconstruct,
        now=now,
    )
    transfer = _Transfer(
        seams=seams,
        remote_writers=remote_writers,
        pr_facts=pr_facts,
        worktree_branches=worktree_branches,
        trunk=trunk,
    )
    request = TransferRequest(
        predecessor_id=_bare(predecessor_id.strip()),
        title=title,
        prose=prose,
        base=base,
        roadmap_nodes=tuple(roadmap_nodes),
        carry_map=dict(carry_map),
        stacked=stacked,
    )
    with _held_lock(lock, repo_root):
        return _run(
            transfer,
            request,
            predecessor=predecessor,
            predecessor_policy=predecessor_policy,
            run_id=run_id,
        )


@contextlib.contextmanager
def _held_lock(
    lock: Callable[[Path], AbstractContextManager[None]], repo_root: Path
) -> Iterator[None]:
    try:
        with lock(repo_root):
            yield
    except oplock.OperationLockBusy as exc:
        raise TransferError(str(exc), error_type="operation_in_progress") from exc


def _run(
    transfer: _Transfer,
    request: TransferRequest,
    *,
    predecessor: ObjectiveState,
    predecessor_policy: objective.DeliveryPolicy,
    run_id: str,
) -> TransferResult:
    seams = transfer.seams
    if _bare(predecessor.id) != request.predecessor_id:
        raise TransferError(
            f"classified predecessor {predecessor.id!r} does not match transfer target "
            f"{request.predecessor_id!r}",
            error_type="invalid_input",
        )
    if predecessor_policy is objective.DeliveryPolicy.INCREMENTAL and not request.stacked:
        raise TransferError(
            "incremental→incremental supersession never routes through the transfer protocol "
            "(the plain §8.32 store mutation owns it)",
            error_type="invalid_input",
        )

    abandoned_operation_id: str | None = None
    if predecessor_policy is objective.DeliveryPolicy.STACKED:
        lineage = _require_predecessor_lineage(predecessor)
        # D11 rerun routing: fold the predecessor journal FIRST (under the lock).
        fold = seams.persistence.read_journal(request.predecessor_id)
        routed = _route_unresolved(transfer, request, fold, run_id=run_id, lineage=lineage)
        if isinstance(routed, TransferResult):
            return routed
        abandoned_operation_id = routed

    # The superseded_by refusal runs AFTER the rerun routing: a transfer interrupted after
    # the finalize stamp (but before the close / the completion append) leaves the
    # predecessor stamped while still mid-protocol. When the stamped successor was created
    # by THIS run, creation + ownership + verification necessarily preceded the stamp
    # (finalize runs last-but-one), so the convergent conclusion is a re-finalize (idempotent
    # — ensures the close) — also the idempotent same-run re-save answer. Any other stamp is
    # a genuinely superseded predecessor.
    superseded_by = predecessor.header.get("superseded_by")
    if superseded_by:
        found = seams.store.find_objective(run_id=run_id)
        if found is not None and _bare(str(superseded_by)) == _bare(found.id):
            seams.store.finalize_supersession(
                old_objective_id=request.predecessor_id, new_objective_id=found.id
            )
            return TransferResult(
                predecessor_id=request.predecessor_id,
                successor=found,
                operation_id=None,
                abandoned_operation_id=abandoned_operation_id,
                rolled_forward=True,
                journaled=False,
            )
        raise TransferError(
            f"objective {request.predecessor_id} is already superseded by {superseded_by!r} — "
            "replan its successor instead",
            error_type="objective_not_open",
        )

    transfer_plan = plan_transfer(
        transfer,
        request,
        predecessor=predecessor,
        predecessor_policy=predecessor_policy,
        run_id=run_id,
    )
    operation_id: str | None = None
    record: PreparedRecord | None = None
    if transfer_plan.journaled:
        manifest = transfer_plan.manifest
        record = PreparedRecord(
            operation_id=mint_operation_id(),
            operation_kind=OperationKind.TRANSFER,
            delivery_lineage=manifest.before.delivery_lineage or "",
            objective_id=request.predecessor_id,
            run_id=run_id,
            created=seams.now(),
            affected_plans=tuple(
                plan_id for _, plan_id in manifest_projection(manifest.after) if plan_id
            ),
            before=_before_payload(manifest.before),
            after=_after_payload(manifest.after),
        )
        try:
            seams.persistence.append_prepared(request.predecessor_id, record)
        except JournalRecordTooLarge as exc:
            raise TransferError(
                f"the transfer manifest exceeds the journal event cap ({exc}) — shorten the "
                "objective prose and re-save (nothing was written)",
                error_type="transfer_manifest_oversize",
            ) from exc
        operation_id = record.operation_id
    successor = _execute(
        seams,
        transfer_plan.manifest,
        run_id=run_id,
        operation_id=operation_id,
        journaled=transfer_plan.journaled,
    )
    return TransferResult(
        predecessor_id=request.predecessor_id,
        successor=successor,
        operation_id=operation_id,
        abandoned_operation_id=abandoned_operation_id,
        rolled_forward=False,
        journaled=transfer_plan.journaled,
    )


def _require_predecessor_lineage(predecessor: ObjectiveState) -> str:
    """A stacked-policy predecessor MUST store a usable lineage — missing/blank/junk is the
    fail-closed typed refusal ``missing_lineage`` (the train reports the same condition as a
    structural blocker)."""
    value = predecessor.header.get("delivery_lineage")
    if isinstance(value, str) and value:
        return value
    raise TransferError(
        f"objective {predecessor.id} has delivery: stacked but no usable delivery_lineage "
        f"(observed {value!r}) — repair the objective metadata before replanning",
        error_type="missing_lineage",
    )


def _route_unresolved(
    transfer: _Transfer,
    request: TransferRequest,
    fold: JournalFold,
    *,
    run_id: str,
    lineage: str,
) -> TransferResult | str | None:
    """The D11 rerun routing over the predecessor fold. Returns a completed
    :class:`TransferResult` (the same-run roll-forward), the abandoned operation id (the
    proven all-before arm — the caller continues the fresh pass), or ``None`` (no unresolved
    operation)."""
    if not fold.unresolved:
        return None
    op = fold.unresolved[0]
    record = op.prepared.record
    if op.kind is not OperationKind.TRANSFER or not isinstance(record, PreparedRecord):
        raise TransferError(
            f"operation {op.operation_id} ({op.kind.value}) is unresolved on lineage "
            f"{lineage} — conclude it via `perk objective stack recover "
            f"{request.predecessor_id}` or the owning command before replanning",
            error_type="unresolved_operation",
        )
    manifest = decode_transfer_record(record)  # malformed → JournalCorruptionError (fail closed)
    found = transfer.seams.store.find_objective(run_id=record.run_id)
    if found is not None:
        corroborate_successor(transfer.seams.store, found, manifest, record)
        if record.run_id == run_id:
            # The same run re-invoked: roll forward to completion from the RECORDED manifest
            # (never live re-derivation while unresolved).
            successor = _execute(
                transfer.seams,
                manifest,
                run_id=record.run_id,
                operation_id=record.operation_id,
                journaled=True,
            )
            return TransferResult(
                predecessor_id=request.predecessor_id,
                successor=successor,
                operation_id=record.operation_id,
                abandoned_operation_id=None,
                rolled_forward=True,
                journaled=True,
            )
        raise TransferError(
            f"an interrupted transfer (operation {record.operation_id}) already created "
            f"successor {found.id} for predecessor {request.predecessor_id} under run "
            f"{record.run_id} — conclude it with `perk objective stack recover "
            f"{request.predecessor_id}` before re-saving",
            error_type="transfer_incomplete",
        )
    # Successor absent ⇒ provably all-before: creation is the first post-prepare effect (the
    # Linear pre-attachment window leaves an inert non-perk residue project, never a
    # predecessor-touching write — D14). Abandon with proof, then continue the fresh pass.
    transfer.seams.persistence.append_outcome(
        request.predecessor_id,
        OutcomeRecord(
            operation_id=record.operation_id,
            role=EventRole.ABANDONED,
            created=transfer.seams.now(),
            observed=transfer_abandon_observation(record),
        ),
    )
    return record.operation_id


def transfer_abandon_observation(record: PreparedRecord) -> dict[str, object]:
    """The all-before proof an abandoned TRANSFER journals: the successor named by the
    record's ``run_id`` was positively absent, so no post-prepare effect exists (creation is
    the first one)."""
    return {
        "proof": "successor_absent",
        "run_id": record.run_id,
        "predecessor_objective_id": record.objective_id,
    }


def corroborate_successor(
    store: TransferStore,
    found: ObjectiveRef,
    manifest: TransferManifest,
    record: PreparedRecord,
) -> ObjectiveState:
    """The roll-forward corroboration (D7): a successor found by ``record.run_id`` must also
    carry ``supersedes`` = the predecessor and the recorded lineage — mismatch fails closed
    (``transfer_incomplete``; a foreign objective must never be adopted as the successor)."""
    state = store.get_objective(objective_id=found.id)
    if state is None:
        raise TransferError(
            f"objective {found.id} was found by run {record.run_id} but cannot be read — "
            "refusing to corroborate the successor",
            error_type="transfer_incomplete",
        )
    supersedes = state.header.get("supersedes")
    expected_predecessor = _bare(manifest.before.predecessor_objective_id)
    if not isinstance(supersedes, str) or _bare(supersedes) != expected_predecessor:
        raise TransferError(
            f"objective {found.id} (found by run {record.run_id}) records "
            f"supersedes={supersedes!r} but the transfer manifest names predecessor "
            f"{expected_predecessor} — refusing to adopt it as the successor",
            error_type="transfer_incomplete",
        )
    stored_lineage = state.header.get("delivery_lineage")
    if (stored_lineage or None) != (manifest.after.delivery_lineage or None):
        raise TransferError(
            f"objective {found.id} (found by run {record.run_id}) stores "
            f"delivery_lineage={stored_lineage!r} but the transfer manifest records "
            f"{manifest.after.delivery_lineage!r} — refusing to adopt it as the successor",
            error_type="transfer_incomplete",
        )
    return state


# ----------------------------------------------------------------- planning (D13 + D3-D6)


def plan_transfer(
    transfer: _Transfer,
    request: TransferRequest,
    *,
    predecessor: ObjectiveState,
    predecessor_policy: objective.DeliveryPolicy,
    run_id: str,
) -> TransferPlan:
    """The D13-split preflight: observe the predecessor (train reconstruction for a stacked
    predecessor; direct reads for an incremental one), enforce D3-D6, and freeze the transfer
    manifest. Every refusal is typed with exact expected-vs-observed detail; nothing has been
    written when it raises."""
    successor_policy = (
        objective.DeliveryPolicy.STACKED
        if request.stacked
        else objective.DeliveryPolicy.INCREMENTAL
    )
    try:
        projection = _request_projection(request)
    except ValueError as exc:
        raise TransferError(
            f"the successor roadmap has no delivery order: {exc}", error_type="invalid_roadmap"
        ) from exc
    cited = [plan_id for _, plan_id in projection if plan_id is not None]
    duplicates = sorted({plan_id for plan_id in cited if cited.count(plan_id) > 1})
    if duplicates:
        raise TransferError(
            f"the successor roadmap cites carried plan(s) {duplicates} more than once — the "
            "node↔plan mapping must be bijective",
            error_type="prefix_mismatch",
        )

    if predecessor_policy is objective.DeliveryPolicy.STACKED:
        return _plan_from_stacked(
            transfer,
            request,
            predecessor=predecessor,
            successor_policy=successor_policy,
            projection=projection,
        )
    return _plan_from_incremental(
        transfer,
        request,
        predecessor=predecessor,
        projection=projection,
        run_id=run_id,
    )


def _request_projection(request: TransferRequest) -> tuple[tuple[str, str | None], ...]:
    """The requested successor's ``(node_id, carried plan id | None)`` delivery-order
    projection (the same rule as :func:`manifest_projection`, over the request)."""
    order = objective.delivery_order(list(request.roadmap_nodes))
    projection: list[tuple[str, str | None]] = []
    for node in order:
        identity = request.carry_map.get(node.id) or node.pr
        projection.append((node.id, _bare(identity) if identity else None))
    return tuple(projection)


def _plan_from_stacked(
    transfer: _Transfer,
    request: TransferRequest,
    *,
    predecessor: ObjectiveState,
    successor_policy: objective.DeliveryPolicy,
    projection: tuple[tuple[str, str | None], ...],
) -> TransferPlan:
    """The stacked-predecessor preflight: reconstruct the train, derive the claimed prefix
    (D2), then D3 (post-publication immutability), D4 (prefix preservation), D5 (open-PR
    guards), and D6 (dirty/active blocking)."""
    seams = transfer.seams
    lineage = _require_predecessor_lineage(predecessor)
    train = seams.reconstruct(seams.repo_root, request.predecessor_id)
    if isinstance(train, NoDeliveryTrain):
        raise TransferError(
            f"objective {train.objective_id} classified stacked but reconstructs no delivery "
            f"train ({train.reason}) — broken stored state",
            error_type="claimed_prefix_malformed",
        )
    try:
        sync.refuse_structural_blockers(train)
        claimed = sync.derive_claimed_prefix(train)
    except sync.SyncError as exc:
        raise TransferError(str(exc), error_type=exc.error_type) from exc

    open_pr_plans = {
        layer.plan_id: layer
        for layer in train.layers
        if layer.plan_id is not None
        and layer.pr in (LayerPr.DRAFT, LayerPr.READY, LayerPr.WRONG_BASE)
    }
    plan_universe = {layer.plan_id for layer in train.layers if layer.plan_id is not None}
    cited = [plan_id for _, plan_id in projection if plan_id is not None]
    foreign = sorted(set(cited) - plan_universe)
    if foreign:
        raise TransferError(
            f"the successor roadmap cites plan(s) {foreign} that do not exist on predecessor "
            f"objective {request.predecessor_id} (its plans: {sorted(plan_universe)})",
            error_type="prefix_mismatch",
        )

    # D3 — post-publication immutability (published = the checkpoint-claimed prefix, D2).
    if claimed:
        if successor_policy is not objective.DeliveryPolicy.STACKED:
            raise TransferError(
                f"objective {request.predecessor_id} has {len(claimed)} published layer(s) — "
                "the delivery policy is immutable after first publication; the successor must "
                "stay stacked",
                error_type="policy_immutable",
            )
        stored_base = predecessor.header.get("base")
        predecessor_effective = (
            stored_base if isinstance(stored_base, str) and stored_base else train.base
        )
        successor_effective = request.base or transfer.trunk(seams.repo_root)
        if successor_effective != predecessor_effective:
            raise TransferError(
                f"the published train is anchored on base {predecessor_effective!r} — a "
                f"replan cannot change it to {successor_effective!r} after publication",
                error_type="base_immutable",
            )
        # D4 — prefix preservation: the first K delivery-order nodes carry the K claimed
        # plans in exact order, each exactly once, none dropped.
        expected = [layer.plan_id for layer in claimed]
        observed = [plan_id for _, plan_id in projection[: len(claimed)]]
        if observed != expected or any(cited.count(plan_id) != 1 for plan_id in expected):
            raise TransferError(
                f"the successor's first {len(claimed)} delivery-order node(s) must carry the "
                f"published plans {expected} in exact order, each exactly once — observed "
                f"{observed} (full cited order: {cited})",
                error_type="prefix_mismatch",
            )

    # D5 — the open-PR drop guard + the policy-conversion refusal.
    dropped_open = sorted(set(open_pr_plans) - set(cited))
    if dropped_open:
        detail = ", ".join(
            f"plan #{plan_id} (PR #{open_pr_plans[plan_id].pr_number})" for plan_id in dropped_open
        )
        raise TransferError(
            f"the successor roadmap drops predecessor plan(s) with OPEN PRs: {detail} — carry "
            "them forward or close the PRs first",
            error_type="dropped_open_pr",
        )
    if successor_policy is not objective.DeliveryPolicy.STACKED:
        carried_open = sorted(set(open_pr_plans) & set(cited))
        if carried_open:
            detail = ", ".join(
                f"plan #{plan_id} (PR #{open_pr_plans[plan_id].pr_number})"
                for plan_id in carried_open
            )
            raise TransferError(
                f"a stacked→incremental replan cannot carry plan(s) with existing PRs: "
                f"{detail} — an existing remote PR already makes the layer published, so the "
                "conversion path no longer applies",
                error_type="pr_exists",
            )

    # D6 — dirty/active blocking over every carried plan + every open-PR plan.
    probe_ids = sorted(set(cited) | set(open_pr_plans))
    affected_layers = [layer for layer in train.layers if layer.plan_id in probe_ids]
    dirty = [layer for layer in affected_layers if layer.writer is LayerWriter.DIRTY]
    if dirty:
        names = ", ".join(f"{layer.node_id} ({layer.branch})" for layer in dirty)
        raise TransferError(
            f"affected layer worktrees carry uncommitted changes: {names} — commit or stash "
            "before replanning",
            error_type="dirty_worktree",
        )
    _probe_remote_writers(transfer, probe_ids)

    node_by_plan = {
        layer.plan_id: layer.node_id for layer in train.layers if layer.plan_id is not None
    }
    claimed_ids = {layer.plan_id for layer in claimed}
    before = TransferBefore(
        predecessor_objective_id=request.predecessor_id,
        base=train.base,
        delivery=objective.DeliveryPolicy.STACKED.value,
        delivery_lineage=lineage,
        claimed_prefix=tuple(
            ClaimedPrefixEntry(
                node_id=layer.node_id,
                plan_id=layer.plan_id,
                branch=layer.branch,
                parent_checkpoint_sha=layer.parent_checkpoint_sha,
                published_head_sha=layer.published_head_sha,
                pr_number=layer.pr_number,
            )
            for layer in claimed
        ),
        carried_unpublished=tuple(
            CarriedPlan(node_id=node_by_plan[plan_id], plan_id=plan_id)
            for plan_id in cited
            if plan_id not in claimed_ids
        ),
    )
    successor_stacked = successor_policy is objective.DeliveryPolicy.STACKED
    stored_base = predecessor.header.get("base")
    after = TransferAfter(
        title=request.title,
        prose=request.prose,
        # D3: post-publication the successor stores the predecessor's stored base VERBATIM;
        # pre-publication the requested base stands (replan is the only base-changing surface).
        base=(stored_base if isinstance(stored_base, str) and stored_base else None)
        if claimed
        else request.base,
        delivery=successor_policy.value,
        delivery_lineage=lineage if successor_stacked else None,
        roadmap_nodes=request.roadmap_nodes,
        carry_map=dict(request.carry_map),
    )
    return TransferPlan(manifest=TransferManifest(before=before, after=after), journaled=True)


def _plan_from_incremental(
    transfer: _Transfer,
    request: TransferRequest,
    *,
    predecessor: ObjectiveState,
    projection: tuple[tuple[str, str | None], ...],
    run_id: str,
) -> TransferPlan:
    """The incremental-predecessor (→ stacked successor) preflight: a direct observation path
    — the train abstraction only exists for stacked policy. The claimed prefix is trivially
    empty; the conversion refuses on ANY predecessor open PR touching a carried plan (D5's
    ``pr_exists``) or a dropped one (``dropped_open_pr``)."""
    seams = transfer.seams
    node_by_plan: dict[str, str] = {}
    for node in predecessor.nodes:
        if node.pr is not None:
            node_by_plan[_bare(node.pr)] = node.id
    cited = [plan_id for _, plan_id in projection if plan_id is not None]
    foreign = sorted(set(cited) - set(node_by_plan))
    if foreign:
        raise TransferError(
            f"the successor roadmap cites plan(s) {foreign} that do not exist on predecessor "
            f"objective {request.predecessor_id} (its plans: {sorted(node_by_plan)})",
            error_type="prefix_mismatch",
        )

    # Open-PR facts + branches via direct reads (the D5 gates need every predecessor plan).
    open_pr: dict[str, int] = {}
    branch_by_plan: dict[str, str] = {}
    for plan_id in sorted(node_by_plan):
        state = seams.issues.get_plan(issue_id=plan_id)
        if state is None:
            if plan_id in cited:
                raise TransferError(
                    f"the successor roadmap carries plan #{plan_id}, which does not exist",
                    error_type="prefix_mismatch",
                )
            continue
        branch = state.header.get("branch")
        branch_by_plan[plan_id] = (
            branch if isinstance(branch, str) and branch else (f"plan-{plan_id}")
        )
        pr_ref = state.header.get("pr")
        if pr_ref is None:
            continue
        if not isinstance(pr_ref, str) or not pr_ref.strip():
            raise TransferError(
                f"plan #{plan_id} has malformed PR metadata {pr_ref!r}; refusing because "
                "the conversion cannot prove that no PR exists",
                error_type="pr_exists",
            )
        try:
            pr_number = int(_bare(pr_ref))
        except ValueError as exc:
            raise TransferError(
                f"plan #{plan_id} has malformed PR metadata {pr_ref!r}; refusing because "
                "the conversion cannot prove that no PR exists",
                error_type="pr_exists",
            ) from exc
        if pr_number <= 0:
            raise TransferError(
                f"plan #{plan_id} has malformed PR metadata {pr_ref!r}; refusing because "
                "the conversion cannot prove that no PR exists",
                error_type="pr_exists",
            )
        facts = transfer.pr_facts(number=pr_number, repo_root=seams.repo_root)
        if facts is not None and facts.state == "OPEN":
            open_pr[plan_id] = pr_number

    dropped_open = sorted(set(open_pr) - set(cited))
    if dropped_open:
        detail = ", ".join(f"plan #{plan_id} (PR #{open_pr[plan_id]})" for plan_id in dropped_open)
        raise TransferError(
            f"the successor roadmap drops predecessor plan(s) with OPEN PRs: {detail} — carry "
            "them forward or close the PRs first",
            error_type="dropped_open_pr",
        )
    carried_open = sorted(set(open_pr) & set(cited))
    if carried_open:
        detail = ", ".join(f"plan #{plan_id} (PR #{open_pr[plan_id]})" for plan_id in carried_open)
        raise TransferError(
            f"an incremental→stacked replan cannot carry plan(s) with existing PRs: {detail} — "
            "an existing remote PR already makes the layer published, so the conversion path "
            "no longer applies",
            error_type="pr_exists",
        )

    # D6 — dirty/active blocking via direct worktree observation + the writer probe.
    probe_ids = sorted(set(cited) | set(open_pr))
    affected_branches = {
        branch_by_plan[plan_id]: plan_id for plan_id in probe_ids if plan_id in branch_by_plan
    }
    dirty = [
        facts
        for facts in transfer.worktree_branches(seams.repo_root)
        if facts.dirty and facts.branch in affected_branches
    ]
    if dirty:
        names = ", ".join(
            f"plan #{affected_branches[facts.branch]} ({facts.branch})" for facts in dirty
        )
        raise TransferError(
            f"affected plan worktrees carry uncommitted changes: {names} — commit or stash "
            "before replanning",
            error_type="dirty_worktree",
        )
    _probe_remote_writers(transfer, probe_ids)

    lineage = _incremental_lineage(transfer.seams, predecessor, run_id=run_id)
    stored_base = predecessor.header.get("base")
    before = TransferBefore(
        predecessor_objective_id=request.predecessor_id,
        base=(
            stored_base
            if isinstance(stored_base, str) and stored_base
            else transfer.trunk(seams.repo_root)
        ),
        delivery=objective.DeliveryPolicy.INCREMENTAL.value,
        delivery_lineage=None,
        claimed_prefix=(),
        carried_unpublished=tuple(
            CarriedPlan(node_id=node_by_plan[plan_id], plan_id=plan_id) for plan_id in cited
        ),
    )
    after = TransferAfter(
        title=request.title,
        prose=request.prose,
        base=request.base,
        delivery=objective.DeliveryPolicy.STACKED.value,
        delivery_lineage=lineage,
        roadmap_nodes=request.roadmap_nodes,
        carry_map=dict(request.carry_map),
    )
    # The non-journaled arm (D1): the append gate requires stored-lineage equality and the
    # predecessor stores none; interruption tolerance is by-construction.
    return TransferPlan(manifest=TransferManifest(before=before, after=after), journaled=False)


def _incremental_lineage(seams: TransferSeams, predecessor: ObjectiveState, *, run_id: str) -> str:
    """The incremental→stacked successor's train identity, rerun-convergent:

    1. a successor already created by THIS run fixes the lineage (a fresh mint mid-convergence
       would fork the train identity: the rerun's identity stamps would diverge from the
       stored successor header and verification would refuse forever);
    2. else a stored predecessor lineage is reused (§8.45 copy-or-mint parity);
    3. else a fresh ULID is minted.
    """
    found = seams.store.find_objective(run_id=run_id)
    if found is not None:
        state = seams.store.get_objective(objective_id=found.id)
        supersedes = state.header.get("supersedes") if state is not None else None
        if (
            state is None
            or not isinstance(supersedes, str)
            or _bare(supersedes) != _bare(predecessor.id)
        ):
            raise TransferError(
                f"objective {found.id} already exists under run {run_id} but does not "
                f"supersede {predecessor.id} — refusing to adopt it as the successor",
                error_type="transfer_incomplete",
            )
        stored = state.header.get("delivery_lineage")
        if isinstance(stored, str) and stored:
            return stored
    stored_lineage = predecessor.header.get("delivery_lineage")
    if isinstance(stored_lineage, str) and stored_lineage:
        return stored_lineage
    return objective.mint_delivery_lineage()


def _probe_remote_writers(transfer: _Transfer, probe_ids: Sequence[str]) -> None:
    """Sync's writer posture verbatim (D6): positively observed writers refuse
    (``active_writer``); an unreadable observation refuses fail-closed
    (``writer_observation_unavailable``) — never \"no writers\"."""
    if not probe_ids:
        return
    try:
        active = transfer.remote_writers.active_plan_ids(list(probe_ids))
    except WriterObservationError as exc:
        raise TransferError(
            f"could not observe the active remote writers ({exc}) — refusing to transfer "
            "under an unreadable writer preflight",
            error_type="writer_observation_unavailable",
        ) from exc
    blocked = sorted(plan_id for plan_id in probe_ids if plan_id in active)
    if blocked:
        names = ", ".join(f"plan #{plan_id}" for plan_id in blocked)
        raise TransferError(
            f"active remote writers hold affected plans: {names} — wait for the runs to "
            "finish before replanning",
            error_type="active_writer",
        )


# ----------------------------------------------------------------- the roll-forward core


def roll_forward_transfer(seams: TransferSeams, *, record: PreparedRecord) -> ObjectiveRef:
    """The lock-ASSUMED conclusion of an unresolved TRANSFER from its recorded manifest:
    create (convergent) → stamp → verify → finalize → complete. Shared by the save's same-run
    rerun and by recover's all-after arm (which already holds the operation lock)."""
    manifest = decode_transfer_record(record)
    return _execute(
        seams,
        manifest,
        run_id=record.run_id,
        operation_id=record.operation_id,
        journaled=True,
    )


def _execute(
    seams: TransferSeams,
    manifest: TransferManifest,
    *,
    run_id: str,
    operation_id: str | None,
    journaled: bool,
) -> ObjectiveRef:
    """Steps create → stamp → verify → finalize → complete (architecture steps 4-9), every
    write convergent/idempotent so a rerun with the same ``run_id`` completes without
    duplicate effects."""
    before = manifest.before
    after = manifest.after
    predecessor_id = _bare(before.predecessor_objective_id)
    successor = seams.store.supersede_objective(
        old_objective_id=predecessor_id,
        title=after.title,
        prose=after.prose,
        run_id=run_id,
        base=after.base,
        roadmap_nodes=list(after.roadmap_nodes),
        carry_map=dict(after.carry_map),
        delivery=(
            objective.DeliveryPolicy.STACKED
            if after.delivery == objective.DeliveryPolicy.STACKED.value
            else None
        ),
        delivery_lineage=after.delivery_lineage,
        close_predecessor=False,
    )
    if successor is None:
        raise TransferError(
            "the configured objective backend does not support superseding — the transfer "
            "cannot proceed",
            error_type="supersede_unsupported",
        )

    for write in _ownership_writes(manifest):
        _apply_ownership(seams, write, successor_id=successor.id, after=after)

    _verify(seams, manifest, successor)

    finalized = seams.store.finalize_supersession(
        old_objective_id=predecessor_id, new_objective_id=successor.id
    )
    if not finalized:
        raise TransferError(
            "the configured objective backend does not support finalizing a supersession — "
            "the transfer cannot proceed",
            error_type="supersede_unsupported",
        )
    if journaled and operation_id is not None:
        seams.persistence.append_outcome(
            predecessor_id,
            OutcomeRecord(
                operation_id=operation_id,
                role=EventRole.COMPLETED,
                created=seams.now(),
                observed={"successor_objective_id": successor.id, "run_id": run_id},
            ),
        )
    return successor


@dataclass(frozen=True)
class _OwnershipWrite:
    """One carried plan's ownership/identity intent, derived from the manifest alone."""

    plan_id: str
    node_id: str  # the NEW node id
    kind: Literal["claimed", "stacked_unpublished", "incremental"]
    predecessor_plan_id: str | None


def _ownership_writes(manifest: TransferManifest) -> tuple[_OwnershipWrite, ...]:
    """Derive every carried plan's writes from the RECORDED manifest (recover has no session
    artifacts): claimed-prefix plans → ownership only; carried-unpublished under a stacked
    successor → ownership + layer identity (predecessor plan id from the successor delivery
    order — explicit null when the layer below is unplanned); carried plans under an
    incremental successor → ownership + the four-field clear."""
    projection = manifest_projection(manifest.after)
    claimed_ids = {_bare(entry.plan_id) for entry in manifest.before.claimed_prefix}
    successor_stacked = manifest.after.delivery == objective.DeliveryPolicy.STACKED.value
    writes: list[_OwnershipWrite] = []
    previous_plan: str | None = None
    for node_id, plan_id in projection:
        if plan_id is not None:
            if plan_id in claimed_ids:
                kind: Literal["claimed", "stacked_unpublished", "incremental"] = "claimed"
                predecessor_plan: str | None = None
            elif successor_stacked:
                kind = "stacked_unpublished"
                predecessor_plan = previous_plan
            else:
                kind = "incremental"
                predecessor_plan = None
            writes.append(
                _OwnershipWrite(
                    plan_id=plan_id,
                    node_id=node_id,
                    kind=kind,
                    predecessor_plan_id=predecessor_plan,
                )
            )
        previous_plan = plan_id
    return tuple(writes)


def _header_value(header: Mapping[str, object], key: str) -> str | None:
    """A plan-header field under the absent ≡ null read rule, junk reading as None (the
    idempotence probe only — a junk value simply re-writes)."""
    value = header.get(key)
    return value if isinstance(value, str) else None


def _apply_ownership(
    seams: TransferSeams, write: _OwnershipWrite, *, successor_id: str, after: TransferAfter
) -> None:
    """Apply one plan's ownership/identity writes, skipping any write whose stored values
    already match (the idempotent rerun — no duplicate header effects)."""
    state = seams.issues.get_plan(issue_id=write.plan_id)
    if state is None:
        raise TransferError(
            f"carried plan #{write.plan_id} does not exist — the successor projection cannot "
            "be materialized",
            error_type="transfer_unverified",
        )
    header = state.header
    owner = _header_value(header, "objective_id")
    node_link = _header_value(header, "objective_node_id")
    if owner is None or _bare(owner) != _bare(successor_id) or node_link != write.node_id:
        seams.persistence.transfer_plan_ownership(
            write.plan_id, objective_id=successor_id, objective_node_id=write.node_id
        )
    if write.kind == "stacked_unpublished":
        lineage = after.delivery_lineage
        if lineage is None:  # unreachable by construction; fail closed
            raise TransferError(
                "a stacked successor manifest carries no delivery_lineage — corrupt manifest",
                error_type="transfer_unverified",
            )
        stored_lineage = _header_value(header, "delivery_lineage")
        stored_predecessor = _header_value(header, "predecessor_plan_id")
        expected_predecessor = write.predecessor_plan_id
        if stored_lineage != lineage or (
            (stored_predecessor and _bare(stored_predecessor)) or None
        ) != ((expected_predecessor and _bare(expected_predecessor)) or None):
            seams.persistence.stamp_layer_identity(
                write.plan_id,
                delivery_lineage=lineage,
                predecessor_plan_id=expected_predecessor,
            )
    elif write.kind == "incremental":
        stacked_fields = (
            _header_value(header, "delivery_lineage"),
            _header_value(header, "predecessor_plan_id"),
            _header_value(header, "parent_checkpoint_sha"),
            _header_value(header, "published_head_sha"),
        )
        if any(value is not None for value in stacked_fields):
            seams.persistence.clear_delivery_metadata(write.plan_id)


# ----------------------------------------------------------------- verification (D12)


def _unverified(detail: str) -> TransferError:
    return TransferError(
        f"the successor projection did not verify: {detail} — the transfer stays unresolved "
        "(predecessor open); repair and rerun, or conclude via "
        "`perk objective stack recover`",
        error_type="transfer_unverified",
    )


def _verify(seams: TransferSeams, manifest: TransferManifest, successor: ObjectiveRef) -> None:
    """The D12 postcondition, split by successor policy — before finalize; failure leaves the
    journal unresolved and the predecessor open (no auto-abandon)."""
    recorded = manifest_projection(manifest.after)
    if manifest.after.delivery == objective.DeliveryPolicy.STACKED.value:
        _verify_stacked(seams, manifest, successor, recorded)
    else:
        _verify_incremental(seams, manifest, successor, recorded)


def _verify_stacked(
    seams: TransferSeams,
    manifest: TransferManifest,
    successor: ObjectiveRef,
    recorded: tuple[tuple[str, str | None], ...],
) -> None:
    try:
        train = seams.reconstruct(seams.repo_root, successor.id)
    except TrainReconstructionError as exc:
        if exc.error_type in ("git_error", "github_error"):
            raise  # infra stays infra (unresolved, recoverable) — never a false unverified
        raise _unverified(f"the successor train cannot be reconstructed ({exc})") from exc
    if isinstance(train, NoDeliveryTrain):
        raise _unverified(
            f"successor {successor.id} reconstructs no delivery train ({train.reason})"
        )
    live = tuple((layer.node_id, layer.plan_id) for layer in train.layers)
    if live != recorded:
        raise _unverified(
            f"the delivery-order projection diverges — recorded {list(recorded)}, observed "
            f"{list(live)} (no missing, extra, or duplicate carry is tolerated)"
        )
    structural = [f for f in train.blockers if f.code in STRUCTURAL_BLOCKER_CODES]
    if structural:
        detail = "; ".join(f"[{f.code}] {f.message}" for f in structural)
        raise _unverified(f"the successor train carries structural blockers: {detail}")
    try:
        claimed = sync.derive_claimed_prefix(train)
    except sync.SyncError as exc:
        raise _unverified(f"the successor's claimed prefix is malformed ({exc})") from exc
    live_claims = tuple(
        (layer.plan_id, layer.branch, layer.parent_checkpoint_sha, layer.published_head_sha)
        for layer in claimed
    )
    recorded_claims = tuple(
        (
            entry.plan_id,
            entry.branch,
            entry.parent_checkpoint_sha,
            entry.published_head_sha,
        )
        for entry in manifest.before.claimed_prefix
    )
    if live_claims != recorded_claims:
        raise _unverified(
            f"the claimed prefix diverges — recorded {list(recorded_claims)}, observed "
            f"{list(live_claims)}"
        )


def _verify_incremental(
    seams: TransferSeams,
    manifest: TransferManifest,
    successor: ObjectiveRef,
    recorded: tuple[tuple[str, str | None], ...],
) -> None:
    """The incremental-successor arm (stacked→incremental; no train exists): direct reads —
    the roadmap rows match the recorded projection and every carried plan re-reads with the
    successor ownership pair and all four stacked fields null. (``before.claimed_prefix`` is
    necessarily empty — D3 forbids the conversion otherwise.)"""
    state = seams.store.get_objective(objective_id=successor.id)
    if state is None:
        raise _unverified(f"successor {successor.id} cannot be read back")
    try:
        order = objective.delivery_order(list(state.nodes))
    except ValueError as exc:
        raise _unverified(f"the successor roadmap has no delivery order ({exc})") from exc
    live = tuple((node.id, _bare(node.pr) if node.pr else None) for node in order)
    if live != recorded:
        raise _unverified(
            f"the roadmap projection diverges — recorded {list(recorded)}, observed {list(live)}"
        )
    for write in _ownership_writes(manifest):
        plan_state = seams.issues.get_plan(issue_id=write.plan_id)
        if plan_state is None:
            raise _unverified(f"carried plan #{write.plan_id} cannot be read back")
        header = plan_state.header
        owner = _header_value(header, "objective_id")
        node_link = _header_value(header, "objective_node_id")
        if owner is None or _bare(owner) != _bare(successor.id) or node_link != write.node_id:
            raise _unverified(
                f"plan #{write.plan_id} records ownership ({owner!r}, {node_link!r}), expected "
                f"({successor.id!r}, {write.node_id!r})"
            )
        for key in (
            "delivery_lineage",
            "predecessor_plan_id",
            "parent_checkpoint_sha",
            "published_head_sha",
        ):
            value = header.get(key)
            if value is not None:
                raise _unverified(
                    f"plan #{write.plan_id} still records {key}={value!r} — every stacked "
                    "field must read back null on an incremental successor"
                )
