"""Hermetic fake-driven tests for the recover operation (contracts.md §8.51).

Mirrors ``test_delivery_sync.py``'s in-memory world: a scriptable mini remote, a recording
persistence fake seeded with unresolved prepared records, in-memory residue (temp refs,
worktree directories, manifest scans), and a timeline pinning the load-bearing ordering
(classify → act → sweep, refs → worktrees → one prune). OFFLINE — no git / gh / network.
"""

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from perk import objective
from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import ObjectiveRef, ObjectiveState
from perk.delivery import continuation, oplock, recover
from perk.delivery import sync as sync_mod
from perk.delivery import transfer as transfer_mod
from perk.delivery.finalize import LandFinalization, LearnConsumeUpdate, ObjectiveLandUpdate
from perk.delivery.journal import (
    EventRole,
    JournalEvent,
    JournalFold,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
    canonical_payload,
    mint_operation_id,
)
from perk.delivery.persistence import AppendResult, UnresolvedOperationError
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    NoDeliveryTrain,
    TrainFinding,
    TrainLayer,
)
from perk.github import GitHubError
from perk.github.prs import PullRequest
from perk.github.stacks import (
    MergeAsyncProbe,
    MergeAsyncProbeState,
    PrDeliveryFacts,
    PrMergedEvidence,
    StackRestEntry,
    StackRestFacts,
)
from perk.substrate import git

ROOT = Path("/repo")
WT_ROOT = Path("/wt")
OBJECTIVE = "500"
LINEAGE = "01LINEAGE"
MAIN = "m" * 40
P1 = "1" * 40
P2 = "2" * 40
P3 = "3" * 40
C2 = "b" * 40  # layer-2's recorded candidate
R3 = "c" * 40  # layer-3's recorded candidate


def _layer(
    node_id: str,
    plan_id: str,
    *,
    pr_number: int,
    parent_checkpoint_sha: str,
    published_head_sha: str,
    expected_pr_base: str | None = None,
    publication: LayerPublication = LayerPublication.UNPUBLISHED,
) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=f"plan-{plan_id}",
        pr_number=pr_number,
        intent=LayerIntent.PLANNED,
        publication=publication,
        git=LayerGit.UNKNOWN,
        pr=LayerPr.ABSENT,
        membership=LayerMembership.NOT_APPLICABLE,
        writer=LayerWriter.FREE,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=parent_checkpoint_sha,
        published_head_sha=published_head_sha,
        observed_remote_head_sha=None,
        observed_pr_base=None,
        expected_pr_base=expected_pr_base,
    )


class _FakePersistence:
    def __init__(self, world: "_World", unresolved: list[PreparedRecord]) -> None:
        self._world = world
        self.unresolved_records: dict[str, PreparedRecord] = {r.operation_id: r for r in unresolved}
        self.prepared: list[PreparedRecord] = []
        self.outcomes: list[OutcomeRecord] = []
        self.checkpoints: list[tuple[str, str, str]] = []
        # Accepted handles by operation id (the LAND async arm) — folded onto the
        # unresolved operation.
        self.accepted_records: dict[str, OutcomeRecord] = {}
        # Resolved operations (seeded, or moved here by append_outcome): the STATEFUL fold —
        # a re-read sees same-invocation conclusions (the §8.51 fresh-fold semantics).
        self.completed: list[tuple[PreparedRecord, OutcomeRecord]] = []
        # Fail-once injection for the roll-forward's invariant-20 arm.
        self.outcome_boom_once: Exception | None = None
        # Ids whose fold reads EMPTY — models a predecessor whose journal walk (predecessors
        # only) cannot see a successor-recorded operation.
        self.empty_fold_ids: set[str] = set()

    def _event(self, record, role: EventRole, comment_id: str) -> JournalEvent:
        return JournalEvent(
            record=record,
            role=role,
            operation_id=record.operation_id,
            canonical_payload=canonical_payload(record),
            comment_id=comment_id,
            created_at=record.created,
        )

    def read_journal(self, objective_id: str) -> JournalFold:
        if objective_id in self.empty_fold_ids:
            return JournalFold(events=(), operations={}, unresolved=(), delivery_lineage=LINEAGE)
        ops = {}
        for record, outcome in self.completed:
            ops[record.operation_id] = OperationState(
                operation_id=record.operation_id,
                kind=record.operation_kind,
                prepared=self._event(record, EventRole.PREPARED, "c1"),
                accepted=None,
                outcome=self._event(outcome, outcome.role, "c3"),
            )
        for op_id, record in self.unresolved_records.items():
            accepted = self.accepted_records.get(op_id)
            ops[op_id] = OperationState(
                operation_id=op_id,
                kind=record.operation_kind,
                prepared=self._event(record, EventRole.PREPARED, "c1"),
                accepted=None
                if accepted is None
                else self._event(accepted, EventRole.ACCEPTED, "c2"),
                outcome=None,
            )
        return JournalFold(
            events=(),
            operations=ops,
            unresolved=tuple(op for op in ops.values() if not op.resolved),
            delivery_lineage=LINEAGE,
        )

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        if self.unresolved_records:
            raise UnresolvedOperationError("an operation is already unresolved")
        self._world.timeline.append(("prepared", record.operation_id))
        self.prepared.append(record)
        self.unresolved_records[record.operation_id] = record
        return AppendResult(record.operation_id, EventRole.PREPARED, existed=False)

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        self._world.timeline.append(("outcome", record.role.value, record.operation_id))
        if self.outcome_boom_once is not None:
            boom = self.outcome_boom_once
            self.outcome_boom_once = None
            raise boom
        self.outcomes.append(record)
        moved = self.unresolved_records.pop(record.operation_id, None)
        if moved is not None and record.role in (EventRole.COMPLETED, EventRole.ABANDONED):
            self.completed.append((moved, record))
        elif moved is not None:
            self.unresolved_records[record.operation_id] = moved  # accepted keeps it live
            self.accepted_records[record.operation_id] = record
        return AppendResult(record.operation_id, record.role, existed=False)

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None:
        self._world.timeline.append(("checkpoints", plan_id))
        self.checkpoints.append((plan_id, parent_checkpoint_sha, published_head_sha))

    # The transfer arm's typed writers (recorded; unused by the no-carry scenarios here).

    def transfer_plan_ownership(
        self, plan_id: str, *, objective_id: str, objective_node_id: str
    ) -> None:
        self._world.timeline.append(("ownership", plan_id, objective_id, objective_node_id))

    def stamp_layer_identity(
        self, plan_id: str, *, delivery_lineage: str, predecessor_plan_id: str | None
    ) -> None:
        self._world.timeline.append(("identity", plan_id, delivery_lineage, predecessor_plan_id))

    def clear_delivery_metadata(self, plan_id: str) -> None:
        self._world.timeline.append(("clear", plan_id))


