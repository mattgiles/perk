"""The internal pure ``DeliveryTrain`` projection (contracts.md §8.44).

The canonical public status entry is :class:`perk.delivery.facade.Delivery`; this module keeps
its fine-grained Protocols and immutable reconstruction pipeline as the pure decision core.
:func:`reconstruct_train` rebuilds one stacked objective's train from durable authorities — the
objective store (policy, lineage, roadmap), plan issues (layer identity + checkpoints), journal
fold (unresolved operations), Git refs (branch content), and GitHub PR + native-stack state —
and classifies every discrepancy as a **blocker** or **information** finding whose message
carries the exact expected-vs-observed values.

Failure-posture split (contracts.md §8.44): the stable authorities hard-fail — a failed
objective read, plan join, journal *carrier* read, or ``git fetch`` raises (status cannot
render an honest projection without its authorities) — while the preview native-stack read
degrades to membership ``UNKNOWN`` plus an information finding (declassifying the affected
layers' publication to drift: unverifiable is never verified), and journal *corruption*
becomes a blocker finding rather than an abort. Local worktree/branch absence is never an
error: the projection works from a fresh clone.

No subprocess or gateway imports here — the module depends only on the narrow Protocols it
declares (plus the backend-tier value types); the production wiring lives in
:mod:`perk.delivery.observe`.
"""

import itertools
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from perk import objective
from perk.backends.issue_backend import PlanState, parse_plan_pr
from perk.backends.objective_store import NativeCancellation, ObjectiveState
from perk.delivery import land_records
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalFold,
    OperationKind,
    PreparedRecord,
)
from perk.objective import DeliveryPolicy, NodeStatus, ObjectiveNode

# The forward supersession walk's depth cap (mirrors the journal chain walk's) — no legitimate
# lineage supersedes itself 50 times; a breach is corruption, never an honest redirect.
_CHAIN_DEPTH_CAP = 50

# The successful no-train explanation for an incremental objective (Decision: incremental is a
# successful answer, not an error).
NO_TRAIN_INCREMENTAL_REASON = "this objective uses incremental delivery; no delivery train exists"

# Reconstruction blockers that impeach the train's identity/topology authority. Mutators and
# workflow gates share this COMPLETE set; unlike sync's historical context-specific list it
# includes ``missing_lineage`` because not every consumer first requires a lineage. The
# cancellation/checkpoint-topology/journal-history codes (§8.54) are structural too — they
# contradict stored identity or append-only history perk cannot repair — EXCEPT the two pending
# codes (`publish_outcome_pending`, `canceled_publication_pending`): a live unresolved PUBLISH
# is concluded through recover / the owning `/submit`, never treated as identity corruption.
STRUCTURAL_BLOCKER_CODES = frozenset(
    {
        "missing_lineage",
        "missing_plan",
        "duplicate_plan_link",
        "wrong_owner",
        "node_link_mismatch",
        "wrong_lineage",
        "lineage_checkpoint_conflict",
        "malformed_plan_header",
        "predecessor_mismatch",
        "journal_corruption",
        "canceled_status_conflict",
        "canceled_plan_unresolved",
        "canceled_published_layer",
        "canceled_remote_work",
        "cancellation_evidence_unavailable",
        "checkpoint_pair_incomplete",
        "checkpoint_prefix_gap",
        "checkpoint_parent_mismatch",
        "missing_publish_outcome",
        "checkpoint_after_abandoned_publish",
    }
)

# The canonical identity/header join findings whose presence on a native-canceled node's plan
# makes the cancellation unsafe (§8.54's exact proof): contraction requires the plan's stored
# identity to positively corroborate before the node may cease to be a layer.
_CANCELLATION_IDENTITY_CODES = frozenset(
    {
        "wrong_owner",
        "node_link_mismatch",
        "wrong_lineage",
        "lineage_checkpoint_conflict",
        "malformed_plan_header",
    }
)


class TrainReconstructionError(Exception):
    """A projection could not be honestly reconstructed. ``error_type`` is the stable machine
    code the CLI maps onto its failure envelope."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # objective_not_found | invalid_delivery_policy | invalid_train
        # | git_error | github_error | supersession_corruption
    ) -> None:
        super().__init__(message)
        self.error_type = error_type


# ----------------------------------------------------------------- the orthogonal layer axes


class LayerIntent(StrEnum):
    """Roadmap intent: ``skipped`` never renders as a layer (skipped nodes contract out of the
    canonical order); ``unplanned`` = no plan backlink yet (fine for future layers);
    ``canceled`` = a native backend cancellation that could NOT be proven safe to contract
    (§8.54) — the node stays a projection-only layer so its evidence cannot disappear."""

    SKIPPED = "skipped"
    UNPLANNED = "unplanned"
    PLANNED = "planned"
    CANCELED = "canceled"


class LayerPublication(StrEnum):
    """``LANDED`` = journal-covered AND corroborated merged (contracts.md §8.44): a completed
    LAND record's prepared⋈completed join names the layer at its exact recorded head, and the
    PR observes MERGED at that head on the layer branch onto a legitimate base. Exactly this
    corroborated arm suppresses the findings the landed state legitimately produces (the
    retarget ``pr_wrong_base``, the deleted-branch ``checkpoint_drift``, native-stack
    membership); a merged PR without coverage keeps today's drift findings."""

    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    PUBLICATION_DRIFT = "publication_drift"
    LANDED = "landed"


class LayerGit(StrEnum):
    UNKNOWN = "unknown"
    ABSENT = "absent"
    SYNCED = "synced"
    REMOTE_AHEAD = "remote_ahead"
    DIVERGED = "diverged"
    WRONG_PARENT = "wrong_parent"


class LayerPr(StrEnum):
    ABSENT = "absent"
    DRAFT = "draft"
    READY = "ready"
    MERGED = "merged"
    CLOSED = "closed"
    WRONG_BASE = "wrong_base"


