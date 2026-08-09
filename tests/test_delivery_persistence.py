"""Tests for the train-persistence adapter (``perk/delivery/persistence.py``).

In-memory Protocol fakes: a ``_FakeStore`` + ``_FakeIssues`` pair holding per-carrier comment
lists. The fake ``add_issue_comment`` is programmable per call — succeed, raise AFTER recording
the comment (ambiguous-landed), raise WITHOUT recording (ambiguous-lost), or record a TAMPERED
payload then raise (the read-back conflict) — so the rescan-one-retry ambiguity policy and the
read-back discipline are pinned end to end.
"""

import itertools
from dataclasses import dataclass, field
from typing import cast

import pytest

from perk.backends import engagement
from perk.backends.issue_backend import (
    CommentResult,
    IssueBackend,
    IssueBackendError,
    PlanHeaderUpdate,
)
from perk.backends.objective_store import ObjectiveHeaderUpdate, ObjectiveState, ObjectiveStore
from perk.delivery import journal
from perk.delivery.persistence import (
    AppendResult,
    JournalAppendAmbiguous,
    TrainPersistence,
    TrainPersistenceError,
    UnresolvedOperationError,
)

_LINEAGE = "01JB0000000000000000000000"
_OP_1 = "01JA0000000000000000000000"
_OP_2 = "01JA0000000000000000000001"

_PERK_AUTHOR = engagement.EngagementAuthor(kind="perk", display_name=None, id=None)


@dataclass
class _FakeObjective:
    header: dict[str, object]
    carrier: str  # the carrier issue-tier id


class _FakeStore:
    """A minimal in-memory objective store: header reads, carrier resolution, header writes."""

    backend_id = "fake"

    def __init__(self) -> None:
        self.objectives: dict[str, _FakeObjective] = {}
        self.header_writes: list[tuple[str, dict[str, object]]] = []

    def add(
        self,
        objective_id: str,
        *,
        lineage: str | None = _LINEAGE,
        supersedes: str | None = None,
        carrier: str | None = None,
    ) -> None:
        header: dict[str, object] = {}
        if lineage is not None:
            header["delivery_lineage"] = lineage
        if supersedes is not None:
            header["supersedes"] = supersedes
        self.objectives[objective_id] = _FakeObjective(
            header=header, carrier=carrier if carrier is not None else objective_id
        )

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        obj = self.objectives.get(objective_id)
        if obj is None:
            return None
        return ObjectiveState(
            id=objective_id,
            url=f"fake://objective/{objective_id}",
            title="t",
            header=dict(obj.header),
            nodes=(),
        )

    def journal_carrier_id(self, *, objective_id: str) -> str | None:
        obj = self.objectives.get(objective_id)
        return None if obj is None else obj.carrier

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> ObjectiveHeaderUpdate:
        self.header_writes.append((objective_id, dict(fields)))
        return ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=dry_run)


@dataclass
class _FakeIssues:
    """A minimal in-memory issue backend: per-carrier comment lists + a programmable POST plan.

    ``post_plan`` entries consumed per ``add_issue_comment`` call (default ``"ok"``):
    ``"ok"`` succeed; ``"raise_after"`` record then raise (ambiguous-landed); ``"raise_lost"``
    raise without recording (ambiguous-lost); ``"tamper"`` record a same-key different-payload
    event then raise (the read-back conflict).
    """

    backend_id = "fake"

    comments: dict[str, list[engagement.EngagementComment]] = field(default_factory=dict)
    post_plan: list[str] = field(default_factory=list)
    post_calls: list[tuple[str, str]] = field(default_factory=list)
    plan_header_writes: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    _seq: "itertools.count[int]" = field(default_factory=lambda: itertools.count(1))

    def seed(self, issue_id: str, body: str) -> None:
        """Seed a pre-existing comment on a carrier (bypassing the POST plan)."""
        self._record(issue_id, body)

    def _record(self, issue_id: str, body: str) -> None:
        n = next(self._seq)
        self.comments.setdefault(issue_id, []).append(
            engagement.EngagementComment(
                id=f"c{n}",
                body=body,
                created_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}Z",
                edited_at=None,
                author=_PERK_AUTHOR,
            )
        )

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> CommentResult:
        self.post_calls.append((issue_id, body))
        behavior = self.post_plan.pop(0) if self.post_plan else "ok"
        if behavior == "raise_lost":
            raise IssueBackendError("boom (write lost)")
        if behavior == "tamper":
            self._record(issue_id, body.replace("created: ", "created: 9999-"))
            raise IssueBackendError("boom (write tampered)")
        self._record(issue_id, body)
        if behavior == "raise_after":
            raise IssueBackendError("boom (write landed)")
        return CommentResult(posted=True)

    def read_comments(self, *, issue_id: str) -> tuple[engagement.EngagementComment, ...]:
        return tuple(self.comments.get(issue_id, ()))

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> PlanHeaderUpdate:
        self.plan_header_writes.append((issue_id, dict(fields)))
        return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=dry_run)


