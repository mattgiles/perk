"""Tests for the two-part `perk objective doctor` (§8.54): the manifest-drift report, the
exact DeliveryTrain diagnosis, the train-repair state machine, the single active-objective
resolution (superseded-id redirect), and the exit-code table.

The store and the train reconstruction are both faked at their seams
(`resolve.resolve_objective_store` / `observe.reconstruct_repo_train`) — the projection's own
behavior is pinned in test_delivery_train.py; here the command's report/repair surface is.
"""

import json
import subprocess
from dataclasses import dataclass, field

from click.testing import CliRunner

from perk import github, objective
from perk.backends import objective_store, resolve
from perk.backends.objective_store import CancellationRepairOutcome
from perk.cli.cli import cli
from perk.delivery import observe
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    NoDeliveryTrain,
    ProjectedCancellation,
    TrainFinding,
    TrainReconstructionError,
)
from perk.objective import NodeStatus
from perk.objective.drift import DriftCode, DriftCondition, DriftReport, ObjectiveDriftSeverity

# ----------------------------------------------------------------- fakes


def _state(
    objective_id: str, header: dict[str, object] | None = None
) -> objective_store.ObjectiveState:
    return objective_store.ObjectiveState(
        id=objective_id,
        url=f"u/{objective_id}",
        title="t",
        header=dict(header or {}),
        nodes=(objective.ObjectiveNode(id="1.1", description="d", status=NodeStatus.PENDING),),
    )


@dataclass
class _FakeStore:
    """A GitHub-shaped store: no divergence surface, NOT a cancellation writer."""

    objectives: dict[str, objective_store.ObjectiveState] = field(default_factory=dict)
    drift: DriftReport = field(default_factory=DriftReport)
    repair: objective_store.RepairResult | None = None
    repair_calls: list[dict[str, object]] = field(default_factory=list)
    detect_calls: list[str] = field(default_factory=list)

    backend_id = "github"

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        return self.objectives.get(objective_id.removeprefix("#"))

    def detect_objective_drift(self, *, objective_id: str) -> DriftReport:
        self.detect_calls.append(objective_id)
        return self.drift

    def repair_objective_drift(
        self, *, objective_id: str, dry_run: bool = False
    ) -> objective_store.RepairResult:
        self.repair_calls.append({"objective_id": objective_id, "dry_run": dry_run})
        if self.repair is not None:
            return self.repair
        return objective_store.RepairResult(
            applied=(), failed=None, remaining=(), aborted=False, dry_run=dry_run
        )


@dataclass
class _FakeWriterStore(_FakeStore):
    """A Linear-project-shaped store: also satisfies the NativeCancellationMetadataWriter
    Protocol (structurally)."""

    backend_id = "linear"
    write_outcomes: list[object] = field(default_factory=list)
    writes: list[dict[str, object]] = field(default_factory=list)

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
        self.writes.append(
            {
                "objective_id": objective_id,
                "node_id": node_id,
                "expected_status": expected_status,
                "new_status": new_status,
                "require_native_canceled": require_native_canceled,
                "dry_run": dry_run,
            }
        )
        if not self.write_outcomes:
            return CancellationRepairOutcome.APPLIED
        value = self.write_outcomes.pop(0)
        assert isinstance(value, CancellationRepairOutcome)
        return value


def _train(
    *,
    objective_id: str = "42",
    findings: tuple[TrainFinding, ...] = (),
    projected: tuple[ProjectedCancellation, ...] = (),
    repairable: tuple[ProjectedCancellation, ...] = (),
) -> DeliveryTrain:
    return DeliveryTrain(
        objective_id=objective_id,
        objective_url=f"u/{objective_id}",
        delivery_lineage="01L",
        base="main",
        redirected_from=None,
        layers=(),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=findings,
        build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="x"),
        projected_canceled_nodes=projected,
        repairable_canceled_nodes=repairable,
    )


class _ScriptedTrains:
    """`observe.reconstruct_repo_train` stand-in: a queue of results/exceptions, last reused."""

    def __init__(self, *steps: object) -> None:
        self._steps = list(steps)
        self.calls: list[str] = []

    def __call__(self, repo_root, objective_id: str):
        self.calls.append(objective_id)
        step = self._steps.pop(0) if len(self._steps) > 1 else self._steps[0]
        if isinstance(step, Exception):
            raise step
        return step


