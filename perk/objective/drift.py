"""The pure objective drift engine (Objective #548, Node 4.4 / #612).

Drift detection is ``diff(manifest, observed)``: the persisted ``objective-manifest`` (the intended
roadmap's structural identity — :class:`perk.objective.Manifest`) is the **expected** baseline; the
live Linear project state (node-issues, blocking relations, milestones, overview integrity) is
**observed**. This module is the diff only — **pure, deterministic, fully offline** (no network, no
clock, no Click). The store builds the :class:`ObservedSnapshot` (network) and calls
:func:`detect_drift`; the condition catalog is unit-tested without a fake Linear.

Each :class:`DriftCondition` carries a stable machine ``code``, a ``severity``, and a ``repairable``
flag. ``--fix`` only converges the **safe, unambiguous** (``repairable``) cases — everything else is
report-only, because auto-repair would *invent* information perk has no authority to invent
(the never-silently-reinterpret principle).
"""

from dataclasses import dataclass
from enum import StrEnum

from perk.objective._models import NodeStatus
from perk.objective.graph import node_sort_key
from perk.objective.manifest import Manifest


class DriftCode(StrEnum):
    """The stable machine codes for each drift condition (the §4 catalog)."""

    MANIFEST_ABSENT = "manifest_absent"
    MANIFEST_MALFORMED = "manifest_malformed"
    MISSING_NODE_ISSUE = "missing_node_issue"
    DUPLICATE_NODE_IDS = "duplicate_node_ids"
    MISSING_NODE_STATUS_BLOCK = "missing_node_status_block"
    BLOCKING_RELATION_CYCLE = "blocking_relation_cycle"
    UNKNOWN_BLOCKER_REFERENCE = "unknown_blocker_reference"
    DEPENDENCY_MISSING_IN_LINEAR = "dependency_missing_in_linear"
    DEPENDENCY_EXTRA_IN_LINEAR = "dependency_extra_in_linear"
    DELETED_PHASE_MILESTONE = "deleted_phase_milestone"
    RENAMED_PHASE_MILESTONE = "renamed_phase_milestone"
    OVERVIEW_MARKER_DAMAGE = "overview_marker_damage"


class ObjectiveDriftSeverity(StrEnum):
    """A drift condition's severity."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ObservedNode:
    """One observed node-issue's drift-relevant state (built from the live Linear project).

    ``node_id`` is ``None`` when the ``objective-node`` block is malformed beyond an id;
    ``block_valid`` is ``False`` when the block is absent/malformed (missing/invalid status).
    ``depends_on_observed`` are the in-objective node ids this node is blocked by (resolved through
    the same identifier→node-id map :meth:`get_objective` builds); ``unknown_blockers`` are blocker
    identifiers that do **not** resolve to an in-objective node (retained, never dropped).
    """

    node_id: str | None
    identifier: str
    status: NodeStatus | None
    milestone_name: str | None
    has_plan_header: bool
    depends_on_observed: tuple[str, ...]
    unknown_blockers: tuple[str, ...]
    block_valid: bool


@dataclass(frozen=True)
class ObservedSnapshot:
    """The complete offline-constructible drift input: the manifest baseline + observed state."""

    manifest: Manifest | None
    manifest_errors: tuple[str, ...]
    nodes: tuple[ObservedNode, ...]
    milestone_names: tuple[str, ...]
    header_ok: bool
    reconcilable_ok: bool


@dataclass(frozen=True)
class DriftCondition:
    """A single detected drift condition (a row of the §4 catalog)."""

    code: DriftCode
    severity: ObjectiveDriftSeverity
    node_id: str | None
    target: str | None
    message: str
    repairable: bool


@dataclass(frozen=True)
class DriftReport:
    """An ordered, immutable collection of detected drift conditions."""

    conditions: tuple[DriftCondition, ...] = ()


def _sorted_nodes(nodes: tuple[ObservedNode, ...]) -> list[ObservedNode]:
    """Observed nodes in deterministic roadmap order (node-id sorted; id-less nodes last)."""
    return sorted(
        nodes,
        key=lambda n: (1, "", 0, 0, "") if n.node_id is None else node_sort_key(n.node_id),
    )


def _find_cycle(edges: dict[str, set[str]]) -> bool:
    """True when the directed graph ``edges`` (``blocker → blocked``) contains a cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in edges}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for nxt in edges.get(node, set()):
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                return True
            if color[nxt] == WHITE and visit(nxt):
                return True
        color[node] = BLACK
        return False

    return any(color[node] == WHITE and visit(node) for node in edges)


