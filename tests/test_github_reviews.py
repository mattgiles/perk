import json
import subprocess
from pathlib import Path

import pytest
from _github_fakes import ROOT, _GhDispatch, _has, _Proc
from pydantic import ValidationError

from perk import github
from perk.github import _exec, reviews

# --- review feedback ----------------------------------------------------------------

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
        batch=[github.ResolveThreadRequest(thread_id="PRRT_1", comment="Fixed")], repo_root=ROOT
    )
    assert result.success is True
    assert result.results[0].comment_added is True and result.results[0].success is True
    # reply mutation ran before the resolve mutation
    assert rec.method_calls("graphql") == 2


def test_resolve_review_threads_no_comment_skips_reply(monkeypatch):
    rec = _GhDispatch([(_has("graphql", "resolveReviewThread"), _Proc(0, "{}"))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(
        batch=[github.ResolveThreadRequest(thread_id="PRRT_1")], repo_root=ROOT
    )
    assert result.success is True and result.results[0].comment_added is False


def test_resolve_review_threads_per_item_error_captured(monkeypatch):
    rec = _GhDispatch([(_has("graphql", "resolveReviewThread"), _Proc(1, stderr="bad thread"))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(
        batch=[github.ResolveThreadRequest(thread_id="BAD", comment=None)], repo_root=ROOT
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
        batch=[
            github.ResolveThreadRequest(thread_id="PRRT_1"),
            github.ResolveThreadRequest(thread_id="PRRT_2"),
        ],
        repo_root=ROOT,
    )
    assert result.success is False
    assert result.results[0].success is True and result.results[1].success is False


def test_resolve_review_threads_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    result = github.resolve_review_threads(
        batch=[github.ResolveThreadRequest(thread_id="PRRT_1", comment="x")],
        repo_root=ROOT,
        dry_run=True,
    )
    assert result.success is True and result.results[0].comment_added is True


# ---------------------------------------------------- GraphQL parse-layer narrowing


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


# --- boundary models (camelCase aliases + identity sharpening) --------------


def test_review_models_camelcase_aliases_map():
    comment = reviews.ReviewCommentModel.model_validate(
        {
            "databaseId": 99,
            "body": "b",
            "author": {"login": "rev"},
            "path": "p.py",
            "line": 3,
            "createdAt": "2024-01-01T00:00:00Z",
        }
    ).to_domain()
    assert comment.comment_id == 99 and comment.author == "rev"
    assert comment.created_at == "2024-01-01T00:00:00Z"

    thread = reviews.ReviewThreadModel.model_validate(
        {"id": "PRRT_1", "isResolved": True, "isOutdated": True}
    ).to_domain(comments=())
    assert (
        thread.thread_id == "PRRT_1" and thread.is_resolved is True and thread.is_outdated is True
    )

    review = reviews.ReviewModel.model_validate(
        {"id": "R_1", "author": {"login": "rev"}, "state": "APPROVED", "submittedAt": "t"}
    ).to_domain()
    assert review.review_id == "R_1" and review.author == "rev" and review.submitted_at == "t"


def test_review_comment_no_database_id_keeps_tolerance():
    # databaseId is not the thread identity, so its absence stays None (not a raise).
    comment = reviews.ReviewCommentModel.model_validate({"body": "a comment"}).to_domain()
    assert comment.comment_id is None and comment.author is None


def test_review_thread_missing_id_raises():
    with pytest.raises(ValidationError):
        reviews.ReviewThreadModel.model_validate({"isResolved": True})


def test_get_pr_feedback_malformed_thread_raises_labelled(monkeypatch):
    malformed = json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        # a thread node missing its required `id`
                        "reviewThreads": {"nodes": [{"isResolved": False}]}
                    }
                }
            }
        }
    )
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "reviewThreads"), _Proc(0, malformed)),
            (_has("graphql", "reviews"), _Proc(0, _REVIEWS_PAYLOAD)),
            (_has("issues/42/comments"), _Proc(0, _COMMENTS_PAYLOAD)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="parse review threads for PR #42"):
        github.get_pr_feedback(pr_number=42, repo_root=ROOT)


# --- the event-aware review submission (post_pr_review event/side + the formal ladder) -------


def _capturing_run(results: list[_Proc]):
    """A fake `_exec._run` that snapshots each call's argv + review payload at call time (the
    `--input` temp file is deleted once `_run` returns)."""
    calls: list[list[str]] = []
    payloads: list[dict] = []

    def fake_run(args, **_):
        calls.append(list(args))
        if "reviews" in " ".join(args) and "--input" in args:
            idx = args.index("--input")
            payloads.append(json.loads(Path(args[idx + 1]).read_text(encoding="utf-8")))
        return results.pop(0) if results else _Proc(0, "{}")

    return fake_run, calls, payloads


def test_post_pr_review_event_and_side_ride_the_payload(monkeypatch):
    fake_run, _calls, payloads = _capturing_run([_Proc(0, "{}")])
    monkeypatch.setattr(_exec, "_run", fake_run)
    result = github.post_pr_review(
        pr_number=42,
        summary="lgtm",
        comments=[github.InlineReviewComment(path="x.py", line=3, body="gone", side="LEFT")],
        repo_root=ROOT,
        event="APPROVE",
    )
    assert result.ok is True and result.mode == "review"
    assert payloads == [
        {
            "event": "APPROVE",
            "body": "lgtm",
            "comments": [{"path": "x.py", "line": 3, "side": "LEFT", "body": "gone"}],
        }
    ]


