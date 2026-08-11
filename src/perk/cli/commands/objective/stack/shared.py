"""Shared helpers for the ``perk objective stack`` command group (status / sync / recover)."""

from pathlib import Path

from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.ensure import UserFacingCliError
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
