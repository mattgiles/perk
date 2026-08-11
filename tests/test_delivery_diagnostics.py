"""Tests for the deterministic diagnosis policy + the race-aware cancellation repair
(``perk/delivery/diagnostics.py``, §8.54).

Pure in-memory fakes: the finding policy is a total mapping pinned category by category (with
the no-overlap invariant), and the repair pass is driven through a scripted reconstruct
sequence + a recording writer — covering fresh-proof races, conditional-writer races,
post-write drift with compensation, and the unavailable arms.
"""

from collections.abc import Callable

import pytest

from perk.backends.objective_store import CancellationRepairOutcome, ObjectiveStoreError
from perk.delivery import diagnostics
from perk.delivery.train import (
    STRUCTURAL_BLOCKER_CODES,
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    ProjectedCancellation,
    TrainFinding,
    TrainReconstructionError,
    TrainStatus,
)
from perk.objective import NodeStatus


def _finding(code: str, *, kind: FindingKind = FindingKind.BLOCKER, node_id: str | None = None):
    return TrainFinding(kind=kind, code=code, message=f"m {code}", node_id=node_id)


def _classify(
    code: str,
    *,
    kind: FindingKind = FindingKind.BLOCKER,
    node_id: str | None = None,
    repairable_nodes: frozenset[str] = frozenset(),
) -> diagnostics.FindingPolicy:
    return diagnostics.classify_finding(
        _finding(code, kind=kind, node_id=node_id),
        objective_id="10",
        repairable_nodes=repairable_nodes,
    )


# ----------------------------------------------------------------- the policy


