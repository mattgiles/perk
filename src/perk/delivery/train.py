"""The immutable ``DeliveryTrain`` projection — the delivery module's read path
(contracts.md §8.44).

Pure orchestration over injected seams: :func:`reconstruct_train` rebuilds one immutable
projection of a stacked objective's delivery train from the durable authorities — the objective
store (policy, lineage, roadmap), the plan issues (layer identity + checkpoints), the journal
fold (unresolved operations), Git refs (branch content), and GitHub PR + native-stack state —
and classifies every discrepancy as a **blocker** or **information** finding whose message
carries the exact expected-vs-observed values.

Failure-posture split (contracts.md §8.44): the stable authorities hard-fail — a failed
objective read, plan join, journal *carrier* read, or ``git fetch`` raises (status cannot
render an honest projection without its authorities) — while the preview native-stack read
degrades to membership ``UNKNOWN`` plus an information finding, and journal *corruption*
becomes a blocker finding rather than an abort. Local worktree/branch absence is never an
error: the projection works from a fresh clone.

No subprocess or gateway imports here — the module depends only on the narrow Protocols it
declares (plus the backend-tier value types); the production wiring lives in
:mod:`perk.delivery.observe`.
"""

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from perk import objective
from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import ObjectiveState
from perk.delivery.journal import JournalCorruptionError, JournalFold, PreparedRecord
from perk.objective import DeliveryPolicy, ObjectiveNode

# The forward supersession walk's depth cap (mirrors the journal chain walk's) — no legitimate
# lineage supersedes itself 50 times; a breach is corruption, never an honest redirect.
_CHAIN_DEPTH_CAP = 50

