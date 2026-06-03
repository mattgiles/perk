"""Objective storage + mechanics — the plan factory's deterministic foundation (P2.T9).

An **objective** is a long-running goal that *generates* bounded plans rather than being
implemented directly (PRIOR_ART §3). This module is the **deterministic mechanics only**: a
pure storage-block engine + roadmap frontmatter parser + dependency-graph next-node selection
+ surgical node mutation. The `objective-plan` registry stage, the plan factory, and the
model-facing bounded transition tools are **T10** — not built here.

Pure and deterministic — **no Click, no subprocess, no network**, mirroring :mod:`perk.plan`.
The metadata-block engine is reused verbatim from :mod:`perk.plan`
(``render_metadata_block`` / ``replace_metadata_block`` / ``find_metadata_block``) — those
functions are already generic, so the objective header *and* roadmap blocks reuse them
directly; only the roadmap node validation/serialization and the rendered table are new.

Storage shape (PRIOR_ART §3, erk's objective storage-format, perk-namespaced + schema 1):

- **Issue body** holds two blocks: ``objective-header`` (compact, queryable run/status) and
  ``objective-roadmap`` (the canonical flat-node YAML frontmatter — the source of truth).
- **First comment** holds the ``objective-body`` block: a human-readable rendered roadmap table
  (deterministically re-rendered from the frontmatter) plus prose.

**Explicit-status-only** (foundation open #3): a node's status is *never* inferred from a PR
column. Setting ``pr`` never changes ``status`` — the departure from erk's two-tier
infer-from-PR model.
"""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, cast

from perk.plan import find_metadata_block, render_metadata_block

OBJECTIVE_LABEL = "perk:objective"
OBJECTIVE_LABEL_COLOR = "5319e7"  # indigo (distinct from plan green / learn purple)
OBJECTIVE_LABEL_DESCRIPTION = "perk objective issue"

OBJECTIVE_HEADER_KEY = "objective-header"
OBJECTIVE_ROADMAP_KEY = "objective-roadmap"
OBJECTIVE_BODY_KEY = "objective-body"

# perk starts its OWN objective schema at 1 — it does not inherit erk's "2"/"3"/"4".
OBJECTIVE_SCHEMA_VERSION = "1"

# The valid `objective-header` field names (LBYL on the staged-population schema, mirroring
# plan.PLAN_HEADER_FIELDS). `status` is the objective-level rollup, stored explicitly.
OBJECTIVE_HEADER_FIELDS = frozenset({"run_id", "created", "objective_comment_id", "status"})

# The human-readable rendered-table markers spliced into the `objective-body` comment.
ROADMAP_TABLE_MARKER_START = "<!-- perk:roadmap-table -->"
ROADMAP_TABLE_MARKER_END = "<!-- /perk:roadmap-table -->"

_METADATA_OPEN = "<!-- perk:metadata-block:{key} -->"


class NodeStatus(StrEnum):
    """A roadmap node's explicit status (open #3: never inferred from a PR column)."""

    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


# The terminal statuses (a dependency is "satisfied" only when terminal).
TERMINAL: frozenset[NodeStatus] = frozenset({NodeStatus.DONE, NodeStatus.SKIPPED})

_VALID_STATUS_VALUES = frozenset(s.value for s in NodeStatus)


@dataclass(frozen=True)
class ObjectiveNode:
    """A single node in an objective roadmap.

    ``depends_on`` is ``None`` (unspecified → infer sequential deps) vs ``()`` (explicitly no
    deps). ``pr`` is ``None`` or ``"#456"``. ``slug``/``comment`` are optional.
    """

    id: str
    description: str
    status: NodeStatus
    pr: str | None = None
    depends_on: tuple[str, ...] | None = None
    slug: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class ObjectiveHeader:
    """Compact, queryable objective metadata stored in the issue *body* (the
    ``objective-header`` block). ``status`` is the objective-level rollup, stored explicitly
    (never inferred from PR state). ``objective_comment_id`` is backfilled in the two-step
    create (it is unknown until the body comment is posted)."""

    run_id: str
    created: str  # ISO-8601 UTC (see plan.now_iso)
    objective_comment_id: int | None = None
    status: str = "active"

    def to_data(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "created": self.created,
            "objective_comment_id": self.objective_comment_id,
            "status": self.status,
        }


