"""Live-shaped GitHub coverage for the train-persistence journal (contracts.md §8.43).

Drives ``TrainPersistence`` over the REAL ``GitHubObjectiveStore`` + ``GitHubIssueBackend`` with
scripted ``gh`` procs (the ``_github_fakes`` substrate): the paginated GraphQL comments read
feeding the fold, the REST append POST carrying the HTML marker + fenced YAML, the read-back
scan, the edited-comment corruption, and the carrier resolution off the objective issue.
"""

import json
import subprocess
from pathlib import Path

import pytest
from _github_fakes import ROOT, _GhDispatch, _has, _Proc

from perk import objective, plan
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.delivery import journal
from perk.delivery.persistence import TrainPersistence

_LINEAGE = "01JB0000000000000000000000"
_OP = "01JA0000000000000000000000"


def _persistence() -> TrainPersistence:
    return TrainPersistence(GitHubObjectiveStore(ROOT), GitHubIssueBackend(ROOT))


def _objective_body(lineage: str = _LINEAGE) -> str:
    return plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY,
        {"run_id": "01RUN", "created": "t", "status": "active", "delivery_lineage": lineage},
    )


def _issue_view(number: int = 252) -> _Proc:
    return _Proc(
        0,
        json.dumps(
            {"number": number, "title": "obj", "body": _objective_body(), "url": f"u{number}"}
        ),
    )


def _prepared(operation_id: str = _OP) -> journal.PreparedRecord:
    return journal.PreparedRecord(
        operation_id=operation_id,
        operation_kind=journal.OperationKind.PUBLISH,
        delivery_lineage=_LINEAGE,
        objective_id="252",
        run_id="01JC0000000000000000000000",
        created="2026-01-01T00:00:00Z",
        affected_plans=("201",),
        before={"sha": "a" * 40},
        after={"sha": "b" * 40},
    )


def _comment_node(
    cid: str, body: str, created_at: str, edited_at: str | None = None
) -> dict[str, object]:
    return {
        "id": cid,
        "body": body,
        "createdAt": created_at,
        "lastEditedAt": edited_at,
        "author": {"login": "perk-bot", "__typename": "Bot", "databaseId": 1},
    }


def _comments_payload(
    nodes: list[dict[str, object]], *, has_next: bool = False, end_cursor: str | None = None
) -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "comments": {
                            "nodes": nodes,
                            "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                        }
                    }
                }
            }
        }
    )


def test_read_journal_folds_across_graphql_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pagination-coverage pin: journal events split across ≥2 GraphQL pages all reach the
    fold (the comments read is the cursor-paginated engagement read, never the non-paginating
    REST marker finder)."""
    prepared_body = journal.render_event(_prepared())
    completed_body = journal.render_event(
        journal.OutcomeRecord(
            operation_id=_OP,
            role=journal.EventRole.COMPLETED,
            created="2026-01-02T00:00:00Z",
            observed={"verified": True},
        )
    )
    page1 = _comments_payload(
        [_comment_node("IC_1", prepared_body, "2026-03-01T00:00:00Z")],
        has_next=True,
        end_cursor="CUR2",
    )
    page2 = _comments_payload([_comment_node("IC_2", completed_body, "2026-03-02T00:00:00Z")])

    rec = _GhDispatch([])

    def dispatch(args: list[str], **_: object) -> _Proc:
        gh = args[1:]
        rec.calls.append(gh)
        if _has("issue", "view", "252")(gh):
            return _issue_view()
        if _has("repo", "view", "nameWithOwner")(gh):
            return _Proc(0, "octo/repo\n")
        if any("cursor=CUR2" in tok for tok in gh):
            return _Proc(0, page2)
        return _Proc(0, page1)

    monkeypatch.setattr(subprocess, "run", dispatch)
    fold = _persistence().read_journal("252")
    assert list(fold.operations) == [_OP]
    assert fold.operations[_OP].resolved is True
    assert fold.unresolved == ()
    # the second graphql call carried the page cursor
    assert any(any("cursor=CUR2" in tok for tok in c) for c in rec.calls)


def test_append_prepared_posts_marker_and_reads_back(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    rec = _GhDispatch([])

    def dispatch(args: list[str], **_: object) -> _Proc:
        gh = args[1:]
        rec.calls.append(gh)
        if _has("issue", "view", "252")(gh):
            return _issue_view()
        if _has("repo", "view", "nameWithOwner")(gh):
            return _Proc(0, "octo/repo\n")
        if _has("issues/252/comments", "POST")(gh):
            for tok in gh:
                if tok.startswith("body=@"):
                    posted.append(Path(tok[len("body=@") :]).read_text(encoding="utf-8"))
            return _Proc(0, "{}")
        # comments read: empty before the POST, the posted event after (the read-back scan).
        nodes = [_comment_node("IC_1", posted[0], "2026-03-01T00:00:00Z")] if posted else []
        return _Proc(0, _comments_payload(nodes))

    monkeypatch.setattr(subprocess, "run", dispatch)
    result = _persistence().append_prepared("252", _prepared())
    assert result.existed is False
    [body] = posted  # exactly one POST
    assert f"<!-- perk:stack-operation-event:{_OP}:prepared -->" in body
    assert "```yaml" in body and "operation_kind: publish" in body


def test_edited_comment_row_is_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    body = journal.render_event(_prepared())
    payload = _comments_payload(
        [_comment_node("IC_1", body, "2026-03-01T00:00:00Z", edited_at="2026-03-02T00:00:00Z")]
    )
    rec = _GhDispatch(
        [
            (_has("issue", "view", "252"), _issue_view()),
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "comments"), _Proc(0, payload)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(journal.JournalCorruptionError, match="edited"):
        _persistence().read_journal("252")


def test_journal_carrier_id_is_the_objective_issue_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _GhDispatch([(_has("issue", "view", "252"), _issue_view())])
    monkeypatch.setattr(subprocess, "run", rec)
    assert GitHubObjectiveStore(ROOT).journal_carrier_id(objective_id="252") == "252"
