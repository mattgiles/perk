"""Deterministic train-finding diagnosis policy + the narrow cancellation repair (§8.54).

This module annotates the EXISTING :class:`~perk.delivery.train.TrainFinding` identity — it is
not a parallel drift engine. Two responsibilities:

- **Finding policy** (:func:`classify_finding`): a total, deterministic mapping from a finding
  to its doctor-facing severity / repairability / remediation. Base rules: BLOCKER →
  ``error``/nonrepairable, INFO → ``info``/nonrepairable; an unknown future code keeps that
  kind-derived default with **no** auto remediation (a new code can never become repairable
  accidentally). The complete current overrides are the category frozensets below (pinned
  disjoint by tests). The ONE repairable finding is a repairable
  ``canceled_unpublished_projected`` — persist a safely-projected native cancellation into the
  node attachment; an already-skipped instance stays info/nonrepairable.
- **Race-aware metadata repair** (:func:`repair_projected_cancellations`): per candidate in
  node order, a FRESH reconstruction proof immediately before a conditional compare-and-write
  through the :class:`NativeCancellationMetadataWriter` seam, post-write verification through
  another reconstruction, and compensation (attachment rollback) + loud abort on observed
  post-write drift. This does not claim distributed atomicity; it prevents stale snapshots
  from writing and compensates observed drift. Doctor NEVER repairs plan identity,
  checkpoints, journal history, branches, PRs, or native stack membership.

Import direction stays legal: this module depends on the pure train projection and the
backend-neutral :mod:`perk.backends.objective_store` vocabulary only; the concrete writer
(``LinearProjectObjectiveStore``) satisfies the Protocol structurally.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from perk.backends.objective_store import CancellationRepairOutcome, ObjectiveStoreError
from perk.delivery.train import (
    DeliveryTrain,
    FindingKind,
    TrainFinding,
    TrainReconstructionError,
    TrainStatus,
)
from perk.objective import NodeStatus

# ----------------------------------------------------------------- the finding policy

# The code every repair action carries (the one repairable finding).
PROJECTED_CANCELLATION_CODE = "canceled_unpublished_projected"

# Pending operations conclude through recover / the owning /submit — never a doctor write.
RECOVER_REMEDIATION_CODES = frozenset(
    {"active_operation", "publish_outcome_pending", "canceled_publication_pending"}
)

# Remote branch/PR/native-stack conflicts are repaired explicitly on GitHub, then re-observed.
GITHUB_REPAIR_CODES = frozenset(
    {
        "missing_pr",
        "pr_wrong_base",
        "pr_wrong_head",
        "pr_closed",
        "stack_missing",
        "stack_divergent",
        "canceled_remote_work",
    }
)

# Degraded read authorities: restore the read (network/API), then rerun status.
READ_AUTHORITY_CODES = frozenset({"stack_read_unavailable", "base_unobserved"})

# Append-only evidence gaps: an explicit audit/restore — doctor never synthesizes history.
EVIDENCE_AUDIT_CODES = frozenset(
    {
        "journal_corruption",
        "missing_publish_outcome",
        "checkpoint_after_abandoned_publish",
        "cancellation_evidence_unavailable",
    }
)

# Identity/topology/status contradictions: restore the edited authority (Linear/plan/GitHub
# native state), rerun status, then optionally replan — replan never bypasses blockers.
IDENTITY_RESTORE_CODES = frozenset(
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
        "checkpoint_pair_incomplete",
        "checkpoint_prefix_gap",
        "checkpoint_parent_mismatch",
        "prefix_gap",
        "canceled_status_conflict",
        "canceled_plan_unresolved",
        "canceled_published_layer",
    }
)

# Lifecycle projections (and the nonrepairable projected cancellation): no remediation.
NO_REMEDIATION_CODES = frozenset({"dynamic_singleton", "all_skipped"})


@dataclass(frozen=True)
class FindingPolicy:
    """One finding's doctor-facing policy: ``severity`` is ``error | warning | info``."""

    severity: str
    repairable: bool
    remediation: str | None


