"""Cross-verb helpers for the ``perk objective`` group."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk import github, objective
from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import ObjectiveState
from perk.boundary import OutputModel
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.cli.plan_selection import parse_plan_id
from perk.delivery import DeliveryError, StatusRequest, resolve_delivery
from perk.delivery import train as train_mod
from perk.prompts import render
from perk.run import resume


def parse_objective_id(raw: str) -> str:
    """Validate an opaque objective issue id (``7``, ``#7``, or Linear's ``ENG-7``).

    The single shared parse for every ``perk objective`` verb — a thin alias of the re-typed
    :func:`perk.cli.plan_selection.parse_plan_id` (one definition, no duplication).
    """
    return parse_plan_id(raw, what="objective")


def objective_read_instruction(backend: str, objective_id: str, url: str) -> str:
    """Backend-aware supplemental clause for the objective-read step of the factory prompts.
    The wording lives in `prompts/common/objective-read/linear.md`, rendered identically by both
    planes via the shared render seam (contracts.md §8.31); branching stays in code. github (and any
    non-linear) → "" (the `perk objective show` step already covers it); linear → the Project URL +
    the linear_get_issue/linear_list_comments tools (an `open <url>` fallback when the url is
    known)."""
    if backend != "linear":
        return ""
    where = f"({url})" if url else f"(run `perk objective show {objective_id}` for its URL)"
    fallback = f"; if the linear tools are unavailable, open {url}" if url else ""
    return render("common/objective-read/linear.md", {"where": where, "fallback": fallback})


class GateBlockerOut(OutputModel):
    """One planning-gate blocker row (contracts.md §8.46) — the shared machine
    discriminator every gate-carrying envelope serializes.

    ``kind`` is ``"technical"`` (a train readiness veto — ``code``/``message`` verbatim, or
    the gate-owned defensive ``dependency_not_ready``) or ``"handoff"`` (a handoff-blocked
    direct dependency — fields-only, no prose: consumers read the pinned fields). Handoff
    rows derive from a verified-PUBLISHED layer, so ``plan``/``pr``/``remediation`` are
    always populated there (the nullable wire types exist for the technical rows).
    """

    kind: str
    code: str | None
    message: str | None
    dependency_node_id: str | None
    plan: str | None
    pr: int | None
    handoff_state: str | None
    stamped_head: str | None
    current_head: str | None
    remediation: str | None


class PlanningGateOut(OutputModel):
    """The composed planning-gate block (contracts.md §8.46): the evaluated candidate
    (``None`` when no candidate exists), the technical-AND-handoff verdict for
    planning/fresh starts, and the blocker rows."""

    node_id: str | None
    ready: bool
    blockers: tuple[GateBlockerOut, ...]


def _handoff_row(layer: train_mod.TrainLayer) -> GateBlockerOut:
    """One handoff blocker row from its own :class:`TrainLayer` fact. A verified-PUBLISHED
    layer carries ``plan_id``/``pr_number`` by construction — the ``Ensure`` narrowing makes
    a null there a programming error, never a rendered state."""
    plan_id = Ensure.not_none(layer.plan_id, "handoff-blocked layer must carry a plan id")
    pr_number = Ensure.not_none(layer.pr_number, "handoff-blocked layer must carry a PR number")
    return GateBlockerOut(
        kind="handoff",
        code=None,
        message=None,
        dependency_node_id=layer.node_id,
        plan=plan_id,
        pr=pr_number,
        handoff_state=layer.handoff.value,
        stamped_head=layer.stamped_head_sha,
        current_head=layer.observed_remote_head_sha,
        remediation=f"perk ready {plan_id}",
    )


def _technical_row(code: str, message: str, remediation: str) -> GateBlockerOut:
    return GateBlockerOut(
        kind="technical",
        code=code,
        message=message,
        dependency_node_id=None,
        plan=None,
        pr=None,
        handoff_state=None,
        stamped_head=None,
        current_head=None,
        remediation=remediation,
    )


def technical_gate_blockers(status: train_mod.DeliveryTrain) -> tuple[GateBlockerOut, ...]:
    """The technical blocker rows (contracts.md §8.46): one per train blocker finding
    (``code``/``message`` verbatim) and one per unresolved operation — mirroring
    :func:`classify_stacked_veto`'s split."""
    objective_id = status.objective_id
    rows = [
        _technical_row(finding.code, finding.message, f"perk objective stack status {objective_id}")
        for finding in status.blockers
    ]
    rows.extend(
        _technical_row(
            "unresolved_operation",
            (
                f"operation {operation.operation_id} ({operation.kind}, prepared "
                f"{operation.prepared_created}) is unresolved"
            ),
            f"perk objective stack recover {objective_id}",
        )
        for operation in status.unresolved_operations
    )
    return tuple(rows)


def handoff_gate_blockers(
    layers: tuple[train_mod.TrainLayer, ...],
) -> tuple[GateBlockerOut, ...]:
    """The handoff blocker rows for the gate's blocking layers (delivery order preserved)."""
    return tuple(_handoff_row(layer) for layer in layers)


def _unready_dependency_rows(
    status: train_mod.DeliveryTrain, gate: train_mod.HandoffGate
) -> tuple[GateBlockerOut, ...]:
    """The defensive ``dependency_not_ready`` arm (contracts.md §8.46): the train's blocker
    findings as technical rows when any exist, else one row per unready dependency."""
    if status.blockers:
        return technical_gate_blockers(status)
    return tuple(
        _technical_row(
            "dependency_not_ready",
            f"{dep.dependency_node_id}: {dep.reason}",
            f"perk objective stack status {status.objective_id}",
        )
        for dep in gate.unready_dependencies
    )


def compose_planning_gate(
    status: train_mod.DeliveryTrain, gate: train_mod.HandoffGate | None
) -> PlanningGateOut:
    """Compose the planning-gate block from one train projection (contracts.md §8.46).

    The five pinned arms: no candidate → ``{node_id: null, ready: false, blockers: []}``
    (the explanation already rides ``next_build_ready.reason``); technically blocked →
    technical rows; technically ready + handoff-blocked → handoff rows (delivery order);
    technically ready + unready dependencies (defensive) → ``dependency_not_ready`` rows;
    both pass → ready with no rows. ``gate=None`` computes the gate here (pure) when the
    train is technically ready.
    """
    readiness = status.build_readiness
    candidate = readiness.next_node_id
    if candidate is None:
        return PlanningGateOut(node_id=None, ready=False, blockers=())
    if not readiness.ready:
        return PlanningGateOut(
            node_id=candidate, ready=False, blockers=technical_gate_blockers(status)
        )
    if gate is None:
        gate = train_mod.check_handoff_gate(status, node_id=candidate)
    if gate.blocking_layers:
        return PlanningGateOut(
            node_id=candidate, ready=False, blockers=handoff_gate_blockers(gate.blocking_layers)
        )
    if gate.unready_dependencies:
        return PlanningGateOut(
            node_id=candidate, ready=False, blockers=_unready_dependency_rows(status, gate)
        )
    return PlanningGateOut(node_id=candidate, ready=True, blockers=())


def handoff_blocker_phrase(layer: train_mod.TrainLayer) -> str:
    """One handoff blocker's human phrase: ``<dep> (plan #<p>, PR #<pr>) — <state>[; stamped
    <sha12> ≠ head <sha12>]; record the handoff: perk ready <p>``."""
    plan_id = Ensure.not_none(layer.plan_id, "handoff-blocked layer must carry a plan id")
    pr_number = Ensure.not_none(layer.pr_number, "handoff-blocked layer must carry a PR number")
    detail = f"{layer.node_id} (plan #{plan_id}, PR #{pr_number}) — {layer.handoff.value}"
    if (
        layer.handoff is train_mod.LayerHandoff.STALE
        and layer.stamped_head_sha is not None
        and layer.observed_remote_head_sha is not None
    ):
        detail += (
            f"; stamped {layer.stamped_head_sha[:12]} ≠ head {layer.observed_remote_head_sha[:12]}"
        )
    return detail + f"; record the handoff: perk ready {plan_id}"


def handoff_blocked_summary(node_id: str, layers: tuple[train_mod.TrainLayer, ...]) -> str:
    """The composed one-string handoff summary (delivery order): ``node <id> waits on
    <phrase>[; <phrase>…]``."""
    return f"node {node_id} waits on " + "; ".join(
        handoff_blocker_phrase(layer) for layer in layers
    )


@dataclass(frozen=True)
class StackedSelection:
    """The readiness-derived planning classification of a STACKED objective (contracts.md
    §8.46) — the one seam the plan door, ``objective next``, and the run supervisor consume.

    ``kind`` is one of ``"build_blocked"`` (the train's readiness veto — ``reason`` carries
    the exact findings), ``"handoff_blocked"`` (the candidate is technically plannable but a
    direct dependency's handoff stamp is missing/stale/suspended — ``handoff_blockers``
    carries the blocking layers in delivery order), ``"plannable"`` (the readiness-derived
    candidate has no committed plan yet), ``"in_flight"`` (the candidate carries a committed
    plan — implement it), or ``"no_candidate"`` (every layer is published — consumers fall
    through to the existing graph classification; completion semantics unchanged). ``node``
    is the candidate for ``plannable``/``in_flight``/``handoff_blocked``, else ``None``.
    ``ready``/``reason`` mirror the train's
    :class:`~perk.delivery.train.BuildReadiness` (the handoff arm composes its own reason).
    """

    kind: str
    node: objective.ObjectiveNode | None
    ready: bool
    reason: str | None
    train: train_mod.DeliveryTrain | None = None
    handoff_blockers: tuple[train_mod.TrainLayer, ...] = ()


def stacked_selection(repo_root: Path, state: ObjectiveState) -> StackedSelection | None:
    """Classify a stacked objective's next planning step from live build readiness (§8.46).

    ``None`` for an incremental objective (the caller keeps the existing dep-terminal graph
    gating). For a stacked objective this REPLACES that gating: the single planning candidate
    is the readiness-derived next layer (the first unpublished layer in delivery order), which
    is what permits planning layer k+1 while layer k is published-but-unmerged. Performs a
    live ``Delivery.status`` read (network); a ``DeliveryError`` maps to a typed
    :class:`UserFacingCliError` preserving its ``error_type``.
    """
    try:
        policy = objective.delivery_policy(state.header)
    except ValueError as exc:
        raise UserFacingCliError(str(exc), error_type="invalid_delivery_policy") from exc
    if policy is objective.DeliveryPolicy.INCREMENTAL:
        return None
    try:
        result = resolve_delivery(repo_root).status(StatusRequest(objective_id=state.id))
    except DeliveryError as exc:
        raise UserFacingCliError(str(exc), error_type=exc.error_type) from exc
    status = result.train
    if status is None:  # defensive: the already-read policy said stacked
        return None
    readiness = status.build_readiness
    if readiness.next_node_id is None:
        return StackedSelection(
            kind="no_candidate", node=None, ready=False, reason=readiness.reason, train=status
        )
    if not readiness.ready:
        return StackedSelection(
            kind="build_blocked", node=None, ready=False, reason=readiness.reason, train=status
        )
    node = next((n for n in state.nodes if n.id == readiness.next_node_id), None)
    if node is None:  # defensive: the readiness candidate derives from these nodes
        return StackedSelection(
            kind="build_blocked",
            node=None,
            ready=False,
            reason=f"the readiness candidate {readiness.next_node_id} is not on the roadmap",
            train=status,
        )
    if node.status is objective.NodeStatus.PENDING or (
        node.status is objective.NodeStatus.PLANNING and node.pr is None
    ):
        # The plannable candidate additionally passes the direct-dependency handoff gate
        # (contracts.md §8.46); the in_flight arm below stays ungated by construction.
        gate = train_mod.check_handoff_gate(status, node_id=node.id)
        if gate.blocking_layers:
            return StackedSelection(
                kind="handoff_blocked",
                node=node,
                ready=False,
                reason=handoff_blocked_summary(node.id, gate.blocking_layers),
                train=status,
                handoff_blockers=gate.blocking_layers,
            )
        if gate.unready_dependencies:
            return StackedSelection(
                kind="build_blocked",
                node=None,
                ready=False,
                reason="; ".join(
                    f"{dep.dependency_node_id}: {dep.reason}" for dep in gate.unready_dependencies
                ),
                train=status,
            )
        return StackedSelection(kind="plannable", node=node, ready=True, reason=None, train=status)
    if node.status is objective.NodeStatus.IN_PROGRESS or (
        node.status is objective.NodeStatus.PLANNING and node.pr is not None
    ):
        return StackedSelection(kind="in_flight", node=node, ready=True, reason=None, train=status)
    # Any other status (an explicitly blocked node, an unpublished done node, …) fails
    # closed: the candidate exists but is not honestly plannable.
    return StackedSelection(
        kind="build_blocked",
        node=node,
        ready=False,
        reason=(
            f"the next build-ready layer {node.id} is {node.status.value} — not plannable "
            "in that status"
        ),
        train=status,
    )


def selection_gate_blockers(selection: "StackedSelection") -> tuple[GateBlockerOut, ...]:
    """The shared blocker rows for one stacked selection (contracts.md §8.46): handoff rows
    on ``handoff_blocked``, technical rows on ``build_blocked`` (the defensive
    ``dependency_not_ready`` rows when the technically-ready gate failed closed), and no
    rows on ``plannable``/``in_flight``/``no_candidate``."""
    status = selection.train
    if status is None:
        return ()
    if selection.kind == "handoff_blocked":
        return handoff_gate_blockers(selection.handoff_blockers)
    if selection.kind != "build_blocked":
        return ()
    readiness = status.build_readiness
    if not readiness.ready or selection.node is not None:
        # The readiness-veto arm (real technical rows) or the not-plannable-status arm
        # (technically ready — no veto rows exist).
        return technical_gate_blockers(status)
    candidate = readiness.next_node_id
    if candidate is None:
        return ()
    # The technically-ready node-less build_blocked: the gate's defensive unready-dependency
    # arm (recomputed — pure over the same projection) or the candidate-off-roadmap arm
    # (whose recomputed gate is empty).
    gate = train_mod.check_handoff_gate(status, node_id=candidate)
    if gate.unready_dependencies:
        return _unready_dependency_rows(status, gate)
    return technical_gate_blockers(status)


@dataclass(frozen=True)
class StackedVeto:
    """A train-wide supervisor pause, with the owning copyable remediation."""

    action: str
    reason: str
    remediation: str


@dataclass(frozen=True)
class StackedAttention:
    """A published layer whose corroborated plan needs address work."""

    node: objective.ObjectiveNode
    plan: PlanState


def classify_stacked_veto(selection: StackedSelection, objective_id: str) -> StackedVeto | None:
    """Classify train-wide vetoes before branching on the selection kind."""
    train = selection.train
    if train is None:  # defensive/test seam; production stacked selections always carry one
        return None
    structural = [
        finding for finding in train.blockers if finding.code in train_mod.STRUCTURAL_BLOCKER_CODES
    ]
    if structural:
        reason = "; ".join(f"[{finding.code}] {finding.message}" for finding in structural)
        return StackedVeto(
            action="build_blocked",
            reason=reason,
            remediation=f"perk objective stack status {objective_id}",
        )
    if train.unresolved_operations:
        reason = "; ".join(
            f"operation {operation.operation_id} ({operation.kind}, prepared "
            f"{operation.prepared_created})"
            for operation in train.unresolved_operations
        )
        return StackedVeto(
            action="repair_required",
            reason=reason,
            remediation=f"perk objective stack recover {objective_id}",
        )
    if train.blockers:
        reason = "; ".join(f"[{finding.code}] {finding.message}" for finding in train.blockers)
        return StackedVeto(
            action="repair_required",
            reason=reason,
            remediation=f"perk objective stack status {objective_id}",
        )
    return None


def stacked_lower_attention(
    repo_root: Path,
    train: train_mod.DeliveryTrain,
    state: ObjectiveState,
    *,
    get_plan: Callable[[str], PlanState | None],
    get_feedback: Callable[[int], github.PrFeedback],
    has_pending_learn: bool,
) -> StackedAttention | None:
    """Return the bottom-most published layer needing actionable address work.

    Draft-ready and awaiting-review layers are deliberate review waits, not supervisor
    priorities. A projection-corroborated plan that vanishes on read fails closed. The
    corroborated plan travels with the node so callers never re-derive identity from roadmap
    prose after the train join has already established it.
    """
    del repo_root  # retained in the public seam for parity with other supervisor helpers
    nodes = {node.id: node for node in state.nodes}
    for layer in train.layers:
        if layer.publication is not train_mod.LayerPublication.PUBLISHED or layer.plan_id is None:
            continue
        node = nodes.get(layer.node_id)
        if node is None:
            raise UserFacingCliError(
                f"published train layer {layer.node_id} is absent from the objective roadmap",
                error_type="github_error",
            )
        plan_id = layer.plan_id.removeprefix("#")
        plan_state = get_plan(plan_id)
        if plan_state is None:
            raise UserFacingCliError(
                f"published layer {layer.node_id} corroborates plan #{plan_id}, but the plan "
                "read returned missing",
                error_type="github_error",
            )
        verdict = resume.resolve_next_action(
            plan_state,
            has_pending_learn=has_pending_learn,
            get_feedback=get_feedback,
        )
        if verdict is resume.NextAction.ADDRESS:
            return StackedAttention(node=node, plan=plan_state)
    return None


def node_to_dict(node: objective.ObjectiveNode) -> dict[str, object]:
    return {
        "id": node.id,
        "description": node.description,
        "status": node.status.value,
        "pr": node.pr,
        "phase": objective.phase_label(objective.derive_phase(node.id)),
    }
