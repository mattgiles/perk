"""`perk pr review checkout` — an ephemeral, detached checkout of a PR's head.

Materializes ``<worktree_root>/review-<n>`` at the PR head *as of now* (an existing checkout is
force-refreshed — no reuse arm, no dirty protection: the checkout is disposable investigation
material by construction). Any PR state (OPEN/MERGED/CLOSED) is checkout-able — read-only
investigation is legitimate on all; a non-OPEN state only earns a stderr note.

The head is **untrusted foreign code**: the checkout is read-only investigation material —
`[worktree] setup` is **never** run and nothing from the head is ever executed (a foreign
``package.json``'s install scripts are arbitrary code execution).

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / op failure · 2 not-a-repo.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from perk import github
from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.shared import resolve_objective_id
from perk.cli.commands.pr.review.shared import (
    remove_review_worktree,
    review_temp_ref,
    review_worktree_name,
)
from perk.cli.commands.pr.review.stack_resolve import (
    ResolvedStack,
    resolve_stack_from_objective,
    resolve_stack_from_pr,
)
from perk.cli.context import require_config, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.substrate import git
from perk.substrate.git import GitError
from perk.substrate.output import log_warn, user_output

# Stale review checkouts (any review-<n> other than the target) older than this are reaped by
# the checkout-path gc backstop. A module constant — a `[gc]` config table is deliberately
# deferred (mirrors state/gc.py's DEFAULT_MAX_AGE_DAYS posture).
_REVIEW_STALE_AFTER_DAYS = 7

_REVIEW_NAME_RE = re.compile(r"^review-(\d+)$")


@dataclass(frozen=True)
class StackCheckoutMember:
    """One pinned member of the stack-checkout snapshot (bottom→top order in the envelope)."""

    pr_number: int
    url: str
    branch: str
    head_sha: str
    base_ref: str
    node_id: str | None
    plan_id: str | None


@dataclass(frozen=True)
class ReviewCheckoutResult:
    path: Path
    pr_number: int
    url: str
    head_sha: str
    base_sha: str
    base_ref: str
    state: str  # feeds the human-render non-OPEN note only
    # Trailing defaulted growth — the `--stack` arm's pinned snapshot: `stack` is the ordered
    # member table (empty for non-stack calls, whose envelope stays byte-compatible) and
    # `stack_notes` the report-only notes carrier (resolution warnings + checkout drift
    # observations) both entry paths render from. On the stack arm `base_ref`/`base_sha` ARE
    # the combined-diff base — no separate stack-base field.
    stack: tuple[StackCheckoutMember, ...] = ()
    stack_notes: tuple[str, ...] = ()


@click.command("checkout")
@click.option("--pr", "pr_number", type=int, default=None, help="The PR number to check out.")
@click.option(
    "--stack",
    "stack_mode",
    is_flag=True,
    help="Check out the whole PR stack (top head; combined base) — with --pr (chain walk) "
    "or --objective (delivery train).",
)
@click.option(
    "--objective",
    "objective_id",
    default=None,
    help="Resolve the stack from this objective's delivery train (requires --stack).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def checkout_review(
    ctx: click.Context,
    *,
    pr_number: int | None,
    stack_mode: bool,
    objective_id: str | None,
    as_json: bool,
) -> None:
    """Create a detached review checkout of PR head at <worktree_root>/review-<n>.

    \b
    Refreshes an existing checkout to the current head and reaps stale
    review-<n> siblings. Never runs [worktree] setup, never installs
    anything — the head is untrusted foreign code. With --stack, resolves
    the whole PR stack (from --pr via the base-ref chain walk, or from
    --objective via the delivery train), fetches every member head, and
    checks out the TOP head at review-<top> so the combined base→top diff
    covers every layer.
    """
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        result = _dispatch(
            repo_root=repo_root,
            worktree_root=config.worktree_root,
            pr_number=pr_number,
            stack_mode=stack_mode,
            objective_id=objective_id,
        )
    except GitHubError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"PR review checkout failed\n{exc}",
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


def _dispatch(
    *,
    repo_root: Path,
    worktree_root: Path,
    pr_number: int | None,
    stack_mode: bool,
    objective_id: str | None,
) -> ReviewCheckoutResult:
    """Route the flag combinations: the non-stack arm is byte-identical to the original
    single-PR checkout; the stack arm resolves wire facts first, then hydrates."""
    if not stack_mode:
        if objective_id is not None:
            raise UserFacingCliError("--objective requires --stack", error_type="invalid_input")
        if pr_number is None:
            raise UserFacingCliError("--pr is required", error_type="invalid_input")
        return _impl(repo_root=repo_root, worktree_root=worktree_root, pr_number=pr_number)
    if pr_number is not None and objective_id is not None:
        raise UserFacingCliError(
            "--pr and --objective are mutually exclusive under --stack",
            error_type="invalid_input",
        )
    if pr_number is not None:
        stack = resolve_stack_from_pr(repo_root, pr_number)
    else:
        # Bare `--stack` resolves the objective from the worktree's plan-ref (the
        # `cache.plan-ref` arm); no linked objective is the typed `no_objective` refusal.
        stack = resolve_stack_from_objective(
            repo_root, resolve_objective_id(repo_root, objective_id)
        )
    return stack_checkout(repo_root=repo_root, worktree_root=worktree_root, stack=stack)


def _impl(*, repo_root: Path, worktree_root: Path, pr_number: int) -> ReviewCheckoutResult:
    pr = github.get_pr(number=pr_number, repo_root=repo_root)
    if pr is None:
        raise UserFacingCliError(
            f"PR #{pr_number} not found\nCheck the number (gh pr list shows open PRs).",
            error_type="pr_not_found",
        )
    if not pr.base_ref:
        raise UserFacingCliError(
            f"PR #{pr_number} carries no base branch\n"
            "The GitHub payload is missing base.ref — retry, or report a bug.",
            error_type="github_error",
        )

    name = review_worktree_name(pr_number)
    path = worktree_root / name
    _reap_stale(repo_root, worktree_root, skip=name)

    # One network round-trip covers both refs: the forcing refspec pins the PR head into the
    # temp ref (FETCH_HEAD is clobber-racy), and the bare base branch also updates
    # refs/remotes/origin/<base> (the merge-base input).
    tmp_ref = review_temp_ref(pr_number)
    try:
        git.fetch_refspecs(repo_root, [f"+refs/pull/{pr_number}/head:{tmp_ref}", pr.base_ref])
    except GitError as exc:
        raise UserFacingCliError(
            f"git fetch failed for refs/pull/{pr_number}/head and base branch "
            f"{pr.base_ref!r}\n{exc}",
            error_type="git_error",
        ) from exc

    head_sha = git.resolve_commit(repo_root, tmp_ref)
    if head_sha is None:
        raise UserFacingCliError(
            f"fetched PR head ref {tmp_ref} did not resolve to a commit",
            error_type="git_error",
        )
    # The 3-dot diff base: GitHub's PR diff (and `gh pr diff`) is the merge-base diff, so
    # base_sha must be the local merge-base — NOT REST base.sha.
    base_sha = git.merge_base(repo_root, f"origin/{pr.base_ref}", head_sha)
    if base_sha is None:
        raise UserFacingCliError(
            f"PR #{pr_number} head has no common ancestor with base branch {pr.base_ref!r}",
            error_type="git_error",
        )

    # Refresh: the door's contract is "a detached checkout of the PR head as of now". Ordering
    # is load-bearing — a failed fetch above leaves an existing checkout untouched. OSError is
    # the removal helper's unregistered-leftover (rmtree) arm.
    try:
        if remove_review_worktree(repo_root, path):
            user_output(f"refreshing review worktree {name}")
    except (GitError, OSError) as exc:
        raise UserFacingCliError(
            f"could not remove existing review worktree {path}\n{exc}", error_type="git_error"
        ) from exc

    try:
        git.worktree_add_detached(repo_root, path, head_sha)
    except GitError as exc:
        raise UserFacingCliError(
            f"git worktree add failed for {path}\n{exc}", error_type="git_error"
        ) from exc

    # Best-effort temp-ref delete: the detached worktree HEAD keeps the commit alive against
    # git gc, and the ref is force-overwritten on the next checkout anyway.
    try:
        git.delete_ref(repo_root, tmp_ref)
    except GitError as exc:
        log_warn(f"could not delete temp ref {tmp_ref}: {exc}")

    # Invariant: NO run_worktree_setup call anywhere on this path — the head is untrusted
    # foreign code and the checkout is read-only investigation material.
    return ReviewCheckoutResult(
        path=path,
        pr_number=pr_number,
        url=pr.url,
        head_sha=head_sha,
        base_sha=base_sha,
        base_ref=pr.base_ref,
        state=pr.state,
    )


def stack_checkout(
    *, repo_root: Path, worktree_root: Path, stack: ResolvedStack
) -> ReviewCheckoutResult:
    """The ``--stack`` hydration boundary: one fetch pins every member head + the stack base,
    the commit topology is validated fail-closed BEFORE any worktree mutation, and the
    existing single-PR tail is reused verbatim at the **top** head (same ``review-<top>``
    name, so ``perk pr review cleanup --pr <top>`` works unchanged).

    The returned envelope is the pinned snapshot every downstream consumer (guidance,
    handoff, posting narrative) reads — nothing downstream re-resolves moving refs. Exported
    (not ``_``-private): ``perk objective stack review`` runs the same implementation.
    """
    top = stack.top
    name = review_worktree_name(top.pr_number)
    path = worktree_root / name
    _reap_stale(repo_root, worktree_root, skip=name)

    # ONE network round-trip pins every member head into its temp ref and updates
    # refs/remotes/origin/<stack base> (the combined merge-base input).
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

    head_shas: list[str] = []
    for member in stack.members:
        sha = git.resolve_commit(repo_root, review_temp_ref(member.pr_number))
        if sha is None:
            raise UserFacingCliError(
                f"fetched PR head ref {review_temp_ref(member.pr_number)} did not resolve to "
                "a commit",
                error_type="git_error",
            )
        head_shas.append(sha)

    # Post-fetch commit-topology validation, fail closed BEFORE any worktree mutation:
    # ref-name linkage alone does not prove the base→top diff contains every layer — every
    # predecessor head must be an ancestor of its successor head, and an indeterminate probe
    # (None) refuses too.
    for index in range(1, len(stack.members)):
        pred, succ = stack.members[index - 1], stack.members[index]
        verdict = git.is_ancestor(repo_root, head_shas[index - 1], head_shas[index])
        if verdict is not True:
            detail = "is not an ancestor of" if verdict is False else "ancestry indeterminate for"
            raise UserFacingCliError(
                f"stack topology broken: PR #{pred.pr_number} head "
                f"{head_shas[index - 1][:12]} {detail} PR #{succ.pr_number} head "
                f"{head_shas[index][:12]} — the combined diff would not contain every layer "
                "(sync the stack first).",
                error_type="stack_topology_broken",
            )

    base_sha = git.merge_base(repo_root, f"origin/{stack.base_ref}", head_shas[-1])
    if base_sha is None:
        raise UserFacingCliError(
            f"the stack top (PR #{top.pr_number}) has no common ancestor with base branch "
            f"{stack.base_ref!r}",
            error_type="git_error",
        )

    # Objective-arm drift corroboration: warn, never refuse — the topology gate above is the
    # safety boundary; a recorded-vs-observed head mismatch is report-only.
    notes = list(stack.notes)
    for member, sha in zip(stack.members, head_shas, strict=True):
        if member.recorded_head_sha is not None and member.recorded_head_sha != sha:
            notes.append(
                f"drift: PR #{member.pr_number} head {sha[:12]} != recorded published head "
                f"{member.recorded_head_sha[:12]}"
            )

    # The existing single-PR tail, verbatim, at the TOP head.
    try:
        if remove_review_worktree(repo_root, path):
            user_output(f"refreshing review worktree {name}")
    except (GitError, OSError) as exc:
        raise UserFacingCliError(
            f"could not remove existing review worktree {path}\n{exc}", error_type="git_error"
        ) from exc

    try:
        git.worktree_add_detached(repo_root, path, head_shas[-1])
    except GitError as exc:
        raise UserFacingCliError(
            f"git worktree add failed for {path}\n{exc}", error_type="git_error"
        ) from exc

    for member in stack.members:
        try:
            git.delete_ref(repo_root, review_temp_ref(member.pr_number))
        except GitError as exc:
            log_warn(f"could not delete temp ref {review_temp_ref(member.pr_number)}: {exc}")

    # Invariant: NO run_worktree_setup call anywhere on this path either — the heads are
    # untrusted foreign code and the checkout is read-only investigation material.
    return ReviewCheckoutResult(
        path=path,
        pr_number=top.pr_number,
        url=top.url,
        head_sha=head_shas[-1],
        base_sha=base_sha,
        # The combined-diff base: base_ref/base_sha stay a coherent pair (the top PR's own
        # base branch is a member head, not the diff base).
        base_ref=stack.base_ref,
        state="OPEN",  # every member is OPEN by resolution
        stack=tuple(
            StackCheckoutMember(
                pr_number=member.pr_number,
                url=member.url,
                branch=member.head_ref,
                head_sha=sha,
                base_ref=member.base_ref,
                node_id=member.node_id,
                plan_id=member.plan_id,
            )
            for member, sha in zip(stack.members, head_shas, strict=True)
        ),
        stack_notes=tuple(notes),
    )


def _stale_review_worktrees(
    worktrees: list[git.Worktree],
    worktree_root: Path,
    *,
    skip: str,
    now: datetime,
) -> list[git.Worktree]:
    """The stale review checkouts among ``worktrees`` (pure classification, injectable ``now``).

    A candidate lives directly under ``worktree_root`` (``.resolve()`` on BOTH sides — macOS
    ``/var``→``/private/var``), matches ``^review-(\\d+)$``, and is not ``skip`` (the target).
    Stale iff its ``.git`` gitlink mtime — written once at creation — is older than
    ``_REVIEW_STALE_AFTER_DAYS``; a **missing** gitlink counts as stale (broken residue).
    """
    root = worktree_root.resolve()
    cutoff = now - timedelta(days=_REVIEW_STALE_AFTER_DAYS)
    stale: list[git.Worktree] = []
    for wt in worktrees:
        name = wt.path.name
        if wt.path.parent.resolve() != root or not _REVIEW_NAME_RE.match(name) or name == skip:
            continue
        gitlink = wt.path / ".git"
        if not gitlink.exists():
            stale.append(wt)
            continue
        mtime = datetime.fromtimestamp(gitlink.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            stale.append(wt)
    return stale


def _reap_stale(
    repo_root: Path, worktree_root: Path, *, skip: str, now: datetime | None = None
) -> None:
    """The gc backstop: reap stale ``review-<n>`` checkouts before creating the target's.

    Lives on the checkout path (not doctor — the ``cache-gc`` precedent keeps doctor
    report-only). Per-item failures warn + continue, never crash.
    """
    now = now or datetime.now(UTC)
    for wt in _stale_review_worktrees(
        git.worktree_list(repo_root), worktree_root, skip=skip, now=now
    ):
        try:
            remove_review_worktree(repo_root, wt.path)
        except (GitError, OSError) as exc:
            log_warn(f"could not reap stale review worktree {wt.path.name}: {exc}")
            continue
        user_output(f"reaped stale review worktree {wt.path.name}")


class PrReviewCheckoutOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`ReviewCheckoutResult` (flat; envelope
    keys first). ``path`` is absolute; the SHAs are full 40-char."""

    success: bool
    error_type: str | None
    message: str | None
    path: str
    pr: int
    url: str
    head_sha: str
    base_sha: str
    base_ref: str

    @classmethod
    def from_domain(cls, result: ReviewCheckoutResult) -> "PrReviewCheckoutOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            path=str(result.path),
            pr=result.pr_number,
            url=result.url,
            head_sha=result.head_sha,
            base_sha=result.base_sha,
            base_ref=result.base_ref,
        )


