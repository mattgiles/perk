"""`perk pr review-submit` — the review doors' atomic review-submission substrate.

**Consumed by the warm `submit_pr_review` posting tool, not human-CLI-first** — no launcher half, no
registry stage; the warm layer owns the structural human gate for formal events. Reads a JSON
review batch (`{body, comments?}`) from `--batch <file>` (pi.exec has no stdin channel), takes
the event from the `--event` flag (`approve|request-changes|comment`, default `comment` — the
dangerous formal events always require explicit spelling), and:

1. **Validates every comment's `{path, line, side}` anchor against the PR diff** (the merge-base
   3-dot diff GitHub validates against) — any failure reports the per-comment `invalid[]` detail
   (`bad_anchors`, exit 1) and **nothing is submitted**; the agent repairs and re-runs.
2. Submits **one atomic review** (`POST .../pulls/{n}/reviews` — comments + body + event land
   together or not at all) via the gateway's event-aware ladder: a failed COMMENT degrades to a
   discussion comment; a failed formal event is retried with the comments folded into the body
   and the event preserved (never a silent verdict drop); an own-PR 422 is the clean `own_pr` arm.

`--dry-run` runs the full validation and stops before the mutation — but, unlike `review-post`'s
fully-offline dry-run, it **requires gh + auth** (anchor validation *is* the dry-run's value and
needs the PR diff). A deliberate, documented divergence. Dry-run additionally **predicts the
own-PR 422** for formal events (author == viewer ⇒ `own_pr`, nothing "submittable") — a
validated batch must mean the real call can land; the real path keeps GitHub as the authority
(the gateway's `OwnPrReviewError` arm).

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / unauthed / bad batch / bad anchors / own_pr / fail ·
2 not-a-repo.
"""

import json
from pathlib import Path
from typing import Literal

import click
from pydantic import Field

from perk import github
from perk.boundary import OutputModel, StrictInputModel, ValidationError, format_validation_error
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError, OwnPrReviewError
from perk.substrate.output import user_output

# flag spelling -> the REST wire spelling.
_WIRE_EVENT = {"approve": "APPROVE", "request-changes": "REQUEST_CHANGES", "comment": "COMMENT"}


class ReviewSubmitCommentInput(StrictInputModel):
    """One inline comment in the machine-authored submission batch (strict: a typo fails loudly).

    `line` is **non-nullable** by design: unanchorable (`line: null`) findings are folded into
    the review body upstream, during the triage curation — never submitted as inline comments.
    """

    path: str = Field(min_length=1)
    line: int
    side: Literal["LEFT", "RIGHT"] = "RIGHT"
    body: str = Field(min_length=1)


class ReviewSubmitBatchInput(StrictInputModel):
    """The strict `review-submit` batch shape (`{body, comments?}` — the event rides the flag).

    No `fyi` field: in-session triage color is structurally unpostable through this door
    (strict extra-forbid rejects it). `comments` stays nullable so an explicit `null` is
    tolerated, normalized to `[]` in conversion.
    """

    body: str = ""
    comments: list[ReviewSubmitCommentInput] | None = None


