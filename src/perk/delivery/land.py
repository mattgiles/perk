"""The pure landing-readiness projection — the dry-run preflight (contracts.md §8.55).

:func:`assess_land_readiness` composes one typed :class:`LandReadiness` from the already
reconstructed :class:`~perk.delivery.train.DeliveryTrain` plus fresh GitHub observations
(per-PR mergeability/review/checks/threads, base merge rules, host stack-API capability) and
the fail-closed remote-writer probe. Composition, never duplication: train blockers,
unresolved operations, and membership are consumed from the projection as-is — only the
landing-specific facts are freshly observed.

Failure posture (§8.55): enrichment failures after a sound reconstruction are fail-closed
BLOCKERS, not aborts — can't-verify ⇒ not-ready, with the rest of the report still rendered.
The raising reads (per-PR readiness, merge rules, the writer probe) embed the exact failure
text in their blocker message; the capability probe is the one declared boolean arm — the
gateway's ``stack_capability`` collapses read failure to ``False`` by design, so unsupported
and unobservable both map to ``stack_capability_unavailable`` without failure detail.
Every positive arm requires positive evidence: absent/``None`` observations block or stay
``None``, never classify as passing.

Capability-evidence limit (§8.55): ``native_stack_capability`` proves only that the host's
GraphQL ``PullRequest`` type exposes the native-stack API surface — NOT per-repository
preview enrollment and NOT ``/merge-async`` availability. Those are observable only at
mutation time and are the landing mutation's failure classification; a READY verdict never
claims more than was observed.

Import direction: this pure core imports only :mod:`perk.delivery.writers` and
:mod:`perk.delivery.train` (never ``sync``/``observe`` — ``observe`` wires *this* module, and
``sync`` imports ``observe``); it never sees ``perk.github`` types — the observation views
below are core-owned, converted by :mod:`perk.delivery.observe`.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal, Protocol

from perk.delivery.train import (
    DeliveryTrain,
    FindingKind,
    LayerMembership,
    LayerPublication,
    LayerWriter,
    TrainFinding,
    TrainLayer,
)
from perk.delivery.writers import RemoteWriterProbe, WriterObservationError

# ----------------------------------------------------------------- observation vocabulary
# Core-owned views: observe.py converts the gateway dataclasses into these, so the pure core
# never imports `perk.github` types (the train.py convention).


@dataclass(frozen=True)
class CheckView:
    """One normalized check context (``outcome`` is the gateway's tri-state)."""

    name: str
    is_required: bool
    outcome: str


@dataclass(frozen=True)
class PrLandView:
    """One PR's fresh landing-readiness observation — the assessed subset of the gateway's
    ``PrLandFacts`` (the rollup aggregate state stays gateway-internal: the gateway consumes
    it for pagination coherence, and the assessment classifies the per-check outcomes plus
    GitHub's ``mergeStateStatus`` aggregate instead)."""

    number: int
    state: str
    is_draft: bool
    base_ref: str
    head_ref: str
    head_sha: str
    mergeable: str
    merge_state_status: str
    review_decision: str | None
    checks: tuple[CheckView, ...]
    unresolved_thread_count: int


@dataclass(frozen=True)
class MergeRulesView:
    """The objective base's direct-merge posture."""

    squash_allowed: bool
    merge_queue_required: bool


class LandObservationError(Exception):
    """A landing-readiness enrichment read failed. The assessment converts it into the
    read-specific fail-closed blocker (``readiness_unobserved`` / ``merge_rules_unobserved``)
    embedding this exact failure text — never an abort, never a pass."""


class LandObservations(Protocol):
    """The fresh GitHub observations the readiness assessment needs (wired by
    :mod:`perk.delivery.observe`)."""

    def pr_readiness(self, number: int) -> PrLandView | None:
        """One PR's fresh readiness facts (``None`` = the PR no longer exists); raises
        :class:`LandObservationError` on any read failure."""
        ...

    def base_merge_rules(self) -> MergeRulesView:
        """The objective base's merge rules; raises :class:`LandObservationError` on any
        read failure."""
        ...

    def stack_capability(self) -> bool:
        """Host-schema evidence that the native-stack API surface exists — the declared
        boolean arm: the gateway collapses read failure to ``False`` (unsupported and
        unobservable are indistinguishable here by design)."""
        ...


# ----------------------------------------------------------------- result types


class LandDisposition(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    NOTHING_TO_LAND = "nothing_to_land"


@dataclass(frozen=True)
class LandLayerReadiness:
    """One train layer's readiness row — honestly nullable: an unassessed row (unpublished
    layer, vanished PR, failed read) carries ``None`` observations, never fabricated ones.
    A LANDED layer's row carries ``landed: true`` with ``assessed: false``-shaped nulls (no
    per-PR readiness read is performed for an already-landed layer)."""

    node_id: str
    plan_id: str | None
    pr_number: int | None
    branch: str | None
    expected_base_ref: str | None
    expected_head_sha: str | None
    base_sha: str | None
    assessed: bool
    observed_state: str | None
    observed_is_draft: bool | None
    observed_base_ref: str | None
    observed_head_ref: str | None
    observed_head_sha: str | None
    mergeable: str | None
    merge_state_status: str | None
    review_decision: str | None
    required_checks_failed: tuple[str, ...]
    required_checks_pending: tuple[str, ...]
    optional_checks_failed: tuple[str, ...]
    unresolved_thread_count: int | None
    landed: bool = False


@dataclass(frozen=True)
class LandPlanLayer:
    """One layer's exact journal evidence for the landing mutation — all non-null (built only
    from fully-verified published layers): ``base_sha`` is the parent checkpoint (the
    incremental diff base), ``head_sha`` the published-head checkpoint."""

    node_id: str
    plan_id: str
    pr_number: int
    base_sha: str
    head_sha: str


@dataclass(frozen=True)
class LandPlan:
    """The dry-run land plan (present only when READY), layers bottom→top."""

    mode: Literal["stack_merge_async", "singleton_squash"]
    merge_method: Literal["squash"]
    top_pr_number: int
    top_head_sha: str
    layers: tuple[LandPlanLayer, ...]


@dataclass(frozen=True)
class LandReadiness:
    """The composed landing-readiness projection (contracts.md §8.55).

    Carries every observation the renderer needs — a consumer never scrapes finding messages
    or re-reads GitHub. ``rules is None`` = unobserved or not consulted (the unobserved arm
    also emits ``merge_rules_unobserved``); ``native_stack_capability is None`` = not
    consulted (singleton/zero-layer). ``plan`` is present only when READY.
    """

    objective_id: str
    objective_url: str
    delivery_lineage: str | None
    base: str
    disposition: LandDisposition
    rules: MergeRulesView | None
    native_stack_capability: bool | None
    layers: tuple[LandLayerReadiness, ...]
    findings: tuple[TrainFinding, ...]
    plan: LandPlan | None

    @property
    def blockers(self) -> tuple[TrainFinding, ...]:
        return tuple(f for f in self.findings if f.kind is FindingKind.BLOCKER)

    @property
    def information(self) -> tuple[TrainFinding, ...]:
        return tuple(f for f in self.findings if f.kind is FindingKind.INFO)


# The land-only finding codes (§8.55's exhaustive enumeration). The public vocabulary is the
# declared union of the §8.44 TrainFinding codes (composed through as-is) and these.
LAND_BLOCKER_CODES = frozenset(
    {
        "unresolved_operation",
        "incomplete_publication",
        "dirty_worktree",
        "active_writer",
        "writer_observation_unavailable",
        "squash_forbidden",
        "queue_required_base",
        "merge_rules_unobserved",
        "stack_capability_unavailable",
        "composition_divergent",
        "readiness_unobserved",
        "pr_missing",
        "pr_not_open",
        "pr_draft",
        "wrong_base",
        "wrong_head_ref",
        "head_moved",
        "pr_conflicting",
        "mergeability_unknown",
        "pr_behind",
        "pr_blocked",
        "merge_state_unknown",
        "required_check_failed",
        "required_check_pending",
        "changes_requested",
        "review_required",
        # The all-LANDED disposition arm's promoted blocker: the train-level
        # `landed_unfinalized` INFO stays informational everywhere else, but an all-landed
        # train with unconverged finalization must read BLOCKED (never NOTHING_TO_LAND —
        # the close arm would otherwise be reachable with unfinalized layers).
        "landed_unfinalized",
    }
)
LAND_INFO_CODES = frozenset({"active_worktree", "optional_check_failed", "unresolved_threads"})


# ----------------------------------------------------------------- helpers


def _blocker(code: str, message: str, *, layer: TrainLayer | None = None) -> TrainFinding:
    return TrainFinding(
        kind=FindingKind.BLOCKER,
        code=code,
        message=message,
        node_id=layer.node_id if layer is not None else None,
        plan_id=layer.plan_id if layer is not None else None,
    )


def _info(code: str, message: str, *, layer: TrainLayer | None = None) -> TrainFinding:
    return TrainFinding(
        kind=FindingKind.INFO,
        code=code,
        message=message,
        node_id=layer.node_id if layer is not None else None,
        plan_id=layer.plan_id if layer is not None else None,
    )


def _unassessed_row(layer: TrainLayer) -> LandLayerReadiness:
    """A row for a layer no fresh read was performed for — expected identity from the train,
    every observation honestly ``None``."""
    return LandLayerReadiness(
        node_id=layer.node_id,
        plan_id=layer.plan_id,
        pr_number=layer.pr_number,
        branch=layer.branch,
        expected_base_ref=layer.expected_pr_base,
        expected_head_sha=layer.published_head_sha,
        base_sha=layer.parent_checkpoint_sha,
        assessed=False,
        observed_state=None,
        observed_is_draft=None,
        observed_base_ref=None,
        observed_head_ref=None,
        observed_head_sha=None,
        mergeable=None,
        merge_state_status=None,
        review_decision=None,
        required_checks_failed=(),
        required_checks_pending=(),
        optional_checks_failed=(),
        unresolved_thread_count=None,
    )


@dataclass(frozen=True)
class _AssessableLayer:
    """One PUBLISHED layer's non-null identity (the §8.46 published-layer definition made
    type-safe: a PUBLISHED layer missing any of these is classified back to
    ``incomplete_publication`` rather than trusted)."""

    layer: TrainLayer
    plan_id: str
    branch: str
    pr_number: int
    expected_base_ref: str
    expected_head_sha: str
    base_sha: str


def _landed_row(layer: TrainLayer) -> LandLayerReadiness:
    """A LANDED layer's row: ``landed: true`` with unassessed nulls — no fresh per-PR
    readiness read is performed for an already-landed layer."""
    return replace(_unassessed_row(layer), landed=True)


def _as_assessable(layer: TrainLayer) -> _AssessableLayer | None:
    if (
        layer.plan_id is None
        or layer.branch is None
        or layer.pr_number is None
        or layer.expected_pr_base is None
        or layer.published_head_sha is None
        or layer.parent_checkpoint_sha is None
    ):
        return None
    return _AssessableLayer(
        layer=layer,
        plan_id=layer.plan_id,
        branch=layer.branch,
        pr_number=layer.pr_number,
        expected_base_ref=layer.expected_pr_base,
        expected_head_sha=layer.published_head_sha,
        base_sha=layer.parent_checkpoint_sha,
    )


def _classify_pr(
    assessable: _AssessableLayer, view: PrLandView, findings: list[TrainFinding]
) -> LandLayerReadiness:
    """One assessed layer's row + its per-PR blockers/information (the step-10 arms).

    The ``merge_state_status`` mapping is deliberately independent of the sibling scalars —
    contradictory observations never pass (a DIRTY aggregate blocks even when ``mergeable``
    says MERGEABLE; a DRAFT aggregate blocks even when ``isDraft`` is false).
    """
    layer = assessable.layer
    if view.state != "OPEN":
        findings.append(
            _blocker("pr_not_open", f"PR #{view.number} is {view.state}, not OPEN", layer=layer)
        )
    if view.is_draft:
        findings.append(_blocker("pr_draft", f"PR #{view.number} is a draft", layer=layer))
    if view.base_ref != assessable.expected_base_ref:
        findings.append(
            _blocker(
                "wrong_base",
                f"PR #{view.number} base is {view.base_ref!r}, expected "
                f"{assessable.expected_base_ref!r}",
                layer=layer,
            )
        )
    if view.head_ref != assessable.branch:
        findings.append(
            _blocker(
                "wrong_head_ref",
                f"PR #{view.number} head ref is {view.head_ref!r}, expected {assessable.branch!r}",
                layer=layer,
            )
        )
    if view.head_sha != assessable.expected_head_sha:
        findings.append(
            _blocker(
                "head_moved",
                f"PR #{view.number} head is {view.head_sha}, expected published head "
                f"{assessable.expected_head_sha}",
                layer=layer,
            )
        )
    if view.mergeable == "CONFLICTING":
        findings.append(
            _blocker("pr_conflicting", f"PR #{view.number} is CONFLICTING", layer=layer)
        )
    elif view.mergeable == "UNKNOWN":
        findings.append(
            _blocker(
                "mergeability_unknown",
                f"PR #{view.number} mergeability is UNKNOWN (GitHub is still computing it — "
                "transient; re-run)",
                layer=layer,
            )
        )
    _classify_merge_state(view, layer, findings)
    required_failed = tuple(c.name for c in view.checks if c.is_required and c.outcome == "failed")
    required_pending = tuple(
        c.name for c in view.checks if c.is_required and c.outcome == "pending"
    )
    optional_failed = tuple(
        c.name for c in view.checks if not c.is_required and c.outcome == "failed"
    )
    if required_failed:
        findings.append(
            _blocker(
                "required_check_failed",
                f"PR #{view.number} required check(s) failed: {', '.join(required_failed)}",
                layer=layer,
            )
        )
    if required_pending:
        findings.append(
            _blocker(
                "required_check_pending",
                f"PR #{view.number} required check(s) not finished: {', '.join(required_pending)}",
                layer=layer,
            )
        )
    if optional_failed:
        findings.append(
            _info(
                "optional_check_failed",
                f"PR #{view.number} optional check(s) failed: {', '.join(optional_failed)}",
                layer=layer,
            )
        )
    if view.review_decision == "CHANGES_REQUESTED":
        findings.append(
            _blocker("changes_requested", f"PR #{view.number} has changes requested", layer=layer)
        )
    elif view.review_decision == "REVIEW_REQUIRED":
        findings.append(
            _blocker("review_required", f"PR #{view.number} still requires review", layer=layer)
        )
    # APPROVED passes; None passes too — the one deliberate nullable-pass: a null
    # reviewDecision positively means the base requires no review.
    if view.unresolved_thread_count > 0:
        findings.append(
            _info(
                "unresolved_threads",
                f"PR #{view.number} has {view.unresolved_thread_count} unresolved review "
                "thread(s) (advisory — never a perk-invented gate)",
                layer=layer,
            )
        )
    return LandLayerReadiness(
        node_id=layer.node_id,
        plan_id=assessable.plan_id,
        pr_number=assessable.pr_number,
        branch=assessable.branch,
        expected_base_ref=assessable.expected_base_ref,
        expected_head_sha=assessable.expected_head_sha,
        base_sha=assessable.base_sha,
        assessed=True,
        observed_state=view.state,
        observed_is_draft=view.is_draft,
        observed_base_ref=view.base_ref,
        observed_head_ref=view.head_ref,
        observed_head_sha=view.head_sha,
        mergeable=view.mergeable,
        merge_state_status=view.merge_state_status,
        review_decision=view.review_decision,
        required_checks_failed=required_failed,
        required_checks_pending=required_pending,
        optional_checks_failed=optional_failed,
        unresolved_thread_count=view.unresolved_thread_count,
    )


def _classify_merge_state(
    view: PrLandView, layer: TrainLayer, findings: list[TrainFinding]
) -> None:
    """The independent fail-closed ``mergeStateStatus`` mapping. Only CLEAN | HAS_HOOKS |
    UNSTABLE add no blocker (UNSTABLE = only optional checks failing, surfaced by the check
    classification)."""
    status = view.merge_state_status
    if status == "BEHIND":
        findings.append(
            _blocker("pr_behind", f"PR #{view.number} is BEHIND its base (update it)", layer=layer)
        )
    elif status == "BLOCKED":
        findings.append(
            _blocker(
                "pr_blocked",
                f"PR #{view.number} is BLOCKED by GitHub's aggregate rule verdict (an "
                "enforced repository rule — e.g. conversation resolution — is unmet)",
                layer=layer,
            )
        )
    elif status == "UNKNOWN":
        findings.append(
            _blocker(
                "merge_state_unknown",
                f"PR #{view.number} merge state is UNKNOWN (transient; re-run)",
                layer=layer,
            )
        )
    elif status == "DIRTY":
        # Independent of `mergeable` — but when the scalar already said CONFLICTING the
        # scalar arm has emitted this exact code, so the aggregate stays silent (one
        # blocker per established fact, never a duplicate row).
        if view.mergeable != "CONFLICTING":
            findings.append(
                _blocker(
                    "pr_conflicting",
                    f"PR #{view.number} merge state is DIRTY (conflicting)",
                    layer=layer,
                )
            )
    elif status == "DRAFT" and not view.is_draft:
        # Same shape: independent of `isDraft`, deduplicated against its scalar arm.
        findings.append(
            _blocker("pr_draft", f"PR #{view.number} merge state says DRAFT", layer=layer)
        )


# ----------------------------------------------------------------- the assessment


def assess_land_readiness(
    train_projection: DeliveryTrain,
    *,
    observations: LandObservations,
    remote_writers: RemoteWriterProbe,
) -> LandReadiness:
    """Compose the dry-run landing-readiness projection (contracts.md §8.55).

    Train state composes first (any train blocker or unresolved operation vetoes landing);
    a zero-layer train short-circuits (NOTHING_TO_LAND only when clean); LANDED layers ride
    as ``landed: true`` rows and are excluded from every enrichment (an all-LANDED train is
    NOTHING_TO_LAND only when fully finalized — else the ``landed_unfinalized`` INFO
    promotes to a blocker); then the enrichments over the non-landed remainder —
    local/remote writers, base merge rules, host stack capability (multi-layer remainder
    only), composition (multi-layer remainder only), and one fresh per-PR readiness read per
    PUBLISHED layer. READY iff ≥1 non-landed layer and zero blockers; information never
    vetoes.
    """
    findings: list[TrainFinding] = []
    # 1. Train state composes as-is (blockers take precedence over every disposition).
    findings.extend(train_projection.blockers)
    for operation in train_projection.unresolved_operations:
        findings.append(
            _blocker(
                "unresolved_operation",
                f"unresolved {operation.kind} operation {operation.operation_id} (prepared "
                f"{operation.prepared_created}) — conclude it before landing",
            )
        )
    findings.extend(train_projection.information)

    def result(
        disposition: LandDisposition,
        *,
        rules: MergeRulesView | None = None,
        capability: bool | None = None,
        layers: tuple[LandLayerReadiness, ...] = (),
        plan: LandPlan | None = None,
    ) -> LandReadiness:
        return LandReadiness(
            objective_id=train_projection.objective_id,
            objective_url=train_projection.objective_url,
            delivery_lineage=train_projection.delivery_lineage,
            base=train_projection.base,
            disposition=disposition,
            rules=rules,
            native_stack_capability=capability,
            layers=layers,
            findings=tuple(findings),
            plan=plan,
        )

    def has_blockers() -> bool:
        return any(f.kind is FindingKind.BLOCKER for f in findings)

    # 2. Zero layers (the all-skipped projection): no enrichment reads at all.
    layers = train_projection.layers
    if not layers:
        clean = not has_blockers()
        return result(LandDisposition.NOTHING_TO_LAND if clean else LandDisposition.BLOCKED)

    # 2b. The all-LANDED train (§8.44/§8.55): nothing remains to merge — no enrichment
    # reads. NOTHING_TO_LAND only when every landed layer converged (finalized + node
    # terminal — the train's `landed_unfinalized` INFO is the evidence); otherwise the INFO
    # promotes to a blocker exactly here, so the close arm stays unreachable.
    landed_rows = {
        layer.node_id: _landed_row(layer)
        for layer in layers
        if layer.publication is LayerPublication.LANDED
    }
    active_layers = tuple(
        layer for layer in layers if layer.publication is not LayerPublication.LANDED
    )
    if not active_layers:
        unconverged = [f for f in train_projection.information if f.code == "landed_unfinalized"]
        for finding in unconverged:
            findings.append(
                _blocker(
                    "landed_unfinalized",
                    f"{finding.message} — the train is fully landed but not converged; "
                    "landing cannot complete the objective",
                )
            )
        rows_all = tuple(landed_rows[layer.node_id] for layer in layers)
        clean = not has_blockers()
        return result(
            LandDisposition.NOTHING_TO_LAND if clean else LandDisposition.BLOCKED,
            layers=rows_all,
        )

    # 3./4. Publication completeness (over the non-landed remainder) + the enrichment
    # eligibility gate.
    assessable: list[_AssessableLayer] = []
    unpublished = False
    for layer in active_layers:
        if layer.publication is not LayerPublication.PUBLISHED:
            unpublished = True
            findings.append(
                _blocker(
                    "incomplete_publication",
                    f"layer {layer.node_id} is not published "
                    f"(publication: {layer.publication.value})",
                    layer=layer,
                )
            )
            continue
        checked = _as_assessable(layer)
        if checked is None:
            # Contradicts the §8.46 published-layer definition — classify back rather
            # than trust a half-identified layer.
            findings.append(
                _blocker(
                    "incomplete_publication",
                    f"layer {layer.node_id} is published but missing identity/checkpoint fields",
                    layer=layer,
                )
            )
            continue
        assessable.append(checked)
    if not unpublished and train_projection.published_prefix_len != len(layers):
        # The publication-completeness invariant checked on BOTH axes: every layer reading
        # published while the contiguous prefix stays short is an inconsistent projection —
        # fail-closed, never READY (the per-layer arm above already covers the ordinary
        # partially-published train, so this fires only for the contradiction).
        findings.append(
            _blocker(
                "incomplete_publication",
                f"published prefix {train_projection.published_prefix_len}/{len(layers)} "
                "does not cover the train although every layer reads published",
            )
        )

    # 5. Local writers (the train's read-only writer axis, the non-landed layers — a
    # landed layer's branch is merged/deleted; local checkouts of it are inert).
    for layer in active_layers:
        if layer.writer is LayerWriter.DIRTY:
            findings.append(
                _blocker(
                    "dirty_worktree",
                    f"layer {layer.node_id} branch {layer.branch} has a dirty local worktree",
                    layer=layer,
                )
            )
        elif layer.writer is LayerWriter.ACTIVE:
            findings.append(
                _info(
                    "active_worktree",
                    f"layer {layer.node_id} branch {layer.branch} is checked out in a clean "
                    "local worktree (landing merges remote PRs; local branches are left "
                    "untouched)",
                    layer=layer,
                )
            )

    # 6. Remote writers (every planned non-landed layer — an active writer anywhere in the
    # remainder is affected; landed layers are already merged).
    plan_ids = [layer.plan_id for layer in active_layers if layer.plan_id is not None]
    try:
        active = remote_writers.active_plan_ids(plan_ids)
    except WriterObservationError as exc:
        findings.append(
            _blocker(
                "writer_observation_unavailable",
                f"could not observe active remote writers: {exc}",
            )
        )
    else:
        if active:
            findings.append(
                _blocker(
                    "active_writer",
                    "active remote writer(s) on plan(s): "
                    + ", ".join(f"#{plan_id}" for plan_id in sorted(active)),
                )
            )

    # 7. Base merge rules.
    rules: MergeRulesView | None
    try:
        rules = observations.base_merge_rules()
    except LandObservationError as exc:
        rules = None
        findings.append(
            _blocker(
                "merge_rules_unobserved",
                f"could not read merge rules for base {train_projection.base!r}: {exc}",
            )
        )
    else:
        if not rules.squash_allowed:
            findings.append(
                _blocker(
                    "squash_forbidden",
                    f"base {train_projection.base!r} does not allow squash merges",
                )
            )
        if rules.merge_queue_required:
            findings.append(
                _blocker(
                    "queue_required_base",
                    f"base {train_projection.base!r} requires a merge queue (a queued base "
                    "cannot take the direct squash merges a stacked train needs)",
                )
            )

    # 8./9. Host stack capability + composition — multi-layer REMAINDERS only (the dynamic
    # singleton — including a one-layer remainder above a landed prefix — lands as one
    # ordinary SHA-pinned squash; membership is NOT_APPLICABLE by design).
    capability: bool | None = None
    if len(active_layers) > 1:
        capability = observations.stack_capability()
        if not capability:
            findings.append(
                _blocker(
                    "stack_capability_unavailable",
                    "the host does not expose the native-stack API surface (or the probe "
                    "could not observe it — the fail-closed boolean arm)",
                )
            )
        for layer in active_layers:
            if layer.membership is not LayerMembership.EXACT:
                findings.append(
                    _blocker(
                        "composition_divergent",
                        f"layer {layer.node_id} native-stack membership is "
                        f"{layer.membership.value}, expected exact (fail-closed: unknown "
                        "blocks)",
                        layer=layer,
                    )
                )

    # 10. Per-layer fresh readiness (assessable layers only; each failure is localized —
    # the remaining layers are still assessed).
    rows: dict[str, LandLayerReadiness] = {}
    for entry in assessable:
        try:
            view = observations.pr_readiness(entry.pr_number)
        except LandObservationError as exc:
            findings.append(
                _blocker(
                    "readiness_unobserved",
                    f"could not read landing readiness for PR #{entry.pr_number}: {exc}",
                    layer=entry.layer,
                )
            )
            continue
        if view is None:
            findings.append(
                _blocker(
                    "pr_missing",
                    f"PR #{entry.pr_number} no longer exists",
                    layer=entry.layer,
                )
            )
            continue
        rows[entry.layer.node_id] = _classify_pr(entry, view, findings)
    layer_rows = tuple(
        landed_rows.get(layer.node_id) or rows.get(layer.node_id, _unassessed_row(layer))
        for layer in layers
    )

    # 11. Disposition + the plan (READY iff ≥1 non-landed layer and zero blockers;
    # information never vetoes). The plan covers exactly the non-landed remainder — a
    # one-layer remainder lands via the SHA-pinned direct squash (endpoint-guaranteed).
    if has_blockers():
        return result(
            LandDisposition.BLOCKED, rules=rules, capability=capability, layers=layer_rows
        )
    plan_layers = tuple(
        LandPlanLayer(
            node_id=entry.layer.node_id,
            plan_id=entry.plan_id,
            pr_number=entry.pr_number,
            base_sha=entry.base_sha,
            head_sha=entry.expected_head_sha,
        )
        for entry in assessable
    )
    top = plan_layers[-1]
    plan = LandPlan(
        mode="singleton_squash" if len(active_layers) == 1 else "stack_merge_async",
        merge_method="squash",
        top_pr_number=top.pr_number,
        top_head_sha=top.head_sha,
        layers=plan_layers,
    )
    return result(
        LandDisposition.READY, rules=rules, capability=capability, layers=layer_rows, plan=plan
    )
