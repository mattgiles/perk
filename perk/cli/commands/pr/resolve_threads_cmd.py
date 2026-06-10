"""`perk pr resolve-threads` — the batched review-thread resolution (the §8.4 op; P2.T7).

Reads a JSON batch (`[{thread_id, comment?}]`) from a `--batch <file>` arg (pi.exec has no stdin
channel, so the warm TS tool writes a run-scoped scratch file and passes its path here), then for
each thread does an optional reply followed by `resolveReviewThread` (GraphQL). The warm in-session
twin is the TS `resolve_review_threads` tool, which delegates here via `pi.exec` (D1 — GitHub
mutations are canonical in the Python gateway). Mirrors `submit_cmd.py` structure.

Exit codes: 0 ok (batch processed; per-item failures ride inside the result) · 1 invalid input /
unauthed / bad batch file / op failure · 2 not-a-repo.
"""

import json
from pathlib import Path
from typing import cast

import click

from perk import github
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output


@click.command("resolve-threads")
@click.option(
    "--batch",
    "batch_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a JSON file: an array of {thread_id, comment?} objects.",
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, help="Validate the batch without touching GitHub."
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def resolve_threads_pr(
    ctx: click.Context, *, batch_file: Path, dry_run: bool, as_json: bool
) -> None:
    """Reply-then-resolve a batch of PR review threads (the parent's resolve step).

    \b
    Reads the batch from --batch <file> (the warm tool writes a run-scoped scratch file).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        batch = _load_batch(batch_file)
        result = github.resolve_review_threads(batch=batch, repo_root=repo_root, dry_run=dry_run)
    except GitHubError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"resolve failed\n{exc}",
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
        machine_output(json.dumps(_result_to_dict(result, dry_run=dry_run)))
    else:
        _render_human(result, dry_run=dry_run)


def _load_batch(batch_file: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(batch_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserFacingCliError(
            f"Could not read the batch file: {exc}", error_type="bad_batch"
        ) from exc
    if not isinstance(data, list):
        raise UserFacingCliError("Batch must be a JSON array", error_type="bad_batch")
    batch: list[dict[str, object]] = []
    for idx, raw in enumerate(data):
        if not isinstance(raw, dict) or "thread_id" not in raw:
            raise UserFacingCliError(
                f"Batch item {idx} must be an object with a 'thread_id'", error_type="bad_batch"
            )
        item = cast("dict[str, object]", raw)
        thread_id = item["thread_id"]
        comment = item.get("comment")
        if not isinstance(thread_id, str):
            raise UserFacingCliError(
                f"Batch item {idx} has a non-string 'thread_id'", error_type="bad_batch"
            )
        if comment is not None and not isinstance(comment, str):
            raise UserFacingCliError(
                f"Batch item {idx} has a non-string 'comment'", error_type="bad_batch"
            )
        batch.append({"thread_id": thread_id, "comment": comment})
    return batch


def _result_to_dict(result: github.BatchResolveResult, *, dry_run: bool) -> dict[str, object]:
    return {
        "success": result.success,
        "error_type": None,
        "message": None,
        "dry_run": dry_run,
        "results": [
            {
                "thread_id": r.thread_id,
                "success": r.success,
                "comment_added": r.comment_added,
                "error": r.error,
            }
            for r in result.results
        ],
    }


def _render_human(result: github.BatchResolveResult, *, dry_run: bool) -> None:
    if dry_run:
        user_output(click.style("pr resolve-threads --dry-run (no GitHub writes)", dim=True))
        user_output(f"  would resolve {len(result.results)} thread(s)")
        return
    ok = sum(1 for r in result.results if r.success)
    style = "green" if result.success else "yellow"
    user_output(
        click.style("✓ " if result.success else "~ ", fg=style)
        + f"Resolved {ok}/{len(result.results)} review thread(s)"
    )
