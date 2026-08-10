"""Hermetic fake-driven tests for the delivery sync operation (contracts.md §8.49).

Every effectful seam of ``synchronize_train`` is injected with an in-memory world: a
scriptable mini remote (branch heads, PR facts, one native stack), a recording persistence
fake, in-memory temp refs / worktrees / continuation manifests, and a timeline that pins the
load-bearing ordering (candidates → approval → re-observation → prepared → one atomic push →
verify → checkpoints bottom→top → completed). OFFLINE — no git / gh / network.
"""

import contextlib
from collections.abc import Callable
from pathlib import Path

import pytest

from perk.delivery import continuation, sync
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
from perk.github.stacks import PrDeliveryFacts, StackRestEntry, StackRestFacts
from perk.substrate import git

ROOT = Path("/repo")
WT_ROOT = Path("/wt")
OBJECTIVE = "500"
LINEAGE = "01LINEAGE"
MAIN = "m" * 40  # the anchored objective base
NEWBASE = "n" * 40  # an advanced objective base head
P1 = "1" * 40  # layer-1 published head
P2 = "2" * 40  # layer-2 published head
P3 = "3" * 40  # layer-3 published head
C2 = "b" * 40  # layer-2 amended local head


def _reb(source: str, onto: str) -> str:
    """The fake rebase's deterministic transplant SHA."""
    return f"reb:{source[:4]}:onto:{onto[:4]}"


def _layer(
    node_id: str,
    plan_id: str | None,
    *,
    pr_number: int | None = None,
    parent_checkpoint_sha: str | None = None,
    published_head_sha: str | None = None,
    branch: str | None = "default",
    writer: LayerWriter = LayerWriter.FREE,
) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=(f"plan-{plan_id}" if branch == "default" else branch),
        pr_number=pr_number,
        intent=LayerIntent.PLANNED,
        publication=LayerPublication.UNPUBLISHED,  # deliberately untrusted by sync
        git=LayerGit.UNKNOWN,
        pr=LayerPr.ABSENT,
        membership=LayerMembership.NOT_APPLICABLE,
        writer=writer,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=parent_checkpoint_sha,
        published_head_sha=published_head_sha,
        observed_remote_head_sha=None,
        observed_pr_base=None,
        expected_pr_base=None,
    )


class _WriterProbe:
    def __init__(self) -> None:
        self.active: frozenset[str] = frozenset()
        self.boom: Exception | None = None
        self.calls: list[tuple[str, ...]] = []

    def active_plan_ids(self, plan_ids) -> frozenset[str]:
        self.calls.append(tuple(plan_ids))
        if self.boom is not None:
            raise self.boom
        return self.active & frozenset(plan_ids)


