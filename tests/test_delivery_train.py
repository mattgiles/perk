"""Tests for the pure ``DeliveryTrain`` reconstruction (``perk/delivery/train.py``).

In-memory fakes for every injected seam (objective reader, plan reader, journal reader, Git
probe, GitHub probe) — hermetic, no subprocess/network. Pins the pipeline arm by arm: policy
short-circuits, canonical ordering, the node↔plan join corroborations, journal surfacing, the
git/pr/membership/publication axes, the published prefix, and the forward supersession
redirect.
"""

from dataclasses import dataclass, field

import pytest

from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import NativeCancellation, ObjectiveState
from perk.delivery import journal as journal_mod
from perk.delivery.train import (
    NO_TRAIN_INCREMENTAL_REASON,
    BaseHeadObservation,
    BranchPrView,
    FindingKind,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    NoDeliveryTrain,
    PrFactsView,
    ProjectedCancellation,
    StackEntryView,
    StackView,
    TrainFinding,
    TrainReconstructionError,
    WorktreeFacts,
    reconstruct_train,
)
from perk.objective import NodeStatus, ObjectiveNode

_LINEAGE = "01JB0000000000000000000000"
_OP = "01JA0000000000000000000000"
_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40
_SHA_D = "d" * 40


# ----------------------------------------------------------------- fakes


class _FakeStore:
    def __init__(self) -> None:
        self.objectives: dict[str, ObjectiveState] = {}

    def add(
        self,
        objective_id: str,
        *,
        header: dict[str, object] | None = None,
        nodes: tuple[ObjectiveNode, ...] = (),
    ) -> None:
        self.objectives[objective_id] = ObjectiveState(
            id=objective_id,
            url=f"fake://objective/{objective_id}",
            title="t",
            header=dict(header or {}),
            nodes=nodes,
        )

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        # GitHub-shaped boundary: accepts the canonical `#<n>` rendering.
        return self.objectives.get(objective_id.removeprefix("#"))


@dataclass
class _FakeIssues:
    plans: dict[str, PlanState] = field(default_factory=dict)

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        return self.plans.get(issue_id)


@dataclass
class _FakeJournal:
    fold: journal_mod.JournalFold | None = None
    corrupt: str | None = None
    calls: list[str] = field(default_factory=list)

    def read_journal(self, objective_id: str) -> journal_mod.JournalFold:
        self.calls.append(objective_id)
        if self.corrupt is not None:
            raise journal_mod.JournalCorruptionError(self.corrupt)
        if self.fold is not None:
            return self.fold
        # The default fold seeds completed PUBLISH coverage for the suite's two published
        # fixture plans: a checkpoint pair may only exist because a PUBLISH completed
        # (§8.54's coverage invariant), so the clean fixtures carry the honest history.
        return _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
        )


@dataclass
class _FakeGit:
    branches: dict[str, str] = field(default_factory=dict)
    ancestry: dict[tuple[str, str], bool | None] = field(default_factory=dict)
    worktrees: tuple[WorktreeFacts, ...] = ()
    fail_fetch: bool = False
    fetches: int = 0
    # The authoritative base observation (defaults to "observed, unmoved": tests that pin
    # exact finding lists stay focused; the base arms are pinned in TestBaseObservation).
    base_head_sha: str | None = _SHA_A
    base_head_failure: str | None = None
    base_head_queries: list[str] = field(default_factory=list)

    def fetch(self) -> None:
        self.fetches += 1
        if self.fail_fetch:
            raise TrainReconstructionError("git fetch failed: boom", error_type="git_error")

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.branches.get(branch)

    def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool | None:
        if ancestor_sha == head_sha:
            return True
        return self.ancestry.get((ancestor_sha, head_sha))

    def worktree_branches(self) -> tuple[WorktreeFacts, ...]:
        return self.worktrees

    def base_head(self, branch: str) -> BaseHeadObservation:
        self.base_head_queries.append(branch)
        if self.base_head_failure is not None:
            return BaseHeadObservation(sha=None, failure=self.base_head_failure)
        return BaseHeadObservation(sha=self.base_head_sha, failure=None)


@dataclass
class _FakeGitHub:
    prs: dict[int, PrFactsView] = field(default_factory=dict)
    stack: StackView = field(default_factory=lambda: StackView(available=True, stacked=False))
    stack_queries: list[int] = field(default_factory=list)
    branch_prs: dict[str, BranchPrView] = field(default_factory=dict)
    branch_queries: list[str] = field(default_factory=list)

    def pr_facts(self, number: int) -> PrFactsView | None:
        return self.prs.get(number)

    def pr_stack(self, number: int) -> StackView:
        self.stack_queries.append(number)
        return self.stack

    def pr_for_branch(self, branch: str) -> BranchPrView | None:
        self.branch_queries.append(branch)
        return self.branch_prs.get(branch)


# ----------------------------------------------------------------- builders


def _node(
    node_id: str,
    *,
    pr: str | None = None,
    status: NodeStatus = NodeStatus.PENDING,
    depends_on: tuple[str, ...] | None = None,
) -> ObjectiveNode:
    return ObjectiveNode(
        id=node_id, description=f"node {node_id}", status=status, pr=pr, depends_on=depends_on
    )


def _stacked_header(**extra: object) -> dict[str, object]:
    header: dict[str, object] = {"delivery": "stacked", "delivery_lineage": _LINEAGE}
    header.update(extra)
    return header


def _plan(
    plan_id: str,
    *,
    objective_id: str = "10",
    node_id: str | None = None,
    lineage: str | None = _LINEAGE,
    predecessor: str | None = None,
    parent_sha: str | None = None,
    published_sha: str | None = None,
    branch: str | None = None,
    pr: str | None = None,
    state: str = "OPEN",
    header_extra: dict[str, object] | None = None,
) -> PlanState:
    header: dict[str, object] = {"run_id": "r", "created": "t", "objective_id": objective_id}
    if node_id is not None:
        header["objective_node_id"] = node_id
    if lineage is not None:
        header["delivery_lineage"] = lineage
    if predecessor is not None:
        header["predecessor_plan_id"] = predecessor
    if parent_sha is not None:
        header["parent_checkpoint_sha"] = parent_sha
    if published_sha is not None:
        header["published_head_sha"] = published_sha
    if branch is not None:
        header["branch"] = branch
    if pr is not None:
        header["pr"] = pr
    header.update(header_extra or {})
    return PlanState(
        id=plan_id,
        url=f"fake://plan/{plan_id}",
        title="p",
        header=header,
        pr=None,
        state=state,
    )


def _open_pr(
    number: int,
    *,
    base: str,
    draft: bool = False,
    head_ref: str = "plan-101",  # matches `_single_plan_store`'s default layer branch
    head_sha: str = _SHA_B,
) -> PrFactsView:
    return PrFactsView(
        number=number,
        state="OPEN",
        is_draft=draft,
        base_ref=base,
        head_ref=head_ref,
        head_sha=head_sha,
    )


def _unresolved_op(
    operation_id: str = _OP,
    *,
    kind: journal_mod.OperationKind = journal_mod.OperationKind.PUBLISH,
    created: str = "2026-02-01T00:00:00Z",
    plan_id: str = "101",
) -> journal_mod.OperationState:
    record = journal_mod.PreparedRecord(
        operation_id=operation_id,
        operation_kind=kind,
        delivery_lineage=_LINEAGE,
        objective_id="10",
        run_id="01JC0000000000000000000000",
        created=created,
        affected_plans=(plan_id,),
        before={},
        after={},
    )
    event = journal_mod.JournalEvent(
        record=record,
        role=journal_mod.EventRole.PREPARED,
        operation_id=operation_id,
        canonical_payload=journal_mod.canonical_payload(record),
        comment_id="c1",
        created_at=created,
        carrier_objective_id="10",
    )
    return journal_mod.OperationState(
        operation_id=operation_id,
        kind=kind,
        prepared=event,
        accepted=None,
        outcome=None,
    )


def _concluded_publish_op(
    operation_id: str,
    *,
    plan_id: str,
    role: journal_mod.EventRole,
    created: str = "2026-02-01T00:00:00Z",
) -> journal_mod.OperationState:
    """A PUBLISH operation folded to a terminal outcome (completed/abandoned)."""
    prepared = _unresolved_op(operation_id, plan_id=plan_id, created=created)
    outcome_record = journal_mod.OutcomeRecord(
        operation_id=operation_id, role=role, created=created, observed={}
    )
    outcome = journal_mod.JournalEvent(
        record=outcome_record,
        role=role,
        operation_id=operation_id,
        canonical_payload=journal_mod.canonical_payload(outcome_record),
        comment_id="c2",
        created_at=created,
        carrier_objective_id="10",
    )
    return journal_mod.OperationState(
        operation_id=operation_id,
        kind=journal_mod.OperationKind.PUBLISH,
        prepared=prepared.prepared,
        accepted=None,
        outcome=outcome,
    )


def _completed_publish_op(operation_id: str, *, plan_id: str) -> journal_mod.OperationState:
    return _concluded_publish_op(
        operation_id, plan_id=plan_id, role=journal_mod.EventRole.COMPLETED
    )


def _fold(*ops: journal_mod.OperationState) -> journal_mod.JournalFold:
    return journal_mod.JournalFold(
        events=tuple(op.prepared for op in ops),
        operations={op.operation_id: op for op in ops},
        unresolved=tuple(op for op in ops if not op.resolved),
        delivery_lineage=_LINEAGE,
    )


def _unresolved_fold(*ops: journal_mod.OperationState) -> journal_mod.JournalFold:
    states = list(ops) if ops else [_unresolved_op()]
    return _fold(*states)


def _reconstruct(
    store: _FakeStore,
    *,
    objective_id: str = "10",
    issues: _FakeIssues | None = None,
    persistence: _FakeJournal | None = None,
    git: _FakeGit | None = None,
    github: _FakeGitHub | None = None,
    trunk: str = "main",
):
    return reconstruct_train(
        objective_id,
        store=store,
        issues=issues or _FakeIssues(),
        persistence=persistence or _FakeJournal(),
        git=git or _FakeGit(),
        github=github or _FakeGitHub(),
        trunk=trunk,
    )


def _published_two_layer() -> tuple[_FakeStore, _FakeIssues, _FakeGit, _FakeGitHub]:
    """A fully-published, exactly-stacked two-layer train (the clean baseline scenario)."""
    store = _FakeStore()
    store.add(
        "10",
        header=_stacked_header(),
        nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102")),
    )
    issues = _FakeIssues(
        {
            "101": _plan(
                "101",
                node_id="1.1",
                parent_sha=_SHA_A,
                published_sha=_SHA_B,
                branch="plan-101",
                pr="#201",
            ),
            "102": _plan(
                "102",
                node_id="1.2",
                predecessor="101",
                parent_sha=_SHA_B,
                published_sha=_SHA_C,
                branch="plan-102",
                pr="#202",
            ),
        }
    )
    git = _FakeGit(
        branches={"plan-101": _SHA_B, "plan-102": _SHA_C},
        ancestry={(_SHA_A, _SHA_B): True, (_SHA_B, _SHA_C): True},
    )
    github = _FakeGitHub(
        prs={
            201: _open_pr(201, base="main", head_ref="plan-101", head_sha=_SHA_B),
            202: _open_pr(202, base="plan-101", head_ref="plan-102", head_sha=_SHA_C),
        },
        stack=StackView(
            available=True,
            stacked=True,
            entries=(StackEntryView(1, 201), StackEntryView(2, 202)),
        ),
    )
    return store, issues, git, github