@click.command("review-submit")
@click.option("--pr", "pr_number", type=int, required=True, help="The PR number to review.")
@click.option(
    "--event",
    "event",
    type=click.Choice(["approve", "request-changes", "comment"]),
    default="comment",
    show_default=True,
    help="The formal review event. Formal verdicts always require explicit spelling.",
)
@click.option(
    "--batch",
    "batch_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a JSON file: {body: str, comments?: [{path, line, side?, body}]}.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Validate the batch + anchors without submitting (still needs gh: it fetches the diff).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def review_submit_pr(
    ctx: click.Context,
    *,
    pr_number: int,
    event: str,
    batch_file: Path,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Submit one atomic review (comments + body + event) to PR N.

    \b
    Consumed by the warm submit_pr_review posting tool. Validates every comment's
    path/line/side anchor against the PR diff BEFORE submitting; --dry-run
    stops after validation (it still shells gh for the diff).
    """
    try:
        repo_root = require_repo(ctx)
        auth = require_github(ctx)  # always — dry-run included (anchor validation shells gh)
        batch = _load_batch(batch_file)
        _check_event_requirements(batch, event=event)
        if dry_run and event != "comment":
            _check_own_pr_formal_event(
                viewer=auth.user, pr_number=pr_number, event=event, repo_root=repo_root
            )
        comments = [
            github.InlineReviewComment(path=c.path, line=c.line, body=c.body, side=c.side)
            for c in (batch.comments or [])
        ]
        _validate_anchors(
            ctx,
            comments,
            pr_number=pr_number,
            event=event,
            repo_root=repo_root,
            dry_run=dry_run,
            as_json=as_json,
        )
        if dry_run:
            result = github.ReviewPostResult(
                ok=True, mode="validated", pr_number=pr_number, comment_count=len(comments)
            )
        else:
            result = github.post_pr_review(
                pr_number=pr_number,
                summary=batch.body,
                comments=comments,
                repo_root=repo_root,
                event=_WIRE_EVENT[event],
            )
    except OwnPrReviewError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="own_pr",
            message=(
                f"GitHub rejected the {event} review: you cannot approve or request changes "
                f"on your own PR\n{exc}"
            ),
            extra={"dry_run": dry_run},
        )
        return
    except GitHubError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"review submission failed\n{exc}",
            extra={"dry_run": dry_run},
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
            extra={"dry_run": dry_run},
        )
        return

    emit(
        as_json=as_json,
        payload=_result_to_dict(result, event=event, dry_run=dry_run),
        render=lambda: _render_human(result, event=event, dry_run=dry_run),
    )


def _load_batch(batch_file: Path) -> ReviewSubmitBatchInput:
    """Parse + strict-validate the batch file. Raises ``bad_batch``."""
    try:
        data = json.loads(batch_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserFacingCliError(
            f"Could not read the batch file: {exc}", error_type="bad_batch"
        ) from exc
    try:
        return ReviewSubmitBatchInput.model_validate(data)
    except ValidationError as exc:
        raise UserFacingCliError(
            format_validation_error(exc, source="batch"), error_type="bad_batch"
        ) from exc


def _check_event_requirements(batch: ReviewSubmitBatchInput, *, event: str) -> None:
    """The event-conditioned batch checks (REST requirements, enforced locally for deterministic
    errors): `comment`/`request-changes` require a non-empty body; only `approve` may be an
    entirely empty batch. Raises ``bad_batch``."""
    if event == "approve":
        return
    if not batch.body.strip():
        raise UserFacingCliError(
            f"a --event {event} review requires a non-empty batch body",
            error_type="bad_batch",
        )


def _check_own_pr_formal_event(
    *, viewer: str | None, pr_number: int, event: str, repo_root: Path
) -> None:
    """Dry-run-only prediction of the own-PR 422: GitHub always rejects a formal review
    (approve/request-changes) from the PR author, so a "submittable" verdict on such a batch is
    false confidence — the run that surfaced this saw a human-approved review lost to the
    rejection. Fails ``own_pr`` when the PR author is the authenticated viewer. Fail-open when
    either login is unresolvable (a missing PR still surfaces as ``pr_not_found`` in anchor
    validation; the real path keeps GitHub's authoritative rejection)."""
    if viewer is None:
        return
    author = github.get_pr_author(number=pr_number, repo_root=repo_root)
    if author is None or author != viewer:
        return
    raise UserFacingCliError(
        f"a --event {event} review cannot land on your own PR\n"
        f"PR #{pr_number} is authored by {author} — the authenticated gh user. GitHub rejects "
        "approve/request-changes from the PR author; use --event comment.",
        error_type="own_pr",
    )


def _validate_anchors(
    ctx: click.Context,
    comments: list[github.InlineReviewComment],
    *,
    pr_number: int,
    event: str,
    repo_root: Path,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Pre-submission anchor validation against the PR's merge-base 3-dot diff — the door's
    reason to exist: the agent repairs bad anchors *before* anything touches GitHub. Any failure
    ``fail``s with the per-comment ``invalid[]`` detail (``bad_anchors``, exit 1) — identical
    shape for dry-run and real runs (the repair loop re-runs ``--dry-run`` until it exits 0)."""
    diff = github.get_pr_diff(pr_number=pr_number, repo_root=repo_root)
    if diff is None:
        raise UserFacingCliError(
            f"PR #{pr_number} not found\nCheck the number (gh pr list shows open PRs).",
            error_type="pr_not_found",
        )
    anchors = github.parse_diff_anchors(diff)
    invalid: list[dict[str, object]] = []
    for index, c in enumerate(comments):
        reason = anchors.check(path=c.path, line=c.line, side=c.side)
        if reason is not None:
            invalid.append(
                {"index": index, "path": c.path, "line": c.line, "side": c.side, "reason": reason}
            )
    if invalid:
        fail(
            ctx,
            as_json=as_json,
            error_type="bad_anchors",
            message=(
                f"{len(invalid)} of {len(comments)} comment anchor(s) not in the PR diff — "
                "repair and retry (--dry-run to re-validate)"
            ),
            extra={"dry_run": dry_run, "pr": pr_number, "event": event, "invalid": invalid},
        )


class PrReviewSubmitOut(OutputModel):
    """The ``--json`` serialization boundary of the submission result (flat; envelope keys
    first). ``event`` is the flag spelling; ``mode`` ∈
    ``validated | review | review_folded | comment_fallback``."""

    success: bool
    error_type: str | None
    message: str | None
    dry_run: bool
    pr: int
    event: str
    mode: str
    comment_count: int

    @classmethod
    def from_domain(
        cls, result: github.ReviewPostResult, *, event: str, dry_run: bool
    ) -> "PrReviewSubmitOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            dry_run=dry_run,
            pr=result.pr_number,
            event=event,
            mode=result.mode,
            comment_count=result.comment_count,
        )


def _result_to_dict(
    result: github.ReviewPostResult, *, event: str, dry_run: bool
) -> dict[str, object]:
    return PrReviewSubmitOut.from_domain(result, event=event, dry_run=dry_run).model_dump(
        mode="json"
    )


def _render_human(result: github.ReviewPostResult, *, event: str, dry_run: bool) -> None:
    if dry_run:
        user_output(
            click.style("pr review-submit --dry-run (validated, no GitHub writes)", dim=True)
        )
        user_output(
            f"  {result.comment_count} inline comment(s), event {event} — batch is submittable"
        )
        return
    user_output(
        click.style("✓ ", fg="green")
        + f"submitted {event} review to PR #{result.pr_number} "
        + f"({result.comment_count} inline comment(s))"
    )
    if result.mode == "review_folded":
        user_output(
            "  note: inline anchors rejected by GitHub — comments folded into the review body, "
            "event preserved"
        )
    elif result.mode == "comment_fallback":
        user_output("  note: degraded to a discussion comment")
