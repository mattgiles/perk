"""Cross-stage resume resolution (P1.T5c) — pure, deterministic, no Click/subprocess/network.

`perk resume <plan>` reads a plan's observable issue-backend state (``IssueBackend.get_plan``)
and uses
this module to (1) reconstruct the provider-agnostic `cache.plan-ref` and (2) derive the **current
actionable stage**. The launcher then materializes the ref + launches that stage (reusing T4a's
`launch_stage`). Keeping the decision pure is what makes the resolution matrix unit-testable.
"""

from typing import Any

from perk import issue_backend, plan


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


def reconstruct_plan_ref(plan_state: issue_backend.PlanState, *, provider: str) -> dict[str, Any]:
    """Rebuild the `cache.plan-ref` payload from a plan's issue-backend state (provider-agnostic).

    ``provider`` is the resolved issue backend's ``backend_id`` (contracts.md §8.21) — callers
    pass it from their resolved backend so this module stays pure (no config read here).
    """
    return {
        "provider": provider,
        "pr_id": plan_state.id,
        "url": plan_state.url,
        "labels": [plan.PLAN_LABEL],
        "objective_id": plan_state.header.get("objective_id"),
        "consumed_learn": plan_state.header.get("consumed_learn") or [],
    }
