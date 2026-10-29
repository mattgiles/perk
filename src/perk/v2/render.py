"""Human lines for a v2 door envelope (contracts.md §8.77): one header, then the snapshot (or its
marker) and whatever receipt, refusal, mismatch or error the outcome carries."""

import json

from perk.v2.envelope import (
    AcceptedEnding,
    AttemptEnding,
    Envelope,
    IncompleteEnding,
    MarkerSnapshot,
    ViewSnapshot,
)

_SHORT = 12


def _age(age_ms: int) -> str:
    seconds = age_ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _ending_status(ending: AttemptEnding) -> str:
    if isinstance(ending, AcceptedEnding):
        return "accepted"
    if isinstance(ending, IncompleteEnding):
        parts: list[str] = [ending.submission]
        if ending.reason is not None:
            parts.append(ending.reason)
        if ending.refusal is not None:
            parts.append(f"refused {ending.refusal}")
        return f"incomplete ({', '.join(parts)})"
    return f"repair ({ending.cause}: {ending.detail})"


def _view_lines(execution_id: str, view: ViewSnapshot) -> list[str]:
    lines: list[str] = [
        f"state: {view.state}" + (f" ({view.wait_reason})" if view.wait_reason else "")
    ]
    observation = view.observation
    if observation is None:
        lines.append("observed: never")
    else:
        lines.append(
            f"observed: {observation.ref} → {observation.commit[:_SHORT]} "
            f"(tree {observation.tree[:_SHORT]}), {_age(observation.age_ms)} ago"
        )
    for assignment in view.assignments:
        currency = "current" if assignment.current else "stale"
        latest = max(assignment.attempts, key=lambda attempt: attempt.ordinal, default=None)
        if latest is None:
            status = "not started"
        elif latest.outcome_id is not None:
            status = "accepted"
        elif latest.ending is None:
            status = "pending"
        else:
            status = _ending_status(latest.ending)
        lines.append(
            f"assignment {assignment.role} "
            f"[{assignment.subject_digest[:_SHORT]}, {currency}]: {status}"
        )
    decision = view.decision
    if decision is not None:
        lines.append(
            f"decision {decision.decision_id}: reply with "
            f"`perk v2 reply {execution_id} {decision.decision_id} <action>` "
            f"(actions: {'|'.join(decision.allowed_actions)})"
        )
    if view.cancellation is not None:
        lines.append(f"cancelled: {view.cancellation.reason}")
    diagnostics = view.diagnostics
    if diagnostics.runnable or diagnostics.blocked or diagnostics.parked or diagnostics.sleeping:
        lines.append(
            f"diagnostics: runnable={str(diagnostics.runnable).lower()}, "
            f"blocked={diagnostics.blocked}, parked={diagnostics.parked}, "
            f"sleeping={diagnostics.sleeping}"
        )
    return lines


def render_lines(envelope: Envelope) -> list[str]:
    """The envelope as human lines, one item per line."""
    epoch = "-" if envelope.epoch is None else str(envelope.epoch)
    lines = [
        f"perk v2 {envelope.verb}: {envelope.outcome} "
        f"(execution {envelope.execution_id}, epoch {epoch})"
    ]
    status = envelope.status
    if isinstance(status, ViewSnapshot):
        lines.extend(_view_lines(envelope.execution_id, status))
    elif isinstance(status, MarkerSnapshot):
        lines.append(f"state: {status.state}")
    receipt = envelope.receipt
    if receipt is not None:
        continuation = receipt.continuation
        suffix = "" if continuation is None else f" (continuation task {continuation.task_id})"
        lines.append(f"receipt: {receipt.op_id}{suffix}")
    if envelope.refusal is not None:
        lines.append(f"refusal: {envelope.refusal.reason} — {envelope.refusal.detail}")
    mismatch = envelope.mismatch
    if mismatch is not None:
        lines.append(
            f"mismatch: {mismatch.field} (expected {json.dumps(mismatch.expected)}, "
            f"found {json.dumps(mismatch.found)})"
        )
    if envelope.error is not None:
        lines.append(f"error: {envelope.error.message}")
    return lines
