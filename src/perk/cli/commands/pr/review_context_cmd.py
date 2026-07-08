"""`perk pr review-context` — the read-only PR-review context fetch.

Flagless, resolves the active plan's PR (from the local `cache.plan-ref`, exactly as `pr feedback`
does); with `--pr <n>`, resolves an arbitrary PR by number, plan-ref-free (the `/review` foreign-PR
flow — no plan exists, so `plan_body` is null). Either way it gathers everything a fresh-context
reviewer child needs (the diff, the PR title/body, and the plan body when one exists) and emits
`--json`. Read-only — no GitHub mutation; the verbose payload is consumed by the spawned reviewer
child so it never transits the parent session.

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / no plan / no PR / op failure · 2 not-a-repo.
"""

from dataclasses import dataclass
from pathlib import Path

import click

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.boundary import OutputModel
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import user_output


@dataclass(frozen=True)
class PrReviewContextResult:
    context: github.PrReviewContext
    branch: str


@click.command("review-context")
@click.option(
    "--pr",
    "pr_number",
    type=int,
    default=None,
    help="Resolve an arbitrary PR by number (plan-ref-free; plan_body is null).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def review_context_pr(ctx: click.Context, *, pr_number: int | None, as_json: bool) -> None:
    """Fetch a PR's review context (read-only; a fresh-context reviewer child runs this).

    \b
    Flagless: the active plan's PR — run from inside the plan's worktree
    (it reads the local cache.plan-ref). With --pr N: an arbitrary PR by
    number, plan-ref-free (plan_body is null).
    """
    try:
        repo_root = require_repo(ctx)
        result = _impl(repo_root=repo_root, pr_number=pr_number)
    except GitHubError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"PR review context failed\n{exc}",
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    emit(as_json=as_json, payload=_result_to_dict(result), render=lambda: _render_human(result))


def _impl(*, repo_root: Path, pr_number: int | None) -> PrReviewContextResult:
    if pr_number is not None:
        return _foreign_pr_context(repo_root=repo_root, pr_number=pr_number)
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
    context = github.get_pr_review_context(
        pr_number=pr.number,
        branch=branch,
        repo_root=repo_root,
        plan_body=_resolve_plan_body(repo_root, plan_ref),
    )
    return PrReviewContextResult(context=context, branch=branch)


def _foreign_pr_context(*, repo_root: Path, pr_number: int) -> PrReviewContextResult:
    """The ``--pr <n>`` arm: an arbitrary PR, plan-ref-free (no plan exists, so ``plan_body`` is
    None). The ``get_pr`` pre-check supplies existence (the clean ``pr_not_found`` arm — a 404
    inside ``get_pr_review_context`` would raise a generic ``GitHubError``) and the head branch
    name (REST ``head.ref``; correct even for fork PRs)."""
    pr = github.get_pr(number=pr_number, repo_root=repo_root)
    if pr is None:
        raise UserFacingCliError(
            f"PR #{pr_number} not found\nCheck the number (gh pr list shows open PRs).",
            error_type="pr_not_found",
        )
    context = github.get_pr_review_context(
        pr_number=pr_number, branch=pr.head_ref, repo_root=repo_root, plan_body=None
    )
    return PrReviewContextResult(context=context, branch=pr.head_ref)


def _resolve_plan_body(repo_root: Path, plan_ref: plan.PlanRef) -> str | None:
    """Resolve the plan body backend-neutrally (mirrors ``materialize_plan_body``): the worktree
    cache mirror first, else fetch via the resolved issue backend (GitHub numeric ids, Linear
    ``ENG-123`` — the resolver owns the id shape). ``None`` when neither is available."""
    mirror = cache.plan_body_path(repo_root)  # primary: the worktree mirror (backend-neutral)
    if mirror.is_file():
        try:
            text = mirror.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        if text:
            return text
    pr_id = plan_ref.pr_id.strip()  # fallback: fetch via the resolver (BOTH)
    if not pr_id:
        return None
    try:
        return resolve.resolve_issue_backend(repo_root).get_plan_body(issue_id=pr_id)
    except (GitHubError, IssueBackendError):
        return None


class PrReviewContextOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrReviewContextResult`
    (flat; field order load-bearing). ``pr`` maps from the domain ``pr_number``."""

    success: bool
    error_type: str | None
    message: str | None
    branch: str
    pr: int
    base_ref: str
    head_ref: str
    title: str
    body: str
    diff: str
    plan_body: str | None

    @classmethod
    def from_domain(cls, result: PrReviewContextResult) -> "PrReviewContextOut":
        c = result.context
        return cls(
            success=True,
            error_type=None,
            message=None,
            branch=result.branch,
            pr=c.pr_number,
            base_ref=c.base_ref,
            head_ref=c.head_ref,
            title=c.title,
            body=c.body,
            diff=c.diff,
            plan_body=c.plan_body,
        )


def _result_to_dict(result: PrReviewContextResult) -> dict[str, object]:
    return PrReviewContextOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrReviewContextResult) -> None:
    c = result.context
    user_output(
        click.style("PR review context ", fg="cyan")
        + f"#{c.pr_number} ({result.branch}): "
        + f"{len(c.diff)} diff byte(s), "
        + ("plan body present" if c.plan_body else "no plan body")
    )
