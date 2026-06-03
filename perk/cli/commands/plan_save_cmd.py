"""`perk plan-save` — the Python/worker GitHub plan-write (the cold save door).

The first `require_github` consumer and the first GitHub *mutation* (contracts.md §8.4;
T2a). The warm in-session twin is the TS `/plan-save` tool (T3). Supervisor surface
(cli-vs-pi §3.2): `--json` to stdout + stable exit codes, human text to stderr.

Exit codes: 0 saved · 1 invalid input / unauthed / op failure · 2 not-a-repo.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import click

from perk import cache, github, plan
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output

# error_type -> process exit code (default 1).
_EXIT_FOR_TYPE = {"not_a_repo": 2}


@dataclass(frozen=True)
class PlanSaveResult:
    issue: github.PlanIssue
    plan_ref: plan.PlanRef
    issue_body: str
    body_comment: str
    dry_run: bool
    cached: bool  # the plan-ref was written to .pi/workflow/plan-ref.json (real save only)


@click.command("plan-save")
@click.option(
    "--plan-file",
    "plan_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the plan markdown to save.",
)
@click.option(
    "--run-id", "run_id", default=None, help="Correlation run id (defaults to $PERK_RUN_ID)."
)
@click.option("--title", default=None, help="Issue title (defaults to the plan's first heading).")
@click.option(
    "--objective-id",
    "objective_id",
    default=None,
    help="Link the plan to an objective (the plan→objective direction; P2.T10).",
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, help="Compose and print without touching GitHub."
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def plan_save(
    ctx: click.Context,
    *,
    plan_file: Path | None,
    run_id: str | None,
    title: str | None,
    objective_id: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Save a plan to GitHub as an issue (the queryable header + the full body comment).

    \b
    Examples:
      perk plan-save --plan-file plan.md           # create the plan issue
      perk plan-save --plan-file plan.md --dry-run # compose + print, no GitHub
      perk plan-save --plan-file plan.md --json    # machine-readable (supervisor surface)
    """
    try:
        repo_root = require_repo(ctx)
        # A dry run composes + prints locally; it needs neither auth nor a network.
        if not dry_run:
            require_github(ctx)
        resolved_run_id = run_id if run_id is not None else os.environ.get("PERK_RUN_ID")
        result = _plan_save_impl(
            repo_root=repo_root,
            plan_file=plan_file,
            run_id=resolved_run_id,
            title=title,
            objective_id=objective_id,
            dry_run=dry_run,
        )
    except GitHubError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"GitHub plan write failed\n{exc}",
        )
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


def _plan_save_impl(
    *,
    repo_root: Path,
    plan_file: Path | None,
    run_id: str | None,
    title: str | None,
    objective_id: str | None = None,
    dry_run: bool,
) -> PlanSaveResult:
    """Pure-ish logic (no Click). Composes the header/body and performs the GitHub write."""
    if plan_file is None:
        raise UserFacingCliError(
            "No plan file given\nPass --plan-file <path> to the plan markdown.",
            error_type="invalid_input",
        )
    if not plan_file.is_file():
        raise UserFacingCliError(f"Plan file not found: {plan_file}", error_type="invalid_input")
    plan_markdown = plan_file.read_text(encoding="utf-8")
    if not plan_markdown.strip():
        raise UserFacingCliError(f"Plan file is empty: {plan_file}", error_type="invalid_input")

    resolved_title = title or plan.derive_title(plan_markdown)
    header = plan.PlanHeader(run_id=run_id or "", created=plan.now_iso(), objective_id=objective_id)
    issue_body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, header.to_data())
    body_comment = plan.render_plan_body(plan_markdown)

    github.create_label(
        plan.PLAN_LABEL,
        color=plan.PLAN_LABEL_COLOR,
        description=plan.PLAN_LABEL_DESCRIPTION,
        repo_root=repo_root,
        dry_run=dry_run,
    )
    issue = github.create_plan_issue(
        title=resolved_title,
        body=issue_body,
        repo_root=repo_root,
        run_id=run_id,
        dry_run=dry_run,
    )
    # Only attach the plan-body comment when we freshly created the issue (idempotent re-save
    # returns the existing one untouched; a dry run shells nothing).
    if not issue.existed and not dry_run:
        github.add_issue_comment(
            issue=issue.number, body=body_comment, repo_root=repo_root, dry_run=dry_run
        )

    plan_ref = plan.PlanRef(
        provider="github",
        pr_id=str(issue.number),
        url=issue.url,
        labels=(plan.PLAN_LABEL,),
        objective_id=objective_id,
    )
    # Persist the ref as the cache.plan-ref pointer (turn-2b §7): the next session's
    # reconciliation links it, and `implement` reads it. A dry run writes nothing.
    if not dry_run:
        cache.write_plan_ref(repo_root, plan_ref.to_data())
    return PlanSaveResult(
        issue=issue,
        plan_ref=plan_ref,
        issue_body=issue_body,
        body_comment=body_comment,
        dry_run=dry_run,
        cached=not dry_run,
    )


def _result_to_dict(result: PlanSaveResult) -> dict[str, object]:
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "issue": {
            "number": result.issue.number,
            "url": result.issue.url,
            "existed": result.issue.existed,  # warm /plan-save surfaces this in details (T3)
        },
        "plan_ref": result.plan_ref.to_data(),
        "cached": result.cached,
        "dry_run": result.dry_run,
    }


def _render_human(result: PlanSaveResult) -> None:
    if result.dry_run:
        user_output(click.style("plan-save --dry-run (no GitHub writes)", dim=True))
        user_output(click.style("── issue body ──", fg="bright_black"))
        user_output(result.issue_body)
        user_output(click.style("── plan-body comment ──", fg="bright_black"))
        user_output(result.body_comment)
        return
    verb = "Found existing" if result.issue.existed else "Saved"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb} plan "
        + click.style(f"#{result.issue.number}", fg="cyan")
        + f" → {result.issue.url}"
    )


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    """Route a failure to the supervisor surface (stable exit code; --json or styled stderr)."""
    if as_json:
        machine_output(
            json.dumps(
                {"success": False, "error_type": error_type, "message": message, "dry_run": False}
            )
        )
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))
