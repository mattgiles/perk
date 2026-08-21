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
    StampAppendResult,
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
        # The store boundary accepts its own supersession writer's canonical `#<n>` rendering
        # (mirroring `GitHubObjectiveStore._number`'s one-leading-`#` strip).
        objective_id = objective_id.removeprefix("#")
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
        obj = self.objectives.get(objective_id.removeprefix("#"))
        return None if obj is None else obj.carrier

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> ObjectiveHeaderUpdate:
        self.header_writes.append((objective_id, dict(fields)))
        return ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=dry_run)


@dataclass
class _FakeIssues:
    """A minimal in-memory issue backend: per-carrier comment lists + programmable POST/read
    plans.

    ``post_plan`` entries consumed per ``add_issue_comment`` call (default ``"ok"``):
    ``"ok"`` succeed; ``"raise_after"`` record then raise (ambiguous-landed); ``"raise_lost"``
    raise without recording (ambiguous-lost); ``"tamper"`` record a same-key different-payload
    event then raise (the read-back conflict); ``"tamper_stamp"`` the ready-stamp mirror — the
    timestamp-free stamp payload has no ``created: `` line, so the mutation rides
    ``delivery_lineage: `` instead (parses fine, same key, differing canonical payload);
    ``"race_stamp"`` record the body AND a same-key different-payload stamp, then succeed (the
    stamp full-scan race); ``"stamp_junk"`` record the body AND a malformed ready-stamp
    comment, then succeed (concurrent cross-grammar corruption during the rescan).
    ``read_plan`` entries consumed per
    ``read_comments`` call (default ``"ok"``): ``"ok"`` honest read; ``"raise"`` an infra
    failure; ``"empty"`` a stale view that hides every comment (read-back visibility lag).
    ``ops`` records the interleaved ``("post"|"read", issue_id)`` sequence — the convergence-
    ordering pin.
    """

    backend_id = "fake"

    comments: dict[str, list[engagement.EngagementComment]] = field(default_factory=dict)
    post_plan: list[str] = field(default_factory=list)
    read_plan: list[str] = field(default_factory=list)
    post_calls: list[tuple[str, str]] = field(default_factory=list)
    ops: list[tuple[str, str]] = field(default_factory=list)
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
        self.ops.append(("post", issue_id))
        behavior = self.post_plan.pop(0) if self.post_plan else "ok"
        if behavior == "raise_lost":
            raise IssueBackendError("boom (write lost)")
        if behavior == "tamper":
            self._record(issue_id, body.replace("created: ", "created: 9999-"))
            raise IssueBackendError("boom (write tampered)")
        if behavior == "tamper_stamp":
            self._record(issue_id, body.replace("delivery_lineage: ", "delivery_lineage: 9"))
            raise IssueBackendError("boom (write tampered)")
        if behavior == "stamp_junk":
            self._record(issue_id, body)
            self._record(issue_id, "<!-- perk:stack-ready-stamp:junk -->\n\nnot a fence")
            return CommentResult(posted=True)
        self._record(issue_id, body)
        if behavior == "race":
            # A concurrent writer's conflicting duplicate lands right AFTER ours — the rescan
            # sees the byte-identical match first, the conflict second (the full-scan pin).
            self._record(issue_id, body.replace("created: ", "created: 9999-"))
            return CommentResult(posted=True)
        if behavior == "race_stamp":
            # The ready-stamp mirror of "race": same key, differing payload, AFTER the match.
            self._record(issue_id, body.replace("delivery_lineage: ", "delivery_lineage: 9"))
            return CommentResult(posted=True)
        if behavior == "raise_after":
            raise IssueBackendError("boom (write landed)")
        return CommentResult(posted=True)

    def read_comments(self, *, issue_id: str) -> tuple[engagement.EngagementComment, ...]:
        self.ops.append(("read", issue_id))
        behavior = self.read_plan.pop(0) if self.read_plan else "ok"
        if behavior == "raise":
            raise IssueBackendError("boom (read failed)")
        if behavior == "empty":
            return ()
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


_HEAD = "a" * 40


