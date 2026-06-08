"""`perk pr-review-post` — submit a `/pr-review` to the PR (#175).

Reads a JSON review batch (`{summary, comments?}`) from a `--batch <file>` arg (pi.exec has no stdin
channel, so the spawned reviewer child writes a temp file and passes its path here), resolves the
active plan's PR, and submits an advisory **COMMENT** review (the `event` is hardcoded — the agent
cannot approve/request-changes). The inline `comments[]` are best-effort line-anchored; on a
submission failure the gateway falls back to a single discussion comment so a review always lands.

Supervisor surface (cli-vs-pi §3.2): `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / unauthed / bad batch / no plan / no PR / fail · 2 not-a-repo.
"""

import json
from pathlib import Path
from typing import cast

import click

from perk import cache, github, launch
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output

_EXIT_FOR_TYPE = {"not_a_repo": 2}


@click.command("pr-review-post")
@click.option(
    "--batch",
    "batch_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a JSON file: {summary: str, comments?: [{path, line, body}]}.",
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, help="Validate the batch without touching GitHub."
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def pr_review_post(ctx: click.Context, *, batch_file: Path, dry_run: bool, as_json: bool) -> None:
    """Submit a `/pr-review` (advisory COMMENT review) to the active plan's PR.

    \b
    Reads the review from --batch <file> (the pr-reviewer child writes a temp file).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        summary, comments = _load_batch(batch_file)
        # Dry-run only validates the batch — it neither requires auth nor resolves the PR (which
        # would shell `gh`). A real post resolves the active plan's PR first.
        pr_number = 0 if dry_run else _resolve_pr(repo_root=repo_root)
        result = github.post_pr_review(
            pr_number=pr_number,
            summary=summary,
            comments=comments,
            repo_root=repo_root,
            dry_run=dry_run,
        )
    except GitHubError as exc:
        _fail(ctx, as_json=as_json, error_type="github_error", message=f"review post failed\n{exc}")
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if as_json:
        machine_output(json.dumps(_result_to_dict(result, dry_run=dry_run)))
    else:
        _render_human(result, dry_run=dry_run)


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


def _load_batch(batch_file: Path) -> tuple[str, list[github.InlineReviewComment]]:
    try:
        data = json.loads(batch_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserFacingCliError(
            f"Could not read the batch file: {exc}", error_type="bad_batch"
        ) from exc
    if not isinstance(data, dict):
        raise UserFacingCliError("Batch must be a JSON object", error_type="bad_batch")
    batch = cast("dict[str, object]", data)
    summary = batch.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise UserFacingCliError(
            "Batch must have a non-empty string 'summary'", error_type="bad_batch"
        )
    raw_comments = batch.get("comments", [])
    if raw_comments is None:
        raw_comments = []
    if not isinstance(raw_comments, list):
        raise UserFacingCliError("Batch 'comments' must be an array", error_type="bad_batch")
    comments: list[github.InlineReviewComment] = []
    for idx, raw in enumerate(raw_comments):
        if not isinstance(raw, dict):
            raise UserFacingCliError(f"Comment {idx} must be an object", error_type="bad_batch")
        item = cast("dict[str, object]", raw)
        path = item.get("path")
        line = item.get("line")
        body = item.get("body")
        if not isinstance(path, str) or not path:
            raise UserFacingCliError(
                f"Comment {idx} has a missing/non-string 'path'", error_type="bad_batch"
            )
        if not isinstance(line, int) or isinstance(line, bool):
            raise UserFacingCliError(
                f"Comment {idx} has a missing/non-integer 'line'", error_type="bad_batch"
            )
        if not isinstance(body, str) or not body.strip():
            raise UserFacingCliError(
                f"Comment {idx} has a missing/non-string 'body'", error_type="bad_batch"
            )
        comments.append(github.InlineReviewComment(path=path, line=line, body=body))
    return summary, comments


def _result_to_dict(result: github.ReviewPostResult, *, dry_run: bool) -> dict[str, object]:
    return {
        "success": result.ok,
        "error_type": None,
        "message": None,
        "dry_run": dry_run,
        "pr": result.pr_number,
        "mode": result.mode,
        "comment_count": result.comment_count,
    }


def _render_human(result: github.ReviewPostResult, *, dry_run: bool) -> None:
    if dry_run:
        user_output(click.style("pr-review-post --dry-run (no GitHub writes)", dim=True))
        user_output(f"  would post a review with {result.comment_count} inline comment(s)")
        return
    label = "review" if result.mode == "review" else "comment (fallback)"
    user_output(
        click.style("✓ ", fg="green")
        + f"Posted {label} to PR #{result.pr_number} "
        + f"({result.comment_count} inline comment(s))"
    )


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(
            json.dumps(
                {"success": False, "error_type": error_type, "message": message, "dry_run": False}
            )
        )
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))
