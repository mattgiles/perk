"""`perk pr ready [PLAN]` — the deliberate draft→ready review gate (the cold ready door).

perk deliberately does NOT auto-publish on submit (the PR stays draft). `/ready` (`perk pr ready`)
is the explicit gesture that opens the PR for review. The optional positional ``PLAN`` selects
the plan canonically (one backend read via ``perk.cli.plan_selection.select_plan``) — ready
needs no source files, so `perk pr ready 42` works from the repository root without requiring
or creating a worktree; the no-argument form keeps reading the invoking checkout's own
``cache.plan-ref`` (inside a plan worktree, that worktree's binding). The command derives only the
selected plan id, delivery mode, and stacked objective id; ``Delivery.publish`` owns incremental
and stacked draft-to-ready mechanics. An already-ready stacked PR still validates the target but
skips mutation-only vetoes.

Exit codes: 0 ready · 1 no saved plan / plan not found / no PR / op failure · 2 not-a-repo.
"""

from dataclasses import dataclass
from pathlib import Path

import click

from perk import delivery, github
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.boundary import OutputModel
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import SelectedPlan, main_repo_root, parse_plan_id, select_plan
from perk.github import GitHubError
from perk.state import cache
from perk.substrate.output import user_output


@dataclass(frozen=True)
class PrReadyResult:
    pr: github.PullRequest
    was_draft: bool
    dry_run: bool


@click.command("ready")
@click.argument("plan", required=False)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Offline preview: validate the selection (PLAN is parse-checked; no backend or GitHub "
        "read) and report what a real run would do — no PR is resolved or marked."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def ready_pr(ctx: click.Context, *, plan: str | None, dry_run: bool, as_json: bool) -> None:
    """Mark a plan's draft PR ready for review (the deliberate review gate).

    \b
    PLAN is an optional plan issue id (e.g. 42, #42, ENG-123, or the pasted issue URL): pass it
    to select the plan canonically (works from the repository root — ready needs no worktree);
    omit it to read the invoking checkout's own cache.plan-ref (inside a plan worktree, that
    worktree's binding). Typed failures (no_plan_ref, plan_not_found, issue_kind_mismatch,
    no_pr, invalid_input) exit 1. Note: --dry-run performs no backend read, so the offline
    preview classifies nothing (kind included).
    """
    try:
        repo_root = require_repo(ctx)
        selected: SelectedPlan | None = None
        explicit_plan_id: str | None = None
        if plan is not None:
            explicit_plan_id = parse_plan_id(plan)
        if not dry_run:
            require_github(ctx)
            if plan is not None:
                # One canonical read: the selection's fetched state replaces the command's own
                # plan re-read below (stacked train reconstruction keeps its per-layer reads).
                selected = select_plan(main_repo_root(repo_root), plan)
        result = _pr_ready_impl(
            repo_root=repo_root,
            dry_run=dry_run,
            selected=selected,
            explicit_plan_id=explicit_plan_id,
        )
    except delivery.DeliveryError as exc:
        message = str(exc) if exc.origin == "domain" else f"pr ready failed\n{exc}"
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type,
            message=message,
            extra={"dry_run": False},
        )
        return
    except (GitHubError, IssueBackendError) as exc:
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

    emit(as_json=as_json, payload=_result_to_dict(result), render=lambda: _render_human(result))


def _no_plan_ref_error() -> UserFacingCliError:
    return UserFacingCliError(
        "No saved plan in this worktree\nRun /plan-save then perk implement first.",
        error_type="no_plan_ref",
    )


def _pr_ready_impl(
    *,
    repo_root: Path,
    dry_run: bool,
    selected: SelectedPlan | None = None,
    explicit_plan_id: str | None = None,
) -> PrReadyResult:
    """Select one plan in the CLI, then delegate ready mechanics to Delivery.publish."""
    if dry_run:
        plan_id = explicit_plan_id
        if plan_id is None:
            plan_ref = cache.read_plan_ref(repo_root)
            if plan_ref is None:
                raise _no_plan_ref_error()
            plan_id = plan_ref.pr_id
        published = delivery.resolve_delivery(repo_root).publish(
            delivery.PublishRequest(kind="ready", plan_id=plan_id, dry_run=True)
        )
    else:
        if selected is not None:
            plan_ref = selected.ref
            state = selected.state
        else:
            plan_ref = cache.read_plan_ref(repo_root)
            if plan_ref is None:
                raise _no_plan_ref_error()
            backend = resolve.resolve_issue_backend(repo_root)
            fetched = backend.get_plan(issue_id=plan_ref.pr_id)
            if fetched is None:
                raise UserFacingCliError(
                    f"Plan issue #{plan_ref.pr_id} not found", error_type="plan_not_found"
                )
            state = fetched
        header_lineage = state.header.get("delivery_lineage")
        stacked = plan_ref.delivery_lineage is not None or (
            isinstance(header_lineage, str) and bool(header_lineage.strip())
        )
        raw_objective = state.header.get("objective_id")
        objective_id = (
            raw_objective.strip()
            if stacked and isinstance(raw_objective, str) and raw_objective.strip()
            else None
        )
        published = delivery.resolve_delivery(repo_root).publish(
            delivery.PublishRequest(
                kind="ready",
                plan_id=plan_ref.pr_id,
                delivery="stacked" if stacked else "incremental",
                objective_id=objective_id,
            )
        )
    detail = published.ready
    if detail is None:
        raise ValueError("ready publish returned no ready detail")
    return PrReadyResult(pr=detail.pr, was_draft=detail.was_draft, dry_run=published.dry_run)


class ReadyPrOut(OutputModel):
    """The serialization boundary of the picked :class:`github.PullRequest` subset
    (field order load-bearing)."""

    number: int
    url: str

    @classmethod
    def from_domain(cls, pr: github.PullRequest) -> "ReadyPrOut":
        return cls(number=pr.number, url=pr.url)


class PrReadyOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrReadyResult` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    pr: ReadyPrOut
    was_draft: bool
    dry_run: bool

    @classmethod
    def from_domain(cls, result: PrReadyResult) -> "PrReadyOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            pr=ReadyPrOut.from_domain(result.pr),
            was_draft=result.was_draft,
            dry_run=result.dry_run,
        )


def _result_to_dict(result: PrReadyResult) -> dict[str, object]:
    return PrReadyOut.from_domain(result).model_dump(mode="json")


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