def _stamp(
    *,
    objective_id: str = "100",
    lineage: str = _LINEAGE,
    plan_id: str = "201",
    node_id: str = "1.1",
    head_sha: str = _HEAD,
) -> journal.ReadyStampRecord:
    return journal.ReadyStampRecord(
        objective_id=objective_id,
        delivery_lineage=lineage,
        plan_id=plan_id,
        node_id=node_id,
        head_sha=head_sha,
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
        # B supersedes A: events split across both carriers fold into ONE journal. Distinct
        # carrier ids pin that reads resolve each member's issue-tier carrier.
        persistence, store, issues = _make()
        store.add("A", carrier="SENT-A")
        store.add("B", supersedes="A", carrier="SENT-B")
        issues.seed("SENT-A", journal.render_event(_prepared(objective_id="A")))
        issues.seed("SENT-A", journal.render_event(_outcome()))
        issues.seed("SENT-B", journal.render_event(_prepared(operation_id=_OP_2, objective_id="B")))
        fold = persistence.read_journal("B")
        assert set(fold.operations) == {_OP_1, _OP_2}
        assert fold.operations[_OP_1].resolved is True
        assert fold.operations[_OP_1].prepared.carrier_objective_id == "A"
        assert fold.operations[_OP_2].prepared.carrier_objective_id == "B"
        assert [op.operation_id for op in fold.unresolved] == [_OP_2]

    def test_succession_folding_accepts_canonical_hash_ids(self) -> None:
        # Regression: GitHub's supersession writer stamps `supersedes: "#<n>"` (the canonical
        # rendering); the succession walk feeds that stored value straight to `get_objective`,
        # so a GitHub-shaped chain must fold without the walker normalizing anything.
        persistence, store, issues = _make()
        store.add("41", carrier="SENT-41")
        store.add("42", supersedes="#41", carrier="SENT-42")
        issues.seed("SENT-41", journal.render_event(_prepared(objective_id="41")))
        issues.seed("SENT-41", journal.render_event(_outcome()))
        fold = persistence.read_journal("42")
        assert _OP_1 in fold.operations
        assert fold.operations[_OP_1].resolved is True

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

    def test_read_back_scans_past_the_first_match(self) -> None:
        # A conflicting duplicate LATER in the same rescan (after the byte-identical match)
        # must still be corruption — the read-back is a complete scan, never first-match-return.
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["race"]
        with pytest.raises(journal.JournalCorruptionError, match="DIFFERENT payload"):
            persistence.append_prepared("100", _prepared())

    def test_rescan_failure_is_ambiguous_without_retry(self) -> None:
        # A failed rescan proves nothing: typed JournalAppendAmbiguous, and NO retry POST —
        # only a rescan that proved absence earns the retry.
        persistence, store, issues = _make()
        store.add("100")
        issues.read_plan = ["ok", "raise"]  # the pre-append fold read, then the failing rescan
        with pytest.raises(JournalAppendAmbiguous, match="rescan failed"):
            persistence.append_prepared("100", _prepared())
        assert len(issues.post_calls) == 1

    def test_concurrent_corrupt_stamp_fails_the_operation_rescan_closed(self) -> None:
        # The cross-grammar rescan pin: a malformed ready-stamp comment arriving DURING the
        # operation POST (after the clean pre-append fold) fails the read-back closed — the
        # guarded remote mutation never proceeds past corruption in EITHER journal grammar.
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["stamp_junk"]
        with pytest.raises(journal.JournalCorruptionError, match="ready-stamp"):
            persistence.append_prepared("100", _prepared())

    def test_invisible_read_back_retries_once_then_converges(self) -> None:
        # A successful POST whose read-back cannot see the event is ambiguous → the same
        # one-retry policy; the duplicate byte-identical comment dedupes in the fold.
        persistence, store, issues = _make()
        store.add("100")
        issues.read_plan = ["ok", "empty", "ok"]
        result = persistence.append_prepared("100", _prepared())
        assert result.existed is False
        assert len(issues.post_calls) == 2
        # convergence ordering: read convergence follows every POST before any retry
        assert issues.ops == [
            ("read", "100"),  # the pre-append fold
            ("post", "100"),
            ("read", "100"),  # the stale rescan (proved absent)
            ("post", "100"),  # the one bounded retry
            ("read", "100"),  # the converging rescan
        ]
        assert len(issues.comments["100"]) == 2  # the duplicate is byte-identical
        fold = persistence.read_journal("100")
        assert len(fold.events) == 1  # …and dedupes in the fold

    def test_invisible_read_back_twice_is_typed_and_bounded(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.read_plan = ["ok", "empty", "empty"]
        with pytest.raises(JournalAppendAmbiguous):
            persistence.append_prepared("100", _prepared())
        assert len(issues.post_calls) == 2  # exactly two POST attempts, never more

    def test_objective_identity_mismatch_fails_closed(self) -> None:
        # A lineage is shared across supersession — the record's objective-at-preparation claim
        # must name the objective it is appended to.
        persistence, store, issues = _make()
        store.add("100")
        with pytest.raises(TrainPersistenceError, match="claims objective"):
            persistence.append_prepared("100", _prepared(objective_id="999"))
        assert issues.post_calls == []

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
        # the outcome is appended against the ACTIVE objective B. The carriers are distinct
        # from the objective ids (the Linear-project shape), so this pins that routing resolves
        # the ISSUE-TIER carrier — posting to the objective id would fail.
        persistence, store, issues = _make()
        store.add("A", carrier="SENT-A")
        store.add("B", supersedes="A", carrier="SENT-B")
        issues.seed("SENT-A", journal.render_event(_prepared(objective_id="A")))
        result = persistence.append_outcome("B", _outcome())
        assert result.existed is False
        [(carrier, _)] = issues.post_calls
        assert carrier == "SENT-A"
        assert len(issues.comments["SENT-A"]) == 2
        assert issues.comments.get("SENT-B", []) == []
        assert issues.comments.get("A", []) == []  # never the objective id itself

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


class TestAppendReadyStamp:
    def test_fresh_append_reads_back(self) -> None:
        persistence, store, issues = _make()
        store.add("100", carrier="SENT-100")
        result = persistence.append_ready_stamp("100", _stamp())
        assert result == StampAppendResult(key=f"100:201:1.1:{_HEAD}", existed=False)
        [(carrier, body)] = issues.post_calls
        assert carrier == "SENT-100"  # the ACTIVE objective's issue-tier carrier
        assert body == journal.render_stamp_event(_stamp())
        assert len(issues.comments["SENT-100"]) == 1

    def test_idempotent_re_append_at_the_same_head(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        persistence.append_ready_stamp("100", _stamp())
        result = persistence.append_ready_stamp("100", _stamp())
        assert result.existed is True
        assert len(issues.post_calls) == 1  # the re-append never POSTs

    def test_ambiguous_landed_converges_without_duplicate(self) -> None:
        # The representative convergence case proving the _stamp_landed wiring (the full
        # four-arm ambiguity matrix stays covered once by TestAppendPrepared).
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["raise_after"]
        result = persistence.append_ready_stamp("100", _stamp())
        assert result.existed is False
        assert len(issues.post_calls) == 1  # the rescan proved it landed — no retry

    def test_ambiguous_message_names_the_ready_stamp_key(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.read_plan = ["ok", "empty", "empty"]  # the fold read, then two stale rescans
        with pytest.raises(
            JournalAppendAmbiguous, match=f"append of ready-stamp 100:201:1.1:{_HEAD}"
        ):
            persistence.append_ready_stamp("100", _stamp())
        assert len(issues.post_calls) == 2  # exactly two POST attempts, never more

    def test_rescan_failure_is_ambiguous_without_retry(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.read_plan = ["ok", "raise"]
        with pytest.raises(JournalAppendAmbiguous, match=r"append of ready-stamp .* rescan"):
            persistence.append_ready_stamp("100", _stamp())
        assert len(issues.post_calls) == 1

    def test_tampered_read_back_is_corruption(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["tamper_stamp"]
        with pytest.raises(journal.JournalCorruptionError, match="DIFFERENT payload"):
            persistence.append_ready_stamp("100", _stamp())

    def test_stamp_read_back_scans_past_the_first_match(self) -> None:
        # The _stamp_landed complete-scan pin: a same-key conflicting duplicate LATER in the
        # rescan (after the byte-identical match) must still be corruption — never a
        # first-match return.
        persistence, store, issues = _make()
        store.add("100")
        issues.post_plan = ["race_stamp"]
        with pytest.raises(journal.JournalCorruptionError, match="DIFFERENT payload"):
            persistence.append_ready_stamp("100", _stamp())

    def test_recycled_head_re_stamp_is_idempotent_and_never_reorders(self) -> None:
        # The pinned deterministic-idempotence corner (contracts.md §8.43): after stamping
        # head A then head B, re-stamping the recycled EXACT head A is existed=True (no new
        # comment) and B's stamp stays latest — re-affirmation of a recycled head is a
        # content change or supersession, never a byte-identical re-append.
        persistence, store, issues = _make()
        store.add("100")
        head_b = "b" * 40
        persistence.append_ready_stamp("100", _stamp())
        persistence.append_ready_stamp("100", _stamp(head_sha=head_b))
        result = persistence.append_ready_stamp("100", _stamp())
        assert result.existed is True
        assert len(issues.post_calls) == 2  # the re-stamp never POSTs
        latest = persistence.read_journal("100").latest_ready_stamp(
            objective_id="100", plan_id="201"
        )
        assert latest is not None and latest.record.head_sha == head_b

    def test_objective_identity_mismatch_fails_closed(self) -> None:
        persistence, store, issues = _make()
        store.add("100")
        with pytest.raises(TrainPersistenceError, match="claims objective"):
            persistence.append_ready_stamp("100", _stamp(objective_id="999"))
        assert issues.post_calls == []

    def test_lineage_mismatch_fails_closed(self) -> None:
        persistence, store, issues = _make()
        store.add("100", lineage="01JZ0000000000000000000000")
        with pytest.raises(TrainPersistenceError, match="refusing to append"):
            persistence.append_ready_stamp("100", _stamp())
        assert issues.post_calls == []

    def test_stamp_appends_outside_the_one_unresolved_operation_gate(self) -> None:
        # The pinned asymmetry: a stamp is not a remote-mutating operation — it appends
        # cleanly while an unresolved PUBLISH blocks append_prepared.
        persistence, store, _ = _make()
        store.add("100")
        persistence.append_prepared("100", _prepared())
        result = persistence.append_ready_stamp("100", _stamp())
        assert result.existed is False
        with pytest.raises(UnresolvedOperationError):
            persistence.append_prepared("100", _prepared(operation_id=_OP_2))

    def test_supersession_scoping_retains_history_but_never_projects(self) -> None:
        # The replan/transfer regression: a predecessor-identity stamp on the shared lineage
        # folds (append-only history) but projects only under its own objective identity.
        persistence, store, issues = _make()
        store.add("A", carrier="SENT-A")
        persistence.append_ready_stamp("A", _stamp(objective_id="A"))
        store.add("B", supersedes="A", carrier="SENT-B")
        fold = persistence.read_journal("B")
        assert len(fold.stamps) == 1
        assert fold.latest_ready_stamp(objective_id="B", plan_id="201") is None
        stamp = fold.latest_ready_stamp(objective_id="A", plan_id="201")
        assert stamp is not None and stamp.record.objective_id == "A"
        assert len(issues.comments["SENT-A"]) == 1
        assert issues.comments.get("SENT-B", []) == []  # nothing ever copies stamps forward

    def test_conversion_scoping_exercises_the_inference_path(self) -> None:
        # The stacked→incremental regression: a conversion successor stores NO lineage, so the
        # fold's effective lineage is operation-inferred — the predecessor's stamp still folds
        # and still never projects under the successor identity.
        persistence, store, issues = _make()
        store.add("A", carrier="SENT-A")
        persistence.append_prepared("A", _prepared(objective_id="A"))
        persistence.append_outcome("A", _outcome())
        persistence.append_ready_stamp("A", _stamp(objective_id="A"))
        store.add("B", lineage=None, supersedes="A", carrier="SENT-B")
        fold = persistence.read_journal("B")
        assert fold.delivery_lineage == _LINEAGE  # inferred from the operation records
        assert len(fold.stamps) == 1
        assert fold.latest_ready_stamp(objective_id="B", plan_id="201") is None
        assert fold.latest_ready_stamp(objective_id="A", plan_id="201") is not None
        assert issues.comments.get("SENT-B", []) == []


class TestTypedWriters:
    def test_write_checkpoints_is_one_paired_write(self) -> None:
        persistence, _, issues = _make()
        persistence.write_checkpoints(
            "201", parent_checkpoint_sha="a" * 40, published_head_sha="b" * 40
        )
        assert issues.plan_header_writes == [
            ("201", {"parent_checkpoint_sha": "a" * 40, "published_head_sha": "b" * 40})
        ]

    def test_write_delivery_lineage_hits_objective_header(self) -> None:
        persistence, store, _ = _make()
        persistence.write_delivery_lineage("100", _LINEAGE)
        assert store.header_writes == [("100", {"delivery_lineage": _LINEAGE})]