class LayerMembership(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    ABSENT = "absent"
    EXACT = "exact"
    DIVERGENT = "divergent"


class LayerWriter(StrEnum):
    """The read-only writer axis: is a local worktree checked out on the layer's branch?"""

    FREE = "free"
    ACTIVE = "active"
    DIRTY = "dirty"


class LayerFinalization(StrEnum):
    NOT_MERGED = "not_merged"
    MERGED = "merged"
    FINALIZED = "finalized"


class FindingKind(StrEnum):
    BLOCKER = "blocker"
    INFO = "info"


# ----------------------------------------------------------------- probe view vocabulary
# The pure module owns its observation vocabulary: `observe.py` converts the gateway/substrate
# types into these views, so the pure core never imports `perk.github` types.


@dataclass(frozen=True)
class WorktreeFacts:
    """One local worktree checked out on a branch (``dirty`` = uncommitted changes)."""

    path: str
    branch: str
    dirty: bool


@dataclass(frozen=True)
class PrFactsView:
    """One PR's observed facts. ``state`` is the normalized ``OPEN | CLOSED | MERGED``."""

    number: int
    state: str
    is_draft: bool
    base_ref: str
    head_ref: str
    head_sha: str


@dataclass(frozen=True)
class StackEntryView:
    """One native-stack entry (1-based ``position``, member PR number)."""

    position: int
    pr_number: int


@dataclass(frozen=True)
class BranchPrView:
    """One branch-owned PR observed by head branch, in ANY state (§8.54's cancellation proof:
    a PR in any state — open, closed, or merged — is remote work a native cancellation must
    not orphan). ``state`` is the normalized ``OPEN | CLOSED | MERGED``."""

    number: int
    state: str


@dataclass(frozen=True)
class BaseHeadObservation:
    """The authoritative live objective-base head read (the §8.44 tolerant-degrade arm).

    ``sha`` is the positively observed ``refs/heads/<base>`` head on origin, or ``None`` when
    not positively observed — either the read failed (``failure`` carries the detail) or the
    remote answered and has no such ref (``failure`` is ``None``). Never a raised error: the
    projection stays tolerant where the sync mutator fails closed.
    """

    sha: str | None
    failure: str | None = None


@dataclass(frozen=True)
class StackView:
    """The tolerant native-stack observation. ``available=False`` = the preview read failed
    (membership unknowable); ``available=True, stacked=False`` = genuinely not stacked;
    ``truncated`` = the observed stack has more entries than one page (never exact)."""

    available: bool
    stacked: bool = False
    entries: tuple[StackEntryView, ...] = ()
    truncated: bool = False


# ----------------------------------------------------------------- injected seams


class ObjectiveReader(Protocol):
    """The narrow objective-store surface reconstruction needs."""

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None: ...


class PlanReader(Protocol):
    """The narrow issue-backend surface reconstruction needs."""

    def get_plan(self, *, issue_id: str) -> PlanState | None: ...


class JournalReader(Protocol):
    """The narrow train-persistence surface reconstruction needs (the succession-folding
    read; :class:`perk.delivery.persistence.TrainPersistence` satisfies it)."""

    def read_journal(self, objective_id: str) -> JournalFold: ...


class GitProbe(Protocol):
    """Read-only Git observation. Failures surface as typed
    :class:`TrainReconstructionError` (``git_error``) from the wiring, never raw substrate
    errors."""

    def trunk_branch(self) -> str: ...

    def fetch(self) -> None: ...

    def remote_branch_sha(self, branch: str) -> str | None: ...

    def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool | None:
        """Whether ``ancestor_sha`` is an ancestor of ``head_sha``; ``None`` when the objects
        are unavailable locally (ancestry unknowable — never an error)."""
        ...

    def worktree_branches(self) -> tuple[WorktreeFacts, ...]: ...

    def base_head(self, branch: str) -> BaseHeadObservation:
        """The AUTHORITATIVE live base-head read (ls-remote, never the fetched remote-tracking
        ref — a plain fetch has no ``--prune``, so a deleted remote base leaves a stale
        tracking ref that still resolves). Tolerant: failures degrade into the observation,
        never raise."""
        ...


class GitHubProbe(Protocol):
    """Read-only GitHub observation. ``pr_facts`` and ``pr_for_branch`` failures are typed
    ``github_error``s from the wiring (stable reads — cancellation proof fails closed on an
    unobservable authority); ``pr_stack`` is tolerant (``StackView.available=False``)."""

    def pr_facts(self, number: int) -> PrFactsView | None: ...

    def pr_stack(self, number: int) -> StackView: ...

    def pr_for_branch(self, branch: str) -> BranchPrView | None:
        """The all-state PR lookup by head branch (``None`` = no PR in any state)."""
        ...


# ----------------------------------------------------------------- the projection


@dataclass(frozen=True)
class TrainFinding:
    """One classified discrepancy. ``code`` is a stable machine string; ``message`` always
    embeds the exact expected-vs-observed values (SHAs, bases, ids)."""

    kind: FindingKind
    code: str
    message: str
    node_id: str | None = None
    plan_id: str | None = None


@dataclass(frozen=True)
class ProjectedCancellation:
    """One native cancellation the projection PROVED safe to contract (§8.54): the node
    projects as skipped while its persisted attachment status stays ``persisted_status``.
    Projection-only — nothing here landed or was persisted; `objective doctor --fix` owns the
    narrow persist-the-skip repair for the non-already-skipped subset."""

    node_id: str
    persisted_status: NodeStatus


@dataclass(frozen=True)
class UnresolvedOperationFacts:
    """One unresolved journal operation (status reports them; mutation gating is the
    mutating nodes' concern)."""

    operation_id: str
    kind: str
    prepared_created: str


@dataclass(frozen=True)
class TrainLayer:
    """One layer of the projection, on the architecture's orthogonal axes."""

    node_id: str
    plan_id: str | None
    branch: str | None
    pr_number: int | None
    intent: LayerIntent
    publication: LayerPublication
    git: LayerGit
    pr: LayerPr
    membership: LayerMembership
    writer: LayerWriter
    finalization: LayerFinalization
    parent_checkpoint_sha: str | None
    published_head_sha: str | None
    observed_remote_head_sha: str | None
    observed_pr_base: str | None
    expected_pr_base: str | None


@dataclass(frozen=True)
class BuildReadiness:
    """The derived build-readiness fact of a train (contracts.md §8.46) — never a node status.

    ``next_node_id`` is the first layer in delivery order whose publication is not
    ``PUBLISHED`` (``None`` when every layer is published, or the layer list is
    empty/all-skipped). ``ready`` is fail-closed and train-wide: ``True`` iff a next layer
    exists AND the train carries no BLOCKER findings AND no journal operation is unresolved
    (the contiguous-prefix invariant makes the next layer's predecessor published by
    construction — a violation is already a ``prefix_gap`` blocker and vetoes here).
    ``reason`` is ``None`` when ready; otherwise it embeds the exact veto.
    """

    next_node_id: str | None
    ready: bool
    reason: str | None


@dataclass(frozen=True)
class DeliveryTrain:
    """The immutable projection: layers in canonical delivery order, bottom first.

    ``published_prefix_len`` is the maximal contiguous bottom run of layers that are LANDED
    or verified-published; ``landed_prefix_len`` is the maximal contiguous bottom run of
    LANDED layers (≤ ``published_prefix_len`` by construction)."""

    objective_id: str
    objective_url: str
    delivery_lineage: str | None
    base: str
    redirected_from: str | None
    layers: tuple[TrainLayer, ...]
    published_prefix_len: int
    unresolved_operation: UnresolvedOperationFacts | None
    findings: tuple[TrainFinding, ...]
    build_readiness: BuildReadiness
    # The positively observed objective-base head (defaulted: DeliveryTrain is directly
    # constructed across many tests; None stays the honest "not positively observed" fact).
    observed_base_head_sha: str | None = None
    # ALL unresolved operations in fold order (contracts.md §8.44 detailed status);
    # ``unresolved_operation`` above stays the first element (defaulted for the same
    # direct-construction reason).
    unresolved_operations: tuple[UnresolvedOperationFacts, ...] = ()
    # Native cancellations PROVEN safe to contract (§8.54), in node order, and the
    # non-already-skipped subset `objective doctor --fix` may persist. Projection-only facts
    # (defaulted: DeliveryTrain is directly constructed across many tests).
    projected_canceled_nodes: tuple[ProjectedCancellation, ...] = ()
    repairable_canceled_nodes: tuple[ProjectedCancellation, ...] = ()
    # The landed bottom-contiguous run (defaulted: DeliveryTrain is directly constructed
    # across many tests; 0 stays the honest "nothing landed" fact).
    landed_prefix_len: int = 0

    @property
    def blockers(self) -> tuple[TrainFinding, ...]:
        return tuple(f for f in self.findings if f.kind is FindingKind.BLOCKER)

    @property
    def information(self) -> tuple[TrainFinding, ...]:
        return tuple(f for f in self.findings if f.kind is FindingKind.INFO)


@dataclass(frozen=True)
class NoDeliveryTrain:
    """The successful no-train answer (an incremental objective)."""

    objective_id: str
    objective_url: str
    redirected_from: str | None
    reason: str


type TrainStatus = DeliveryTrain | NoDeliveryTrain


# ----------------------------------------------------------------- helpers


def _bare(identifier: str) -> str:
    """Strip one leading ``#`` (the canonical-rendering normalization for id comparisons)."""
    return identifier.removeprefix("#")


def _objective_header_str(
    header: Mapping[str, object],
    key: str,
    *,
    objective_id: str,
    error_type: str = "invalid_train",
) -> str | None:
    """A nullable string objective-header field, fail-closed on junk (a non-string value is
    tampering/corruption territory, never silently coerced)."""
    value = header.get(key)
    if value is None or isinstance(value, str):
        return value
    raise TrainReconstructionError(
        f"objective {objective_id}: header field {key!r} is not a string ({value!r})",
        error_type=error_type,
    )


@dataclass
class _LayerWork:
    """The mutable per-layer working record the pipeline fills, frozen at the end."""

    node: ObjectiveNode
    plan_id: str | None = None
    plan: PlanState | None = None
    branch: str | None = None
    pr_number: int | None = None
    stored_predecessor: str | None = None
    intent: LayerIntent = LayerIntent.PLANNED
    publication: LayerPublication = LayerPublication.UNPUBLISHED
    git: LayerGit = LayerGit.ABSENT
    pr: LayerPr = LayerPr.ABSENT
    membership: LayerMembership = LayerMembership.NOT_APPLICABLE
    writer: LayerWriter = LayerWriter.FREE
    finalization: LayerFinalization = LayerFinalization.NOT_MERGED
    parent_checkpoint_sha: str | None = None
    published_head_sha: str | None = None
    observed_remote_head_sha: str | None = None
    observed_pr_base: str | None = None
    expected_pr_base: str | None = None
    # Journal-covered AND corroborated merged (the §8.44 landed classification) — set by the
    # landed pre-pass; the corroborating PR read is cached so the PR observation never
    # re-reads it.
    landed: bool = False
    cached_pr_facts: "PrFactsView | None" = None
    pr_open: bool = False
    # True while the staged PR's head corroborates the layer branch/head (open PRs only);
    # publication verification requires it.
    pr_head_ok: bool = True
    # An unsafe native cancellation's projection-only ordering surrogate (§8.54): the layer
    # freezes with intent CANCELED; the real persisted status stays in provenance.
    native_canceled: bool = False
    # Idempotent join marker: a work preloaded (and joined) during cancellation classification
    # is never re-joined — its canonical findings were already emitted once.
    joined: bool = False

    @property
    def full_checkpoint_pair(self) -> bool:
        """Both checkpoint fields recorded (the pair is written together — only a full pair is
        a well-formed publication claim; a half-pair is ``checkpoint_pair_incomplete``)."""
        return self.parent_checkpoint_sha is not None and self.published_head_sha is not None

    @property
    def has_checkpoints(self) -> bool:
        """Publication is claimed when either checkpoint is recorded (the pair is written
        together; a half-pair still claims publication and classifies as drift)."""
        return self.parent_checkpoint_sha is not None or self.published_head_sha is not None

    def blocker(self, code: str, message: str) -> TrainFinding:
        return TrainFinding(
            kind=FindingKind.BLOCKER,
            code=code,
            message=message,
            node_id=self.node.id,
            plan_id=self.plan_id,
        )

    def freeze(self) -> TrainLayer:
        return TrainLayer(
            node_id=self.node.id,
            plan_id=self.plan_id,
            branch=self.branch,
            pr_number=self.pr_number,
            intent=LayerIntent.CANCELED if self.native_canceled else self.intent,
            publication=self.publication,
            git=self.git,
            pr=self.pr,
            membership=self.membership,
            writer=self.writer,
            finalization=self.finalization,
            parent_checkpoint_sha=self.parent_checkpoint_sha,
            published_head_sha=self.published_head_sha,
            observed_remote_head_sha=self.observed_remote_head_sha,
            observed_pr_base=self.observed_pr_base,
            expected_pr_base=self.expected_pr_base,
        )


def _pr_no_claim(raw: object) -> bool:
    """``parse_plan_pr``'s no-claim vocabulary (§8.54): absent/null/blank/``"None"``."""
    if raw is None:
        return True
    return isinstance(raw, str) and (not raw.strip() or raw.strip() == "None")


def _plan_header_str(work: _LayerWork, key: str, *, findings: list[TrainFinding]) -> str | None:
    """A nullable string plan-header field — non-string junk is a ``malformed_plan_header``
    blocker (fail-closed *reporting*, not a crash) and reads as absent."""
    if work.plan is None:
        return None
    value = work.plan.header.get(key)
    if value is None or isinstance(value, str):
        return value
    findings.append(
        work.blocker(
            "malformed_plan_header",
            f"plan #{work.plan_id}: header field {key!r} is not a string ({value!r})",
        )
    )
    return None


def resolve_active_objective(
    store: ObjectiveReader, objective_id: str
) -> tuple[ObjectiveState, str | None]:
    """Resolve the requested objective and follow ``superseded_by`` forward to the ACTIVE one
    (cycle guard + depth cap → ``supersession_corruption``). Returns the active state plus the
    originally-requested id when redirected."""
    state = store.get_objective(objective_id=objective_id)
    if state is None:
        raise TrainReconstructionError(
            f"objective {objective_id} not found", error_type="objective_not_found"
        )
    requested_id = state.id
    seen = {_bare(state.id)}
    hops = 0
    while True:
        successor_id = _objective_header_str(
            state.header,
            "superseded_by",
            objective_id=state.id,
            error_type="supersession_corruption",
        )
        if successor_id is None:
            break
        if _bare(successor_id) in seen:
            raise TrainReconstructionError(
                f"supersession cycle at objective {successor_id} "
                f"(walking forward from {requested_id})",
                error_type="supersession_corruption",
            )
        hops += 1
        if hops >= _CHAIN_DEPTH_CAP:
            raise TrainReconstructionError(
                f"supersession chain from objective {requested_id} exceeds the depth cap "
                f"({_CHAIN_DEPTH_CAP})",
                error_type="supersession_corruption",
            )
        successor = store.get_objective(objective_id=successor_id)
        if successor is None:
            raise TrainReconstructionError(
                f"objective {state.id} is superseded by {successor_id}, which does not exist",
                error_type="supersession_corruption",
            )
        seen.add(_bare(successor_id))
        state = successor
    redirected_from = requested_id if state.id != requested_id else None
    return state, redirected_from


def _runtime_roadmap_errors(nodes: list[ObjectiveNode]) -> list[str]:
    """The structural roadmap errors, with the 2-100 authoring bounds filtered out — runtime
    never enforces the authoring bound (a dynamic singleton / all-skipped train is a lifecycle
    fact, classified as information). Both bound messages start with the filtered prefix."""
    return [
        error
        for error in objective.validate_stacked_roadmap(nodes)
        if not error.startswith("a stacked delivery train")
    ]


def _join_layers(
    layers: list[_LayerWork],
    *,
    issues: PlanReader,
    active_id: str,
    lineage: str | None,
    findings: list[TrainFinding],
) -> None:
    """Join each ordered node to its plan and corroborate the plan header against the roadmap
    authority (owner / node link / lineage / checkpoints). Idempotent per work: a layer
    preloaded during cancellation classification (``joined=True``) is skipped — its canonical
    findings were already emitted once. Duplicate backlinks are the pre-contraction global
    scan's concern (:func:`_scan_duplicate_backlinks`), not the join's."""
    for work in layers:
        _join_layer(work, issues=issues, active_id=active_id, lineage=lineage, findings=findings)


def _join_layer(
    work: _LayerWork,
    *,
    issues: PlanReader,
    active_id: str,
    lineage: str | None,
    findings: list[TrainFinding],
) -> None:
    """Join ONE node to its plan (the idempotent plan/header loader both normal layers and the
    cancellation preload share — §8.54)."""
    if work.joined:
        return
    work.joined = True
    node = work.node
    if node.pr is None:
        work.intent = LayerIntent.UNPLANNED
        return
    plan_id = _bare(node.pr)
    work.plan_id = plan_id
    plan_state = issues.get_plan(issue_id=plan_id)
    if plan_state is None:
        findings.append(
            work.blocker(
                "missing_plan",
                f"node {node.id} links plan #{plan_id}, which does not exist",
            )
        )
        work.branch = f"plan-{plan_id}"
        return
    work.plan = plan_state
    # Ownership identity is corroborated fail-closed: ABSENT is a conflict too — a
    # node-linked plan always carries these (only lineage gets the pre-publication
    # absence exception below).
    owner = _plan_header_str(work, "objective_id", findings=findings)
    if owner is None:
        findings.append(
            work.blocker(
                "wrong_owner",
                f"plan #{plan_id} records no objective_id but node {node.id} belongs to "
                f"objective {active_id}",
            )
        )
    elif _bare(owner) != _bare(active_id):
        findings.append(
            work.blocker(
                "wrong_owner",
                f"plan #{plan_id} claims objective {owner} but node {node.id} belongs to "
                f"objective {active_id}",
            )
        )
    node_link = _plan_header_str(work, "objective_node_id", findings=findings)
    if node_link is None:
        findings.append(
            work.blocker(
                "node_link_mismatch",
                f"plan #{plan_id} records no objective_node_id but is linked from node {node.id}",
            )
        )
    elif node_link != node.id:
        findings.append(
            work.blocker(
                "node_link_mismatch",
                f"plan #{plan_id} claims node {node_link} but is linked from node {node.id}",
            )
        )
    work.parent_checkpoint_sha = _plan_header_str(work, "parent_checkpoint_sha", findings=findings)
    work.published_head_sha = _plan_header_str(work, "published_head_sha", findings=findings)
    if (work.parent_checkpoint_sha is None) != (work.published_head_sha is None):
        # The checkpoint pair is written together in ONE update — a half-pair is broken
        # stored state, never a legitimate mid-write snapshot.
        present, absent = (
            ("parent_checkpoint_sha", "published_head_sha")
            if work.parent_checkpoint_sha is not None
            else ("published_head_sha", "parent_checkpoint_sha")
        )
        findings.append(
            work.blocker(
                "checkpoint_pair_incomplete",
                f"plan #{plan_id} records {present} but no {absent} — the checkpoint "
                "pair is written together only after publication verification",
            )
        )
    plan_lineage = _plan_header_str(work, "delivery_lineage", findings=findings)
    if plan_lineage is not None and lineage is not None and plan_lineage != lineage:
        findings.append(
            work.blocker(
                "wrong_lineage",
                f"plan #{plan_id} carries delivery_lineage {plan_lineage!r} but objective "
                f"{active_id} carries {lineage!r}",
            )
        )
    elif plan_lineage is None and work.has_checkpoints:
        # Absent lineage is legal pre-publication; checkpoints without a lineage are not.
        findings.append(
            work.blocker(
                "lineage_checkpoint_conflict",
                f"plan #{plan_id} records publication checkpoints but no delivery_lineage "
                "— checkpoints cannot precede layer identity",
            )
        )
    work.stored_predecessor = _plan_header_str(work, "predecessor_plan_id", findings=findings)
    branch = _plan_header_str(work, "branch", findings=findings)
    work.branch = branch if branch is not None else f"plan-{plan_id}"
    # The raw value goes straight to the shared tolerant parser (§8.54) — a positive integer
    # is a valid claim, so it must never detour through the string-only helper first.
    raw_pr = work.plan.header.get("pr") if work.plan is not None else None
    resolved_pr = parse_plan_pr(raw_pr)
    if resolved_pr is not None:
        work.pr_number = resolved_pr
    elif not _pr_no_claim(raw_pr):
        # Absent/blank/"None" is the parser's no-claim vocabulary; anything else that fails
        # to resolve is malformed stored state (reported, raw preserved).
        findings.append(
            work.blocker(
                "malformed_plan_header",
                f"plan #{plan_id}: header field 'pr' is not a PR number ({raw_pr!r})",
            )
        )


def _fold_journal(
    persistence: JournalReader,
    *,
    active_id: str,
    findings: list[TrainFinding],
) -> JournalFold | None:
    """Fold the succession journal ONCE (unresolved facts, PUBLISH coverage, and cancellation
    evidence all read it). Journal *corruption* does not abort status: it becomes a blocker,
    the fold reads ``None``, and every fold consumer fails its question closed (unresolved
    facts unknown; planned cancellation unprovable; coverage unclassifiable)."""
    try:
        return persistence.read_journal(active_id)
    except JournalCorruptionError as exc:
        findings.append(
            TrainFinding(
                kind=FindingKind.BLOCKER,
                code="journal_corruption",
                message=(
                    f"the operation journal is corrupt ({exc}); unresolved-operation facts "
                    "are unknown"
                ),
            )
        )
        return None


def _surface_unresolved(
    fold: JournalFold | None, *, findings: list[TrainFinding]
) -> tuple[UnresolvedOperationFacts, ...]:
    """Surface EVERY unresolved operation in fold order (each becomes an ``active_operation``
    INFO finding)."""
    if fold is None:
        return ()
    facts: list[UnresolvedOperationFacts] = []
    for op in fold.unresolved:
        record = op.prepared.record
        created = record.created if isinstance(record, PreparedRecord) else op.prepared.created_at
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="active_operation",
                message=(
                    f"operation {op.operation_id} ({op.kind.value}, prepared {created}) is "
                    "unresolved — recover or abandon it before the next train mutation"
                ),
            )
        )
        facts.append(
            UnresolvedOperationFacts(
                operation_id=op.operation_id, kind=op.kind.value, prepared_created=created
            )
        )
    return tuple(facts)