class _World:
    """The injectable mini remote + residue + recorders for one recover invocation."""

    def __init__(
        self, layers: list[TrainLayer], *, unresolved: list[PreparedRecord] | None = None
    ) -> None:
        self.layers = layers
        self.no_train = False
        self.findings: tuple[TrainFinding, ...] = ()
        self.timeline: list[tuple] = []
        self.persistence = _FakePersistence(self, unresolved or [])
        # Git/GitHub state.
        self.remote: dict[str, str | None] = {"main": MAIN}
        self.pr_entries: dict[int, tuple[str, str, str]] = {}
        self.pr_head_overrides: dict[int, str] = {}
        self.stack_members: list[int] | None = None
        # Residue state.
        self.refs: dict[str, str] = {}
        self.worktree_names: list[str] = []
        self.stale_admin_names: list[str] = []
        self.open_pr_branches: dict[str, int] = {}
        self.scan = continuation.ManifestScan(manifests=(), unparseable=())
        self.delete_ref_boom: set[str] = set()
        self.worktree_remove_boom: set[str] = set()
        self.prune_boom: Exception | None = None
        self.read_boom: dict[str, Exception] = {}
        self.lock_busy = False
        self.sleeps: list[float] = []
        # Transfer-arm state: objectives readable by id / findable by run_id.
        self.objectives: dict[str, ObjectiveState] = {}
        self.objectives_by_run: dict[str, ObjectiveRef] = {}
        self.supersede_calls: list[dict] = []
        self.finalized: list[tuple[str, str]] = []
        # LAND-arm state (§8.51): the scripted handle probe, per-PR merged evidence, the
        # recording finalize seam, plans readable for consumed_learn, and the close log.
        self.probe_results: list[MergeAsyncProbe] = []
        self.probe_calls: list[tuple[int, str]] = []
        self.pr_merged: dict[int, PrMergedEvidence | Exception | None] = {}
        self.finalize_calls: list[tuple[str, str]] = []
        self.finalize_boom: dict[str, Exception] = {}
        self.plans: dict[str, PlanState] = {}
        self.closed_objectives: list[str] = []
        self.close_boom: Exception | None = None
        self.backend_id = "github"

    # ------------------------------------------------------------- seams

    @contextlib.contextmanager
    def _lock(self, root: Path) -> Iterator[None]:
        if self.lock_busy:
            raise oplock.OperationLockBusy("another stack operation holds the lock")
        yield

    def _reconstruct(self, root: Path, objective_id: str):
        if self.no_train:
            return NoDeliveryTrain(
                objective_id=OBJECTIVE,
                objective_url="u",
                redirected_from=None,
                reason="objective is incremental",
            )
        return DeliveryTrain(
            objective_id=OBJECTIVE,
            objective_url="u",
            delivery_lineage=LINEAGE,
            base="main",
            redirected_from=None,
            layers=tuple(self.layers),
            published_prefix_len=0,
            unresolved_operation=None,
            findings=self.findings,
            build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="veto"),
            observed_base_head_sha=MAIN,
        )

    def _fetch(self, root: Path, refspecs: list[str]) -> None:
        self.timeline.append(("fetch", tuple(refspecs)))
        if exc := self.read_boom.get("fetch"):
            raise exc

    def _remote_head(self, root: Path, branch: str) -> str | None:
        self.timeline.append(("remote_head", branch))
        if exc := self.read_boom.get("remote_head"):
            raise exc
        return self.remote.get(branch)

    def _pr_facts(self, *, number: int, repo_root: Path) -> PrDeliveryFacts | None:
        if exc := self.read_boom.get("pr_facts"):
            raise exc
        entry = self.pr_entries.get(number)
        if entry is None:
            return None
        branch, base, state = entry
        return PrDeliveryFacts(
            number=number,
            state=state,
            is_draft=True,
            base_ref=base,
            head_ref=branch,
            head_sha=self.pr_head_overrides.get(number, self.remote.get(branch) or ""),
        )

    def _stack_read(self, *, number: int, repo_root: Path) -> StackRestFacts | None:
        if exc := self.read_boom.get("stack_read"):
            raise exc
        if self.stack_members is None or number not in self.stack_members:
            return None
        entries = tuple(
            StackRestEntry(
                pr_number=n, state="open", draft=True, merged=False, head_ref="", head_sha=""
            )
            for n in self.stack_members
        )
        return StackRestFacts(number=9, size=len(entries), entries=entries)

    def _list_refs(self, root: Path, prefix: str) -> list[str]:
        return sorted(ref for ref in self.refs if ref.startswith(prefix))

    def _delete_ref(self, root: Path, ref: str) -> None:
        if ref in self.delete_ref_boom:
            raise git.GitError("cannot delete")
        self.timeline.append(("delete_ref", ref))
        self.refs.pop(ref, None)

    def _worktree_remove(self, root: Path, path: Path) -> None:
        if path.name in self.worktree_remove_boom:
            raise git.GitError("cannot remove")
        self.timeline.append(("worktree_remove", str(path)))
        self.worktree_names.remove(path.name)

    def _worktree_prune(self, root: Path) -> None:
        if self.prune_boom is not None:
            raise self.prune_boom
        self.timeline.append(("worktree_prune",))

    def _iter_manifests(self, root: Path) -> continuation.ManifestScan:
        return self.scan

    def _worktree_dirs(self, root: Path) -> list[Path]:
        return [WT_ROOT / name for name in sorted(self.worktree_names)]

    def _worktree_admin_dirs(self, root: Path) -> list[Path]:
        # Git's inventory: every on-disk entry plus the stale (directory-gone) records.
        return [WT_ROOT / name for name in sorted({*self.worktree_names, *self.stale_admin_names})]

    def _pr_for_branch(self, *, branch: str, repo_root: Path):
        self.timeline.append(("pr_for_branch", branch))
        number = self.open_pr_branches.get(branch)
        state = "OPEN"
        if number is None:
            matches = [
                (candidate, base, candidate_state)
                for candidate, (head, base, candidate_state) in self.pr_entries.items()
                if head == branch
            ]
            chosen = next((item for item in matches if item[2] == "OPEN"), None)
            if chosen is None and matches:
                chosen = matches[0]
            if chosen is None:
                return None
            number, _base, state = chosen
        return PullRequest(
            number=number,
            url="u",
            is_draft=True,
            state=state,
            existed=True,
            base_ref=self.pr_entries.get(number, ("", "", ""))[1],
            head_ref=branch,
        )

    # ------------------------------------------------------------- transfer seams

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        return self.objectives.get(objective_id)

    def find_objective(self, *, run_id: str) -> ObjectiveRef | None:
        self.timeline.append(("find_objective", run_id))
        return self.objectives_by_run.get(run_id)

    def supersede_objective(self, **kwargs) -> ObjectiveRef | None:
        self.timeline.append(("supersede", kwargs["run_id"]))
        self.supersede_calls.append(kwargs)
        return self.objectives_by_run.get(kwargs["run_id"])

    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool:
        self.timeline.append(("finalize", old_objective_id, new_objective_id))
        self.finalized.append((old_objective_id, new_objective_id))
        return True

    def get_plan(self, *, issue_id: str):
        return self.plans.get(issue_id)

    # ------------------------------------------------------------- LAND seams (§8.51)

    def _merge_probe(self, *, number: int, uuid: str, repo_root: Path) -> MergeAsyncProbe:
        self.timeline.append(("merge_probe", number, uuid))
        self.probe_calls.append((number, uuid))
        if not self.probe_results:
            return MergeAsyncProbe(state="unreadable", sha=None, message="unscripted")
        return self.probe_results.pop(0)

    def _merged_evidence(self, *, number: int, repo_root: Path) -> PrMergedEvidence | None:
        self.timeline.append(("merged_evidence", number))
        entry = self.pr_merged.get(number)
        if isinstance(entry, Exception):
            raise entry
        return entry

    def _finalize(self, repo_root: Path, *, landed, pr_base: str, close_objective_on_complete=True):
        self.timeline.append(("finalize", landed.plan_id, pr_base))
        assert close_objective_on_complete is False
        boom = self.finalize_boom.get(landed.plan_id)
        if boom is not None:
            raise boom
        self.finalize_calls.append((landed.plan_id, pr_base))
        return LandFinalization(
            learn_state="pending",
            plan_issue_closed=True,
            objective=ObjectiveLandUpdate(OBJECTIVE, (), None),
            learn=LearnConsumeUpdate((), "no_consumed_learn"),
        )

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        self.timeline.append(("close_objective", objective_id))
        if self.close_boom is not None:
            raise self.close_boom
        self.closed_objectives.append(objective_id)
        state = self.objectives.get(objective_id)
        if state is not None:  # the stateful lifecycle read: a close flips the state
            self.objectives[objective_id] = ObjectiveState(
                id=state.id,
                url=state.url,
                title=state.title,
                header=state.header,
                nodes=state.nodes,
                native_cancellations=state.native_cancellations,
                state="closed",
            )
        return True

    def _transfer_seams(self, root: Path) -> transfer_mod.TransferSeams:
        return transfer_mod.TransferSeams(
            repo_root=root,
            store=self,
            issues=self,
            persistence=self.persistence,
            reconstruct=self._reconstruct,
            now=lambda: "2026-02-02T00:00:00Z",
        )

    # ------------------------------------------------------------- driving

    def recover(
        self,
        *,
        dry_run: bool = False,
        abandon: bool = False,
        accept_prefix: bool = False,
        operation: str | None = None,
        approve: Callable[[recover.AbandonPreview], bool] | None = None,
        accept_approve: Callable[[recover.AcceptPrefixPreview], bool] | None = None,
        objective_id: str = OBJECTIVE,
    ) -> recover.RecoverResult:
        return recover.recover_operations(
            ROOT,
            objective_id=objective_id,
            worktree_root=WT_ROOT,
            dry_run=dry_run,
            abandon=abandon,
            accept_prefix=accept_prefix,
            operation_id=operation,
            approve=approve,
            accept_approve=accept_approve,
            reconstruct=self._reconstruct,
            persistence_factory=lambda root: self.persistence,
            transfer_seams_factory=self._transfer_seams,
            pr_facts=self._pr_facts,
            stack_read=self._stack_read,
            merge_probe=self._merge_probe,
            merged_evidence=self._merged_evidence,
            finalize=self._finalize,
            issues_factory=lambda root: self,
            store_factory=lambda root: self,
            fetch=self._fetch,
            remote_head=self._remote_head,
            pr_for_branch=self._pr_for_branch,
            list_refs=self._list_refs,
            delete_ref=self._delete_ref,
            worktree_remove=self._worktree_remove,
            worktree_prune=self._worktree_prune,
            iter_manifests=self._iter_manifests,
            worktree_dirs=self._worktree_dirs,
            worktree_admin_dirs=self._worktree_admin_dirs,
            lock=self._lock,
            sleep=self.sleeps.append,
            now=lambda: "2026-02-02T00:00:00Z",
        )

    def events(self, kind: str) -> list[tuple]:
        return [t for t in self.timeline if t[0] == kind]

    def assert_nothing_journaled(self) -> None:
        assert self.persistence.prepared == []
        assert self.persistence.outcomes == []
        assert self.persistence.checkpoints == []


def _three_layer_world(unresolved: list[PreparedRecord] | None = None) -> _World:
    world = _World(
        [
            _layer("1.1", "101", pr_number=201, parent_checkpoint_sha=MAIN, published_head_sha=P1),
            _layer("1.2", "102", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=P2),
            _layer("1.3", "103", pr_number=203, parent_checkpoint_sha=P2, published_head_sha=P3),
        ],
        unresolved=unresolved,
    )
    world.remote.update({"plan-101": P1, "plan-102": P2, "plan-103": P3})
    world.pr_entries = {
        201: ("plan-101", "main", "OPEN"),
        202: ("plan-102", "plan-101", "OPEN"),
        203: ("plan-103", "plan-102", "OPEN"),
    }
    world.stack_members = [201, 202, 203]
    return world


def _sync_record(
    *,
    operation_kind: OperationKind = OperationKind.SYNC,
    after_extra: dict | None = None,
) -> PreparedRecord:
    after: dict = {
        "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
        "prs": [
            {"number": 202, "head_sha": C2, "base": "plan-101"},
            {"number": 203, "head_sha": R3, "base": "plan-102"},
        ],
        "base_parent": None,
    }
    if after_extra:
        after.update(after_extra)
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=operation_kind,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="2026-01-01T00:00:00Z",
        affected_plans=("102", "103"),
        before={
            "base": None,
            "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}],
            "prs": [
                {"number": 202, "head_sha": P2, "base": "plan-101"},
                {"number": 203, "head_sha": P3, "base": "plan-102"},
            ],
            "stack": {"members": [201, 202, 203]},
        },
        after=after,
    )


def _publish_record() -> PreparedRecord:
    """A mid-flight publication of layer 1.3 (its PR staged; the stack not yet appended)."""
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.PUBLISH,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="2026-01-01T00:00:00Z",
        affected_plans=("103",),
        before={
            "branch": {"ref": "plan-103", "sha": P3},
            "pr": {"number": 203, "base": "plan-102", "head_sha": P3, "state": "OPEN"},
            "stack": {"members": [201, 202, 203]},
        },
        after={
            "branch": {"ref": "plan-103", "sha": R3},
            "pr": {"base": "plan-102", "head_sha": R3},
            "stack": {"members": [201, 202, 203]},
        },
    )


def _foreign_record(kind: OperationKind) -> PreparedRecord:
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=kind,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="2026-01-01T00:00:00Z",
        affected_plans=("102",),
        before={"anything": True},
        after={"anything": True},
    )


def _recover_error(world: _World, **kwargs) -> recover.RecoverError:
    with pytest.raises(recover.RecoverError) as excinfo:
        world.recover(**kwargs)
    return excinfo.value


# ----------------------------------------------------------------- classification per kind