def _codes(status, kind: FindingKind | None = None) -> list[str]:
    return [f.code for f in status.findings if kind is None or f.kind is kind]


# ----------------------------------------------------------------- policy + validation


class TestPolicy:
    def test_incremental_objective_is_a_successful_no_train(self) -> None:
        store = _FakeStore()
        store.add("10", header={}, nodes=(_node("1.1"),))
        git = _FakeGit()
        status = _reconstruct(store, git=git)
        assert status == NoDeliveryTrain(
            objective_id="10",
            objective_url="fake://objective/10",
            redirected_from=None,
            reason=NO_TRAIN_INCREMENTAL_REASON,
        )
        # Short-circuits before any Git/GitHub work.
        assert git.fetches == 0

    def test_junk_delivery_policy_fails_closed(self) -> None:
        store = _FakeStore()
        store.add("10", header={"delivery": "yolo"}, nodes=(_node("1.1"),))
        with pytest.raises(TrainReconstructionError) as excinfo:
            _reconstruct(store)
        assert excinfo.value.error_type == "invalid_delivery_policy"

    def test_missing_objective_is_typed(self) -> None:
        with pytest.raises(TrainReconstructionError) as excinfo:
            _reconstruct(_FakeStore(), objective_id="404")
        assert excinfo.value.error_type == "objective_not_found"

    def test_structural_invalidity_is_invalid_train_with_exact_errors(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(
                _node("1.1", depends_on=("1.2",)),
                _node("1.2", depends_on=("1.1",)),
                _node("1.3", depends_on=("9.9",)),
            ),
        )
        with pytest.raises(TrainReconstructionError) as excinfo:
            _reconstruct(store)
        assert excinfo.value.error_type == "invalid_train"
        assert "cycle" in str(excinfo.value)
        assert "unknown node: 9.9" in str(excinfo.value)

    def test_runtime_never_enforces_the_authoring_bound(self) -> None:
        # One non-skipped node fails authoring validation but renders at runtime as a train
        # with a dynamic_singleton information finding.
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", status=NodeStatus.SKIPPED), _node("1.2")),
        )
        status = _reconstruct(store)
        assert status.__class__.__name__ == "DeliveryTrain"
        assert _codes(status, FindingKind.INFO) == ["dynamic_singleton"]
        assert [layer.node_id for layer in status.layers] == ["1.2"]
        assert status.layers[0].membership is LayerMembership.NOT_APPLICABLE

    def test_all_skipped_completes_without_a_merge(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(
                _node("1.1", status=NodeStatus.SKIPPED),
                _node("1.2", status=NodeStatus.SKIPPED),
            ),
        )
        status = _reconstruct(store)
        assert status.layers == ()
        assert _codes(status) == ["all_skipped"]


class TestOrdering:
    def test_canonical_delivery_order_on_a_non_linear_dag(self) -> None:
        # Fan-out: 1.2 and 1.3 both depend on 1.1; 1.4 fans in. Kahn + node_sort_key gives the
        # deterministic 1.1, 1.2, 1.3, 1.4 regardless of declaration order.
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(
                _node("1.4", depends_on=("1.2", "1.3")),
                _node("1.3", depends_on=("1.1",)),
                _node("1.2", depends_on=("1.1",)),
                _node("1.1", depends_on=()),
            ),
        )
        status = _reconstruct(store)
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2", "1.3", "1.4"]


# ----------------------------------------------------------------- the node↔plan join


