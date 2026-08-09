"""`perk learn pending` — list the closed plans still awaiting /learn.

Lists the closed plan issues whose canonical plan-header `learn_state` reads `pending`
(contracts.md §8.36) — landed, /learn not yet run — via the backend-neutral
`IssueBackend.list_plans_pending_learn` read. `--limit` bounds the scan window to the N most
recently updated closed plans (the pending stamp lands at close time, so pending plans sort
early). Canonical-field only: legacy pre-field plans (whose pending state lives solely in the
local per-worktree marker) are not listed — the local marker is worktree cache and cannot power
a repo-wide view.

Exit codes: 0 ok/empty · 1 backend failure / unauthed · 2 not-a-repo.
"""

import click

from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError, PendingLearnPlan
from perk.boundary import OutputModel
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import user_output


@click.command("pending")
@click.option(
    "--limit",
    type=click.IntRange(1, 100),
    default=50,
    help="Scan the N most recently updated closed plan issues.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def pending_learn(ctx: click.Context, *, limit: int, as_json: bool) -> None:
    """List closed plans still awaiting /learn (plan-header learn_state: pending)."""
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)
        backend = resolve.resolve_issue_backend(repo_root)
        rows = backend.list_plans_pending_learn(limit=limit)
    except IssueBackendError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"learn pending failed\n{exc}",
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

    emit(
        as_json=as_json,
        payload=_result_to_dict(rows),
        render=lambda: _render_human(rows, limit=limit),
    )


class PendingPlanOut(OutputModel):
    id: str
    title: str
    url: str
    closed_at: str | None


class LearnPendingOut(OutputModel):
    """The ``--json`` serialization boundary (order load-bearing)."""

    success: bool
    error_type: str | None
    plans: list[PendingPlanOut]


def _result_to_dict(rows: tuple[PendingLearnPlan, ...]) -> dict[str, object]:
    return LearnPendingOut(
        success=True,
        error_type=None,
        plans=[
            PendingPlanOut(id=r.id, title=r.title, url=r.url, closed_at=r.closed_at) for r in rows
        ],
    ).model_dump(mode="json")


def _render_human(rows: tuple[PendingLearnPlan, ...], *, limit: int) -> None:
    if not rows:
        user_output(
            f"No plans pending learn (scanned the {limit} most recently updated closed plans)."
        )
        return
    for row in rows:
        user_output(f"#{row.id}  {row.closed_at or '?'}  {row.title}  {row.url}")
    user_output(click.style("run: perk plan resume <id>  (launches the learn stage)", dim=True))
