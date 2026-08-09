"""Live-shaped Linear coverage for the train-persistence journal (contracts.md §8.43).

Drives ``TrainPersistence`` over the REAL ``LinearProjectObjectiveStore`` +
``LinearIssueBackend`` sharing one stateful ``FakeLinearWorkspace`` (page size 2, so the cursor
loop runs on real data): the journal carrier is the Project metadata sentinel issue, appends
store the TRANSCODED inline-code marker (the real ``to_linear_markdown`` transcoder), reads
parse it back (the cross-encoding round trip), and an ``editedAt``-stamped comment is
corruption. The scripted-fake carrier-resolution cases (sentinel-less raise / absent-project
None) live in ``tests/test_linear_project_store.py``.
"""

from pathlib import Path

import pytest
from test_linear_lifecycle import FakeLinearWorkspace

from perk import objective
from perk.backends.linear import LinearIssueBackend, LinearProjectObjectiveStore
from perk.delivery import journal
from perk.delivery.persistence import TrainPersistence

_LINEAGE = "01JB0000000000000000000000"
_OP = "01JA0000000000000000000000"


def _setup() -> tuple[TrainPersistence, FakeLinearWorkspace, str]:
    """One workspace, the real store + backend over it, and a created objective (sentinel
    minted first → ``ENG-1``) whose header carries the delivery lineage."""
    ws = FakeLinearWorkspace()
    store = LinearProjectObjectiveStore(ws, team_key="ENG", repo_root=Path("/repo"))
    issues = LinearIssueBackend(ws, team_key="ENG", repo_root=Path("/repo"))
    nodes = [
        objective.ObjectiveNode(id="1.1", description="One", status=objective.NodeStatus.PENDING)
    ]
    ref = store.create_objective(
        title="Obj", body="# Obj\n\nprose", run_id="01RUN", roadmap_nodes=nodes
    )
    store.update_objective_header(objective_id=ref.id, fields={"delivery_lineage": _LINEAGE})
    return TrainPersistence(store, issues), ws, ref.id


def _prepared(objective_id: str) -> journal.PreparedRecord:
    return journal.PreparedRecord(
        operation_id=_OP,
        operation_kind=journal.OperationKind.PUBLISH,
        delivery_lineage=_LINEAGE,
        objective_id=objective_id,
        run_id="01JC0000000000000000000000",
        created="2026-01-01T00:00:00Z",
        affected_plans=("ENG-9",),
        before={"sha": "a" * 40},
        after={"sha": "b" * 40},
    )


def _outcome() -> journal.OutcomeRecord:
    return journal.OutcomeRecord(
        operation_id=_OP,
        role=journal.EventRole.COMPLETED,
        created="2026-01-02T00:00:00Z",
        observed={"verified": True},
    )


def test_journal_carrier_is_the_sentinel_identifier() -> None:
    persistence, ws, obj_id = _setup()
    del persistence
    store = LinearProjectObjectiveStore(ws, team_key="ENG", repo_root=Path("/repo"))
    assert store.journal_carrier_id(objective_id=obj_id) == "ENG-1"


def test_append_round_trips_through_the_transcoder() -> None:
    """The cross-encoding round trip against the real transcoder + the real paginate loop:
    appends land the TRANSCODED inline-code marker on the sentinel issue; the read parses it
    back byte-identically (canonical payload). Three comments on a page size of 2 exercise the
    cursor loop."""
    persistence, ws, obj_id = _setup()
    # A foreign integration-style comment on the sentinel is ignored as unrelated DATA (and
    # pushes the comment count past one page).
    ws.add_foreign_comment("ENG-1", "linkback from a GitHub integration")

    result = persistence.append_prepared(obj_id, _prepared(obj_id))
    assert result.existed is False

    sentinel = ws.issue_by_identifier("ENG-1")
    [_, prepared_comment] = ws.comments_of(sentinel)
    body = str(prepared_comment["body"])
    assert f"`perk:stack-operation-event:{_OP}:prepared`" in body  # the transcoded marker
    assert "<!--" not in body  # nothing HTML-encoded survives the transcoder
    assert "```yaml" in body

    outcome = persistence.append_outcome(obj_id, _outcome())
    assert outcome.existed is False
    assert len(ws.comments_of(sentinel)) == 3  # > one fake page (page size 2)

    fold = persistence.read_journal(obj_id)
    assert list(fold.operations) == [_OP]
    assert fold.operations[_OP].resolved is True
    assert fold.unresolved == ()
    # byte identity across encodings: the parsed canonical payload equals the record's.
    assert fold.operations[_OP].prepared.canonical_payload == journal.canonical_payload(
        _prepared(obj_id)
    )


def test_idempotent_re_append_over_the_transcoded_marker() -> None:
    persistence, ws, obj_id = _setup()
    persistence.append_prepared(obj_id, _prepared(obj_id))
    again = persistence.append_prepared(obj_id, _prepared(obj_id))
    assert again.existed is True
    assert len(ws.comments_of(ws.issue_by_identifier("ENG-1"))) == 1  # never duplicated


def test_edited_comment_is_corruption() -> None:
    persistence, ws, obj_id = _setup()
    persistence.append_prepared(obj_id, _prepared(obj_id))
    sentinel = ws.issue_by_identifier("ENG-1")
    ws.comments_of(sentinel)[0]["editedAt"] = "2026-06-13T00:00:00Z"
    with pytest.raises(journal.JournalCorruptionError, match="edited"):
        persistence.read_journal(obj_id)