class TestJoin:
    def test_missing_backlink_is_unplanned(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1"), _node("1.2")))
        status = _reconstruct(store)
        assert all(layer.intent is LayerIntent.UNPLANNED for layer in status.layers)
        assert status.blockers == ()

    def test_dangling_backlink_is_missing_plan(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        status = _reconstruct(store)
        assert _codes(status, FindingKind.BLOCKER) == ["missing_plan"]
        assert "plan #101" in status.blockers[0].message
        # The deterministic worktree convention still names the branch.
        assert status.layers[0].branch == "plan-101"

    def test_two_nodes_sharing_one_plan_is_duplicate_plan_link(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#101")),
        )
        issues = _FakeIssues({"101": _plan("101", node_id="1.1")})
        status = _reconstruct(store, issues=issues)
        assert "duplicate_plan_link" in _codes(status, FindingKind.BLOCKER)
        dup = next(f for f in status.blockers if f.code == "duplicate_plan_link")
        assert "1.1" in dup.message and "1.2" in dup.message

    def test_header_corroboration_blockers(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102")),
        )
        issues = _FakeIssues(
            {
                "101": _plan("101", objective_id="99", node_id="1.1"),
                "102": _plan("102", node_id="7.7", lineage="01JB0000000000000000000001"),
            }
        )
        status = _reconstruct(store, issues=issues)
        codes = _codes(status, FindingKind.BLOCKER)
        assert codes == ["wrong_owner", "node_link_mismatch", "wrong_lineage"]
        wrong_owner = status.blockers[0]
        assert "99" in wrong_owner.message and "10" in wrong_owner.message
        assert "7.7" in status.blockers[1].message and "1.2" in status.blockers[1].message
        assert _LINEAGE in status.blockers[2].message

    def test_absent_ownership_identity_is_a_conflict(self) -> None:
        # ABSENT objective_id / objective_node_id on a linked plan is a conflict too — a
        # node-linked plan always carries them (only lineage gets the pre-publication
        # absence exception).
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        headerless = PlanState(
            id="101",
            url="fake://plan/101",
            title="p",
            header={"run_id": "r", "created": "t"},
            pr=None,
            state="OPEN",
        )
        status = _reconstruct(store, issues=_FakeIssues({"101": headerless}))
        codes = _codes(status, FindingKind.BLOCKER)
        assert codes == ["wrong_owner", "node_link_mismatch"]
        assert "no objective_id" in status.blockers[0].message
        assert "no objective_node_id" in status.blockers[1].message

    def test_half_checkpoint_pair_is_incomplete(self) -> None:
        # The pair is written together in ONE update — a half-pair is broken stored state:
        # the dedicated `checkpoint_pair_incomplete` blocker (`checkpoint_drift` is reserved
        # for remote/head/ancestry mismatch), and never verified publication even with every
        # observation matching.
        store, issues = _single_plan_store(published_sha=_SHA_B, pr="#201")
        git = _FakeGit(branches={"plan-101": _SHA_B})
        github = _FakeGitHub(prs={201: _open_pr(201, base="main")})
        status = _reconstruct(store, issues=issues, git=git, github=github)
        incomplete = [f for f in status.blockers if f.code == "checkpoint_pair_incomplete"]
        assert any("pair is written together" in f.message for f in incomplete)
        assert status.layers[0].publication is LayerPublication.PUBLICATION_DRIFT
        assert status.published_prefix_len == 0

    def test_checkpoints_without_lineage_is_a_conflict(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        issues = _FakeIssues(
            {"101": _plan("101", node_id="1.1", lineage=None, published_sha=_SHA_B)}
        )
        status = _reconstruct(store, issues=issues)
        assert "lineage_checkpoint_conflict" in _codes(status, FindingKind.BLOCKER)

    def test_non_string_header_junk_is_malformed_plan_header(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        issues = _FakeIssues(
            {"101": _plan("101", node_id="1.1", header_extra={"published_head_sha": 42})}
        )
        status = _reconstruct(store, issues=issues)
        malformed = [f for f in status.blockers if f.code == "malformed_plan_header"]
        assert len(malformed) == 1
        assert "published_head_sha" in malformed[0].message and "42" in malformed[0].message

    def test_integer_pr_header_resolves_through_the_shared_parser(self) -> None:
        # A positive-integer raw `pr` is a VALID claim (§8.54's tolerant boundary) — it must
        # resolve to the PR number, never classify as malformed via the string-only helper.
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        issues = _FakeIssues(
            {
                "101": _plan(
                    "101",
                    node_id="1.1",
                    parent_sha=_SHA_A,
                    published_sha=_SHA_B,
                    header_extra={"pr": 201},
                )
            }
        )
        status = _reconstruct(store, issues=issues)
        assert "malformed_plan_header" not in _codes(status, FindingKind.BLOCKER)
        missing = [f for f in status.blockers if f.code == "missing_pr"]
        assert any("PR #201" in f.message for f in missing)  # resolved, then observed absent

    def test_unresolvable_pr_header_is_malformed(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        issues = _FakeIssues({"101": _plan("101", node_id="1.1", header_extra={"pr": -3})})
        status = _reconstruct(store, issues=issues)
        malformed = [f for f in status.blockers if f.code == "malformed_plan_header"]
        assert len(malformed) == 1 and "'pr'" in malformed[0].message

    def test_predecessor_mismatch_carries_both_ids(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102")),
        )
        issues = _FakeIssues(
            {
                "101": _plan("101", node_id="1.1"),
                "102": _plan("102", node_id="1.2", predecessor="999"),
            }
        )
        status = _reconstruct(store, issues=issues)
        assert _codes(status, FindingKind.BLOCKER) == ["predecessor_mismatch"]
        assert "#999" in status.blockers[0].message and "#101" in status.blockers[0].message

    def test_stored_predecessor_absent_is_legal_pre_publication(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102")),
        )
        issues = _FakeIssues(
            {"101": _plan("101", node_id="1.1"), "102": _plan("102", node_id="1.2")}
        )
        status = _reconstruct(store, issues=issues)
        assert status.blockers == ()


# ----------------------------------------------------------------- journal


class TestJournal:
    def test_missing_lineage_is_a_blocker_and_skips_the_journal(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header={"delivery": "stacked"},
            nodes=(_node("1.1"), _node("1.2")),
        )
        persistence = _FakeJournal()
        status = _reconstruct(store, persistence=persistence)
        assert _codes(status, FindingKind.BLOCKER) == ["missing_lineage"]
        assert persistence.calls == []
        assert status.unresolved_operation is None

    def test_unresolved_operation_is_surfaced_as_information(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1"), _node("1.2")))
        persistence = _FakeJournal(fold=_unresolved_fold())
        status = _reconstruct(store, persistence=persistence)
        assert persistence.calls == ["10"]
        assert status.unresolved_operation is not None
        assert status.unresolved_operation.operation_id == _OP
        assert status.unresolved_operation.kind == "publish"
        assert status.unresolved_operation.prepared_created == "2026-02-01T00:00:00Z"
        assert _codes(status, FindingKind.INFO) == ["active_operation"]
        assert status.blockers == ()

    def test_every_unresolved_operation_is_exposed_with_a_finding_each(self) -> None:
        # The §8.44 detailed-status widening: ALL of fold.unresolved ride
        # `unresolved_operations` (fold order); the legacy single field is the first.
        second = "01JD0000000000000000000000"
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1"), _node("1.2")))
        fold = _unresolved_fold(
            _unresolved_op(),
            _unresolved_op(
                second,
                kind=journal_mod.OperationKind.SYNC,
                created="2026-02-02T00:00:00Z",
            ),
        )
        status = _reconstruct(store, persistence=_FakeJournal(fold=fold))
        assert [
            (facts.operation_id, facts.kind, facts.prepared_created)
            for facts in status.unresolved_operations
        ] == [
            (_OP, "publish", "2026-02-01T00:00:00Z"),
            (second, "sync", "2026-02-02T00:00:00Z"),
        ]
        assert status.unresolved_operation == status.unresolved_operations[0]
        assert _codes(status, FindingKind.INFO) == ["active_operation", "active_operation"]

    def test_journal_corruption_is_a_blocker_not_an_abort(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1"), _node("1.2")))
        persistence = _FakeJournal(corrupt="conflicting duplicate on carrier 10")
        status = _reconstruct(store, persistence=persistence)
        assert _codes(status, FindingKind.BLOCKER) == ["journal_corruption"]
        assert "conflicting duplicate" in status.blockers[0].message
        assert status.unresolved_operation is None
        assert status.unresolved_operations == ()


# ----------------------------------------------------------------- git observation


def _single_plan_store(**plan_kwargs) -> tuple[_FakeStore, _FakeIssues]:
    store = _FakeStore()
    store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
    defaults: dict = {"node_id": "1.1", "branch": "plan-101"}
    defaults.update(plan_kwargs)
    return store, _FakeIssues({"101": _plan("101", **defaults)})


class TestGitAxis:
    def test_absent_remote_ref_with_checkpoints_is_drift(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B)
        status = _reconstruct(store, issues=issues, git=_FakeGit())
        layer = status.layers[0]
        assert layer.git is LayerGit.ABSENT
        assert layer.observed_remote_head_sha is None
        drift = [f for f in status.blockers if f.code == "checkpoint_drift"]
        assert len(drift) == 1 and _SHA_B in drift[0].message

    def test_absent_remote_ref_without_checkpoints_is_quiet(self) -> None:
        store, issues = _single_plan_store()
        status = _reconstruct(store, issues=issues, git=_FakeGit())
        assert status.layers[0].git is LayerGit.ABSENT
        assert status.blockers == ()

    def test_remote_at_published_head_is_synced(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B)
        git = _FakeGit(branches={"plan-101": _SHA_B}, ancestry={(_SHA_A, _SHA_B): True})
        status = _reconstruct(store, issues=issues, git=git)
        assert status.layers[0].git is LayerGit.SYNCED
        assert status.layers[0].observed_remote_head_sha == _SHA_B
        assert [f.code for f in status.blockers if f.code == "checkpoint_drift"] == []

    def test_recorded_head_ancestor_of_observed_is_remote_ahead(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B)
        git = _FakeGit(
            branches={"plan-101": _SHA_C},
            ancestry={(_SHA_A, _SHA_C): True, (_SHA_B, _SHA_C): True},
        )
        status = _reconstruct(store, issues=issues, git=git)
        assert status.layers[0].git is LayerGit.REMOTE_AHEAD
        drift = [f for f in status.blockers if f.code == "checkpoint_drift"]
        assert len(drift) == 1 and _SHA_B in drift[0].message and _SHA_C in drift[0].message

    def test_observed_behind_or_unrelated_is_diverged(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B)
        git = _FakeGit(
            branches={"plan-101": _SHA_C},
            ancestry={(_SHA_A, _SHA_C): True, (_SHA_B, _SHA_C): False},
        )
        status = _reconstruct(store, issues=issues, git=git)
        assert status.layers[0].git is LayerGit.DIVERGED

    def test_unknown_ancestry_is_unknown(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B)
        # No ancestry entries: objects unavailable → is_ancestor None everywhere.
        git = _FakeGit(branches={"plan-101": _SHA_C})
        status = _reconstruct(store, issues=issues, git=git)
        assert status.layers[0].git is LayerGit.UNKNOWN

    def test_unknown_parent_ancestry_never_reads_synced(self) -> None:
        # The remote head MATCHES the recorded head, but the parent-ancestry check is
        # unknowable (objects unavailable): verification is incomplete → UNKNOWN, never a
        # silently-promoted SYNCED/PUBLISHED.
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B, pr="#201")
        git = _FakeGit(branches={"plan-101": _SHA_B})  # no ancestry entries → is_ancestor None
        github = _FakeGitHub(prs={201: _open_pr(201, base="main", head_sha=_SHA_B)})
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.layers[0].git is LayerGit.UNKNOWN
        assert status.layers[0].publication is LayerPublication.PUBLICATION_DRIFT
        assert status.published_prefix_len == 0

    def test_head_not_containing_parent_checkpoint_is_wrong_parent(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B)
        git = _FakeGit(branches={"plan-101": _SHA_B}, ancestry={(_SHA_A, _SHA_B): False})
        status = _reconstruct(store, issues=issues, git=git)
        assert status.layers[0].git is LayerGit.WRONG_PARENT
        drift = [f for f in status.blockers if f.code == "checkpoint_drift"]
        assert len(drift) == 1 and _SHA_A in drift[0].message

    def test_writer_axis_from_worktrees(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102"), _node("1.3", pr="#103")),
        )
        issues = _FakeIssues(
            {
                "101": _plan("101", node_id="1.1", branch="plan-101"),
                "102": _plan("102", node_id="1.2", branch="plan-102"),
                "103": _plan("103", node_id="1.3", branch="plan-103"),
            }
        )
        git = _FakeGit(
            worktrees=(
                WorktreeFacts(path="/wt/a", branch="plan-101", dirty=False),
                WorktreeFacts(path="/wt/b", branch="plan-102", dirty=True),
            )
        )
        status = _reconstruct(store, issues=issues, git=git)
        assert [layer.writer for layer in status.layers] == [
            LayerWriter.ACTIVE,
            LayerWriter.DIRTY,
            LayerWriter.FREE,
        ]

    def test_fresh_clone_is_never_an_error(self) -> None:
        # Zero worktrees, no remote refs, no local objects: the projection still renders and
        # every writer is FREE (the fresh-clone promise).
        store, issues = _single_plan_store()
        status = _reconstruct(store, issues=issues, git=_FakeGit())
        assert all(layer.writer is LayerWriter.FREE for layer in status.layers)

    def test_fetch_failure_propagates_as_git_error(self) -> None:
        store, issues = _single_plan_store()
        with pytest.raises(TrainReconstructionError) as excinfo:
            _reconstruct(store, issues=issues, git=_FakeGit(fail_fetch=True))
        assert excinfo.value.error_type == "git_error"


# ----------------------------------------------------------------- PR observation


class TestPrAxis:
    def test_checkpoints_with_missing_pr_is_a_blocker(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B, pr="#201")
        git = _FakeGit(branches={"plan-101": _SHA_B})
        status = _reconstruct(store, issues=issues, git=git, github=_FakeGitHub())
        assert status.layers[0].pr is LayerPr.ABSENT
        missing = [f for f in status.blockers if f.code == "missing_pr"]
        assert len(missing) == 1 and "#201" in missing[0].message

    def test_checkpoints_with_no_staged_pr_is_a_blocker(self) -> None:
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B)
        git = _FakeGit(branches={"plan-101": _SHA_B})
        status = _reconstruct(store, issues=issues, git=git)
        assert "missing_pr" in [f.code for f in status.blockers]

    def test_absent_pr_without_checkpoints_is_quiet(self) -> None:
        store, issues = _single_plan_store(pr="#201")
        status = _reconstruct(store, issues=issues)
        assert status.layers[0].pr is LayerPr.ABSENT
        assert status.blockers == ()

    def test_wrong_base_carries_both_refs(self) -> None:
        store, issues = _single_plan_store(pr="#201")
        github = _FakeGitHub(prs={201: _open_pr(201, base="develop")})
        status = _reconstruct(store, issues=issues, github=github)
        layer = status.layers[0]
        assert layer.pr is LayerPr.WRONG_BASE
        assert layer.expected_pr_base == "main" and layer.observed_pr_base == "develop"
        wrong = [f for f in status.blockers if f.code == "pr_wrong_base"]
        assert len(wrong) == 1
        assert "'develop'" in wrong[0].message and "'main'" in wrong[0].message

    def test_non_bottom_layer_expects_the_predecessor_branch(self) -> None:
        store, issues, git, github = _published_two_layer()
        github.prs[202] = _open_pr(202, base="main")  # should be plan-101
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.layers[1].pr is LayerPr.WRONG_BASE
        assert status.layers[1].expected_pr_base == "plan-101"

    def test_draft_and_ready_arms(self) -> None:
        store, issues = _single_plan_store(pr="#201")
        github = _FakeGitHub(prs={201: _open_pr(201, base="main", draft=True)})
        status = _reconstruct(store, issues=issues, github=github)
        assert status.layers[0].pr is LayerPr.DRAFT
        github = _FakeGitHub(prs={201: _open_pr(201, base="main")})
        status = _reconstruct(store, issues=issues, github=github)
        assert status.layers[0].pr is LayerPr.READY

    def test_closed_unmerged_pr_is_a_blocker(self) -> None:
        store, issues = _single_plan_store(pr="#201")
        github = _FakeGitHub(
            prs={
                201: PrFactsView(
                    number=201,
                    state="CLOSED",
                    is_draft=False,
                    base_ref="main",
                    head_ref="h",
                    head_sha=_SHA_B,
                )
            }
        )
        status = _reconstruct(store, issues=issues, github=github)
        assert status.layers[0].pr is LayerPr.CLOSED
        assert "pr_closed" in [f.code for f in status.blockers]

    def test_merged_pr_with_wrong_base_is_still_flagged(self) -> None:
        # The terminal state is preserved on the axis (and finalization still derives), but
        # a layer merged into the WRONG target is the conflict most worth surfacing.
        merged = PrFactsView(
            number=201,
            state="MERGED",
            is_draft=False,
            base_ref="develop",
            head_ref="plan-101",
            head_sha=_SHA_B,
        )
        store, issues = _single_plan_store(pr="#201", state="CLOSED")
        status = _reconstruct(store, issues=issues, github=_FakeGitHub(prs={201: merged}))
        layer = status.layers[0]
        assert layer.pr is LayerPr.MERGED
        assert layer.finalization is LayerFinalization.FINALIZED
        wrong = [f for f in status.blockers if f.code == "pr_wrong_base"]
        assert len(wrong) == 1
        assert "'develop'" in wrong[0].message and "'main'" in wrong[0].message

    def test_pr_head_ref_mismatch_is_a_blocker(self) -> None:
        # The staged PR must actually serve the layer branch — a PR for some other branch
        # never counts as this layer's publication.
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B, pr="#201")
        git = _FakeGit(branches={"plan-101": _SHA_B}, ancestry={(_SHA_A, _SHA_B): True})
        github = _FakeGitHub(
            prs={201: _open_pr(201, base="main", head_ref="other-branch", head_sha=_SHA_B)}
        )
        status = _reconstruct(store, issues=issues, git=git, github=github)
        wrong = [f for f in status.blockers if f.code == "pr_wrong_head"]
        assert len(wrong) == 1
        assert "'other-branch'" in wrong[0].message and "'plan-101'" in wrong[0].message
        assert status.layers[0].publication is LayerPublication.PUBLICATION_DRIFT

    def test_pr_head_sha_skew_is_a_blocker(self) -> None:
        # Right branch, wrong content: the PR head OID disagrees with the observed remote
        # head — the PR is not serving the published state.
        store, issues = _single_plan_store(parent_sha=_SHA_A, published_sha=_SHA_B, pr="#201")
        git = _FakeGit(branches={"plan-101": _SHA_B}, ancestry={(_SHA_A, _SHA_B): True})
        github = _FakeGitHub(
            prs={201: _open_pr(201, base="main", head_ref="plan-101", head_sha=_SHA_D)}
        )
        status = _reconstruct(store, issues=issues, git=git, github=github)
        wrong = [f for f in status.blockers if f.code == "pr_wrong_head"]
        assert len(wrong) == 1
        assert _SHA_D in wrong[0].message and _SHA_B in wrong[0].message
        assert status.layers[0].publication is LayerPublication.PUBLICATION_DRIFT

    def test_merged_pr_maps_onto_finalization(self) -> None:
        merged = PrFactsView(
            number=201,
            state="MERGED",
            is_draft=False,
            base_ref="main",
            head_ref="h",
            head_sha=_SHA_B,
        )
        store, issues = _single_plan_store(pr="#201")
        status = _reconstruct(store, issues=issues, github=_FakeGitHub(prs={201: merged}))
        assert status.layers[0].pr is LayerPr.MERGED
        assert status.layers[0].finalization is LayerFinalization.MERGED
        # Plan issue CLOSED + PR merged → FINALIZED.
        store, issues = _single_plan_store(pr="#201", state="CLOSED")
        status = _reconstruct(store, issues=issues, github=_FakeGitHub(prs={201: merged}))
        assert status.layers[0].finalization is LayerFinalization.FINALIZED


# ----------------------------------------------------------------- publication + membership


class TestPublication:
    def test_fully_published_exact_train_is_clean(self) -> None:
        store, issues, git, github = _published_two_layer()
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert [layer.publication for layer in status.layers] == [
            LayerPublication.PUBLISHED,
            LayerPublication.PUBLISHED,
        ]
        assert [layer.membership for layer in status.layers] == [
            LayerMembership.EXACT,
            LayerMembership.EXACT,
        ]
        assert status.published_prefix_len == 2
        assert status.findings == ()
        assert github.stack_queries == [201]

    def test_unpublished_layers_have_no_checkpoints(self) -> None:
        store, issues = _single_plan_store(pr="#201")
        github = _FakeGitHub(prs={201: _open_pr(201, base="main")})
        status = _reconstruct(store, issues=issues, github=github)
        assert status.layers[0].publication is LayerPublication.UNPUBLISHED
        assert status.published_prefix_len == 0

    def test_observation_mismatch_is_publication_drift(self) -> None:
        store, issues, git, github = _published_two_layer()
        git.branches["plan-102"] = _SHA_D  # drifted off the recorded checkpoint
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.layers[1].publication is LayerPublication.PUBLICATION_DRIFT
        assert status.published_prefix_len == 1

    def test_prefix_gap_when_published_above_non_published(self) -> None:
        store, issues, git, github = _published_two_layer()
        git.branches["plan-101"] = _SHA_D  # the BOTTOM layer drifts; the top stays published
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.published_prefix_len == 0
        assert status.layers[1].publication is LayerPublication.PUBLISHED
        gap = [f for f in status.blockers if f.code == "prefix_gap"]
        assert len(gap) == 1 and gap[0].node_id == "1.2"


class TestMembership:
    def test_single_published_pr_is_not_applicable(self) -> None:
        store, issues, git, github = _published_two_layer()
        # Strip the top layer's checkpoints: only one published PR remains.
        issues.plans["102"] = _plan("102", node_id="1.2", branch="plan-102", pr="#202")
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert all(layer.membership is LayerMembership.NOT_APPLICABLE for layer in status.layers)
        assert github.stack_queries == []
        assert status.blockers == ()

    def test_two_published_prs_with_no_stack_is_stack_missing(self) -> None:
        store, issues, git, github = _published_two_layer()
        github.stack = StackView(available=True, stacked=False)
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert all(layer.membership is LayerMembership.ABSENT for layer in status.layers)
        missing = [f for f in status.blockers if f.code == "stack_missing"]
        assert len(missing) == 1 and "[201, 202]" in missing[0].message
        # Membership is part of verified publication at ≥2 PRs.
        assert all(
            layer.publication is LayerPublication.PUBLICATION_DRIFT for layer in status.layers
        )

    def test_reordered_stack_is_divergent(self) -> None:
        store, issues, git, github = _published_two_layer()
        github.stack = StackView(
            available=True,
            stacked=True,
            entries=(StackEntryView(1, 202), StackEntryView(2, 201)),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert all(layer.membership is LayerMembership.DIVERGENT for layer in status.layers)
        divergent = [f for f in status.blockers if f.code == "stack_divergent"]
        assert len(divergent) == 1
        assert "[201, 202]" in divergent[0].message and "[202, 201]" in divergent[0].message

    def test_extra_stack_entry_is_divergent(self) -> None:
        store, issues, git, github = _published_two_layer()
        github.stack = StackView(
            available=True,
            stacked=True,
            entries=(StackEntryView(1, 201), StackEntryView(2, 202), StackEntryView(3, 999)),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert "stack_divergent" in [f.code for f in status.blockers]

    def test_truncated_stack_is_divergent(self) -> None:
        store, issues, git, github = _published_two_layer()
        github.stack = StackView(
            available=True,
            stacked=True,
            entries=(StackEntryView(1, 201), StackEntryView(2, 202)),
            truncated=True,
        )
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert all(layer.membership is LayerMembership.DIVERGENT for layer in status.layers)

    def test_unavailable_preview_read_is_information_only(self) -> None:
        store, issues, git, github = _published_two_layer()
        github.stack = StackView(available=False)
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert all(layer.membership is LayerMembership.UNKNOWN for layer in status.layers)
        # Preview instability stays INFORMATION (never a blocker) — but unverifiable
        # membership never counts as fully published at ≥2 PRs, so the affected layers
        # declassify to drift and the published prefix drops.
        assert _codes(status, FindingKind.INFO) == ["stack_read_unavailable"]
        assert status.blockers == ()
        assert all(
            layer.publication is LayerPublication.PUBLICATION_DRIFT for layer in status.layers
        )
        assert status.published_prefix_len == 0


# ----------------------------------------------------------------- supersession redirect


class TestRedirect:
    def test_superseded_objective_redirects_forward(self) -> None:
        store = _FakeStore()
        store.add("10", header={"superseded_by": "#20"})
        store.add("20", header=_stacked_header(), nodes=(_node("1.1"), _node("1.2")))
        status = _reconstruct(store, objective_id="10")
        assert status.objective_id == "20"
        assert status.redirected_from == "10"

    def test_unredirected_objective_reports_no_redirect(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1"), _node("1.2")))
        assert _reconstruct(store).redirected_from is None

    def test_incremental_redirect_still_reports_redirected_from(self) -> None:
        store = _FakeStore()
        store.add("10", header={"superseded_by": "#20"})
        store.add("20", header={})
        status = _reconstruct(store, objective_id="10")
        assert isinstance(status, NoDeliveryTrain)
        assert status.objective_id == "20" and status.redirected_from == "10"

    def test_supersession_cycle_is_typed_corruption(self) -> None:
        store = _FakeStore()
        store.add("10", header={"superseded_by": "#20"})
        store.add("20", header={"superseded_by": "#10"})
        with pytest.raises(TrainReconstructionError) as excinfo:
            _reconstruct(store, objective_id="10")
        assert excinfo.value.error_type == "supersession_corruption"

    def test_dangling_forward_pointer_is_typed_corruption(self) -> None:
        store = _FakeStore()
        store.add("10", header={"superseded_by": "#404"})
        with pytest.raises(TrainReconstructionError) as excinfo:
            _reconstruct(store, objective_id="10")
        assert excinfo.value.error_type == "supersession_corruption"

    def test_depth_cap_breach_is_typed_corruption(self) -> None:
        store = _FakeStore()
        for i in range(60):
            header: dict[str, object] = {"superseded_by": f"#{i + 1}"} if i < 59 else {}
            store.add(str(i), header=header)
        with pytest.raises(TrainReconstructionError) as excinfo:
            _reconstruct(store, objective_id="0")
        assert excinfo.value.error_type == "supersession_corruption"


# ----------------------------------------------------------------- build readiness


class TestBuildReadiness:
    def test_bottom_layer_ready_on_an_unpublished_train(self) -> None:
        # Nothing published yet, no blockers → the bottom layer is the buildable candidate.
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        issues = _FakeIssues({"101": _plan("101", node_id="1.1", branch="plan-101")})
        status = _reconstruct(store, issues=issues)
        readiness = status.build_readiness
        assert readiness.next_node_id == "1.1"
        assert readiness.ready is True
        assert readiness.reason is None

    def test_successor_ready_once_the_predecessor_is_published(self) -> None:
        # Layer 1 fully published, layer 2 planned-but-unpublished → 1.2 is buildable.
        store, issues, git, github = _published_two_layer()
        issues.plans["102"] = _plan("102", node_id="1.2", predecessor="101", branch="plan-102")
        del git.branches["plan-102"]
        status = _reconstruct(store, issues=issues, git=git, github=github)
        readiness = status.build_readiness
        assert status.layers[0].publication is LayerPublication.PUBLISHED
        assert readiness.next_node_id == "1.2"
        assert readiness.ready is True and readiness.reason is None

    def test_any_blocker_vetoes_readiness_with_the_exact_findings(self) -> None:
        # A wrong-lineage blocker anywhere on the train fails readiness closed; the reason
        # carries the exact code + message (the blocked answer names the findings).
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        issues = _FakeIssues(
            {"101": _plan("101", node_id="1.1", branch="plan-101", lineage="01JB" + "1" * 22)}
        )
        status = _reconstruct(store, issues=issues)
        readiness = status.build_readiness
        assert readiness.next_node_id == "1.1"
        assert readiness.ready is False
        assert readiness.reason is not None and "[wrong_lineage]" in readiness.reason

    def test_unresolved_operation_vetoes_readiness(self) -> None:
        store = _FakeStore()
        store.add("10", header=_stacked_header(), nodes=(_node("1.1", pr="#101"), _node("1.2")))
        issues = _FakeIssues({"101": _plan("101", node_id="1.1", branch="plan-101")})
        status = _reconstruct(
            store, issues=issues, persistence=_FakeJournal(fold=_unresolved_fold())
        )
        readiness = status.build_readiness
        assert readiness.ready is False
        assert readiness.reason is not None and _OP in readiness.reason

    def test_all_published_has_no_candidate(self) -> None:
        store, issues, git, github = _published_two_layer()
        status = _reconstruct(store, issues=issues, git=git, github=github)
        readiness = status.build_readiness
        assert readiness.next_node_id is None
        assert readiness.ready is False
        assert readiness.reason == "all layers published or landed"

    def test_dynamic_singleton_is_buildable_under_the_bottom_layer_rule(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", status=NodeStatus.SKIPPED), _node("1.2", pr="#102")),
        )
        issues = _FakeIssues({"102": _plan("102", node_id="1.2", branch="plan-102")})
        status = _reconstruct(store, issues=issues)
        readiness = status.build_readiness
        # dynamic_singleton is INFORMATION, never a veto.
        assert _codes(status, FindingKind.INFO) == ["dynamic_singleton"]
        assert readiness.next_node_id == "1.2" and readiness.ready is True

    def test_all_skipped_yields_no_candidate(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(
                _node("1.1", status=NodeStatus.SKIPPED),
                _node("1.2", status=NodeStatus.SKIPPED),
            ),
        )
        status = _reconstruct(store)
        readiness = status.build_readiness
        assert readiness.next_node_id is None
        assert readiness.ready is False
        assert readiness.reason is not None and "no layers" in readiness.reason


# ----------------------------------------------------------------- base observation


class TestBaseObservation:
    def test_advanced_base_is_an_info_finding_with_the_sync_remediation(self) -> None:
        store, issues, git, github = _published_two_layer()
        git.base_head_sha = _SHA_D  # origin/main moved past the anchored parent checkpoint
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.observed_base_head_sha == _SHA_D
        assert git.base_head_queries == ["main"]
        advanced = [f for f in status.information if f.code == "base_advanced"]
        assert len(advanced) == 1
        assert _SHA_D in advanced[0].message and _SHA_A in advanced[0].message
        assert "perk objective stack sync 10 --base" in advanced[0].message
        assert advanced[0].node_id == "1.1"
        assert status.blockers == ()  # INFO, never a blocker

    def test_unmoved_base_is_not_advanced(self) -> None:
        store, issues, git, github = _published_two_layer()
        assert git.base_head_sha == _SHA_A  # the fake default: observed at the anchor
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.observed_base_head_sha == _SHA_A
        assert [f.code for f in status.information] == []

    def test_empty_published_prefix_never_reports_advanced(self) -> None:
        store, issues = _single_plan_store(pr="#201")
        git = _FakeGit(base_head_sha=_SHA_D)
        github = _FakeGitHub(prs={201: _open_pr(201, base="main")})
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.observed_base_head_sha == _SHA_D
        assert "base_advanced" not in [f.code for f in status.findings]

    def test_read_failure_degrades_to_unobserved_naming_the_arm(self) -> None:
        store, issues, git, github = _published_two_layer()
        git.base_head_failure = "ls-remote timed out"
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.observed_base_head_sha is None
        unobserved = [f for f in status.information if f.code == "base_unobserved"]
        assert len(unobserved) == 1
        assert "read failed" in unobserved[0].message
        assert "ls-remote timed out" in unobserved[0].message
        assert status.blockers == ()  # tolerant-degrade: never a blocker, never an abort

    def test_absent_ref_degrades_to_unobserved_naming_the_arm(self) -> None:
        store, issues, git, github = _published_two_layer()
        git.base_head_sha = None  # the remote answered; no such ref (a deleted base)
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert status.observed_base_head_sha is None
        unobserved = [f for f in status.information if f.code == "base_unobserved"]
        assert len(unobserved) == 1
        assert "no refs/heads/main" in unobserved[0].message


# ----------------------------------------------------------------- native cancellation (§8.54)


def _canceled_node(
    node_id: str,
    *,
    persisted: NodeStatus = NodeStatus.PENDING,
    pr: str | None = None,
) -> tuple[ObjectiveNode, NativeCancellation]:
    """A store-shaped native cancellation: the node reads back effectively SKIPPED while the
    persisted attachment status rides provenance."""
    node = ObjectiveNode(
        id=node_id, description=f"node {node_id}", status=NodeStatus.SKIPPED, pr=pr
    )
    return node, NativeCancellation(node_id=node_id, persisted_status=persisted)


def _cancellation_world(
    *,
    persisted: NodeStatus = NodeStatus.PENDING,
    pr: str | None = "#103",
    plan: PlanState | None = None,
    extra_nodes: tuple[ObjectiveNode, ...] = (),
) -> tuple[_FakeStore, _FakeIssues]:
    """A three-node train whose LAST node (1.3) is natively canceled."""
    node, cancellation = _canceled_node("1.3", persisted=persisted, pr=pr)
    store = _FakeStore()
    store.objectives["10"] = ObjectiveState(
        id="10",
        url="fake://objective/10",
        title="t",
        header=_stacked_header(),
        nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102"), node, *extra_nodes),
        native_cancellations=(cancellation,),
    )
    issues = _FakeIssues(
        {
            "101": _plan("101", node_id="1.1", branch="plan-101"),
            "102": _plan("102", node_id="1.2", branch="plan-102"),
        }
    )
    if plan is not None:
        issues.plans["103"] = plan
    return store, issues


class TestCancellationContraction:
    """The exact safe-contraction proof's SAFE arms: the node projects as skipped, the INFO
    finding carries the persisted status, and the projected/repairable facts are typed."""

    def test_unplanned_cancellation_contracts_safely(self) -> None:
        store, issues = _cancellation_world(pr=None)
        status = _reconstruct(store, issues=issues)
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2"]
        assert status.blockers == ()
        info = [f for f in status.information if f.code == "canceled_unpublished_projected"]
        assert len(info) == 1 and info[0].node_id == "1.3"
        assert "persisted status pending" in info[0].message
        assert "perk objective doctor 10 --fix" in info[0].message
        assert status.projected_canceled_nodes == (
            ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING),
        )
        assert status.repairable_canceled_nodes == status.projected_canceled_nodes

    def test_planned_cancellation_with_clean_plan_contracts(self) -> None:
        # The plan resolves, identity corroborates, no checkpoints/PR claims, journal has
        # only an abandoned PUBLISH (acceptable), no remote branch, no branch-owned PR.
        store, issues = _cancellation_world(
            persisted=NodeStatus.PLANNING,
            plan=_plan("103", node_id="1.3", branch="plan-103"),
        )
        fold = _fold(
            _concluded_publish_op(
                "01JA0000000000000000000103",
                plan_id="103",
                role=journal_mod.EventRole.ABANDONED,
            ),
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
        )
        github = _FakeGitHub()
        status = _reconstruct(
            store, issues=issues, persistence=_FakeJournal(fold=fold), github=github
        )
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2"]
        assert status.blockers == ()
        assert status.projected_canceled_nodes == (
            ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PLANNING),
        )
        # The proof observed the stored branch and the all-state branch-owned PR.
        assert github.branch_queries == ["plan-103"]

    def test_legacy_no_claim_pr_spellings_contract(self) -> None:
        # The shared no-claim vocabulary (§8.54): a blank/"None" header spelling is NOT a PR
        # claim — the planned cancellation contracts instead of blocking on a phantom claim.
        for spelling in ("", "None"):
            store, issues = _cancellation_world(
                persisted=NodeStatus.PLANNING,
                plan=_plan("103", node_id="1.3", branch="plan-103", pr=spelling),
            )
            fold = _fold(
                _concluded_publish_op(
                    "01JA0000000000000000000103",
                    plan_id="103",
                    role=journal_mod.EventRole.ABANDONED,
                ),
                _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
                _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            )
            status = _reconstruct(
                store, issues=issues, persistence=_FakeJournal(fold=fold), github=_FakeGitHub()
            )
            assert status.blockers == (), spelling
            assert [layer.node_id for layer in status.layers] == ["1.1", "1.2"]
            assert status.projected_canceled_nodes == (
                ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PLANNING),
            )

    def test_already_skipped_cancellation_is_projected_but_not_repairable(self) -> None:
        store, issues = _cancellation_world(persisted=NodeStatus.SKIPPED, pr=None)
        status = _reconstruct(store, issues=issues)
        info = [f for f in status.information if f.code == "canceled_unpublished_projected"]
        assert len(info) == 1 and "already skipped" in info[0].message
        assert status.projected_canceled_nodes == (
            ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.SKIPPED),
        )
        assert status.repairable_canceled_nodes == ()

    def test_no_provenance_means_existing_behavior(self) -> None:
        # A plain SKIPPED node with no provenance never classifies as a cancellation.
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1"), _node("1.2"), _node("1.3", status=NodeStatus.SKIPPED)),
        )
        status = _reconstruct(store)
        assert _codes(status) == []
        assert status.projected_canceled_nodes == ()


class TestCancellationUnsafe:
    """Every unsafe evidence family: the node stays a projection-only CANCELED layer (the
    PENDING ordering surrogate is never returned/persisted) with ALL applicable blockers."""

    def _one(self, status, code: str) -> TrainFinding:
        hits = [f for f in status.blockers if f.code == code]
        assert len(hits) == 1, f"expected exactly one {code}, got {_codes(status)}"
        return hits[0]

    def test_persisted_done_is_a_status_conflict(self) -> None:
        store, issues = _cancellation_world(persisted=NodeStatus.DONE, pr=None)
        status = _reconstruct(store, issues=issues)
        finding = self._one(status, "canceled_status_conflict")
        assert finding.node_id == "1.3" and "done" in finding.message
        # The unsafe node stays a layer with intent CANCELED; nothing is projected.
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2", "1.3"]
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.projected_canceled_nodes == ()
        assert status.repairable_canceled_nodes == ()

    def test_duplicate_backlink_involving_the_canceled_node_is_unsafe(self) -> None:
        # The global scan preserves duplicates involving canceled nodes (the old layer-only
        # join would have contracted this away silently).
        store, issues = _cancellation_world(pr="#102")
        status = _reconstruct(store, issues=issues)
        dup = self._one(status, "duplicate_plan_link")
        assert "1.2" in dup.message and "1.3" in dup.message
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2", "1.3"]
        assert status.layers[2].intent is LayerIntent.CANCELED

    def test_missing_plan_is_unresolved_and_unsafe(self) -> None:
        store, issues = _cancellation_world()  # plan 103 does not exist
        status = _reconstruct(store, issues=issues)
        self._one(status, "canceled_plan_unresolved")
        # The canonical finding is emitted ONCE (the preload is the join; no re-join).
        self._one(status, "missing_plan")
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.layers[2].branch == "plan-103"  # the deterministic convention

    def test_identity_conflicts_are_unsafe_and_emitted_once(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan("103", objective_id="99", node_id="7.7", branch="plan-103")
        )
        status = _reconstruct(store, issues=issues)
        self._one(status, "wrong_owner")
        self._one(status, "node_link_mismatch")
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.projected_canceled_nodes == ()

    def test_wrong_lineage_is_unsafe(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103", lineage="01OTHER")
        )
        status = _reconstruct(store, issues=issues)
        self._one(status, "wrong_lineage")
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.projected_canceled_nodes == ()

    def test_lineage_checkpoint_conflict_is_unsafe(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan(
                "103",
                node_id="1.3",
                branch="plan-103",
                lineage=None,
                parent_sha=_SHA_A,
                published_sha=_SHA_B,
            )
        )
        status = _reconstruct(store, issues=issues)
        self._one(status, "lineage_checkpoint_conflict")
        # The checkpoint claim independently proves publication — both families emit.
        assert "canceled_published_layer" in _codes(status, FindingKind.BLOCKER)
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.projected_canceled_nodes == ()

    def test_malformed_header_field_is_unsafe(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan(
                "103", node_id="1.3", branch="plan-103", header_extra={"delivery_lineage": 5}
            )
        )
        status = _reconstruct(store, issues=issues)
        self._one(status, "malformed_plan_header")
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.projected_canceled_nodes == ()

    def test_stale_string_predecessor_still_contracts(self) -> None:
        # The deliberate predecessor split: a semantically stale but WELL-TYPED
        # predecessor_plan_id does not prevent contraction (the contracted layer never
        # takes part in predecessor checks)…
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103", predecessor="999")
        )
        status = _reconstruct(store, issues=issues)
        assert status.blockers == ()
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2"]
        assert status.projected_canceled_nodes == (
            ProjectedCancellation(node_id="1.3", persisted_status=NodeStatus.PENDING),
        )

    def test_non_string_predecessor_is_malformed_and_unsafe(self) -> None:
        # …while a NON-STRING one is malformed identity and stays unsafe.
        store, issues = _cancellation_world(
            plan=_plan(
                "103", node_id="1.3", branch="plan-103", header_extra={"predecessor_plan_id": 7}
            )
        )
        status = _reconstruct(store, issues=issues)
        self._one(status, "malformed_plan_header")
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.projected_canceled_nodes == ()

    def test_checkpoints_are_a_published_layer(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103", parent_sha=_SHA_A),
        )
        status = _reconstruct(store, issues=issues)
        published = [f for f in status.blockers if f.code == "canceled_published_layer"]
        assert any(_SHA_A in f.message for f in published)
        assert status.layers[2].intent is LayerIntent.CANCELED

    def test_raw_pr_claim_is_remote_work(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103", pr="#203"),
        )
        status = _reconstruct(store, issues=issues)
        remote = [f for f in status.blockers if f.code == "canceled_remote_work"]
        assert any("PR claim" in f.message for f in remote)

    def test_malformed_raw_pr_claim_is_still_remote_work(self) -> None:
        # The tolerant parser resolves no number, but the RAW claim is cancellation evidence:
        # malformed metadata never reads as "no PR".
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103", pr="garbage"),
        )
        status = _reconstruct(store, issues=issues)
        assert [f.code for f in status.blockers if f.code == "canceled_remote_work"] != []

    def test_remote_branch_is_remote_work(self) -> None:
        store, issues = _cancellation_world(plan=_plan("103", node_id="1.3", branch="plan-103"))
        git = _FakeGit(branches={"plan-103": _SHA_D})
        status = _reconstruct(store, issues=issues, git=git)
        remote = self._one(status, "canceled_remote_work")
        assert "plan-103" in remote.message and _SHA_D in remote.message

    def test_branch_owned_pr_in_any_state_is_remote_work(self) -> None:
        store, issues = _cancellation_world(plan=_plan("103", node_id="1.3", branch="plan-103"))
        github = _FakeGitHub(branch_prs={"plan-103": BranchPrView(number=203, state="CLOSED")})
        status = _reconstruct(store, issues=issues, github=github)
        remote = self._one(status, "canceled_remote_work")
        assert "#203" in remote.message and "CLOSED" in remote.message

    def test_missing_lineage_makes_planned_cancellation_unprovable(self) -> None:
        node, cancellation = _canceled_node("1.3", pr="#103")
        store = _FakeStore()
        store.objectives["10"] = ObjectiveState(
            id="10",
            url="fake://objective/10",
            title="t",
            header={"delivery": "stacked"},  # no lineage
            nodes=(_node("1.1"), _node("1.2"), node),
            native_cancellations=(cancellation,),
        )
        issues = _FakeIssues({"103": _plan("103", node_id="1.3", lineage=None)})
        persistence = _FakeJournal()
        status = _reconstruct(store, issues=issues, persistence=persistence)
        assert persistence.calls == []  # no lineage to fold against
        codes = _codes(status, FindingKind.BLOCKER)
        assert "missing_lineage" in codes and "cancellation_evidence_unavailable" in codes
        assert status.layers[2].intent is LayerIntent.CANCELED

    def test_journal_corruption_fails_planned_cancellation_closed(self) -> None:
        store, issues = _cancellation_world(plan=_plan("103", node_id="1.3", branch="plan-103"))
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(corrupt="boom"))
        codes = _codes(status, FindingKind.BLOCKER)
        assert "journal_corruption" in codes and "cancellation_evidence_unavailable" in codes

    def test_unplanned_cancellation_needs_no_journal_evidence(self) -> None:
        # No plan backlink: no plan/branch/journal identity exists — corruption elsewhere
        # never blocks THIS contraction.
        store, issues = _cancellation_world(pr=None)
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(corrupt="boom"))
        assert "cancellation_evidence_unavailable" not in _codes(status)
        assert status.projected_canceled_nodes != ()

    def test_completed_publish_is_a_published_layer(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103"),
        )
        fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _completed_publish_op("01JA0000000000000000000103", plan_id="103"),
        )
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(fold=fold))
        published = self._one(status, "canceled_published_layer")
        assert "01JA0000000000000000000103" in published.message

    def test_unresolved_publish_is_publication_pending(self) -> None:
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103"),
        )
        fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _unresolved_op("01JA0000000000000000000103", plan_id="103"),
        )
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(fold=fold))
        pending = self._one(status, "canceled_publication_pending")
        assert "01JA0000000000000000000103" in pending.message
        # The unresolved operation still rides active_operation (INFO).
        assert "active_operation" in _codes(status, FindingKind.INFO)

    def test_completed_and_unresolved_publish_both_emit(self) -> None:
        # The two journal predicates are INDEPENDENT — a fold carrying BOTH a completed and
        # an unresolved PUBLISH for the canceled plan emits both blockers (an `elif`
        # regression would silently suppress the pending one).
        store, issues = _cancellation_world(
            plan=_plan("103", node_id="1.3", branch="plan-103"),
        )
        fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _completed_publish_op("01JA0000000000000000000113", plan_id="103"),
            _unresolved_op("01JA0000000000000000000123", plan_id="103"),
        )
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(fold=fold))
        published = self._one(status, "canceled_published_layer")
        pending = self._one(status, "canceled_publication_pending")
        assert "01JA0000000000000000000113" in published.message
        assert "01JA0000000000000000000123" in pending.message
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2", "1.3"]
        assert status.layers[2].intent is LayerIntent.CANCELED

    def test_persisted_skipped_with_unsafe_evidence_never_disappears(self) -> None:
        # Crossing an unsafe evidence family with persisted skipped: the evidence stays
        # visible on a CANCELED layer — persisted-skipped can never bury it.
        store, issues = _cancellation_world(
            persisted=NodeStatus.SKIPPED,
            plan=_plan("103", node_id="1.3", branch="plan-103", parent_sha=_SHA_A),
        )
        status = _reconstruct(store, issues=issues)
        assert "canceled_published_layer" in _codes(status, FindingKind.BLOCKER)
        assert [layer.node_id for layer in status.layers] == ["1.1", "1.2", "1.3"]
        assert status.layers[2].intent is LayerIntent.CANCELED
        assert status.projected_canceled_nodes == ()

    def test_overlapping_findings_all_emit(self) -> None:
        # Persisted done + checkpoints + raw PR + remote branch: every applicable predicate
        # emits — never short-circuited.
        store, issues = _cancellation_world(
            persisted=NodeStatus.DONE,
            plan=_plan(
                "103",
                node_id="1.3",
                branch="plan-103",
                parent_sha=_SHA_A,
                published_sha=_SHA_B,
                pr="#203",
            ),
        )
        git = _FakeGit(branches={"plan-103": _SHA_B})
        status = _reconstruct(store, issues=issues, git=git)
        codes = set(_codes(status, FindingKind.BLOCKER))
        assert {
            "canceled_status_conflict",
            "canceled_published_layer",
            "canceled_remote_work",
        } <= codes

    def test_readiness_is_vetoed_by_the_unsafe_cancellation(self) -> None:
        store, issues = _cancellation_world(persisted=NodeStatus.DONE, pr=None)
        status = _reconstruct(store, issues=issues)
        assert status.build_readiness.ready is False
        assert status.build_readiness.reason is not None
        assert "canceled_status_conflict" in status.build_readiness.reason


