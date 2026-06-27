"""Cross-stage resume resolution — pure, deterministic, no Click/subprocess/network.

`perk resume <plan>` reads a plan's observable issue-backend state (``IssueBackend.get_plan``)
and uses
this module to (1) reconstruct the provider-agnostic `cache.plan-ref` and (2) derive the **current
actionable stage**. The launcher then materializes the ref + launches that stage (reusing
`launch_stage`). Keeping the decision pure is what makes the resolution matrix unit-testable.
"""

from perk import plan
from perk.backends import issue_backend
from perk.state.cache import PlanRefCache


def resolve_resume_stage(
    plan_state: issue_backend.PlanState, *, has_pending_learn: bool
) -> str | None:
    """The stage to resume a plan at, or ``None`` when nothing is actionable (merged + learned).

    The minimal state machine (turn-5 §8 / D5):

    - no PR and not yet implementing       -> ``implement``
    - implementing, no PR yet              -> ``implement`` (continue)
    - PR open                              -> ``submit`` (the impl worktree; submit is idempotent)
    - PR merged + ``pending-learn``        -> ``learn``
    - PR merged, learned                   -> ``None`` (done)
    """
    pr = plan_state.pr
    if pr is None:
        return "implement"  # planned or mid-implementation, no PR yet
    if pr.state == "OPEN":
        return "submit"
    if pr.state == "MERGED" and has_pending_learn:
        return "learn"
    return None


def reconstruct_plan_ref(plan_state: issue_backend.PlanState, *, provider: str) -> PlanRefCache:
    """Rebuild the `cache.plan-ref` payload from a plan's issue-backend state (provider-agnostic).

    ``provider`` is the resolved issue backend's ``backend_id`` (contracts.md §8.21) — callers
    pass it from their resolved backend so this module stays pure (no config read here).
    """
    raw_consumed = plan_state.header.get("consumed_learn")
    consumed = tuple(str(x) for x in raw_consumed) if isinstance(raw_consumed, list) else ()
    return PlanRefCache(
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
