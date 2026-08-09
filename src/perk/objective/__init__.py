"""Objective storage + mechanics — the plan factory's deterministic foundation.

An **objective** is a long-running goal that *generates* bounded plans rather than being
implemented directly. This package is the **deterministic mechanics only**: a
pure storage-block engine + roadmap frontmatter parser + dependency-graph next-node selection
+ surgical node mutation. The `objective-plan` registry stage, the plan factory, and the
model-facing bounded transition tools live elsewhere — not here.

Pure and deterministic — **no Click, no subprocess, no network**, mirroring :mod:`perk.plan`.
The metadata-block engine is reused verbatim from :mod:`perk.plan`
(``render_metadata_block`` / ``replace_metadata_block`` / ``find_metadata_block``) — those
functions are already generic, so the objective header *and* roadmap blocks reuse them
directly; only the roadmap node validation/serialization and the rendered table are new.

Storage shape (perk-namespaced + schema 1):

- **Issue body** holds two blocks: ``objective-header`` (compact, queryable run/status) and
  ``objective-roadmap`` (the canonical flat-node YAML frontmatter — the source of truth).
- **First comment** holds the ``objective-body`` block: a human-readable rendered roadmap table
  (deterministically re-rendered from the frontmatter) plus prose.

**Explicit-status-only** (foundation open #3): a node's status is *never* inferred from a PR
column. Setting ``pr`` never changes ``status``.

**Package layout.** This
``__init__`` re-exports every public symbol plus the test-reached privates behind a sorted
``__all__``, preserving the ``objective.X`` attribute-access import path. ``add_node`` is a
facade global so the
``monkeypatch.setattr(objective, "add_node", …)`` site in ``test_github`` rebinds the name the
lone caller (``perk.github.objectives``) reads through the facade. Submodules:

- ``_models`` — the type leaf: module constants/markers, :class:`NodeStatus` + its category sets,
  :class:`DeliveryPolicy` + the train bounds, the dataclasses (:class:`ObjectiveNode` /
  :class:`ObjectiveHeader` / :class:`PlanSelection` / :class:`DependencyGraph`), and the
  dual-encoding marker helpers.
- ``parse`` — the roadmap-block readers/validators + the delivery-policy read classifier.
- ``render`` — the byte-stable body/table/update-composer renderers.
- ``manifest`` — :class:`Manifest` + its render/parse/validate concern (the drift baseline).
- ``graph`` — the phase/sort helpers, node mutation, node↔PR matchers, graph constructors, and
  the stacked-delivery mechanics (:func:`delivery_order` / :func:`validate_stacked_roadmap`).
"""

from perk.objective._models import (
    _INLINE_MARKER_RE,
    _VALID_STATUS_VALUES,
    ADOPTED_OVERVIEW_MARKER,
    DELIVERY_TRAIN_MAX_LAYERS,
    DELIVERY_TRAIN_MIN_LAYERS,
    IN_FLIGHT,
    OBJECTIVE_BODY_KEY,
    OBJECTIVE_HEADER_FIELDS,
    OBJECTIVE_HEADER_KEY,
    OBJECTIVE_LABEL,
    OBJECTIVE_LABEL_COLOR,
    OBJECTIVE_LABEL_DESCRIPTION,
    OBJECTIVE_MANIFEST_KEY,
    OBJECTIVE_NODE_KEY,
    OBJECTIVE_NODE_LABEL,
    OBJECTIVE_NODE_LABEL_COLOR,
    OBJECTIVE_NODE_LABEL_DESCRIPTION,
    OBJECTIVE_RECONCILABLE_MARKER_END,
    OBJECTIVE_RECONCILABLE_MARKER_START,
    OBJECTIVE_ROADMAP_KEY,
    OBJECTIVE_SCHEMA_VERSION,
    PLANNABLE,
    ROADMAP_TABLE_MARKER_END,
    ROADMAP_TABLE_MARKER_START,
    TERMINAL,
    DeliveryPolicy,
    DependencyGraph,
    NodeStatus,
    ObjectiveHeader,
    ObjectiveNode,
    ObjectiveNodeEntry,
    PlanSelection,
    _find_marker_pair,
    _has_block,
    _inline_marker,
    mint_delivery_lineage,
)
from perk.objective.graph import (
    _graph_from_sequential,
    add_node,
    build_graph,
    canonical_pr,
    delivery_order,
    derive_phase,
    enrich_phase_names,
    group_nodes_by_phase,
    node_issue_title,
    node_sort_key,
    nodes_for_pr,
    phase_key_str,
    phase_label,
    slugify_description,
    summary,
    update_node,
    validate_stacked_roadmap,
)
from perk.objective.manifest import (
    Manifest,
    _validate_manifest,
    parse_manifest,
    parse_manifest_data,
    render_manifest_block,
)
from perk.objective.parse import (
    delivery_policy,
    parse_adopt_mapping,
    parse_roadmap_nodes,
    parse_structured_roadmap,
    validate_roadmap,
)
from perk.objective.render import (
    _escape_cell,
    objective_callout,
    objective_created_update_body,
    plan_landed_update_body,
    reconciled_update_body,
    render_adopted_overview_note,
    render_body_comment,
    render_header_block,
    render_node_block,
    render_roadmap_block,
    render_roadmap_table,
    replace_reconcilable_section,
    rerender_body_table,
)