class TestCancellationCrashWindows:
    """The §8.47 publication crash windows read through the cancellation proof: header
    metadata may not have landed, so journal + remote evidence must fail contraction closed."""

    def _world(self) -> tuple[_FakeStore, _FakeIssues]:
        return _cancellation_world(plan=_plan("103", node_id="1.3", branch="plan-103"))

    def _fold_with(self, op: journal_mod.OperationState) -> journal_mod.JournalFold:
        return _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            op,
        )

    def test_prepared_before_push_is_unsafe_until_terminal_abandonment(self) -> None:
        store, issues = self._world()
        fold = self._fold_with(_unresolved_op("01JA0000000000000000000103", plan_id="103"))
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(fold=fold))
        assert "canceled_publication_pending" in _codes(status, FindingKind.BLOCKER)
        # ... and after the terminal abandonment (all-before proven) it contracts.
        fold = self._fold_with(
            _concluded_publish_op(
                "01JA0000000000000000000103",
                plan_id="103",
                role=journal_mod.EventRole.ABANDONED,
            )
        )
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(fold=fold))
        assert status.blockers == ()
        assert status.projected_canceled_nodes != ()

    def test_pushed_before_pr_never_contracts(self) -> None:
        # The branch landed on the remote before the PR/header writes crashed.
        store, issues = self._world()
        fold = self._fold_with(_unresolved_op("01JA0000000000000000000103", plan_id="103"))
        git = _FakeGit(branches={"plan-103": _SHA_D})
        status = _reconstruct(store, issues=issues, git=git, persistence=_FakeJournal(fold=fold))
        codes = set(_codes(status, FindingKind.BLOCKER))
        assert {"canceled_publication_pending", "canceled_remote_work"} <= codes

    def test_post_pr_pre_header_never_contracts(self) -> None:
        # PR created, header metadata lost: the branch-owned all-state PR lookup is the proof.
        store, issues = self._world()
        github = _FakeGitHub(branch_prs={"plan-103": BranchPrView(number=203, state="OPEN")})
        git = _FakeGit(branches={"plan-103": _SHA_D})
        status = _reconstruct(store, issues=issues, git=git, github=github)
        assert "canceled_remote_work" in _codes(status, FindingKind.BLOCKER)

    def test_completed_with_lost_header_never_contracts(self) -> None:
        # The journal folds a completed PUBLISH even though the plan header lost its
        # checkpoints: append-only history wins.
        store, issues = self._world()
        fold = self._fold_with(_completed_publish_op("01JA0000000000000000000103", plan_id="103"))
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(fold=fold))
        assert "canceled_published_layer" in _codes(status, FindingKind.BLOCKER)


