"""Cross-verb helpers for the ``perk objective`` group."""

from perk import objective
from perk.cli.commands.plan.resume_cmd import parse_plan_id
from perk.prompts import render


def parse_objective_id(raw: str) -> str:
    """Validate an opaque objective issue id (``7``, ``#7``, or Linear's ``ENG-7``).

    The single shared parse for every ``perk objective`` verb — a thin alias of the re-typed
    :func:`perk.cli.commands.plan.resume_cmd.parse_plan_id` (one definition, no duplication).
    """
    return parse_plan_id(raw, what="objective")


def objective_read_instruction(backend: str, objective_id: str, url: str) -> str:
    """Backend-aware supplemental clause for the objective-read step of the factory prompts.
    The wording lives in `prompts/common/objective-read/linear.md`, rendered identically by both
    planes via the shared render seam (contracts.md §8.31); branching stays in code. github (and any
    non-linear) → "" (the `perk objective show` step already covers it); linear → the Project URL +
    the linear_get_issue/linear_list_comments tools (an `open <url>` fallback when the url is
    known)."""
    if backend != "linear":
        return ""
    where = f"({url})" if url else f"(run `perk objective show {objective_id}` for its URL)"
    fallback = f"; if the linear tools are unavailable, open {url}" if url else ""
    return render("common/objective-read/linear.md", {"where": where, "fallback": fallback})


def node_to_dict(node: objective.ObjectiveNode) -> dict[str, object]:
    return {
        "id": node.id,
        "description": node.description,
        "status": node.status.value,
        "pr": node.pr,
        "phase": objective.phase_label(objective.derive_phase(node.id)),
    }
