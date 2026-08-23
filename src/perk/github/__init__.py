"""The GitHub gateway — Python plane, **verification-only** (contracts.md §8.4).

A thin ``gh``-shelling gateway implementing the two verification ops the init/doctor
surfaces need. It **never mutates** GitHub (the first label is created lazily by
``/plan-save``). Mutation ops are named-only in §8.4 and land with their stage handlers.

The TS extension authors the *same* operation names + payload shapes, so
``doctor`` can verify both planes and either can later swap ``gh``-shell → API-backed.

Issue/objective tier demotion: the issue/objective substrate now lives in
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
from perk.github.diff_anchors import (
    DiffAnchors,
    parse_diff_anchors,
)
from perk.github.prs import (
    PrBodyUpdate,
    PullRequest,
    create_pr,
    default_branch,
    find_pr_for_branch,
    get_pr,
    get_pr_author,
    get_pr_body,
    list_open_prs_for_base,
    list_prs_for_branch,
    mark_pr_ready,
    merge_pr,
    reopen_pr,
    update_pr_base,
    update_pr_body,
    validate_pr_body,
)
from perk.github.repo import (
    RepoIdentity,
    repo_identity,
)
from perk.github.reviews import (
    ADD_REVIEW_THREAD_REPLY_MUTATION,
    GET_PR_REVIEW_THREADS_QUERY,
    GET_PR_REVIEWS_QUERY,
    RESOLVE_REVIEW_THREAD_MUTATION,
    BatchResolveResult,
    DiscussionComment,
    InlineReviewComment,
    OwnPrReviewError,
    PrFeedback,
    PrReviewContext,
    ResolveThreadRequest,
    Review,
    ReviewComment,
    ReviewPostResult,
    ReviewThread,
    ThreadResolveResult,
    add_pr_reaction,
    get_pr_diff,
    get_pr_feedback,
    get_pr_review_context,
    post_pr_review,
    resolve_review_threads,
)
from perk.github.stacks import (
    PrDeliveryFacts,
    StackEntryFacts,
    StackFacts,
    StackMutationOutcome,
    StackObservation,
    StackRestEntry,
    StackRestFacts,
    append_to_stack,
    create_stack,
    pr_delivery_facts,
    pr_stack,
    stack_for_pr,
)
from perk.github.workflows import (
    WorkflowPermissions,
    WorkflowRun,
    WorkflowRunListing,
    cancel_workflow_run,
    get_repo_variable,
    get_workflow_permissions,
    get_workflow_run,
    list_workflow_runs,
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
    "DiffAnchors",
    "DiscussionComment",
    "GitHubError",
    "InlineReviewComment",
    "OwnPrReviewError",
    "PrBodyUpdate",
    "PrDeliveryFacts",
    "PrFeedback",
    "PrReviewContext",
    "PullRequest",
    "RepoAccess",
    "RepoIdentity",
    "ResolveThreadRequest",
    "Review",
    "ReviewComment",
    "ReviewPostResult",
    "ReviewThread",
    "StackEntryFacts",
    "StackFacts",
    "StackMutationOutcome",
    "StackObservation",
    "StackRestEntry",
    "StackRestFacts",
    "ThreadResolveResult",
    "WorkflowPermissions",
    "WorkflowRun",
    "WorkflowRunListing",
    "_exec",
    "add_pr_reaction",
    "append_to_stack",
    "cancel_workflow_run",
    "check_auth",
    "check_repo_access",
    "create_pr",
    "create_stack",
    "default_branch",
    "find_pr_for_branch",
    "get_pr",
    "get_pr_author",
    "get_pr_body",
    "get_pr_diff",
    "get_pr_feedback",
    "get_pr_review_context",
    "get_repo_variable",
    "get_workflow_permissions",
    "get_workflow_run",
    "list_open_prs_for_base",
    "list_prs_for_branch",
    "list_workflow_runs",
    "mark_pr_ready",
    "merge_pr",
    "parse_diff_anchors",
    "post_pr_review",
    "pr_delivery_facts",
    "pr_stack",
    "reopen_pr",
    "repo_identity",
    "rerun_workflow_run",
    "resolve_review_threads",
    "secret_exists",
    "stack_for_pr",
    "trigger_workflow",
    "update_pr_base",
    "update_pr_body",
    "validate_pr_body",
]