# --------------------------------------------------------------------- parsing / validation


def _has_block(text: str, key: str) -> bool:
    return _METADATA_OPEN.format(key=key) in text


def validate_roadmap(data: dict[str, Any]) -> tuple[list[ObjectiveNode], list[str]]:
    """Validate a parsed roadmap block (``{schema_version, nodes:[…]}``) against the schema.

    Returns ``(nodes, errors)``; on any error ``nodes`` is ``[]``. Required per-node fields:
    ``id``/``description``/``status`` (typed, ``status`` a valid :class:`NodeStatus`). Optional:
    ``pr``/``depends_on``/``slug``/``comment``.
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
        raw = cast(dict[str, Any], raw_item)
        for field in ("id", "description", "status"):
            if field not in raw:
                return [], [f"node {i} missing required field: {field}"]
        node_id = raw["id"]
        description = raw["description"]
        status = raw["status"]
        if not isinstance(node_id, str):
            return [], [f"node {i} field 'id' must be a string"]
        if not isinstance(description, str):
            return [], [f"node {i} field 'description' must be a string"]
        if not isinstance(status, str) or status not in _VALID_STATUS_VALUES:
            return [], [
                f"node {i} field 'status' must be one of: {', '.join(sorted(_VALID_STATUS_VALUES))}"
            ]

        raw_pr = raw.get("pr")
        if raw_pr is not None and not isinstance(raw_pr, str):
            return [], [f"node {i} field 'pr' must be a string or null"]

        raw_depends = raw.get("depends_on")
        depends_on: tuple[str, ...] | None = None
        if raw_depends is not None:
            if not isinstance(raw_depends, list):
                return [], [f"node {i} field 'depends_on' must be a list or null"]
            for j, item in enumerate(raw_depends):
                if not isinstance(item, str):
                    return [], [f"node {i} field 'depends_on' item {j} must be a string"]
            depends_on = tuple(raw_depends)

        raw_slug = raw.get("slug")
        if raw_slug is not None and not isinstance(raw_slug, str):
            return [], [f"node {i} field 'slug' must be a string or null"]
        raw_comment = raw.get("comment")
        if raw_comment is not None and not isinstance(raw_comment, str):
            return [], [f"node {i} field 'comment' must be a string or null"]

        nodes.append(
            ObjectiveNode(
                id=node_id,
                description=description,
                status=NodeStatus(status),
                pr=raw_pr,
                depends_on=depends_on,
                slug=raw_slug,
                comment=raw_comment,
            )
        )
    return nodes, errors


def parse_roadmap_nodes(issue_body: str) -> tuple[list[ObjectiveNode], list[str]]:
    """Read + validate the ``objective-roadmap`` block from an issue body.

    Three cases: **no block** ⇒ ``([], [])`` (a valid roadmap-free objective); **block present
    but malformed/invalid** ⇒ ``([], [error])``; **valid** ⇒ ``(nodes, [])``.
    """
    if not _has_block(issue_body, OBJECTIVE_ROADMAP_KEY):
        return [], []
    block = find_metadata_block(issue_body, OBJECTIVE_ROADMAP_KEY)
    if block is None:
        return [], ["objective-roadmap block is present but malformed (unparseable YAML)"]
    return validate_roadmap(block)


def render_roadmap_block(nodes: list[ObjectiveNode]) -> dict[str, object]:
    """Build the data dict for ``render_metadata_block(OBJECTIVE_ROADMAP_KEY, …)``.

    ``depends_on``/``comment`` columns are omitted unless some node specifies them (matching
    erk's compact serialization).
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


# --------------------------------------------------------------------- phase derivation


def derive_phase(node_id: str) -> tuple[int, str]:
    """The ``(number, suffix)`` phase a node belongs to, from its ID prefix.

    ``"1.2" → (1, "")``, ``"2A.1" → (2, "A")``, ``"3" → (1, "")`` (no dot ⇒ phase 1).
    """
    if "." not in node_id:
        return (1, "")
    phase_id = node_id.rsplit(".", 1)[0]
    match = re.match(r"^(\d+)([A-Z]*)", phase_id)
    if match:
        return (int(match.group(1)), match.group(2))
    return (1, "")


def group_nodes_by_phase(
    nodes: list[ObjectiveNode],
) -> list[tuple[tuple[int, str], list[ObjectiveNode]]]:
    """Group nodes by their derived ``(number, suffix)`` phase key, sorted by phase."""
    phase_map: dict[tuple[int, str], list[ObjectiveNode]] = {}
    for node in nodes:
        phase_map.setdefault(derive_phase(node.id), []).append(node)
    return sorted(phase_map.items(), key=lambda kv: kv[0])


def phase_label(key: tuple[int, str]) -> str:
    """The default ``Phase N[A]`` label for a phase key (names are not stored)."""
    return f"Phase {key[0]}{key[1]}"


def enrich_phase_names(body: str, keys: list[tuple[int, str]]) -> dict[tuple[int, str], str]:
    """Extract ``### Phase N[A]: name`` headers from ``body`` for the given phase keys.

    Returns a ``{phase_key: name}`` map; keys without a header fall back to :func:`phase_label`.
    """
    pattern = re.compile(
        r"^###\s+Phase\s+(\d+)([A-Z]?):\s*(.+?)(?:\s+\(\d+\s+PR\))?$", re.MULTILINE
    )
    found: dict[tuple[int, str], str] = {}
    for match in pattern.finditer(body):
        found[(int(match.group(1)), match.group(2))] = match.group(3).strip()
    return {key: found.get(key, phase_label(key)) for key in keys}


# --------------------------------------------------------------- mutation (explicit-status-only)


def update_node(
    nodes: list[ObjectiveNode],
    node_id: str,
    *,
    status: NodeStatus | None = None,
    pr: str | None = None,
    description: str | None = None,
    slug: str | None = None,
    comment: str | None = None,
) -> list[ObjectiveNode] | None:
    """Return a new node list with ``node_id`` updated, or ``None`` if not found.

    Unset fields are preserved. ``pr``: ``None`` preserves, ``""`` clears, ``"#N"`` sets.
    **``status`` is taken verbatim or preserved — never inferred from ``pr``** (open #3).
    """
    found = False
    updated: list[ObjectiveNode] = []
    for node in nodes:
        if node.id != node_id:
            updated.append(node)
            continue
        found = True
        if pr is None:
            resolved_pr = node.pr
        elif pr:
            resolved_pr = pr
        else:
            resolved_pr = None
        changes: dict[str, Any] = {"pr": resolved_pr}
        if status is not None:
            changes["status"] = status
        if description is not None:
            changes["description"] = description
        if slug is not None:
            changes["slug"] = slug
        if comment is not None:
            changes["comment"] = comment
        updated.append(replace(node, **changes))
    return updated if found else None


def add_node(
    nodes: list[ObjectiveNode],
    *,
    phase: int,
    description: str,
    status: NodeStatus = NodeStatus.PENDING,
    slug: str | None = None,
    depends_on: tuple[str, ...] | None = None,
    comment: str | None = None,
) -> tuple[list[ObjectiveNode], str] | None:
    """Add a node to ``phase``, auto-assigning the next ``<phase>.<n>`` id and inserting it
    after that phase's last node. Returns ``(nodes, new_id)`` or ``None`` on a (defensive)
    id collision."""
    prefix = f"{phase}."
    max_num = 0
    last_index = -1
    for i, node in enumerate(nodes):
        if node.id.startswith(prefix):
            suffix = node.id[len(prefix) :]
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
            last_index = i
    new_id = f"{phase}.{max_num + 1}"
    if any(node.id == new_id for node in nodes):
        return None
    new_node = ObjectiveNode(
        id=new_id,
        description=description,
        status=status,
        pr=None,
        depends_on=depends_on,
        slug=slug if slug is not None else slugify_description(description),
        comment=comment,
    )
    insert_at = last_index + 1 if last_index >= 0 else len(nodes)
    updated = list(nodes)
    updated.insert(insert_at, new_node)
    return updated, new_id


def slugify_description(description: str) -> str:
    """Lowercase kebab-case slug (collapse non-alphanumerics, strip edges)."""
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower())
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