def _invoke(args, *, git: bool = True):
    runner = CliRunner()
    with runner.isolated_filesystem():
        if git:
            subprocess.run(["git", "init", "-q"], check=True)
        return runner.invoke(cli, args)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _wire(monkeypatch, store, trains) -> None:
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    monkeypatch.setattr(observe, "reconstruct_repo_train", trains)


_BLOCKER = TrainFinding(
    kind=FindingKind.BLOCKER,
    code="checkpoint_drift",
    message="recorded X observed Y",
    node_id="1.1",
    plan_id="101",
)
_CANCEL_INFO = TrainFinding(
    kind=FindingKind.INFO,
    code="canceled_unpublished_projected",
    message="node 1.3 projects as skipped",
    node_id="1.3",
    plan_id=None,
)


# ----------------------------------------------------------------- detect


def test_detect_stacked_reports_policy_annotated_findings(monkeypatch):
    c13 = ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING)
    store = _FakeStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(
        _train(findings=(_BLOCKER, _CANCEL_INFO), projected=(c13,), repairable=(c13,))
    )
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    # Exact top-level order: the existing keys, then the additive §8.54 keys.
    assert list(payload.keys()) == [
        "success",
        "error_type",
        "objective",
        "drift",
        "fix",
        "redirected_from",
        "train",
        "train_fix",
    ]
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["drift"] == [] and payload["fix"] is None
    assert payload["redirected_from"] is None and payload["train_fix"] is None
    train = payload["train"]
    assert list(train.keys()) == [
        "state",
        "objective_id",
        "redirected_from",
        "error_type",
        "message",
        "blockers",
        "information",
    ]
    assert train["state"] == "stacked"
    assert train["error_type"] is None and train["message"] is None
    (blocker,) = train["blockers"]
    assert list(blocker.keys()) == [
        "code",
        "severity",
        "node_id",
        "plan_id",
        "message",
        "repairable",
        "remediation",
    ]
    assert blocker["code"] == "checkpoint_drift" and blocker["severity"] == "error"
    assert blocker["repairable"] is False
    assert blocker["remediation"] is not None and "--adopt NODE" in blocker["remediation"]
    (info,) = train["information"]
    assert info["code"] == "canceled_unpublished_projected"
    assert info["severity"] == "warning" and info["repairable"] is True
    assert info["remediation"] == "perk objective doctor 42 --fix"


def test_detect_incremental_is_the_no_train_message(monkeypatch):
    store = _FakeStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(
        NoDeliveryTrain(objective_id="42", objective_url="u", redirected_from=None, reason="inc")
    )
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    train = json.loads(result.output)["train"]
    assert train["state"] == "incremental" and train["message"] == "inc"
    assert train["error_type"] is None
    assert train["blockers"] == [] and train["information"] == []


def test_detect_train_unavailable_exits_1_with_the_assembled_report(monkeypatch):
    store = _FakeStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(TrainReconstructionError("git down", error_type="git_error"))
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is True  # assembled report; the exit conveys unavailability
    train = payload["train"]
    assert train["state"] == "unavailable"
    assert train["error_type"] == "git_error" and "git down" in train["message"]
    assert train["blockers"] == [] and train["information"] == []


def test_superseded_id_targets_the_active_successor(monkeypatch):
    store = _FakeStore(
        objectives={"42": _state("42", {"superseded_by": "#43"}), "43": _state("43")}
    )
    trains = _ScriptedTrains(_train(objective_id="43"))
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["objective"] == "43"
    assert payload["redirected_from"] == "42"
    assert payload["train"]["objective_id"] == "43"
    assert payload["train"]["redirected_from"] == "42"
    # Every read targeted the ACTIVE successor — both report parts.
    assert trains.calls == ["43"]
    assert store.detect_calls == ["43"]


def test_superseded_id_fix_writes_only_against_the_successor(monkeypatch):
    # `doctor OLD --fix` never mutates the predecessor: the manifest repair and the
    # conditional cancellation write both name the active successor.
    _authed(monkeypatch)
    c13 = ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING)
    before = _train(objective_id="43", projected=(c13,), repairable=(c13,))
    converged = _train(
        objective_id="43",
        projected=(ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.SKIPPED),),
        repairable=(),
    )
    store = _FakeWriterStore(
        objectives={"42": _state("42", {"superseded_by": "#43"}), "43": _state("43")}
    )
    trains = _ScriptedTrains(before, before, before, converged, converged)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    assert store.repair_calls == [{"objective_id": "43", "dry_run": False}]
    (write,) = store.writes
    assert write["objective_id"] == "43"
    assert set(trains.calls) == {"43"}


