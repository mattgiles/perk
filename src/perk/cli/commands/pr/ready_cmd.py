"""`perk pr ready [PLAN]` — the deliberate ready gesture (the cold ready door).

For an **incremental** plan this is the review gate: perk deliberately does NOT auto-publish on
submit (the PR stays draft), and `/ready` (`perk pr ready`) is the explicit gesture that opens
the PR for review. For a **stacked** layer it is the deliberate post-review HUMAN handoff:
review happens on the draft layer PR, and after review + address the human runs ready to record
the handoff stamp at the exact verified published head — on draft AND non-draft PRs alike
(mark-ready mechanics first, then the journal append). It is never routine post-submit
choreography and never auto-run. The optional positional ``PLAN`` selects
the plan canonically (one backend read via ``perk.cli.plan_selection.select_plan``) — ready
needs no source files, so `perk pr ready 42` works from the repository root without requiring
or creating a worktree; the no-argument form keeps reading the invoking checkout's own
``cache.plan-ref`` (inside a plan worktree, that worktree's binding). The command derives only the
selected plan id, delivery mode, and stacked objective id; ``Delivery.publish`` owns incremental
and stacked ready mechanics. An already-ready stacked PR still validates the target but
skips mutation-only vetoes — and still stamps. A failed/ambiguous stamp append exits nonzero
with ``error_type: ready_stamp_failed`` while the envelope reports the truthful ``pr`` and
``was_draft``; the ambiguous/transient arms converge on an idempotent re-run (the deterministic
stamp key), deterministic failures name their own remediation. This worker is deterministic and
non-launching — it never starts the ready-time reconcile pass (which does not exist yet); the
envelope's ``reconcile_notice``/``reconcile_retry`` say so.

Exit codes: 0 ready · 1 no saved plan / plan not found / no PR / op failure · 2 not-a-repo.
"""

from dataclasses import dataclass
from pathlib import Path

import click

from perk import delivery, github
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.boundary import OutputModel
from perk.cli import completions
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import SelectedPlan, main_repo_root, parse_plan_id, select_plan
from perk.github import GitHubError
from perk.state import cache
from perk.substrate.output import user_output


@dataclass(frozen=True)
class PrReadyResult:
    """The thin command-level carrier around the façade's ready detail.

    ``stacked`` is the command's own routing decision (``None`` on the offline dry run, which
    classifies nothing); the continuation facts are derived from ``ready.stamp`` at the
    serialization boundary only.
    """

    ready: delivery.PublishResult.Ready
    plan_id: str
    stacked: bool | None
    dry_run: bool