# --------------------------------------------------------------------- dependency graph


@dataclass(frozen=True)
class DependencyGraph:
    """A DAG of objective nodes with resolved (never-``None``) dependency edges."""

    nodes: tuple[ObjectiveNode, ...]

    def _node_map(self) -> dict[str, ObjectiveNode]:
        return {node.id: node for node in self.nodes}

    def unblocked_nodes(self) -> list[ObjectiveNode]:
        """Nodes whose dependencies are all terminal (``done``/``skipped``)."""
        node_map = self._node_map()
        result: list[ObjectiveNode] = []
        for node in self.nodes:
            deps = node.depends_on or ()
            if all(node_map[dep].status in TERMINAL for dep in deps if dep in node_map):
                result.append(node)
        return result

    def pending_unblocked_nodes(self) -> list[ObjectiveNode]:
        """All unblocked ``pending`` nodes, in position order."""
        return [n for n in self.unblocked_nodes() if n.status == NodeStatus.PENDING]

    def next_node(self) -> ObjectiveNode | None:
        """The first unblocked pending node by position, else ``None``."""
        pending = self.pending_unblocked_nodes()
        return pending[0] if pending else None

    def is_complete(self) -> bool:
        """True when every node is terminal."""
        return all(node.status in TERMINAL for node in self.nodes)