def test_sync_all_after_target_rolls_forward_automatically():
    record = _sync_record()
    world = _three_layer_world([record])
    world.remote.update({"plan-102": C2, "plan-103": R3})  # the push landed
    result = world.recover()
    (row,) = result.operations
    assert row.operation_id == record.operation_id
    assert row.kind == "sync" and row.classification == "all_after"
    assert row.action == "rolled_forward"
    assert result.selection_required is False and result.dry_run is False
    # Record-driven steps 13-14 under the SAME operation: checkpoints then completed.
    assert world.persistence.checkpoints == [("102", P1, C2), ("103", C2, R3)]
    assert [o.role for o in world.persistence.outcomes] == [EventRole.COMPLETED]
    assert world.persistence.prepared == []  # never a new operation


def test_adopt_record_rolls_forward_identically():
    a2 = "e" * 40
    record = _sync_record(
        operation_kind=OperationKind.ADOPT,
        after_extra={"adopted": {"node_id": "1.2", "plan_id": "102", "remote_head": a2}},
    )
    world = _three_layer_world([record])
    world.remote.update({"plan-102": C2, "plan-103": R3})
    result = world.recover()
    (row,) = result.operations
    assert row.kind == "adopt" and row.action == "rolled_forward"
    assert world.persistence.checkpoints == [("102", P1, C2), ("103", C2, R3)]


def test_sync_all_before_is_reported_with_the_owning_command_hint():
    record = _sync_record()
    world = _three_layer_world([record])  # remote still at the before set
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_before" and row.action == "reported"
    assert "--abandon" in row.detail and "perk objective stack sync" in row.detail
    world.assert_nothing_journaled()


def test_sync_mixed_observation_is_reported_fail_closed():
    record = _sync_record()
    world = _three_layer_world([record])
    world.remote["plan-102"] = C2  # one applied, one at before
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    assert "refusing to guess" in row.detail
    world.assert_nothing_journaled()


def test_sync_corroboration_failure_classifies_mixed():
    # The fresh reconstruction no longer matches the record (a foreign plan id): fail
    # closed to a reported mixed row — never an error, never a conclusion.
    record = _sync_record()
    world = _three_layer_world([record])
    world.layers[1] = _layer(
        "1.2", "999", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=P2
    )
    world.remote.update({"plan-102": C2, "plan-103": R3})
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    assert "corroboration" in row.detail
    world.assert_nothing_journaled()


def test_publish_all_after_reports_the_submit_rerun():
    record = _publish_record()
    world = _three_layer_world([record])
    world.remote["plan-103"] = R3  # branch + PR + stack are all at after
    result = world.recover()
    (row,) = result.operations
    assert row.kind == "publish" and row.classification == "all_after"
    assert row.action == "reported"  # recover NEVER rolls a publish forward
    assert "/submit" in row.detail and "plan #103" in row.detail
    assert world.events("pr_for_branch") == [("pr_for_branch", "plan-103")]
    world.assert_nothing_journaled()


@pytest.mark.parametrize("drift", ["pr_base", "pr_head", "stack"])
def test_publish_all_after_requires_the_full_pr_and_stack_proof(drift):
    record = _publish_record()
    world = _three_layer_world([record])
    world.remote["plan-103"] = R3
    if drift == "pr_base":
        world.pr_entries[203] = ("plan-103", "main", "OPEN")
    elif drift == "pr_head":
        # The head-selector finds the right PR, but its delivery facts disagree with after.
        world.pr_head_overrides[203] = P3
    else:
        world.stack_members = [201, 202]
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    world.assert_nothing_journaled()


def test_publish_all_before_requires_the_full_proof():
    record = _publish_record()
    world = _three_layer_world([record])  # branch at before; PR + stack corroborate
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_before" and row.action == "reported"
    assert "--abandon" in row.detail

    # The SAME branch observation with a drifted PR base is mixed — branch-only proof is
    # never enough (the full publish proof: branch + PR facts + stack membership).
    world = _three_layer_world([_publish_record()])
    world.pr_entries[203] = ("plan-103", "main", "OPEN")  # re-staged base
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"


@pytest.mark.parametrize(
    "malformation",
    ["missing_branch_sha", "partial_pr", "unknown_numbered_pr", "missing_stack_members"],
)
def test_publish_all_before_refuses_unknown_or_malformed_record_facts(malformation):
    record = _publish_record()
    before_branch: dict[str, object] = {"ref": "plan-103", "sha": P3}
    before_pr: dict[str, object] = {
        "number": 203,
        "base": "plan-102",
        "head_sha": P3,
        "state": "OPEN",
    }
    before_stack: dict[str, object] = {"members": [201, 202, 203]}
    if malformation == "missing_branch_sha":
        before_branch.pop("sha")
    elif malformation == "partial_pr":
        before_pr.pop("state")
    elif malformation == "unknown_numbered_pr":
        before_pr = {"number": 203, "base": None, "head_sha": None, "state": None}
    else:
        before_stack = {}
    before: dict[str, object] = {
        "branch": before_branch,
        "pr": before_pr,
        "stack": before_stack,
    }
    world = _three_layer_world([replace(record, before=before)])
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and "unreadable" in row.detail
    error = _recover_error(world, abandon=True, approve=lambda preview: True)
    assert error.error_type == "abandon_blocked"
    world.assert_nothing_journaled()


def test_publish_all_before_requires_exact_live_pr_facts():
    record = _publish_record()
    world = _three_layer_world([record])
    world.pr_entries.pop(203)  # unknown is not equality/absence proof for a numbered PR
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"
    assert "expected" in row.detail and "observed" in row.detail
    world.assert_nothing_journaled()


def test_land_with_undecodable_payload_is_mixed_and_never_observed():
    # A LAND record whose payload does not strict-decode classifies mixed (fail closed) —
    # never probed, never observed, nothing journaled.
    record = _foreign_record(OperationKind.LAND)
    world = _three_layer_world([record])
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    assert "undecodable" in row.detail
    assert world.events("merge_probe") == [] and world.events("merged_evidence") == []
    world.assert_nothing_journaled()


# ----------------------------------------------------------------- target selection


def test_several_unresolved_without_operation_is_a_selection_required_report():
    first = _sync_record()
    second = _publish_record()
    world = _three_layer_world([first, second])
    world.remote.update({"plan-102": C2, "plan-103": R3})  # first would be all_after
    result = world.recover()
    assert result.selection_required is True
    assert [row.action for row in result.operations] == ["reported", "reported"]
    # The all-after non-target row carries the rerun hint, not an action.
    assert f"--operation {first.operation_id}" in result.operations[0].detail
    world.assert_nothing_journaled()


def test_operation_flag_selects_the_action_target():
    first = _sync_record()
    second = _foreign_record(OperationKind.TRANSFER)
    world = _three_layer_world([first, second])
    world.remote.update({"plan-102": C2, "plan-103": R3})
    result = world.recover(operation=first.operation_id)
    assert result.selection_required is False
    by_id = {row.operation_id: row for row in result.operations}
    assert by_id[first.operation_id].action == "rolled_forward"
    assert by_id[second.operation_id].action == "reported"
    assert [o.role for o in world.persistence.outcomes] == [EventRole.COMPLETED]


def test_unknown_operation_is_operation_not_found():
    record = _sync_record()
    world = _three_layer_world([record])
    error = _recover_error(world, operation="01UNKNOWNOP")
    assert error.error_type == "operation_not_found"
    assert record.operation_id in str(error)
    world.assert_nothing_journaled()


def test_abandon_with_several_unresolved_is_operation_ambiguous():
    first = _sync_record()
    second = _publish_record()
    world = _three_layer_world([first, second])
    error = _recover_error(world, abandon=True)
    assert error.error_type == "operation_ambiguous"
    assert first.operation_id in str(error) and second.operation_id in str(error)
    world.assert_nothing_journaled()


def test_abandon_with_nothing_unresolved_is_operation_not_found():
    world = _three_layer_world()
    error = _recover_error(world, abandon=True)
    assert error.error_type == "operation_not_found"


# ----------------------------------------------------------------- the abandon arm


def test_abandon_all_before_journals_the_post_confirmation_proof():
    record = _sync_record()
    world = _three_layer_world([record])
    previews: list[recover.AbandonPreview] = []
    result = world.recover(abandon=True, approve=lambda p: previews.append(p) or True)
    (row,) = result.operations
    assert row.action == "abandoned"
    (preview,) = previews
    assert preview.operation_id == record.operation_id and preview.kind == "sync"
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.ABANDONED
    assert outcome.observed == {
        "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}]
    }
    assert world.persistence.checkpoints == []


def test_abandon_reclassifies_after_confirmation():
    # The world moves during the confirmation pause: the pre-confirmation all-before is
    # stale, the re-classification refuses, and NOTHING is journaled (decision 18).
    record = _sync_record()
    world = _three_layer_world([record])

    def approve(preview: recover.AbandonPreview) -> bool:
        world.remote["plan-103"] = "9" * 40
        return True

    error = _recover_error(world, abandon=True, approve=approve)
    assert error.error_type == "abandon_blocked"
    assert "while the confirmation was pending" in str(error)
    world.assert_nothing_journaled()


def test_abandon_blocked_on_all_after_and_mixed():
    for mutate, expected in [
        (lambda w: w.remote.update({"plan-102": C2, "plan-103": R3}), "all_after"),
        (lambda w: w.remote.update({"plan-102": C2}), "mixed"),
    ]:
        record = _sync_record()
        world = _three_layer_world([record])
        mutate(world)
        error = _recover_error(world, abandon=True, approve=lambda p: True)
        assert error.error_type == "abandon_blocked"
        assert expected in str(error)
        world.assert_nothing_journaled()


def test_abandon_declined_is_a_success_row_with_an_untouched_journal():
    record = _sync_record()
    world = _three_layer_world([record])
    result = world.recover(abandon=True, approve=lambda p: False)
    (row,) = result.operations
    assert row.action == "declined"
    assert "declined" in row.detail
    world.assert_nothing_journaled()


def test_abandon_on_mixed_land_is_abandon_blocked():
    record = _foreign_record(OperationKind.LAND)
    world = _three_layer_world([record])
    error = _recover_error(world, abandon=True, approve=lambda p: True)
    assert error.error_type == "abandon_blocked"
    world.assert_nothing_journaled()