def _scan_duplicate_backlinks(
    nodes: list[ObjectiveNode], *, findings: list[TrainFinding]
) -> set[str]:
    """The pre-contraction global duplicate-backlink scan (§8.54): EVERY roadmap node's plan
    backlink participates — including skipped and native-canceled nodes, whose duplicates the
    old layer-only join could silently contract away. Returns the ids of every node involved
    in a duplicate (a native cancellation involving one is never safe to contract)."""
    plan_owner: dict[str, str] = {}
    duplicated: set[str] = set()
    for node in nodes:
        if node.pr is None:
            continue
        plan_id = _bare(node.pr)
        prior = plan_owner.get(plan_id)
        if prior is None:
            plan_owner[plan_id] = node.id
            continue
        findings.append(
            TrainFinding(
                kind=FindingKind.BLOCKER,
                code="duplicate_plan_link",
                message=(
                    f"nodes {prior} and {node.id} both link plan #{plan_id} — the "
                    "node↔plan↔layer mapping must be bijective"
                ),
                node_id=node.id,
                plan_id=plan_id,
            )
        )
        duplicated.add(prior)
        duplicated.add(node.id)
    return duplicated


@dataclass(frozen=True)
class _PublishHistory:
    """One plan's folded PUBLISH history (total precedence: completed > unresolved >
    abandoned > absent). Other operation kinds never substitute for PUBLISH."""

    completed: tuple[str, ...]
    unresolved: tuple[str, ...]
    abandoned: tuple[str, ...]


