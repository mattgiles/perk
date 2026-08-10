"""Cross-verb helpers for the ``perk objective`` group."""

from dataclasses import dataclass
from pathlib import Path

from perk import objective
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.cli.commands.plan.resume_cmd import parse_plan_id
from perk.cli.ensure import UserFacingCliError
from perk.delivery import observe
from perk.delivery import train as train_mod
from perk.delivery.persistence import TrainPersistenceError
from perk.prompts import render


def parse_objective_id(raw: str) -> str:
    """Validate an opaque objective issue id (``7``, ``#7``, or Linear's ``ENG-7``).

    The single shared parse for every ``perk objective`` verb — a thin alias of the re-typed
    :func:`perk.cli.commands.plan.resume_cmd.parse_plan_id` (one definition, no duplication).
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


def node_to_dict(node: objective.ObjectiveNode) -> dict[str, object]:
    return {
        "id": node.id,
        "description": node.description,
        "status": node.status.value,
        "pr": node.pr,
        "phase": objective.phase_label(objective.derive_phase(node.id)),
    }