def classify_finding(
    finding: TrainFinding, *, objective_id: str, repairable_nodes: frozenset[str]
) -> FindingPolicy:
    """The total policy mapping (see the module docstring). ``repairable_nodes`` is the
    train's ``repairable_canceled_nodes`` node-id set — repairability is tied to the typed
    candidate on the projection, never re-derived from finding text."""
    code = finding.code
    if code == PROJECTED_CANCELLATION_CODE:
        if finding.node_id is not None and finding.node_id in repairable_nodes:
            return FindingPolicy(
                severity="warning",
                repairable=True,
                remediation=f"perk objective doctor {objective_id} --fix",
            )
        return FindingPolicy(severity="info", repairable=False, remediation=None)
    severity = "error" if finding.kind is FindingKind.BLOCKER else "info"
    return FindingPolicy(
        severity=severity, repairable=False, remediation=_remediation(code, objective_id)
    )


def _remediation(code: str, objective_id: str) -> str | None:
    if code in RECOVER_REMEDIATION_CODES:
        return (
            f"conclude the operation via `perk objective stack recover {objective_id}` "
            "or the owning `/submit`"
        )
    if code == "base_advanced":
        return f"perk objective stack sync {objective_id} --base"
    if code == "checkpoint_drift":
        return (
            "inspect the drifted branch/checkpoints; "
            f"`perk objective stack sync {objective_id} --adopt NODE` only for an "
            "intentional adoption"
        )
    if code in GITHUB_REPAIR_CODES:
        return (
            "repair the branch/PR/native stack on GitHub explicitly, then rerun "
            f"`perk objective stack status {objective_id}`"
        )
    if code in READ_AUTHORITY_CODES:
        return (
            "restore the read authority (network/API), then rerun "
            f"`perk objective stack status {objective_id}`"
        )
    if code in EVIDENCE_AUDIT_CODES:
        return (
            "audit/restore the append-only journal evidence explicitly — doctor never "
            "synthesizes history"
        )
    if code in IDENTITY_RESTORE_CODES:
        return (
            "restore the contradicted authority/native state, rerun "
            f"`perk objective stack status {objective_id}`, then replan only if a coherent "
            "future roadmap still needs reshaping"
        )
    # NO_REMEDIATION_CODES and every unknown future code: no auto remediation.
    return None


# ----------------------------------------------------------------- the conditional writer seam


@runtime_checkable
class NativeCancellationMetadataWriter(Protocol):
    """The narrow attachment-only conditional write an objective store may offer (§8.54) —
    implemented only by ``LinearProjectObjectiveStore``. The writer performs a FRESH
    state-bearing read at the effect boundary, compares the persisted attachment status
    against ``expected_status``, requires the node natively canceled when
    ``require_native_canceled`` is True (``None`` = no native predicate — the rollback arm;
    False = require NOT canceled), rechecks that no raw PR/checkpoint claims exist when
    ``require_no_raw_publish_claims``, and writes ONLY the ``objective-node`` attachment —
    never the generic status update, never a workflow-state mirror/re-cancel."""

    def write_node_cancellation_status(
        self,
        *,
        objective_id: str,
        node_id: str,
        expected_status: NodeStatus,
        new_status: NodeStatus,
        require_native_canceled: bool | None,
        require_no_raw_publish_claims: bool,
        dry_run: bool = False,
    ) -> CancellationRepairOutcome: ...


# ----------------------------------------------------------------- the repair pass


@dataclass(frozen=True)
class CancellationRepairAction:
    """One per-candidate repair outcome: ``applied | would_apply | skipped | failed``."""

    code: str
    node_id: str
    outcome: str
    error: str | None = None


@dataclass(frozen=True)
class CancellationRepairResult:
    """The repair pass outcome. ``aborted`` is True on a write/verification/rollback failure
    (``failed`` names the action) OR when a reconstruction failed (``unavailable`` carries
    the message; ``failed`` stays None unless the failure followed an applied write, which
    records the verification failure)."""

    actions: tuple[CancellationRepairAction, ...]
    failed: CancellationRepairAction | None
    aborted: bool
    dry_run: bool
    unavailable: str | None = None