def _publish_history(fold: JournalFold, plan_id: str) -> _PublishHistory:
    """Every PUBLISH operation whose ``affected_plans`` names ``plan_id``, split by outcome."""
    completed: list[str] = []
    unresolved: list[str] = []
    abandoned: list[str] = []
    for op in fold.operations.values():
        if op.kind is not OperationKind.PUBLISH:
            continue
        record = op.prepared.record
        if not isinstance(record, PreparedRecord) or plan_id not in record.affected_plans:
            continue
        if op.terminal_role is EventRole.COMPLETED:
            completed.append(op.operation_id)
        elif op.terminal_role is EventRole.ABANDONED:
            abandoned.append(op.operation_id)
        else:
            unresolved.append(op.operation_id)
    return _PublishHistory(
        completed=tuple(completed), unresolved=tuple(unresolved), abandoned=tuple(abandoned)
    )


def _check_publish_coverage(
    layers: list[_LayerWork], fold: JournalFold | None, *, findings: list[TrainFinding]
) -> None:
    """Journal coverage of every checkpoint claim (§8.54): a checkpoint pair may only exist
    because a PUBLISH operation completed, so each checkpoint-claiming plan's PUBLISH history
    classifies with total precedence — any completed match satisfies coverage (older abandoned
    / newer unresolved attempts notwithstanding; unresolved ones still ride
    ``active_operation``); otherwise an unresolved match is the pending
    ``publish_outcome_pending``; otherwise abandoned-only is
    ``checkpoint_after_abandoned_publish``; otherwise ``missing_publish_outcome``. A ``None``
    fold (missing lineage / corruption) already carries its own blocker — coverage never
    guesses on unavailable evidence."""
    if fold is None:
        return
    for work in layers:
        if not work.has_checkpoints or work.plan_id is None:
            continue
        history = _publish_history(fold, work.plan_id)
        if history.completed:
            continue
        if history.unresolved:
            findings.append(
                work.blocker(
                    "publish_outcome_pending",
                    f"plan #{work.plan_id} records publication checkpoints while PUBLISH "
                    f"operation {history.unresolved[0]} is unresolved — conclude it via "
                    "`perk objective stack recover` or the owning `/submit`",
                )
            )
        elif history.abandoned:
            findings.append(
                work.blocker(
                    "checkpoint_after_abandoned_publish",
                    f"plan #{work.plan_id} records publication checkpoints but its only "
                    f"journaled PUBLISH history is abandoned ({', '.join(history.abandoned)}) "
                    "— checkpoints cannot outlive an abandoned publication",
                )
            )
        else:
            findings.append(
                work.blocker(
                    "missing_publish_outcome",
                    f"plan #{work.plan_id} records publication checkpoints but the journal "
                    "folds no PUBLISH operation affecting it — append-only history is "
                    "missing its publication evidence",
                )
            )


def _check_checkpoint_topology(layers: list[_LayerWork], *, findings: list[TrainFinding]) -> None:
    """Stored checkpoint-claim topology (§8.54) — header-derived, distinct from the remote
    ``checkpoint_drift`` observation and the verified-publication ``prefix_gap``:
    ``checkpoint_prefix_gap`` for a claim above a layer without a FULL pair, and
    ``checkpoint_parent_mismatch`` for adjacent full claims whose child parent checkpoint
    differs from the predecessor's published head."""
    for index, work in enumerate(layers):
        if not work.has_checkpoints:
            continue
        below = next((w for w in layers[:index] if not w.full_checkpoint_pair), None)
        if below is not None:
            findings.append(
                work.blocker(
                    "checkpoint_prefix_gap",
                    f"plan #{work.plan_id} claims publication checkpoints above layer "
                    f"{below.node.id} (plan #{below.plan_id}), which records no full "
                    "checkpoint pair — the claimed prefix must be contiguous from the bottom",
                )
            )
    for prev, work in itertools.pairwise(layers):
        if not (prev.full_checkpoint_pair and work.full_checkpoint_pair):
            continue
        if work.parent_checkpoint_sha != prev.published_head_sha:
            findings.append(
                work.blocker(
                    "checkpoint_parent_mismatch",
                    f"plan #{work.plan_id} records parent_checkpoint_sha "
                    f"{work.parent_checkpoint_sha} but predecessor plan #{prev.plan_id} "
                    f"records published_head_sha {prev.published_head_sha}",
                )
            )