class _FakePersistence:
    """In-memory journal: seeded unresolved records, recorded appends, and a live fold."""

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
    """The injectable mini remote + recorders for one ``synchronize_train`` invocation."""

    def __init__(
        self,
        layers: list[TrainLayer],
        *,
        unresolved: list[PreparedRecord] | None = None,
    ) -> None:
        self.layers = layers
        self.lineage: str | None = LINEAGE
        self.base_head: str | None = MAIN
        self.findings: tuple[TrainFinding, ...] = ()
        self.no_train = False
        self.timeline: list[tuple] = []
        self.persistence = _FakePersistence(self, unresolved or [])
        self.writer_probe = _WriterProbe()
        # Git state.
        self.remote: dict[str, str | None] = {"main": MAIN}
        self.local: dict[str, str | None] = {}
        self.ancestry: set[tuple[str, str]] = set()
        self.urls = ["https://gh/octo/repo.git"]
        self.atomic_probe_boom: Exception | None = None
        self.push_reject = False
        self.push_reject_leaves: dict[str, str] = {}
        self.on_push: Callable[[], None] | None = None
        self.fetch_boom: Exception | None = None
        self.remote_head_boom: Exception | None = None
        # GitHub state: PR number → (branch, base, state); head_sha reads live remote.
        self.pr_entries: dict[int, tuple[str, str, str]] = {}
        self.pr_facts_script: list[PrDeliveryFacts | None | Exception] = []
        self.stack_members: list[int] | None = None
        # Residue state.
        self.refs: dict[str, str] = {}
        self.worktrees_added: list[tuple[Path, str]] = []
        self.worktrees_removed: list[Path] = []
        self.checkouts: list[str] = []
        self.rebase_conflicts: set[tuple[str, str]] = set()  # (source, onto) → conflict
        self.manifests: dict[str, continuation.ContinuationManifest] = {}
        self.pending_unparseable = False
        self.sleeps: list[float] = []

    # ---------------------------------------------------------------- train

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
            delivery_lineage=self.lineage,
            base="main",
            redirected_from=None,
            layers=tuple(self.layers),
            # Deliberately 0 even for fully-claimed worlds: sync's universe is the claimed
            # prefix, never the classifier's verified prefix.
            published_prefix_len=0,
            unresolved_operation=None,
            findings=self.findings,
            build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="veto"),
            observed_base_head_sha=self.base_head,
        )

    # ---------------------------------------------------------------- git seams

    def _fetch(self, root: Path, refspecs: list[str]) -> None:
        if self.fetch_boom is not None:
            raise self.fetch_boom
        self.timeline.append(("fetch", tuple(refspecs)))

    def _remote_head(self, root: Path, branch: str) -> str | None:
        if self.remote_head_boom is not None:
            raise self.remote_head_boom
        return self.remote.get(branch)

    def _local_head(self, root: Path, ref: str) -> str | None:
        return self.local.get(ref)

    def _is_ancestor(self, root: Path, ancestor: str, head: str) -> bool:
        return ancestor == head or (ancestor, head) in self.ancestry

    def _push_urls(self, root: Path) -> list[str]:
        return list(self.urls)

    def _atomic_probe(self, root: Path, url: str, branch: str, sha: str) -> None:
        self.timeline.append(("atomic_probe", url, branch, sha))
        if self.atomic_probe_boom is not None:
            raise self.atomic_probe_boom

    def _push_atomic(self, root: Path, updates: list[git.RefUpdate]) -> None:
        self.timeline.append(
            ("push_atomic", tuple((u.branch, u.expected_remote_sha, u.new_sha) for u in updates))
        )
        if self.push_reject:
            self.remote.update(self.push_reject_leaves)
            if self.on_push is not None:
                self.on_push()
            raise git.PushRejectedError("a lease was stale")
        for update in updates:
            self.remote[update.branch] = update.new_sha
        if self.on_push is not None:
            self.on_push()

    def _update_ref(self, root: Path, ref: str, sha: str) -> None:
        self.timeline.append(("update_ref", ref, sha))
        self.refs[ref] = sha

    def _delete_ref(self, root: Path, ref: str) -> None:
        self.refs.pop(ref, None)

    def _list_refs(self, root: Path, prefix: str) -> list[str]:
        return sorted(ref for ref in self.refs if ref.startswith(prefix))

    def _worktree_add(self, root: Path, path: Path, commit: str) -> None:
        self.timeline.append(("worktree_add", str(path), commit))
        self.worktrees_added.append((path, commit))

    def _worktree_remove(self, root: Path, path: Path) -> None:
        self.worktrees_removed.append(path)

    def _checkout_detached(self, worktree: Path, sha: str) -> None:
        self.checkouts.append(sha)

    def _rebase_onto(self, worktree: Path, *, onto: str, upstream: str) -> git.RebaseOutcome:
        source = self.checkouts[-1]
        self.timeline.append(("rebase", source, onto, upstream))
        if (source, onto) in self.rebase_conflicts:
            return git.RebaseConflict(detail="CONFLICT (content): parent.txt")
        return git.RebaseCompleted(head_sha=_reb(source, onto))

    # ---------------------------------------------------------------- github seams

    def _pr_facts(self, *, number: int, repo_root: Path) -> PrDeliveryFacts | None:
        if self.pr_facts_script:
            value = self.pr_facts_script.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
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
            head_sha=self.remote.get(branch) or "",
        )

    def _stack_read(self, *, number: int, repo_root: Path) -> StackRestFacts | None:
        self.timeline.append(("stack_read", number))
        if self.stack_members is None or number not in self.stack_members:
            return None
        entries = tuple(
            StackRestEntry(
                pr_number=n,
                state="open",
                draft=True,
                merged=False,
                head_ref=f"pr-{n}",
                head_sha="",
            )
            for n in self.stack_members
        )
        return StackRestFacts(number=9, size=len(entries), entries=entries)

    # ---------------------------------------------------------------- continuation seams

    def _pending_read(self, root: Path, lineage: str) -> continuation.PendingContinuation | None:
        path = Path(f"/main/.perk/workflow/sync-continuations/{lineage}.json")
        if self.pending_unparseable:
            return continuation.PendingContinuation(path=path, manifest=None)
        manifest = self.manifests.get(lineage)
        if manifest is None:
            return None
        return continuation.PendingContinuation(path=path, manifest=manifest)

    def _manifest_write(self, root: Path, manifest: continuation.ContinuationManifest) -> Path:
        self.timeline.append(("manifest_write", manifest.delivery_lineage))
        self.manifests[manifest.delivery_lineage] = manifest
        return Path(f"/main/.perk/workflow/sync-continuations/{manifest.delivery_lineage}.json")

    # ---------------------------------------------------------------- driving

    def sync(
        self,
        *,
        include_base: bool = False,
        approve: Callable[[sync.SyncCascade], bool] | None = None,
        run_id: str = "01RUN",
    ) -> sync.SyncResult:
        return sync.synchronize_train(
            ROOT,
            objective_id=OBJECTIVE,
            run_id=run_id,
            include_base=include_base,
            approve=approve,
            remote_writers=self.writer_probe,
            worktree_root=WT_ROOT,
            reconstruct=self._reconstruct,
            persistence_factory=lambda root: self.persistence,
            pr_facts=self._pr_facts,
            stack_read=self._stack_read,
            fetch=self._fetch,
            remote_head=self._remote_head,
            local_head=self._local_head,
            is_ancestor=self._is_ancestor,
            push_urls=self._push_urls,
            atomic_push_probe=self._atomic_probe,
            push_atomic=self._push_atomic,
            update_ref=self._update_ref,
            delete_ref=self._delete_ref,
            list_refs=self._list_refs,
            worktree_add=self._worktree_add,
            worktree_remove=self._worktree_remove,
            checkout_detached=self._checkout_detached,
            rebase_onto=self._rebase_onto,
            pending_read=self._pending_read,
            manifest_write=self._manifest_write,
            sleep=self.sleeps.append,
            now=lambda: "2026-01-01T00:00:00Z",
        )

    def events(self, kind: str) -> list[tuple]:
        return [t for t in self.timeline if t[0] == kind]

    def assert_guard_cleaned(self) -> None:
        """The centralized cleanup guard fired: no temp refs survive and every created
        isolated worktree was removed."""
        assert self.refs == {}
        if self.worktrees_added:
            assert self.worktrees_removed == [path for path, _ in self.worktrees_added]

    def assert_nothing_journaled(self) -> None:
        assert self.persistence.prepared == []
        assert self.persistence.outcomes == []
        assert self.persistence.checkpoints == []


