"""Cross-stage resume resolution — pure, deterministic, no Click/subprocess/network.

`perk resume <plan>` reads a plan's observable issue-backend state (``IssueBackend.get_plan``)
and uses
this module to (1) reconstruct the provider-agnostic `cache.plan-ref` and (2) derive the **current
actionable stage**. The launcher then materializes the ref + launches that stage (reusing
`launch_stage`). Keeping the decision pure is what makes the resolution matrix unit-testable.
"""

from perk import plan
from perk.backends import issue_backend


def resolve_resume_stage(
    plan_state: issue_backend.PlanState, *, has_pending_learn: bool
) -> str | None:
    """The stage to resume a plan at, or ``None`` when nothing is actionable (merged + learned).

    The minimal state machine (turn-5 §8 / D5; merged-arm resolution per contracts.md §8.36):

    - no PR and not yet implementing            -> ``implement``
    - implementing, no PR yet                   -> ``implement`` (continue)
    - PR open                                   -> ``submit`` (the impl worktree; idempotent)
    - PR merged + header ``learn_state: pending``   -> ``learn``
    - PR merged + header ``captured``/``skipped``   -> ``None`` (done — even with a stale marker)
    - PR merged, field absent/unrecognized      -> the legacy fallback: ``learn`` iff
      ``has_pending_learn`` (the local marker — pre-field plans and failed stamps)

    ``has_pending_learn`` is explicitly the legacy/cache **fallback** signal: the canonical
    plan-header ``learn_state`` field wins whenever it carries a recognized value, so a merged
    plan resolves identically from a fresh clone or another machine (no local marker needed).
    """
    pr = plan_state.pr
    if pr is None:
        return "implement"  # planned or mid-implementation, no PR yet
    if pr.state == "OPEN":
        return "submit"
    if pr.state == "MERGED":
        learn_state = plan_state.header.get("learn_state")
        if learn_state == plan.LearnState.PENDING:
            return "learn"
        if learn_state in (plan.LearnState.CAPTURED, plan.LearnState.SKIPPED):
            return None
        return "learn" if has_pending_learn else None
    return None


def reconstruct_plan_ref(plan_state: issue_backend.PlanState, *, provider: str) -> plan.PlanRef:
    """Rebuild the `cache.plan-ref` payload from a plan's issue-backend state (provider-agnostic).

    ``provider`` is the resolved issue backend's ``backend_id`` (contracts.md §8.21) — callers
    pass it from their resolved backend so this module stays pure (no config read here).
    """
    raw_consumed = plan_state.header.get("consumed_learn")
    consumed = tuple(str(x) for x in raw_consumed) if isinstance(raw_consumed, list) else ()
    return plan.PlanRef(
        provider=provider,
        pr_id=plan_state.id,
        url=plan_state.url,
        labels=(plan.PLAN_LABEL,),
        objective_id=_opt_str(plan_state.header.get("objective_id")),
        consumed_learn=consumed,
        # The pinned base: recovered from the canonical `plan-header` so implement/resume/
        # the remote run-worker base off it even when the local cache.plan-ref is absent.
        base=_opt_str(plan_state.header.get("base")),
    )


def _opt_str(value: object) -> str | None:
    """The header value as a ``str``, or ``None`` for an absent/non-string value."""
    return value if isinstance(value, str) else None