def test_not_a_repo_is_the_fail_envelope_exit_2(monkeypatch):
    result = _invoke(["objective", "doctor", "42", "--json"], git=False)
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "not_a_repo"


def test_active_resolution_failure_is_the_fail_envelope_exit_1(monkeypatch):
    store = _FakeStore()  # objective 42 does not exist
    _wire(monkeypatch, store, _ScriptedTrains(_train()))
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "objective_not_found"


# ----------------------------------------------------------------- fix


def _repairable_world() -> tuple[_FakeWriterStore, DeliveryTrain, DeliveryTrain]:
    c13 = ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING)
    before = _train(findings=(_BLOCKER, _CANCEL_INFO), projected=(c13,), repairable=(c13,))
    converged = _train(
        findings=(_BLOCKER,),
        projected=(ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.SKIPPED),),
        repairable=(),
    )
    store = _FakeWriterStore(objectives={"42": _state("42")})
    return store, before, converged


def test_fix_applies_the_cancellation_repair_and_reports_remaining(monkeypatch):
    _authed(monkeypatch)
    store, before, converged = _repairable_world()
    # doctor initial, repair initial, fresh proof, post-write verify, final diagnosis.
    trains = _ScriptedTrains(before, before, before, converged, converged)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0  # report-only drift remains → still a clean exit
    payload = json.loads(result.output)
    fix = payload["train_fix"]
    assert list(fix.keys()) == [
        "state",
        "applied",
        "skipped",
        "failed",
        "remaining",
        "aborted",
        "dry_run",
    ]
    assert fix["state"] == "completed" and fix["aborted"] is False
    (action,) = fix["applied"]
    assert list(action.keys()) == ["code", "node_id", "outcome", "error"]
    assert action == {
        "code": "canceled_unpublished_projected",
        "node_id": "1.3",
        "outcome": "applied",
        "error": None,
    }
    assert fix["failed"] is None and fix["skipped"] == []
    # The final diagnosis rides `remaining` (the report-only blocker survives).
    assert [f["code"] for f in fix["remaining"]] == ["checkpoint_drift"]
    # The conditional write targeted the active objective with the fresh-proof predicates.
    (write,) = store.writes
    assert write["objective_id"] == "42" and write["node_id"] == "1.3"
    assert write["expected_status"] is NodeStatus.PENDING
    assert write["new_status"] is NodeStatus.SKIPPED
    assert write["require_native_canceled"] is True


def test_fix_dry_run_would_apply_without_writing(monkeypatch):
    store, before, _converged = _repairable_world()
    trains = _ScriptedTrains(before)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--dry-run", "--json"])
    assert result.exit_code == 0
    fix = json.loads(result.output)["train_fix"]
    assert fix["state"] == "completed" and fix["dry_run"] is True
    assert [a["outcome"] for a in fix["applied"]] == ["would_apply"]
    (write,) = store.writes
    assert write["dry_run"] is True


def test_fix_write_verification_failure_is_an_aborted_train_fix(monkeypatch):
    _authed(monkeypatch)
    store, before, _converged = _repairable_world()
    store.write_outcomes.extend(
        [
            CancellationRepairOutcome.APPLIED,  # forward write
            CancellationRepairOutcome.APPLIED,  # compensation rollback
            CancellationRepairOutcome.ALREADY_CONVERGED,  # rollback verification read
        ]
    )
    drifted = _train(findings=(_BLOCKER,))  # the node vanished from the projection facts
    trains = _ScriptedTrains(before, before, before, drifted)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is True  # assembled report; exit conveys the abort
    fix = payload["train_fix"]
    assert fix["state"] == "aborted" and fix["aborted"] is True
    assert fix["failed"]["outcome"] == "failed"
    assert "post-write drift" in fix["failed"]["error"]
    # Forward write + compensation rollback + the rollback-verification read all hit the
    # writer seam.
    assert [w["new_status"] for w in store.writes] == [
        NodeStatus.SKIPPED,
        NodeStatus.PENDING,
        NodeStatus.PENDING,
    ]
    assert store.writes[1]["require_native_canceled"] is None
    assert store.writes[2]["dry_run"] is True