class TestCancellationLifecycle:
    """Cancellation-derived singleton/all-skipped: projection-only status messages (landing/
    finalization stay out of this surface's claims)."""

    def test_cancellation_derived_singleton_message_is_projection_only(self) -> None:
        node, cancellation = _canceled_node("1.2", pr=None)
        store = _FakeStore()
        store.objectives["10"] = ObjectiveState(
            id="10",
            url="fake://objective/10",
            title="t",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), node),
            native_cancellations=(cancellation,),
        )
        issues = _FakeIssues({"101": _plan("101", node_id="1.1", branch="plan-101")})
        status = _reconstruct(store, issues=issues)
        singleton = next(f for f in status.information if f.code == "dynamic_singleton")
        assert "projects as a single layer (1.1)" in singleton.message
        assert "performs no landing" in singleton.message
        assert "lineage is retained" in singleton.message
        assert status.layers[0].membership is LayerMembership.NOT_APPLICABLE

    def test_all_canceled_projects_all_skipped_without_completion_claims(self) -> None:
        n1, c1 = _canceled_node("1.1", pr=None)
        n2, c2 = _canceled_node("1.2", pr=None)
        store = _FakeStore()
        store.objectives["10"] = ObjectiveState(
            id="10",
            url="fake://objective/10",
            title="t",
            header=_stacked_header(),
            nodes=(n1, n2),
            native_cancellations=(c1, c2),
        )
        status = _reconstruct(store)
        assert status.layers == ()
        skipped = next(f for f in status.information if f.code == "all_skipped")
        assert "performs no objective completion" in skipped.message
        assert len(status.projected_canceled_nodes) == 2


