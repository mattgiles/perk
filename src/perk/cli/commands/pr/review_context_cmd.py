"""`perk pr review-context` — the read-only PR-review context fetch.

Flagless, resolves the active plan's PR (from the local `cache.plan-ref`, exactly as `pr feedback`
does); `--expected-pr <n>` keeps that active-plan path but fails if the branch-selected PR changed;
with `--pr <n>`, resolves an arbitrary PR by number, plan-ref-free (the review doors' foreign-PR
mode — no plan exists, so `plan_body` is null). Either way it gathers everything a
fresh-context reviewer child needs (the diff, the PR title/body, and the plan body when one
exists) and emits `--json`. Read-only — no GitHub mutation; the verbose payload is consumed by
the spawned reviewer child so it never transits the parent session.

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / no plan / no PR / op failure · 2 not-a-repo.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import click

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.boundary import OutputModel
from perk.cli.commands.pr.review.shared import review_temp_ref
from perk.cli.commands.pr.review.stack_resolve import ResolvedStack, resolve_stack_from_pr
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate import git
from perk.substrate.git import GitError
from perk.substrate.output import log_warn, user_output

# A stack member whose head branch is a plan branch gets its plan body enriched via the
# resolver-fallback arm (the resolver owns the id shape — GitHub numeric, Linear ENG-123).
_PLAN_BRANCH_RE = re.compile(r"^plan-(.+)$")


@dataclass(frozen=True)
class StackContextMember:
    """One per-member review-context section of the ``--stack`` arm (bottom→top order)."""

    pr_number: int
    base_ref: str
    head_ref: str
    title: str
    body: str
    diff: str
    plan_body: str | None


@dataclass(frozen=True)
class PrReviewContextResult:
    context: github.PrReviewContext
    branch: str
    # Trailing defaulted growth — the ``--stack`` arm: per-member sections (bottom→top) plus
    # the combined base→top diff. Empty/None for non-stack calls (byte-identical envelope).
    stack: tuple[StackContextMember, ...] = ()
    combined_diff: str | None = None


@click.command("review-context")
@click.option(
    "--pr",
    "pr_number",
    type=int,
    default=None,
    help="Resolve an arbitrary PR by number (plan-ref-free; plan_body is null).",
)
@click.option(
    "--expected-pr",
    type=int,
    default=None,
    help="Require the active plan branch to still select this positive PR number.",
)
@click.option(
    "--stack",
    "stack_mode",
    is_flag=True,
    help="Gather the whole PR stack's context (per-member sections + the combined diff); "
    "requires --pr.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def review_context_pr(
    ctx: click.Context,
    *,
    pr_number: int | None,
    expected_pr: int | None,
    stack_mode: bool,
    as_json: bool,
) -> None:
    """Fetch a PR's review context (read-only; a fresh-context reviewer child runs this).

    \b
    Flagless (or --expected-pr N): the active plan's PR — run from inside
    the plan's worktree (it reads the local cache.plan-ref). With --pr N:
    an arbitrary PR by number, plan-ref-free (plan_body is null). With
    --pr N --stack: the whole PR stack containing N — per-member sections
    plus the combined base→top diff.
    """
    try:
        repo_root = require_repo(ctx)
        result = _impl(
            repo_root=repo_root,
            pr_number=pr_number,
            expected_pr=expected_pr,
            stack_mode=stack_mode,
        )
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


def _impl(
    *,
    repo_root: Path,
    pr_number: int | None,
    expected_pr: int | None,
    stack_mode: bool = False,
) -> PrReviewContextResult:
    if stack_mode and expected_pr is not None:
        raise UserFacingCliError(
            "--stack and --expected-pr are mutually exclusive", error_type="invalid_input"
        )
    if stack_mode and pr_number is None:
        raise UserFacingCliError(
            "--stack requires --pr (the stack arm is always top-PR-addressed)",
            error_type="invalid_input",
        )
    if pr_number is not None and expected_pr is not None:
        raise UserFacingCliError(
            "--pr and --expected-pr are mutually exclusive", error_type="invalid_input"
        )
    if expected_pr is not None and expected_pr <= 0:
        raise UserFacingCliError(
            "--expected-pr must be a positive integer", error_type="invalid_input"
        )
    if stack_mode and pr_number is not None:
        return _stack_context(repo_root=repo_root, pr_number=pr_number)
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
    if expected_pr is not None and pr.number != expected_pr:
        raise UserFacingCliError(
            f"Review target changed: expected PR #{expected_pr}, but branch {branch!r} now selects "
            f"PR #{pr.number}\nRerun the review wave against the current PR.",
            error_type="review_target_changed",
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


def _stack_context(*, repo_root: Path, pr_number: int) -> PrReviewContextResult:
    """The ``--stack`` arm: resolve the chain containing ``pr_number`` (a perk train IS a
    base-ref chain, so the same cardinality/fork gates apply and children refuse consistently
    with the doors), gather one per-member section per PR, and render the combined diff from
    a local fetch (the same refspec build as checkout — idempotent).

    The existing top-level fields keep describing the TOP PR (the stack arm is foreign-style,
    so top-level ``plan_body`` mirrors the top member's enrichment).
    """
    stack = resolve_stack_from_pr(repo_root, pr_number)
    members = tuple(
        StackContextMember(
            pr_number=member.pr_number,
            base_ref=context.base_ref,
            head_ref=context.head_ref,
            title=context.title,
            body=context.body,
            diff=context.diff,
            plan_body=_plan_body_for_branch(repo_root, member.head_ref),
        )
        for member, context in (
            (
                member,
                github.get_pr_review_context(
                    pr_number=member.pr_number,
                    branch=member.head_ref,
                    repo_root=repo_root,
                    plan_body=None,
                ),
            )
            for member in stack.members
        )
    )
    combined_diff = _combined_diff(repo_root, stack)
    top = members[-1]
    top_context = github.PrReviewContext(
        pr_number=top.pr_number,
        base_ref=top.base_ref,
        head_ref=top.head_ref,
        title=top.title,
        body=top.body,
        diff=top.diff,
        plan_body=top.plan_body,
    )
    return PrReviewContextResult(
        context=top_context,
        branch=top.head_ref,
        stack=members,
        combined_diff=combined_diff,
    )


def _combined_diff(repo_root: Path, stack: ResolvedStack) -> str:
    """Fetch the member heads + the stack base (the checkout refspec build, idempotent) and
    render the combined base→top diff locally. Temp refs are deleted best-effort after the
    read (the checkout discipline)."""
    refspecs = [
        f"+refs/pull/{member.pr_number}/head:{review_temp_ref(member.pr_number)}"
        for member in stack.members
    ]
    refspecs.append(stack.base_ref)
    try:
        git.fetch_refspecs(repo_root, refspecs)
    except GitError as exc:
        raise UserFacingCliError(
            f"git fetch failed for the stack member heads and base branch "
            f"{stack.base_ref!r}\n{exc}",
            error_type="git_error",
        ) from exc
    top_ref = review_temp_ref(stack.top.pr_number)
    top_sha = git.resolve_commit(repo_root, top_ref)
    if top_sha is None:
        raise UserFacingCliError(
            f"fetched PR head ref {top_ref} did not resolve to a commit", error_type="git_error"
        )
    base_sha = git.merge_base(repo_root, f"origin/{stack.base_ref}", top_sha)
    if base_sha is None:
        raise UserFacingCliError(
            f"the stack top (PR #{stack.top.pr_number}) has no common ancestor with base "
            f"branch {stack.base_ref!r}",
            error_type="git_error",
        )
    try:
        diff = git.diff_range(repo_root, base_sha, top_sha)
    except GitError as exc:
        raise UserFacingCliError(
            f"git diff failed for the combined stack diff\n{exc}", error_type="git_error"
        ) from exc
    for member in stack.members:
        try:
            git.delete_ref(repo_root, review_temp_ref(member.pr_number))
        except GitError as exc:
            log_warn(f"could not delete temp ref {review_temp_ref(member.pr_number)}: {exc}")
    return diff


def _plan_body_for_branch(repo_root: Path, head_ref: str) -> str | None:
    """Enrich a stack member whose head branch is a plan branch (``plan-<id>``) with its plan
    body via the resolver-fallback arm (the id shape is the resolver's concern)."""
    match = _PLAN_BRANCH_RE.match(head_ref)
    if match is None:
        return None
    return _fetch_plan_body(repo_root, match.group(1))


def _fetch_plan_body(repo_root: Path, pr_id: str) -> str | None:
    """The resolver-fallback plan-body fetch shared by the active-plan and stack arms."""
    try:
        return resolve.resolve_issue_backend(repo_root).get_plan_body(issue_id=pr_id)
    except (GitHubError, IssueBackendError):
        return None


def _resolve_plan_body(repo_root: Path, plan_ref: plan.PlanRef) -> str | None:
    """Resolve the plan body backend-neutrally (mirrors ``materialize_plan_body``): the worktree
    snapshot first — offline and fetch-once, so review-context reviews the plan as implemented,
    not whatever the issue says today — else fetch via the resolved issue backend (the fallback
    for a worktree without a snapshot; GitHub numeric ids, Linear ``ENG-123`` — the resolver owns
    the id shape). ``None`` when neither is available."""
    # primary: the worktree snapshot (offline; the plan as implemented)
    mirror = cache.plan_body_path(repo_root)
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
    return _fetch_plan_body(repo_root, pr_id)


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


class StackContextMemberOut(OutputModel):
    """One ``stack[]`` per-member section (bottom→top order)."""

    pr: int
    base_ref: str
    head_ref: str
    title: str
    body: str
    diff: str
    plan_body: str | None

    @classmethod
    def from_domain(cls, member: StackContextMember) -> "StackContextMemberOut":
        return cls(
            pr=member.pr_number,
            base_ref=member.base_ref,
            head_ref=member.head_ref,
            title=member.title,
            body=member.body,
            diff=member.diff,
            plan_body=member.plan_body,
        )


class PrReviewStackContextOut(PrReviewContextOut):
    """The ``--stack`` envelope: the single-PR fields (describing the top PR) plus the
    additive per-member sections and combined diff. A separate model so non-stack calls stay
    byte-identical (no null stack keys)."""

    stack: tuple[StackContextMemberOut, ...]
    combined_diff: str

    @classmethod
    def from_stack_domain(cls, result: PrReviewContextResult) -> "PrReviewStackContextOut":
        base = PrReviewContextOut.from_domain(result)
        return cls(
            **base.model_dump(),
            stack=tuple(StackContextMemberOut.from_domain(m) for m in result.stack),
            combined_diff=result.combined_diff or "",
        )


def _result_to_dict(result: PrReviewContextResult) -> dict[str, object]:
    if result.stack:
        return PrReviewStackContextOut.from_stack_domain(result).model_dump(mode="json")
    return PrReviewContextOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrReviewContextResult) -> None:
    c = result.context
    user_output(
        click.style("PR review context ", fg="cyan")
        + f"#{c.pr_number} ({result.branch}): "
        + f"{len(c.diff)} diff byte(s), "
        + ("plan body present" if c.plan_body else "no plan body")
    )
    if result.stack:
        user_output(
            f"  stack: {len(result.stack)} member(s), "
            f"{len(result.combined_diff or '')} combined-diff byte(s)"
        )
