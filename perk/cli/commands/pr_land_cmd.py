"""`perk pr-land` — the Python/worker PR merge (the cold land door; P1.T5b).

Finds the active plan's PR, marks it ready (if draft), squash-merges it (the `Closes #N` in the
PR body closes the plan issue), and sets the `pending-learn` semaphore. Idempotent: an already
merged PR is success. Reuses T2a's write conventions; the warm in-session twin is the TS `/land`
tool (delegates here via `pi.exec`, then mirrors the marker for the in-session path).

Exit codes: 0 landed · 1 invalid input / unauthed / no plan / no PR / op failure · 2 not-a-repo.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import click

from perk import cache, github, launch
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output

_EXIT_FOR_TYPE = {"not_a_repo": 2}


@dataclass(frozen=True)
class PrLandResult:
    pr: github.PullRequest
    branch: str
    issue: int
    pending_learn: bool
    dry_run: bool


@click.command("pr-land")
@click.option(
    "--dry-run", "dry_run", is_flag=True, help="Compose the plan without touching GitHub."
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def pr_land(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Merge the active plan's PR and set the pending-learn semaphore (submit → land).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _pr_land_impl(repo_root=repo_root, dry_run=dry_run)
    except GitHubError as exc:
        _fail(ctx, as_json=as_json, error_type="github_error", message=f"PR land failed\n{exc}")
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
        machine_output(json.dumps(_result_to_dict(result)))
    else:
        _render_human(result)


def _pr_land_impl(*, repo_root: Path, dry_run: bool) -> PrLandResult:
    """Resolves the plan's PR, marks ready + squash-merges, sets pending-learn.

    A dry run is fully **offline** (no `gh`, no marker write): it composes the preview from the
    local `cache.plan-ref` only (mirroring `pr-submit --dry-run`).
    """
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    branch = launch.resolve_plan_worktree_name(plan_ref)
    issue = int(str(plan_ref["pr_id"]))

    if dry_run:
        return PrLandResult(
            pr=github.PullRequest(
                number=0, url="(dry-run)", is_draft=False, state="OPEN", existed=True
            ),
            branch=branch,
            issue=issue,
            pending_learn=False,  # a dry run sets no marker
            dry_run=True,
        )

    pr = github.find_pr_for_branch(branch=branch, repo_root=repo_root)
    if pr is None:
        raise UserFacingCliError(
            f"No PR found for branch {branch!r}\nRun /submit first.", error_type="no_pr"
        )
    if pr.state != "MERGED":
        if pr.is_draft:
            github.mark_pr_ready(number=pr.number, repo_root=repo_root)
        pr = github.merge_pr(
            number=pr.number,
            repo_root=repo_root,
            commit_message=_squash_commit_message(issue=issue, repo_root=repo_root),
        )
    cache.set_marker(repo_root, cache.PENDING_LEARN)
    return PrLandResult(pr=pr, branch=branch, issue=issue, pending_learn=True, dry_run=False)


def _squash_commit_message(*, issue: int, repo_root: Path) -> str:
    """The deepened squash commit message (P2.T8b, D8): plain ``"<plan title>\\n\\nCloses #N"``.

    This is the second of the two PR targets (the GitHub HTML body is the other, T8a) — plain text
    only, so no HTML leaks into ``git log``. Best-effort title fetch: a missing/empty title (or any
    GitHub read failure) falls back to the bare ``Closes #N``.
    """
    closes = f"Closes #{issue}"
    try:
        state = github.get_plan(number=issue, repo_root=repo_root)
    except GitHubError:
        return closes
    title = state.title.strip() if state is not None else ""
    return f"{title}\n\n{closes}" if title else closes


def _result_to_dict(result: PrLandResult) -> dict[str, object]:
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "pr": {"number": result.pr.number, "state": result.pr.state},
        "branch": result.branch,
        "issue": result.issue,
        "pending_learn": result.pending_learn,
        "dry_run": result.dry_run,
    }


def _render_human(result: PrLandResult) -> None:
    if result.dry_run:
        user_output(click.style("pr-land --dry-run (no GitHub writes, no marker)", dim=True))
        user_output(f"  branch={result.branch}  plan=#{result.issue}")
        user_output("  would: mark ready (if draft) → squash-merge → set pending-learn")
        return
    user_output(
        click.style("✓ ", fg="green")
        + "Landed PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + " (squash-merged); pending-learn set"
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