@click.command("ready")
@click.argument("plan", required=False, shell_complete=completions.complete_plan_id)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Offline selection-validation preview: PLAN is parse-checked and the no-argument form "
        "confirms a saved plan exists — no backend or GitHub read, no delivery classification, "
        "so it cannot predict which arm a real run would take. Nothing is resolved, marked, or "
        "stamped; a real run marks the draft PR ready (incremental) or records the post-review "
        "handoff stamp (stacked)."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def ready_pr(ctx: click.Context, *, plan: str | None, dry_run: bool, as_json: bool) -> None:
    """Ready a plan's PR: the review gate (incremental) or the handoff stamp (stacked).

    \b
    Incremental plans: mark the draft PR ready for review — the deliberate review gate
    (submit keeps the PR draft on purpose). Stacked layers: the deliberate POST-review human
    handoff — review happens on the draft layer PR, and after review + address this gesture
    stamps the exact verified published head into the delivery journal (draft AND non-draft
    PRs; mark-ready first, then the append); the recorded stamp unblocks planning of the
    layer's direct dependents. Never routine post-submit choreography; never auto-run.
    A failed stamp exits 1 as ready_stamp_failed with the truthful pr/was_draft;
    an ambiguous/transient append converges on an idempotent re-run.

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
    except delivery.ReadyStampError as exc:
        # The stamp-specific failure envelope: the gesture may already have flipped the PR, so
        # the truthful PR facts always ride along (contracts.md §8.43).
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type,
            message=str(exc),
            extra={
                "pr": {"number": exc.pr.number, "url": exc.pr.url},
                "was_draft": exc.was_draft,
                "dry_run": False,
            },
        )
        return
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
    stacked: bool | None = None
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
    return PrReadyResult(
        ready=detail,
        plan_id=published.plan_id,
        stacked=stacked,
        dry_run=published.dry_run,
    )


class ReadyPrOut(OutputModel):
    """The serialization boundary of the picked :class:`github.PullRequest` subset
    (field order load-bearing)."""

    number: int
    url: str

    @classmethod
    def from_domain(cls, pr: github.PullRequest) -> "ReadyPrOut":
        return cls(number=pr.number, url=pr.url)


def _reconcile_notice() -> str:
    return (
        "the ready-time reconcile pass was not launched — perk ready is deterministic and "
        "non-launching"
    )


def _reconcile_retry(plan_id: str) -> str:
    return f"perk ready {plan_id}"


class PrReadyOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrReadyResult` (order load-bearing —
    the seven continuation fields are tail-additive).

    Null semantics: dry-run → all seven continuation fields null; incremental →
    ``stacked=false``, rest null; stacked success → all populated (``reconcile_notice`` /
    ``reconcile_retry`` are CLI-composed presentation: the ready-time reconcile pass was not
    launched — this worker never launches — plus the copyable re-run gesture).
    """

    success: bool
    error_type: str | None
    message: str | None
    pr: ReadyPrOut
    was_draft: bool
    dry_run: bool
    stacked: bool | None
    objective: str | None
    node: str | None
    stamped_head: str | None
    stamp_advanced: bool | None
    reconcile_notice: str | None
    reconcile_retry: str | None

    @classmethod
    def from_domain(cls, result: PrReadyResult) -> "PrReadyOut":
        stamp = result.ready.stamp
        return cls(
            success=True,
            error_type=None,
            message=None,
            pr=ReadyPrOut.from_domain(result.ready.pr),
            was_draft=result.ready.was_draft,
            dry_run=result.dry_run,
            stacked=result.stacked,
            objective=stamp.record.objective_id if stamp is not None else None,
            node=stamp.record.node_id if stamp is not None else None,
            stamped_head=stamp.record.head_sha if stamp is not None else None,
            stamp_advanced=(not stamp.existed) if stamp is not None else None,
            reconcile_notice=_reconcile_notice() if stamp is not None else None,
            reconcile_retry=_reconcile_retry(result.plan_id) if stamp is not None else None,
        )


def _result_to_dict(result: PrReadyResult) -> dict[str, object]:
    return PrReadyOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrReadyResult) -> None:
    if result.dry_run:
        user_output(click.style("pr ready --dry-run (no GitHub writes)", dim=True))
        # The offline preview validates selection only — it performs no delivery
        # classification, so it cannot claim which arm a real run would take.
        user_output("  validated the plan selection offline (nothing resolved or classified)")
        user_output(
            "  a real run would: mark the draft PR ready for review (incremental) or record "
            "the post-review handoff stamp (stacked)"
        )
        return
    verb = "Marked ready" if result.ready.was_draft else "Already ready"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb}: PR "
        + click.style(f"#{result.ready.pr.number}", fg="cyan")
        + " is open for review"
    )
    stamp = result.ready.stamp
    if stamp is None:
        return
    stamped = "Handoff stamped" if not stamp.existed else "Handoff already stamped"
    user_output(
        f"  {stamped}: objective #{stamp.record.objective_id} node {stamp.record.node_id} "
        f"at {stamp.record.head_sha}"
    )
    user_output(f"  {_reconcile_notice()}; re-run: {_reconcile_retry(result.plan_id)}")