class TestPublishCoverage:
    """§8.54 journal coverage of checkpoint claims: total precedence completed > unresolved >
    abandoned > absent; other operation kinds never substitute."""

    def _published(self, fold: journal_mod.JournalFold):
        store, issues, git, github = _published_two_layer()
        return _reconstruct(
            store, issues=issues, git=git, github=github, persistence=_FakeJournal(fold=fold)
        )

    def test_completed_beats_abandoned_and_unresolved(self) -> None:
        fold = _fold(
            _concluded_publish_op(
                "01JA0000000000000000000001",
                plan_id="101",
                role=journal_mod.EventRole.ABANDONED,
            ),
            _completed_publish_op("01JA0000000000000000000002", plan_id="101"),
            _unresolved_op("01JA0000000000000000000003", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
        )
        status = self._published(fold)
        blocker_codes = _codes(status, FindingKind.BLOCKER)
        assert "missing_publish_outcome" not in blocker_codes
        assert "publish_outcome_pending" not in blocker_codes
        assert "checkpoint_after_abandoned_publish" not in blocker_codes
        # The unresolved attempt still rides active_operation.
        assert "active_operation" in _codes(status, FindingKind.INFO)

    def test_unresolved_beats_abandoned(self) -> None:
        fold = _fold(
            _concluded_publish_op(
                "01JA0000000000000000000001",
                plan_id="101",
                role=journal_mod.EventRole.ABANDONED,
            ),
            _unresolved_op("01JA0000000000000000000003", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
        )
        status = self._published(fold)
        pending = [f for f in status.blockers if f.code == "publish_outcome_pending"]
        assert len(pending) == 1 and pending[0].plan_id == "101"
        assert "01JA0000000000000000000003" in pending[0].message

    def test_abandoned_only_is_checkpoint_after_abandoned_publish(self) -> None:
        fold = _fold(
            _concluded_publish_op(
                "01JA0000000000000000000001",
                plan_id="101",
                role=journal_mod.EventRole.ABANDONED,
            ),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
        )
        status = self._published(fold)
        hits = [f for f in status.blockers if f.code == "checkpoint_after_abandoned_publish"]
        assert len(hits) == 1 and hits[0].plan_id == "101"

    def test_absent_history_is_missing_publish_outcome(self) -> None:
        fold = _fold(_completed_publish_op("01JA0000000000000000000102", plan_id="102"))
        status = self._published(fold)
        hits = [f for f in status.blockers if f.code == "missing_publish_outcome"]
        assert len(hits) == 1 and hits[0].plan_id == "101"

    def test_other_operation_kinds_never_substitute_for_publish(self) -> None:
        sync_op = _unresolved_op(
            "01JA0000000000000000000003",
            kind=journal_mod.OperationKind.SYNC,
            plan_id="101",
        )
        completed_sync = journal_mod.OperationState(
            operation_id=sync_op.operation_id,
            kind=sync_op.kind,
            prepared=sync_op.prepared,
            accepted=None,
            outcome=_concluded_publish_op(
                "01JA0000000000000000000003",
                plan_id="101",
                role=journal_mod.EventRole.COMPLETED,
            ).outcome,
        )
        fold = _fold(
            completed_sync,
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
        )
        status = self._published(fold)
        assert [f.plan_id for f in status.blockers if f.code == "missing_publish_outcome"] == [
            "101"
        ]

    def test_unclassifiable_without_a_fold_emits_no_coverage_guess(self) -> None:
        store, issues, git, github = _published_two_layer()
        status = _reconstruct(
            store, issues=issues, git=git, github=github, persistence=_FakeJournal(corrupt="x")
        )
        codes = _codes(status, FindingKind.BLOCKER)
        assert "journal_corruption" in codes
        assert "missing_publish_outcome" not in codes


class TestCheckpointTopology:
    """§8.54 stored checkpoint-claim topology — distinct from the remote `checkpoint_drift`
    observation and the verified-publication `prefix_gap`."""

    def _world(self, plan102: PlanState) -> tuple[_FakeStore, _FakeIssues]:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102")),
        )
        issues = _FakeIssues(
            {"101": _plan("101", node_id="1.1", branch="plan-101"), "102": plan102}
        )
        return store, issues

    def test_claim_above_a_layer_without_a_full_pair_is_a_checkpoint_prefix_gap(self) -> None:
        # Bottom layer records NO checkpoints; the top layer claims a full pair.
        store, issues = self._world(
            _plan(
                "102",
                node_id="1.2",
                predecessor="101",
                branch="plan-102",
                parent_sha=_SHA_B,
                published_sha=_SHA_C,
                pr="#202",
            )
        )
        fold = _fold(_completed_publish_op("01JA0000000000000000000102", plan_id="102"))
        status = _reconstruct(store, issues=issues, persistence=_FakeJournal(fold=fold))
        gap = [f for f in status.blockers if f.code == "checkpoint_prefix_gap"]
        assert len(gap) == 1 and gap[0].plan_id == "102"
        assert "1.1" in gap[0].message

    def test_half_pair_below_a_full_claim_emits_both_topology_codes(self) -> None:
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101"), _node("1.2", pr="#102")),
        )
        issues = _FakeIssues(
            {
                "101": _plan("101", node_id="1.1", branch="plan-101", published_sha=_SHA_B),
                "102": _plan(
                    "102",
                    node_id="1.2",
                    predecessor="101",
                    branch="plan-102",
                    parent_sha=_SHA_B,
                    published_sha=_SHA_C,
                ),
            }
        )
        status = _reconstruct(store, issues=issues)
        codes = _codes(status, FindingKind.BLOCKER)
        assert "checkpoint_pair_incomplete" in codes
        gap = [f for f in status.blockers if f.code == "checkpoint_prefix_gap"]
        assert len(gap) == 1 and gap[0].plan_id == "102"

    def test_adjacent_full_claims_with_disagreeing_shas_is_parent_mismatch(self) -> None:
        store, issues = self._world(
            _plan(
                "102",
                node_id="1.2",
                predecessor="101",
                branch="plan-102",
                parent_sha=_SHA_D,  # disagrees with plan 101's published head (SHA_B)
                published_sha=_SHA_C,
                pr="#202",
            )
        )
        issues.plans["101"] = _plan(
            "101",
            node_id="1.1",
            branch="plan-101",
            parent_sha=_SHA_A,
            published_sha=_SHA_B,
            pr="#201",
        )
        status = _reconstruct(store, issues=issues)
        mismatch = [f for f in status.blockers if f.code == "checkpoint_parent_mismatch"]
        assert len(mismatch) == 1 and mismatch[0].plan_id == "102"
        assert _SHA_D in mismatch[0].message and _SHA_B in mismatch[0].message
        # Distinct from predecessor_mismatch (the plan-id chain is correct here).
        assert "predecessor_mismatch" not in _codes(status)

    def test_agreeing_full_claims_are_quiet(self) -> None:
        store, issues, git, github = _published_two_layer()
        status = _reconstruct(store, issues=issues, git=git, github=github)
        codes = _codes(status)
        assert "checkpoint_prefix_gap" not in codes
        assert "checkpoint_parent_mismatch" not in codes