def detect_drift(snapshot: ObservedSnapshot) -> DriftReport:
    """Diff the manifest baseline against the observed project state (the §4 condition catalog).

    Pure + deterministic. A malformed manifest or an absent manifest short-circuits (no baseline to
    diff against); otherwise every catalog condition is emitted in a stable order.
    """
    conditions: list[DriftCondition] = []

    # A damaged manifest block disables detection entirely — never diff a corrupt baseline (halt
    # loud). A malformed manifest takes precedence over an absent one.
    if snapshot.manifest_errors:
        conditions.append(
            DriftCondition(
                code=DriftCode.MANIFEST_MALFORMED,
                severity=ObjectiveDriftSeverity.ERROR,
                node_id=None,
                target=None,
                message="objective-manifest block is malformed: "
                + "; ".join(snapshot.manifest_errors),
                repairable=False,
            )
        )
        return DriftReport(conditions=tuple(conditions))

    if snapshot.manifest is None:
        conditions.append(
            DriftCondition(
                code=DriftCode.MANIFEST_ABSENT,
                severity=ObjectiveDriftSeverity.INFO,
                node_id=None,
                target=None,
                message="no objective-manifest block in the overview — "
                "run `perk objective doctor --fix` to backfill it from the current node-issues",
                repairable=True,
            )
        )
        return DriftReport(conditions=tuple(conditions))

    manifest = snapshot.manifest
    manifest_ids = [n.id for n in manifest.nodes]

    # Overview marker integrity (report-only; does NOT halt — the manifest itself parsed fine).
    if not snapshot.header_ok or not snapshot.reconcilable_ok:
        damaged = []
        if not snapshot.header_ok:
            damaged.append("objective-header")
        if not snapshot.reconcilable_ok:
            damaged.append("Reconcilable region")
        conditions.append(
            DriftCondition(
                code=DriftCode.OVERVIEW_MARKER_DAMAGE,
                severity=ObjectiveDriftSeverity.ERROR,
                node_id=None,
                target=None,
                message="overview marker damage: " + ", ".join(damaged) + " absent or malformed",
                repairable=False,
            )
        )

    # Observed node-id index (only valid-id nodes participate in the structural diff).
    observed_by_id: dict[str, list[ObservedNode]] = {}
    for obs in snapshot.nodes:
        if obs.node_id is not None:
            observed_by_id.setdefault(obs.node_id, []).append(obs)
    observed_ids = set(observed_by_id)

    # 1 · MISSING_NODE_ISSUE — a manifest node with no observed node-issue (repairable: recreate).
    for node_id in (nid for nid in manifest_ids if nid not in observed_ids):
        conditions.append(
            DriftCondition(
                code=DriftCode.MISSING_NODE_ISSUE,
                severity=ObjectiveDriftSeverity.ERROR,
                node_id=node_id,
                target=None,
                message=f"manifest node {node_id!r} has no node-issue in the project",
                repairable=True,
            )
        )

    # 2 · DUPLICATE_NODE_IDS — ≥2 observed node-issues share a manifest id (report-only).
    for node_id in manifest_ids:
        dupes = observed_by_id.get(node_id, [])
        if len(dupes) >= 2:
            conditions.append(
                DriftCondition(
                    code=DriftCode.DUPLICATE_NODE_IDS,
                    severity=ObjectiveDriftSeverity.ERROR,
                    node_id=node_id,
                    target=", ".join(d.identifier for d in dupes),
                    message=f"node id {node_id!r} is shared by {len(dupes)} node-issues "
                    f"({', '.join(d.identifier for d in dupes)})",
                    repairable=False,
                )
            )

    # 3 · MISSING_NODE_STATUS_BLOCK — an observed node-issue with an absent/malformed block.
    for obs in _sorted_nodes(snapshot.nodes):
        if not obs.block_valid:
            conditions.append(
                DriftCondition(
                    code=DriftCode.MISSING_NODE_STATUS_BLOCK,
                    severity=ObjectiveDriftSeverity.WARNING,
                    node_id=obs.node_id,
                    target=obs.identifier,
                    message=f"node-issue {obs.identifier} has an absent or malformed "
                    "objective-node status block",
                    repairable=False,
                )
            )

    # 4 · BLOCKING_RELATION_CYCLE — a cycle in the observed blocked-by graph (manifest-enriched).
    edges: dict[str, set[str]] = {nid: set() for nid in observed_ids}
    observed_edge_set: set[tuple[str, str]] = set()
    for node_id, obs_list in observed_by_id.items():
        for obs in obs_list:
            for dep in obs.depends_on_observed:
                if dep in observed_ids:
                    edges[dep].add(node_id)  # dep BLOCKS node_id
                    observed_edge_set.add((dep, node_id))
    manifest_edge_set: set[tuple[str, str]] = {
        (dep, n.id) for n in manifest.nodes for dep in (n.depends_on or ())
    }
    if _find_cycle(edges):
        human_added = sorted(observed_edge_set - manifest_edge_set)
        added_desc = (
            "; human-added edges (not in the manifest): "
            + ", ".join(f"{dep}→{node}" for dep, node in human_added)
            if human_added
            else ""
        )
        conditions.append(
            DriftCondition(
                code=DriftCode.BLOCKING_RELATION_CYCLE,
                severity=ObjectiveDriftSeverity.ERROR,
                node_id=None,
                target=None,
                message="the observed blocking-relation graph contains a cycle" + added_desc,
                repairable=False,
            )
        )

    # 5 · UNKNOWN_BLOCKER_REFERENCE — a blocker that is not an in-objective node (disclosure).
    for obs in _sorted_nodes(snapshot.nodes):
        for blocker in obs.unknown_blockers:
            conditions.append(
                DriftCondition(
                    code=DriftCode.UNKNOWN_BLOCKER_REFERENCE,
                    severity=ObjectiveDriftSeverity.INFO,
                    node_id=obs.node_id,
                    target=blocker,
                    message=f"node-issue {obs.identifier} is blocked by {blocker}, which is not a "
                    "roadmap node — perk's roadmap graph cannot represent this external edge",
                    repairable=False,
                )
            )

    # 6 · DEPENDENCY_MISSING_IN_LINEAR — a manifest edge absent from observed (repairable: create).
    for node in manifest.nodes:
        if node.id not in observed_ids:
            continue  # MISSING_NODE_ISSUE owns it; recreate restores the relations
        observed_deps = {dep for obs in observed_by_id[node.id] for dep in obs.depends_on_observed}
        for dep in node.depends_on or ():
            if dep in observed_ids and dep not in observed_deps:
                conditions.append(
                    DriftCondition(
                        code=DriftCode.DEPENDENCY_MISSING_IN_LINEAR,
                        severity=ObjectiveDriftSeverity.WARNING,
                        node_id=node.id,
                        target=dep,
                        message=f"manifest edge {dep}→{node.id} (dep {dep} blocks {node.id}) "
                        "has no blocking relation in Linear",
                        repairable=True,
                    )
                )

    # 7 · DEPENDENCY_EXTRA_IN_LINEAR — an observed edge (both endpoints nodes) absent from manifest.
    for dep, node_id in sorted(observed_edge_set - manifest_edge_set):
        conditions.append(
            DriftCondition(
                code=DriftCode.DEPENDENCY_EXTRA_IN_LINEAR,
                severity=ObjectiveDriftSeverity.INFO,
                node_id=node_id,
                target=dep,
                message=f"Linear has a blocking relation {dep}→{node_id} not in the manifest "
                "(an intentional human edit, or stale — deleting it is a judgment call)",
                repairable=False,
            )
        )

    # 8 · DELETED_PHASE_MILESTONE — a pinned phase name matching no observed milestone (repairable).
    observed_milestones = set(snapshot.milestone_names)
    for phase_key, pinned_name in manifest.phase_names.items():
        if pinned_name not in observed_milestones:
            conditions.append(
                DriftCondition(
                    code=DriftCode.DELETED_PHASE_MILESTONE,
                    severity=ObjectiveDriftSeverity.ERROR,
                    node_id=None,
                    target=pinned_name,
                    message=f"phase {phase_key!r} milestone {pinned_name!r} is missing "
                    "(deleted or renamed) — it will be recreated and its node-issues reattached",
                    repairable=True,
                )
            )

    # 9 · RENAMED_PHASE_MILESTONE — an observed milestone whose name pins to no manifest phase.
    pinned_names = set(manifest.phase_names.values())
    for name in snapshot.milestone_names:
        if name not in pinned_names:
            conditions.append(
                DriftCondition(
                    code=DriftCode.RENAMED_PHASE_MILESTONE,
                    severity=ObjectiveDriftSeverity.WARNING,
                    node_id=None,
                    target=name,
                    message=f"milestone {name!r} matches no manifest-pinned phase name "
                    "(renamed in Linear, or an extra milestone)",
                    repairable=False,
                )
            )

    return DriftReport(conditions=tuple(conditions))