def _three_layer_world() -> _World:
    """A fully claimed three-layer train, remote exactly at its checkpoints."""
    world = _World(
        [
            _layer("1.1", "101", pr_number=201, parent_checkpoint_sha=MAIN, published_head_sha=P1),
            _layer("1.2", "102", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=P2),
            _layer("1.3", "103", pr_number=203, parent_checkpoint_sha=P2, published_head_sha=P3),
        ]
    )
    world.remote.update({"plan-101": P1, "plan-102": P2, "plan-103": P3})
    world.pr_entries = {
        201: ("plan-101", "main", "OPEN"),
        202: ("plan-102", "plan-101", "OPEN"),
        203: ("plan-103", "plan-102", "OPEN"),
    }
    world.stack_members = [201, 202, 203]
    return world


def _amended_middle_world() -> _World:
    """The default cascade scenario: layer 1.2's branch was amended locally (P2 → C2)."""
    world = _three_layer_world()
    world.local["plan-102"] = C2
    world.ancestry.add((P1, C2))  # C2 still contains its parent checkpoint
    return world


def _sync_error(world: _World, **kwargs) -> sync.SyncError:
    with pytest.raises(sync.SyncError) as excinfo:
        world.sync(**kwargs)
    return excinfo.value


# ----------------------------------------------------------------- the fresh cascade


R3 = _reb(P3, C2)  # layer 1.3's transplant onto the amended C2


def test_local_change_cascades_the_published_suffix():
    world = _amended_middle_world()
    result = world.sync()
    assert result.no_op is False and result.declined is False and result.resumed is False
    assert result.base_cascaded is False
    assert result.operation_id is not None and result.abandoned_operation_id is None
    assert result.objective_id == OBJECTIVE and result.objective_url == "u"
    assert [
        (s.node_id, s.plan_id, s.branch, s.pr_number, s.before_sha, s.after_sha)
        for s in result.affected
    ] == [
        ("1.2", "102", "plan-102", 202, P2, C2),  # the changed layer: fast path, no rebase
        ("1.3", "103", "plan-103", 203, P3, R3),  # its successor: transplanted
    ]
    # The changed layer's candidate IS its local head (new parent edge unchanged → no
    # rebase); only the successor transplants.
    assert world.events("rebase") == [("rebase", P3, C2, P2)]
    # One atomic push, every affected ref under its exact lease.
    assert world.events("push_atomic") == [
        ("push_atomic", (("plan-102", P2, C2), ("plan-103", P3, R3)))
    ]
    assert world.remote["plan-102"] == C2 and world.remote["plan-103"] == R3
    # Checkpoints bottom→top with the NEW parent edges, then completed.
    assert world.persistence.checkpoints == [("102", P1, C2), ("103", C2, R3)]
    outcome = world.persistence.outcomes[-1]
    assert outcome.role is EventRole.COMPLETED
    assert outcome.observed == {
        "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
        "prs": [{"number": 202, "head_sha": C2}, {"number": 203, "head_sha": R3}],
    }
    world.assert_guard_cleaned()


def test_ordering_prepared_push_verify_checkpoints_completed():
    world = _amended_middle_world()
    world.sync()
    kinds = [t[0] for t in world.timeline]
    assert kinds.index("prepared") < kinds.index("push_atomic")
    assert kinds.index("push_atomic") < kinds.index("checkpoints")
    assert kinds.index("checkpoints") < kinds.index("outcome")
    # The bottom-up checkpoint order.
    assert [t[1] for t in world.events("checkpoints")] == ["102", "103"]
    # Candidates are calculated (and approval passes) BEFORE the prepared record.
    assert kinds.index("update_ref") < kinds.index("prepared")


def test_prepared_record_payload_pins():
    world = _amended_middle_world()
    world.sync()
    record = world.persistence.prepared[0]
    assert record.operation_kind is OperationKind.SYNC
    assert record.delivery_lineage == LINEAGE and record.run_id == "01RUN"
    assert record.affected_plans == ("102", "103")
    assert record.before == {
        "base": None,
        "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}],
        "prs": [
            {"number": 202, "head_sha": P2, "base": "plan-101"},
            {"number": 203, "head_sha": P3, "base": "plan-102"},
        ],
        "stack": {"members": [201, 202, 203]},
    }
    assert record.after == {
        "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
        "prs": [
            {"number": 202, "head_sha": C2, "base": "plan-101"},
            {"number": 203, "head_sha": R3, "base": "plan-102"},
        ],
        "base_parent": None,
    }


def test_base_cascade_parent_edge_arithmetic():
    # --base with an advanced base: the bottom layer re-anchors onto the observed base head,
    # every successor transplants onto its predecessor's fresh candidate.
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    r1 = _reb(P1, NEWBASE)
    r2 = _reb(P2, r1)
    r3 = _reb(P3, r2)
    result = world.sync(include_base=True)
    assert result.base_cascaded is True
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [
        (P1, r1),
        (P2, r2),
        (P3, r3),
    ]
    assert world.events("rebase") == [
        ("rebase", P1, NEWBASE, MAIN),
        ("rebase", P2, r1, P1),
        ("rebase", P3, r2, P2),
    ]
    assert world.persistence.checkpoints == [
        ("101", NEWBASE, r1),
        ("102", r1, r2),
        ("103", r2, r3),
    ]
    record = world.persistence.prepared[0]
    assert record.before["base"] == {"branch": "main", "sha": NEWBASE}
    assert record.after["base_parent"] == NEWBASE
    world.assert_guard_cleaned()


def test_the_cascade_is_offered_for_approval_with_base_facts():
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    seen: list[sync.SyncCascade] = []

    def approve(cascade: sync.SyncCascade) -> bool:
        seen.append(cascade)
        return True

    world.sync(include_base=True, approve=approve)
    (cascade,) = seen
    assert cascade.objective_id == OBJECTIVE
    assert cascade.include_base is True
    assert cascade.base_branch == "main"
    assert cascade.base_before == MAIN and cascade.base_after == NEWBASE
    assert [layer.pr_number for layer in cascade.layers] == [201, 202, 203]