def test_abandon_publish_journals_the_publish_shaped_proof():
    record = _publish_record()
    world = _three_layer_world([record])
    result = world.recover(abandon=True, approve=lambda p: True)
    (row,) = result.operations
    assert row.action == "abandoned"
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.ABANDONED
    assert outcome.observed == {
        "branch": {"ref": "plan-103", "sha": P3},
        "pr": {"number": 203, "base": "plan-102", "head_sha": P3, "state": "OPEN"},
        "stack": {"members": [201, 202, 203]},
    }


# ----------------------------------------------------------------- --dry-run


def test_dry_run_reports_would_be_actions_and_sweeps_nothing():
    op = mint_operation_id()
    record = _sync_record()
    world = _three_layer_world([record])
    world.remote.update({"plan-102": C2, "plan-103": R3})  # the target would roll forward
    world.refs[f"refs/perk/sync/{op}/plan-102"] = C2
    world.worktree_names.append(f"sync-{op}")
    result = world.recover(dry_run=True)
    assert result.dry_run is True
    (row,) = result.operations
    assert row.action == "reported" and "would roll this forward" in row.detail
    world.assert_nothing_journaled()
    # The would-be sweep rides the envelope; nothing was deleted.
    assert result.swept_refs == (f"refs/perk/sync/{op}/plan-102",)
    assert result.swept_worktrees == (str(WT_ROOT / f"sync-{op}"),)
    assert world.events("delete_ref") == [] and world.events("worktree_remove") == []
    assert world.events("worktree_prune") == []
    assert world.refs != {} and world.worktree_names != []


def test_dry_run_with_abandon_is_invalid_input():
    world = _three_layer_world([_sync_record()])
    error = _recover_error(world, dry_run=True, abandon=True)
    assert error.error_type == "invalid_input"
    assert world.timeline == []  # refused before any observation


# ----------------------------------------------------------------- the orphan sweep


def _protecting_manifest(operation_id: str) -> continuation.ContinuationManifest:
    return continuation.ContinuationManifest(
        operation_id=operation_id,
        objective_id="777",  # a FOREIGN objective's lineage still protects its residue
        delivery_lineage="01OTHERLINEAGE",
        run_id="01RUN",
        include_base=False,
        captured_base_head=None,
        layers=(),
        conflict_node_id="9.9",
        worktree_path=str(WT_ROOT / f"sync-{operation_id}"),
        created="2026-01-01T00:00:00Z",
    )


def test_sweep_removes_unprotected_residue_refs_then_worktrees_then_prune():
    orphan = mint_operation_id()
    protected = mint_operation_id()
    world = _three_layer_world()
    world.refs[f"refs/perk/sync/{orphan}/plan-102"] = C2
    world.refs[f"refs/perk/sync/{protected}/plan-999"] = P1
    world.refs["refs/perk/sync/garbage/x"] = P1  # not a perk-minted shape: untouched
    world.worktree_names += [f"sync-{orphan}", f"sync-{protected}", "sync-notaulid", "plan-101"]
    world.scan = continuation.ManifestScan(
        manifests=(_protecting_manifest(protected),), unparseable=()
    )
    result = world.recover()
    assert result.swept_refs == (f"refs/perk/sync/{orphan}/plan-102",)
    assert result.swept_worktrees == (str(WT_ROOT / f"sync-{orphan}"),)
    assert result.sweep_failures == () and result.sweep_skipped is None
    # The protected + non-minted residue survives.
    assert f"refs/perk/sync/{protected}/plan-999" in world.refs
    assert "refs/perk/sync/garbage/x" in world.refs
    assert set(world.worktree_names) == {f"sync-{protected}", "sync-notaulid", "plan-101"}
    # Ordering: refs, then worktrees, then ONE prune.
    kinds = [t[0] for t in world.timeline if t[0].startswith(("delete_ref", "worktree"))]
    assert kinds == ["delete_ref", "worktree_remove", "worktree_prune"]


def test_sweep_skips_entirely_while_any_manifest_is_unparseable():
    orphan = mint_operation_id()
    world = _three_layer_world()
    world.refs[f"refs/perk/sync/{orphan}/plan-102"] = C2
    world.scan = continuation.ManifestScan(
        manifests=(), unparseable=(Path("/main/.perk/workflow/sync-continuations/x.json"),)
    )
    result = world.recover()
    assert result.sweep_skipped is not None and "unparseable" in result.sweep_skipped
    assert result.swept_refs == () and result.swept_worktrees == ()
    assert world.refs != {}  # nothing deleted


def test_sweep_records_per_item_failures_and_continues():
    broken = mint_operation_id()
    fine = mint_operation_id()
    world = _three_layer_world()
    world.refs[f"refs/perk/sync/{broken}/plan-102"] = C2
    world.refs[f"refs/perk/sync/{fine}/plan-103"] = P3
    world.delete_ref_boom.add(f"refs/perk/sync/{broken}/plan-102")
    world.worktree_names.append(f"sync-{fine}")
    result = world.recover()
    assert result.swept_refs == (f"refs/perk/sync/{fine}/plan-103",)
    assert result.swept_worktrees == (str(WT_ROOT / f"sync-{fine}"),)
    (failure,) = result.sweep_failures
    assert failure.target == f"refs/perk/sync/{broken}/plan-102"
    assert "cannot delete" in failure.error


def test_typed_refusals_never_sweep():
    orphan = mint_operation_id()
    first = _sync_record()
    second = _publish_record()
    world = _three_layer_world([first, second])
    world.refs[f"refs/perk/sync/{orphan}/plan-102"] = C2
    error = _recover_error(world, abandon=True)  # operation_ambiguous
    assert error.error_type == "operation_ambiguous"
    assert world.refs != {} and world.events("delete_ref") == []


def test_declined_abandon_still_sweeps():
    # A declined confirmation is a SUCCESS envelope — the sweep still runs.
    orphan = mint_operation_id()
    record = _sync_record()
    world = _three_layer_world([record])
    world.refs[f"refs/perk/sync/{orphan}/plan-102"] = C2
    result = world.recover(abandon=True, approve=lambda p: False)
    assert result.operations[0].action == "declined"
    assert result.swept_refs == (f"refs/perk/sync/{orphan}/plan-102",)


# ----------------------------------------------------------------- gates


def test_busy_lock_is_operation_in_progress():
    world = _three_layer_world([_sync_record()])
    world.lock_busy = True
    error = _recover_error(world)
    assert error.error_type == "operation_in_progress"
    assert world.timeline == []


def test_no_train_is_not_stacked():
    world = _three_layer_world()
    world.no_train = True
    error = _recover_error(world)
    assert error.error_type == "not_stacked"


def test_no_unresolved_and_no_residue_is_a_clean_report():
    world = _three_layer_world()
    result = world.recover()
    assert result.operations == () and result.selection_required is False
    assert result.swept_refs == () and result.swept_worktrees == ()
    assert result.sweep_skipped is None
    assert result.objective_id == OBJECTIVE and result.objective_url == "u"


# ----------------------------------------------------------------- classification-read failures


@pytest.mark.parametrize("seam", ["fetch", "remote_head", "pr_facts", "stack_read"])
def test_classification_read_failure_prevents_every_conclusion_and_sweep(seam):
    record = _sync_record() if seam in {"fetch", "remote_head"} else _publish_record()
    world = _three_layer_world([record])
    if record.operation_kind is OperationKind.PUBLISH:
        world.remote["plan-103"] = R3
    elif seam == "fetch":
        # Classification reaches all-after; the roll-forward tail's fresh fetch then fails
        # before any checkpoint/outcome and before the post-conclusion orphan sweep.
        world.remote.update({"plan-102": C2, "plan-103": R3})
    failure: Exception = (
        git.GitError(f"{seam} unavailable")
        if seam in {"fetch", "remote_head"}
        else GitHubError(f"{seam} unavailable")
    )
    world.read_boom[seam] = failure
    orphan = mint_operation_id()
    world.refs[f"refs/perk/sync/{orphan}/plan-102"] = C2
    world.worktree_names.append(f"sync-{orphan}")

    expected_error = sync_mod.SyncError if seam == "fetch" else type(failure)
    with pytest.raises(expected_error, match=f"{seam} unavailable"):
        world.recover()

    world.assert_nothing_journaled()
    assert world.events("delete_ref") == []
    assert world.events("worktree_remove") == []
    assert world.events("worktree_prune") == []
    assert f"refs/perk/sync/{orphan}/plan-102" in world.refs
    assert f"sync-{orphan}" in world.worktree_names


# ----------------------------------------------------------------- the structural gate


def test_structural_blockers_refuse_recovery_before_any_conclusion():
    # Sync's fail-closed identity/topology gate applies to recover too: a mis-linked layer
    # can still corroborate on branch/checkpoint fields, and an all-after roll-forward
    # would checkpoint into the wrong plan.
    record = _sync_record()
    world = _three_layer_world([record])
    world.remote["plan-102"] = C2
    world.remote["plan-103"] = R3  # all-after: would roll forward without the gate
    world.findings = (
        TrainFinding(
            kind=FindingKind.BLOCKER,
            code="wrong_owner",
            message="plan #102 carries no objective_id",
            node_id="1.2",
            plan_id="102",
        ),
    )
    world.refs["refs/perk/sync/01ORPHANORPHANORPHANORPHAN/x"] = C2
    with pytest.raises(sync_mod.SyncError) as excinfo:
        world.recover()
    assert excinfo.value.error_type == "claimed_prefix_malformed"
    assert "wrong_owner" in str(excinfo.value)
    world.assert_nothing_journaled()
    assert world.events("delete_ref") == []  # a typed refusal never sweeps


def _cancellation_findings() -> tuple[TrainFinding, ...]:
    """Structural findings a REAL unresolved PUBLISH legitimately produces on a
    native-canceled layer (§8.54's crash windows)."""
    return (
        TrainFinding(
            kind=FindingKind.BLOCKER,
            code="canceled_remote_work",
            message="node 1.3 is natively canceled but branch 'plan-103' exists on the remote",
            node_id="1.3",
            plan_id="103",
        ),
        TrainFinding(
            kind=FindingKind.BLOCKER,
            code="canceled_publication_pending",
            message="node 1.3 is natively canceled while a PUBLISH is unresolved",
            node_id="1.3",
            plan_id="103",
        ),
    )


