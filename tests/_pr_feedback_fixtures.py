"""Shared `perk pr feedback` fixtures.

The mixed fixture exercises every shape the `/address` parent's snapshot decoder narrows: an
unresolved thread, a resolved thread (excluded from classification), an outdated-but-unresolved
thread whose inline comment has a null id and a null author, two discussion comments, and one
PR-level review (counted, never classified). Its golden (`pr_feedback_mixed.json`) is the
cross-plane fixture the TypeScript decoder test reads.
"""

from perk import github


def mixed_feedback() -> github.PrFeedback:
    return github.PrFeedback(
        pr_number=42,
        review_threads=(
            github.ReviewThread(
                thread_id="PRRT_open",
                is_resolved=False,
                is_outdated=False,
                path="perk/github.py",
                line=12,
                comments=(
                    github.ReviewComment(
                        comment_id=101,
                        body="rename this",
                        author="rev",
                        path="perk/github.py",
                        line=12,
                        created_at="2026-01-01T00:00:00Z",
                    ),
                    github.ReviewComment(
                        comment_id=102,
                        body="agreed",
                        author="other",
                        path="perk/github.py",
                        line=12,
                        created_at="2026-01-02T00:00:00Z",
                    ),
                ),
            ),
            github.ReviewThread(
                thread_id="PRRT_resolved",
                is_resolved=True,
                is_outdated=False,
                path="perk/cli.py",
                line=3,
                comments=(
                    github.ReviewComment(
                        comment_id=103,
                        body="done already",
                        author="rev",
                        path="perk/cli.py",
                        line=3,
                        created_at="2026-01-01T00:00:00Z",
                    ),
                ),
            ),
            github.ReviewThread(
                thread_id="PRRT_outdated",
                is_resolved=False,
                is_outdated=True,
                path=None,
                line=None,
                comments=(
                    github.ReviewComment(
                        comment_id=None,
                        body="is this still needed?",
                        author=None,
                        path=None,
                        line=None,
                        created_at=None,
                    ),
                ),
            ),
        ),
        discussion_comments=(
            github.DiscussionComment(
                comment_id=7, body="nice work", author="rev", created_at="2026-01-03T00:00:00Z"
            ),
            github.DiscussionComment(
                comment_id=8, body="please add a test", author=None, created_at=None
            ),
        ),
        reviews=(
            github.Review(
                review_id="PRR_1",
                author="rev",
                body="changes please",
                state="CHANGES_REQUESTED",
                submitted_at="2026-01-03T00:00:00Z",
            ),
        ),
    )
