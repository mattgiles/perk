"""`perk pr resolve-threads` — the batched review-thread resolution (the §8.4 op).

Reads a JSON batch (`[{thread_id, comment?}]`) from a `--batch <file>` arg (pi.exec has no stdin
channel, so the warm TS tool writes a run-scoped scratch file and passes its path here), then for
each thread does an optional reply followed by `resolveReviewThread` (GraphQL). The warm in-session
`finalize_address` tool delegates its internal mechanical resolve half here via `pi.exec` after
publication succeeds (GitHub mutations are canonical in the Python gateway). Mirrors
`submit_cmd.py` structure.

Exit codes: 0 ok (batch processed; per-item failures ride inside the result) · 1 invalid input /
unauthed / bad batch file / op failure · 2 not-a-repo.
"""

import json
from pathlib import Path

import click
from pydantic import ConfigDict, RootModel

from perk import github
from perk.boundary import StrictInputModel, ValidationError, format_validation_error
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.substrate.output import user_output


@click.command("resolve-threads")
@click.option(
    "--batch",
    "batch_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a JSON file: an array of {thread_id, comment?} objects.",
)
@click.option("--dry-run", is_flag=True, help="Validate the batch without touching GitHub.")
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

    emit(
        as_json=as_json,
        payload=_result_to_dict(result, dry_run=dry_run),
        render=lambda: _render_human(result, dry_run=dry_run),
    )


class ResolveThreadInput(StrictInputModel):
    """One strict batch item (`{thread_id, comment?}`); a typo/wrong type fails loudly."""

    thread_id: str
    comment: str | None = None


class ResolveThreadsBatch(RootModel[list[ResolveThreadInput]]):
    """The strict batch root: a JSON array of thread items (a non-array fails loudly)."""

    model_config = ConfigDict(strict=True)


def _load_batch(batch_file: Path) -> list[github.ResolveThreadRequest]:
    try:
        data = json.loads(batch_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserFacingCliError(
            f"Could not read the batch file: {exc}", error_type="bad_batch"
        ) from exc
    try:
        model = ResolveThreadsBatch.model_validate(data)
    except ValidationError as exc:
        raise UserFacingCliError(
            format_validation_error(exc, source="batch"), error_type="bad_batch"
        ) from exc
    return [
        github.ResolveThreadRequest(thread_id=i.thread_id, comment=i.comment) for i in model.root
    ]


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