# ----------------------------------------------------------------- landed classification (§8.44)


def _merged_pr(
    number: int, *, base: str, head_ref: str, head_sha: str, state: str = "MERGED"
) -> PrFactsView:
    return PrFactsView(
        number=number,
        state=state,
        is_draft=False,
        base_ref=base,
        head_ref=head_ref,
        head_sha=head_sha,
    )


def _completed_land_op(
    operation_id: str,
    *,
    plan_layers: list[tuple[str, str, int, str, str]],
    merged: dict[int, str],
    external_prefix: bool = False,
    corrupt_completed: bool = False,
    created: str = "2026-02-01T00:00:00Z",
) -> journal_mod.OperationState:
    """A completed LAND operation: ``plan_layers`` rows are (node_id, plan_id, pr_number,
    base_sha, head_sha); ``merged`` maps pr_number → merge commit (the completed rows)."""
    rows = [
        {
            "node_id": node_id,
            "plan_id": plan_id,
            "pr_number": pr_number,
            "base_sha": base_sha,
            "head_sha": head_sha,
        }
        for node_id, plan_id, pr_number, base_sha, head_sha in plan_layers
    ]
    record = journal_mod.PreparedRecord(
        operation_id=operation_id,
        operation_kind=journal_mod.OperationKind.LAND,
        delivery_lineage=_LINEAGE,
        objective_id="10",
        run_id="01JC0000000000000000000000",
        created=created,
        affected_plans=tuple(str(row[1]) for row in plan_layers),
        before={
            "mode": "stack_merge_async" if len(rows) > 1 else "singleton_squash",
            "merge_method": "squash",
            "base": "main",
            "top_pr_number": rows[-1]["pr_number"],
            "top_head_sha": rows[-1]["head_sha"],
            "layers": rows,
        },
        after={"merged_pr_numbers": [row["pr_number"] for row in rows], "base": "main"},
    )
    prepared = journal_mod.JournalEvent(
        record=record,
        role=journal_mod.EventRole.PREPARED,
        operation_id=operation_id,
        canonical_payload=journal_mod.canonical_payload(record),
        comment_id="c1",
        created_at=created,
        carrier_objective_id="10",
    )
    observed: dict[str, object] = {
        "layers": [
            {"pr_number": pr_number, "merge_commit_sha": sha} for pr_number, sha in merged.items()
        ],
        "reported_sha": None,
        "final_base_sha": next(reversed(merged.values())) if merged else "x" * 40,
    }
    if external_prefix:
        observed["external_prefix"] = True
        observed["remainder"] = []
    if corrupt_completed:
        observed = {"layers": "junk"}
    outcome_record = journal_mod.OutcomeRecord(
        operation_id=operation_id,
        role=journal_mod.EventRole.COMPLETED,
        created=created,
        observed=observed,
    )
    outcome = journal_mod.JournalEvent(
        record=outcome_record,
        role=journal_mod.EventRole.COMPLETED,
        operation_id=operation_id,
        canonical_payload=journal_mod.canonical_payload(outcome_record),
        comment_id="c2",
        created_at=created,
        carrier_objective_id="10",
    )
    return journal_mod.OperationState(
        operation_id=operation_id,
        kind=journal_mod.OperationKind.LAND,
        prepared=prepared,
        accepted=None,
        outcome=outcome,
    )