def repair_projected_cancellations(
    objective_id: str,
    *,
    writer: NativeCancellationMetadataWriter,
    reconstruct: Callable[[], TrainStatus],
    dry_run: bool = False,
) -> CancellationRepairResult:
    """Persist every repairable projected cancellation, one candidate at a time, in node
    order — each with a fresh proof immediately before the conditional write and a
    verification reconstruction after it (see the module docstring). ``dry_run`` executes
    the fresh proof and the writer's conditional validation but no write/compensation."""
    initial = _pinned(_reconstruct_or_none(reconstruct), objective_id)
    if not isinstance(initial, DeliveryTrain):
        return CancellationRepairResult(
            actions=(),
            failed=None,
            aborted=True,
            dry_run=dry_run,
            unavailable=initial if isinstance(initial, str) else "the objective has no train",
        )
    actions: list[CancellationRepairAction] = []
    for candidate in initial.repairable_canceled_nodes:
        node_id = candidate.node_id
        # Fresh proof immediately before the compare-and-write: the exact repairable
        # candidate must still be present on a just-reconstructed projection.
        fresh = _pinned(_reconstruct_or_none(reconstruct), objective_id)
        if not isinstance(fresh, DeliveryTrain):
            return CancellationRepairResult(
                actions=tuple(actions),
                failed=None,
                aborted=True,
                dry_run=dry_run,
                unavailable=fresh if isinstance(fresh, str) else "the objective has no train",
            )
        proven = next(
            (fact for fact in fresh.repairable_canceled_nodes if fact.node_id == node_id), None
        )
        if proven is None:
            actions.append(
                CancellationRepairAction(
                    code=PROJECTED_CANCELLATION_CODE,
                    node_id=node_id,
                    outcome="skipped",
                    error="no longer a repairable projected cancellation on fresh proof",
                )
            )
            continue
        try:
            outcome = writer.write_node_cancellation_status(
                objective_id=objective_id,
                node_id=node_id,
                expected_status=proven.persisted_status,
                new_status=NodeStatus.SKIPPED,
                require_native_canceled=True,
                require_no_raw_publish_claims=True,
                dry_run=dry_run,
            )
        except ObjectiveStoreError as exc:
            failed = CancellationRepairAction(
                code=PROJECTED_CANCELLATION_CODE,
                node_id=node_id,
                outcome="failed",
                error=str(exc),
            )
            return CancellationRepairResult(
                actions=tuple(actions), failed=failed, aborted=True, dry_run=dry_run
            )
        if dry_run:
            actions.append(
                CancellationRepairAction(
                    code=PROJECTED_CANCELLATION_CODE,
                    node_id=node_id,
                    outcome=(
                        "would_apply" if outcome is CancellationRepairOutcome.APPLIED else "skipped"
                    ),
                    error=None if outcome is CancellationRepairOutcome.APPLIED else outcome.value,
                )
            )
            continue
        if outcome is not CancellationRepairOutcome.APPLIED:
            # STALE (the world moved) and ALREADY_CONVERGED are skipped/not-applied — never
            # an abort; the final diagnosis reports whatever remains.
            actions.append(
                CancellationRepairAction(
                    code=PROJECTED_CANCELLATION_CODE,
                    node_id=node_id,
                    outcome="skipped",
                    error=outcome.value,
                )
            )
            continue
        verification_error, train_unavailable = _verify_applied(objective_id, node_id, reconstruct)
        if verification_error is not None:
            if train_unavailable:
                # No observation exists to compensate against — record the verification
                # failure on the applied action and surface the unavailable train loudly.
                failed = CancellationRepairAction(
                    code=PROJECTED_CANCELLATION_CODE,
                    node_id=node_id,
                    outcome="failed",
                    error=verification_error,
                )
                return CancellationRepairResult(
                    actions=tuple(actions),
                    failed=failed,
                    aborted=True,
                    dry_run=dry_run,
                    unavailable=verification_error,
                )
            rollback_note = _compensate(
                writer, objective_id=objective_id, node_id=node_id, prior=proven.persisted_status
            )
            failed = CancellationRepairAction(
                code=PROJECTED_CANCELLATION_CODE,
                node_id=node_id,
                outcome="failed",
                error=f"{verification_error}; {rollback_note}",
            )
            return CancellationRepairResult(
                actions=tuple(actions), failed=failed, aborted=True, dry_run=dry_run
            )
        actions.append(
            CancellationRepairAction(
                code=PROJECTED_CANCELLATION_CODE, node_id=node_id, outcome="applied"
            )
        )
    return CancellationRepairResult(
        actions=tuple(actions), failed=None, aborted=False, dry_run=dry_run
    )


