"""Objective body/table/update-composer rendering.

The byte-stable renderers relocated verbatim from the pre-split ``perk/objective.py``: the roadmap
storage block (:func:`render_roadmap_block`), the node-issue block (:func:`render_node_block`), the
human-readable roadmap table (:func:`render_roadmap_table` / :func:`_escape_cell`), the
``objective-body`` comment + its Reconcilable/table splicers
(:func:`render_body_comment` / :func:`replace_reconcilable_section` / :func:`rerender_body_table`),
the command callout (:func:`objective_callout`), the adopted-overview archive note
(:func:`render_adopted_overview_note`), and the Project-Update body composers.

Every rendered byte stays identical to the pre-split module for every pre-existing input (the
hard render-contract invariant). The one deliberate addition since the relocation:
:func:`render_header_block` appends the stacked-delivery pair (``delivery`` /
``delivery_lineage``) when set — legacy/incremental headers still render byte-identically
(contracts.md §8.42).
"""

from collections.abc import Sequence

from perk.objective._models import (
    ADOPTED_OVERVIEW_MARKER,
    OBJECTIVE_RECONCILABLE_MARKER_END,
    OBJECTIVE_RECONCILABLE_MARKER_START,
    OBJECTIVE_SCHEMA_VERSION,
    ROADMAP_TABLE_MARKER_END,
    ROADMAP_TABLE_MARKER_START,
    ObjectiveHeader,
    ObjectiveNode,
    _find_marker_pair,
)
from perk.objective.graph import canonical_pr, enrich_phase_names, group_nodes_by_phase
from perk.plan import render_command_callout


def render_adopted_overview_note(original: str) -> str:
    """Render the Immutable archive note holding the adopted source's ORIGINAL overview/body
    verbatim (§8.30), appended below the closing Reconcilable marker (Immutable).

    Empty/blank ``original`` → ``""`` (nothing to archive). Both backends call this single helper so
    the archived shape is identical across GitHub + Linear and unit-testable.
    """
    body = original.strip()
    if not body:
        return ""
    return (
        f"{ADOPTED_OVERVIEW_MARKER}\n"
        "> Adopted in place by perk. The text below is the source's original overview/body, "
        "preserved verbatim.\n\n"
        f"{body}"
    )


def render_header_block(header: ObjectiveHeader) -> dict[str, object]:
    """Build the data dict for ``render_metadata_block(OBJECTIVE_HEADER_KEY, …)``.

    Emits the 8 base :class:`ObjectiveHeader` fields in DECLARATION order (nulls included) —
    byte-identical to the former ``header.model_dump(mode="json")`` (all fields are flat scalars,
    dumped in declaration order with no JSON transform). The delivery pair (``delivery`` /
    ``delivery_lineage``) and ``origin`` are **omitted when absent** — deliberately unlike the
    null-emitting base fields — so incremental / normally-authored objectives keep the existing
    storage shape (contracts.md §8.42).
    """
    data: dict[str, object] = {
        "run_id": header.run_id,
        "created": header.created,
        "objective_comment_id": header.objective_comment_id,
        "status": header.status,
        "base": header.base,
        "adopted_from": header.adopted_from,
        "supersedes": header.supersedes,
        "superseded_by": header.superseded_by,
    }
    if header.delivery is not None:
        data["delivery"] = header.delivery
    if header.delivery_lineage is not None:
        data["delivery_lineage"] = header.delivery_lineage
    if header.origin is not None:
        data["origin"] = header.origin
    return data


def render_roadmap_block(nodes: list[ObjectiveNode]) -> dict[str, object]:
    """Build the data dict for ``render_metadata_block(OBJECTIVE_ROADMAP_KEY, …)``.

    ``depends_on``/``comment`` columns are omitted unless some node specifies them.
    """
    any_depends = any(n.depends_on is not None for n in nodes)
    any_comment = any(n.comment is not None for n in nodes)
    node_dicts: list[dict[str, object]] = []
    for n in nodes:
        node_dict: dict[str, object] = {
            "id": n.id,
            "slug": n.slug,
            "description": n.description,
            "status": n.status.value,
            "pr": n.pr,
        }
        if any_depends:
            node_dict["depends_on"] = list(n.depends_on) if n.depends_on is not None else []
        if any_comment:
            node_dict["comment"] = n.comment
        node_dicts.append(node_dict)
    return {"schema_version": OBJECTIVE_SCHEMA_VERSION, "nodes": node_dicts}


def render_node_block(node: ObjectiveNode) -> dict[str, object]:
    """The data for ``plan.render_metadata_block(OBJECTIVE_NODE_KEY, …, style="inline-code")`` on a
    node-issue. Always includes ``id``/``status``/``description``; includes ``slug``/``comment``
    only when non-None. Excludes ``pr`` (plan-header authority) and ``depends_on`` (derived from
    blocking relations)."""
    data: dict[str, object] = {
        "id": node.id,
        "status": node.status.value,
        "description": node.description,
    }
    if node.slug is not None:
        data["slug"] = node.slug
    if node.comment is not None:
        data["comment"] = node.comment
    return data


def objective_created_update_body(title: str, *, node_count: int, phase_count: int) -> str:
    """The Project Update body posted when a project-backed objective is created."""
    return f"**Objective created** — {title}\n\n{node_count} nodes across {phase_count} phases."


def plan_landed_update_body(node_ids: Sequence[str], *, pr: str | int, complete: bool) -> str:
    """The Project Update body posted when a plan lands and marks node(s) done. ``pr`` is
    normalized through :func:`canonical_pr` (displayed as ``#N``)."""
    ids = ", ".join(node_ids)
    body = f"**Plan landed** — node(s) {ids} (PR {canonical_pr(pr)}) marked done."
    if complete:
        body += "\n\nObjective complete."
    return body


