"""`perk pr url` — the read-only active-PR locator.

Resolves the active plan's PR (from the local `cache.plan-ref`, exactly as `pr feedback` /
`pr review-context` do) and emits its number + URL as `--json`. Read-only — no GitHub mutation.
The warm `/pr-review-local` door consumes this to fill plannotator's `code-review` `prUrl`
implicitly (GitHub resolution stays canonical in Python).

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 invalid input / no plan / no PR / op failure · 2 not-a-repo.
"""

from dataclasses import dataclass
from pathlib import Path

import click

from perk import github
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import user_output


@dataclass(frozen=True)
class PrUrlResult:
    number: int
    url: str
    branch: str


@click.command("url")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def url_pr(ctx: click.Context, *, as_json: bool) -> None:
    """Resolve the active plan's PR url (read-only; the /pr-review-local door runs this).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        result = _impl(repo_root=repo_root)
    except GitHubError as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=f"PR url failed\n{exc}")
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    emit(as_json=as_json, payload=_result_to_dict(result), render=lambda: _render_human(result))


def _impl(*, repo_root: Path) -> PrUrlResult:
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
    return PrUrlResult(number=pr.number, url=pr.url, branch=branch)


def _result_to_dict(result: PrUrlResult) -> dict[str, object]:
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "pr": {"number": result.number, "url": result.url},
    }


def _render_human(result: PrUrlResult) -> None:
    user_output(
        click.style("PR url ", fg="cyan") + f"#{result.number} ({result.branch}): {result.url}"
    )
