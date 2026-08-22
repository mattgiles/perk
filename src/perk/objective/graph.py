"""Objective dependency graph + node mechanics.

The phase-derivation / sort / grouping helpers, the explicit-status-only node mutation
(:func:`update_node` / :func:`add_node`), the node↔PR matchers (:func:`canonical_pr` /
:func:`nodes_for_pr`), the dependency-graph constructors (:func:`build_graph` /
:func:`_graph_from_sequential`), and the stacked-delivery mechanics (:func:`delivery_order` /
:func:`validate_stacked_roadmap`).
The :class:`DependencyGraph` / :class:`PlanSelection` dataclasses themselves live in
:mod:`perk.objective._models` (the type leaf); their constructors live here.
"""

import heapq
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from perk.objective._models import (
    DELIVERY_TRAIN_MAX_LAYERS,
    DELIVERY_TRAIN_MIN_LAYERS,
    DependencyGraph,
    NodeStatus,
    ObjectiveNode,
)


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


def _contracted_deps(nodes: list[ObjectiveNode]) -> dict[str, set[str]]:
    """The resolved dependency edges of the NON-SKIPPED nodes, with edges through skipped nodes
    contracted transitively (a dependency on a skipped node inherits that node's own
    dependencies, recursively) and unknown dep ids dropped (validation reports those).

    Each skipped node's contracted deps are computed ONCE (memoized — shared skipped subgraphs
    must not re-expand per incoming path, or a fan-shaped skipped chain goes exponential). A
    dependency cycle lying entirely among skipped nodes raises ``ValueError``: contraction
    cannot represent it, and the caller's Kahn pass only sees non-skipped nodes, so silently
    dropping the back-edge would derive an order from an invalid graph. EVERY skipped node is
    swept (memoized, still linear) — a skipped-only cycle unreachable from any non-skipped
    node (a disconnected component, or an all-skipped roadmap) raises too, never returns
    normally.
    """
    graph = build_graph(nodes)
    node_map = {n.id: n for n in graph.nodes}
    memo: dict[str, set[str]] = {}
    in_progress: set[str] = set()

    def skipped_deps(node_id: str) -> set[str]:
        cached = memo.get(node_id)
        if cached is not None:
            return cached
        if node_id in in_progress:
            raise ValueError(f"dependency cycle among skipped delivery nodes: {node_id}")
        in_progress.add(node_id)
        expanded: set[str] = set()
        for dep in node_map[node_id].depends_on or ():
            expanded |= expand(dep)
        in_progress.discard(node_id)
        memo[node_id] = expanded
        return expanded

    def expand(dep_id: str) -> set[str]:
        node = node_map.get(dep_id)
        if node is None:
            return set()
        if node.status is not NodeStatus.SKIPPED:
            return {dep_id}
        return skipped_deps(dep_id)

    contracted: dict[str, set[str]] = {}
    for node in graph.nodes:
        if node.status is NodeStatus.SKIPPED:
            continue
        deps: set[str] = set()
        for dep in node.depends_on or ():
            deps |= expand(dep)
        contracted[node.id] = deps
    for node in graph.nodes:
        # The disconnected-component sweep: skipped nodes unreachable from any non-skipped
        # node still validate (a cycle there raises rather than silently vanishing).
        if node.status is NodeStatus.SKIPPED:
            skipped_deps(node.id)
    return contracted


def resolved_direct_deps(nodes: list[ObjectiveNode]) -> dict[str, frozenset[str]]:
    """The resolved DIRECT dependency edges of the non-skipped nodes (contracts.md §8.46).

    The public accessor over the same skip-transparent resolution :func:`delivery_order`
    uses: explicit ``depends_on`` wins, else sequential inference; edges through SKIPPED
    nodes contract transitively; unknown dep ids are dropped (validation reports those).
    Strictly direct edges otherwise — no recursive withdrawal through live nodes. Raises
    ``ValueError`` on a dependency cycle lying entirely among skipped nodes (matching
    :func:`delivery_order`).
    """
    return {node_id: frozenset(deps) for node_id, deps in _contracted_deps(nodes).items()}


