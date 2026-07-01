"""`perk pr feedback` — the read-only PR-feedback fetch (the classify child runs this).

Resolves the active plan's PR (from the local `cache.plan-ref`, exactly as `pr land` does), fetches
its reviewer feedback (review threads + PR-level reviews via GraphQL, discussion comments via REST),
and emits `--json`. Read-only — no GitHub mutation; the verbose payload is consumed by the spawned
`perk.review-classifier` child so it never transits the parent session (route-don't-relay).

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / no plan / no PR / op failure · 2 not-a-repo.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import click

from perk import github
from perk.boundary import OutputModel
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@dataclass(frozen=True)
class PrFeedbackResult:
    feedback: github.PrFeedback
    branch: str


@click.command("feedback")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def feedback_pr(ctx: click.Context, *, as_json: bool) -> None:
    """Fetch the active plan's PR review feedback (read-only; the classify child runs this).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        result = _pr_feedback_impl(repo_root=repo_root)
    except GitHubError as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=f"PR feedback failed\n{exc}")
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if as_json:
        machine_output(json.dumps(_result_to_dict(result)))
    else:
        _render_human(result)


def _pr_feedback_impl(*, repo_root: Path) -> PrFeedbackResult:
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    branch = launch.resolve_plan_worktree_name(plan_ref)
    pr = github.find_pr_for_branch(branch=branch, repo_root=repo_root)
    if pr is None:
        raise UserFacingCliError(
            f"No PR found for branch {branch!r}\nRun /submit first.", error_type="no_pr"
        )
    feedback = github.get_pr_feedback(pr_number=pr.number, repo_root=repo_root)
    return PrFeedbackResult(feedback=feedback, branch=branch)


class FeedbackCommentOut(OutputModel):
    """The serialization boundary of one :class:`github.ReviewComment` (order load-bearing)."""

    comment_id: int | None
    body: str
    author: str | None
    path: str | None
    line: int | None
    created_at: str | None

    @classmethod
    def from_domain(cls, c: github.ReviewComment) -> "FeedbackCommentOut":
        return cls(
            comment_id=c.comment_id,
            body=c.body,
            author=c.author,
            path=c.path,
            line=c.line,
            created_at=c.created_at,
        )


class FeedbackThreadOut(OutputModel):
    """The serialization boundary of one :class:`github.ReviewThread` (field order load-bearing)."""

    thread_id: str
    is_resolved: bool
    is_outdated: bool
    path: str | None
    line: int | None
    comments: tuple[FeedbackCommentOut, ...]

    @classmethod
    def from_domain(cls, t: github.ReviewThread) -> "FeedbackThreadOut":
        return cls(
            thread_id=t.thread_id,
            is_resolved=t.is_resolved,
            is_outdated=t.is_outdated,
            path=t.path,
            line=t.line,
            comments=tuple(FeedbackCommentOut.from_domain(c) for c in t.comments),
        )


class DiscussionCommentOut(OutputModel):
    """The serialization boundary of one :class:`github.DiscussionComment`
    (field order load-bearing)."""

    comment_id: int
    body: str
    author: str | None
    created_at: str | None

    @classmethod
    def from_domain(cls, c: github.DiscussionComment) -> "DiscussionCommentOut":
        return cls(comment_id=c.comment_id, body=c.body, author=c.author, created_at=c.created_at)


class FeedbackReviewOut(OutputModel):
    """The serialization boundary of one :class:`github.Review` (field order load-bearing)."""

    review_id: str
    author: str | None
    body: str
    state: str
    submitted_at: str | None

    @classmethod
    def from_domain(cls, r: github.Review) -> "FeedbackReviewOut":
        return cls(
            review_id=r.review_id,
            author=r.author,
            body=r.body,
            state=r.state,
            submitted_at=r.submitted_at,
        )


class FeedbackCountsOut(OutputModel):
    """The computed feedback tally (field order load-bearing)."""

    review_threads: int
    unresolved_threads: int
    discussion_comments: int
    reviews: int


class PrFeedbackOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrFeedbackResult` (order
    load-bearing). ``pr`` maps from the domain ``pr_number``."""

    success: bool
    error_type: str | None
    message: str | None
    branch: str
    pr: int
    review_threads: tuple[FeedbackThreadOut, ...]
    discussion_comments: tuple[DiscussionCommentOut, ...]
    reviews: tuple[FeedbackReviewOut, ...]
    counts: FeedbackCountsOut

    @classmethod
    def from_domain(cls, result: PrFeedbackResult) -> "PrFeedbackOut":
        fb = result.feedback
        return cls(
            success=True,
            error_type=None,
            message=None,
            branch=result.branch,
            pr=fb.pr_number,
            review_threads=tuple(FeedbackThreadOut.from_domain(t) for t in fb.review_threads),
            discussion_comments=tuple(
                DiscussionCommentOut.from_domain(c) for c in fb.discussion_comments
            ),
            reviews=tuple(FeedbackReviewOut.from_domain(r) for r in fb.reviews),
            counts=FeedbackCountsOut(
                review_threads=len(fb.review_threads),
                unresolved_threads=sum(1 for t in fb.review_threads if not t.is_resolved),
                discussion_comments=len(fb.discussion_comments),
                reviews=len(fb.reviews),
            ),
        )


def _result_to_dict(result: PrFeedbackResult) -> dict[str, object]:
    return PrFeedbackOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrFeedbackResult) -> None:
    fb = result.feedback
    unresolved = sum(1 for t in fb.review_threads if not t.is_resolved)
    user_output(
        click.style("PR feedback ", fg="cyan")
        + f"#{fb.pr_number} ({result.branch}): "
        + f"{len(fb.review_threads)} thread(s) [{unresolved} unresolved], "
        + f"{len(fb.discussion_comments)} comment(s), {len(fb.reviews)} review(s)"
    )
