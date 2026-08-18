"""`perk pr land` — the Python/worker PR merge (the cold land door).

A thin request/result mapper over :meth:`perk.delivery.Delivery.land`: the worktree
`cache.plan-ref` is reconstructed into one ``LandRequest(kind="plan", …)`` and the façade owns
the whole operation — the stacked-lineage refusal (cached ref half before the fully offline
`--dry-run` early return; the authoritative plan header wins on a real run), the pre-merge plan
read, the all-state PR lookup, draft→ready, the direct idempotent squash merge (the `Closes #N`
in the squash footer closes the plan issue on GitHub default-base merges), and the four-effect
finalization bookkeeping. Idempotent: an already merged PR is success.

Two effects stay caller-owned here (per the finalize seam contract): the `pending-learn`
semaphore (worktree-cache state — except for a learn-docs consolidation plan with non-empty
`consumed_learn`, which is exempt from the land→learn cycle: no marker, `pending_learn: false`,
`learn_state: skipped` stamped instead) and the Linear agent "landed" activity emission
(worktree-session-scoped, non-idempotent). The warm in-session twin is the TS `/land` tool
(delegates here via `pi.exec`, then mirrors the marker for the in-session path).

Exit codes: 0 landed · 1 invalid input / unauthed / no plan / no PR / op failure · 2 not-a-repo.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import click

from perk import delivery
from perk.backends.linear import agent as linear_agent
from perk.boundary import OutputModel
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import user_output

# Learn-consume skip reasons that are ordinary, not failures: non-factory plans carry no
# `consumed_learn` (so `no_consumed_learn` is expected) and a dry run early-returns `dry_run`.
# Anything else is surfaced.
_BENIGN_LEARN_SKIPS = frozenset({"no_consumed_learn", "dry_run"})


@dataclass(frozen=True)
class PrLandResult:
    pr: delivery.LandResult.PrSummary
    branch: str
    issue: str  # the opaque plan-issue id (GitHub: "42"; Linear: "ENG-123")
    pending_learn: bool
    dry_run: bool
    objective: delivery.LandResult.ObjectiveUpdate
    learn: delivery.LandResult.LearnUpdate
    # An explicit on-land plan-issue close. GitHub relies on the squash footer's `Closes #N`
    # autoclose for default-branch merges, so this only fires for github when the PR's base is
    # non-default (autoclose never runs there); non-github backends always close explicitly.
    # Fail-open: False when skipped (autoclose path) or the close failed.
    plan_issue_closed: bool = False
    # The canonical post-merge learn state stamped onto the plan-header (contracts.md §8.36):
    # the effective `learn_state` value after the stamp (the kept value on the never-downgrade
    # arm), or None on dry-run / a failed stamp (resolution falls back to the local marker).
    learn_state: str | None = None


@click.command("land")
@click.option("--dry-run", is_flag=True, help="Compose the plan without touching GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def land_pr(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Merge the active plan's PR and set the pending-learn semaphore (submit → land).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _pr_land_impl(repo_root=repo_root, dry_run=dry_run)
    except delivery.DeliveryError as exc:
        # Domain refusals render bare (their bytes are already the message); infra failures
        # keep the historical `PR land failed` prefix.
        message = str(exc) if exc.origin == "domain" else f"PR land failed\n{exc}"
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type,
            message=message,
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


def _pr_land_impl(*, repo_root: Path, dry_run: bool) -> PrLandResult:
    """Reconstruct the cached plan-ref into one ``LandRequest`` and run ``Delivery.land``.

    A dry run is fully **offline** (no `gh`, no marker write): the façade composes the preview
    from the request alone (mirroring `pr submit --dry-run`).
    """
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    branch = launch.resolve_plan_worktree_name(plan_ref)
    issue = plan_ref.pr_id
    request = delivery.LandRequest(
        kind="plan",
        plan_id=issue,
        branch=branch,
        objective_id=plan_ref.objective_id,
        consumed_learn=plan_ref.consumed_learn,
        delivery_lineage=plan_ref.delivery_lineage,
        dry_run=dry_run,
    )
    result = delivery.resolve_delivery(repo_root).land(request)
    detail = result.plan
    if detail is None:
        raise ValueError("plan land result carried no plan detail")
    if not dry_run:
        # A learn-docs consolidation plan (non-empty `consumed_learn`) IS the learn pass — it
        # is exempt from the land→learn cycle: no pending-learn marker (which would strand the
        # worktree behind a pointless /learn short-circuit); `learn_state: skipped` is stamped
        # instead. The marker is worktree-cache state, so it stays here (the façade is
        # cache-free).
        if not plan_ref.consumed_learn:
            cache.set_marker(repo_root, cache.PENDING_LEARN)
        # Mirror the land into the Linear agent session. Gated inside the emitter
        # (stamped provider == "linear" AND LINEAR_AGENT_TOKEN) and fully fail-soft — it never
        # changes the land result or exit code. Never reached on --dry-run. Deliberately
        # OUTSIDE the façade: the gate reads worktree-session state and the emission is not
        # idempotent — activity reporting is this caller's concern.
        linear_agent.emit_landed(
            repo_root,
            pr_number=detail.pr.number,
            summary=_landed_summary(detail.objective),
            environ=os.environ,
        )
    return PrLandResult(
        pr=detail.pr,
        branch=branch,
        issue=issue,
        pending_learn=not dry_run and not plan_ref.consumed_learn,
        dry_run=dry_run,
        objective=detail.objective,
        learn=detail.learn,
        plan_issue_closed=detail.plan_issue_closed,
        learn_state=detail.learn_state,
    )


def _landed_summary(obj_update: delivery.LandResult.ObjectiveUpdate) -> str:
    """The one-line land summary for the agent-session ``response`` activity:
    the objective nodes the merge marked done, when any; empty otherwise (the emitter
    supplies the "PR #n squash-merged." base line itself)."""
    if not obj_update.nodes_marked:
        return ""
    nodes = ", ".join(obj_update.nodes_marked)
    line = f"Objective #{obj_update.objective}: marked node(s) {nodes} done."
    if obj_update.closed:
        line += " Objective complete — closed."
    return line


class LandPrOut(OutputModel):
    """The serialization boundary of :class:`delivery.LandResult.PrSummary`
    (field order load-bearing)."""

    number: int
    state: str

    @classmethod
    def from_domain(cls, pr: delivery.LandResult.PrSummary) -> "LandPrOut":
        return cls(number=pr.number, state=pr.state)


class ObjectiveLandOut(OutputModel):
    """The serialization boundary of :class:`delivery.LandResult.ObjectiveUpdate`
    (field order load-bearing).

    ``id`` maps from the domain ``objective`` field (the linked objective id)."""

    id: str | None
    nodes_marked: tuple[str, ...]
    skipped_reason: str | None
    closed: bool

    @classmethod
    def from_domain(cls, update: delivery.LandResult.ObjectiveUpdate) -> "ObjectiveLandOut":
        return cls(
            id=update.objective,
            nodes_marked=update.nodes_marked,
            skipped_reason=update.skipped_reason,
            closed=update.closed,
        )


class LearnConsumeOut(OutputModel):
    """The serialization boundary of :class:`delivery.LandResult.LearnUpdate`
    (field order load-bearing)."""

    closed: tuple[str, ...]
    skipped_reason: str | None

    @classmethod
    def from_domain(cls, update: delivery.LandResult.LearnUpdate) -> "LearnConsumeOut":
        return cls(closed=update.closed, skipped_reason=update.skipped_reason)


class PrLandOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrLandResult` (field order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    pr: LandPrOut
    branch: str
    issue: str  # opaque string id at every machine boundary (contracts §8.21)
    pending_learn: bool
    plan_issue_closed: bool
    dry_run: bool
    objective: ObjectiveLandOut
    learn: LearnConsumeOut
    # Declared LAST so the existing field byte-order is preserved (contracts.md §8.36).
    learn_state: str | None = None

    @classmethod
    def from_domain(cls, result: PrLandResult) -> "PrLandOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            pr=LandPrOut.from_domain(result.pr),
            branch=result.branch,
            issue=result.issue,
            pending_learn=result.pending_learn,
            plan_issue_closed=result.plan_issue_closed,
            dry_run=result.dry_run,
            objective=ObjectiveLandOut.from_domain(result.objective),
            learn=LearnConsumeOut.from_domain(result.learn),
            learn_state=result.learn_state,
        )


def _result_to_dict(result: PrLandResult) -> dict[str, object]:
    return PrLandOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrLandResult) -> None:
    if result.dry_run:
        user_output(click.style("pr land --dry-run (no GitHub writes, no marker)", dim=True))
        user_output(f"  branch={result.branch}  plan=#{result.issue}")
        user_output("  would: mark ready (if draft) → squash-merge → set pending-learn")
        return
    learn_fragment = (
        "; pending-learn set" if result.pending_learn else "; learn pass exempt (learn-docs plan)"
    )
    landed = (
        click.style("✓ ", fg="green")
        + "Landed PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + " (squash-merged)"
        + learn_fragment
    )
    if result.learn_state is not None:
        landed += f"; learn_state={result.learn_state}"
    user_output(landed)
    if result.learn_state is None:
        user_output(
            click.style(
                "  ⚠ learn-state stamp failed — resume falls back to the local marker",
                fg="yellow",
            )
        )
    if result.plan_issue_closed:
        user_output(
            click.style("  plan issue closed explicitly (non-default base branch)", dim=True)
        )
    if result.objective.nodes_marked:
        nodes = ", ".join(result.objective.nodes_marked)
        user_output(f"  objective #{result.objective.objective}: marked node(s) {nodes} done")
    if result.objective.closed:
        user_output(f"  objective #{result.objective.objective} complete — closed")
    if result.learn.closed:
        closed = ", ".join(f"#{n}" for n in result.learn.closed)
        user_output(f"  consolidated learn issue(s) {closed} into docs/learned")
    # Surface a non-benign learn-consume skip: `no_consumed_learn` is the ordinary
    # non-factory case (and dry-run early-returns), so stay quiet on those; a real failure
    # (`failed: …`, `bad_consumed_learn`, `error: …`) must be visible, not silent.
    if result.learn.skipped_reason and result.learn.skipped_reason not in _BENIGN_LEARN_SKIPS:
        user_output(
            click.style(f"  ⚠ learn consume incomplete: {result.learn.skipped_reason}", fg="yellow")
        )
