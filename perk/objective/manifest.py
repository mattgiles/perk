"""Objective manifest — the project-overview drift baseline (Node 4.4 / #612), relocated verbatim
in the Node 2.3 module->package split.

The cohesive manifest concern: the :class:`Manifest` dataclass plus its renderer
(:func:`render_manifest_block`), parser (:func:`parse_manifest`), and validator
(:func:`_validate_manifest`). The manifest captures only the *structural identity* of a roadmap
(id/slug/description/depends_on per node + a pinned phase-name map); status/pr are excluded.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from perk.objective._models import (
    OBJECTIVE_MANIFEST_KEY,
    OBJECTIVE_SCHEMA_VERSION,
    NodeStatus,
    ObjectiveNode,
    _has_block,
)
from perk.plan import find_metadata_block


@dataclass(frozen=True)
class Manifest:
    """The persisted drift baseline of an objective's intended roadmap (Node 4.4 / #612).

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
    """Build the data dict for ``render_metadata_block(OBJECTIVE_MANIFEST_KEY, …)`` (Node 4.4).

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


def _validate_manifest(data: dict[str, Any]) -> tuple[Manifest | None, list[str]]:
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
        raw = cast(dict[str, Any], raw_item)
        for field in ("id", "description"):
            if field not in raw:
                return None, [f"node {i} missing required field: {field}"]
        node_id = raw["id"]
        description = raw["description"]
        if not isinstance(node_id, str):
            return None, [f"node {i} field 'id' must be a string"]
        if not isinstance(description, str):
            return None, [f"node {i} field 'description' must be a string"]
        raw_slug = raw.get("slug")
        if raw_slug is not None and not isinstance(raw_slug, str):
            return None, [f"node {i} field 'slug' must be a string or null"]
        raw_depends = raw.get("depends_on")
        depends_on: tuple[str, ...] = ()
        if raw_depends is not None:
            if not isinstance(raw_depends, list):
                return None, [f"node {i} field 'depends_on' must be a list or null"]
            for j, item in enumerate(raw_depends):
                if not isinstance(item, str):
                    return None, [f"node {i} field 'depends_on' item {j} must be a string"]
            depends_on = tuple(raw_depends)
        nodes.append(
            ObjectiveNode(
                id=node_id,
                description=description,
                status=NodeStatus.PENDING,
                depends_on=depends_on,
                slug=raw_slug,
            )
        )

    raw_phases = data.get("phases")
    if raw_phases is None:
        return None, ["missing required field: phases"]
    if not isinstance(raw_phases, dict):
        return None, ["field 'phases' must be a mapping"]
    phase_names: dict[str, str] = {}
    for key, value in cast(dict[Any, Any], raw_phases).items():
        if not isinstance(key, str) or not isinstance(value, str):
            return None, ["field 'phases' must be a {str: str} mapping"]
        phase_names[key] = value

    return Manifest(
        schema_version=str(schema_version), nodes=tuple(nodes), phase_names=phase_names
    ), []


def parse_manifest(overview: str) -> tuple[Manifest | None, list[str]]:
    """Read + validate the ``objective-manifest`` block from a project overview (Node 4.4).

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