_MC1 = "e" * 40  # layer-1 merge commit
_MC2 = "f" * 40  # layer-2 merge commit


class TestLandedClassification:
    """The §8.44 landed-layer classification: the prepared⋈completed coverage join, the
    corroborated suppression set, prefix semantics, and the consumer-facing readiness."""

    def _landed_bottom_world(
        self,
    ) -> tuple[_FakeStore, _FakeIssues, _FakeGit, _FakeGitHub, _FakeJournal]:
        """Layer 1.1 landed (PR 201 MERGED at its checkpoint; branch deleted; plan CLOSED;
        node done); layer 1.2 still published open, retargeted onto main."""
        store = _FakeStore()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(
                _node("1.1", pr="#101", status=NodeStatus.DONE),
                _node("1.2", pr="#102"),
            ),
        )
        issues = _FakeIssues(
            {
                "101": _plan(
                    "101",
                    node_id="1.1",
                    parent_sha=_SHA_A,
                    published_sha=_SHA_B,
                    branch="plan-101",
                    pr="#201",
                    state="CLOSED",
                ),
                "102": _plan(
                    "102",
                    node_id="1.2",
                    predecessor="101",
                    parent_sha=_SHA_B,
                    published_sha=_SHA_C,
                    branch="plan-102",
                    pr="#202",
                ),
            }
        )
        git = _FakeGit(
            branches={"plan-102": _SHA_C},  # plan-101 deleted at merge
            ancestry={(_SHA_B, _SHA_C): True},
        )
        github = _FakeGitHub(
            prs={
                201: _merged_pr(201, base="main", head_ref="plan-101", head_sha=_SHA_B),
                # GitHub retargeted the dependent PR onto the base at merge.
                202: _open_pr(202, base="main", head_ref="plan-102", head_sha=_SHA_C),
            },
        )
        persistence = _FakeJournal(
            fold=_fold(
                _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
                _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
                _completed_land_op(
                    "01JA0000000000000000000201",
                    plan_layers=[("1.1", "101", 201, _SHA_A, _SHA_B)],
                    merged={201: _MC1},
                ),
            )
        )
        return store, issues, git, github, persistence

    def test_covered_corroborated_layer_lands_with_the_suppression_set(self) -> None:
        store, issues, git, github, persistence = self._landed_bottom_world()
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        landed, published = status.layers
        assert landed.publication is LayerPublication.LANDED
        assert landed.pr is LayerPr.MERGED
        assert landed.membership is LayerMembership.NOT_APPLICABLE
        assert published.publication is LayerPublication.PUBLISHED
        # The suppression set: no deleted-branch checkpoint_drift, no retarget pr_wrong_base.
        codes = _codes(status, FindingKind.BLOCKER)
        assert "checkpoint_drift" not in codes
        assert "pr_wrong_base" not in codes
        assert status.blockers == ()
        # Prefix semantics + the landed-aware expected base for the first non-landed layer.
        assert status.landed_prefix_len == 1
        assert status.published_prefix_len == 2
        assert published.expected_pr_base == "main"
        # The next-build selection skips the landed layer.
        assert status.build_readiness.next_node_id is None

    def test_membership_desired_composition_is_the_non_landed_open_prs(self) -> None:
        # Three layers: 1.1 landed; 1.2/1.3 published open — the membership probe's desired
        # composition is exactly the non-landed PRs.
        store, issues, git, github, persistence = self._landed_bottom_world()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(
                _node("1.1", pr="#101", status=NodeStatus.DONE),
                _node("1.2", pr="#102"),
                _node("1.3", pr="#103"),
            ),
        )
        issues.plans["103"] = _plan(
            "103",
            node_id="1.3",
            predecessor="102",
            parent_sha=_SHA_C,
            published_sha=_SHA_D,
            branch="plan-103",
            pr="#203",
        )
        git.branches["plan-103"] = _SHA_D
        git.ancestry[(_SHA_C, _SHA_D)] = True
        github.prs[203] = _open_pr(203, base="plan-102", head_ref="plan-103", head_sha=_SHA_D)
        github.stack = StackView(
            available=True,
            stacked=True,
            entries=(StackEntryView(1, 202), StackEntryView(2, 203)),
        )
        persistence.fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _completed_publish_op("01JA0000000000000000000103", plan_id="103"),
            _completed_land_op(
                "01JA0000000000000000000201",
                plan_layers=[("1.1", "101", 201, _SHA_A, _SHA_B)],
                merged={201: _MC1},
            ),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        assert github.stack_queries == [202]  # probed from the first NON-landed participant
        assert [layer.publication for layer in status.layers] == [
            LayerPublication.LANDED,
            LayerPublication.PUBLISHED,
            LayerPublication.PUBLISHED,
        ]
        assert status.blockers == ()

    def test_pr_number_only_near_miss_never_classifies_landed(self) -> None:
        # The coverage join requires node/plan identity AND the recorded head == the
        # checkpoint — a matching PR number alone (a replanned layer) keeps drift findings.
        store, issues, git, github, persistence = self._landed_bottom_world()
        persistence.fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _completed_land_op(
                "01JA0000000000000000000201",
                plan_layers=[("1.1", "999", 201, _SHA_A, _SHA_B)],  # foreign plan id
                merged={201: _MC1},
            ),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        landed = status.layers[0]
        assert landed.publication is not LayerPublication.LANDED
        codes = _codes(status, FindingKind.BLOCKER)
        assert "checkpoint_drift" in codes  # the deleted branch stays drift

    def test_recorded_head_must_equal_the_checkpoint(self) -> None:
        store, issues, git, github, persistence = self._landed_bottom_world()
        persistence.fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _completed_land_op(
                "01JA0000000000000000000201",
                plan_layers=[("1.1", "101", 201, _SHA_A, _SHA_D)],  # stale recorded head
                merged={201: _MC1},
            ),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        assert status.layers[0].publication is not LayerPublication.LANDED
        assert status.landed_prefix_len == 0

    def test_merged_without_coverage_keeps_todays_drift(self) -> None:
        store, issues, git, github, persistence = self._landed_bottom_world()
        persistence.fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        assert status.layers[0].publication is LayerPublication.PUBLICATION_DRIFT
        codes = _codes(status, FindingKind.BLOCKER)
        assert "checkpoint_drift" in codes
        assert status.landed_prefix_len == 0

    def test_failed_live_corroboration_never_lands(self) -> None:
        # Coverage exists but the PR re-observes OPEN (the interrupted-landing crash window
        # cannot happen with a completed record, but external drift can) — fail closed.
        store, issues, git, github, persistence = self._landed_bottom_world()
        github.prs[201] = _open_pr(201, base="main", head_ref="plan-101", head_sha=_SHA_B)
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        assert status.layers[0].publication is not LayerPublication.LANDED

    def test_landed_above_non_landed_is_landed_prefix_gap(self) -> None:
        # Layer 1.2 landed while 1.1 is still open/published — the gap blocker (plain,
        # deliberately not structural), and landed_prefix_len stays 0.
        store, issues, git, github, persistence = self._landed_bottom_world()
        github.prs[201] = _open_pr(201, base="main", head_ref="plan-101", head_sha=_SHA_B)
        github.prs[202] = _merged_pr(202, base="main", head_ref="plan-102", head_sha=_SHA_C)
        git.branches["plan-101"] = _SHA_B
        git.branches.pop("plan-102", None)
        persistence.fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _completed_land_op(
                "01JA0000000000000000000201",
                plan_layers=[("1.2", "102", 202, _SHA_B, _SHA_C)],
                merged={202: _MC2},
            ),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        assert status.layers[1].publication is LayerPublication.LANDED
        assert status.landed_prefix_len == 0
        gap = [f for f in status.blockers if f.code == "landed_prefix_gap"]
        assert len(gap) == 1 and gap[0].node_id == "1.2"
        from perk.delivery.train import STRUCTURAL_BLOCKER_CODES

        assert "landed_prefix_gap" not in STRUCTURAL_BLOCKER_CODES

    def test_landed_unfinalized_info_fires_on_open_plan_or_non_terminal_node(self) -> None:
        store, issues, git, github, persistence = self._landed_bottom_world()
        issues.plans["101"] = _plan(
            "101",
            node_id="1.1",
            parent_sha=_SHA_A,
            published_sha=_SHA_B,
            branch="plan-101",
            pr="#201",
            state="OPEN",  # plan not closed → finalization MERGED, not FINALIZED
        )
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        rows = [f for f in status.information if f.code == "landed_unfinalized"]
        assert len(rows) == 1 and rows[0].node_id == "1.1"
        assert "perk objective stack recover" in rows[0].message
        assert status.layers[0].publication is LayerPublication.LANDED  # INFO, never a veto

    def test_fully_finalized_landed_layer_is_quiet(self) -> None:
        store, issues, git, github, persistence = self._landed_bottom_world()
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        assert "landed_unfinalized" not in _codes(status)

    def test_undecodable_land_payload_is_journal_corruption(self) -> None:
        store, issues, git, github, persistence = self._landed_bottom_world()
        persistence.fold = _fold(
            _completed_publish_op("01JA0000000000000000000101", plan_id="101"),
            _completed_publish_op("01JA0000000000000000000102", plan_id="102"),
            _completed_land_op(
                "01JA0000000000000000000201",
                plan_layers=[("1.1", "101", 201, _SHA_A, _SHA_B)],
                merged={201: _MC1},
                corrupt_completed=True,
            ),
        )
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        corruption = [f for f in status.blockers if f.code == "journal_corruption"]
        assert len(corruption) == 1 and "undecodable" in corruption[0].message
        assert status.layers[0].publication is not LayerPublication.LANDED  # fail closed

    def test_build_readiness_skips_landed_layers(self) -> None:
        # 1.1 landed, 1.2 unplanned — the next-build selection lands on 1.2, never 1.1.
        store, issues, git, github, persistence = self._landed_bottom_world()
        store.add(
            "10",
            header=_stacked_header(),
            nodes=(_node("1.1", pr="#101", status=NodeStatus.DONE), _node("1.2")),
        )
        del issues.plans["102"]
        git.branches.pop("plan-102", None)
        status = _reconstruct(store, issues=issues, git=git, github=github, persistence=persistence)
        assert status.layers[0].publication is LayerPublication.LANDED
        assert status.build_readiness.next_node_id == "1.2"