def delivery_order(nodes: list[ObjectiveNode]) -> tuple[ObjectiveNode, ...]:
    """The **delivery order** (glossary: ``CONTEXT.md`` § Objective delivery): a total,
    deterministic topological order of the non-skipped roadmap nodes — **derived, never
    persisted** (contracts.md §8.42).

    Edges resolve via :func:`build_graph` (explicit ``depends_on`` wins; otherwise sequential
    inference); skipped nodes vanish from the result with their edges contracted transitively;
    then Kahn's algorithm runs with the ready pool ordered by :func:`node_sort_key` (pop the
    smallest each round) — input-order-independent. Unknown dep ids are ignored (matching
    ``DependencyGraph.unblocked_nodes``; :func:`validate_stacked_roadmap` reports them). A cycle
    raises ``ValueError`` — including one lying entirely among skipped nodes, which contraction
    cannot represent (defensive — callers run validation first, and
    :func:`validate_stacked_roadmap` reports every cycle this raises on).
    """
    node_map = {n.id: n for n in nodes}
    remaining = _contracted_deps(nodes)
    dependents: dict[str, set[str]] = {node_id: set() for node_id in remaining}
    for node_id, deps in remaining.items():
        for dep in deps:
            dependents[dep].add(node_id)
    ready = [(node_sort_key(node_id), node_id) for node_id, deps in remaining.items() if not deps]
    heapq.heapify(ready)
    order: list[ObjectiveNode] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        order.append(node_map[node_id])
        for dependent in dependents[node_id]:
            deps = remaining[dependent]
            deps.discard(node_id)
            if not deps:
                heapq.heappush(ready, (node_sort_key(dependent), dependent))
    if len(order) != len(remaining):
        stuck = sorted(node_id for node_id, deps in remaining.items() if deps)
        raise ValueError(f"dependency cycle among delivery nodes: {', '.join(stuck)}")
    return tuple(order)


def _has_cycle(edges: dict[str, set[str]]) -> bool:
    """True when the directed graph ``edges`` contains a cycle (a local DFS — the drift
    engine's cycle finder is private to it)."""
    white, gray, black = 0, 1, 2
    color = {node: white for node in edges}

    def visit(node: str) -> bool:
        color[node] = gray
        for nxt in edges.get(node, set()):
            if color.get(nxt) == gray:
                return True
            if color.get(nxt) == white and visit(nxt):
                return True
        color[node] = black
        return False

    return any(color[node] == white and visit(node) for node in edges)


