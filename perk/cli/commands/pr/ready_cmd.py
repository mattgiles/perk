"""`perk pr ready` — the deliberate draft→ready review gate (the cold ready door; P2.T8a, D6).

perk deliberately does NOT auto-publish on submit (the PR stays draft). `/ready` (`perk pr ready`)
is the explicit gesture that opens the PR for review: resolve the active plan-ref → find the PR →
`mark_pr_ready` if it is still a draft. Idempotent — an already-ready PR is success.

Exit codes: 0 ready · 1 no saved plan / no PR / op failure · 2 not-a-repo.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import click

from perk import github
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@dataclass(frozen=True)
class PrReadyResult:
    pr: github.PullRequest
    was_draft: bool
    dry_run: bool


@click.command("ready")
@click.option("--dry-run", is_flag=True, help="Resolve the PR without marking it ready.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def ready_pr(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Mark the active plan's draft PR ready for review (the deliberate review gate).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _pr_ready_impl(repo_root=repo_root, dry_run=dry_run)
    except GitHubError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"pr ready failed\n{exc}",
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


def _pr_ready_impl(*, repo_root: Path, dry_run: bool) -> PrReadyResult:
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    branch = launch.resolve_plan_worktree_name(plan_ref)

    if dry_run:
        return PrReadyResult(
            pr=github.PullRequest(
                number=0, url="(dry-run)", is_draft=True, state="OPEN", existed=True
            ),
            was_draft=True,
            dry_run=True,
        )

    pr = github.find_pr_for_branch(branch=branch, repo_root=repo_root)
    if pr is None:
        raise UserFacingCliError(
            f"No PR found for branch {branch!r}\nRun /submit first.", error_type="no_pr"
        )
    was_draft = pr.is_draft
    if was_draft:
        github.mark_pr_ready(number=pr.number, repo_root=repo_root)
    return PrReadyResult(pr=pr, was_draft=was_draft, dry_run=False)


def _result_to_dict(result: PrReadyResult) -> dict[str, object]:
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "pr": {"number": result.pr.number, "url": result.pr.url},
        "was_draft": result.was_draft,
        "dry_run": result.dry_run,
    }


def _render_human(result: PrReadyResult) -> None:
    if result.dry_run:
        user_output(click.style("pr ready --dry-run (no GitHub writes)", dim=True))
        user_output("  would: mark the PR ready for review (if draft)")
        return
    verb = "Marked ready" if result.was_draft else "Already ready"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb}: PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + " is open for review"
    )