def _make() -> tuple[TrainPersistence, _FakeStore, _FakeIssues]:
    store = _FakeStore()
    issues = _FakeIssues()
    persistence = TrainPersistence(cast("ObjectiveStore", store), cast("IssueBackend", issues))
    return persistence, store, issues


def _prepared(
    *,
    operation_id: str = _OP_1,
    kind: journal.OperationKind = journal.OperationKind.PUBLISH,
    lineage: str = _LINEAGE,
    objective_id: str = "100",
) -> journal.PreparedRecord:
    return journal.PreparedRecord(
        operation_id=operation_id,
        operation_kind=kind,
        delivery_lineage=lineage,
        objective_id=objective_id,
        run_id="01JC0000000000000000000000",
        created="2026-01-01T00:00:00Z",
        affected_plans=("201",),
        before={"sha": "a" * 40},
        after={"sha": "b" * 40},
    )


def _outcome(
    *,
    operation_id: str = _OP_1,
    role: journal.EventRole = journal.EventRole.COMPLETED,
) -> journal.OutcomeRecord:
    return journal.OutcomeRecord(
        operation_id=operation_id,
        role=role,
        created="2026-01-02T00:00:00Z",
        observed={"verified": True},
    )


class TestReadJournal:
    def test_missing_objective_is_a_caller_bug(self) -> None:
        persistence, _, _ = _make()
        with pytest.raises(TrainPersistenceError, match="not found"):
            persistence.read_journal("100")

    def test_empty_carrier_folds_empty(self) -> None:
        persistence, store, _ = _make()
        store.add("100")
        fold = persistence.read_journal("100")
        assert fold.events == ()
        assert fold.delivery_lineage == _LINEAGE

    def test_unrelated_comments_are_ignored(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.seed("100", "a human comment")
        issues.seed("100", journal.render_event(_prepared()))
        fold = persistence.read_journal("100")
        assert list(fold.operations) == [_OP_1]

    def test_succession_folding_spans_carriers(self) -> None:
        # B supersedes A: events split across both carriers fold into ONE journal.
        persistence, store, issues = _make()
        store.add("A")
        store.add("B", supersedes="A")
        issues.seed("A", journal.render_event(_prepared(objective_id="A")))
        issues.seed("A", journal.render_event(_outcome()))
        issues.seed("B", journal.render_event(_prepared(operation_id=_OP_2, objective_id="B")))
        fold = persistence.read_journal("B")
        assert set(fold.operations) == {_OP_1, _OP_2}
        assert fold.operations[_OP_1].resolved is True
        assert fold.operations[_OP_1].prepared.carrier_objective_id == "A"
        assert fold.operations[_OP_2].prepared.carrier_objective_id == "B"
        assert [op.operation_id for op in fold.unresolved] == [_OP_2]

    def test_supersession_cycle_is_corruption(self) -> None:
        persistence, store, _ = _make()
        store.add("A", supersedes="B")
        store.add("B", supersedes="A")
        with pytest.raises(journal.JournalCorruptionError, match="cycle"):
            persistence.read_journal("B")

    def test_supersession_depth_cap_is_corruption(self) -> None:
        persistence, store, _ = _make()
        for i in range(60):
            store.add(f"o{i}", supersedes=f"o{i + 1}" if i < 59 else None)
        with pytest.raises(journal.JournalCorruptionError, match="depth cap"):
            persistence.read_journal("o0")

    def test_missing_predecessor_is_unreadable(self) -> None:
        persistence, store, _ = _make()
        store.add("B", supersedes="A")
        with pytest.raises(TrainPersistenceError, match="does not exist"):
            persistence.read_journal("B")

    def test_foreign_lineage_event_never_folds(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.seed("100", journal.render_event(_prepared(lineage="01JZ0000000000000000000000")))
        with pytest.raises(journal.JournalCorruptionError, match="foreign delivery_lineage"):
            persistence.read_journal("100")


class TestAppendPrepared:
    def test_happy_path_reads_back(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        result = persistence.append_prepared("100", _prepared())
        assert result == AppendResult(
            operation_id=_OP_1, role=journal.EventRole.PREPARED, existed=False
        )
        [(carrier, body)] = issues.post_calls
        assert carrier == "100"
        assert f"<!-- perk:stack-operation-event:{_OP_1}:prepared -->" in body
        assert len(issues.comments["100"]) == 1

    def test_idempotent_re_append(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared())
        result = persistence.append_prepared("100", _prepared())
        assert result.existed is True
        assert len(issues.post_calls) == 1  # the re-append never POSTs
        assert len(issues.comments["100"]) == 1

    def test_conflicting_re_append_is_corruption(self) -> None:
        persistence, store, _ = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared())
        conflicting = journal.PreparedRecord(
            operation_id=_OP_1,
            operation_kind=journal.OperationKind.PUBLISH,
            delivery_lineage=_LINEAGE,
            objective_id="100",
            run_id="01JC0000000000000000000000",
            created="2027-06-06T00:00:00Z",
            affected_plans=("201",),
            before={},
            after={},
        )
        with pytest.raises(journal.JournalCorruptionError, match="differing"):
            persistence.append_prepared("100", conflicting)

    def test_ambiguous_landed_recovers_without_duplicate(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["raise_after"]
        result = persistence.append_prepared("100", _prepared())
        assert result.existed is False
        assert len(issues.post_calls) == 1  # the rescan proved it landed — no retry
        assert len(issues.comments["100"]) == 1

    def test_ambiguous_lost_retries_once_and_lands(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["raise_lost", "ok"]
        result = persistence.append_prepared("100", _prepared())
        assert result.existed is False
        assert len(issues.post_calls) == 2
        assert len(issues.comments["100"]) == 1

    def test_ambiguous_lost_twice_is_typed_and_bounded(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["raise_lost", "raise_lost"]
        with pytest.raises(JournalAppendAmbiguous):
            persistence.append_prepared("100", _prepared())
        assert len(issues.post_calls) == 2  # exactly two POST attempts, never more
        assert issues.comments.get("100", []) == []

    def test_read_back_conflict_is_corruption(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["tamper"]
        with pytest.raises(journal.JournalCorruptionError, match="DIFFERENT payload"):
            persistence.append_prepared("100", _prepared())

    def test_partial_write_surfaces_as_unresolved(self) -> None:
        # The crash-between-append-and-effect story: a prepared with no outcome is unresolved
        # on the next read.
        persistence, store, _ = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared())
        fold = persistence.read_journal("100")
        assert [op.operation_id for op in fold.unresolved] == [_OP_1]

    def test_one_unresolved_gate(self) -> None:
        persistence, store, _ = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared())
        with pytest.raises(UnresolvedOperationError, match=_OP_1):
            persistence.append_prepared("100", _prepared(operation_id=_OP_2))
        persistence.append_outcome("100", _outcome())
        result = persistence.append_prepared("100", _prepared(operation_id=_OP_2))
        assert result.existed is False

    def test_lineage_mismatch_fails_closed(self) -> None:
        persistence, store, issues = _make()
        store.add("100", lineage="01JZ0000000000000000000000")
        with pytest.raises(TrainPersistenceError, match="refusing to append"):
            persistence.append_prepared("100", _prepared())
        assert issues.post_calls == []

    def test_oversize_record_is_refused_before_post(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        record = journal.PreparedRecord(
            operation_id=_OP_1,
            operation_kind=journal.OperationKind.PUBLISH,
            delivery_lineage=_LINEAGE,
            objective_id="100",
            run_id="r",
            created="t",
            affected_plans=(),
            before={"blob": "x" * (journal.JOURNAL_EVENT_MAX_CHARS + 1)},
            after={},
        )
        with pytest.raises(journal.JournalRecordTooLarge):
            persistence.append_prepared("100", record)
        assert issues.post_calls == []


class TestAppendOutcome:
    def test_orphan_outcome_is_corruption(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        with pytest.raises(journal.JournalCorruptionError, match="out-of-band deletion"):
            persistence.append_outcome("100", _outcome())
        assert issues.post_calls == []

    def test_outcome_routes_to_the_prepared_carrier(self) -> None:
        # The transfer exception: op prepared on predecessor A stays on A's carrier even when
        # the outcome is appended against the ACTIVE objective B.
        persistence, store, issues = _make()
        store.add("A")
        store.add("B", supersedes="A")
        issues.seed("A", journal.render_event(_prepared(objective_id="A")))
        result = persistence.append_outcome("B", _outcome())
        assert result.existed is False
        [(carrier, _)] = issues.post_calls
        assert carrier == "A"
        assert len(issues.comments["A"]) == 2
        assert issues.comments.get("B", []) == []

    def test_idempotent_outcome_re_append(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared())
        persistence.append_outcome("100", _outcome())
        result = persistence.append_outcome("100", _outcome())
        assert result.existed is True
        assert len(issues.post_calls) == 2

    def test_differing_terminal_outcome_is_corruption(self) -> None:
        persistence, store, _ = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared())
        persistence.append_outcome("100", _outcome(role=journal.EventRole.COMPLETED))
        with pytest.raises(journal.JournalCorruptionError, match="already terminal"):
            persistence.append_outcome("100", _outcome(role=journal.EventRole.ABANDONED))

    def test_accepted_on_non_land_refused_before_write(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared(kind=journal.OperationKind.PUBLISH))
        posts_before = len(issues.post_calls)
        with pytest.raises(TrainPersistenceError, match="gated to land"):
            persistence.append_outcome("100", _outcome(role=journal.EventRole.ACCEPTED))
        assert len(issues.post_calls) == posts_before

    def test_accepted_then_completed_on_land(self) -> None:
        persistence, store, _ = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared(kind=journal.OperationKind.LAND))
        persistence.append_outcome("100", _outcome(role=journal.EventRole.ACCEPTED))
        persistence.append_outcome("100", _outcome(role=journal.EventRole.COMPLETED))
        fold = persistence.read_journal("100")
        assert fold.operations[_OP_1].resolved is True
        assert fold.unresolved == ()


class TestTypedWriters:
    def test_write_checkpoints_is_one_paired_write(self) -> None:
        persistence, _, issues = _make()
        persistence.write_checkpoints(
            "201", parent_checkpoint_sha="a" * 40, published_head_sha="b" * 40
        )
        assert issues.plan_header_writes == [
            ("201", {"parent_checkpoint_sha": "a" * 40, "published_head_sha": "b" * 40})
        ]

    def test_transfer_plan_ownership_is_one_write(self) -> None:
        persistence, _, issues = _make()
        persistence.transfer_plan_ownership("201", objective_id="300", objective_node_id="1.2")
        assert issues.plan_header_writes == [
            ("201", {"objective_id": "300", "objective_node_id": "1.2"})
        ]

    def test_stamp_layer_identity_allows_null_predecessor(self) -> None:
        persistence, _, issues = _make()
        persistence.stamp_layer_identity("201", delivery_lineage=_LINEAGE, predecessor_plan_id=None)
        assert issues.plan_header_writes == [
            ("201", {"delivery_lineage": _LINEAGE, "predecessor_plan_id": None})
        ]

    def test_write_delivery_lineage_hits_objective_header(self) -> None:
        persistence, store, _ = _make()
        persistence.write_delivery_lineage("100", _LINEAGE)
        assert store.header_writes == [("100", {"delivery_lineage": _LINEAGE})]
