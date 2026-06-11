"""`perk pr submit` — the Python/worker PR open (the cold submit door; P1.T5a).

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
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output


@dataclass(frozen=True)
class PrSubmitResult:
    pr: github.PullRequest
    branch: str
    issue: int
    header_update: github.PlanHeaderUpdate
    plan_embedded: bool
    pr_checked: bool
    dry_run: bool


@click.command("submit")
@click.option("--dry-run", is_flag=True, help="Compose the plan without pushing or hitting GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def submit_pr(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
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
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"PR submit failed\n{exc}",
            extra={"dry_run": False},
        )
        return
    except git.PushRejectedError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="push_rejected",
            message=(
                "Push rejected — the remote branch moved unexpectedly.\n"
                "Fetch/rebase onto the latest origin and re-submit.\n" + str(exc)
            ),
            extra={"dry_run": False},
        )
        return
    except git.GitError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="git_error",
            message=f"git push failed\n{exc}",
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
            plan_embedded=False,
            pr_checked=False,
            dry_run=True,
        )

    state = github.get_plan(number=issue, repo_root=repo_root)
    if state is None:
        raise UserFacingCliError(f"Plan issue #{issue} not found", error_type="plan_not_found")
    if git.is_dirty(repo_root):
        raise UserFacingCliError(
            "Uncommitted changes in this worktree\n"
            "Commit your changes before submitting — uncommitted work isn't pushed.",
            error_type="dirty_tree",
        )
    base = github.default_branch(repo_root)
    # Auto-force (--force-with-lease): perk plan branches are single-author and expected to
    # diverge after amend/squash/rebase; a no-op on the first push.
    git.push(repo_root, branch, force=True)

    # Best-effort plan embed (D3): fetch the verbatim plan markdown; None (no block / fetch
    # failure) -> no embed, no raise. The PR number is unknown until create_pr returns, so the
    # checkout footer is appended in a second update_pr_body pass (D2 — create-then-update).
    plan_body = _safe_plan_body(issue=issue, repo_root=repo_root)
    pr = github.create_pr(
        head=branch,
        base=base,
        title=state.title,
        body=_compose_pr_body(issue=issue, plan_body=plan_body),
        repo_root=repo_root,
        draft=True,
    )
    full_body = _compose_pr_body(issue=issue, plan_body=plan_body, pr_number=pr.number)
    github.update_pr_body(number=pr.number, body=full_body, repo_root=repo_root)
    # Post-write self-check (D5): exactly what catches the issue-numbered-footer bug.
    errors = github.validate_pr_body(full_body, pr_number=pr.number)
    if errors:
        raise UserFacingCliError(
            "PR body check failed:\n  " + "\n  ".join(errors), error_type="pr_check_failed"
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
        pr=pr,
        branch=branch,
        issue=issue,
        header_update=header_update,
        plan_embedded=plan_body is not None,
        pr_checked=True,
        dry_run=False,
    )


def _safe_plan_body(*, issue: int, repo_root: Path) -> str | None:
    """Fetch the verbatim plan markdown for the `<details>` embed (D3). Best-effort: any GitHub
    failure degrades to `None` (no embed) rather than sinking the submit."""
    try:
        return github.get_plan_body(number=issue, repo_root=repo_root)
    except GitHubError:
        return None


def _compose_pr_body(
    *, issue: int, plan_body: str | None = None, pr_number: int | None = None
) -> str:
    """Compose the GitHub PR body (P2.T8a, D2/D3/D4): closing keyword + plan link + a best-effort
    `<details>` embed of the verbatim plan + the checkout footer.

    The two-target split (D4): this HTML-enhanced body goes ONLY into the GitHub PR body (the
    `<details>` embed is fine here). The **footer** (not the embed) must stay a plain-backtick line
    carrying the **PR** number `gh pr checkout <pr_number>` — the issue number fails
    `validate_pr_body` (the create-then-update fix for the latent issue-numbered-footer bug). The
    squash commit message is the OTHER target (plain text), set at land.
    """
    parts = [f"Closes #{issue}", f"Plan: #{issue}"]
    if plan_body:
        parts.append(f"<details><summary>Plan #{issue}</summary>\n\n{plan_body}\n\n</details>")
    if pr_number is not None:
        parts.append(f"`gh pr checkout {pr_number}`")
    return "\n\n".join(parts) + "\n"


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
        "plan_embedded": result.plan_embedded,
        "pr_checked": result.pr_checked,
        "dry_run": result.dry_run,
    }


def _render_human(result: PrSubmitResult) -> None:
    if result.dry_run:
        user_output(click.style("pr submit --dry-run (no push, no GitHub writes)", dim=True))
        user_output(f"  branch={result.branch}  base-plan=#{result.issue}")
        user_output(f"  would set plan-header: {', '.join(result.header_update.fields_updated)}")
        return
    verb = "Found existing" if result.pr.existed else "Opened draft"
    embed = "plan embedded" if result.plan_embedded else "no plan embed"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb} PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + f" → {result.pr.url} ({embed}; footer checked)"
    )
