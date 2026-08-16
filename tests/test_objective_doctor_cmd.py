"""Tests for the two-part `perk objective doctor` (§8.54): the manifest-drift report, the
exact DeliveryTrain diagnosis, the train-repair state machine, the single active-objective
resolution (superseded-id redirect), and the exit-code table.

The store, façade-backed report diagnosis, and retained repair-proof reconstruction are faked
at their explicit seams. The projection's own behavior is pinned in test_delivery_train.py;
here the command's report/repair surface is.
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective
from perk.backends import issue_backend, objective_store, resolve
from perk.backends.objective_store import CancellationRepairOutcome
from perk.cli.cli import cli
from perk.cli.commands.objective import doctor_cmd
from perk.delivery import DeliveryError, StatusResult, observe
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    NoDeliveryTrain,
    ProjectedCancellation,
    TrainFinding,
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


# `_FakeStore.carrier` sentinel: default = the GitHub shape (the objective issue itself);
# tests override it with a sentinel identifier (the Linear-project shape), None, or an
# Exception to raise from the resolution seam.
_DEFAULT_CARRIER: object = object()


@dataclass
class _FakeStore:
    """A GitHub-shaped store: no divergence surface, NOT a cancellation writer."""

    objectives: dict[str, objective_store.ObjectiveState] = field(default_factory=dict)
    drift: DriftReport = field(default_factory=DriftReport)
    repair: objective_store.RepairResult | None = None
    repair_calls: list[dict[str, object]] = field(default_factory=list)
    detect_calls: list[str] = field(default_factory=list)
    carrier: object = _DEFAULT_CARRIER

    backend_id = "github"

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        return self.objectives.get(objective_id.removeprefix("#"))

    def journal_carrier_id(self, *, objective_id: str) -> str | None:
        if self.carrier is not _DEFAULT_CARRIER:
            if isinstance(self.carrier, Exception):
                raise self.carrier
            assert self.carrier is None or isinstance(self.carrier, str)
            return self.carrier
        state = self.get_objective(objective_id=objective_id)
        return None if state is None else objective_id.removeprefix("#")

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
    """Two explicit scripted seams over one ordered scenario.

    ``status`` returns the façade's ``StatusResult``/``DeliveryError`` contract for report
    diagnosis; ``reconstruct`` returns the retained internal train status for cancellation
    proof reads. The shared step queue preserves effect-boundary ordering assertions.
    """

    def __init__(self, *steps: object) -> None:
        self._steps = list(steps)
        self.calls: list[str] = []
        self.status_calls: list[str] = []
        self.reconstruction_calls: list[str] = []

    def _next(self, objective_id: str):
        self.calls.append(objective_id)
        step = self._steps.pop(0) if len(self._steps) > 1 else self._steps[0]
        if isinstance(step, Exception):
            raise step
        return step

    def status(self, request):
        self.status_calls.append(request.objective_id)
        step = self._next(request.objective_id)
        if isinstance(step, NoDeliveryTrain):
            return StatusResult(
                objective_id=step.objective_id,
                objective_url=step.objective_url,
                redirected_from=step.redirected_from,
                train=None,
                no_train_reason=step.reason,
            )
        return StatusResult(
            objective_id=step.objective_id,
            objective_url=step.objective_url,
            redirected_from=step.redirected_from,
            train=step,
            no_train_reason=None,
        )

    def reconstruct(self, repo_root, objective_id: str):
        self.reconstruction_calls.append(objective_id)
        return self._next(objective_id)


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


def _wire(monkeypatch, store, trains, *, reads: dict[str, object] | None = None) -> list[Path]:
    """Wire the doctor seams and return the repository roots used to resolve ``Delivery``.

    ``reads`` maps carrier id → ``AdoptableIssue`` for the kind-corruption check's presence-only
    read (default: every read misses → no finding); an ``Exception`` value raises from the read
    seam instead.
    """
    delivery_roots: list[Path] = []

    def resolve_delivery(repo_root: Path):
        delivery_roots.append(repo_root)
        return trains

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    monkeypatch.setattr(doctor_cmd, "resolve_delivery", resolve_delivery)
    monkeypatch.setattr(observe, "reconstruct_repo_train", trains.reconstruct)

    class _FakeIssueBackend:
        def read_issue(self, *, issue_id: str):
            value = (reads or {}).get(issue_id)
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: _FakeIssueBackend())
    return delivery_roots


def _carrier_read(carrier: str, *, both: bool = True) -> issue_backend.AdoptableIssue:
    """An issue-tier carrier read; ``both=True`` bears BOTH headers (the corruption shape)."""
    return issue_backend.AdoptableIssue(
        id=carrier,
        url=f"u/{carrier}",
        title="t",
        body="b",
        state="OPEN",
        already_plan=both,
        already_objective=True,
    )


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
        "corruption",
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
    trains = _ScriptedTrains(DeliveryError("git down", error_type="git_error"))
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
    delivery_roots = _wire(monkeypatch, store, trains)
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
    assert trains.status_calls == ["42", "42"]
    assert trains.reconstruction_calls == ["42", "42", "42"]
    assert len(delivery_roots) == 1


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
    trains = _ScriptedTrains(DeliveryError("gone", error_type="github_error"))
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


def test_fix_manifest_action_serialization_preserves_the_conditional_error_key(monkeypatch):
    # §8.54: `error` rides ONLY the failed action — a successful action's serialized form
    # has no `error` key at all (the envelope-pin promotion preserves the hand-built
    # payload's conditional omission byte-for-byte).
    _authed(monkeypatch)
    store, before, _converged = _repairable_world()
    store.repair = objective_store.RepairResult(
        applied=(objective_store.RepairAction(DriftCode.DELETED_PHASE_MILESTONE, None),),
        failed=objective_store.RepairAction(DriftCode.DELETED_PHASE_MILESTONE, "1.1", "boom"),
        remaining=(),
        aborted=True,
        dry_run=False,
    )
    trains = _ScriptedTrains(before)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    fix = json.loads(result.output)["fix"]
    (applied,) = fix["applied"]
    assert list(applied.keys()) == ["code", "node_id"]  # no `error` key on success
    assert list(fix["failed"].keys()) == ["code", "node_id", "error"]
    assert fix["failed"] == {
        "code": "deleted_phase_milestone",
        "node_id": "1.1",
        "error": "boom",
    }


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


def test_manifest_repair_with_applied_changes_rediagnoses_before_train_actions(monkeypatch):
    # A manifest repair that APPLIED changes must refresh the train diagnosis before any
    # train action — the fix routing follows the post-repair world, never the pre-repair
    # snapshot (here the fresh diagnosis is incremental: no candidate is ever written).
    _authed(monkeypatch)
    c13 = ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING)
    before = _train(findings=(_CANCEL_INFO,), projected=(c13,), repairable=(c13,))
    store = _FakeWriterStore(objectives={"42": _state("42")})
    store.repair = objective_store.RepairResult(
        applied=(objective_store.RepairAction(code=DriftCode.MISSING_NODE_ISSUE, node_id="1.1"),),
        failed=None,
        remaining=(),
        aborted=False,
        dry_run=False,
    )
    incremental = NoDeliveryTrain(
        objective_id="42", objective_url="u", redirected_from=None, reason="now incremental"
    )
    trains = _ScriptedTrains(before, incremental)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    fix = payload["train_fix"]
    assert fix["state"] == "completed" and fix["applied"] == [] and fix["skipped"] == []
    assert store.writes == []  # the stale pre-repair candidate was never written
    assert trains.calls == ["42", "42"]  # initial diagnosis + the post-manifest re-diagnosis


# ------------------------------------------- the both-headers corruption signature


def _incremental_trains() -> _ScriptedTrains:
    return _ScriptedTrains(
        NoDeliveryTrain(objective_id="42", objective_url="u", redirected_from=None, reason="inc")
    )


def test_corruption_both_headers_yields_one_finding(monkeypatch):
    # The kind-corruption signature (report-only): a carrier bearing BOTH headers yields
    # exactly one finding — and the report stays clean (exit 0).
    store = _FakeStore(objectives={"42": _state("42")})
    _wire(monkeypatch, store, _incremental_trains(), reads={"42": _carrier_read("42")})
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    (finding,) = payload["corruption"]
    assert list(finding.keys()) == ["code", "carrier", "message", "remediation"]
    assert finding["code"] == "both_headers" and finding["carrier"] == "42"
    assert "BOTH objective-header and plan-header" in finding["message"]
    # Direction-neutral remediation: provenance inspection or supersession, never auto-repair.
    assert "perk objective replan 42" in finding["remediation"]
    assert "no automatic repair" in finding["remediation"]


def test_corruption_human_render_prints_only_when_detected(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(objectives={"42": _state("42")})
    _wire(monkeypatch, store, _incremental_trains(), reads={"42": _carrier_read("42")})
    result = _invoke(["objective", "doctor", "42"])
    assert result.exit_code == 0
    assert "Corruption: 1 finding(s)" in result.output
    assert "ERROR both_headers [#42]:" in result.output
    assert "remediation: report-only, no automatic repair" in result.output

    # A clean carrier prints NOTHING — clean runs' output stays byte-unchanged.
    store2 = _FakeStore(objectives={"42": _state("42")})
    _wire(monkeypatch, store2, _incremental_trains(), reads={"42": _carrier_read("42", both=False)})
    result2 = _invoke(["objective", "doctor", "42"])
    assert result2.exit_code == 0
    assert "Corruption" not in result2.output


def test_corruption_linear_sentinel_carrier_is_resolved(monkeypatch):
    # The carrier-resolution proof: on a Linear-project-shaped store the §8.43 carrier is the
    # metadata SENTINEL issue — the finding names the sentinel, not the Project id.
    store = _FakeStore(objectives={"42": _state("42")}, carrier="SEN-9")
    _wire(monkeypatch, store, _incremental_trains(), reads={"SEN-9": _carrier_read("SEN-9")})
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    (finding,) = json.loads(result.output)["corruption"]
    assert finding["carrier"] == "SEN-9"
    assert "#SEN-9" in finding["message"]


def test_corruption_targets_the_active_successor_after_redirect(monkeypatch):
    # The redirect proof for the corruption check: with BOTH carriers wired corrupt, the
    # single finding names the ACTIVE successor — a predecessor-targeted read would surface
    # a finding naming "42" instead of silently missing on the default-miss mask.
    store = _FakeStore(
        objectives={"42": _state("42", {"superseded_by": "#43"}), "43": _state("43")}
    )
    trains = _ScriptedTrains(
        NoDeliveryTrain(objective_id="43", objective_url="u", redirected_from=None, reason="inc")
    )
    _wire(
        monkeypatch,
        store,
        trains,
        reads={"42": _carrier_read("42"), "43": _carrier_read("43")},
    )
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["redirected_from"] == "42"
    (finding,) = payload["corruption"]
    assert finding["carrier"] == "43"
    # The active id rides the remediation string, not the requested predecessor's.
    assert "perk objective replan 43" in finding["remediation"]


def test_corruption_healthy_carrier_is_empty(monkeypatch):
    store = _FakeStore(objectives={"42": _state("42")})
    _wire(monkeypatch, store, _incremental_trains(), reads={"42": _carrier_read("42", both=False)})
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["corruption"] == []


def test_corruption_no_carrier_is_empty(monkeypatch):
    store = _FakeStore(objectives={"42": _state("42")}, carrier=None)
    _wire(monkeypatch, store, _incremental_trains())
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["corruption"] == []


def test_corruption_fix_never_touches_it(monkeypatch):
    # `--fix` has NO repair arm for the signature: the finding survives a fix pass verbatim
    # and the pass itself stays a clean completed run (exit 0).
    _authed(monkeypatch)
    store = _FakeStore(objectives={"42": _state("42")})
    _wire(monkeypatch, store, _incremental_trains(), reads={"42": _carrier_read("42")})
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    (finding,) = payload["corruption"]
    assert finding["code"] == "both_headers"
    assert payload["fix"]["applied"] == []  # no manifest repair references it
    assert payload["train_fix"]["applied"] == []  # no train repair references it


def test_carrier_read_failure_is_the_fail_envelope_github_error(monkeypatch):
    # An IssueBackendError from the presence-only carrier read fails the whole report as
    # github_error (§8.54: the assembly boundary's posture) — never a silent empty check.
    store = _FakeStore(objectives={"42": _state("42")})
    _wire(
        monkeypatch,
        store,
        _incremental_trains(),
        reads={"42": issue_backend.IssueBackendError("carrier read down")},
    )
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "github_error"
    assert "carrier read down" in payload["message"]


def test_carrier_resolution_failure_is_the_fail_envelope_github_error(monkeypatch):
    # The other raising seam: a §8.43 journal_carrier_id failure rides the same arm.
    store = _FakeStore(
        objectives={"42": _state("42")},
        carrier=issue_backend.IssueBackendError("carrier resolution down"),
    )
    _wire(monkeypatch, store, _incremental_trains())
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "github_error"
    assert "carrier resolution down" in payload["message"]


# ----------------------------------------------------------------- the human render


def test_human_render_reports_both_parts_with_remediation(monkeypatch):
    _authed(monkeypatch)
    c13 = ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING)
    store = _FakeStore(objectives={"42": _state("42")})
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
    trains = _ScriptedTrains(
        _train(findings=(_BLOCKER, _CANCEL_INFO), projected=(c13,), repairable=(c13,))
    )
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42"])
    assert result.exit_code == 0
    out = result.output
    # Part 1: the manifest condition line.
    assert "1 manifest drift condition(s)" in out
    assert "deleted_phase_milestone: milestone gone" in out
    # Part 2: both findings with severity, anchor, message, and the policy remediation.
    assert "Train: 2 finding(s)" in out
    assert "checkpoint_drift [1.1]: recorded X observed Y" in out
    assert "--adopt NODE" in out  # checkpoint_drift's inspect/adopt remediation
    assert "canceled_unpublished_projected [1.3]" in out
    assert "remediation: perk objective doctor 42 --fix" in out


def test_human_render_clean_report_and_incremental_train(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(
        NoDeliveryTrain(objective_id="42", objective_url="u", redirected_from=None, reason="inc")
    )
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42"])
    assert result.exit_code == 0
    assert "no manifest drift" in result.output
    assert "Train: inc" in result.output


def test_human_render_unavailable_train_names_the_typed_error(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(objectives={"42": _state("42")})
    trains = _ScriptedTrains(DeliveryError("gone", error_type="github_error"))
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42"])
    assert result.exit_code == 1
    assert "Train unavailable:" in result.output
    assert "[github_error] gone" in result.output


def test_human_render_redirect_names_both_ids(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(
        objectives={"42": _state("42", {"superseded_by": "#43"}), "43": _state("43")}
    )
    trains = _ScriptedTrains(_train(objective_id="43"))
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42"])
    assert result.exit_code == 0
    assert "Objective #42 → active objective #43" in result.output


def test_human_render_train_fix_summary_and_failure(monkeypatch):
    _authed(monkeypatch)
    store, before, converged = _repairable_world()
    trains = _ScriptedTrains(before, before, before, converged, converged)
    _wire(monkeypatch, store, trains)
    result = _invoke(["objective", "doctor", "42", "--fix"])
    assert result.exit_code == 0
    assert "train fix (completed): applied 1 repair(s), 0 skipped" in result.output

    store2, before2, _converged2 = _repairable_world()
    store2.write_outcomes.extend(
        [
            CancellationRepairOutcome.APPLIED,
            CancellationRepairOutcome.APPLIED,
            CancellationRepairOutcome.ALREADY_CONVERGED,
        ]
    )
    drifted = _train(findings=(_BLOCKER,))
    trains2 = _ScriptedTrains(before2, before2, before2, drifted)
    _wire(monkeypatch, store2, trains2)
    result2 = _invoke(["objective", "doctor", "42", "--fix"])
    assert result2.exit_code == 1
    assert "train fix failed:" in result2.output
    assert "post-write drift" in result2.output
