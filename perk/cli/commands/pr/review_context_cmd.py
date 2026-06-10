"""`perk pr review-context` — the read-only PR-review context fetch (#175).

Resolves the active plan's PR (from the local `cache.plan-ref`, exactly as `pr feedback` does),
gathers everything the fresh-context `perk.pr-reviewer` child needs to review it (the diff, the PR
title/body, and the plan body), and emits `--json`. Read-only — no GitHub mutation; the verbose
payload is consumed by the spawned reviewer child so it never transits the parent session.

Supervisor surface (cli-vs-pi §3.2): `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / no plan / no PR / op failure · 2 not-a-repo.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import click

from perk import cache, github, launch
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output


@dataclass(frozen=True)
class PrReviewContextResult:
    context: github.PrReviewContext
    branch: str


@click.command("review-context")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def review_context_pr(ctx: click.Context, *, as_json: bool) -> None:
    """Fetch the active plan's PR review context (read-only; the pr-reviewer child runs this).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        result = _impl(repo_root=repo_root)
    except GitHubError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"PR review context failed\n{exc}",
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

    if as_json:
        machine_output(json.dumps(_result_to_dict(result)))
    else:
        _render_human(result)


def _impl(*, repo_root: Path) -> PrReviewContextResult:
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
    context = github.get_pr_review_context(pr_number=pr.number, branch=branch, repo_root=repo_root)
    return PrReviewContextResult(context=context, branch=branch)


def _result_to_dict(result: PrReviewContextResult) -> dict[str, object]:
    c = result.context
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "branch": result.branch,
        "pr": c.pr_number,
        "base_ref": c.base_ref,
        "head_ref": c.head_ref,
        "title": c.title,
        "body": c.body,
        "diff": c.diff,
        "plan_body": c.plan_body,
    }


def _render_human(result: PrReviewContextResult) -> None:
    c = result.context
    user_output(
        click.style("PR review context ", fg="cyan")
        + f"#{c.pr_number} ({result.branch}): "
        + f"{len(c.diff)} diff byte(s), "
        + ("plan body present" if c.plan_body else "no plan body")
    )