def _reconstruct_or_none(reconstruct: Callable[[], TrainStatus]) -> TrainStatus | str:
    """One reconstruction; a typed failure returns its message (the unavailable arm)."""
    try:
        return reconstruct()
    except TrainReconstructionError as exc:
        return str(exc)


def _pinned(result: TrainStatus | str, objective_id: str) -> TrainStatus | str:
    """Pin a reconstruction proof to the write target. The reconstruction callback follows
    ``superseded_by`` on every call, so a mid-fix supersession can hand back the SUCCESSOR's
    projection — never a valid proof for a write against ``objective_id``. A redirected
    train reads as the unavailable arm (its message names the redirect)."""
    if isinstance(result, DeliveryTrain) and result.objective_id != objective_id:
        return (
            f"the reconstruction redirected to objective {result.objective_id} — objective "
            f"{objective_id} was superseded mid-repair, so no fresh proof can target it"
        )
    return result


def _verify_applied(
    objective_id: str, node_id: str, reconstruct: Callable[[], TrainStatus]
) -> tuple[str | None, bool]:
    """Post-APPLIED verification: the node must still be natively canceled, safely projected,
    and no longer repairable — on a proof pinned to the written objective. Returns
    ``(error, train_unavailable)`` — an unavailable (or mid-repair-superseded) train yields
    no observation to compensate against (reported loudly, no blind rollback); any other
    failure is post-write drift (native reopen, journal/branch/PR/header evidence appearing)
    → the compensation arm."""
    post = _pinned(_reconstruct_or_none(reconstruct), objective_id)
    if not isinstance(post, DeliveryTrain):
        detail = post if isinstance(post, str) else "the objective has no train"
        return (f"post-write verification could not reconstruct the train ({detail})", True)
    projected = {fact.node_id for fact in post.projected_canceled_nodes}
    repairable = {fact.node_id for fact in post.repairable_canceled_nodes}
    if node_id not in projected:
        return (
            f"post-write drift: node {node_id} is no longer a safely projected native "
            "cancellation (native reopen or new journal/branch/PR/header evidence)",
            False,
        )
    if node_id in repairable:
        return (f"post-write verification failed: node {node_id} still reads as repairable", False)
    return (None, False)


def _compensate(
    writer: NativeCancellationMetadataWriter,
    *,
    objective_id: str,
    node_id: str,
    prior: NodeStatus,
) -> str:
    """The compensation arm: conditionally write the attachment BACK from skipped to the
    prior persisted status (no native predicate — the drift may be a reopen), then VERIFY
    the rollback with a fresh conditional read (a dry-run compare against ``prior`` — the
    writer's own fresh state-bearing read is the observation; ``ALREADY_CONVERGED`` iff the
    attachment reads back as ``prior``). A failed rollback or a failed verification is
    included in the loud abort, never swallowed."""
    try:
        outcome = writer.write_node_cancellation_status(
            objective_id=objective_id,
            node_id=node_id,
            expected_status=NodeStatus.SKIPPED,
            new_status=prior,
            require_native_canceled=None,
            require_no_raw_publish_claims=False,
        )
    except ObjectiveStoreError as exc:
        return f"compensation rollback FAILED ({exc}) — the attachment may still read skipped"
    if outcome not in (
        CancellationRepairOutcome.APPLIED,
        CancellationRepairOutcome.ALREADY_CONVERGED,
    ):
        return (
            f"compensation rollback did not verify (writer answered {outcome.value}) — "
            "inspect the node attachment"
        )
    try:
        check = writer.write_node_cancellation_status(
            objective_id=objective_id,
            node_id=node_id,
            expected_status=prior,
            new_status=prior,
            require_native_canceled=None,
            require_no_raw_publish_claims=False,
            dry_run=True,
        )
    except ObjectiveStoreError as exc:
        return f"compensation rollback verification FAILED ({exc}) — inspect the node attachment"
    if check is not CancellationRepairOutcome.ALREADY_CONVERGED:
        return (
            f"compensation rollback did not verify: the fresh read answered {check.value} "
            f"instead of {prior.value} — inspect the node attachment"
        )
    return f"compensated: the attachment was rolled back to {prior.value} (verified)"