def _graph_from_sequential(nodes: list[ObjectiveNode]) -> DependencyGraph:
    """Infer sequential deps: first node of a phase → last of the previous phase; subsequent
    nodes → the previous node in the same phase."""
    resolved: list[ObjectiveNode] = []
    last_of_prev_phase: str | None = None
    for _key, phase_nodes in group_nodes_by_phase(nodes):
        prev_id: str | None = None
        for i, node in enumerate(phase_nodes):
            if i == 0 and last_of_prev_phase is not None:
                deps: tuple[str, ...] = (last_of_prev_phase,)
            elif prev_id is not None:
                deps = (prev_id,)
            else:
                deps = ()
            resolved.append(replace(node, depends_on=deps))
            prev_id = node.id
        if phase_nodes:
            last_of_prev_phase = phase_nodes[-1].id
    return DependencyGraph(nodes=tuple(resolved))


def build_graph(nodes: list[ObjectiveNode]) -> DependencyGraph:
    """Build the dependency graph. When any node has explicit ``depends_on`` use those
    (``None`` → ``()``); otherwise infer sequential deps from phase ordering."""
    if any(node.depends_on is not None for node in nodes):
        return DependencyGraph(
            nodes=tuple(replace(n, depends_on=n.depends_on or ()) for n in nodes)
        )
    return _graph_from_sequential(nodes)


def summary(nodes: list[ObjectiveNode]) -> dict[str, int]:
    """Per-status counts + total (the objective-progress rollup)."""
    counts = {status.value: 0 for status in NodeStatus}
    for node in nodes:
        counts[node.status.value] += 1
    counts["total"] = len(nodes)
    return counts


# --------------------------------------------------------------------- rendered table


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


def render_body_comment(nodes: list[ObjectiveNode], *, prose: str = "") -> str:
    """Render the ``objective-body`` comment content: marker-bounded rendered table + prose."""
    table = render_roadmap_table(nodes)
    block = (
        f"{ROADMAP_TABLE_MARKER_START}\n{table}\n{ROADMAP_TABLE_MARKER_END}"
        if table
        else f"{ROADMAP_TABLE_MARKER_START}\n_(no roadmap nodes yet)_\n{ROADMAP_TABLE_MARKER_END}"
    )
    return f"{block}\n\n{prose.strip()}".rstrip() + "\n" if prose.strip() else block + "\n"


def rerender_body_table(comment_body: str, nodes: list[ObjectiveNode]) -> str | None:
    """Re-render the marker-bounded table inside an existing ``objective-body`` comment from the
    authoritative ``nodes``. Returns the updated comment, or ``None`` if no markers are found."""
    start = comment_body.find(ROADMAP_TABLE_MARKER_START)
    if start == -1:
        return None
    end = comment_body.find(ROADMAP_TABLE_MARKER_END, start)
    if end == -1:
        return None
    table = render_roadmap_table(nodes, body=comment_body)
    return (
        comment_body[:start]
        + ROADMAP_TABLE_MARKER_START
        + "\n"
        + table
        + "\n"
        + ROADMAP_TABLE_MARKER_END
        + comment_body[end + len(ROADMAP_TABLE_MARKER_END) :]
    )


def render_metadata_block_for(key: str, data: dict[str, object]) -> str:
    """Thin re-export so callers can render objective blocks without importing :mod:`perk.plan`
    directly (the block engine lives there)."""
    return render_metadata_block(key, data)