def _classify_cancellations(
    all_nodes: list[ObjectiveNode],
    cancellations: tuple[NativeCancellation, ...],
    *,
    issues: PlanReader,
    active_id: str,
    lineage: str | None,
    fold: JournalFold | None,
    duplicated: set[str],
    git: GitProbe,
    github: GitHubProbe,
    findings: list[TrainFinding],
) -> tuple[dict[str, _LayerWork], tuple[ProjectedCancellation, ...], set[str]]:
    """The exact safe-contraction proof (§8.54). A native-canceled node contracts (projects as
    skipped) ONLY when every applicable predicate positively passes; anything unprovable stays
    a projection-only CANCELED layer with its evidence visible. Failed predicates emit ALL
    applicable findings (never short-circuited). Returns the preloaded per-node works (reused
    by the unsafe layers so canonical findings emit once), the safely projected facts in node
    order, and the unsafe node-id set."""
    node_by_id = {node.id: node for node in all_nodes}
    works: dict[str, _LayerWork] = {}
    projected: list[ProjectedCancellation] = []
    unsafe: set[str] = set()
    for cancellation in cancellations:
        node = node_by_id.get(cancellation.node_id)
        if node is None:  # provenance and roadmap derive from one read — fail closed anyway
            raise TrainReconstructionError(
                f"native-cancellation provenance names unknown node {cancellation.node_id}",
                error_type="invalid_train",
            )
        work = _LayerWork(node=node, native_canceled=True)
        works[node.id] = work
        node_unsafe = False
        persisted = cancellation.persisted_status
        if persisted is NodeStatus.DONE:
            findings.append(
                work.blocker(
                    "canceled_status_conflict",
                    f"node {node.id} is natively canceled but its persisted status is done — "
                    "the cancellation contradicts recorded completion",
                )
            )
            node_unsafe = True
        if node.id in duplicated:
            # The duplicate_plan_link blocker was already emitted by the global scan; a
            # duplicated backlink alone makes the identity unprovable.
            node_unsafe = True
        if node.pr is not None and _canceled_plan_unsafe(
            work,
            issues=issues,
            active_id=active_id,
            lineage=lineage,
            fold=fold,
            git=git,
            github=github,
            findings=findings,
        ):
            node_unsafe = True
        if node_unsafe:
            unsafe.add(node.id)
            continue
        repair = (
            "the persisted status is already skipped — nothing to repair"
            if persisted is NodeStatus.SKIPPED
            else f"persist the skip with `perk objective doctor {active_id} --fix`"
        )
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="canceled_unpublished_projected",
                message=(
                    f"node {node.id} is natively canceled with no publication identity — it "
                    f"projects as skipped (persisted status {persisted.value}; projection "
                    f"only, nothing was persisted); {repair}"
                ),
                node_id=node.id,
                plan_id=work.plan_id,
            )
        )
        projected.append(ProjectedCancellation(node_id=node.id, persisted_status=persisted))
    return works, tuple(projected), unsafe


def _canceled_plan_unsafe(
    work: _LayerWork,
    *,
    issues: PlanReader,
    active_id: str,
    lineage: str | None,
    fold: JournalFold | None,
    git: GitProbe,
    github: GitHubProbe,
    findings: list[TrainFinding],
) -> bool:
    """The plan-backlinked arm of the proof: preload/join the plan once (canonical findings),
    then require — emitting every failure — a resolvable plan, clean identity, no checkpoint
    claim, no raw/resolved PR claim, honest journal evidence with no completed/unresolved
    PUBLISH, no remote branch, and no branch-owned PR in any state."""
    node = work.node
    before = len(findings)
    _join_layer(work, issues=issues, active_id=active_id, lineage=lineage, findings=findings)
    emitted = findings[before:]
    plan_id = work.plan_id
    node_unsafe = False
    if work.plan is None:
        findings.append(
            work.blocker(
                "canceled_plan_unresolved",
                f"node {node.id} is natively canceled but its linked plan #{plan_id} cannot "
                "be resolved — the cancellation is unprovable without the plan authority",
            )
        )
        node_unsafe = True
    if any(f.code in _CANCELLATION_IDENTITY_CODES for f in emitted):
        node_unsafe = True
    header: Mapping[str, object] = work.plan.header if work.plan is not None else {}
    raw_parent = header.get("parent_checkpoint_sha")
    raw_head = header.get("published_head_sha")
    if raw_parent is not None or raw_head is not None:
        findings.append(
            work.blocker(
                "canceled_published_layer",
                f"node {node.id} is natively canceled but plan #{plan_id} records publication "
                f"checkpoints (parent {raw_parent!r}, head {raw_head!r}) — a published layer "
                "never contracts",
            )
        )
        node_unsafe = True
    raw_pr = header.get("pr")
    resolved_pr = work.plan.pr if work.plan is not None else None
    # The shared no-claim vocabulary (§8.54): a blank/"None" header spelling is NOT a PR claim —
    # only a genuine raw claim or a resolved PR blocks the planned cancellation.
    if not _pr_no_claim(raw_pr) or resolved_pr is not None:
        findings.append(
            work.blocker(
                "canceled_remote_work",
                f"node {node.id} is natively canceled but plan #{plan_id} carries a PR claim "
                f"(raw {raw_pr!r}, resolved {resolved_pr!r}) — claimed remote PR work is "
                "never orphaned by contraction",
            )
        )
        node_unsafe = True
    if fold is None:
        # Missing lineage / journal corruption already carry their own blocker; the planned
        # cancellation additionally fails closed — evidence it needs is unavailable.
        findings.append(
            work.blocker(
                "cancellation_evidence_unavailable",
                f"node {node.id} is natively canceled but the lineage/journal evidence is "
                "unavailable — a planned cancellation cannot be proven safe without it",
            )
        )
        node_unsafe = True
    elif plan_id is not None:
        history = _publish_history(fold, plan_id)
        if history.completed:
            findings.append(
                work.blocker(
                    "canceled_published_layer",
                    f"node {node.id} is natively canceled but PUBLISH operation "
                    f"{history.completed[0]} completed for plan #{plan_id} — a published "
                    "layer never contracts",
                )
            )
            node_unsafe = True
        if history.unresolved:
            findings.append(
                work.blocker(
                    "canceled_publication_pending",
                    f"node {node.id} is natively canceled while PUBLISH operation "
                    f"{history.unresolved[0]} for plan #{plan_id} is unresolved — conclude "
                    "it via `perk objective stack recover` or the owning `/submit` first",
                )
            )
            node_unsafe = True
        # Abandoned-only history is acceptable: the existing recovery protocol writes an
        # abandoned outcome only after an exact all-before branch/PR/stack proof.
    branch = work.branch if work.branch is not None else f"plan-{plan_id}"
    remote_sha = git.remote_branch_sha(branch)
    if remote_sha is not None:
        findings.append(
            work.blocker(
                "canceled_remote_work",
                f"node {node.id} is natively canceled but branch {branch!r} exists on the "
                f"remote at {remote_sha} — remote work is never orphaned by contraction",
            )
        )
        node_unsafe = True
    branch_pr = github.pr_for_branch(branch)
    if branch_pr is not None:
        findings.append(
            work.blocker(
                "canceled_remote_work",
                f"node {node.id} is natively canceled but PR #{branch_pr.number} "
                f"({branch_pr.state}) serves branch {branch!r} — remote PR work is never "
                "orphaned by contraction",
            )
        )
        node_unsafe = True
    return node_unsafe


@dataclass(frozen=True)
class _LandCoverageRow:
    """One journal-covered landed-layer claim: the prepared⋈completed join (contracts.md
    §8.44) — the completed layer row joined to its own operation's prepared layer by
    ``pr_number``, carrying the recorded head the current layer's checkpoint must equal."""

    node_id: str
    plan_id: str
    pr_number: int
    head_sha: str
    merge_commit_sha: str


def _land_coverage(
    fold: JournalFold | None, *, findings: list[TrainFinding]
) -> dict[tuple[str, str, int], _LandCoverageRow]:
    """The landed-layer coverage map, computed ONCE per reconstruction from the fold: every
    *completed* LAND operation's prepared⋈completed join, keyed ``(node_id, plan_id,
    pr_number)``. Coverage additionally requires the recorded head to equal the layer's
    ``published_head_sha`` checkpoint — checked at the join site (:func:`_observe_landed`) —
    so PR-number-only matching can never adopt a replanned layer. An undecodable LAND payload
    is the existing ``journal_corruption`` blocker (a corrupt perk-authored record is
    out-of-band-edit territory); that operation contributes no coverage (fail closed)."""
    if fold is None:
        return {}
    coverage: dict[tuple[str, str, int], _LandCoverageRow] = {}
    joins, failures = land_records.join_completed_land_operations(fold)
    for join in joins:
        for row in join.layers:
            coverage[(row.node_id, row.plan_id, row.pr_number)] = _LandCoverageRow(
                node_id=row.node_id,
                plan_id=row.plan_id,
                pr_number=row.pr_number,
                head_sha=row.head_sha,
                merge_commit_sha=row.merge_commit_sha,
            )
    for failure in failures:
        findings.append(
            TrainFinding(
                kind=FindingKind.BLOCKER,
                code="journal_corruption",
                message=(
                    f"a completed LAND record is undecodable ({failure.error}); its layers "
                    "cannot classify as landed"
                ),
            )
        )
    return coverage


