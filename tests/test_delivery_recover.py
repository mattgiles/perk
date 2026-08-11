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

from perk.delivery import continuation, oplock, recover
from perk.delivery import sync as sync_mod
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
from perk.github.stacks import PrDeliveryFacts, StackRestEntry, StackRestFacts
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
) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=f"plan-{plan_id}",
        pr_number=pr_number,
        intent=LayerIntent.PLANNED,
        publication=LayerPublication.UNPUBLISHED,
        git=LayerGit.UNKNOWN,
        pr=LayerPr.ABSENT,
        membership=LayerMembership.NOT_APPLICABLE,
        writer=LayerWriter.FREE,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=parent_checkpoint_sha,
        published_head_sha=published_head_sha,
        observed_remote_head_sha=None,
        observed_pr_base=None,
        expected_pr_base=None,
    )


class _FakePersistence:
    def __init__(self, world: "_World", unresolved: list[PreparedRecord]) -> None:
        self._world = world
        self.unresolved_records: dict[str, PreparedRecord] = {r.operation_id: r for r in unresolved}
        self.prepared: list[PreparedRecord] = []
        self.outcomes: list[OutcomeRecord] = []
        self.checkpoints: list[tuple[str, str, str]] = []

    def read_journal(self, objective_id: str) -> JournalFold:
        ops = {}
        for op_id, record in self.unresolved_records.items():
            event = JournalEvent(
                record=record,
                role=EventRole.PREPARED,
                operation_id=op_id,
                canonical_payload=canonical_payload(record),
                comment_id="c1",
                created_at=record.created,
            )
            ops[op_id] = OperationState(
                operation_id=op_id,
                kind=record.operation_kind,
                prepared=event,
                accepted=None,
                outcome=None,
            )
        return JournalFold(
            events=(),
            operations=ops,
            unresolved=tuple(ops.values()),
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
        self.outcomes.append(record)
        self.unresolved_records.pop(record.operation_id, None)
        return AppendResult(record.operation_id, record.role, existed=False)

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None:
        self._world.timeline.append(("checkpoints", plan_id))
        self.checkpoints.append((plan_id, parent_checkpoint_sha, published_head_sha))


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

    # ------------------------------------------------------------- driving

    def recover(
        self,
        *,
        dry_run: bool = False,
        abandon: bool = False,
        operation: str | None = None,
        approve: Callable[[recover.AbandonPreview], bool] | None = None,
    ) -> recover.RecoverResult:
        return recover.recover_operations(
            ROOT,
            objective_id=OBJECTIVE,
            worktree_root=WT_ROOT,
            dry_run=dry_run,
            abandon=abandon,
            operation_id=operation,
            approve=approve,
            reconstruct=self._reconstruct,
            persistence_factory=lambda root: self.persistence,
            pr_facts=self._pr_facts,
            stack_read=self._stack_read,
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


def test_transfer_and_land_are_unsupported_and_never_observed():
    for kind in (OperationKind.TRANSFER, OperationKind.LAND):
        record = _foreign_record(kind)
        world = _three_layer_world([record])
        result = world.recover()
        (row,) = result.operations
        assert row.classification == "unsupported" and row.action == "reported"
        assert "report-only" in row.detail
        assert world.events("remote_head") == []  # never decoded, never observed
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


def test_abandon_on_transfer_is_unsupported_operation_kind():
    record = _foreign_record(OperationKind.TRANSFER)
    world = _three_layer_world([record])
    error = _recover_error(world, abandon=True, approve=lambda p: True)
    assert error.error_type == "unsupported_operation_kind"
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
