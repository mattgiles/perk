"""Cross-verb helpers for the ``perk objective`` group."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk import github, objective
from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import parse_plan_id
from perk.delivery import observe
from perk.delivery import train as train_mod
from perk.delivery.persistence import TrainPersistenceError
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


@dataclass(frozen=True)
class StackedSelection:
    """The readiness-derived planning classification of a STACKED objective (contracts.md
    §8.46) — the one seam the plan door, ``objective next``, and the run supervisor consume.

    ``kind`` is one of ``"build_blocked"`` (the train's readiness veto — ``reason`` carries
    the exact findings), ``"plannable"`` (the readiness-derived candidate has no committed
    plan yet), ``"in_flight"`` (the candidate carries a committed plan — implement it), or
    ``"no_candidate"`` (every layer is published — consumers fall through to the existing
    graph classification; completion semantics unchanged). ``node`` is the candidate for
    ``plannable``/``in_flight``, else ``None``. ``ready``/``reason`` mirror the train's
    :class:`~perk.delivery.train.BuildReadiness`.
    """

    kind: str
    node: objective.ObjectiveNode | None
    ready: bool
    reason: str | None
    train: train_mod.DeliveryTrain | None = None


def stacked_selection(repo_root: Path, state: ObjectiveState) -> StackedSelection | None:
    """Classify a stacked objective's next planning step from live build readiness (§8.46).

    ``None`` for an incremental objective (the caller keeps the existing dep-terminal graph
    gating). For a stacked objective this REPLACES that gating: the single planning candidate
    is the readiness-derived next layer (the first unpublished layer in delivery order), which
    is what permits planning layer k+1 while layer k is published-but-unmerged. Performs a
    live train reconstruction (network); a ``TrainReconstructionError`` maps to a typed
    :class:`UserFacingCliError` preserving its ``error_type``.
    """
    try:
        policy = objective.delivery_policy(state.header)
    except ValueError as exc:
        raise UserFacingCliError(str(exc), error_type="invalid_delivery_policy") from exc
    if policy is objective.DeliveryPolicy.INCREMENTAL:
        return None
    try:
        status = observe.reconstruct_repo_train(repo_root, state.id)
    except train_mod.TrainReconstructionError as exc:
        raise UserFacingCliError(str(exc), error_type=exc.error_type) from exc
    except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
        # The authority-read translation the stack-status and launch paths already apply —
        # every consumer of this seam gets the stable error surface, not a traceback.
        raise UserFacingCliError(str(exc), error_type="github_error") from exc
    if not isinstance(status, train_mod.DeliveryTrain):  # defensive: the policy said stacked
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