class StackMemberOut(OutputModel):
    """One `stack[]` snapshot row (bottom→top order)."""

    pr: int
    url: str
    branch: str
    head_sha: str
    base_ref: str
    node_id: str | None
    plan_id: str | None

    @classmethod
    def from_domain(cls, member: StackCheckoutMember) -> "StackMemberOut":
        return cls(
            pr=member.pr_number,
            url=member.url,
            branch=member.branch,
            head_sha=member.head_sha,
            base_ref=member.base_ref,
            node_id=member.node_id,
            plan_id=member.plan_id,
        )


class PrReviewStackCheckoutOut(PrReviewCheckoutOut):
    """The ``--stack`` envelope: the single-PR fields (describing the top PR + the combined
    base) plus the additive pinned snapshot. A separate model so non-stack calls stay
    byte-compatible (no null stack keys)."""

    stack: tuple[StackMemberOut, ...]
    stack_notes: tuple[str, ...]

    @classmethod
    def from_stack_domain(cls, result: ReviewCheckoutResult) -> "PrReviewStackCheckoutOut":
        base = PrReviewCheckoutOut.from_domain(result)
        return cls(
            **base.model_dump(),
            stack=tuple(StackMemberOut.from_domain(m) for m in result.stack),
            stack_notes=result.stack_notes,
        )


def _result_to_dict(result: ReviewCheckoutResult) -> dict[str, object]:
    if result.stack:
        return PrReviewStackCheckoutOut.from_stack_domain(result).model_dump(mode="json")
    return PrReviewCheckoutOut.from_domain(result).model_dump(mode="json")


def _render_human(result: ReviewCheckoutResult) -> None:
    user_output(
        click.style("✓ ", fg="green") + f"review checkout #{result.pr_number} → {result.path}"
    )
    user_output(f"  head {result.head_sha[:8]} · base {result.base_sha[:8]} ← {result.base_ref}")
    if result.state != "OPEN":
        user_output(f"  note: PR is {result.state}")
    if result.stack:
        user_output(f"  stack ({len(result.stack)} member(s), base {result.base_ref}):")
        for member in result.stack:
            user_output(
                f"    #{member.pr_number} {member.branch} ← {member.base_ref} "
                f"({member.head_sha[:8]})"
            )
    for note in result.stack_notes:
        user_output(f"  note: {note}")
