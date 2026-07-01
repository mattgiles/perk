"""Objective dependency graph + node mechanics.

The phase-derivation / sort / grouping helpers, the explicit-status-only node mutation
(:func:`update_node` / :func:`add_node`), the node↔PR matchers (:func:`canonical_pr` /
:func:`nodes_for_pr`), and the dependency-graph constructors (:func:`build_graph` /
:func:`_graph_from_sequential`).
The :class:`DependencyGraph` / :class:`PlanSelection` dataclasses themselves live in
:mod:`perk.objective._models` (the type leaf); their constructors live here.
"""

import re
from dataclasses import replace
from typing import Any

from perk.objective._models import DependencyGraph, NodeStatus, ObjectiveNode


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


def phase_key_str(node_id: str) -> str:
    """The canonical phase-key string for a node id — ``f"{num}{suffix}"`` from :func:`derive_phase`
    (e.g. ``"1.2" → "1"``, ``"2A.1" → "2A"``). This is the manifest ``phases`` map key. Phase is
    derived from the id (the single authority), so id↔phase can never diverge."""
    num, suffix = derive_phase(node_id)
    return f"{num}{suffix}"


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


def node_sort_key(node_id: str) -> tuple[int, str, int, int, str]:
    """A deterministic natural-ordering key for a node id (shared by 3.2 create order and 3.3
    read order). Built from :func:`derive_phase` plus the trailing id segment parsed numerically
    when it is all digits (so ``3.2`` sorts before ``3.10``), else lexically. The numeric/lexical
    discriminator (``0`` vs ``1``) keeps numeric segments ahead of non-numeric ones and avoids
    mixing ``int``/``str`` in a single comparison slot.
    """
    phase_num, phase_suffix = derive_phase(node_id)
    trailing = node_id.rsplit(".", 1)[-1]
    if trailing.isdigit():
        return (phase_num, phase_suffix, 0, int(trailing), "")
    return (phase_num, phase_suffix, 1, 0, trailing)


def node_issue_title(node: ObjectiveNode, *, max_len: int = 120) -> str:
    """The node-issue title: ``"{id}: {slug}"`` when the node has a slug, else ``"{id}: "`` + the
    description truncated to ``max_len`` characters (with a ``"…"`` ellipsis when it was longer)."""
    if node.slug:
        return f"{node.id}: {node.slug}"
    description = node.description
    if len(description) > max_len:
        description = description[:max_len] + "…"
    return f"{node.id}: {description}"


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


def canonical_pr(pr_number: str | int) -> str:
    """Normalize a PR/plan number to the canonical ``"#<n>"`` form (strip a leading ``#``)."""
    return "#" + str(pr_number).lstrip("#")


def nodes_for_pr(nodes: list[ObjectiveNode], pr_number: str | int) -> list[ObjectiveNode]:
    """Return all nodes whose ``pr`` backlink equals ``pr_number`` (canonicalized to ``"#<n>"``).

    Pure + offline. Matches ``"#6"`` / ``6`` / ``"6"`` interchangeably; ignores non-matching nodes
    and nodes with no ``pr``. This is the deterministic node↔plan match the land path consumes to
    auto-mark backlinked node(s) ``done`` after a merge.
    """
    target = canonical_pr(pr_number)
    return [node for node in nodes if node.pr is not None and canonical_pr(node.pr) == target]


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
