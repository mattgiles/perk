"""Objective roadmap parsing + validation.

The roadmap-block readers/validators:
:func:`validate_roadmap` (the shared per-node schema gate), :func:`parse_roadmap_nodes` (read +
validate the ``objective-roadmap`` block), :func:`parse_structured_roadmap` (the out-of-band
structured-roadmap path), and :func:`parse_adopt_mapping` (the in-place adoption side-map).
"""

from typing import cast

from pydantic import ValidationError

from perk.boundary import format_validation_error
from perk.objective._models import (
    OBJECTIVE_ROADMAP_KEY,
    OBJECTIVE_SCHEMA_VERSION,
    NodeStatus,
    ObjectiveNode,
    _has_block,
)
from perk.plan import find_metadata_block


def validate_roadmap(data: dict[str, object]) -> tuple[list[ObjectiveNode], list[str]]:
    """Validate a parsed roadmap block (``{schema_version, nodes:[…]}``) against the schema.

    Returns ``(nodes, errors)``; on any error ``nodes`` is ``[]``. Required per-node fields:
    ``id``/``description``/``status`` (typed, ``status`` a valid :class:`NodeStatus`). Optional:
    ``pr``/``depends_on``/``slug``/``comment``.

    Envelope checks (``schema_version`` / ``nodes`` is-a-list / per-item is-a-mapping) stay
    hand-written for byte-identical messages; only the per-node field validation runs on pydantic
    (:meth:`ObjectiveNode.model_validate`), which drops sibling keys like ``adopt_issue`` via the
    model's ``_tolerate`` before-validator and bails on the first failing node.
    """
    errors: list[str] = []
    schema_version = data.get("schema_version")
    if schema_version is None:
        return [], ["missing required field: schema_version"]
    if str(schema_version) != OBJECTIVE_SCHEMA_VERSION:
        return [], [f"unsupported schema_version: {schema_version!r}"]

    raw_nodes = data.get("nodes")
    if raw_nodes is None:
        return [], ["missing required field: nodes"]
    if not isinstance(raw_nodes, list):
        return [], ["field 'nodes' must be a list"]

    nodes: list[ObjectiveNode] = []
    for i, raw_item in enumerate(raw_nodes):
        if not isinstance(raw_item, dict):
            return [], [f"node {i} is not a mapping"]
        try:
            nodes.append(ObjectiveNode.model_validate(raw_item))
        except ValidationError as exc:
            return [], [format_validation_error(exc, source=f"node {i}")]
    return nodes, errors


def parse_roadmap_nodes(issue_body: str) -> tuple[list[ObjectiveNode], list[str]]:
    """Read + validate the ``objective-roadmap`` block from an issue body.

    Three cases: **no block** ⇒ ``([], [])`` (a valid roadmap-free objective); **block present
    but malformed/invalid** ⇒ ``([], [error])``; **valid** ⇒ ``(nodes, [])``.

    Roadmap-free is valid at parse/read time; creation rejects an empty roadmap — see
    :func:`perk.github.create_objective_issue` / ``perk objective create``.
    """
    if not _has_block(issue_body, OBJECTIVE_ROADMAP_KEY):
        return [], []
    block = find_metadata_block(issue_body, OBJECTIVE_ROADMAP_KEY)
    if block is None:
        return [], ["objective-roadmap block is present but malformed (unparseable YAML)"]
    return validate_roadmap(block)


def parse_structured_roadmap(raw: object) -> tuple[list[ObjectiveNode], list[str]]:
    """Validate a *structured* roadmap supplied out-of-band (the ``perk objective create
    --roadmap <json>`` path / the ``objective_save`` tool) — never hand-written YAML.

    Accepts either a bare list of node mappings (the common shape) or a full
    ``{schema_version, nodes}`` mapping. A bare list is wrapped with the current schema version
    before validation. ``None`` / ``[]`` → ``([], [])`` (a valid roadmap-free objective).
    Delegates to :func:`validate_roadmap` so the per-node rules are identical to the YAML path.

    Roadmap-free is valid at parse/read time; creation rejects an empty roadmap — see
    :func:`perk.github.create_objective_issue` / ``perk objective create``.
    """
    if raw is None:
        return [], []
    if isinstance(raw, list):
        data: dict[str, object] = {"schema_version": OBJECTIVE_SCHEMA_VERSION, "nodes": raw}
    elif isinstance(raw, dict):
        data = cast(dict[str, object], dict(raw))
        data.setdefault("schema_version", OBJECTIVE_SCHEMA_VERSION)
    else:
        return [], ["roadmap must be a JSON array of nodes (or a {schema_version, nodes} mapping)"]
    # `status` is optional on the structured path (id + description are the only required fields) —
    # default a missing/blank status to `pending` before the shared validator runs.
    nodes_raw = data.get("nodes")
    if isinstance(nodes_raw, list):
        defaulted: list[object] = []
        for item in nodes_raw:
            if isinstance(item, dict):
                node = cast(dict[str, object], item)
                if not node.get("status"):
                    defaulted.append({**node, "status": NodeStatus.PENDING.value})
                    continue
            defaulted.append(item)
        data["nodes"] = defaulted
    return validate_roadmap(data)


def parse_adopt_mapping(raw: object) -> dict[str, str]:
    """Extract the per-node ``adopt_issue`` mapping from the same raw roadmap shape
    :func:`parse_structured_roadmap` accepts (a bare list of node mappings or a
    ``{schema_version, nodes}`` mapping) — the in-place objective-adoption side-map (§8.30).

    Returns ``{node_id: source_issue_id}`` for every node carrying a non-blank string
    ``adopt_issue`` (the id/identifier of a pre-existing source issue the node adopts in place).
    Nodes without it are skipped; non-dict items are ignored (the validator already reports those).
    No existence check — the writer resolves/validates at write time. Carried **separately** from
    :class:`ObjectiveNode` so the core node dataclass (used pervasively in rendering/manifest/drift)
    stays pristine. Offline-pure.
    """
    if isinstance(raw, dict):
        nodes_raw = cast(dict[str, object], raw).get("nodes")
    elif isinstance(raw, list):
        nodes_raw = raw
    else:
        return {}
    if not isinstance(nodes_raw, list):
        return {}
    mapping: dict[str, str] = {}
    for item in nodes_raw:
        if not isinstance(item, dict):
            continue
        node = cast(dict[str, object], item)
        node_id = node.get("id")
        adopt = node.get("adopt_issue")
        if isinstance(node_id, str) and node_id and isinstance(adopt, str) and adopt.strip():
            mapping[node_id] = adopt.strip()
    return mapping