def validate_stacked_roadmap(nodes: list[ObjectiveNode]) -> list[str]:
    """Strict authoring-time validation of a stacked delivery train's roadmap shape
    (contracts.md §8.42) — the :func:`perk.objective.parse.validate_roadmap`-style errors-list
    contract (``[]`` = valid).

    Checks, in order: a duplicate node id (it breaks the bijective node↔plan↔layer mapping);
    an unknown ``depends_on`` reference (on the :func:`build_graph`-resolved edges); a
    dependency cycle; and the 2-100 bound on NON-SKIPPED nodes (a one-node stacked objective is
    rejected — save it as a standalone plan instead). **No DAG-shape constraint**: fan-out,
    fan-in, and independent nodes are all explicitly valid.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        if node.id in seen:
            errors.append(f"duplicate node id: {node.id}")
        seen.add(node.id)
    graph = build_graph(nodes)
    known = {n.id for n in graph.nodes}
    edges: dict[str, set[str]] = {n.id: set() for n in graph.nodes}
    for node in graph.nodes:
        for dep in node.depends_on or ():
            if dep in known:
                edges[node.id].add(dep)
            else:
                errors.append(f"node {node.id} depends on unknown node: {dep}")
    if _has_cycle(edges):
        errors.append("the dependency graph contains a cycle")
    active = sum(1 for node in nodes if node.status is not NodeStatus.SKIPPED)
    if active < DELIVERY_TRAIN_MIN_LAYERS:
        errors.append(
            f"a stacked delivery train needs at least {DELIVERY_TRAIN_MIN_LAYERS} non-skipped "
            f"nodes (got {active}) — save a one-node objective as a standalone plan instead"
        )
    elif active > DELIVERY_TRAIN_MAX_LAYERS:
        errors.append(
            f"a stacked delivery train allows at most {DELIVERY_TRAIN_MAX_LAYERS} non-skipped "
            f"nodes (got {active})"
        )
    return errors


def validate_stacked_tail_append(
    existing: Sequence[ObjectiveNode], candidate: Sequence[ObjectiveNode]
) -> list[str]:
    """Validate one stacked-roadmap node-add as a guarded **tail-append** (contracts.md §8.66)
    — the :func:`validate_stacked_roadmap`-style errors-list contract (``[]`` = valid).

    The ready-time reconcile pass may grow an accepted-but-not-landed train only at its tail:
    the candidate is the existing roadmap plus exactly one new ``pending`` node that orders
    strictly last, with every existing identity, encoding, resolved edge, and delivery-order
    position untouched. Anything else is a structural roadmap change and routes through
    ``perk objective replan``. A ``ValueError`` from the order/edge helpers (a skipped-only
    cycle) is reported as an error string, never raised.

    Checks, in order: the complete candidate re-validates (:func:`validate_stacked_roadmap`,
    reported verbatim); exactly one new node, entering as ``pending`` only (also keeps the
    prefix check non-vacuous — a skipped node would vanish from delivery order); no
    graph-mode flip (an all-inferred roadmap flipping to explicit-edge mode silently vacates
    every inferred edge, which order comparison alone can miss); existing identities +
    ``depends_on`` encodings unchanged; resolved direct edges unchanged over the existing ids
    (catches inference shifts, e.g. a mid-roadmap phase insertion re-pointing the next
    phase's first node); and delivery-order prefix identity (the existing order is exactly
    the candidate order's prefix, the new node the single trailing element).
    """
    existing_nodes = list(existing)
    candidate_nodes = list(candidate)
    errors = validate_stacked_roadmap(candidate_nodes)
    existing_ids = {node.id for node in existing_nodes}
    new_ids = [node.id for node in candidate_nodes if node.id not in existing_ids]
    if len(candidate_nodes) != len(existing_nodes) + 1 or len(new_ids) != 1:
        errors.append(
            "a stacked tail-append adds exactly one new node "
            f"(existing {len(existing_nodes)} node(s), candidate {len(candidate_nodes)} "
            f"node(s), {len(new_ids)} new id(s))"
        )
        return errors
    new_id = new_ids[0]
    new_node = next(node for node in candidate_nodes if node.id == new_id)
    if new_node.status is not NodeStatus.PENDING:
        errors.append(
            f"a stacked tail-append enters as pending only — new node {new_id} is "
            f"{new_node.status.value}"
        )
    if any(node.depends_on is not None for node in existing_nodes) != any(
        node.depends_on is not None for node in candidate_nodes
    ):
        errors.append(
            "a stacked tail-append must not flip the roadmap between inferred and "
            "explicit-edge dependency modes"
        )
    candidate_map = {node.id: node for node in candidate_nodes}
    for node in existing_nodes:
        counterpart = candidate_map.get(node.id)
        if counterpart is None:
            errors.append(f"existing node {node.id} is missing from the candidate")
        elif counterpart.depends_on != node.depends_on:
            errors.append(f"existing node {node.id}'s depends_on encoding changed")
    try:
        existing_deps = resolved_direct_deps(existing_nodes)
        candidate_deps = resolved_direct_deps(candidate_nodes)
    except ValueError as exc:
        errors.append(str(exc))
        return errors
    candidate_existing_deps = {
        node_id: deps for node_id, deps in candidate_deps.items() if node_id != new_id
    }
    if candidate_existing_deps != existing_deps:
        changed = sorted(
            node_id
            for node_id in set(existing_deps) | set(candidate_existing_deps)
            if existing_deps.get(node_id) != candidate_existing_deps.get(node_id)
        )
        errors.append(
            "a stacked tail-append must not change existing resolved dependencies "
            f"(changed: {', '.join(changed)})"
        )
    try:
        existing_order = [node.id for node in delivery_order(existing_nodes)]
        candidate_order = [node.id for node in delivery_order(candidate_nodes)]
    except ValueError as exc:
        errors.append(str(exc))
        return errors
    if candidate_order != [*existing_order, new_id]:
        errors.append(
            "a stacked tail-append must order strictly last — expected delivery order "
            f"{', '.join([*existing_order, new_id])}; got {', '.join(candidate_order)}"
        )
    return errors


def summary(nodes: list[ObjectiveNode]) -> dict[str, int]:
    """Per-status counts + total (the objective-progress rollup)."""
    counts = {status.value: 0 for status in NodeStatus}
    for node in nodes:
        counts[node.status.value] += 1
    counts["total"] = len(nodes)
    return counts