def test_fix_current_train_unavailable_is_the_unavailable_state(monkeypatch):
    _authed(monkeypatch)
    store = _FakeWriterStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(TrainReconstructionError("gone", error_type="github_error"))
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 1
    fix = json.loads(result.output)["train_fix"]
    assert fix["state"] == "unavailable" and fix["aborted"] is True
    assert fix["failed"] is None and fix["remaining"] == []
    assert store.writes == []


def test_fix_manifest_abort_skips_every_train_action(monkeypatch):
    _authed(monkeypatch)
    store, before, _converged = _repairable_world()
    store.repair = objective_store.RepairResult(
        applied=(),
        failed=objective_store.RepairAction(DriftCode.DELETED_PHASE_MILESTONE, "1.1", "boom"),
        remaining=(),
        aborted=True,
        dry_run=False,
    )
    trains = _ScriptedTrains(before)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 1
    fix = json.loads(result.output)["train_fix"]
    assert fix["state"] == "skipped_manifest_abort" and fix["aborted"] is True
    assert fix["failed"] is None and fix["applied"] == []
    # The initial diagnosis remains (as `remaining`); no train write ran.
    assert [f["code"] for f in fix["remaining"]] == [
        "checkpoint_drift",
        "canceled_unpublished_projected",
    ]
    assert store.writes == []


def test_fix_semantic_blockers_are_never_repaired(monkeypatch):
    # A train with only nonrepairable blockers: --fix runs an empty completed pass — the
    # writer is never called for identity/topology/status conflicts.
    _authed(monkeypatch)
    store = _FakeWriterStore(objectives={"42": _state("42")})
    blocked = _train(
        findings=(
            TrainFinding(kind=FindingKind.BLOCKER, code="canceled_published_layer", message="m"),
            TrainFinding(kind=FindingKind.BLOCKER, code="wrong_owner", message="m"),
        )
    )
    trains = _ScriptedTrains(blocked)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    fix = json.loads(result.output)["train_fix"]
    assert fix["state"] == "completed"
    assert fix["applied"] == [] and fix["skipped"] == []
    assert store.writes == []


def test_fix_on_a_non_writer_store_never_attempts_a_write(monkeypatch):
    # A GitHub-shaped store (no writer seam): even a train claiming repairable candidates
    # (impossible in production — no provenance) runs an empty completed pass.
    _authed(monkeypatch)
    c13 = ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING)
    store = _FakeStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(_train(projected=(c13,), repairable=(c13,)))
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    fix = json.loads(result.output)["train_fix"]
    assert fix["state"] == "completed" and fix["applied"] == []


def test_fix_incremental_is_an_empty_completed_pass(monkeypatch):
    _authed(monkeypatch)
    store = _FakeWriterStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(
        NoDeliveryTrain(objective_id="42", objective_url="u", redirected_from=None, reason="inc")
    )
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    fix = json.loads(result.output)["train_fix"]
    assert fix["state"] == "completed" and fix["remaining"] == []


def test_fix_idempotent_rerun_after_success_is_clean(monkeypatch):
    _authed(monkeypatch)
    store, _before, converged = _repairable_world()
    trains = _ScriptedTrains(converged)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    fix = json.loads(result.output)["train_fix"]
    assert fix["state"] == "completed" and fix["applied"] == []
    assert store.writes == []  # nothing repairable remains


def test_fix_manifest_and_train_reports_are_both_present_for_linear(monkeypatch):
    # The two-part report: Linear manifest drift AND the train diagnosis ride one payload.
    _authed(monkeypatch)
    store, before, converged = _repairable_world()
    store.drift = DriftReport(
        conditions=(
            DriftCondition(
                code=DriftCode.DELETED_PHASE_MILESTONE,
                severity=ObjectiveDriftSeverity.WARNING,
                node_id=None,
                target="Phase 1",
                message="milestone gone",
                repairable=True,
            ),
        )
    )
    trains = _ScriptedTrains(before, before, before, converged, converged)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    payload = json.loads(result.output)
    assert [c["code"] for c in payload["drift"]] == ["deleted_phase_milestone"]
    assert payload["train"]["state"] == "stacked"
    assert payload["train_fix"]["state"] == "completed"
    # The manifest repair targeted the same active id.
    assert store.repair_calls == [{"objective_id": "42", "dry_run": False}]
