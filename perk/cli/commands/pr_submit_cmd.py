"""`perk pr-submit` — the Python/worker PR open (the cold submit door; P1.T5a).

Pushes the active plan's branch and opens a **draft** PR linking the plan (`Closes #N`), then
populates the staged `branch`/`pr`/`lifecycle_stage` plan-header fields. Reuses T2a's write
conventions; the warm in-session twin is the TS `/submit` tool (delegates here via `pi.exec`).
Supervisor surface (cli-vs-pi §3.2): `--json` to stdout + stable exit codes, human text to stderr.

Exit codes: 0 submitted · 1 invalid input / unauthed / no saved plan / op failure · 2 not-a-repo.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import click

from perk import cache, git, github, launch, plan
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output

_EXIT_FOR_TYPE = {"not_a_repo": 2}


@dataclass(frozen=True)
class PrSubmitResult:
    pr: github.PullRequest
    branch: str
    issue: int
    header_update: github.PlanHeaderUpdate
    dry_run: bool


@click.command("pr-submit")
@click.option(
    "--dry-run", "dry_run", is_flag=True, help="Compose the plan without pushing or hitting GitHub."
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def pr_submit(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Open a draft PR for the active plan's branch (the implement → submit boundary).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _pr_submit_impl(repo_root=repo_root, dry_run=dry_run)
    except GitHubError as exc:
        _fail(ctx, as_json=as_json, error_type="github_error", message=f"PR submit failed\n{exc}")
        return
    except git.GitError as exc:
        _fail(ctx, as_json=as_json, error_type="git_error", message=f"git push failed\n{exc}")
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


_HEADER_FIELDS = ("branch", "pr", "lifecycle_stage")


def _pr_submit_impl(*, repo_root: Path, dry_run: bool) -> PrSubmitResult:
    """Resolves the plan, pushes, opens the PR, updates the header.

    A dry run is fully **offline** (no push, no `gh` read or write): it composes the launch
    preview from the local `cache.plan-ref` only (mirroring `plan-save --dry-run`).
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
        return PrSubmitResult(
            pr=github.PullRequest(
                number=0, url="(dry-run)", is_draft=True, state="OPEN", existed=False
            ),
            branch=branch,
            issue=issue,
            header_update=github.PlanHeaderUpdate(fields_updated=_HEADER_FIELDS, dry_run=True),
            dry_run=True,
        )

    state = github.get_plan(number=issue, repo_root=repo_root)
    if state is None:
        raise UserFacingCliError(f"Plan issue #{issue} not found", error_type="plan_not_found")
    base = github.default_branch(repo_root)
    git.push(repo_root, branch)

    pr = github.create_pr(
        head=branch,
        base=base,
        title=state.title,
        body=_compose_pr_body(issue=issue),
        repo_root=repo_root,
        draft=True,
    )
    header_update = github.update_plan_header(
        issue=issue,
        repo_root=repo_root,
        fields={
            "branch": branch,
            "pr": str(pr.number),
            "lifecycle_stage": plan.LifecycleStage.IMPL.value,
        },
    )
    return PrSubmitResult(
        pr=pr, branch=branch, issue=issue, header_update=header_update, dry_run=False
    )


def _compose_pr_body(*, issue: int) -> str:
    """The Phase-1 minimal PR body (P1.T5a D2): closing keyword + plan link + plain checkout footer.

    No HTML `<details>` (erk tripwire: breaks checkout-footer validation); full-plan re-embedding
    is Phase 2.
    """
    return f"Closes #{issue}\n\nPlan: #{issue}\n\n`gh pr checkout {issue}`\n"


def _result_to_dict(result: PrSubmitResult) -> dict[str, object]:
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "pr": {
            "number": result.pr.number,
            "url": result.pr.url,
            "is_draft": result.pr.is_draft,
            "existed": result.pr.existed,
        },
        "branch": result.branch,
        "issue": result.issue,
        "plan_header": {"fields_updated": list(result.header_update.fields_updated)},
        "dry_run": result.dry_run,
    }


def _render_human(result: PrSubmitResult) -> None:
    if result.dry_run:
        user_output(click.style("pr-submit --dry-run (no push, no GitHub writes)", dim=True))
        user_output(f"  branch={result.branch}  base-plan=#{result.issue}")
        user_output(f"  would set plan-header: {', '.join(result.header_update.fields_updated)}")
        return
    verb = "Found existing" if result.pr.existed else "Opened draft"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb} PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + f" → {result.pr.url}"
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
