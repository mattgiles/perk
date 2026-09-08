"""`perk pr review-context` — the read-only PR-review context fetch.

Flagless, resolves the active plan's PR (from the local `cache.plan-ref`, exactly as `pr feedback`
does); `--expected-pr <n>` keeps that active-plan path but fails if the branch-selected PR changed;
with `--pr <n>`, resolves an arbitrary PR by number, plan-ref-free (the review doors' foreign-PR
mode — the top-level `plan_body` is null on that single-PR arm). With `--pr <n> --stack` it
gathers the whole stack containing that PR — per-member sections plus the combined base→top
diff — and each member whose head is a plan branch (`plan-<id>`) IS enriched with its plan body
(the resolver-fallback fetch; non-plan members carry null). Either way it gathers everything a
fresh-context reviewer child needs (the diff, the PR title/body, and the plan body where one
exists) and emits `--json`. Read-only — no GitHub mutation; the payload is consumed by the
spawned reviewer child so it never transits the parent session.

The `--json` payload is a POINTER envelope: every free-text section (`body`, `diff`,
`plan_body`, each `stack[]` member's sections, `combined_diff`) is written to its own
line-oriented file under the invocation checkout's run scratch dir —
`cache.run_scratch_dir(root, $PERK_RUN_ID or a minted run id)` +
`/review-context/pr-<n>[-stack]-<token>/` (gitignored, per-invocation unique, pruned by the
run-dir age GC) — and the envelope carries `{path, bytes, lines, max_line_bytes}` references plus
`context_dir`. The reviewer pages the files with `read`/`grep`; a line above Pi's per-line `read`
bound is announced by `max_line_bytes` so the child falls back to
`sed -n 'Np' <path> | tail -c +<offset> | head -c` byte slices. Inlining the text would put a
multi-hundred-KB single line on stdout that no reviewer tool can consume. A filesystem or encoding
failure while writing is `write_failed`.

Diff provenance: every per-PR `diff` is GitHub's diff media type by default; on GitHub's 406
`too_large` refusal (above 20,000 lines / 300 files) the gateway renders it locally (a fetch +
merge-base diff), and `--local` forces that on every arm (the single-PR `diff` and each `--stack`
member `diff`; PR title/body/base/head stay GitHub reads). Each `diff_source`
(`"github"` | `"local-git"`) describes exactly the `diff` beside it — the top-level field the
top-level `diff`, each `stack[]` member's its own `diff`. `combined_diff` is ALWAYS a local
merge-base rendering (the stack arm fetches and diffs locally by construction) and carries no
provenance field.

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / no plan / no PR / op failure · 2 not-a-repo.
"""

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import click

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.boundary import OutputModel
from perk.cli.commands.pr.review.context_files import (
    MaterializedContext,
    MaterializedSections,
    TextFileRef,
    context_dir_for,
    materialize_review_context,
)
from perk.cli.commands.pr.review.stack_resolve import ResolvedStack, resolve_stack_from_pr
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.state import run_id as run_id_mod
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
    diff_source: github.DiffSource = "github"


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
    help="Resolve an arbitrary PR by number, plan-ref-free (top-level plan_body is null; "
    "with --stack, plan-branch members are still enriched per member).",
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
@click.option(
    "--local",
    "local_diff",
    is_flag=True,
    help="Render the diff locally (git fetch + merge-base diff) instead of GitHub's diff media "
    "type; automatic on GitHub's 20,000-line/300-file 406.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def review_context_pr(
    ctx: click.Context,
    *,
    pr_number: int | None,
    expected_pr: int | None,
    stack_mode: bool,
    local_diff: bool,
    as_json: bool,
) -> None:
    """Fetch a PR's review context (read-only; a fresh-context reviewer child runs this).

    \b
    Flagless (or --expected-pr N): the active plan's PR — run from inside
    the plan's worktree (it reads the local cache.plan-ref). With --pr N:
    an arbitrary PR by number, plan-ref-free (plan_body is null). With
    --pr N --stack: the whole PR stack containing N — per-member sections
    plus the combined base→top diff, plan-branch members enriched with
    their plan bodies. --local renders every diff locally (composes
    with every arm).
    """
    try:
        repo_root = require_repo(ctx)
        result = _impl(
            repo_root=repo_root,
            pr_number=pr_number,
            expected_pr=expected_pr,
            stack_mode=stack_mode,
            local_diff=local_diff,
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

    # The files land in the INVOCATION checkout's run scratch dir (never the CWD or a system
    # tempdir): gitignored, reachable by the reviewer children (they run in the caller
    # checkout), and pruned by the run-dir age rule — the live run is protected via PERK_RUN_ID.
    effective_run_id = os.environ.get("PERK_RUN_ID") or run_id_mod.mint()
    context_dir = context_dir_for(
        repo_root,
        pr_number=result.context.pr_number,
        stack=bool(result.stack),
        run_id=effective_run_id,
    )
    try:
        materialized = materialize_review_context(
            context_dir,
            top=result.context,
            members=result.stack,
            combined_diff=result.combined_diff,
        )
    except (OSError, UnicodeError) as exc:
        # Exactly the writer's documented failure set: the filesystem arms and the
        # UnicodeEncodeError even UTF-8 raises for unencodable text (lone surrogates).
        fail(
            ctx,
            as_json=as_json,
            error_type="write_failed",
            message=f"could not write the review context files under {context_dir}\n{exc}",
        )
        return

    emit(
        as_json=as_json,
        payload=_result_to_dict(result, materialized),
        render=lambda: _render_human(result, materialized),
    )


def _impl(
    *,
    repo_root: Path,
    pr_number: int | None,
    expected_pr: int | None,
    stack_mode: bool = False,
    local_diff: bool = False,
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
        return _stack_context(repo_root=repo_root, pr_number=pr_number, local_diff=local_diff)
    if pr_number is not None:
        return _foreign_pr_context(repo_root=repo_root, pr_number=pr_number, local_diff=local_diff)
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
        local_diff=local_diff,
    )
    return PrReviewContextResult(context=context, branch=branch)


def _foreign_pr_context(
    *, repo_root: Path, pr_number: int, local_diff: bool
) -> PrReviewContextResult:
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
        pr_number=pr_number,
        branch=pr.head_ref,
        repo_root=repo_root,
        plan_body=None,
        local_diff=local_diff,
    )
    return PrReviewContextResult(context=context, branch=pr.head_ref)