def reconciled_update_body() -> str:
    """The Project Update body posted when the objective prose is reconciled against a merge."""
    return "**Roadmap reconciled** — the objective prose was updated against the merged diff."


def _escape_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def render_roadmap_table(nodes: list[ObjectiveNode], *, body: str = "") -> str:
    """Render the human-readable markdown roadmap table (grouped by phase). A "Depends On"
    column is inserted when any node specifies explicit ``depends_on``. Phase names are
    enriched from ``### Phase N: name`` headers in ``body`` when present."""
    grouped = group_nodes_by_phase(nodes)
    names = enrich_phase_names(body, [key for key, _ in grouped])
    any_depends = any(n.depends_on is not None for n in nodes)
    sections: list[str] = []
    for key, phase_nodes in grouped:
        pr_count = sum(1 for n in phase_nodes if n.pr is not None)
        header = f"### {names[key]} ({pr_count} PR)"
        rows: list[str] = []
        if any_depends:
            rows.append("| Node | Description | Depends On | Status | PR |")
            rows.append("|------|-------------|------------|--------|----|")
        else:
            rows.append("| Node | Description | Status | PR |")
            rows.append("|------|-------------|--------|----|")
        for n in phase_nodes:
            cells = [n.id, n.description]
            if any_depends:
                cells.append(", ".join(n.depends_on) if n.depends_on else "-")
            cells.extend([n.status.value.replace("_", "-"), n.pr if n.pr is not None else "-"])
            rows.append("| " + " | ".join(_escape_cell(c) for c in cells) + " |")
        sections.append(header + "\n" + "\n".join(rows))
    return "\n\n".join(sections)


def objective_callout(objective_id: str) -> str:
    """The objective command callout — ``perk objective plan <objective_id>`` (plans the next node).

    Reuses :func:`perk.plan.render_command_callout`; ``objective_id`` is the artifact's own ref id
    (GitHub number, Linear ``ENG-N`` identifier, or a raw Linear project UUID).
    """
    return render_command_callout(
        "Plan the next node:",
        f"perk objective plan {objective_id}",
        "Run from the repo root to plan the next actionable node.",
    )


def render_body_comment(nodes: list[ObjectiveNode], *, prose: str = "") -> str:
    """Render the ``objective-body`` comment content: the marker-bounded rendered table (Mechanical)
    followed by the marker-bounded Reconcilable prose region.

    Every objective carries the Reconcilable markers — even with empty ``prose`` the (empty) marker
    pair is emitted so post-merge reconciliation always has a splice target. Anything appended below
    the closing Reconcilable marker is Immutable by construction.
    """
    table = render_roadmap_table(nodes)
    block = (
        f"{ROADMAP_TABLE_MARKER_START}\n{table}\n{ROADMAP_TABLE_MARKER_END}"
        if table
        else f"{ROADMAP_TABLE_MARKER_START}\n_(no roadmap nodes yet)_\n{ROADMAP_TABLE_MARKER_END}"
    )
    prose_body = prose.strip()
    reconcilable = (
        f"{OBJECTIVE_RECONCILABLE_MARKER_START}\n{prose_body}\n{OBJECTIVE_RECONCILABLE_MARKER_END}"
        if prose_body
        else f"{OBJECTIVE_RECONCILABLE_MARKER_START}\n{OBJECTIVE_RECONCILABLE_MARKER_END}"
    )
    return f"{block}\n\n{reconcilable}\n"


def replace_reconcilable_section(comment_body: str, new_prose: str) -> str | None:
    """Splice ``new_prose`` between the Reconcilable markers in an ``objective-body`` comment,
    preserving everything outside (the Mechanical table block above, any Immutable notes below).
    Returns the updated comment, or ``None`` if the Reconcilable markers are absent (older
    objectives that predate the Reconcilable markers).

    Pure + offline. Structurally Immutable-safe: only the marker-bounded region is rewritten.
    Dual-encoding + form-preserving: the HTML markers are tried first (the GitHub
    path, byte-identical behavior), then the Linear-safe inline-code forms — whichever was found
    is re-emitted.
    """
    found = _find_marker_pair(
        comment_body, OBJECTIVE_RECONCILABLE_MARKER_START, OBJECTIVE_RECONCILABLE_MARKER_END
    )
    if found is None:
        return None
    start, end, open_marker, close_marker = found
    prose_body = new_prose.strip()
    inner = f"\n{prose_body}\n" if prose_body else "\n"
    return (
        comment_body[:start]
        + open_marker
        + inner
        + close_marker
        + comment_body[end + len(close_marker) :]
    )


def rerender_body_table(comment_body: str, nodes: list[ObjectiveNode]) -> str | None:
    """Re-render the marker-bounded table inside an existing ``objective-body`` comment from the
    authoritative ``nodes``. Returns the updated comment, or ``None`` if no markers are found.
    Dual-encoding + form-preserving: re-emits whichever marker form was found."""
    found = _find_marker_pair(comment_body, ROADMAP_TABLE_MARKER_START, ROADMAP_TABLE_MARKER_END)
    if found is None:
        return None
    start, end, open_marker, close_marker = found
    table = render_roadmap_table(nodes, body=comment_body)
    return (
        comment_body[:start]
        + open_marker
        + "\n"
        + table
        + "\n"
        + close_marker
        + comment_body[end + len(close_marker) :]
    )