def _observe_landed(
    layers: list[_LayerWork],
    coverage: dict[tuple[str, str, int], _LandCoverageRow],
    *,
    github: GitHubProbe,
    base: str,
) -> None:
    """The landed pre-pass (contracts.md §8.44): a journal-covered layer marks ``landed``
    only when the live PR corroborates the recorded merge — MERGED with ``head_sha`` == the
    recorded head (== the layer's ``published_head_sha`` checkpoint), ``head_ref`` == the
    layer branch, and ``base_ref`` ∈ {the predecessor-branch expected base, the objective
    base} (GitHub retargets a dependent PR onto the base when merged branches delete). The
    corroborating read is cached on the work so the PR observation never re-reads it. A
    failed corroboration leaves the layer un-landed — today's drift findings stand (fail
    closed); no coverage → never touched (the scope guard)."""
    if not coverage:
        return
    prev_branch: str | None = None
    for index, work in enumerate(layers):
        expected_base = base if index == 0 else prev_branch
        prev_branch = work.branch
        if work.plan_id is None or work.pr_number is None or work.branch is None:
            continue
        row = coverage.get((work.node.id, work.plan_id, work.pr_number))
        if row is None or work.published_head_sha != row.head_sha:
            # No coverage, or the checkpoint moved past the recorded head (a replanned/
            # republished layer) — never adopted as landed.
            continue
        facts = github.pr_facts(work.pr_number)
        if facts is not None:
            work.cached_pr_facts = facts
        if (
            facts is None
            or facts.state != "MERGED"
            or facts.head_sha != row.head_sha
            or facts.head_ref != work.branch
            or facts.base_ref not in (expected_base, base)
        ):
            continue
        work.landed = True


def _landed_prefix(layers: list[_LayerWork], *, findings: list[TrainFinding]) -> int:
    """The maximal contiguous LANDED run from the bottom; a landed layer above a non-landed
    one keeps its axis value but is the blocker ``landed_prefix_gap`` (deliberately NOT
    structural — recover must still classify; §8.49's ``derive_claimed_prefix`` refuses
    independently)."""
    prefix = 0
    for work in layers:
        if not work.landed:
            break
        prefix += 1
    for work in layers[prefix:]:
        if work.landed:
            findings.append(
                work.blocker(
                    "landed_prefix_gap",
                    f"layer {work.node.id} is landed above a non-landed layer — the landed "
                    "prefix must be contiguous from the bottom",
                )
            )
    return prefix


def _check_landed_finalization(layers: list[_LayerWork], *, findings: list[TrainFinding]) -> None:
    """The ``landed_unfinalized`` INFO (contracts.md §8.44): a landed layer whose
    finalization is not FINALIZED or whose node is non-terminal still needs the idempotent
    finalization convergence — the detail routes to ``perk objective stack recover``."""
    for work in layers:
        if not work.landed:
            continue
        unfinalized = work.finalization is not LayerFinalization.FINALIZED
        non_terminal = work.node.status not in objective.TERMINAL
        if not (unfinalized or non_terminal):
            continue
        detail = []
        if unfinalized:
            detail.append(f"finalization is {work.finalization.value}")
        if non_terminal:
            detail.append(f"node status is {work.node.status.value}")
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="landed_unfinalized",
                message=(
                    f"layer {work.node.id} is landed but not fully finalized "
                    f"({'; '.join(detail)}) — run `perk objective stack recover` to converge "
                    "finalization"
                ),
                node_id=work.node.id,
                plan_id=work.plan_id,
            )
        )


def _check_predecessors(layers: list[_LayerWork], *, findings: list[TrainFinding]) -> None:
    """Derived predecessor plan identity (previous layer in canonical order) vs the stored
    ``predecessor_plan_id`` — stored-absent is legal pre-publication; a differing stored value
    is a blocker carrying both ids."""
    prev_plan_id: str | None = None
    for work in layers:
        stored = work.stored_predecessor
        if stored is not None and (prev_plan_id is None or _bare(stored) != _bare(prev_plan_id)):
            derived = f"plan #{prev_plan_id}" if prev_plan_id is not None else "none (bottom layer)"
            findings.append(
                work.blocker(
                    "predecessor_mismatch",
                    f"plan #{work.plan_id} records predecessor plan #{_bare(stored)} but the "
                    f"canonical order derives {derived}",
                )
            )
        prev_plan_id = work.plan_id


def _observe_git(layers: list[_LayerWork], *, git: GitProbe, findings: list[TrainFinding]) -> None:
    """Per-layer branch observation over the pipeline's single earlier fetch (§8.54 — the
    cancellation stage and the normal layers share one fetch): the writer axis from local
    worktrees and the git axis from the remote head vs the recorded checkpoints. Local absence
    is never an error (the fresh-clone promise)."""
    worktrees = {facts.branch: facts for facts in git.worktree_branches()}
    for work in layers:
        if work.branch is None:
            continue
        local = worktrees.get(work.branch)
        if local is not None:
            work.writer = LayerWriter.DIRTY if local.dirty else LayerWriter.ACTIVE
        remote_sha = git.remote_branch_sha(work.branch)
        work.observed_remote_head_sha = remote_sha
        work.git = _classify_git(work, remote_sha, git=git, findings=findings)


def _classify_git(
    work: _LayerWork,
    remote_sha: str | None,
    *,
    git: GitProbe,
    findings: list[TrainFinding],
) -> LayerGit:
    recorded = work.published_head_sha
    parent = work.parent_checkpoint_sha
    if remote_sha is None:
        # A landed layer's branch deletion at merge is the EXPECTED state — the absent-remote
        # checkpoint_drift is suppressed for exactly the corroborated landed arm (§8.44).
        if work.has_checkpoints and not work.landed:
            findings.append(
                work.blocker(
                    "checkpoint_drift",
                    f"plan #{work.plan_id}: published_head_sha {recorded} is recorded but "
                    f"branch {work.branch!r} has no remote ref",
                )
            )
        return LayerGit.ABSENT
    parent_contained: bool | None = None
    if parent is not None:
        parent_contained = git.is_ancestor(parent, remote_sha)
        if parent_contained is False:
            findings.append(
                work.blocker(
                    "checkpoint_drift",
                    f"plan #{work.plan_id}: branch {work.branch!r} head {remote_sha} does not "
                    f"contain the recorded parent checkpoint {parent}",
                )
            )
            return LayerGit.WRONG_PARENT
    if recorded is None:
        # A remote branch with no recorded publication: nothing to compare against.
        return LayerGit.UNKNOWN
    if remote_sha == recorded:
        # SYNCED requires POSITIVE parent verification: unknowable ancestry (objects
        # unavailable) must never be silently promoted to a verified publication.
        if parent is not None and parent_contained is None:
            return LayerGit.UNKNOWN
        return LayerGit.SYNCED
    findings.append(
        work.blocker(
            "checkpoint_drift",
            f"plan #{work.plan_id}: recorded published_head_sha {recorded} but observed "
            f"branch {work.branch!r} at {remote_sha}",
        )
    )
    ahead = git.is_ancestor(recorded, remote_sha)
    if ahead is True:
        return LayerGit.REMOTE_AHEAD
    if ahead is False:
        return LayerGit.DIVERGED
    return LayerGit.UNKNOWN