class TestFindingPolicy:
    def test_category_sets_are_disjoint(self) -> None:
        # No code may live in two remediation categories — the policy must be a function.
        categories = [
            diagnostics.RECOVER_REMEDIATION_CODES,
            diagnostics.GITHUB_REPAIR_CODES,
            diagnostics.READ_AUTHORITY_CODES,
            diagnostics.EVIDENCE_AUDIT_CODES,
            diagnostics.IDENTITY_RESTORE_CODES,
            diagnostics.NO_REMEDIATION_CODES,
            frozenset({diagnostics.PROJECTED_CANCELLATION_CODE}),
            frozenset({"base_advanced", "checkpoint_drift"}),
        ]
        seen: set[str] = set()
        for category in categories:
            assert not (category & seen), f"overlap: {category & seen}"
            seen |= category

    def test_category_membership_is_pinned(self) -> None:
        assert {
            "active_operation",
            "publish_outcome_pending",
            "canceled_publication_pending",
        } == diagnostics.RECOVER_REMEDIATION_CODES
        assert {
            "missing_pr",
            "pr_wrong_base",
            "pr_wrong_head",
            "pr_closed",
            "stack_missing",
            "stack_divergent",
            "canceled_remote_work",
        } == diagnostics.GITHUB_REPAIR_CODES
        assert {"stack_read_unavailable", "base_unobserved"} == diagnostics.READ_AUTHORITY_CODES
        assert {
            "journal_corruption",
            "missing_publish_outcome",
            "checkpoint_after_abandoned_publish",
            "cancellation_evidence_unavailable",
        } == diagnostics.EVIDENCE_AUDIT_CODES
        assert {
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
        } == diagnostics.IDENTITY_RESTORE_CODES
        assert {"dynamic_singleton", "all_skipped"} == diagnostics.NO_REMEDIATION_CODES

    def test_every_structural_blocker_code_has_a_policy_home(self) -> None:
        # Every structural code maps into exactly one non-default category (never the
        # unknown-code fallback) — a grown catalog must grow the policy in the same change.
        categorized = (
            diagnostics.RECOVER_REMEDIATION_CODES
            | diagnostics.GITHUB_REPAIR_CODES
            | diagnostics.READ_AUTHORITY_CODES
            | diagnostics.EVIDENCE_AUDIT_CODES
            | diagnostics.IDENTITY_RESTORE_CODES
        )
        uncategorized = STRUCTURAL_BLOCKER_CODES - categorized
        assert uncategorized == set()

    def test_blocker_base_rule(self) -> None:
        policy = _classify("some_future_code")
        assert policy == diagnostics.FindingPolicy(
            severity="error", repairable=False, remediation=None
        )

    def test_info_base_rule(self) -> None:
        policy = _classify("some_future_notice", kind=FindingKind.INFO)
        assert policy == diagnostics.FindingPolicy(
            severity="info", repairable=False, remediation=None
        )

    def test_unknown_codes_can_never_become_repairable(self) -> None:
        # Even with a repairable node set present, an unknown code keeps the kind-derived
        # default and no auto remediation.
        policy = _classify("brand_new_code", node_id="1.3", repairable_nodes=frozenset({"1.3"}))
        assert policy.repairable is False and policy.remediation is None

    def test_repairable_projected_cancellation_is_the_one_repairable(self) -> None:
        policy = _classify(
            "canceled_unpublished_projected",
            kind=FindingKind.INFO,
            node_id="1.3",
            repairable_nodes=frozenset({"1.3"}),
        )
        assert policy.severity == "warning" and policy.repairable is True
        assert policy.remediation == "perk objective doctor 10 --fix"

    def test_already_skipped_projected_cancellation_stays_info(self) -> None:
        # Repairability is tied to the TYPED candidate set, never re-derived from text.
        policy = _classify(
            "canceled_unpublished_projected",
            kind=FindingKind.INFO,
            node_id="1.3",
            repairable_nodes=frozenset(),
        )
        assert policy == diagnostics.FindingPolicy(
            severity="info", repairable=False, remediation=None
        )

    @pytest.mark.parametrize(
        ("code", "fragment"),
        [
            ("publish_outcome_pending", "perk objective stack recover 10"),
            ("canceled_publication_pending", "perk objective stack recover 10"),
            ("active_operation", "/submit"),
            ("base_advanced", "perk objective stack sync 10 --base"),
            ("checkpoint_drift", "--adopt NODE"),
            ("canceled_remote_work", "on GitHub explicitly"),
            ("missing_pr", "perk objective stack status 10"),
            ("stack_read_unavailable", "restore the read authority"),
            ("journal_corruption", "never synthesizes history"),
            ("cancellation_evidence_unavailable", "append-only"),
            ("canceled_status_conflict", "restore the contradicted authority"),
            ("prefix_gap", "then replan only if"),
        ],
    )
    def test_remediation_fragments(self, code: str, fragment: str) -> None:
        policy = _classify(code)
        assert policy.remediation is not None and fragment in policy.remediation

    @pytest.mark.parametrize("code", ["dynamic_singleton", "all_skipped"])
    def test_lifecycle_projections_have_no_remediation(self, code: str) -> None:
        policy = _classify(code, kind=FindingKind.INFO)
        assert policy.remediation is None and policy.repairable is False


# ----------------------------------------------------------------- the repair pass


def _train(
    *,
    projected: tuple[ProjectedCancellation, ...] = (),
    repairable: tuple[ProjectedCancellation, ...] = (),
) -> DeliveryTrain:
    return DeliveryTrain(
        objective_id="10",
        objective_url="u",
        delivery_lineage="01L",
        base="main",
        redirected_from=None,
        layers=(),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="x"),
        projected_canceled_nodes=projected,
        repairable_canceled_nodes=repairable,
    )


def _candidate(node_id: str, persisted: NodeStatus = NodeStatus.PENDING) -> ProjectedCancellation:
    return ProjectedCancellation(node_id=node_id, persisted_status=persisted)


class _ScriptedReconstruct:
    """A queue of trains/exceptions; the last entry is reused once exhausted."""

    def __init__(self, *steps: TrainStatus | Exception) -> None:
        self._steps = list(steps)
        self.calls = 0

    def __call__(self) -> TrainStatus:
        self.calls += 1
        step = self._steps.pop(0) if len(self._steps) > 1 else self._steps[0]
        if isinstance(step, Exception):
            raise step
        return step


