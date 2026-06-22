import json
import subprocess

import pytest
from _github_fakes import ROOT, _GhDispatch, _has, _Proc

from perk import github
from perk.github import _exec, reviews

# --- review feedback (P2.T7) ----------------------------------------------------------------

_THREADS_PAYLOAD = json.dumps(
    {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "PRRT_1",
                                "isResolved": False,
                                "isOutdated": False,
                                "path": "perk/github.py",
                                "line": 12,
                                "comments": {
                                    "nodes": [
                                        {
                                            "databaseId": 99,
                                            "body": "please rename this",
                                            "author": {"login": "rev"},
                                            "path": "perk/github.py",
                                            "line": 12,
                                            "createdAt": "2026-01-01T00:00:00Z",
                                        }
                                    ]
                                },
                            },
                            {
                                "id": "PRRT_2",
                                "isResolved": True,
                                "isOutdated": False,
                                "path": None,
                                "line": None,
                                "comments": {"nodes": []},
                            },
                        ]
                    }
                }
            }
        }
    }
)

_REVIEWS_PAYLOAD = json.dumps(
    {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviews": {
                        "nodes": [
                            {
                                "id": "PRR_1",
                                "author": {"login": "rev"},
                                "body": "looks good",
                                "state": "APPROVED",
                                "submittedAt": "2026-01-02T00:00:00Z",
                            }
                        ]
                    }
                }
            }
        }
    }
)

_COMMENTS_PAYLOAD = json.dumps(
    [{"id": 7, "body": "nice work", "user": {"login": "rev"}, "created_at": "2026-01-03T00:00:00Z"}]
)


def test_get_pr_feedback_parses_all_sources(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "reviewThreads"), _Proc(0, _THREADS_PAYLOAD)),
            (_has("graphql", "reviews"), _Proc(0, _REVIEWS_PAYLOAD)),
            (_has("issues/42/comments"), _Proc(0, _COMMENTS_PAYLOAD)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    fb = github.get_pr_feedback(pr_number=42, repo_root=ROOT)
    assert fb.pr_number == 42
    assert len(fb.review_threads) == 2
    assert fb.review_threads[0].thread_id == "PRRT_1"
    assert fb.review_threads[0].is_resolved is False
    assert fb.review_threads[0].comments[0].comment_id == 99
    assert fb.review_threads[1].is_resolved is True
    assert len(fb.discussion_comments) == 1 and fb.discussion_comments[0].comment_id == 7
    assert len(fb.reviews) == 1 and fb.reviews[0].state == "APPROVED"


def test_get_pr_feedback_infra_failure_raises(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "reviewThreads"), _Proc(1, stderr="HTTP 500")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError):
        github.get_pr_feedback(pr_number=42, repo_root=ROOT)


def test_resolve_review_threads_reply_then_resolve(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("graphql", "addPullRequestReviewThreadReply"), _Proc(0, "{}")),
            (_has("graphql", "resolveReviewThread"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "PRRT_1", "comment": "Fixed"}], repo_root=ROOT
    )
    assert result.success is True
    assert result.results[0].comment_added is True and result.results[0].success is True
    # reply mutation ran before the resolve mutation
    assert rec.method_calls("graphql") == 2


def test_resolve_review_threads_no_comment_skips_reply(monkeypatch):
    rec = _GhDispatch([(_has("graphql", "resolveReviewThread"), _Proc(0, "{}"))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(batch=[{"thread_id": "PRRT_1"}], repo_root=ROOT)
    assert result.success is True and result.results[0].comment_added is False


def test_resolve_review_threads_per_item_error_captured(monkeypatch):
    rec = _GhDispatch([(_has("graphql", "resolveReviewThread"), _Proc(1, stderr="bad thread"))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "BAD", "comment": None}], repo_root=ROOT
    )
    assert result.success is False
    assert result.results[0].success is False and "bad thread" in (result.results[0].error or "")


def test_resolve_review_threads_batch_success_is_all(monkeypatch):
    def fake_run(args, **_):
        gh = args[1:]
        if any("resolveReviewThread" in t for t in gh):
            # second thread id fails
            if any("PRRT_2" in t for t in gh):
                return _Proc(1, stderr="nope")
            return _Proc(0, "{}")
        return _Proc(1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "PRRT_1"}, {"thread_id": "PRRT_2"}], repo_root=ROOT
    )
    assert result.success is False
    assert result.results[0].success is True and result.results[1].success is False


def test_resolve_review_threads_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "PRRT_1", "comment": "x"}], repo_root=ROOT, dry_run=True
    )
    assert result.success is True and result.results[0].comment_added is True


# ---------------------------------------------------- GraphQL parse-layer narrowing (Node 4.1)


def test_opt_str_narrows():
    assert _exec._opt_str("hi") == "hi"
    assert _exec._opt_str(7) is None
    assert _exec._opt_str(None) is None
    assert _exec._opt_str(True) is None


def test_opt_int_narrows():
    assert _exec._opt_int(7) == 7
    assert _exec._opt_int("7") is None
    assert _exec._opt_int(None) is None
    # a GraphQL Int is never a bool — reject it (bool is an int subclass)
    assert _exec._opt_int(True) is None
    assert _exec._opt_int(False) is None


def test_parse_review_threads_partial_payload_is_none_safe():
    # A null `repository` (a not-found / permission-shaped GraphQL payload) yields no threads.
    assert reviews._parse_review_threads({"data": {"repository": None}}) == ()
    # An entirely empty payload is equally safe.
    assert reviews._parse_review_threads({}) == ()


def test_parse_review_threads_missing_node_fields_fill_none():
    payload: dict[str, object] = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "PRRT_1",
                                # isResolved/isOutdated/path/line absent
                                "comments": {
                                    "nodes": [
                                        # databaseId/author/path/line/createdAt all absent
                                        {"body": "a comment"}
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    (thread,) = reviews._parse_review_threads(payload)
    assert thread.thread_id == "PRRT_1"
    assert thread.is_resolved is False and thread.is_outdated is False
    assert thread.path is None and thread.line is None
    (comment,) = thread.comments
    assert comment.comment_id is None
    assert comment.body == "a comment"
    assert comment.author is None
    assert comment.path is None and comment.line is None and comment.created_at is None


def test_parse_reviews_partial_payload_is_none_safe():
    assert reviews._parse_reviews({"data": {"repository": None}}) == ()
    payload: dict[str, object] = {
        "data": {
            "repository": {
                "pullRequest": {
                    # author/submittedAt absent on the node
                    "reviews": {"nodes": [{"id": "R_1", "state": "COMMENTED"}]}
                }
            }
        }
    }
    (review,) = reviews._parse_reviews(payload)
    assert review.review_id == "R_1" and review.state == "COMMENTED"
    assert review.author is None and review.submitted_at is None and review.body == ""