def test_post_pr_review_formal_failure_folds_once_event_preserved(monkeypatch):
    fake_run, calls, payloads = _capturing_run(
        [_Proc(1, "", "422 Unprocessable: line not part of the diff"), _Proc(0, "{}")]
    )
    monkeypatch.setattr(_exec, "_run", fake_run)
    comments = [
        github.InlineReviewComment(path="x.py", line=3, body="nit"),
        github.InlineReviewComment(path="y.py", line=9, body="dropped", side="LEFT"),
    ]
    result = github.post_pr_review(
        pr_number=42,
        summary="changes",
        comments=comments,
        repo_root=ROOT,
        event="REQUEST_CHANGES",
    )
    assert result.ok is True and result.mode == "review_folded"
    assert result.comment_count == 2  # the batch size, mirroring comment_fallback semantics
    assert len(payloads) == 2
    retry = payloads[1]
    assert retry["event"] == "REQUEST_CHANGES" and retry["comments"] == []
    assert "x.py:3" in retry["body"] and "nit" in retry["body"]
    assert "`y.py:9` (LEFT)" in retry["body"]  # the LEFT marker survives the fold
    # never a discussion-comment POST on a formal event
    assert not any("issues/42/comments" in " ".join(c) for c in calls)


def test_post_pr_review_formal_fold_retry_failure_raises_loudly(monkeypatch):
    fake_run, calls, _payloads = _capturing_run(
        [_Proc(1, "", "422 bad anchor"), _Proc(1, "", "422 still bad")]
    )
    monkeypatch.setattr(_exec, "_run", fake_run)
    with pytest.raises(github.GitHubError, match="REQUEST_CHANGES review for PR #42"):
        github.post_pr_review(
            pr_number=42,
            summary="changes",
            comments=[github.InlineReviewComment(path="x.py", line=3, body="nit")],
            repo_root=ROOT,
            event="REQUEST_CHANGES",
        )
    # two review POSTs (original + fold retry), never a discussion comment
    assert sum(1 for c in calls if "reviews" in " ".join(c)) == 2
    assert not any("issues/42/comments" in " ".join(c) for c in calls)


def test_post_pr_review_own_pr_rejection_raises_without_retry(monkeypatch):
    fake_run, calls, _payloads = _capturing_run(
        [_Proc(1, "", "422 Can not approve your own pull request")]
    )
    monkeypatch.setattr(_exec, "_run", fake_run)
    with pytest.raises(github.OwnPrReviewError):
        github.post_pr_review(
            pr_number=42,
            summary="lgtm",
            comments=[github.InlineReviewComment(path="x.py", line=3, body="nit")],
            repo_root=ROOT,
            event="APPROVE",
        )
    assert len(calls) == 1  # no second POST — an own-PR retry would fail identically


def test_post_pr_review_fold_retry_own_pr_rejection_classified(monkeypatch):
    # The first 422 may be anchor-shaped with the own-PR rejection surfacing only on the retry.
    fake_run, _calls, _payloads = _capturing_run(
        [
            _Proc(1, "", "422 bad anchor"),
            _Proc(1, "", "Can not request changes on your own pull request"),
        ]
    )
    monkeypatch.setattr(_exec, "_run", fake_run)
    with pytest.raises(github.OwnPrReviewError):
        github.post_pr_review(
            pr_number=42,
            summary="changes",
            comments=[github.InlineReviewComment(path="x.py", line=3, body="nit")],
            repo_root=ROOT,
            event="REQUEST_CHANGES",
        )


def test_post_pr_review_formal_bare_verdict_failure_raises_without_retry(monkeypatch):
    fake_run, calls, _payloads = _capturing_run([_Proc(1, "", "500 boom")])
    monkeypatch.setattr(_exec, "_run", fake_run)
    with pytest.raises(github.GitHubError, match="APPROVE review for PR #42"):
        github.post_pr_review(
            pr_number=42, summary="lgtm", comments=[], repo_root=ROOT, event="APPROVE"
        )
    assert len(calls) == 1  # an identical retry is pointless on a bare verdict


# --- get_pr_diff (the lean 3-dot diff read) ---------------------------------------------------


def test_get_pr_diff_success_returns_stdout(monkeypatch):
    diff_text = "diff --git a/x.py b/x.py\n"
    rec = _GhDispatch([(_has("pr", "diff"), _Proc(0, diff_text))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert github.get_pr_diff(pr_number=42, repo_root=ROOT) == diff_text
    assert rec.calls == [["pr", "diff", "42"]]


def test_get_pr_diff_not_found_returns_none(monkeypatch):
    rec = _GhDispatch(
        [
            (
                _has("pr", "diff"),
                _Proc(1, "", "GraphQL: Could not resolve to a PullRequest with the number of 42"),
            )
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert github.get_pr_diff(pr_number=42, repo_root=ROOT) is None


def test_get_pr_diff_other_failure_raises(monkeypatch):
    rec = _GhDispatch([(_has("pr", "diff"), _Proc(1, "", "HTTP 500"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="failed to read the diff for PR #42"):
        github.get_pr_diff(pr_number=42, repo_root=ROOT)