def _stack_context(*, repo_root: Path, pr_number: int, local_diff: bool) -> PrReviewContextResult:
    """The ``--stack`` arm: resolve the chain containing ``pr_number`` (a perk train IS a
    base-ref chain, so the same cardinality/fork gates apply and children refuse consistently
    with the doors), gather one per-member section per PR, and render the combined diff from
    a local fetch (the same refspec build as checkout — idempotent).

    The existing top-level fields keep describing the TOP PR (the stack arm is foreign-style,
    so top-level ``plan_body`` mirrors the top member's enrichment). Each member's
    ``diff_source`` describes that member's ``diff`` (``local_diff`` forces every one local);
    ``combined_diff`` is always rendered locally and carries no provenance field.
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
            diff_source=context.diff_source,
        )
        for member, context in (
            (
                member,
                github.get_pr_review_context(
                    pr_number=member.pr_number,
                    branch=member.head_ref,
                    repo_root=repo_root,
                    plan_body=None,
                    local_diff=local_diff,
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
        diff_source=top.diff_source,
    )
    return PrReviewContextResult(
        context=top_context,
        branch=top.head_ref,
        stack=members,
        combined_diff=combined_diff,
    )


def _combined_diff(repo_root: Path, stack: ResolvedStack) -> str:
    """Fetch the member heads + the stack base into a PER-INVOCATION temp-ref namespace and
    render the combined base→top diff locally, after re-validating the commit topology
    fail-closed.

    The private namespace matters: concurrent reviewer lanes all run this worker, and
    worktrees share ONE ref store — a shared temp-ref name would let one lane delete or
    clobber another's ref mid-read (nondeterministic ``git_error`` lane losses). The base
    branch is fetched into the same namespace (never ``refs/remotes/origin/…``), so parallel
    invocations touch no shared ref at all. The topology gate repeats the checkout worker's
    rule because this worker is independently callable and a layer force-pushed after
    checkout must not silently vanish from a "combined" diff. The namespace is deleted in a
    ``finally`` (best-effort, like the checkout discipline)."""
    namespace = f"refs/perk/review-ctx/{uuid.uuid4().hex[:12]}"

    def ctx_ref(name: str) -> str:
        return f"{namespace}/{name}"

    refspecs = [
        f"+refs/pull/{member.pr_number}/head:{ctx_ref(str(member.pr_number))}"
        for member in stack.members
    ]
    refspecs.append(f"+refs/heads/{stack.base_ref}:{ctx_ref('base')}")
    try:
        git.fetch_refspecs(repo_root, refspecs)
    except GitError as exc:
        raise UserFacingCliError(
            f"git fetch failed for the stack member heads and base branch "
            f"{stack.base_ref!r}\n{exc}",
            error_type="git_error",
        ) from exc
    try:
        head_shas: list[str] = []
        for member in stack.members:
            sha = git.resolve_commit(repo_root, ctx_ref(str(member.pr_number)))
            if sha is None:
                raise UserFacingCliError(
                    f"fetched PR head ref {ctx_ref(str(member.pr_number))} did not resolve "
                    "to a commit",
                    error_type="git_error",
                )
            head_shas.append(sha)
        # The checkout worker's fail-closed topology gate, repeated at THIS read: every
        # predecessor head must be an ancestor of its successor head, and an indeterminate
        # probe refuses too — otherwise a broken stack would render a "combined" diff that
        # silently omits layers.
        for index in range(1, len(stack.members)):
            pred, succ = stack.members[index - 1], stack.members[index]
            verdict = git.is_ancestor(repo_root, head_shas[index - 1], head_shas[index])
            if verdict is not True:
                detail = (
                    "is not an ancestor of" if verdict is False else "ancestry indeterminate for"
                )
                raise UserFacingCliError(
                    f"stack topology broken: PR #{pred.pr_number} head "
                    f"{head_shas[index - 1][:12]} {detail} PR #{succ.pr_number} head "
                    f"{head_shas[index][:12]} — the combined diff would not contain every "
                    "layer (sync the stack first).",
                    error_type="stack_topology_broken",
                )
        base_sha = git.merge_base(repo_root, ctx_ref("base"), head_shas[-1])
        if base_sha is None:
            raise UserFacingCliError(
                f"the stack top (PR #{stack.top.pr_number}) has no common ancestor with base "
                f"branch {stack.base_ref!r}",
                error_type="git_error",
            )
        try:
            return git.diff_range(repo_root, base_sha, head_shas[-1])
        except GitError as exc:
            raise UserFacingCliError(
                f"git diff failed for the combined stack diff\n{exc}", error_type="git_error"
            ) from exc
    finally:
        for name in [str(member.pr_number) for member in stack.members] + ["base"]:
            try:
                git.delete_ref(repo_root, ctx_ref(name))
            except GitError as exc:
                log_warn(f"could not delete temp ref {ctx_ref(name)}: {exc}")


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


class TextFileRefOut(OutputModel):
    """One materialized text section: its absolute ``path`` plus the sizes a reviewer pages
    against — ``max_line_bytes`` is the longest line's UTF-8 length (compared against Pi's
    per-line ``read`` bound to pick the byte-slice fallback)."""

    path: str
    bytes: int
    lines: int
    max_line_bytes: int

    @classmethod
    def from_domain(cls, ref: TextFileRef) -> "TextFileRefOut":
        return cls(
            path=str(ref.path),
            bytes=ref.bytes,
            lines=ref.lines,
            max_line_bytes=ref.max_line_bytes,
        )


def _optional_ref(ref: TextFileRef | None) -> TextFileRefOut | None:
    return None if ref is None else TextFileRefOut.from_domain(ref)


class PrReviewContextOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrReviewContextResult` — a pointer
    envelope (field order load-bearing). ``pr`` maps from the domain ``pr_number``; ``body``,
    ``diff`` and ``plan_body`` are file references into ``context_dir`` (in stack mode they
    alias the LAST ``stack[]`` member's files — the top PR's text is written once)."""

    success: bool
    error_type: str | None
    message: str | None
    branch: str
    pr: int
    base_ref: str
    head_ref: str
    title: str
    context_dir: str
    body: TextFileRefOut
    diff: TextFileRefOut
    plan_body: TextFileRefOut | None
    diff_source: github.DiffSource

    @classmethod
    def from_domain(
        cls, result: PrReviewContextResult, materialized: MaterializedContext
    ) -> "PrReviewContextOut":
        c = result.context
        top = materialized.top
        return cls(
            success=True,
            error_type=None,
            message=None,
            branch=result.branch,
            pr=c.pr_number,
            base_ref=c.base_ref,
            head_ref=c.head_ref,
            title=c.title,
            context_dir=str(materialized.context_dir),
            body=TextFileRefOut.from_domain(top.body),
            diff=TextFileRefOut.from_domain(top.diff),
            plan_body=_optional_ref(top.plan_body),
            diff_source=c.diff_source,
        )


