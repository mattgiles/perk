"""Shared helpers for the ``perk objective stack`` command group (status / sync / recover /
land)."""

from pathlib import Path

from perk.backends.resolve import resolve_objective_store
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.ensure import UserFacingCliError
from perk.delivery import train
from perk.state import cache


def resolve_objective_id(repo_root: Path, explicit: str | None) -> str:
    """Explicit argument wins; else the worktree plan-ref's linked objective; neither is a
    typed refusal (a cold session must name its objective). The ``superseded_by`` forward
    walk deliberately stays where it lives — inside the train reconstruction
    (``resolve_active_objective``) — so every stack command redirects identically."""
    if explicit is not None:
        return parse_objective_id(explicit)
    ref = cache.read_plan_ref(repo_root)
    if ref is not None and ref.objective_id is not None:
        return ref.objective_id
    raise UserFacingCliError(
        "No objective given — pass OBJECTIVE or run from a plan worktree linked to one.",
        error_type="no_objective",
    )


def resolve_run_id(repo_root: Path, objective_id: str, explicit: str | None) -> str:
    """``--run-id`` → the ACTIVE objective header's ``run_id`` (stamped at save); both absent
    is the typed ``invalid_input`` refusal (a defensive arm).

    The header fallback follows ``superseded_by`` forward (the same walk the operation's
    reconstruction performs) so a mutating stack operation invoked through a superseded
    objective journals the ACTIVE objective's run identity, never the predecessor's.
    """
    if explicit is not None and explicit.strip():
        return explicit.strip()
    store = resolve_objective_store(repo_root)
    state, _redirected_from = train.resolve_active_objective(store, objective_id)
    header_run_id = state.header.get("run_id")
    if isinstance(header_run_id, str) and header_run_id.strip():
        return header_run_id.strip()
    raise UserFacingCliError(
        f"Objective #{state.id} carries no run_id and none was passed — supply --run-id.",
        error_type="invalid_input",
    )