__all__ = [
    "ADOPTED_OVERVIEW_MARKER",
    "DELIVERY_TRAIN_MAX_LAYERS",
    "DELIVERY_TRAIN_MIN_LAYERS",
    "IN_FLIGHT",
    "OBJECTIVE_BODY_KEY",
    "OBJECTIVE_HEADER_FIELDS",
    "OBJECTIVE_HEADER_KEY",
    "OBJECTIVE_LABEL",
    "OBJECTIVE_LABEL_COLOR",
    "OBJECTIVE_LABEL_DESCRIPTION",
    "OBJECTIVE_MANIFEST_KEY",
    "OBJECTIVE_NODE_KEY",
    "OBJECTIVE_NODE_LABEL",
    "OBJECTIVE_NODE_LABEL_COLOR",
    "OBJECTIVE_NODE_LABEL_DESCRIPTION",
    "OBJECTIVE_RECONCILABLE_MARKER_END",
    "OBJECTIVE_RECONCILABLE_MARKER_START",
    "OBJECTIVE_ROADMAP_KEY",
    "OBJECTIVE_SCHEMA_VERSION",
    "PLANNABLE",
    "ROADMAP_TABLE_MARKER_END",
    "ROADMAP_TABLE_MARKER_START",
    "TERMINAL",
    "_INLINE_MARKER_RE",
    "_VALID_STATUS_VALUES",
    "DeliveryPolicy",
    "DependencyGraph",
    "Manifest",
    "NodeStatus",
    "ObjectiveHeader",
    "ObjectiveNode",
    "ObjectiveNodeEntry",
    "PlanSelection",
    "_escape_cell",
    "_find_marker_pair",
    "_graph_from_sequential",
    "_has_block",
    "_inline_marker",
    "_validate_manifest",
    "add_node",
    "build_graph",
    "canonical_pr",
    "delivery_order",
    "delivery_policy",
    "derive_phase",
    "enrich_phase_names",
    "group_nodes_by_phase",
    "mint_delivery_lineage",
    "node_issue_title",
    "node_sort_key",
    "nodes_for_pr",
    "objective_callout",
    "objective_created_update_body",
    "parse_adopt_mapping",
    "parse_manifest",
    "parse_manifest_data",
    "parse_roadmap_nodes",
    "parse_structured_roadmap",
    "phase_key_str",
    "phase_label",
    "plan_landed_update_body",
    "reconciled_update_body",
    "render_adopted_overview_note",
    "render_body_comment",
    "render_header_block",
    "render_manifest_block",
    "render_node_block",
    "render_roadmap_block",
    "render_roadmap_table",
    "replace_reconcilable_section",
    "rerender_body_table",
    "slugify_description",
    "summary",
    "update_node",
    "validate_roadmap",
    "validate_stacked_roadmap",
]