def test_sole_unresolved_publish_routes_past_the_structural_gate():
    # §8.54 fold-first: a real unresolved PUBLISH produces structural cancellation/remote
    # findings ITSELF — the generic gate would dead-end exactly the operation recover exists
    # to conclude. The sole-PUBLISH route reaches the publish classifier; all-after stays
    # report-only with the owning /submit.
    record = _publish_record()
    world = _three_layer_world([record])
    world.remote["plan-103"] = R3  # branch + PR + stack all at after
    world.findings = _cancellation_findings()
    result = world.recover()
    (row,) = result.operations
    assert row.kind == "publish" and row.classification == "all_after"
    assert row.action == "reported" and "/submit" in row.detail
    world.assert_nothing_journaled()


def test_sole_publish_all_before_abandon_still_works_under_structural_findings():
    # The abandon arm (confirmation + fresh reclassification + abandoned outcome) is
    # unaffected by the bypass — the publish proof stays the safety gate.
    record = _publish_record()
    world = _three_layer_world([record])  # branch observed at before
    world.findings = _cancellation_findings()
    result = world.recover(abandon=True, approve=lambda preview: True)
    (row,) = result.operations
    assert row.classification == "all_before" and row.action == "abandoned"
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.ABANDONED


def test_sole_publish_mixed_stays_report_only_under_structural_findings():
    record = _publish_record()
    world = _three_layer_world([record])
    world.remote["plan-103"] = "f" * 40  # neither before nor after
    world.findings = _cancellation_findings()
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    world.assert_nothing_journaled()


def test_sole_publish_route_still_sweeps_orphans():
    record = _publish_record()
    world = _three_layer_world([record])
    world.remote["plan-103"] = R3
    world.findings = _cancellation_findings()
    orphan = mint_operation_id()
    world.refs[f"refs/perk/sync/{orphan}/x"] = C2
    result = world.recover()
    assert result.swept_refs == (f"refs/perk/sync/{orphan}/x",)


def test_sole_publish_route_follows_the_active_fold_after_redirect():
    # `recover OLD`: the requested fold walks predecessors only, so a successor-recorded
    # PUBLISH is invisible to it — the bypass must derive from the ACTIVE train's fold (the
    # same snapshot classified below), or the structural gate would dead-end exactly the
    # crash-window findings this route exists to bypass.
    record = _publish_record()
    world = _three_layer_world([record])
    world.persistence.empty_fold_ids.add("7")  # the requested predecessor's fold
    world.remote["plan-103"] = R3
    world.findings = _cancellation_findings()
    result = world.recover(objective_id="7")
    (row,) = result.operations
    assert row.kind == "publish" and row.classification == "all_after"
    assert row.action == "reported"
    assert result.objective_id == OBJECTIVE
    world.assert_nothing_journaled()


def test_sole_non_publish_unresolved_keeps_the_structural_gate():
    # The carve-out is PUBLISH-only: a sole unresolved SYNC under structural findings still
    # refuses (a roll-forward would checkpoint into the wrong plan).
    record = _sync_record()
    world = _three_layer_world([record])
    world.findings = _cancellation_findings()
    with pytest.raises(sync_mod.SyncError) as excinfo:
        world.recover()
    assert excinfo.value.error_type == "claimed_prefix_malformed"
    world.assert_nothing_journaled()


def test_multiple_unresolved_keeps_the_structural_gate_even_with_a_publish():
    # Multi-unresolved states keep today's gates — the route requires a SOLE PUBLISH.
    world = _three_layer_world([_publish_record(), _sync_record()])
    world.findings = _cancellation_findings()
    with pytest.raises(sync_mod.SyncError) as excinfo:
        world.recover()
    assert excinfo.value.error_type == "claimed_prefix_malformed"
    world.assert_nothing_journaled()


# ----------------------------------------------------------------- the publish fresh-train proof


def test_publish_record_disagreeing_with_the_fresh_train_is_mixed():
    # The record's desired PR base no longer matches the fresh topology (the layer's
    # predecessor branch) — record-relative remote facts alone must never conclude it.
    record = _publish_record()
    drifted = PreparedRecord(
        operation_id=record.operation_id,
        operation_kind=record.operation_kind,
        delivery_lineage=record.delivery_lineage,
        objective_id=record.objective_id,
        run_id=record.run_id,
        created=record.created,
        affected_plans=record.affected_plans,
        before=record.before,
        after={**record.after, "pr": {"base": "main", "head_sha": R3}},
    )
    world = _three_layer_world([drifted])
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"
    assert "corroboration against fresh authority failed" in row.detail
    # Acting on it with --abandon is blocked; nothing journaled.
    error = _recover_error(world, abandon=True, approve=lambda preview: True)
    assert error.error_type == "abandon_blocked"
    world.assert_nothing_journaled()


def test_publish_record_for_a_plan_off_the_train_is_mixed():
    record = _publish_record()
    off_train = PreparedRecord(
        operation_id=record.operation_id,
        operation_kind=record.operation_kind,
        delivery_lineage=record.delivery_lineage,
        objective_id=record.objective_id,
        run_id=record.run_id,
        created=record.created,
        affected_plans=("999",),
        before=record.before,
        after=record.after,
    )
    world = _three_layer_world([off_train])
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"
    assert "corroboration against fresh authority failed" in row.detail


@pytest.mark.parametrize("surviving_state", ["OPEN", "CLOSED"])
def test_publish_all_before_with_no_recorded_pr_requires_positive_pr_absence(surviving_state):
    # A first publication captures no pre-operation PR. That is NOT proof of absence: the
    # operation may have created its PR before the branch was reset back — an OPEN PR for
    # the recorded head branch keeps the record mixed (never abandonable).
    record = _publish_record()
    creation = PreparedRecord(
        operation_id=record.operation_id,
        operation_kind=record.operation_kind,
        delivery_lineage=record.delivery_lineage,
        objective_id=record.objective_id,
        run_id=record.run_id,
        created=record.created,
        affected_plans=record.affected_plans,
        before={
            "branch": {"ref": "plan-103", "sha": P3},
            "pr": {"number": None, "base": None, "head_sha": None, "state": None},
            "stack": {"members": None},
        },
        after=record.after,
    )
    world = _three_layer_world([creation])
    world.pr_entries.pop(203)  # the delivery-facts read has nothing recorded to probe
    world.stack_members = None
    if surviving_state == "OPEN":
        world.open_pr_branches["plan-103"] = 203
    else:
        world.pr_entries[203] = ("plan-103", "plan-102", "CLOSED")
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"
    assert "PR effect persists" in row.detail and surviving_state in row.detail
    assert ("pr_for_branch", "plan-103") in world.timeline


def test_publish_all_before_accepts_a_positively_absent_pr():
    record = _publish_record()
    creation = replace(
        record,
        before={
            "branch": {"ref": "plan-103", "sha": P3},
            "pr": {"number": None, "base": None, "head_sha": None, "state": None},
            "stack": {"members": None},
        },
    )
    world = _three_layer_world([creation])
    world.pr_entries.pop(203)
    world.stack_members = None
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_before"
    assert ("pr_for_branch", "plan-103") in world.timeline


# ----------------------------------------------------------------- stale worktree-admin entries


def test_orphan_scan_includes_stale_admin_entries_in_status_and_dry_run():
    stale = mint_operation_id()
    protected = mint_operation_id()
    world = _three_layer_world()
    world.stale_admin_names += [f"sync-{stale}", f"sync-{protected}"]
    world.scan = continuation.ManifestScan(
        manifests=(_protecting_manifest(protected),), unparseable=()
    )
    result = world.recover(dry_run=True)
    assert result.swept_worktrees == (str(WT_ROOT / f"sync-{stale}"),)  # would-be sweep
    assert world.events("worktree_remove") == []  # dry-run: nothing deleted


def test_sweep_prune_collects_stale_admin_entries():
    stale = mint_operation_id()
    world = _three_layer_world()
    world.stale_admin_names.append(f"sync-{stale}")
    result = world.recover()
    assert result.swept_worktrees == (str(WT_ROOT / f"sync-{stale}"),)
    # The stale entry is swept by the ONE prune, never worktree_remove (its dir is gone).
    assert world.events("worktree_remove") == []
    assert world.events("worktree_prune") == [("worktree_prune",)]


def test_sweep_prune_failure_reports_the_stale_admin_entries_unswept():
    stale = mint_operation_id()
    world = _three_layer_world()
    world.stale_admin_names.append(f"sync-{stale}")
    world.prune_boom = git.GitError("prune refused")
    result = world.recover()
    assert result.swept_worktrees == ()
    targets = {failure.target for failure in result.sweep_failures}
    assert targets == {"worktree-prune", str(WT_ROOT / f"sync-{stale}")}


# ----------------------------------------------------------------- the TRANSFER arm (§8.53)


def _transfer_record(*, run_id: str = "01RUNTRANSFER") -> PreparedRecord:
    """A REAL decodable transfer manifest: a pre-publication stacked→incremental conversion
    with an all-fresh successor roadmap (no carried plans — transfer's own suite owns the
    carry matrix)."""
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.TRANSFER,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id=run_id,
        created="2026-01-01T00:00:00Z",
        affected_plans=(),
        before={
            "predecessor_objective_id": OBJECTIVE,
            "base": "main",
            "delivery": "stacked",
            "delivery_lineage": LINEAGE,
            "claimed_prefix": [],
            "carried_unpublished": [],
        },
        after={
            "title": "Successor",
            "prose": "p",
            "base": None,
            "delivery": "incremental",
            "delivery_lineage": None,
            "roadmap_nodes": [
                {
                    "id": "1.1",
                    "slug": None,
                    "description": "fresh work",
                    "status": "pending",
                    "pr": None,
                    "depends_on": None,
                    "adopt_issue": None,
                    "comment": None,
                }
            ],
            "carry_map": {},
        },
    )


def _seed_transfer_world(record: PreparedRecord, *, successor: bool) -> "_World":
    world = _three_layer_world([record])
    world.objectives[OBJECTIVE] = ObjectiveState(
        id=OBJECTIVE,
        url="u/500",
        title="Old",
        header={"delivery": "stacked", "delivery_lineage": LINEAGE},
        nodes=(),
    )
    if successor:
        world.objectives_by_run[record.run_id] = ObjectiveRef(id="600", url="u/600", existed=True)
        world.objectives["600"] = ObjectiveState(
            id="600",
            url="u/600",
            title="Successor",
            header={"supersedes": OBJECTIVE},
            nodes=(
                objective.ObjectiveNode(
                    id="1.1", description="fresh work", status=objective.NodeStatus.PENDING
                ),
            ),
        )
    return world


