"""The GitHub gateway — Python plane, **verification-only** (contracts.md §8.4).

A thin ``gh``-shelling gateway implementing the two verification ops the init/doctor
surfaces need in Phase 0. It **never mutates** GitHub (Q9 — the first label is created
lazily by ``/plan-save`` in Phase 1). Mutation ops are named-only in §8.4 and land with
their stage handlers.

The TS extension authors the *same* operation names + payload shapes in Phase 1, so
``doctor`` can verify both planes and either can later swap ``gh``-shell → API-backed.

Issue/objective tier demotion (Objectives #252/#746): the issue/objective substrate now lives in
the backend tier at perk/backends/github/{plans,objectives,engagement}.py — plan/learn/objective
issues, marked comments, labels, and the read-only ``gh api graphql`` engagement reads. Production
code reaches that substrate only through the resolvers in perk/backends/resolve.py — never by
calling those module functions directly (enforced by the source-scan regression tests in
``tests/test_resolve.py``). The PR/CI/auth/review tier here remains the direct forge surface for all
backends.

This package is the **pure GitHub gateway** (PR/CI/auth/review only): it never imports the backend
tier (the one-way import guard scans this package for any backend-tier import).
"""

from perk.github import _exec
from perk.github._exec import GitHubError
from perk.github.auth import (
    AuthStatus,
    RepoAccess,
    check_auth,
    check_repo_access,
)
from perk.github.prs import (
    PrBodyUpdate,
    PullRequest,
    create_pr,
    default_branch,
    find_pr_for_branch,
    get_pr,
    get_pr_body,
    mark_pr_ready,
    merge_pr,
    update_pr_body,
    validate_pr_body,
)
from perk.github.reviews import (
    ADD_REVIEW_THREAD_REPLY_MUTATION,
    GET_PR_REVIEW_THREADS_QUERY,
    GET_PR_REVIEWS_QUERY,
    RESOLVE_REVIEW_THREAD_MUTATION,
    BatchResolveResult,
    DiscussionComment,
    InlineReviewComment,
    PrFeedback,
    PrReviewContext,
    Review,
    ReviewComment,
    ReviewPostResult,
    ReviewThread,
    ThreadResolveResult,
    add_pr_reaction,
    get_pr_feedback,
    get_pr_review_context,
    post_pr_review,
    resolve_review_threads,
)
from perk.github.workflows import (
    WorkflowPermissions,
    WorkflowRun,
    cancel_workflow_run,
    get_repo_variable,
    get_workflow_permissions,
    get_workflow_run,
    rerun_workflow_run,
    secret_exists,
    trigger_workflow,
)

__all__ = [
    "ADD_REVIEW_THREAD_REPLY_MUTATION",
    "GET_PR_REVIEWS_QUERY",
    "GET_PR_REVIEW_THREADS_QUERY",
    "RESOLVE_REVIEW_THREAD_MUTATION",
    "AuthStatus",
    "BatchResolveResult",
    "DiscussionComment",
    "GitHubError",
    "InlineReviewComment",
    "PrBodyUpdate",
    "PrFeedback",
    "PrReviewContext",
    "PullRequest",
    "RepoAccess",
    "Review",
    "ReviewComment",
    "ReviewPostResult",
    "ReviewThread",
    "ThreadResolveResult",
    "WorkflowPermissions",
    "WorkflowRun",
    "_exec",
    "add_pr_reaction",
    "cancel_workflow_run",
    "check_auth",
    "check_repo_access",
    "create_pr",
    "default_branch",
    "find_pr_for_branch",
    "get_pr",
    "get_pr_body",
    "get_pr_feedback",
    "get_pr_review_context",
    "get_repo_variable",
    "get_workflow_permissions",
    "get_workflow_run",
    "mark_pr_ready",
    "merge_pr",
    "post_pr_review",
    "rerun_workflow_run",
    "resolve_review_threads",
    "secret_exists",
    "trigger_workflow",
    "update_pr_body",
    "validate_pr_body",
]
