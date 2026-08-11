"""`perk pr ready` — the deliberate draft→ready review gate (the cold ready door).

perk deliberately does NOT auto-publish on submit (the PR stays draft). `/ready` (`perk pr ready`)
is the explicit gesture that opens the PR for review: resolve the active plan-ref → find the PR →
`mark_pr_ready` if it is still a draft. Idempotent — an already-ready PR is success.

Exit codes: 0 ready · 1 no saved plan / no PR / op failure · 2 not-a-repo.
"""

from dataclasses import dataclass
from pathlib import Path

import click

from perk import delivery, github
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import user_output


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
    except (delivery.LayerError, delivery.TrainReconstructionError) as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type,
            message=str(exc),
            extra={"dry_run": False},
        )
        return
    except (
        GitHubError,
        IssueBackendError,
        ObjectiveStoreError,
        delivery.TrainPersistenceError,
        delivery.JournalCorruptionError,
    ) as exc:
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

    backend = resolve.resolve_issue_backend(repo_root)
    state = backend.get_plan(issue_id=plan_ref.pr_id)
    if state is None:
        raise UserFacingCliError(
            f"Plan issue #{plan_ref.pr_id} not found", error_type="plan_not_found"
        )
    header_lineage = state.header.get("delivery_lineage")
    stacked = plan_ref.delivery_lineage is not None or (
        isinstance(header_lineage, str) and bool(header_lineage.strip())
    )
    if not stacked:
        pr = github.find_pr_for_branch(branch=branch, repo_root=repo_root)
        if pr is None:
            raise UserFacingCliError(
                f"No PR found for branch {branch!r}\nRun /submit first.", error_type="no_pr"
            )
        was_draft = pr.is_draft
        if was_draft:
            github.mark_pr_ready(number=pr.number, repo_root=repo_root)
        return PrReadyResult(pr=pr, was_draft=was_draft, dry_run=False)

    objective_id = state.header.get("objective_id")
    if not isinstance(objective_id, str) or not objective_id.strip():
        raise UserFacingCliError(
            f"plan #{plan_ref.pr_id} carries delivery_lineage but no objective_id — a "
            "stacked layer always belongs to an objective",
            error_type="not_stacked",
        )
    train = delivery.reconstruct_repo_train(repo_root, objective_id.strip())
    if isinstance(train, delivery.NoDeliveryTrain):
        raise UserFacingCliError(
            f"objective {train.objective_id} has no delivery train ({train.reason})",
            error_type="not_stacked",
        )
    ctx = delivery.derive_layer_context(train, plan_id=plan_ref.pr_id)
    layer = next(candidate for candidate in train.layers if candidate.node_id == ctx.node_id)
    if layer.pr_number is None:
        raise UserFacingCliError(
            f"layer {layer.node_id} (plan #{plan_ref.pr_id}) stages no PR",
            error_type="no_pr",
        )
    pr = github.get_pr(number=layer.pr_number, repo_root=repo_root)
    if pr is None:
        raise UserFacingCliError(
            f"No PR found for published layer {layer.node_id} (expected #{layer.pr_number})",
            error_type="no_pr",
        )
    if pr.state.upper() != "OPEN":
        raise UserFacingCliError(
            f"PR #{pr.number} for published layer {layer.node_id} is {pr.state}, not OPEN",
            error_type="pr_not_open",
        )
    if pr.is_draft:
        delivery.require_reviewable_layer(train, plan_id=plan_ref.pr_id, mutating=True)
        github.mark_pr_ready(number=pr.number, repo_root=repo_root)
        was_draft = True
    else:
        delivery.require_reviewable_layer(train, plan_id=plan_ref.pr_id, mutating=False)
        was_draft = False
    return PrReadyResult(pr=pr, was_draft=was_draft, dry_run=False)


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