class _FakeWriter:
    """Records every conditional write; outcomes scripted per (node_id, new_status)."""

    def __init__(self, outcomes: dict[str, list[object]] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._outcomes = {k: list(v) for k, v in (outcomes or {}).items()}

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
    ) -> CancellationRepairOutcome:
        self.calls.append(
            {
                "objective_id": objective_id,
                "node_id": node_id,
                "expected_status": expected_status,
                "new_status": new_status,
                "require_native_canceled": require_native_canceled,
                "require_no_raw_publish_claims": require_no_raw_publish_claims,
                "dry_run": dry_run,
            }
        )
        queue = self._outcomes.get(node_id)
        if not queue:
            return CancellationRepairOutcome.APPLIED
        value = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(value, Exception):
            raise value
        assert isinstance(value, CancellationRepairOutcome)
        return value


def _repair(
    reconstruct: Callable[[], TrainStatus],
    writer: _FakeWriter,
    *,
    dry_run: bool = False,
) -> diagnostics.CancellationRepairResult:
    return diagnostics.repair_projected_cancellations(
        "10", writer=writer, reconstruct=reconstruct, dry_run=dry_run
    )


class TestCancellationRepair:
    def test_applies_candidates_in_node_order_with_fresh_proof(self) -> None:
        c13 = _candidate("1.3", NodeStatus.PLANNING)
        c21 = _candidate("2.1")
        before = _train(projected=(c13, c21), repairable=(c13, c21))
        after_13 = _train(projected=(_candidate("1.3", NodeStatus.SKIPPED), c21), repairable=(c21,))
        after_both = _train(
            projected=(
                _candidate("1.3", NodeStatus.SKIPPED),
                _candidate("2.1", NodeStatus.SKIPPED),
            ),
            repairable=(),
        )
        # initial, fresh(1.3), verify(1.3), fresh(2.1), verify(2.1)
        reconstruct = _ScriptedReconstruct(before, before, after_13, after_13, after_both)
        writer = _FakeWriter()
        result = _repair(reconstruct, writer)
        assert [a.outcome for a in result.actions] == ["applied", "applied"]
        assert [a.node_id for a in result.actions] == ["1.3", "2.1"]
        assert result.aborted is False and result.failed is None
        # The conditional write carries the exact fresh-proof predicates.
        assert writer.calls[0]["expected_status"] is NodeStatus.PLANNING
        assert writer.calls[0]["new_status"] is NodeStatus.SKIPPED
        assert writer.calls[0]["require_native_canceled"] is True
        assert writer.calls[0]["require_no_raw_publish_claims"] is True
        assert writer.calls[0]["dry_run"] is False
        assert writer.calls[1]["expected_status"] is NodeStatus.PENDING

    def test_dry_run_validates_but_never_verifies_or_compensates(self) -> None:
        c13 = _candidate("1.3")
        train = _train(projected=(c13,), repairable=(c13,))
        reconstruct = _ScriptedReconstruct(train)
        writer = _FakeWriter()
        result = _repair(reconstruct, writer, dry_run=True)
        assert [a.outcome for a in result.actions] == ["would_apply"]
        assert result.dry_run is True and result.aborted is False
        assert writer.calls[0]["dry_run"] is True
        # initial + fresh proof only: no post-write verification reconstruct.
        assert reconstruct.calls == 2

    def test_reopen_between_detection_and_per_action_proof_is_skipped(self) -> None:
        # The candidate vanished from the FRESH reconstruction (native reopen / new
        # evidence): skipped, never written.
        c13 = _candidate("1.3")
        initial = _train(projected=(c13,), repairable=(c13,))
        fresh = _train()  # no longer a candidate
        reconstruct = _ScriptedReconstruct(initial, fresh)
        writer = _FakeWriter()
        result = _repair(reconstruct, writer)
        assert [a.outcome for a in result.actions] == ["skipped"]
        assert writer.calls == []
        assert result.aborted is False

    def test_race_between_proof_and_conditional_writer_is_a_stale_skip(self) -> None:
        # The writer's OWN fresh read failed a predicate (STALE): skipped/not-applied,
        # never an abort.
        c13 = _candidate("1.3")
        train = _train(projected=(c13,), repairable=(c13,))
        reconstruct = _ScriptedReconstruct(train)
        writer = _FakeWriter({"1.3": [CancellationRepairOutcome.STALE]})
        result = _repair(reconstruct, writer)
        assert [a.outcome for a in result.actions] == ["skipped"]
        assert result.actions[0].error == "stale"
        assert result.aborted is False
        # No verification/compensation followed a non-applied write.
        assert len(writer.calls) == 1

    def test_already_converged_is_skipped_not_applied(self) -> None:
        c13 = _candidate("1.3")
        train = _train(projected=(c13,), repairable=(c13,))
        writer = _FakeWriter({"1.3": [CancellationRepairOutcome.ALREADY_CONVERGED]})
        result = _repair(_ScriptedReconstruct(train), writer)
        assert [a.outcome for a in result.actions] == ["skipped"]
        assert result.actions[0].error == "already_converged"

    def test_post_write_drift_compensates_and_aborts_loudly(self) -> None:
        # After APPLIED the verification reconstruct shows the node is no longer safely
        # projected (native reopen / new remote evidence): the attachment is rolled back
        # from skipped to the prior status with NO native predicate, then the pass aborts.
        c13 = _candidate("1.3", NodeStatus.IN_PROGRESS)
        before = _train(projected=(c13,), repairable=(c13,))
        drifted = _train()  # the node vanished from the projection facts entirely
        reconstruct = _ScriptedReconstruct(before, before, drifted)
        writer = _FakeWriter()
        result = _repair(reconstruct, writer)
        assert result.aborted is True and result.failed is not None
        assert result.failed.outcome == "failed"
        assert result.failed.error is not None
        assert "post-write drift" in result.failed.error
        assert "compensated" in result.failed.error
        forward, rollback = writer.calls
        assert rollback["expected_status"] is NodeStatus.SKIPPED
        assert rollback["new_status"] is NodeStatus.IN_PROGRESS
        assert rollback["require_native_canceled"] is None
        assert rollback["require_no_raw_publish_claims"] is False
        assert forward["require_native_canceled"] is True

    def test_failed_rollback_is_included_in_the_loud_abort(self) -> None:
        c13 = _candidate("1.3")
        before = _train(projected=(c13,), repairable=(c13,))
        drifted = _train()
        reconstruct = _ScriptedReconstruct(before, before, drifted)
        writer = _FakeWriter(
            {"1.3": [CancellationRepairOutcome.APPLIED, ObjectiveStoreError("write refused")]}
        )
        result = _repair(reconstruct, writer)
        assert result.aborted is True and result.failed is not None
        assert result.failed.error is not None
        assert "rollback FAILED" in result.failed.error
        assert "write refused" in result.failed.error

    def test_writer_infra_failure_aborts(self) -> None:
        c13 = _candidate("1.3")
        train = _train(projected=(c13,), repairable=(c13,))
        writer = _FakeWriter({"1.3": [ObjectiveStoreError("network down")]})
        result = _repair(_ScriptedReconstruct(train), writer)
        assert result.aborted is True and result.failed is not None
        assert result.failed.error == "network down"

    def test_initial_reconstruction_failure_is_unavailable(self) -> None:
        reconstruct = _ScriptedReconstruct(
            TrainReconstructionError("git down", error_type="git_error")
        )
        writer = _FakeWriter()
        result = _repair(reconstruct, writer)
        assert result.aborted is True and result.unavailable is not None
        assert "git down" in result.unavailable
        assert result.failed is None and writer.calls == []

    def test_post_apply_reconstruction_failure_records_the_verification_failure(self) -> None:
        # An applied write followed by an unavailable train: the failed action records the
        # verification failure; NO blind compensation runs (there is no observation).
        c13 = _candidate("1.3")
        before = _train(projected=(c13,), repairable=(c13,))
        reconstruct = _ScriptedReconstruct(
            before, before, TrainReconstructionError("gone", error_type="github_error")
        )
        writer = _FakeWriter()
        result = _repair(reconstruct, writer)
        assert result.aborted is True and result.unavailable is not None
        assert result.failed is not None and result.failed.outcome == "failed"
        assert result.failed.error is not None
        assert "could not reconstruct" in result.failed.error
        assert len(writer.calls) == 1  # forward write only — no compensation

    def test_idempotent_rerun_after_success_is_an_empty_completed_pass(self) -> None:
        converged = _train(projected=(_candidate("1.3", NodeStatus.SKIPPED),), repairable=())
        writer = _FakeWriter()
        result = _repair(_ScriptedReconstruct(converged), writer)
        assert result.actions == () and result.aborted is False
        assert writer.calls == []
