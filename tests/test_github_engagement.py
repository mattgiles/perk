import json
import subprocess

import pytest
from _github_fakes import ROOT, _GhDispatch, _has, _Proc

from perk import github
from perk.backends.github import engagement as gh_engagement

# --- human-engagement reads (Objective #682, Node 1.3) --------------------------------------


def _actor_node(*, login, database_id, typename="User"):
    return {"login": login, "__typename": typename, "databaseId": database_id}


def _comments_payload(nodes, *, has_next=False, end_cursor=None):
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


def _edits_payload(nodes, *, has_next=False, end_cursor=None):
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "userContentEdits": {
                            "nodes": nodes,
                            "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                        }
                    }
                }
            }
        }
    )


def test_read_issue_comments_parses_and_orders(monkeypatch):
    nodes = [
        {
            "id": "IC_3",
            "body": "later human",
            "createdAt": "2026-03-03T00:00:00Z",
            "lastEditedAt": "2026-03-04T00:00:00Z",
            "author": _actor_node(login="alice", database_id=11),
        },
        {
            "id": "IC_1",
            "body": "earliest human",
            "createdAt": "2026-03-01T00:00:00Z",
            "lastEditedAt": None,
            "author": _actor_node(login="bob", database_id=22),
        },
        {
            "id": "IC_2",
            "body": "bot beep",
            "createdAt": "2026-03-02T00:00:00Z",
            "lastEditedAt": None,
            "author": _actor_node(login="perk-bot", database_id=33, typename="Bot"),
        },
    ]
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "comments"), _Proc(0, _comments_payload(nodes))),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    rows = gh_engagement.read_issue_comments(issue=42, repo_root=ROOT)
    assert [r.id for r in rows] == ["IC_1", "IC_2", "IC_3"]  # ascending createdAt
    assert rows[0].edited_at is None and rows[0].author_is_bot is False
    assert rows[0].author_login == "bob" and rows[0].author_id == "22"
    assert rows[1].author_is_bot is True  # the bot comment
    assert rows[2].edited_at == "2026-03-04T00:00:00Z"  # the edited comment


def test_read_issue_comments_paginates(monkeypatch):
    page1 = _comments_payload(
        [
            {
                "id": "IC_1",
                "body": "p1",
                "createdAt": "2026-03-01T00:00:00Z",
                "lastEditedAt": None,
                "author": _actor_node(login="a", database_id=1),
            }
        ],
        has_next=True,
        end_cursor="CUR2",
    )
    page2 = _comments_payload(
        [
            {
                "id": "IC_2",
                "body": "p2",
                "createdAt": "2026-03-02T00:00:00Z",
                "lastEditedAt": None,
                "author": _actor_node(login="b", database_id=2),
            }
        ]
    )

    def dispatch(args, **_):
        gh = args[1:]
        rec.calls.append(gh)
        if "nameWithOwner" in " ".join(gh):
            return _Proc(0, "octo/repo\n")
        if any("cursor=CUR2" in tok for tok in gh):
            return _Proc(0, page2)
        return _Proc(0, page1)

    rec = _GhDispatch([])
    monkeypatch.setattr(subprocess, "run", dispatch)
    rows = gh_engagement.read_issue_comments(issue=42, repo_root=ROOT)
    assert [r.id for r in rows] == ["IC_1", "IC_2"]
    # the second graphql call carried the cursor
    assert any(any("cursor=CUR2" in tok for tok in c) for c in rec.calls)


def test_read_description_edits_parses_diff_passthrough_and_orders(monkeypatch):
    nodes = [
        {
            "editedAt": "2026-04-02T00:00:00Z",
            "diff": None,
            "editor": _actor_node(login="botedit", database_id=9, typename="Bot"),
        },
        {
            "editedAt": "2026-04-01T00:00:00Z",
            "diff": "@@ -1 +1 @@",
            "editor": _actor_node(login="human", database_id=8),
        },
    ]
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "userContentEdits"), _Proc(0, _edits_payload(nodes))),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    rows = gh_engagement.read_description_edits(issue=42, repo_root=ROOT)
    assert [r.edited_at for r in rows] == [
        "2026-04-01T00:00:00Z",
        "2026-04-02T00:00:00Z",
    ]  # ascending
    assert rows[0].diff == "@@ -1 +1 @@" and rows[0].editor_is_bot is False
    assert rows[1].diff is None and rows[1].editor_is_bot is True


def test_engagement_reads_not_found_fold_to_empty(monkeypatch):
    # The real `gh api graphql` miss: exit 1, stderr "Could not resolve to an Issue ..." + a
    # stdout body carrying `"type":"NOT_FOUND"` — neither the literal "not found" nor "404".
    not_found = _Proc(
        1,
        stdout=json.dumps(
            {"data": {"repository": {"issue": None}}, "errors": [{"type": "NOT_FOUND"}]}
        ),
        stderr="gh: Could not resolve to an Issue with the number of 999.",
    )
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql"), not_found),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert gh_engagement.read_issue_comments(issue=999, repo_root=ROOT) == []
    assert gh_engagement.read_description_edits(issue=999, repo_root=ROOT) == []


def test_engagement_reads_infra_failure_raises(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql"), _Proc(1, stderr="HTTP 500")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError):
        gh_engagement.read_issue_comments(issue=42, repo_root=ROOT)
    with pytest.raises(github.GitHubError):
        gh_engagement.read_description_edits(issue=42, repo_root=ROOT)
