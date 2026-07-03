"""Unified next-stage resolution — pure, deterministic, no Click/subprocess/network.

The **shared classifier** (contracts.md §8.37): given a plan's observable issue-backend state
(``IssueBackend.get_plan``), derive the next action. Both canonical-state consumers delegate
here — `perk plan resume` (launch the verdict's stage, or name the human gate) and the
`perk objective run` supervisor (map the verdict onto its ``action`` vocabulary) — so the two
surfaces provably agree on the same plan state. This module also reconstructs the
provider-agnostic `cache.plan-ref` (``reconstruct_plan_ref``). Keeping the decision pure is what
makes the resolution matrix unit-testable.
"""

from collections.abc import Callable
from enum import StrEnum

from perk import github, plan
from perk.backends import issue_backend


class NextAction(StrEnum):
    """The seven next-action verdicts (contracts.md §8.37).

    Three are launchable stages (``IMPLEMENT``/``ADDRESS``/``LEARN``); the rest are human
    gates (``READY_FOR_REVIEW``/``AWAITING_REVIEW``/``PR_CLOSED``) or terminal (``DONE``).
    """

    IMPLEMENT = "implement"
    ADDRESS = "address"
    LEARN = "learn"
    READY_FOR_REVIEW = "ready_for_review"
    AWAITING_REVIEW = "awaiting_review"
    PR_CLOSED = "pr_closed"
    DONE = "done"

    @property
    def stage_id(self) -> str | None:
        """The launchable registry stage id, or ``None`` for a gate/terminal verdict."""
        return _STAGE_FOR_VERDICT.get(self)


_STAGE_FOR_VERDICT: dict[NextAction, str] = {
    NextAction.IMPLEMENT: "implement",
    NextAction.ADDRESS: "address",
    NextAction.LEARN: "learn",
}


def needs_address(feedback: github.PrFeedback) -> bool:
    """True when an OPEN non-draft PR has actionable review feedback (pure, offline-testable).

    True when either any review thread is unresolved, or the **latest review per author**
    (max ``submitted_at``, ISO-8601 string compare; ``None`` sorts oldest) is
    ``CHANGES_REQUESTED``. ``COMMENTED``/``APPROVED`` latest reviews and discussion comments are
    not address triggers (the latter are conversation, not change requests).
    """
    if any(not thread.is_resolved for thread in feedback.review_threads):
        return True
    latest: dict[str | None, github.Review] = {}
    for review in feedback.reviews:
        current = latest.get(review.author)
        if current is None or (review.submitted_at or "") >= (current.submitted_at or ""):
            latest[review.author] = review
    return any(review.state == "CHANGES_REQUESTED" for review in latest.values())


def resolve_next_action(
    plan_state: issue_backend.PlanState,
    *,
    has_pending_learn: bool,
    get_feedback: Callable[[int], github.PrFeedback],
) -> NextAction:
    """Classify a plan's canonical state into its next action (contracts.md §8.37).

    The arm order over the normalized PR vocabulary:

    - no PR yet                                     -> ``IMPLEMENT``
    - PR merged + header ``learn_state: pending``   -> ``LEARN``
    - PR merged + header ``captured``/``skipped``   -> ``DONE`` (even with a stale marker)
    - PR merged, field absent/unrecognized          -> the legacy fallback: ``LEARN`` iff
      ``has_pending_learn`` (the local marker — pre-field plans and failed stamps), else ``DONE``
    - PR closed unmerged                            -> ``PR_CLOSED`` (needs human attention)
    - PR draft                                      -> ``READY_FOR_REVIEW`` (no feedback fetch)
    - PR open non-draft                             -> ``ADDRESS`` when :func:`needs_address`,
      else ``AWAITING_REVIEW`` (any unknown PR state is treated as open)

    ``get_feedback`` is the **lazy** injected feedback fetch — called only on the
    open-non-draft arm, so the function stays pure given a pure callable (offline tests pass a
    raising stub for every other arm). ``has_pending_learn`` is explicitly the legacy/cache
    **fallback** signal (contracts.md §8.36): the canonical plan-header ``learn_state`` field
    wins whenever it carries a recognized value, so a merged plan resolves identically from a
    fresh clone or another machine (no local marker needed).
    """
    pr = plan_state.pr
    if pr is None:
        return NextAction.IMPLEMENT  # planned or mid-implementation, no PR yet
    if pr.state == "MERGED":
        learn_state = plan_state.header.get("learn_state")
        if learn_state == plan.LearnState.PENDING:
            return NextAction.LEARN
        if learn_state in (plan.LearnState.CAPTURED, plan.LearnState.SKIPPED):
            return NextAction.DONE
        return NextAction.LEARN if has_pending_learn else NextAction.DONE
    if pr.state == "CLOSED":
        return NextAction.PR_CLOSED
    if pr.is_draft:
        return NextAction.READY_FOR_REVIEW
    if needs_address(get_feedback(pr.number)):
        return NextAction.ADDRESS
    return NextAction.AWAITING_REVIEW


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
