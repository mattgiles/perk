"""`perk pr review-post` — submit a `/pr-review` verdict to the PR.

Reads a JSON review batch (`{verdict, summary, comments?, fyi?}`) from a `--batch <file>` arg
(pi.exec has no stdin channel, so the spawned reviewer child writes a temp file and passes its path
here), resolves the active plan's PR, and branches on the **verdict**:

- `"actionable"` — submits an advisory **COMMENT** review (the `event` is hardcoded — the agent
  cannot approve/request-changes). The inline `comments[]` are best-effort line-anchored; on a
  submission failure the gateway falls back to a single discussion comment so the review always
  lands. Next step: `/address`.
- `"clean"` — posts exactly one 👍 reaction to the PR description; nothing review-shaped lands on
  the PR (`comments` must be absent/empty). Next step: `/land`.

The optional `fyi: string[]` carries borderline notes that are echoed in-session only — they are
structurally never part of any GitHub payload.

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / unauthed / bad batch / no plan / no PR / fail · 2 not-a-repo.
"""

import json
from pathlib import Path
from typing import Literal

import click
from pydantic import Field, model_validator

from perk import github
from perk.boundary import StrictInputModel, ValidationError, format_validation_error
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@click.command("review-post")
@click.option(
    "--batch",
    "batch_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Path to a JSON file: {verdict: 'clean'|'actionable', summary: str, "
        "comments?: [{path, line, body}] (actionable only), fyi?: [str] (in-session only)}."
    ),
)
@click.option("--dry-run", is_flag=True, help="Validate the batch without touching GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def review_post_pr(ctx: click.Context, *, batch_file: Path, dry_run: bool, as_json: bool) -> None:
    """Submit a `/pr-review` verdict to the active plan's PR.

    \b
    Reads the review from --batch <file> (the pr-reviewer child writes a temp file).
    An 'actionable' verdict posts an advisory COMMENT review; a 'clean' verdict posts
    a single thumbs-up reaction (no comments land on the PR).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        verdict, summary, comments, fyi = _load_batch(batch_file)
        # Dry-run only validates the batch — it neither requires auth nor resolves the PR (which
        # would shell `gh`). A real post resolves the active plan's PR first.
        pr_number = 0 if dry_run else _resolve_pr(repo_root=repo_root)
        if verdict == "clean":
            result = github.add_pr_reaction(
                pr_number=pr_number, repo_root=repo_root, dry_run=dry_run
            )
        else:
            result = github.post_pr_review(
                pr_number=pr_number,
                summary=summary,
                comments=comments,
                repo_root=repo_root,
                dry_run=dry_run,
            )
    except GitHubError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"review post failed\n{exc}",
            extra={"dry_run": False},
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
            extra={"dry_run": False},
        )
        return

    if as_json:
        machine_output(
            json.dumps(_result_to_dict(result, verdict=verdict, fyi=fyi, dry_run=dry_run))
        )
    else:
        _render_human(result, verdict=verdict, fyi=fyi, dry_run=dry_run)


def _resolve_pr(*, repo_root: Path) -> int:
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
    return pr.number


class ReviewCommentInput(StrictInputModel):
    """One inline review finding in the machine-authored batch (strict: a typo fails loudly)."""

    path: str = Field(min_length=1)
    line: int
    body: str = Field(min_length=1)


class ReviewBatchInput(StrictInputModel):
    """The strict `/pr-review` batch shape (`{verdict, summary, comments?, fyi?}`).

    `comments`/`fyi` stay nullable so an explicit `null` is tolerated (today's behavior),
    normalized to `[]` in conversion. `line: int` under strict rejects `bool`/`float`/`str`
    (preserving the old `isinstance(line, bool)` guard).
    """

    verdict: Literal["clean", "actionable"]
    summary: str = Field(min_length=1)
    comments: list[ReviewCommentInput] | None = None
    fyi: list[str] | None = None

    @model_validator(mode="after")
    def _clean_has_no_comments(self) -> "ReviewBatchInput":
        if self.verdict == "clean" and self.comments:
            raise ValueError("a 'clean' verdict must not carry comments")
        return self


def _load_batch(
    batch_file: Path,
) -> tuple[str, str, list[github.InlineReviewComment], list[str]]:
    """Parse + validate the batch → ``(verdict, summary, comments, fyi)``. Raises ``bad_batch``."""
    try:
        data = json.loads(batch_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserFacingCliError(
            f"Could not read the batch file: {exc}", error_type="bad_batch"
        ) from exc
    try:
        model = ReviewBatchInput.model_validate(data)
    except ValidationError as exc:
        raise UserFacingCliError(
            format_validation_error(exc, source="batch"), error_type="bad_batch"
        ) from exc
    comments = [
        github.InlineReviewComment(path=c.path, line=c.line, body=c.body)
        for c in (model.comments or [])
    ]
    return model.verdict, model.summary, comments, list(model.fyi or [])


def _result_to_dict(
    result: github.ReviewPostResult, *, verdict: str, fyi: list[str], dry_run: bool
) -> dict[str, object]:
    return {
        "success": result.ok,
        "error_type": None,
        "message": None,
        "dry_run": dry_run,
        "pr": result.pr_number,
        "mode": result.mode,
        "verdict": verdict,
        "fyi": fyi,
        "next_command": "/land" if verdict == "clean" else "/address",
        "comment_count": result.comment_count,
    }


def _render_human(
    result: github.ReviewPostResult, *, verdict: str, fyi: list[str], dry_run: bool
) -> None:
    if dry_run:
        user_output(click.style("pr review-post --dry-run (no GitHub writes)", dim=True))
        if verdict == "clean":
            user_output("  would post 👍 to the PR (clean — no comments). Next: /land")
        else:
            user_output(
                f"  would post a review with {result.comment_count} inline comment(s). "
                "Next: /address"
            )
        _render_fyi(fyi)
        return
    if verdict == "clean":
        user_output(
            click.style("✓ ", fg="green")
            + f"Clean review — posted 👍 to PR #{result.pr_number} (no comments). Next: /land"
        )
    else:
        label = "review" if result.mode == "review" else "comment (fallback)"
        user_output(
            click.style("✓ ", fg="green")
            + f"Posted {label} to PR #{result.pr_number} "
            + f"({result.comment_count} inline comment(s)). Next: /address"
        )
    _render_fyi(fyi)


def _render_fyi(fyi: list[str]) -> None:
    if not fyi:
        return
    user_output("FYI:")
    for note in fyi:
        user_output(f"  - {note}")
