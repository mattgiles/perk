"""The delivery **land** operation — the incremental plan variant (contracts.md §8.4).

``kind="plan"`` is the complete incremental ``perk pr land`` operation: the fail-closed
stacked-lineage refusal (the cached half rides the request and refuses before the offline
dry-run early return; the authoritative plan-header half wins on a real run), the fully
offline dry-run preview, the load-bearing pre-merge plan read, the all-state branch PR
lookup, draft→ready, the direct idempotent squash merge with the deepened commit message
(composed from the authoritative ``PlanState`` url/title + the persistence backend
identity), pre-merge ``base_ref`` capture, and the four-effect convergent fail-open
finalization bookkeeping (:mod:`perk.delivery.finalize`, package-internal — bound through
the private land runtime).

Deliberately caller-owned (per the finalize seam contract): the pending-learn marker
(worktree-cache state) and the Linear agent "landed" activity emission
(worktree-session-scoped, non-idempotent).

The sole service entry is :meth:`perk.delivery.facade.Delivery.land`. Its private immutable
context binds the three aggregate authorities; the private runtime carries only the
package-internal per-layer finalizer. No consent callback and no lock exist on this
variant — both belong to the objective variant (:mod:`perk.delivery.landing`), and the
façade rejects a consent callback here.
"""

from dataclasses import dataclass

from perk.delivery import landing
from perk.delivery.facade import (
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    LandRequest,
    LandResult,
)
from perk.delivery.finalize import LandedPlan, finalize_landed_plan


@dataclass(frozen=True)
class _LandRuntime:
    """Private immutable helpers that are not delivery authorities."""

    finalize: landing._Finalize


_DEFAULT_LAND_RUNTIME = _LandRuntime(finalize=finalize_landed_plan)


@dataclass(frozen=True)
class _LandContext:
    """One façade-bound land context over the three aggregate authorities."""

    persistence: DeliveryPersistence
    git: DeliveryGit
    github: DeliveryGitHub


def _stacked_refusal(plan_id: str) -> DeliveryError:
    """The fail-closed stacked-lineage refusal: landing one stacked layer individually merges
    into its parent branch and tears the train, so land refuses before any mutation."""
    return DeliveryError(
        f"plan #{plan_id} carries stacked delivery lineage — stacked layers land only as one "
        "atomic train, never individually\n"
        "Landing one layer merges into its parent branch and tears the train. "
        "Review + address happen on the layer PR; when done, record the post-review handoff "
        f"with /ready (perk ready {plan_id}); the train lands whole via /objective-land "
        "(perk objective stack land). "
        "Inspect the train with: perk objective stack status",
        error_type="stacked_plan",
        phase="land",
        origin="domain",
    )


def _dispatch(context: _LandContext, request: LandRequest, *, runtime: _LandRuntime) -> LandResult:
    """Run one plan land in today's exact order (see the module docstring)."""
    # Explicit narrowing: the flat request's kind guards make a blank/absent identity
    # unreachable for kind="plan".
    plan_id = request.plan_id
    branch = request.branch
    if plan_id is None or branch is None:
        raise ValueError("validated plan land request lost plan_id/branch")
    # The cached half of the stacked routing discriminator runs BEFORE the dry-run early
    # return: a "would: mark ready → squash-merge" preview would be a lie for a stacked plan,
    # and the request-borne check keeps the dry run fully offline.
    if request.delivery_lineage is not None:
        raise _stacked_refusal(plan_id)
    if request.dry_run:
        # Fully offline: returns before EVERY authority call (the Publish dry-run guarantee).
        return LandResult(
            kind="plan",
            plan=LandResult.Plan(
                dry_run=True,
                pr=LandResult.PrSummary(number=0, state="OPEN"),
                objective=LandResult.ObjectiveUpdate(None, (), "dry_run"),
                learn=LandResult.LearnUpdate((), "dry_run"),
            ),
        )
    # Load-bearing pre-merge plan read: the header half of the stacked discriminator must be
    # checked before any mutation, and the squash title/url ride the same read.
    state = context.persistence.get_plan(issue_id=plan_id)
    if state is None:
        raise DeliveryError(
            f"Plan issue #{plan_id} not found",
            error_type="plan_not_found",
            phase="land",
            origin="domain",
        )
    # Header wins over a stale cached ref: a ref without the lineage still refuses once the
    # plan header shows it (a stale cached ref must not silently land a stacked layer).
    header_lineage = state.header.get("delivery_lineage")
    if isinstance(header_lineage, str) and bool(header_lineage.strip()):
        raise _stacked_refusal(plan_id)
    pr = context.github.pr_for_branch(branch)
    if pr is None:
        raise DeliveryError(
            f"No PR found for branch {branch!r}\nRun /submit first.",
            error_type="no_pr",
            phase="land",
            origin="domain",
        )
    # Capture the PR's actual base before the merge reassigns `pr` to a synthetic PullRequest
    # (which carries no base_ref). An idempotent re-land still sees the real base here.
    pr_base = pr.base_ref
    if pr.state != "MERGED":
        if pr.is_draft:
            context.github.mark_pr_ready(pr.number)
        pr = context.github.merge_pr(
            pr.number,
            commit_message=landing.squash_commit_message(
                issue=plan_id,
                url=state.url,
                backend_id=context.persistence.backend_id(),
                title=state.title,
            ),
        )
    fin = runtime.finalize(
        context.git.repo_root,
        landed=LandedPlan(
            plan_id=plan_id,
            objective_id=request.objective_id,
            consumed_learn=request.consumed_learn,
        ),
        pr_base=pr_base,
    )
    return LandResult(
        kind="plan",
        plan=LandResult.Plan(
            dry_run=False,
            pr=LandResult.PrSummary(number=pr.number, state=pr.state),
            objective=LandResult.ObjectiveUpdate(
                objective=fin.objective.objective,
                nodes_marked=fin.objective.nodes_marked,
                skipped_reason=fin.objective.skipped_reason,
                closed=fin.objective.closed,
            ),
            learn=LandResult.LearnUpdate(
                closed=fin.learn.closed, skipped_reason=fin.learn.skipped_reason
            ),
            plan_issue_closed=fin.plan_issue_closed,
            learn_state=fin.learn_state,
        ),
    )