# ----------------------------------------------------------------- the no-op + declined arms


def test_no_local_change_is_the_typed_no_op():
    world = _three_layer_world()
    result = world.sync()
    assert result.no_op is True and result.operation_id is None
    assert result.affected == () and result.base_cascaded is False
    assert result.base_advanced is False
    world.assert_nothing_journaled()
    assert world.worktrees_added == []  # no candidate work at all


def test_no_op_carries_the_base_advanced_notice():
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.findings = (
        TrainFinding(kind=FindingKind.INFO, code="base_advanced", message="advanced"),
    )
    result = world.sync()  # no --base: the advance is a notice, never an implicit cascade
    assert result.no_op is True and result.base_advanced is True
    world.assert_nothing_journaled()


def test_stale_local_branch_is_never_a_revert_source():
    # The local branch resolves BEHIND the published head (an ancestor): information, never
    # a trigger — the cascade must not "sync" the remote back to the stale head.
    world = _three_layer_world()
    stale = "5" * 40
    world.local["plan-102"] = stale
    world.ancestry.add((stale, P2))
    result = world.sync()
    assert result.no_op is True
    world.assert_nothing_journaled()


def test_declined_cascade_journals_nothing_and_cleans_the_guard():
    world = _amended_middle_world()
    result = world.sync(approve=lambda cascade: False)
    assert result.declined is True and result.no_op is False
    assert result.operation_id is None and result.affected == ()
    world.assert_nothing_journaled()
    assert world.events("push_atomic") == []
    assert world.worktrees_added != []  # candidates were calculated…
    world.assert_guard_cleaned()  # …and the guard cleaned them up


# ----------------------------------------------------------------- claimed-prefix derivation


def test_half_checkpoint_pair_is_malformed():
    world = _three_layer_world()
    world.layers[1] = _layer(
        "1.2", "102", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=None
    )
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "half a checkpoint pair" in str(error)


def test_checkpointed_layer_missing_identity_is_malformed():
    world = _three_layer_world()
    world.layers[1] = _layer(
        "1.2", "102", pr_number=None, parent_checkpoint_sha=P1, published_head_sha=P2
    )
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "identity" in str(error)


def test_claimed_layer_above_unclaimed_is_malformed():
    world = _three_layer_world()
    world.layers[1] = _layer("1.2", "102", pr_number=202)  # no checkpoints
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "contiguous" in str(error)


def test_unclaimed_suffix_is_simply_outside_the_universe():
    # A trailing unpublished layer is fine — the claimed prefix just ends below it.
    world = _amended_middle_world()
    world.layers.append(_layer("1.4", "104"))
    result = world.sync()
    assert [s.plan_id for s in result.affected] == ["102", "103"]


# ----------------------------------------------------------------- drift reachability


def test_drifted_bottom_layer_is_remote_drift_never_a_false_no_op():
    # The classifier would truncate its verified prefix at the drifted bottom layer; sync's
    # claimed universe keeps the layer in scope so the drift refusal is REACHABLE.
    world = _three_layer_world()
    world.remote["plan-101"] = "9" * 40
    error = _sync_error(world)
    assert error.error_type == "remote_drift"
    assert "plan-101" in str(error)
    world.assert_nothing_journaled()


def test_drifted_upper_claimed_layer_blocks_a_lower_cascade():
    world = _amended_middle_world()  # the trigger is layer 1.2…
    world.remote["plan-103"] = "9" * 40  # …but the claimed layer ABOVE it drifted
    error = _sync_error(world)
    assert error.error_type == "remote_drift"
    assert "plan-103" in str(error)


# ----------------------------------------------------------------- the preflight refusal matrix


def test_not_stacked_when_no_train():
    world = _three_layer_world()
    world.no_train = True
    assert _sync_error(world).error_type == "not_stacked"


def test_missing_lineage_is_not_stacked():
    world = _three_layer_world()
    world.lineage = None
    assert _sync_error(world).error_type == "not_stacked"


def test_foreign_unresolved_kind_refuses():
    world = _amended_middle_world()
    record = _record(operation_kind=OperationKind.PUBLISH, affected_plans=("102",))
    world.persistence.unresolved_records[record.operation_id] = record
    assert _sync_error(world).error_type == "unresolved_operation"


def test_pr_drift_rows():
    for mutate in (
        lambda w: w.pr_entries.__setitem__(202, ("plan-102", "plan-101", "CLOSED")),
        lambda w: w.pr_entries.__setitem__(202, ("plan-102", "main", "OPEN")),  # wrong base
        lambda w: w.pr_entries.pop(202),  # absent
    ):
        world = _amended_middle_world()
        mutate(world)
        error = _sync_error(world)
        assert error.error_type == "pr_drift"
        world.assert_nothing_journaled()


def test_membership_drift():
    world = _amended_middle_world()
    world.stack_members = [201, 202]  # the claimed prefix is not exactly stacked
    assert _sync_error(world).error_type == "membership_drift"


def test_dirty_worktree_refuses():
    world = _amended_middle_world()
    world.layers[2] = _layer(
        "1.3",
        "103",
        pr_number=203,
        parent_checkpoint_sha=P2,
        published_head_sha=P3,
        writer=LayerWriter.DIRTY,
    )
    error = _sync_error(world)
    assert error.error_type == "dirty_worktree"
    assert "1.3" in str(error)


def test_clean_active_worktree_does_not_block():
    # A clean checked-out worktree is the normal state of the just-amended layer.
    world = _amended_middle_world()
    world.layers[1] = _layer(
        "1.2",
        "102",
        pr_number=202,
        parent_checkpoint_sha=P1,
        published_head_sha=P2,
        writer=LayerWriter.ACTIVE,
    )
    assert world.sync().no_op is False