class StackContextMemberOut(OutputModel):
    """One ``stack[]`` per-member section (bottom→top order); text fields are file references
    under ``context_dir/stack/<pr>/``."""

    pr: int
    base_ref: str
    head_ref: str
    title: str
    body: TextFileRefOut
    diff: TextFileRefOut
    plan_body: TextFileRefOut | None
    diff_source: github.DiffSource

    @classmethod
    def from_domain(
        cls, member: StackContextMember, sections: MaterializedSections
    ) -> "StackContextMemberOut":
        return cls(
            pr=member.pr_number,
            base_ref=member.base_ref,
            head_ref=member.head_ref,
            title=member.title,
            body=TextFileRefOut.from_domain(sections.body),
            diff=TextFileRefOut.from_domain(sections.diff),
            plan_body=_optional_ref(sections.plan_body),
            diff_source=member.diff_source,
        )


class PrReviewStackContextOut(PrReviewContextOut):
    """The ``--stack`` envelope: the single-PR fields (describing the top PR) plus the
    additive per-member sections and the combined-diff reference. A separate model so
    non-stack calls stay byte-identical (no null stack keys)."""

    stack: tuple[StackContextMemberOut, ...]
    combined_diff: TextFileRefOut

    @classmethod
    def from_stack_domain(
        cls, result: PrReviewContextResult, materialized: MaterializedContext
    ) -> "PrReviewStackContextOut":
        if materialized.combined_diff is None:
            raise ValueError("the --stack envelope requires a materialized combined diff")
        base = PrReviewContextOut.from_domain(result, materialized)
        return cls(
            **base.model_dump(),
            stack=tuple(
                StackContextMemberOut.from_domain(member, sections)
                for member, sections in zip(result.stack, materialized.members, strict=True)
            ),
            combined_diff=TextFileRefOut.from_domain(materialized.combined_diff),
        )


def _result_to_dict(
    result: PrReviewContextResult, materialized: MaterializedContext
) -> dict[str, object]:
    if result.stack:
        return PrReviewStackContextOut.from_stack_domain(result, materialized).model_dump(
            mode="json"
        )
    return PrReviewContextOut.from_domain(result, materialized).model_dump(mode="json")


def _render_human(result: PrReviewContextResult, materialized: MaterializedContext) -> None:
    c = result.context
    user_output(
        click.style("PR review context ", fg="cyan")
        + f"#{c.pr_number} ({result.branch}): "
        + f"{materialized.top.diff.bytes} diff byte(s), "
        + ("plan body present" if c.plan_body else "no plan body")
        + f", diff via {c.diff_source}"
    )
    user_output(f"  context: {materialized.context_dir}")
    if result.stack:
        combined = materialized.combined_diff
        user_output(
            f"  stack: {len(result.stack)} member(s), "
            f"{0 if combined is None else combined.bytes} combined-diff byte(s)"
        )