# The successful no-train explanation for an incremental objective (Decision: incremental is a
# successful answer, not an error).
NO_TRAIN_INCREMENTAL_REASON = "this objective uses incremental delivery; no delivery train exists"


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
    canonical order); ``unplanned`` = no plan backlink yet (fine for future layers)."""

    SKIPPED = "skipped"
    UNPLANNED = "unplanned"
    PLANNED = "planned"


class LayerPublication(StrEnum):
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    PUBLICATION_DRIFT = "publication_drift"


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

    def fetch(self) -> None: ...

    def remote_branch_sha(self, branch: str) -> str | None: ...

    def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool | None:
        """Whether ``ancestor_sha`` is an ancestor of ``head_sha``; ``None`` when the objects
        are unavailable locally (ancestry unknowable — never an error)."""
        ...

    def worktree_branches(self) -> tuple[WorktreeFacts, ...]: ...


class GitHubProbe(Protocol):
    """Read-only GitHub observation. ``pr_facts`` failures are typed ``github_error``s from
    the wiring; ``pr_stack`` is tolerant (``StackView.available=False``)."""

    def pr_facts(self, number: int) -> PrFactsView | None: ...

    def pr_stack(self, number: int) -> StackView: ...


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
class UnresolvedOperationFacts:
    """The first unresolved journal operation (status reports it; mutation gating is the
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
class DeliveryTrain:
    """The immutable projection: layers in canonical delivery order, bottom first."""

    objective_id: str
    objective_url: str
    delivery_lineage: str | None
    base: str
    redirected_from: str | None
    layers: tuple[TrainLayer, ...]
    published_prefix_len: int
    unresolved_operation: UnresolvedOperationFacts | None
    findings: tuple[TrainFinding, ...]

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
    pr_open: bool = False

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
            intent=self.intent,
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


def _resolve_active_objective(
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
    authority (owner / node link / lineage / checkpoints)."""
    plan_owner: dict[str, str] = {}
    for work in layers:
        node = work.node
        if node.pr is None:
            work.intent = LayerIntent.UNPLANNED
            continue
        plan_id = _bare(node.pr)
        work.plan_id = plan_id
        prior = plan_owner.get(plan_id)
        if prior is not None:
            findings.append(
                work.blocker(
                    "duplicate_plan_link",
                    f"nodes {prior} and {node.id} both link plan #{plan_id} — the "
                    "node↔plan↔layer mapping must be bijective",
                )
            )
        else:
            plan_owner[plan_id] = node.id
        plan_state = issues.get_plan(issue_id=plan_id)
        if plan_state is None:
            findings.append(
                work.blocker(
                    "missing_plan",
                    f"node {node.id} links plan #{plan_id}, which does not exist",
                )
            )
            work.branch = f"plan-{plan_id}"
            continue
        work.plan = plan_state
        owner = _plan_header_str(work, "objective_id", findings=findings)
        if owner is not None and _bare(owner) != _bare(active_id):
            findings.append(
                work.blocker(
                    "wrong_owner",
                    f"plan #{plan_id} claims objective {owner} but node {node.id} belongs to "
                    f"objective {active_id}",
                )
            )
        node_link = _plan_header_str(work, "objective_node_id", findings=findings)
        if node_link is not None and node_link != node.id:
            findings.append(
                work.blocker(
                    "node_link_mismatch",
                    f"plan #{plan_id} claims node {node_link} but is linked from node {node.id}",
                )
            )
        work.parent_checkpoint_sha = _plan_header_str(
            work, "parent_checkpoint_sha", findings=findings
        )
        work.published_head_sha = _plan_header_str(work, "published_head_sha", findings=findings)
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
        pr_ref = _plan_header_str(work, "pr", findings=findings)
        if pr_ref is not None:
            try:
                work.pr_number = int(_bare(pr_ref))
            except ValueError:
                findings.append(
                    work.blocker(
                        "malformed_plan_header",
                        f"plan #{plan_id}: header field 'pr' is not a PR number ({pr_ref!r})",
                    )
                )


def _read_unresolved_operation(
    persistence: JournalReader,
    *,
    active_id: str,
    findings: list[TrainFinding],
) -> UnresolvedOperationFacts | None:
    """Fold the journal and surface the first unresolved operation. Journal *corruption* does
    not abort status: it becomes a blocker and the unresolved facts report unknown."""
    try:
        fold = persistence.read_journal(active_id)
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
    if not fold.unresolved:
        return None
    op = fold.unresolved[0]
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
    return UnresolvedOperationFacts(
        operation_id=op.operation_id, kind=op.kind.value, prepared_created=created
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
    """One fetch, then per-layer branch observation: the writer axis from local worktrees and
    the git axis from the remote head vs the recorded checkpoints. Local absence is never an
    error (the fresh-clone promise)."""
    git.fetch()
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
        if work.has_checkpoints:
            findings.append(
                work.blocker(
                    "checkpoint_drift",
                    f"plan #{work.plan_id}: published_head_sha {recorded} is recorded but "
                    f"branch {work.branch!r} has no remote ref",
                )
            )
        return LayerGit.ABSENT
    if parent is not None and git.is_ancestor(parent, remote_sha) is False:
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
    bottom layer) vs observed, and the pr + finalization axes."""
    prev_branch: str | None = None
    for index, work in enumerate(layers):
        work.expected_pr_base = base if index == 0 else prev_branch
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
        facts = github.pr_facts(work.pr_number)
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
        if facts.state == "MERGED":
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
        if work.expected_pr_base is not None and facts.base_ref != work.expected_pr_base:
            work.pr = LayerPr.WRONG_BASE
            findings.append(
                work.blocker(
                    "pr_wrong_base",
                    f"PR #{work.pr_number} has base {facts.base_ref!r} but the train expects "
                    f"{work.expected_pr_base!r}",
                )
            )
        else:
            work.pr = LayerPr.DRAFT if facts.is_draft else LayerPr.READY


def _classify_publication(layers: list[_LayerWork]) -> None:
    """The load-bearing publication definition (pre-membership): checkpoints present AND the
    remote branch at the recorded head AND an open PR at the expected base → ``published``;
    checkpoints with any observation mismatch → ``publication_drift``; checkpoints absent →
    ``unpublished``. The membership corroboration may still downgrade (see
    :func:`_observe_membership`)."""
    for work in layers:
        if not work.has_checkpoints:
            work.publication = LayerPublication.UNPUBLISHED
            continue
        verified = (
            work.published_head_sha is not None
            and work.git is LayerGit.SYNCED
            and work.pr in (LayerPr.DRAFT, LayerPr.READY)
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
    (a single published PR is explicitly not stacked); an unavailable preview read →
    ``unknown`` + information; a missing/divergent stack → blockers, and the affected layers'
    publication downgrades to drift (an exact stack is part of verified publication once two
    or more PRs exist)."""
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
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="stack_read_unavailable",
                message=(
                    "the native-stack read is unavailable (preview API failure) — stack "
                    "membership is unknown"
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


def _published_prefix(layers: list[_LayerWork], *, findings: list[TrainFinding]) -> int:
    """The maximal contiguous published run from the bottom; any published layer above a
    non-published one is a ``prefix_gap`` blocker."""
    prefix = 0
    for work in layers:
        if work.publication is not LayerPublication.PUBLISHED:
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


def reconstruct_train(
    objective_id: str,
    *,
    store: ObjectiveReader,
    issues: PlanReader,
    persistence: JournalReader,
    git: GitProbe,
    github: GitHubProbe,
    trunk: str,
) -> TrainStatus:
    """Reconstruct one immutable :class:`DeliveryTrain` projection (or the
    :class:`NoDeliveryTrain` answer for an incremental objective).

    The architecture's reconstruction pipeline: resolve + redirect forward → policy →
    validate/derive the canonical order → lineage → node↔plan join → journal fold →
    predecessor identity → Git observation → PR observation → publication classification →
    native-stack membership → the published prefix. Raises
    :class:`TrainReconstructionError` only where no honest projection exists; every observable
    conflict is a finding instead.
    """
    state, redirected_from = _resolve_active_objective(store, objective_id)
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

    nodes = list(state.nodes)
    errors = _runtime_roadmap_errors(nodes)
    if errors:
        raise TrainReconstructionError(
            "no canonical delivery order exists: " + "; ".join(errors),
            error_type="invalid_train",
        )
    try:
        order = objective.delivery_order(nodes)
    except ValueError as exc:
        raise TrainReconstructionError(
            f"no canonical delivery order exists: {exc}", error_type="invalid_train"
        ) from exc

    findings: list[TrainFinding] = []
    layers = [_LayerWork(node=node) for node in order]
    if len(layers) == 1:
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="dynamic_singleton",
                message=(
                    f"the train has contracted to a single layer ({layers[0].node.id}); it "
                    "lands as an objective-scoped single PR — native stack membership is "
                    "not applicable"
                ),
                node_id=layers[0].node.id,
            )
        )
    elif not layers:
        findings.append(
            TrainFinding(
                kind=FindingKind.INFO,
                code="all_skipped",
                message="every roadmap node is skipped; the train completes without a merge",
            )
        )

    lineage = _objective_header_str(state.header, "delivery_lineage", objective_id=active_id)
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

    _join_layers(layers, issues=issues, active_id=active_id, lineage=lineage, findings=findings)

    unresolved = (
        _read_unresolved_operation(persistence, active_id=active_id, findings=findings)
        if lineage is not None
        else None  # no lineage to fold against (Decision: report, don't abort)
    )

    _check_predecessors(layers, findings=findings)
    _observe_git(layers, git=git, findings=findings)
    base = _objective_header_str(state.header, "base", objective_id=active_id) or trunk
    _observe_prs(layers, github=github, base=base, findings=findings)
    _classify_publication(layers)
    _observe_membership(layers, github=github, findings=findings)
    prefix = _published_prefix(layers, findings=findings)

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
    )