def test_active_remote_writer_refuses():
    world = _amended_middle_world()
    world.writer_probe.active = frozenset({"103"})
    error = _sync_error(world)
    assert error.error_type == "active_writer"
    assert "103" in str(error)
    assert world.writer_probe.calls == [("101", "102", "103")]


def test_writer_probe_failure_fails_closed():
    world = _amended_middle_world()
    world.writer_probe.boom = sync.WriterObservationError("gh api down")
    error = _sync_error(world)
    assert error.error_type == "writer_observation_unavailable"
    assert "gh api down" in str(error)


def test_include_base_with_unobserved_base_refuses():
    world = _three_layer_world()
    world.base_head = None
    error = _sync_error(world, include_base=True)
    assert error.error_type == "base_unobserved"


def test_stale_parent_refuses():
    world = _amended_middle_world()
    world.ancestry.discard((P1, C2))  # the amended head no longer contains its parent edge
    error = _sync_error(world)
    assert error.error_type == "stale_parent"
    assert "plan-102" in str(error)


def test_multiple_push_urls_refuses():
    world = _amended_middle_world()
    world.urls = ["https://gh/octo/repo.git", "/mirror.git"]
    error = _sync_error(world)
    assert error.error_type == "multiple_push_urls"


def test_atomic_push_unsupported():
    world = _amended_middle_world()
    world.atomic_probe_boom = git.GitError("atomic not supported")
    error = _sync_error(world)
    assert error.error_type == "atomic_push_unsupported"
    # The probe was pinned to the bottom AFFECTED layer's branch at its verified head.
    assert world.events("atomic_probe") == [
        ("atomic_probe", "https://gh/octo/repo.git", "plan-102", P2)
    ]


# ----------------------------------------------------------------- the conflict stop


def test_rebase_conflict_retains_residue_under_a_manifest():
    world = _amended_middle_world()
    world.rebase_conflicts.add((P3, C2))  # layer 1.3's transplant conflicts
    error = _sync_error(world)
    assert error.error_type == "rebase_conflict"
    assert "1.3" in str(error)
    assert "no remote ref and no journal record" in str(error)
    # The guard DISARMED: temp refs + worktree retained, manifest written.
    manifest = world.manifests[LINEAGE]
    assert manifest.conflict_node_id == "1.3"
    assert manifest.include_base is False and manifest.captured_base_head is None
    assert [
        (layer.node_id, layer.new_parent_edge, layer.candidate_sha) for layer in manifest.layers
    ] == [
        ("1.2", P1, C2),  # the completed layer below the conflict
        ("1.3", C2, None),  # the conflicting layer: parent known, no candidate
    ]
    assert manifest.worktree_path == str(world.worktrees_added[0][0])
    assert world.worktrees_removed == []
    assert world.refs != {}  # the completed candidate's temp ref survives
    world.assert_nothing_journaled()
    assert world.events("push_atomic") == []
    # The write ordering: the manifest lands before the error propagates, never after
    # any journal/push event (there are none).
    kinds = [t[0] for t in world.timeline]
    assert "manifest_write" in kinds and "prepared" not in kinds


def test_continuation_gate_refuses_a_fresh_sync():
    world = _amended_middle_world()
    world.manifests[LINEAGE] = continuation.ContinuationManifest(
        operation_id=mint_operation_id(),
        objective_id=OBJECTIVE,
        delivery_lineage=LINEAGE,
        run_id="01RUN",
        include_base=False,
        captured_base_head=None,
        layers=(),
        conflict_node_id="1.3",
        worktree_path="/wt/sync-OP",
        created="2026-01-01T00:00:00Z",
    )
    error = _sync_error(world)
    assert error.error_type == "sync_conflict_pending"
    assert "/wt/sync-OP" in str(error)  # names the retained worktree
    assert "sync-continuations" in str(error)  # …and the manifest path
    world.assert_nothing_journaled()


def test_unparseable_manifest_still_gates():
    world = _amended_middle_world()
    world.pending_unparseable = True
    error = _sync_error(world)
    assert error.error_type == "sync_conflict_pending"
    assert "could not be parsed" in str(error)


def test_cross_lineage_manifest_does_not_gate():
    world = _amended_middle_world()
    world.manifests["01OTHERLINEAGE"] = continuation.ContinuationManifest(
        operation_id=mint_operation_id(),
        objective_id="777",
        delivery_lineage="01OTHERLINEAGE",
        run_id="01RUN",
        include_base=False,
        captured_base_head=None,
        layers=(),
        conflict_node_id="9.9",
        worktree_path="/wt/sync-X",
        created="2026-01-01T00:00:00Z",
    )
    assert world.sync().no_op is False  # this lineage cascades untouched


# ----------------------------------------------------------------- the approval race


def test_remote_mutation_during_approval_is_remote_drift_with_no_record():
    world = _amended_middle_world()

    def approve(cascade: sync.SyncCascade) -> bool:
        world.remote["plan-103"] = "9" * 40  # a foreign writer moves a lease mid-approval
        return True

    error = _sync_error(world, approve=approve)
    assert error.error_type == "remote_drift"
    assert "re-observed after approval" in str(error)
    world.assert_nothing_journaled()  # NO prepared record was written
    world.assert_guard_cleaned()


def test_base_mutation_during_approval_is_remote_drift():
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE

    def approve(cascade: sync.SyncCascade) -> bool:
        world.remote["main"] = "9" * 40
        return True

    error = _sync_error(world, include_base=True, approve=approve)
    assert error.error_type == "remote_drift"
    world.assert_nothing_journaled()


# ----------------------------------------------------------------- push rejection