def _observe_prs(
    layers: list[_LayerWork],
    *,
    github: GitHubProbe,
    base: str,
    findings: list[TrainFinding],
) -> None:
    """Per-layer PR observation: expected base (predecessor branch; the objective base for the
    bottom layer — landed-aware: the first NON-landed layer above the landed prefix expects
    the objective base, GitHub's retarget target) vs observed — checked for EVERY observed
    PR, including merged/closed ones (a layer merged into the wrong target is the conflict
    most worth surfacing), with the retarget ``pr_wrong_base`` suppressed for exactly the
    corroborated landed arm — plus the PR head corroboration (the staged PR must actually
    serve the layer branch/head) and the pr + finalization axes."""
    landed_prefix = 0
    for work in layers:
        if not work.landed:
            break
        landed_prefix += 1
    prev_branch: str | None = None
    for index, work in enumerate(layers):
        work.expected_pr_base = base if index == 0 or index == landed_prefix else prev_branch
        prev_branch = work.branch
        if work.pr_number is None:
            if work.has_checkpoints:
                findings.append(
                    work.blocker(
                        "missing_pr",
                        f"plan #{work.plan_id} records publication checkpoints "
                        f"(published_head_sha {work.published_head_sha}) but stages no PR",
                    )
                )
            continue
        facts = (
            work.cached_pr_facts
            if work.cached_pr_facts is not None
            else github.pr_facts(work.pr_number)
        )
        if facts is None:
            if work.has_checkpoints:
                findings.append(
                    work.blocker(
                        "missing_pr",
                        f"plan #{work.plan_id} stages PR #{work.pr_number}, which does not "
                        "exist on GitHub, while its checkpoints claim publication",
                    )
                )
            continue
        work.observed_pr_base = facts.base_ref
        base_mismatch = (
            work.expected_pr_base is not None
            and facts.base_ref != work.expected_pr_base
            # The landed retarget arm (base_ref == train.base) is legitimate — suppressed
            # for exactly the corroborated landed classification (§8.44).
            and not work.landed
        )
        if base_mismatch:
            findings.append(
                work.blocker(
                    "pr_wrong_base",
                    f"PR #{work.pr_number} has base {facts.base_ref!r} but the train expects "
                    f"{work.expected_pr_base!r}",
                )
            )
        if facts.state == "MERGED":
            # The terminal state is preserved on the axis; the base conflict (a layer merged
            # into the wrong target) was already surfaced above.
            work.pr = LayerPr.MERGED
            plan_closed = work.plan is not None and work.plan.state == "CLOSED"
            work.finalization = (
                LayerFinalization.FINALIZED if plan_closed else LayerFinalization.MERGED
            )
            continue
        if facts.state == "CLOSED":
            work.pr = LayerPr.CLOSED
            findings.append(
                work.blocker(
                    "pr_closed",
                    f"PR #{work.pr_number} (node {work.node.id}) is closed without merging",
                )
            )
            continue
        work.pr_open = True
        # Corroborate the PR's HEAD against the layer: the staged PR must serve the layer
        # branch (and, once observed/published, its head commit) — a PR for some other
        # branch/content never counts as this layer's publication.
        head_reference = work.observed_remote_head_sha or work.published_head_sha
        if work.branch is not None and facts.head_ref != work.branch:
            work.pr_head_ok = False
            findings.append(
                work.blocker(
                    "pr_wrong_head",
                    f"PR #{work.pr_number} has head {facts.head_ref!r} but layer "
                    f"{work.node.id} publishes branch {work.branch!r}",
                )
            )
        elif head_reference is not None and facts.head_sha != head_reference:
            work.pr_head_ok = False
            findings.append(
                work.blocker(
                    "pr_wrong_head",
                    f"PR #{work.pr_number} head is at {facts.head_sha} but the layer's "
                    f"observed/recorded head is {head_reference}",
                )
            )
        if base_mismatch:
            work.pr = LayerPr.WRONG_BASE
        else:
            work.pr = LayerPr.DRAFT if facts.is_draft else LayerPr.READY


def _classify_publication(layers: list[_LayerWork]) -> None:
    """The load-bearing publication definition (pre-membership): the FULL checkpoint pair
    present (the pair is written together — a half-pair is drift, never publication) AND the
    remote branch verified at the recorded head (``synced`` implies positive parent ancestry)
    AND an open PR at the expected base serving the layer head → ``published``; checkpoints
    with any observation mismatch → ``publication_drift``; checkpoints absent →
    ``unpublished``. The membership corroboration may still downgrade (see
    :func:`_observe_membership`)."""
    for work in layers:
        if work.landed:
            # Journal-covered + corroborated merged (§8.44) — the landed pre-pass proved it.
            work.publication = LayerPublication.LANDED
            continue
        if not work.has_checkpoints:
            work.publication = LayerPublication.UNPUBLISHED
            continue
        verified = (
            work.parent_checkpoint_sha is not None
            and work.published_head_sha is not None
            and work.git is LayerGit.SYNCED
            and work.pr in (LayerPr.DRAFT, LayerPr.READY)
            and work.pr_head_ok
        )
        work.publication = (
            LayerPublication.PUBLISHED if verified else LayerPublication.PUBLICATION_DRIFT
        )


def _observe_membership(
    layers: list[_LayerWork],
    *,
    github: GitHubProbe,
    findings: list[TrainFinding],
) -> None:
    """Native-stack membership over the published open PRs. Fewer than two → not applicable
    (a single published PR is explicitly not stacked); a missing/divergent stack → blockers.
    Once ≥2 published PRs exist, verified ``exact``/``not_applicable`` membership is part of
    the publication definition — so ``unknown`` (the tolerant preview-read failure, an
    information finding, never a blocker), ``absent``, and ``divergent`` all declassify the
    affected layers to ``publication_drift``: unverifiable membership never counts as fully
    published."""
    participants = [
        work
        for work in layers
        if work.has_checkpoints and work.pr_number is not None and work.pr_open
    ]
    if len(participants) < 2:
        return
    expected = [work.pr_number for work in participants if work.pr_number is not None]
    bottom = expected[0]
    view = github.pr_stack(bottom)
    if not view.available:
        for work in participants:
            work.membership = LayerMembership.UNKNOWN
            if work.publication is LayerPublication.PUBLISHED:
                work.publication = LayerPublication.PUBLICATION_DRIFT
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="stack_read_unavailable",
                message=(
                    "the native-stack read is unavailable (preview API failure) — stack "
                    "membership is unknown, so the affected layers classify as "
                    "publication_drift until membership is verifiable"
                ),
            )
        )
        return
    if not view.stacked:
        for work in participants:
            work.membership = LayerMembership.ABSENT
            work.publication = LayerPublication.PUBLICATION_DRIFT
        findings.append(
            TrainFinding(
                kind=FindingKind.BLOCKER,
                code="stack_missing",
                message=(
                    f"{len(participants)} published PRs expect a native stack of "
                    f"{expected} bottom→top, but PR #{bottom} belongs to no stack"
                ),
            )
        )
        return
    entries = sorted(view.entries, key=lambda entry: entry.position)
    observed = [entry.pr_number for entry in entries]
    positions = [entry.position for entry in entries]
    contiguous = all(b == a + 1 for a, b in itertools.pairwise(positions))
    exact = observed == expected and contiguous and not view.truncated
    if exact:
        for work in participants:
            work.membership = LayerMembership.EXACT
        return
    for work in participants:
        work.membership = LayerMembership.DIVERGENT
        work.publication = LayerPublication.PUBLICATION_DRIFT
    truncated_note = " (stack truncated beyond 100 entries)" if view.truncated else ""
    findings.append(
        TrainFinding(
            kind=FindingKind.BLOCKER,
            code="stack_divergent",
            message=(
                f"native stack diverges: expected PRs {expected} bottom→top, observed "
                f"{observed}{truncated_note}"
            ),
        )
    )


def _observe_base(
    layers: list[_LayerWork],
    prefix: int,
    *,
    git: GitProbe,
    base: str,
    objective_id: str,
    findings: list[TrainFinding],
) -> str | None:
    """The authoritative objective-base head observation (contracts.md §8.44).

    Tolerant-degrade (the mutator fails closed where status stays tolerant): an unobserved
    base — read failed OR ref absent — is an INFO ``base_unobserved`` finding naming which
    arm fired. A positively observed head differing from the published bottom layer's
    ``parent_checkpoint_sha`` is the INFO ``base_advanced`` finding carrying both SHAs and
    the remediation (``perk objective stack sync <N> --base``).
    """
    observation = git.base_head(base)
    if observation.sha is None:
        arm = (
            f"the ls-remote read failed ({observation.failure})"
            if observation.failure is not None
            else f"origin has no refs/heads/{base}"
        )
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="base_unobserved",
                message=f"the objective base {base!r} was not positively observed — {arm}",
            )
        )
        return None
    if prefix >= 1:
        bottom = layers[0]
        anchored = bottom.parent_checkpoint_sha
        if anchored is not None and observation.sha != anchored:
            findings.append(
                TrainFinding(
                    kind=FindingKind.INFO,
                    code="base_advanced",
                    message=(
                        f"the objective base {base!r} has advanced to {observation.sha}; the "
                        f"published train is anchored at {anchored} — cascade with "
                        f"`perk objective stack sync {objective_id} --base`"
                    ),
                    node_id=bottom.node.id,
                    plan_id=bottom.plan_id,
                )
            )
    return observation.sha