def test_transfer_all_after_rolls_forward_to_completion():
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=True)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_after" and row.action == "rolled_forward"
    assert "successor 600" in row.detail
    # The convergent re-create ran with the deferred close, then finalize + completion.
    (call,) = world.supersede_calls
    assert call["close_predecessor"] is False and call["run_id"] == record.run_id
    assert world.finalized == [(OBJECTIVE, "600")]
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert outcome.observed == {"successor_objective_id": "600", "run_id": record.run_id}
    assert result.objective_url == "u/500"


def test_transfer_routed_before_the_not_stacked_and_structural_gates():
    # (a) a finalized-but-uncompleted stacked→incremental predecessor has NO train at all —
    # the old flow's not_stacked rejection must never fire for a sole unresolved TRANSFER.
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=True)
    world.no_train = True
    result = world.recover()
    (row,) = result.operations
    assert row.action == "rolled_forward"
    # (b) a mid-transfer predecessor shows intentional structural blockers (wrong_owner) —
    # the structural gate must not refuse the arm either.
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=True)
    world.findings = (
        TrainFinding(
            kind=FindingKind.BLOCKER,
            code="wrong_owner",
            message="plan #102 records objective 600, expected 500",
            plan_id="102",
        ),
    )
    result = world.recover()
    (row,) = result.operations
    assert row.action == "rolled_forward"


def test_transfer_all_before_reported_with_the_abandon_hint():
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=False)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_before" and row.action == "reported"
    assert "no successor exists" in row.detail
    assert "--abandon" in row.detail and "re-save the replan" in row.detail
    world.assert_nothing_journaled()
    assert world.persistence.outcomes == []


def test_transfer_all_before_abandons_with_proof_confirmed():
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=False)
    previews: list[recover.AbandonPreview] = []
    result = world.recover(abandon=True, approve=lambda p: previews.append(p) or True)
    (row,) = result.operations
    assert row.action == "abandoned"
    (preview,) = previews
    assert preview.operation_id == record.operation_id and preview.kind == "transfer"
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.ABANDONED
    assert outcome.observed == {
        "proof": "successor_absent",
        "run_id": record.run_id,
        "predecessor_objective_id": OBJECTIVE,
    }
    assert world.supersede_calls == []  # abandon never creates


def test_transfer_abandon_reclassifies_after_confirmation():
    # The successor appears during the confirmation pause: the stale all-before refuses.
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=False)

    def approve(preview: recover.AbandonPreview) -> bool:
        world.objectives_by_run[record.run_id] = ObjectiveRef(id="600", url="u/600", existed=True)
        world.objectives["600"] = ObjectiveState(
            id="600",
            url="u/600",
            title="Successor",
            header={"supersedes": OBJECTIVE},
            nodes=(),
        )
        return True

    error = _recover_error(world, abandon=True, approve=approve)
    assert error.error_type == "abandon_blocked"
    assert "while the confirmation was pending" in str(error)
    assert world.persistence.outcomes == []


def test_transfer_abandon_blocked_on_all_after():
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=True)
    error = _recover_error(world, abandon=True, approve=lambda p: True)
    assert error.error_type == "abandon_blocked"
    assert "all_after" in str(error)
    assert world.persistence.outcomes == []


def test_transfer_corrupt_manifest_is_a_report_only_row():
    record = _foreign_record(OperationKind.TRANSFER)
    world = _three_layer_world([record])
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    assert "undecodable" in row.detail
    world.assert_nothing_journaled()
    assert world.persistence.outcomes == []
    error = _recover_error(world, abandon=True, approve=lambda p: True)
    assert error.error_type == "abandon_blocked"


def test_transfer_corroboration_mismatch_is_mixed():
    # A foreign objective found by the run id must never be adopted as the successor.
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=True)
    world.objectives["600"] = ObjectiveState(
        id="600", url="u/600", title="Foreign", header={"supersedes": "999"}, nodes=()
    )
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    assert "corroboration against fresh authority failed" in row.detail
    assert world.supersede_calls == []


def test_transfer_dry_run_reports_the_would_be_roll_forward():
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=True)
    result = world.recover(dry_run=True)
    assert result.dry_run is True
    (row,) = result.operations
    assert row.classification == "all_after" and row.action == "reported"
    assert "a real recover would roll this forward automatically" in row.detail
    assert world.supersede_calls == [] and world.finalized == []
    world.assert_nothing_journaled()


def test_transfer_operation_flag_must_name_the_sole_unresolved():
    record = _transfer_record()
    world = _seed_transfer_world(record, successor=True)
    error = _recover_error(world, operation="01SOMEOTHEROP")
    assert error.error_type == "operation_not_found"
    assert record.operation_id in str(error)


# ----------------------------------------------------------------- the LAND arm (§8.51)

M1 = "d" * 40  # layer-1 merge commit
M2 = "e" * 40  # layer-2 merge commit
M3 = "f" * 40  # layer-3 merge commit
AGED = "2026-01-01T00:00:00Z"  # ≥24h before the injected now (2026-02-02)
YOUNG = "2026-02-01T12:00:00Z"  # 12h before the injected now


def _land_record(
    *,
    mode: str = "stack_merge_async",
    created: str = AGED,
    layers: list[tuple[str, str, int, str, str]] | None = None,
) -> PreparedRecord:
    rows = layers or [
        ("1.1", "101", 201, MAIN, P1),
        ("1.2", "102", 202, P1, P2),
        ("1.3", "103", 203, P2, P3),
    ]
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.LAND,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created=created,
        affected_plans=tuple(row[1] for row in rows),
        before={
            "mode": mode,
            "merge_method": "squash",
            "base": "main",
            "top_pr_number": rows[-1][2],
            "top_head_sha": rows[-1][4],
            "layers": [
                {
                    "node_id": node_id,
                    "plan_id": plan_id,
                    "pr_number": pr,
                    "base_sha": base,
                    "head_sha": head,
                }
                for node_id, plan_id, pr, base, head in rows
            ],
        },
        after={"merged_pr_numbers": [row[2] for row in rows], "base": "main"},
    )


def _merged_ev(number: int, *, head: str, merge: str, base: str, branch: str) -> PrMergedEvidence:
    return PrMergedEvidence(
        number=number,
        state="MERGED",
        base_ref=base,
        head_ref=branch,
        head_sha=head,
        merge_commit_sha=merge,
    )


def _open_ev(number: int, *, head: str, base: str, branch: str) -> PrMergedEvidence:
    return PrMergedEvidence(
        number=number,
        state="OPEN",
        base_ref=base,
        head_ref=branch,
        head_sha=head,
        merge_commit_sha=None,
    )


def _land_world(record: PreparedRecord | None = None) -> _World:
    """The three-layer LAND world: expected bases on the layers, per-PR merged-evidence
    scripts, and a terminal-node objective (the state-aware close's authority)."""
    unresolved = [record] if record is not None else []
    world = _World(
        [
            _layer(
                "1.1",
                "101",
                pr_number=201,
                parent_checkpoint_sha=MAIN,
                published_head_sha=P1,
                expected_pr_base="main",
            ),
            _layer(
                "1.2",
                "102",
                pr_number=202,
                parent_checkpoint_sha=P1,
                published_head_sha=P2,
                expected_pr_base="plan-101",
            ),
            _layer(
                "1.3",
                "103",
                pr_number=203,
                parent_checkpoint_sha=P2,
                published_head_sha=P3,
                expected_pr_base="plan-102",
            ),
        ],
        unresolved=unresolved,
    )
    world.remote.update({"plan-101": P1, "plan-102": P2, "plan-103": P3})
    world.pr_entries = {
        201: ("plan-101", "main", "OPEN"),
        202: ("plan-102", "plan-101", "OPEN"),
        203: ("plan-103", "plan-102", "OPEN"),
    }
    done = objective.NodeStatus.DONE
    world.objectives[OBJECTIVE] = ObjectiveState(
        id=OBJECTIVE,
        url="u",
        title="t",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="a", status=done, pr="#101"),
            objective.ObjectiveNode(id="1.2", description="b", status=done, pr="#102"),
            objective.ObjectiveNode(id="1.3", description="c", status=done, pr="#103"),
        ),
    )
    return world


def _all_merged(world: _World) -> None:
    world.pr_merged = {
        201: _merged_ev(201, head=P1, merge=M1, base="main", branch="plan-101"),
        202: _merged_ev(202, head=P2, merge=M2, base="plan-101", branch="plan-102"),
        203: _merged_ev(203, head=P3, merge=M3, base="main", branch="plan-103"),  # retargeted
    }


def _all_before(world: _World) -> None:
    world.pr_merged = {
        201: _open_ev(201, head=P1, base="main", branch="plan-101"),
        202: _open_ev(202, head=P2, base="plan-101", branch="plan-102"),
        203: _open_ev(203, head=P3, base="plan-102", branch="plan-103"),
    }


def _prefix_one(world: _World) -> None:
    """PR 201 externally merged (branch deleted → 202 retargeted is NOT required); the
    remainder OPEN at its recorded heads."""
    world.pr_merged = {
        201: _merged_ev(201, head=P1, merge=M1, base="main", branch="plan-101"),
        202: _open_ev(202, head=P2, base="plan-101", branch="plan-102"),
        203: _open_ev(203, head=P3, base="plan-102", branch="plan-103"),
    }


def _probe(state: MergeAsyncProbeState, *, sha: str | None = None) -> MergeAsyncProbe:
    return MergeAsyncProbe(state=state, sha=sha, message="")


def _accepted(world: _World, record: PreparedRecord, uuid: str = "u-1") -> None:
    world.persistence.accepted_records[record.operation_id] = OutcomeRecord(
        operation_id=record.operation_id,
        role=EventRole.ACCEPTED,
        created=record.created,
        observed={
            "uuid": uuid,
            "merge_method": "squash",
            "merge_action": "direct_merge",
            "expected_head_sha": P3,
            "http_status": 202,
        },
    )


# --- record corroboration (fail closed) --------------------------------------------------