def test_push_rejected_all_before_abandons_with_proof():
    world = _amended_middle_world()
    world.push_reject = True
    error = _sync_error(world)
    assert error.error_type == "push_rejected"
    # Abandoned-with-proof: the one outcome is ABANDONED carrying the all-before observation.
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.ABANDONED
    assert outcome.observed == {
        "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}]
    }
    assert world.persistence.checkpoints == []
    world.assert_guard_cleaned()


def test_push_rejected_mixed_observation_is_sync_drift_unresolved():
    world = _amended_middle_world()
    world.push_reject = True
    world.push_reject_leaves = {"plan-103": "9" * 40}  # neither before nor after
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert world.persistence.outcomes == []  # unresolved — no abandon without proof
    assert world.persistence.unresolved_records  # the prepared record stays open
    world.assert_guard_cleaned()


def test_push_rejected_unreadable_refetch_is_postcondition_unverified():
    world = _amended_middle_world()
    world.push_reject = True
    world.on_push = lambda: setattr(world, "remote_head_boom", git.GitError("net down"))
    error = _sync_error(world)
    assert error.error_type == "postcondition_unverified"
    assert world.persistence.outcomes == []


# ----------------------------------------------------------------- postcondition verification


def test_foreign_writer_after_push_is_sync_drift_unresolved():
    world = _amended_middle_world()
    world.on_push = lambda: world.remote.__setitem__("plan-103", "9" * 40)
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert world.persistence.checkpoints == []
    assert world.persistence.unresolved_records


def test_unreadable_branch_refetch_is_postcondition_unverified():
    world = _amended_middle_world()
    world.on_push = lambda: setattr(world, "fetch_boom", git.GitError("net down"))
    error = _sync_error(world)
    assert error.error_type == "postcondition_unverified"


def test_pr_settle_poll_converges_on_a_stale_then_current_read():
    world = _amended_middle_world()
    stale = PrDeliveryFacts(
        number=202,
        state="OPEN",
        is_draft=True,
        base_ref="plan-101",
        head_ref="plan-102",
        head_sha=P2,  # the pre-push head: GitHub has not propagated yet
    )
    world.on_push = lambda: world.pr_facts_script.append(stale)
    result = world.sync()
    assert result.operation_id is not None
    assert world.sleeps == [2.0]  # exactly one settle wait before the converged read


def test_pr_still_stale_after_the_poll_is_pr_drift():
    world = _amended_middle_world()
    stale = PrDeliveryFacts(
        number=202,
        state="OPEN",
        is_draft=True,
        base_ref="plan-101",
        head_ref="plan-102",
        head_sha=P2,
    )
    world.on_push = lambda: world.pr_facts_script.extend([stale] * 5)
    error = _sync_error(world)
    assert error.error_type == "pr_drift"
    assert len(world.sleeps) == 4  # the full bounded poll
    assert world.persistence.checkpoints == []


def test_unreadable_pr_read_is_postcondition_unverified():
    world = _amended_middle_world()
    world.on_push = lambda: world.pr_facts_script.append(GitHubError("boom"))
    error = _sync_error(world)
    assert error.error_type == "postcondition_unverified"


def test_membership_no_longer_exact_after_push_is_membership_drift():
    world = _amended_middle_world()
    world.on_push = lambda: setattr(world, "stack_members", [201, 202])
    error = _sync_error(world)
    assert error.error_type == "membership_drift"
    assert world.persistence.checkpoints == []


# ----------------------------------------------------------------- the resume matrix


def _record(
    *,
    operation_kind: OperationKind = OperationKind.SYNC,
    affected_plans: tuple[str, ...] = ("102", "103"),
    before: dict | None = None,
    after: dict | None = None,
    lineage: str = LINEAGE,
) -> PreparedRecord:
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=operation_kind,
        delivery_lineage=lineage,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="2026-01-01T00:00:00Z",
        affected_plans=affected_plans,
        before=before
        if before is not None
        else {
            "base": None,
            "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}],
            "prs": [
                {"number": 202, "head_sha": P2, "base": "plan-101"},
                {"number": 203, "head_sha": P3, "base": "plan-102"},
            ],
            "stack": {"members": [201, 202, 203]},
        },
        after=after
        if after is not None
        else {
            "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
            "prs": [
                {"number": 202, "head_sha": C2, "base": "plan-101"},
                {"number": 203, "head_sha": R3, "base": "plan-102"},
            ],
            "base_parent": None,
        },
    )


def _resume_world(record: PreparedRecord) -> _World:
    world = _amended_middle_world()
    world.persistence.unresolved_records[record.operation_id] = record
    return world


def test_resume_all_after_rolls_forward_under_the_same_operation():
    record = _record()
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})  # the push landed; nothing else did
    result = world.sync()
    assert result.resumed is True
    assert result.operation_id == record.operation_id
    assert result.abandoned_operation_id is None
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [(P2, C2), (P3, R3)]
    # Steps 13-14 only: no fresh candidates, no push — verify then persist.
    assert world.events("push_atomic") == [] and world.worktrees_added == []
    assert world.persistence.checkpoints == [("102", P1, C2), ("103", C2, R3)]
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED


def test_resume_all_before_abandons_with_proof_and_prepares_fresh():
    record = _record()
    world = _resume_world(record)  # remote still at P2/P3; the local amend still stands
    result = world.sync()
    assert result.resumed is False
    assert result.abandoned_operation_id == record.operation_id
    assert result.operation_id is not None and result.operation_id != record.operation_id
    # The abandon-with-proof came first, then the fresh prepared record.
    roles = [outcome.role for outcome in world.persistence.outcomes]
    assert roles == [EventRole.ABANDONED, EventRole.COMPLETED]
    assert world.persistence.outcomes[0].observed == {
        "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}]
    }
    assert world.persistence.prepared[0].operation_id == result.operation_id
    assert world.remote["plan-102"] == C2  # the fresh cascade pushed