def _published_prefix(layers: list[_LayerWork], *, findings: list[TrainFinding]) -> int:
    """The maximal contiguous LANDED-or-verified-published run from the bottom (the §8.44
    redefinition — a landed layer satisfies the prefix); any published layer above the run is
    a ``prefix_gap`` blocker (a landed layer above it emits ``landed_prefix_gap`` from the
    landed contiguity check instead — never both)."""
    satisfied = (LayerPublication.PUBLISHED, LayerPublication.LANDED)
    prefix = 0
    for work in layers:
        if work.publication not in satisfied:
            break
        prefix += 1
    for work in layers[prefix:]:
        if work.publication is LayerPublication.PUBLISHED:
            findings.append(
                work.blocker(
                    "prefix_gap",
                    f"layer {work.node.id} is published above a non-published layer — the "
                    "published prefix must be contiguous from the bottom",
                )
            )
    return prefix


def _build_readiness(
    layers: list[_LayerWork],
    *,
    unresolved: UnresolvedOperationFacts | None,
    findings: list[TrainFinding],
) -> BuildReadiness:
    """Derive the train's build readiness (contracts.md §8.46). Pure derivation over the
    already-classified layers/findings — no axis or status is mutated. Vetoes are
    deliberately conservative and fail-closed: ANY blocker or ANY unresolved operation blocks
    the whole train, and the blocked answer carries the exact findings."""
    next_node_id = next(
        (
            work.node.id
            for work in layers
            if work.publication not in (LayerPublication.PUBLISHED, LayerPublication.LANDED)
        ),
        None,
    )
    if next_node_id is None:
        reason = (
            "all layers published or landed"
            if layers
            else "the train has no layers (all skipped/empty)"
        )
        return BuildReadiness(next_node_id=None, ready=False, reason=reason)
    blockers = [f for f in findings if f.kind is FindingKind.BLOCKER]
    if blockers:
        detail = "; ".join(f"[{f.code}] {f.message}" for f in blockers)
        return BuildReadiness(
            next_node_id=next_node_id,
            ready=False,
            reason=f"the train has blocker findings: {detail}",
        )
    if unresolved is not None:
        return BuildReadiness(
            next_node_id=next_node_id,
            ready=False,
            reason=(
                f"operation {unresolved.operation_id} ({unresolved.kind}, prepared "
                f"{unresolved.prepared_created}) is unresolved — recover or abandon it first"
            ),
        )
    return BuildReadiness(next_node_id=next_node_id, ready=True, reason=None)


def reconstruct_train(
    objective_id: str,
    *,
    store: ObjectiveReader,
    issues: PlanReader,
    persistence: JournalReader,
    git: GitProbe,
    github: GitHubProbe,
) -> TrainStatus:
    """Reconstruct one immutable :class:`DeliveryTrain` projection (or the
    :class:`NoDeliveryTrain` answer for an incremental objective).

    The architecture's reconstruction pipeline (§8.54's crash-window-honest ordering):
    resolve + redirect forward → policy → lineage + journal fold → the global duplicate
    scan → ONE Git fetch → native-cancellation classification (the exact safe-contraction
    proof; unsafe nodes gain projection-only ordering surrogates) → validate/derive the
    canonical order → node↔plan join → PUBLISH coverage + checkpoint topology → predecessor
    identity → Git observation → PR observation → publication classification → native-stack
    membership → the published prefix. Raises :class:`TrainReconstructionError` only where no
    honest projection exists; every observable conflict is a finding instead.
    """
    state, redirected_from = resolve_active_objective(store, objective_id)
    active_id = state.id
    try:
        policy = objective.delivery_policy(state.header)
    except ValueError as exc:
        raise TrainReconstructionError(str(exc), error_type="invalid_delivery_policy") from exc
    if policy is DeliveryPolicy.INCREMENTAL:
        return NoDeliveryTrain(
            objective_id=active_id,
            objective_url=state.url,
            redirected_from=redirected_from,
            reason=NO_TRAIN_INCREMENTAL_REASON,
        )

    findings: list[TrainFinding] = []
    all_nodes = list(state.nodes)

    # Lineage + the succession fold come BEFORE cancellation contraction: planned-cancellation
    # evidence and PUBLISH coverage both read the fold, and a missing/corrupt fold must fail
    # those questions closed rather than silently contract.
    lineage = _objective_header_str(state.header, "delivery_lineage", objective_id=active_id)
    fold: JournalFold | None = None
    if lineage is None:
        findings.append(
            TrainFinding(
                kind=FindingKind.BLOCKER,
                code="missing_lineage",
                message=(
                    f"objective {active_id} has delivery: stacked but no delivery_lineage — "
                    "publication cannot be journaled until a lineage is minted"
                ),
            )
        )
    else:
        fold = _fold_journal(persistence, active_id=active_id, findings=findings)

    duplicated = _scan_duplicate_backlinks(all_nodes, findings=findings)

    # One fetch for the whole projection (the cancellation proof and the normal layer
    # observation share it).
    git.fetch()

    canceled_works: dict[str, _LayerWork] = {}
    projected: tuple[ProjectedCancellation, ...] = ()
    unsafe: set[str] = set()
    if state.native_cancellations:
        canceled_works, projected, unsafe = _classify_cancellations(
            all_nodes,
            tuple(state.native_cancellations),
            issues=issues,
            active_id=active_id,
            lineage=lineage,
            fold=fold,
            duplicated=duplicated,
            git=git,
            github=github,
            findings=findings,
        )

    # Unsafe native cancellations get a projection-only PENDING ordering surrogate (never
    # returned/persisted) so the node stays a layer and its evidence cannot disappear.
    effective_nodes = [
        replace(node, status=NodeStatus.PENDING) if node.id in unsafe else node
        for node in all_nodes
    ]
    errors = _runtime_roadmap_errors(effective_nodes)
    if errors:
        raise TrainReconstructionError(
            "no canonical delivery order exists: " + "; ".join(errors),
            error_type="invalid_train",
        )
    try:
        order = objective.delivery_order(effective_nodes)
    except ValueError as exc:
        raise TrainReconstructionError(
            f"no canonical delivery order exists: {exc}", error_type="invalid_train"
        ) from exc

    layers = [
        canceled_works[node.id] if node.id in canceled_works else _LayerWork(node=node)
        for node in order
    ]
    if len(layers) == 1:
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="dynamic_singleton",
                message=(
                    f"the train projects as a single layer ({layers[0].node.id}); the "
                    "delivery lineage is retained and native stack membership is not "
                    "applicable — status only projects this state and performs no landing"
                ),
                node_id=layers[0].node.id,
            )
        )
    elif not layers:
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="all_skipped",
                message=(
                    "every roadmap node projects as skipped; no layer remains — status only "
                    "projects this state and performs no objective completion"
                ),
            )
        )

    _join_layers(layers, issues=issues, active_id=active_id, lineage=lineage, findings=findings)

    unresolved_all = _surface_unresolved(fold, findings=findings)
    unresolved = unresolved_all[0] if unresolved_all else None

    _check_publish_coverage(layers, fold, findings=findings)
    _check_checkpoint_topology(layers, findings=findings)
    _check_predecessors(layers, findings=findings)
    base = _objective_header_str(state.header, "base", objective_id=active_id) or git.trunk_branch()
    # The landed pre-pass (§8.44) runs BEFORE the Git/PR observation: the corroborated
    # landed marks make the deleted-branch/retarget observations coverage-aware, and the
    # corroborating PR reads are cached so nothing is read twice.
    coverage = _land_coverage(fold, findings=findings)
    _observe_landed(layers, coverage, github=github, base=base)
    _observe_git(layers, git=git, findings=findings)
    _observe_prs(layers, github=github, base=base, findings=findings)
    _classify_publication(layers)
    _observe_membership(layers, github=github, findings=findings)
    _check_landed_finalization(layers, findings=findings)
    landed_prefix = _landed_prefix(layers, findings=findings)
    prefix = _published_prefix(layers, findings=findings)
    observed_base = _observe_base(
        layers, prefix, git=git, base=base, objective_id=active_id, findings=findings
    )
    readiness = _build_readiness(layers, unresolved=unresolved, findings=findings)

    return DeliveryTrain(
        objective_id=active_id,
        objective_url=state.url,
        delivery_lineage=lineage,
        base=base,
        redirected_from=redirected_from,
        layers=tuple(work.freeze() for work in layers),
        published_prefix_len=prefix,
        unresolved_operation=unresolved,
        findings=tuple(findings),
        build_readiness=readiness,
        observed_base_head_sha=observed_base,
        unresolved_operations=unresolved_all,
        projected_canceled_nodes=projected,
        repairable_canceled_nodes=tuple(
            fact for fact in projected if fact.persisted_status is not NodeStatus.SKIPPED
        ),
        landed_prefix_len=landed_prefix,
    )