def test_land_record_with_extra_current_layer_is_mixed():
    # The record names layers 1-2 but the train carries three non-landed layers: a stale
    # record (node-add while unresolved) never concludes.
    record = _land_record(layers=[("1.1", "101", 201, MAIN, P1), ("1.2", "102", 202, P1, P2)])
    world = _land_world(record)
    _all_merged(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    assert "stale record" in row.detail
    world.assert_nothing_journaled()


def test_land_record_with_identity_mismatch_is_mixed():
    record = _land_record(
        layers=[
            ("1.1", "101", 201, MAIN, P1),
            ("1.2", "999", 202, P1, P2),  # foreign plan id
            ("1.3", "103", 203, P2, P3),
        ]
    )
    world = _land_world(record)
    _all_merged(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"
    world.assert_nothing_journaled()


# --- the handle-evidence x observation-shape table ---------------------------------------


@pytest.mark.parametrize("live_state", ["pending", "enqueued"])
def test_live_probe_is_in_flight_for_every_shape(live_state):
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    world.probe_results = [_probe(live_state)]
    _all_merged(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "in_flight" and row.action == "reported"
    assert world.probe_calls == [(203, "u-1")]  # ONE probe per classification pass
    world.assert_nothing_journaled()


def test_probe_merged_with_uncorroborated_observation_is_in_flight_never_mixed():
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    world.probe_results = [_probe("merged", sha=M3)]
    _all_before(world)  # propagation lag / contradiction
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "in_flight"
    assert "corroborated" in row.detail
    world.assert_nothing_journaled()


@pytest.mark.parametrize("terminal", ["failed", "expired"])
def test_terminal_probe_all_before_classifies_all_before(terminal):
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    world.probe_results = [_probe(terminal)]
    _all_before(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_before" and row.action == "reported"
    assert "--abandon" in row.detail
    world.assert_nothing_journaled()


@pytest.mark.parametrize("terminal", ["failed", "expired"])
def test_terminal_probe_prefix_classifies_external_prefix(terminal):
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    world.probe_results = [_probe(terminal)]
    _prefix_one(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "external_prefix" and row.action == "reported"
    assert "--accept-prefix" in row.detail
    # The structured preview rides the reported row (dry-run included — r22).
    assert row.merged_layers == (
        recover.MergedPrefixRow(node_id="1.1", pr_number=201, merge_commit_sha=M1),
    )
    assert row.remainder == (
        recover.RemainderPrRow(pr_number=202, state="OPEN", head_sha=P2),
        recover.RemainderPrRow(pr_number=203, state="OPEN", head_sha=P3),
    )
    world.assert_nothing_journaled()


def test_unreadable_probe_is_monotonic_only():
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    # all-merged concludes (monotonic-safe) …
    world.probe_results = [_probe("unreadable")]
    _all_merged(world)
    result = world.recover(dry_run=True)
    (row,) = result.operations
    assert row.classification == "all_after"
    # … but all-before / prefix stay in_flight (a live job may exist).
    for shape in (_all_before, _prefix_one):
        world = _land_world(_land_record())
        _accepted(
            world,
            world.persistence.unresolved_records[next(iter(world.persistence.unresolved_records))],
        )
        world.probe_results = [_probe("unreadable")]
        shape(world)
        result = world.recover()
        (row,) = result.operations
        assert row.classification == "in_flight"
        world.assert_nothing_journaled()


def test_no_handle_async_young_is_monotonic_only_with_the_remaining_wait():
    record = _land_record(created=YOUNG)
    world = _land_world(record)
    _prefix_one(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "in_flight"
    assert "remaining wait" in row.detail
    world.assert_nothing_journaled()

    # all-merged still concludes under the young no-handle window (monotonic-safe).
    world = _land_world(_land_record(created=YOUNG))
    _all_merged(world)
    result = world.recover(dry_run=True)
    (row,) = result.operations
    assert row.classification == "all_after"


@pytest.mark.parametrize("created", ["2026-01-01T00:00:00", "not-a-timestamp", ""])
def test_no_handle_unknown_age_is_monotonic_only_never_a_crash(created):
    # A naive ISO `created` (aware-vs-naive subtraction raises TypeError) or outright junk
    # means the record's age is UNKNOWN — fail closed onto the young monotonic-only
    # posture (`in_flight` report), never a recovery crash.
    record = _land_record(created=created)
    world = _land_world(record)
    _prefix_one(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "in_flight"
    world.assert_nothing_journaled()

    # all-merged still concludes under unknown age (monotonic-safe).
    world = _land_world(_land_record(created=created))
    _all_merged(world)
    result = world.recover(dry_run=True)
    (row,) = result.operations
    assert row.classification == "all_after"


def test_no_handle_async_aged_is_observation_authoritative():
    record = _land_record(created=AGED)
    world = _land_world(record)
    _prefix_one(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "external_prefix"
    assert world.probe_calls == []  # no handle — nothing to probe


def test_singleton_record_is_observation_authoritative_and_never_prefix():
    # A one-layer record cannot have a k < n prefix; observation decides directly.
    record = _land_record(mode="singleton_squash", layers=[("1.1", "101", 201, MAIN, P1)])
    world = _World(
        [
            _layer(
                "1.1",
                "101",
                pr_number=201,
                parent_checkpoint_sha=MAIN,
                published_head_sha=P1,
                expected_pr_base="main",
            )
        ],
        unresolved=[record],
    )
    world.pr_merged = {201: _open_ev(201, head=P1, base="main", branch="plan-101")}
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_before"
    assert world.probe_calls == []


def test_non_prefix_drift_arms_are_mixed_and_journal_nothing():
    # Merged-above-unmerged (not bottom-contiguous) → other → mixed.
    record = _land_record()
    world = _land_world(record)
    world.pr_merged = {
        201: _open_ev(201, head=P1, base="main", branch="plan-101"),
        202: _merged_ev(202, head=P2, merge=M2, base="plan-101", branch="plan-102"),
        203: _open_ev(203, head=P3, base="plan-102", branch="plan-103"),
    }
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and row.action == "reported"
    world.assert_nothing_journaled()

    # A CLOSED PR anywhere poisons the prefix shape → mixed.
    world = _land_world(_land_record())
    world.pr_merged = {
        201: _merged_ev(201, head=P1, merge=M1, base="main", branch="plan-101"),
        202: PrMergedEvidence(
            number=202,
            state="CLOSED",
            base_ref="plan-101",
            head_ref="plan-102",
            head_sha=P2,
            merge_commit_sha=None,
        ),
        203: _open_ev(203, head=P3, base="plan-102", branch="plan-103"),
    }
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"
    world.assert_nothing_journaled()


def test_drifted_remainder_head_is_mixed_not_external_prefix():
    # r2: external_prefix requires every remaining layer OPEN at its RECORDED head.
    record = _land_record()
    world = _land_world(record)
    _prefix_one(world)
    world.pr_merged[202] = _open_ev(202, head=C2, base="plan-101", branch="plan-102")  # drifted
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed"
    world.assert_nothing_journaled()


def test_evidence_read_failure_is_mixed():
    record = _land_record()
    world = _land_world(record)
    _all_merged(world)
    world.pr_merged[202] = GitHubError("api down")
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "mixed" and "fail closed" in row.detail
    world.assert_nothing_journaled()


# --- the all_after roll-forward -----------------------------------------------------------


def test_land_all_after_rolls_forward_automatically():
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    world.probe_results = [_probe("expired")]
    _all_merged(world)
    result = world.recover()
    (row,) = result.operations
    assert row.classification == "all_after" and row.action == "rolled_forward"
    # The §8.56 completed shape: layers bottom→top, reported_sha null (the probe did not
    # say merged), final_base_sha = the TOP layer's merge commit.
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED and outcome.operation_id == record.operation_id
    assert outcome.observed == {
        "layers": [
            {"pr_number": 201, "merge_commit_sha": M1},
            {"pr_number": 202, "merge_commit_sha": M2},
            {"pr_number": 203, "merge_commit_sha": M3},
        ],
        "reported_sha": None,
        "final_base_sha": M3,
    }
    # Finalized bottom→top with the layer's expected base ref as pr_base.
    assert world.finalize_calls == [("101", "main"), ("102", "plan-101"), ("103", "plan-102")]
    # The state-aware close fired (open objective, every node terminal) + fresh evidence.
    assert result.objective_closed is True
    assert world.closed_objectives == [OBJECTIVE]
    assert result.reconcile_evidence is not None
    assert [(r.pr_number, r.merge_commit_sha) for r in result.reconcile_evidence.layers] == [
        (201, M1),
        (202, M2),
        (203, M3),
    ]
    assert result.reconcile_evidence.final_base_sha == M3
    assert [(r.plan_id, r.finalized) for r in result.landed_layers] == [
        ("101", True),
        ("102", True),
        ("103", True),
    ]


def test_land_all_after_with_probe_merged_records_the_reported_sha():
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    world.probe_results = [_probe("merged", sha=M3)]
    _all_merged(world)
    result = world.recover()
    (row,) = result.operations
    assert row.action == "rolled_forward"
    (outcome,) = world.persistence.outcomes
    assert outcome.observed["reported_sha"] == M3
    assert result.objective_closed is True


def test_roll_forward_finalize_failure_is_isolated_and_loud():
    record = _land_record()
    world = _land_world(record)
    world.probe_results = []
    _all_merged(world)
    world.finalize_boom["102"] = RuntimeError("bookkeeping down")
    result = world.recover()
    (row,) = result.operations
    assert row.action == "rolled_forward"
    assert [(r.plan_id, r.finalized) for r in result.landed_layers] == [
        ("101", True),
        ("102", False),  # attempted-and-failed — distinguishable from a dry-run null
        ("103", True),
    ]
    assert any("finalize failed for plan #102" in note for note in result.notes)
    assert result.objective_closed is True  # the close still ran


def test_roll_forward_completed_append_failure_degrades_and_the_rerun_converges():
    # Invariant-20 analog: the failed append is a loud note; finalization still runs; the
    # CLOSE is deferred (closing before the completion is durable would assemble EMPTY
    # evidence and permanently suppress the reconcile drive); the op stays unresolved and
    # the NEXT run converges the journal, then closes WITH evidence — no duplicate finalize
    # effects beyond idempotent re-runs (the stateful-fake shape).
    record = _land_record()
    world = _land_world(record)
    _all_merged(world)
    world.persistence.outcome_boom_once = UnresolvedOperationError("carrier hiccup")
    result = world.recover()
    (row,) = result.operations
    assert row.action == "rolled_forward"
    assert any("could not be journaled" in note for note in result.notes)
    assert any("close deferred" in note for note in result.notes)
    assert world.persistence.outcomes == []  # nothing landed in the journal
    assert record.operation_id in world.persistence.unresolved_records  # still unresolved
    assert [(r.plan_id, r.finalized) for r in result.landed_layers] == [
        ("101", True),
        ("102", True),
        ("103", True),
    ]  # finalization still ran
    assert result.objective_closed is False  # the close is DEFERRED, never evidence-less
    assert world.closed_objectives == []
    assert result.reconcile_evidence is None

    # The rerun re-classifies all_after, appends the completed outcome exactly once, and
    # closes WITH the full evidence — the reconcile-drive path is preserved.
    result2 = world.recover()
    (row2,) = result2.operations
    assert row2.action == "rolled_forward"
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert result2.objective_closed is True
    assert world.closed_objectives == [OBJECTIVE]
    assert result2.reconcile_evidence is not None
    assert [r.pr_number for r in result2.reconcile_evidence.layers] == [201, 202, 203]


def test_land_all_after_dry_run_reports_without_acting():
    record = _land_record()
    world = _land_world(record)
    _all_merged(world)
    result = world.recover(dry_run=True)
    (row,) = result.operations
    assert row.classification == "all_after" and row.action == "reported"
    assert "a real recover would roll this forward automatically" in row.detail
    world.assert_nothing_journaled()
    assert world.finalize_calls == [] and world.closed_objectives == []


# --- the abandon arm (all_before) ---------------------------------------------------------


def test_land_abandon_journals_recovered_before_state_with_proof():
    record = _land_record()
    world = _land_world(record)
    _accepted(world, record)
    world.probe_results = [_probe("expired"), _probe("expired")]  # classify + re-classify
    _all_before(world)
    previews: list[recover.AbandonPreview] = []
    result = world.recover(abandon=True, approve=lambda p: previews.append(p) or True)
    (row,) = result.operations
    assert row.action == "abandoned"
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.ABANDONED
    assert outcome.observed["reason"] == "recovered_before_state"
    assert outcome.observed["reobserved"] == [
        {"pr_number": 201, "state": "OPEN", "head_sha": P1},
        {"pr_number": 202, "state": "OPEN", "head_sha": P2},
        {"pr_number": 203, "state": "OPEN", "head_sha": P3},
    ]
    # The consent race re-probes: two strict handle reads across the two passes.
    assert world.probe_calls == [(203, "u-1"), (203, "u-1")]


def test_land_abandon_reclassifies_after_confirmation():
    record = _land_record()
    world = _land_world(record)
    _all_before(world)

    def approve(preview: recover.AbandonPreview) -> bool:
        _prefix_one(world)  # the world moves during the pause
        return True

    error = _recover_error(world, abandon=True, approve=approve)
    assert error.error_type == "abandon_blocked"
    assert world.persistence.outcomes == []


# --- the accept-prefix arm (external_prefix) ----------------------------------------------


def test_accept_prefix_journals_the_breach_and_finalizes_the_prefix_only():
    record = _land_record()
    world = _land_world(record)
    _prefix_one(world)
    # The remainder's nodes are still open — the state-aware close must not fire.
    done, in_progress = objective.NodeStatus.DONE, objective.NodeStatus.IN_PROGRESS
    world.objectives[OBJECTIVE] = ObjectiveState(
        id=OBJECTIVE,
        url="u",
        title="t",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="a", status=done, pr="#101"),
            objective.ObjectiveNode(id="1.2", description="b", status=in_progress, pr="#102"),
            objective.ObjectiveNode(id="1.3", description="c", status=in_progress, pr="#103"),
        ),
    )
    previews: list[recover.AcceptPrefixPreview] = []
    result = world.recover(accept_prefix=True, accept_approve=lambda p: previews.append(p) or True)
    (row,) = result.operations
    assert row.classification == "external_prefix" and row.action == "accepted_prefix"
    (preview,) = previews
    assert preview.merged_layers == (
        recover.MergedPrefixRow(node_id="1.1", pr_number=201, merge_commit_sha=M1),
    )
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert outcome.observed == {
        "layers": [{"pr_number": 201, "merge_commit_sha": M1}],  # the merged prefix ONLY
        "reported_sha": None,
        "final_base_sha": M1,  # the top MERGED layer's merge commit
        "external_prefix": True,
        "remainder": [
            {"pr_number": 202, "state": "OPEN", "head_sha": P2},
            {"pr_number": 203, "state": "OPEN", "head_sha": P3},
        ],
    }
    # The prefix finalizes; the remainder is untouched (the negative assertion).
    assert world.finalize_calls == [("101", "main")]
    assert result.objective_closed is False  # open nodes — the close cannot fire
    assert "sync --base" in row.detail


def test_accept_prefix_membership_change_after_confirmation_is_accept_blocked():
    record = _land_record()
    world = _land_world(record)
    _prefix_one(world)

    def approve(preview: recover.AcceptPrefixPreview) -> bool:
        # PR 202 merges externally during the pause: the prefix membership changes.
        world.pr_merged[202] = _merged_ev(
            202, head=P2, merge=M2, base="plan-101", branch="plan-102"
        )
        return True

    error = _recover_error(world, accept_prefix=True, accept_approve=approve)
    assert error.error_type == "accept_blocked"
    assert "membership changed" in str(error)
    world.assert_nothing_journaled()
    assert world.finalize_calls == []


def test_accept_prefix_on_a_non_external_target_is_accept_blocked():
    record = _land_record()
    world = _land_world(record)
    _all_before(world)
    error = _recover_error(world, accept_prefix=True, accept_approve=lambda p: True)
    assert error.error_type == "accept_blocked"
    world.assert_nothing_journaled()


def test_accept_prefix_declined_journals_nothing():
    record = _land_record()
    world = _land_world(record)
    _prefix_one(world)
    result = world.recover(accept_prefix=True, accept_approve=lambda p: False)
    (row,) = result.operations
    assert row.action == "declined"
    world.assert_nothing_journaled()


def test_accept_prefix_flag_matrix_is_invalid_input():
    world = _land_world(_land_record())
    error = _recover_error(world, accept_prefix=True, abandon=True)
    assert error.error_type == "invalid_input"
    error = _recover_error(world, accept_prefix=True, dry_run=True)
    assert error.error_type == "invalid_input"


# --- the finalization-convergence pass (§8.51) --------------------------------------------


def _seed_completed_land(
    world: _World,
    *,
    layers: list[tuple[str, str, int, str, str]],
    merges: dict[int, str],
    external_prefix: bool = False,
) -> PreparedRecord:
    record = _land_record(layers=layers)
    observed: dict[str, object] = {
        "layers": [{"pr_number": pr, "merge_commit_sha": sha} for pr, sha in merges.items()],
        "reported_sha": None,
        "final_base_sha": list(merges.values())[-1],
    }
    if external_prefix:
        observed["external_prefix"] = True
        observed["remainder"] = []
    world.persistence.completed.append(
        (
            record,
            OutcomeRecord(
                operation_id=record.operation_id,
                role=EventRole.COMPLETED,
                created="2026-01-02T00:00:00Z",
                observed=observed,
            ),
        )
    )
    return record


def test_convergence_refinalizes_every_covered_corroborated_layer():
    # Zero unresolved operations — the pass still runs (r3: no completeness proxy).
    world = _land_world()
    _seed_completed_land(
        world,
        layers=[("1.1", "101", 201, MAIN, P1), ("1.2", "102", 202, P1, P2)],
        merges={201: M1, 202: M2},
    )
    _all_merged(world)
    result = world.recover()
    assert result.operations == ()
    assert world.finalize_calls == [("101", "main"), ("102", "plan-101")]
    assert [(r.plan_id, r.finalized) for r in result.landed_layers] == [
        ("101", True),
        ("102", True),
    ]
    # Layer 1.3 has no journal coverage — never touched (the scope-guard negative).
    assert all(r.plan_id != "103" for r in result.landed_layers)
    assert result.objective_closed is True
    assert result.reconcile_evidence is not None
    assert [r.pr_number for r in result.reconcile_evidence.layers] == [201, 202]


def test_convergence_corroboration_failure_skips_loudly():
    world = _land_world()
    _seed_completed_land(world, layers=[("1.1", "101", 201, MAIN, P1)], merges={201: M1})
    world.pr_merged = {201: _open_ev(201, head=P1, base="main", branch="plan-101")}
    result = world.recover()
    assert world.finalize_calls == []
    assert any("did not corroborate" in note for note in result.notes)
    assert result.landed_layers == ()


def test_convergence_no_coverage_is_never_touched():
    # A merged PR with NO land-journal coverage is never adopted (the scope guard).
    world = _land_world()
    _all_merged(world)
    result = world.recover()
    assert world.finalize_calls == [] and result.landed_layers == ()
    # No coverage also means no evidence-bearing close on an open-noded objective.


def test_convergence_dry_run_rows_carry_finalized_null():
    world = _land_world()
    _seed_completed_land(world, layers=[("1.1", "101", 201, MAIN, P1)], merges={201: M1})
    _all_merged(world)
    result = world.recover(dry_run=True)
    assert world.finalize_calls == [] and world.closed_objectives == []
    (row,) = result.landed_layers
    assert row.plan_id == "101" and row.finalized is None
    assert result.objective_closed is False


def test_convergence_excludes_layers_concluded_this_invocation():
    # The accept-prefix conclusion finalizes layer 101; the convergence pass sees the fresh
    # fold (the breach record it just appended) but must NOT duplicate the row.
    record = _land_record()
    world = _land_world(record)
    _prefix_one(world)
    result = world.recover(accept_prefix=True, accept_approve=lambda p: True)
    assert world.finalize_calls == [("101", "main")]  # exactly once
    assert [r.plan_id for r in result.landed_layers] == ["101"]


def test_convergence_close_on_a_closed_objective_reports_false():
    world = _land_world()
    _seed_completed_land(world, layers=[("1.1", "101", 201, MAIN, P1)], merges={201: M1})
    _all_merged(world)
    state = world.objectives[OBJECTIVE]
    world.objectives[OBJECTIVE] = ObjectiveState(
        id=state.id,
        url=state.url,
        title=state.title,
        header=state.header,
        nodes=state.nodes,
        state="closed",
    )
    result = world.recover()
    assert world.finalize_calls == [("101", "main")]  # finalization still converges
    assert result.objective_closed is False
    assert world.closed_objectives == []
    assert any("already closed" in note for note in result.notes)
