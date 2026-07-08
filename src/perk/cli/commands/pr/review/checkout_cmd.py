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
from perk.cli.commands.pr.review.shared import (
    remove_review_worktree,
    review_temp_ref,
    review_worktree_name,
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
class ReviewCheckoutResult:
    path: Path
    pr_number: int
    url: str
    head_sha: str
    base_sha: str
    base_ref: str
    state: str  # feeds the human-render non-OPEN note only


@click.command("checkout")
@click.option("--pr", "pr_number", type=int, required=True, help="The PR number to check out.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def checkout_review(ctx: click.Context, *, pr_number: int, as_json: bool) -> None:
    """Create a detached review checkout of PR head at <worktree_root>/review-<n>.

    \b
    Refreshes an existing checkout to the current head and reaps stale
    review-<n> siblings. Never runs [worktree] setup, never installs
    anything — the head is untrusted foreign code.
    """
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        result = _impl(repo_root=repo_root, worktree_root=config.worktree_root, pr_number=pr_number)
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


def _result_to_dict(result: ReviewCheckoutResult) -> dict[str, object]:
    return PrReviewCheckoutOut.from_domain(result).model_dump(mode="json")


def _render_human(result: ReviewCheckoutResult) -> None:
    user_output(
        click.style("✓ ", fg="green") + f"review checkout #{result.pr_number} → {result.path}"
    )
    user_output(f"  head {result.head_sha[:8]} · base {result.base_sha[:8]} ← {result.base_ref}")
    if result.state != "OPEN":
        user_output(f"  note: PR is {result.state}")
