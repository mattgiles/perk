"""`perk pr review cleanup` — remove a PR's ephemeral review checkout.

Single-PR and idempotent: nothing to remove is success (``removed: false``, exit 0). Fully
offline — no GitHub calls (the worktree name is derived from the number alone). Also deletes a
leftover ``refs/perk/review/<n>`` temp ref best-effort (insurance against an interrupted
checkout).

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 op failure · 2 not-a-repo.
"""

from dataclasses import dataclass
from pathlib import Path

import click

from perk.boundary import OutputModel
from perk.cli.commands.pr.review.shared import (
    remove_review_worktree,
    review_temp_ref,
    review_worktree_name,
)
from perk.cli.context import require_config, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate import git
from perk.substrate.git import GitError
from perk.substrate.output import log_warn, user_output


@dataclass(frozen=True)
class ReviewCleanupResult:
    pr_number: int
    path: Path
    removed: bool


@click.command("cleanup")
@click.option("--pr", "pr_number", type=int, required=True, help="The PR number to clean up.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def cleanup_review(ctx: click.Context, *, pr_number: int, as_json: bool) -> None:
    """Remove the review checkout for PR N (idempotent; nothing to remove is success)."""
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        result = _impl(repo_root=repo_root, worktree_root=config.worktree_root, pr_number=pr_number)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    emit(as_json=as_json, payload=_result_to_dict(result), render=lambda: _render_human(result))


def _impl(*, repo_root: Path, worktree_root: Path, pr_number: int) -> ReviewCleanupResult:
    path = worktree_root / review_worktree_name(pr_number)
    try:
        removed = remove_review_worktree(repo_root, path)
    except GitError as exc:
        raise UserFacingCliError(
            f"could not remove review worktree {path}\n{exc}", error_type="git_error"
        ) from exc
    # Leftover-ref insurance (an interrupted checkout can leave the temp ref behind);
    # best-effort — an absent ref is already a git no-op.
    tmp_ref = review_temp_ref(pr_number)
    try:
        git.delete_ref(repo_root, tmp_ref)
    except GitError as exc:
        log_warn(f"could not delete temp ref {tmp_ref}: {exc}")
    return ReviewCleanupResult(pr_number=pr_number, path=path, removed=removed)


class PrReviewCleanupOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`ReviewCleanupResult` (flat; envelope
    keys first). ``path`` is absolute."""

    success: bool
    error_type: str | None
    message: str | None
    pr: int
    path: str
    removed: bool

    @classmethod
    def from_domain(cls, result: ReviewCleanupResult) -> "PrReviewCleanupOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            pr=result.pr_number,
            path=str(result.path),
            removed=result.removed,
        )


def _result_to_dict(result: ReviewCleanupResult) -> dict[str, object]:
    return PrReviewCleanupOut.from_domain(result).model_dump(mode="json")


def _render_human(result: ReviewCleanupResult) -> None:
    if result.removed:
        user_output(
            click.style("✓ ", fg="green")
            + f"removed review worktree {review_worktree_name(result.pr_number)}"
        )
    else:
        user_output(f"no review worktree for PR #{result.pr_number}")