def test_resume_mixed_state_is_sync_drift_unresolved():
    record = _record()
    world = _resume_world(record)
    world.remote["plan-102"] = C2  # one ref applied, the other still at before
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert world.persistence.outcomes == []  # unresolved, fail closed
    assert world.persistence.unresolved_records


def test_resume_corroboration_drift_rows():
    # The fresh reconstruction must still agree with the record: a foreign lineage, a
    # missing plan, a renamed branch, and a re-staged PR are each sync_drift.
    rows: list[Callable[[_World], None]] = [
        lambda w: w.layers.__setitem__(
            1,
            _layer("1.2", "999", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=P2),
        ),
        lambda w: w.layers.__setitem__(
            1,
            _layer(
                "1.2",
                "102",
                pr_number=202,
                parent_checkpoint_sha=P1,
                published_head_sha=P2,
                branch="plan-renamed",
            ),
        ),
        lambda w: w.layers.__setitem__(
            1,
            _layer("1.2", "102", pr_number=999, parent_checkpoint_sha=P1, published_head_sha=P2),
        ),
    ]
    for mutate in rows:
        record = _record()
        world = _resume_world(record)
        mutate(world)
        assert _sync_error(world).error_type == "sync_drift"


def test_resume_foreign_lineage_record_is_sync_drift():
    record = _record(lineage="01FOREIGN")
    world = _resume_world(record)
    assert _sync_error(world).error_type == "sync_drift"


def test_resume_base_cascade_restores_recorded_parent_edges():
    r1 = _reb(P1, NEWBASE)
    record = _record(
        affected_plans=("101", "102", "103"),
        before={
            "base": {"branch": "main", "sha": NEWBASE},
            "branches": [
                {"ref": "plan-101", "sha": P1},
                {"ref": "plan-102", "sha": P2},
                {"ref": "plan-103", "sha": P3},
            ],
            "prs": [
                {"number": 201, "head_sha": P1, "base": "main"},
                {"number": 202, "head_sha": P2, "base": "plan-101"},
                {"number": 203, "head_sha": P3, "base": "plan-102"},
            ],
            "stack": {"members": [201, 202, 203]},
        },
        after={
            "branches": [
                {"ref": "plan-101", "sha": r1},
                {"ref": "plan-102", "sha": _reb(P2, r1)},
                {"ref": "plan-103", "sha": _reb(P3, _reb(P2, r1))},
            ],
            "prs": [
                {"number": 201, "head_sha": r1, "base": "main"},
                {"number": 202, "head_sha": _reb(P2, r1), "base": "plan-101"},
                {"number": 203, "head_sha": _reb(P3, _reb(P2, r1)), "base": "plan-102"},
            ],
            "base_parent": NEWBASE,
        },
    )
    world = _three_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote.update(
        {"plan-101": r1, "plan-102": _reb(P2, r1), "plan-103": _reb(P3, _reb(P2, r1))}
    )
    result = world.sync()
    assert result.resumed is True and result.base_cascaded is True
    assert world.persistence.checkpoints == [
        ("101", NEWBASE, r1),
        ("102", r1, _reb(P2, r1)),
        ("103", _reb(P2, r1), _reb(P3, _reb(P2, r1))),
    ]


# ----------------------------------------------------------------- the cleanup guard


def _race_approve(world: _World) -> Callable[[sync.SyncCascade], bool]:
    def race(cascade: sync.SyncCascade) -> bool:
        world.remote["plan-103"] = "9" * 40
        return True

    return race


def test_guard_cleans_on_every_non_conflict_exit_arm():
    arms: list[tuple[str, Callable[[_World], None], Callable[[_World], dict]]] = [
        ("success", lambda w: None, lambda w: {}),
        ("declined", lambda w: None, lambda w: {"approve": lambda c: False}),
        ("push_rejected", lambda w: setattr(w, "push_reject", True), lambda w: {}),
        (
            "postcondition_unverified",
            lambda w: setattr(w, "on_push", lambda: setattr(w, "fetch_boom", git.GitError("x"))),
            lambda w: {},
        ),
        ("remote_drift (approval race)", lambda w: None, lambda w: {"approve": _race_approve(w)}),
    ]
    for name, mutate, make_kwargs in arms:
        world = _amended_middle_world()
        mutate(world)
        with contextlib.suppress(sync.SyncError):
            world.sync(**make_kwargs(world))
        assert world.refs == {}, name
        assert world.worktrees_removed == [p for p, _ in world.worktrees_added], name


# ----------------------------------------------------------------- structural blockers + lineage


def test_structural_blockers_refuse_before_any_route():
    # A structurally mis-linked plan (owned by a foreign objective) must never be pushed or
    # checkpointed, even when the live branch/PR observations all look consistent.
    world = _amended_middle_world()
    world.findings = (
        TrainFinding(
            kind=FindingKind.BLOCKER,
            code="wrong_owner",
            message="plan #102 is owned by objective #999",
        ),
    )
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "wrong_owner" in str(error)
    world.assert_nothing_journaled()
    assert world.worktrees_added == []  # refused before any candidate work


def test_operational_drift_blockers_pass_through_to_syncs_own_preflight():
    # The operational axes (checkpoint/PR/stack drift) stay sync's own fresh observation —
    # a stale projection blocker must not veto a world sync re-verifies itself.
    world = _amended_middle_world()
    world.findings = (
        TrainFinding(kind=FindingKind.BLOCKER, code="checkpoint_drift", message="stale"),
    )
    result = world.sync()
    assert result.no_op is False and result.operation_id is not None


def test_malformed_lineage_is_invalid_input():
    world = _amended_middle_world()
    world.lineage = "../../evil"
    error = _sync_error(world)
    assert error.error_type == "invalid_input"
    assert "path-safe" in str(error)
    world.assert_nothing_journaled()


