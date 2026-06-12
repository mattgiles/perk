"""`perk pr check` — the deterministic PR-body checkout-footer validator (the cold check; P2.T8a).

The supervisor surface for the post-write self-check `pr submit` runs inline: resolve the active
plan-ref → find the PR → read its body → `github.validate_pr_body` (footer-scoped). This is exactly
what catches the issue-numbered-footer bug (a footer carrying the *issue* number, not the PR's).

Exit codes: 0 valid · 1 invalid footer / no saved plan / no PR / op failure · 2 not-a-repo.
"""

import json
from pathlib import Path

import click

from perk import github, launch
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@click.command("check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def check_pr(ctx: click.Context, *, as_json: bool) -> None:
    """Validate the active plan's PR checkout footer (the deterministic `pr check`).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)
        errors = _pr_check_impl(repo_root=repo_root)
    except GitHubError as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=f"pr check failed\n{exc}")
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if errors:
        fail(
            ctx,
            as_json=as_json,
            error_type="pr_check_failed",
            message="PR body check failed:\n  " + "\n  ".join(errors),
        )
        return

    if as_json:
        machine_output(json.dumps({"success": True, "error_type": None, "message": None}))
    else:
        user_output(click.style("✓ ", fg="green") + "PR checkout footer valid")


def _pr_check_impl(*, repo_root: Path) -> tuple[str, ...]:
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
    body = github.get_pr_body(number=pr.number, repo_root=repo_root)
    return github.validate_pr_body(body or "", pr_number=pr.number)
