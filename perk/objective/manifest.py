"""Objective manifest — the project-overview drift baseline.

The cohesive manifest concern: the :class:`Manifest` dataclass plus its renderer
(:func:`render_manifest_block`), parser (:func:`parse_manifest`), and validator
(:func:`_validate_manifest`). The manifest captures only the *structural identity* of a roadmap
(id/slug/description/depends_on per node + a pinned phase-name map); status/pr are excluded.
"""

from collections.abc import Mapping
from typing import cast

from pydantic import ValidationError

from perk.boundary import StrictBoundaryModel, format_validation_error
from perk.objective._models import (
    OBJECTIVE_MANIFEST_KEY,
    OBJECTIVE_SCHEMA_VERSION,
    NodeStatus,
    ObjectiveNode,
    _has_block,
)
from perk.plan import find_metadata_block


class Manifest(StrictBoundaryModel):
    """The persisted drift baseline of an objective's intended roadmap.

    Structural identity only: ``nodes`` reuse :class:`ObjectiveNode` but only their
    ``id``/``slug``/``description``/``depends_on`` are meaningful (``status``/``pr`` are left at
    defaults and never read — they are live/observed state). ``depends_on`` is the **explicit** edge
    set as authored (``()`` → no edges). ``phase_names`` pins the canonical milestone name per phase
    key (``phase_key_str`` → name), decoupling it from the drift-prone ``### Phase N:`` overview
    header that :func:`enrich_phase_names` reads.
    """

    schema_version: str
    nodes: tuple[ObjectiveNode, ...]
    phase_names: dict[str, str]


def render_manifest_block(
    nodes: list[ObjectiveNode], phase_names: Mapping[str, str]
) -> dict[str, object]:
    """Build the data dict for ``render_metadata_block(OBJECTIVE_MANIFEST_KEY, …)``.

    Captures only the **structural identity** of each node — ``id``/``slug``/``description`` plus
    the explicit ``depends_on`` edge set (always emitted as a list, ``[]`` when none).
    ``status``/``pr`` are deliberately omitted (live/observed state). ``phases`` pins the canonical
    milestone name per phase key (``phase_key_str``).
    """
    node_dicts: list[dict[str, object]] = []
    for n in nodes:
        node_dicts.append(
            {
                "id": n.id,
                "slug": n.slug,
                "description": n.description,
                "depends_on": list(n.depends_on) if n.depends_on else [],
            }
        )
    return {
        "schema_version": OBJECTIVE_SCHEMA_VERSION,
        "nodes": node_dicts,
        "phases": dict(phase_names),
    }


def _validate_manifest(data: dict[str, object]) -> tuple[Manifest | None, list[str]]:
    """Validate a parsed ``objective-manifest`` block. Returns ``(Manifest, [])`` on success, else
    ``(None, [error…])``. Mirrors :func:`validate_roadmap`'s per-node typing rules (minus
    ``status``/``pr``, which the manifest excludes) plus the ``phases`` ``{str: str}`` map."""
    schema_version = data.get("schema_version")
    if schema_version is None:
        return None, ["missing required field: schema_version"]
    if str(schema_version) != OBJECTIVE_SCHEMA_VERSION:
        return None, [f"unsupported schema_version: {schema_version!r}"]

    raw_nodes = data.get("nodes")
    if raw_nodes is None:
        return None, ["missing required field: nodes"]
    if not isinstance(raw_nodes, list):
        return None, ["field 'nodes' must be a list"]

    nodes: list[ObjectiveNode] = []
    for i, raw_item in enumerate(raw_nodes):
        if not isinstance(raw_item, dict):
            return None, [f"node {i} is not a mapping"]
        # Inject `status` (the manifest excludes it) to satisfy the required field; the model's
        # `_tolerate` before-validator drops anything the manifest doesn't declare (e.g. `pr`).
        raw = cast(dict[str, object], raw_item)
        try:
            nodes.append(ObjectiveNode.model_validate({**raw, "status": NodeStatus.PENDING.value}))
        except ValidationError as exc:
            return None, [format_validation_error(exc, source=f"node {i}")]

    raw_phases = data.get("phases")
    if raw_phases is None:
        return None, ["missing required field: phases"]
    if not isinstance(raw_phases, dict):
        return None, ["field 'phases' must be a mapping"]
    phase_names: dict[str, str] = {}
    for key, value in cast(dict[object, object], raw_phases).items():
        if not isinstance(key, str) or not isinstance(value, str):
            return None, ["field 'phases' must be a {str: str} mapping"]
        phase_names[key] = value

    return Manifest(
        schema_version=str(schema_version), nodes=tuple(nodes), phase_names=phase_names
    ), []


def parse_manifest(overview: str) -> tuple[Manifest | None, list[str]]:
    """Read + validate the ``objective-manifest`` block from a project overview.

    Three cases, with an explicit **absent vs malformed** distinction: **no block** → ``(None, [])``
    (a valid backfill target — a pre-manifest objective); **block present but malformed/invalid** →
    ``(None, [error…])`` (damaged — drift detection must halt loud, never diff a corrupt baseline);
    **valid** → ``(Manifest, [])``.
    """
    if not _has_block(overview, OBJECTIVE_MANIFEST_KEY):
        return None, []
    block = find_metadata_block(overview, OBJECTIVE_MANIFEST_KEY)
    if block is None:
        return None, ["objective-manifest block is present but malformed (unparseable YAML)"]
    return _validate_manifest(block)
