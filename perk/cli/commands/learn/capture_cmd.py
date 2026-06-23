"""`perk learn capture --json --body <file>` — the deep `/learn` knowledge-capture pass.

Graduates `/learn` from a thin marker-clear into a real capture: read the agent-captured learnings
markdown from a run-scoped scratch file (the stdin-less worker pattern), create a `perk:learn`
labelled issue (idempotent via the `perk:learn`-scoped `find_learn_issue`), post a back-link comment
on the plan issue (best-effort), and clear the `pending-learn` semaphore.

Exit codes: 0 captured · 1 invalid input / no plan / plan-not-found / op failure · 2 not-a-repo.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import click

from perk.backends import issue_backend, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.commands.learn.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@dataclass(frozen=True)
class LearnCaptureResult:
    learn_issue: issue_backend.IssueRef
    plan_issue: str  # the opaque plan-issue id (GitHub: "42"; Linear: "ENG-123")
    commented: bool
    pending_cleared: bool
    dry_run: bool


@click.command("capture")
@click.option(
    "--body",
    "body_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the captured-learnings markdown (a run-scoped scratch file).",
)
@click.option("--dry-run", is_flag=True, help="Compose without creating an issue or clearing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def capture_learn(ctx: click.Context, *, body_path: Path, dry_run: bool, as_json: bool) -> None:
    """Create the perk:learn issue from captured learnings and clear pending-learn (land → learn).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _learn_capture_impl(repo_root=repo_root, body_path=body_path, dry_run=dry_run)
    except IssueBackendError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"learn capture failed\n{exc}",
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
        machine_output(json.dumps(_result_to_dict(result)))
    else:
        _render_human(result)


def _learn_capture_impl(*, repo_root: Path, body_path: Path, dry_run: bool) -> LearnCaptureResult:
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    issue = str(plan_ref["pr_id"])
    body_text = body_path.read_text(encoding="utf-8").strip()
    if not body_text:
        raise UserFacingCliError(
            "Captured-learnings file is empty\nNothing to capture.", error_type="empty_body"
        )

    if dry_run:
        return LearnCaptureResult(
            learn_issue=issue_backend.IssueRef(id="0", url="(dry-run)", existed=False),
            plan_issue=issue,
            commented=False,
            pending_cleared=False,
            dry_run=True,
        )

    backend = resolve.resolve_issue_backend(repo_root)
    state = backend.get_plan(issue_id=issue)
    if state is None:
        raise UserFacingCliError(f"Plan issue #{issue} not found", error_type="plan_not_found")
    run_id = state.header.get("run_id")
    learn_issue = backend.create_learn_issue(
        title=f"Learnings: {state.title}",
        body=body_text,
        run_id=str(run_id) if isinstance(run_id, str) else None,
        plan_id=issue,
    )
    commented = _backlink(backend, issue=issue, learn=learn_issue)
    cache.clear_marker(repo_root, cache.PENDING_LEARN)
    return LearnCaptureResult(
        learn_issue=learn_issue,
        plan_issue=issue,
        commented=commented,
        pending_cleared=True,
        dry_run=False,
    )


def _backlink(
    backend: issue_backend.IssueBackend, *, issue: str, learn: issue_backend.IssueRef
) -> bool:
    """Post a back-link comment on the plan issue (best-effort — a failure never sinks capture)."""
    try:
        backend.add_issue_comment(
            issue_id=issue,
            body=f"Learnings captured in #{learn.id}.",
        )
    except IssueBackendError:
        return False
    return True


def _result_to_dict(result: LearnCaptureResult) -> dict[str, object]:
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "learn_issue": {
            # Opaque string id at every machine boundary (contracts §8.21).
            "id": result.learn_issue.id,
            "url": result.learn_issue.url,
            "existed": result.learn_issue.existed,
        },
        "plan_issue": result.plan_issue,
        "commented": result.commented,
        "pending_cleared": result.pending_cleared,
        "dry_run": result.dry_run,
    }


def _render_human(result: LearnCaptureResult) -> None:
    if result.dry_run:
        user_output(click.style("learn capture --dry-run (no issue, no marker clear)", dim=True))
        user_output(f"  plan=#{result.plan_issue}")
        return
    verb = "Found existing" if result.learn_issue.existed else "Created"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb} learn issue "
        + click.style(f"#{result.learn_issue.id}", fg="cyan")
        + "; pending-learn cleared"
    )