# ----------------------------------------------------------------- more approval-race axes


def test_pr_mutation_during_approval_is_remote_drift_with_no_record():
    world = _amended_middle_world()

    def approve(cascade: sync.SyncCascade) -> bool:
        world.pr_entries[203] = ("plan-103", "plan-102", "CLOSED")  # a PR flips mid-approval
        return True

    error = _sync_error(world, approve=approve)
    assert error.error_type == "remote_drift"
    world.assert_nothing_journaled()
    world.assert_guard_cleaned()


def test_membership_mutation_during_approval_is_remote_drift_with_no_record():
    world = _amended_middle_world()

    def approve(cascade: sync.SyncCascade) -> bool:
        world.stack_members = [201, 202]  # the native stack is edited mid-approval
        return True

    error = _sync_error(world, approve=approve)
    assert error.error_type == "remote_drift"
    world.assert_nothing_journaled()
    world.assert_guard_cleaned()


# ----------------------------------------------------------------- the one-layer train


C1 = "a" * 40  # layer 1.1's amended local head (single-layer scenario)


def _one_layer_world() -> _World:
    world = _World(
        [_layer("1.1", "101", pr_number=201, parent_checkpoint_sha=MAIN, published_head_sha=P1)]
    )
    world.remote.update({"plan-101": P1})
    world.pr_entries = {201: ("plan-101", "main", "OPEN")}
    world.stack_members = None  # below two PRs there is no native stack at all
    world.local["plan-101"] = C1
    world.ancestry.add((MAIN, C1))
    return world


def test_single_layer_train_cascades_without_stack_work():
    world = _one_layer_world()
    result = world.sync()
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [(P1, C1)]
    assert world.events("stack_read") == []  # membership is not_applicable: never read
    record = world.persistence.prepared[0]
    assert record.before["stack"] is None  # …and serialized as the null observation
    assert record.affected_plans == ("101",)
    assert world.events("push_atomic") == [("push_atomic", (("plan-101", P1, C1),))]
    assert world.remote["plan-101"] == C1
    assert world.persistence.checkpoints == [("101", MAIN, C1)]
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED
    world.assert_guard_cleaned()


# ----------------------------------------------------------------- resume fail-closed rows


def test_resume_malformed_payload_rows_fail_closed():
    # Structurally incomplete/corrupt prepared payloads are sync_drift — never resumed, never
    # completed, no checkpoints; the operation stays unresolved.
    good = _record()
    rows: list[dict] = [
        # A truncated after.branches array (parallel-array break).
        {
            "after": {
                "branches": [{"ref": "plan-102", "sha": C2}],
                "prs": dict(good.after)["prs"],
                "base_parent": None,
            }
        },
        # A non-list branches payload.
        {"before": {**dict(good.before), "branches": "junk"}},
        # A branch entry whose after ref disagrees with its before ref.
        {
            "after": {
                "branches": [
                    {"ref": "plan-999", "sha": C2},
                    {"ref": "plan-103", "sha": R3},
                ],
                "prs": dict(good.after)["prs"],
                "base_parent": None,
            }
        },
    ]
    for overrides in rows:
        record = _record(**overrides)
        world = _resume_world(record)
        error = _sync_error(world)
        assert error.error_type == "sync_drift", overrides
        assert world.persistence.outcomes == [] and world.persistence.checkpoints == []
        assert world.persistence.unresolved_records  # fail closed: still unresolved


def test_resume_stale_recorded_pr_base_is_sync_drift():
    # The record captured plan-102's PR onto 'main', but the fresh train derives 'plan-101' —
    # the base topology moved while the operation was unresolved.
    record = _record(
        after={
            "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
            "prs": [
                {"number": 202, "head_sha": C2, "base": "main"},  # stale
                {"number": 203, "head_sha": R3, "base": "plan-102"},
            ],
            "base_parent": None,
        }
    )
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})  # even a landed push cannot resume
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "PR base" in str(error)
    assert world.persistence.outcomes == [] and world.persistence.checkpoints == []


def test_resume_missing_stored_checkpoints_is_sync_drift():
    record = _record()
    world = _resume_world(record)
    world.layers[1] = _layer("1.2", "102", pr_number=202)  # checkpoints vanished from store
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "checkpoints" in str(error)
    assert world.persistence.outcomes == [] and world.persistence.checkpoints == []


def test_resume_non_contiguous_affected_order_is_sync_drift():
    # The record names plans 102+103 but the fresh roadmap inserted a layer between them.
    record = _record()
    world = _resume_world(record)
    world.layers.insert(
        2,
        _layer("1.2b", "150", pr_number=250, parent_checkpoint_sha=P2, published_head_sha=P3),
    )
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "affected order" in str(error)


def test_resume_roll_forward_verifies_recorded_membership():
    record = _record()
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})  # all-after…
    world.stack_members = [201, 202]  # …but the recorded membership no longer holds
    error = _sync_error(world)
    assert error.error_type == "membership_drift"
    assert world.persistence.checkpoints == []
    assert world.persistence.unresolved_records


def test_resume_all_before_then_declined_keeps_the_abandoned_id():
    # The all-before abandon re-runs the FULL fresh protocol; a declined fresh cascade keeps
    # the declined shape (operation_id null) while carrying the abandoned id — the abandon
    # was journaled as an OUTCOME under the old id, never a prepared record.
    record = _record()
    world = _resume_world(record)
    result = world.sync(approve=lambda cascade: False)
    assert result.declined is True and result.operation_id is None
    assert result.abandoned_operation_id == record.operation_id
    assert [o.role for o in world.persistence.outcomes] == [EventRole.ABANDONED]
    assert world.persistence.prepared == []
    world.assert_guard_cleaned()
