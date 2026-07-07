"""The pure objective drift engine.

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

The catalog is a declarative check table (``_CHECKS``): one frozen :class:`_CheckSpec` row per
:class:`DriftCode`, declaring the code's fixed ``severity``/``repairable`` classification once and
pairing it with a finder that only produces findings — the table order defines the stable report
order.
"""

from collections.abc import Callable
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


@dataclass(frozen=True)
class _Finding:
    """One detected instance of a condition — only what varies per hit (the spec owns the rest)."""

    message: str
    node_id: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class _DriftContext:
    """The shared derived indices, built once per detection pass.

    Only reached when the manifest parsed — ``manifest`` is non-``None`` by construction. This is
    the whole input surface of a check: finders read only from here.
    """

    snapshot: ObservedSnapshot
    manifest: Manifest
    manifest_ids: tuple[str, ...]
    # Only valid-id nodes participate in the structural diff.
    observed_by_id: dict[str, tuple[ObservedNode, ...]]
    observed_ids: frozenset[str]
    # Observed nodes in deterministic roadmap order (node-id sorted; id-less nodes last).
    sorted_nodes: tuple[ObservedNode, ...]
    # Edges are (blocker, blocked); observed edges keep only in-objective endpoints.
    observed_edges: frozenset[tuple[str, str]]
    manifest_edges: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class _CheckSpec:
    """One row of the §4 catalog: the code's fixed classification + its finding producer."""

    code: DriftCode
    severity: ObjectiveDriftSeverity
    repairable: bool
    find: Callable[[_DriftContext], list[_Finding]]


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


def _build_context(snapshot: ObservedSnapshot, manifest: Manifest) -> _DriftContext:
    """Build the shared derived indices every finder reads (one pass per detection)."""
    grouped: dict[str, list[ObservedNode]] = {}
    for obs in snapshot.nodes:
        if obs.node_id is not None:
            grouped.setdefault(obs.node_id, []).append(obs)
    observed_by_id = {node_id: tuple(obs_list) for node_id, obs_list in grouped.items()}
    observed_ids = frozenset(observed_by_id)
    observed_edges: set[tuple[str, str]] = set()
    for node_id, obs_list in observed_by_id.items():
        for obs in obs_list:
            for dep in obs.depends_on_observed:
                if dep in observed_ids:
                    observed_edges.add((dep, node_id))  # dep BLOCKS node_id
    manifest_edges = frozenset((dep, n.id) for n in manifest.nodes for dep in (n.depends_on or ()))
    return _DriftContext(
        snapshot=snapshot,
        manifest=manifest,
        manifest_ids=tuple(n.id for n in manifest.nodes),
        observed_by_id=observed_by_id,
        observed_ids=observed_ids,
        sorted_nodes=tuple(_sorted_nodes(snapshot.nodes)),
        observed_edges=frozenset(observed_edges),
        manifest_edges=manifest_edges,
    )


def _find_overview_marker_damage(ctx: _DriftContext) -> list[_Finding]:
    """Overview marker integrity (report-only; does NOT halt — the manifest itself parsed fine)."""
    if ctx.snapshot.header_ok and ctx.snapshot.reconcilable_ok:
        return []
    damaged = []
    if not ctx.snapshot.header_ok:
        damaged.append("objective-header")
    if not ctx.snapshot.reconcilable_ok:
        damaged.append("Reconcilable region")
    return [
        _Finding(message="overview marker damage: " + ", ".join(damaged) + " absent or malformed")
    ]


def _find_missing_node_issue(ctx: _DriftContext) -> list[_Finding]:
    """A manifest node with no observed node-issue (repairable: recreate)."""
    return [
        _Finding(
            message=f"manifest node {node_id!r} has no node-issue in the project",
            node_id=node_id,
        )
        for node_id in ctx.manifest_ids
        if node_id not in ctx.observed_ids
    ]


def _find_duplicate_node_ids(ctx: _DriftContext) -> list[_Finding]:
    """≥2 observed node-issues share a manifest id (report-only)."""
    findings: list[_Finding] = []
    for node_id in ctx.manifest_ids:
        dupes = ctx.observed_by_id.get(node_id, ())
        if len(dupes) >= 2:
            findings.append(
                _Finding(
                    message=f"node id {node_id!r} is shared by {len(dupes)} node-issues "
                    f"({', '.join(d.identifier for d in dupes)})",
                    node_id=node_id,
                    target=", ".join(d.identifier for d in dupes),
                )
            )
    return findings


def _find_missing_node_status_block(ctx: _DriftContext) -> list[_Finding]:
    """An observed node-issue with an absent/malformed status block."""
    return [
        _Finding(
            message=f"node-issue {obs.identifier} has an absent or malformed "
            "objective-node status block",
            node_id=obs.node_id,
            target=obs.identifier,
        )
        for obs in ctx.sorted_nodes
        if not obs.block_valid
    ]


def _find_blocking_relation_cycle(ctx: _DriftContext) -> list[_Finding]:
    """A cycle in the observed blocked-by graph (manifest-enriched message)."""
    edges: dict[str, set[str]] = {nid: set() for nid in ctx.observed_ids}
    for dep, node_id in ctx.observed_edges:
        edges[dep].add(node_id)  # dep BLOCKS node_id
    if not _find_cycle(edges):
        return []
    human_added = sorted(ctx.observed_edges - ctx.manifest_edges)
    added_desc = (
        "; human-added edges (not in the manifest): "
        + ", ".join(f"{dep}→{node}" for dep, node in human_added)
        if human_added
        else ""
    )
    return [_Finding(message="the observed blocking-relation graph contains a cycle" + added_desc)]


def _find_unknown_blocker_reference(ctx: _DriftContext) -> list[_Finding]:
    """A blocker that is not an in-objective node (disclosure)."""
    return [
        _Finding(
            message=f"node-issue {obs.identifier} is blocked by {blocker}, which is not a "
            "roadmap node — perk's roadmap graph cannot represent this external edge",
            node_id=obs.node_id,
            target=blocker,
        )
        for obs in ctx.sorted_nodes
        for blocker in obs.unknown_blockers
    ]


def _find_dependency_missing_in_linear(ctx: _DriftContext) -> list[_Finding]:
    """A manifest edge absent from observed (repairable: create it)."""
    findings: list[_Finding] = []
    for node in ctx.manifest.nodes:
        if node.id not in ctx.observed_ids:
            continue  # MISSING_NODE_ISSUE owns it; recreate restores the relations
        observed_deps = {
            dep for obs in ctx.observed_by_id[node.id] for dep in obs.depends_on_observed
        }
        for dep in node.depends_on or ():
            if dep in ctx.observed_ids and dep not in observed_deps:
                findings.append(
                    _Finding(
                        message=f"manifest edge {dep}→{node.id} (dep {dep} blocks {node.id}) "
                        "has no blocking relation in Linear",
                        node_id=node.id,
                        target=dep,
                    )
                )
    return findings


def _find_dependency_extra_in_linear(ctx: _DriftContext) -> list[_Finding]:
    """An observed edge (both endpoints nodes) absent from the manifest (report-only)."""
    return [
        _Finding(
            message=f"Linear has a blocking relation {dep}→{node_id} not in the manifest "
            "(an intentional human edit, or stale — deleting it is a judgment call)",
            node_id=node_id,
            target=dep,
        )
        for dep, node_id in sorted(ctx.observed_edges - ctx.manifest_edges)
    ]


def _find_deleted_phase_milestone(ctx: _DriftContext) -> list[_Finding]:
    """A pinned phase name matching no observed milestone (repairable: recreate)."""
    observed_milestones = set(ctx.snapshot.milestone_names)
    return [
        _Finding(
            message=f"phase {phase_key!r} milestone {pinned_name!r} is missing "
            "(deleted or renamed) — it will be recreated and its node-issues reattached",
            target=pinned_name,
        )
        for phase_key, pinned_name in ctx.manifest.phase_names.items()
        if pinned_name not in observed_milestones
    ]


def _find_renamed_phase_milestone(ctx: _DriftContext) -> list[_Finding]:
    """An observed milestone whose name pins to no manifest phase."""
    pinned_names = set(ctx.manifest.phase_names.values())
    return [
        _Finding(
            message=f"milestone {name!r} matches no manifest-pinned phase name "
            "(renamed in Linear, or an extra milestone)",
            target=name,
        )
        for name in ctx.snapshot.milestone_names
        if name not in pinned_names
    ]


# The §4 condition catalog as data. Table order IS the stable report-emission order, and each row
# is the single authority for its code's severity/repairable classification. Every DriftCode
# except the two manifest short-circuits (MANIFEST_MALFORMED / MANIFEST_ABSENT, inline in
# detect_drift) must have exactly one row — pinned by tests/test_objective_drift.py.
_CHECKS: tuple[_CheckSpec, ...] = (
    _CheckSpec(
        code=DriftCode.OVERVIEW_MARKER_DAMAGE,
        severity=ObjectiveDriftSeverity.ERROR,
        repairable=False,
        find=_find_overview_marker_damage,
    ),
    _CheckSpec(
        code=DriftCode.MISSING_NODE_ISSUE,
        severity=ObjectiveDriftSeverity.ERROR,
        repairable=True,
        find=_find_missing_node_issue,
    ),
    _CheckSpec(
        code=DriftCode.DUPLICATE_NODE_IDS,
        severity=ObjectiveDriftSeverity.ERROR,
        repairable=False,
        find=_find_duplicate_node_ids,
    ),
    _CheckSpec(
        code=DriftCode.MISSING_NODE_STATUS_BLOCK,
        severity=ObjectiveDriftSeverity.WARNING,
        repairable=False,
        find=_find_missing_node_status_block,
    ),
    _CheckSpec(
        code=DriftCode.BLOCKING_RELATION_CYCLE,
        severity=ObjectiveDriftSeverity.ERROR,
        repairable=False,
        find=_find_blocking_relation_cycle,
    ),
    _CheckSpec(
        code=DriftCode.UNKNOWN_BLOCKER_REFERENCE,
        severity=ObjectiveDriftSeverity.INFO,
        repairable=False,
        find=_find_unknown_blocker_reference,
    ),
    _CheckSpec(
        code=DriftCode.DEPENDENCY_MISSING_IN_LINEAR,
        severity=ObjectiveDriftSeverity.WARNING,
        repairable=True,
        find=_find_dependency_missing_in_linear,
    ),
    _CheckSpec(
        code=DriftCode.DEPENDENCY_EXTRA_IN_LINEAR,
        severity=ObjectiveDriftSeverity.INFO,
        repairable=False,
        find=_find_dependency_extra_in_linear,
    ),
    _CheckSpec(
        code=DriftCode.DELETED_PHASE_MILESTONE,
        severity=ObjectiveDriftSeverity.ERROR,
        repairable=True,
        find=_find_deleted_phase_milestone,
    ),
    _CheckSpec(
        code=DriftCode.RENAMED_PHASE_MILESTONE,
        severity=ObjectiveDriftSeverity.WARNING,
        repairable=False,
        find=_find_renamed_phase_milestone,
    ),
)


def detect_drift(snapshot: ObservedSnapshot) -> DriftReport:
    """Diff the manifest baseline against the observed project state (the §4 condition catalog).

    Pure + deterministic. A malformed manifest or an absent manifest short-circuits (no baseline to
    diff against); otherwise every catalog condition is emitted in a stable order. ``_CHECKS`` is
    the catalog's single ordering + severity/repairable authority — one row per code, table order =
    report order.
    """
    # A damaged manifest block disables detection entirely — never diff a corrupt baseline (halt
    # loud). A malformed manifest takes precedence over an absent one. These two stay inline
    # rather than as table rows: they short-circuit the whole pass (no baseline to diff).
    if snapshot.manifest_errors:
        malformed = DriftCondition(
            code=DriftCode.MANIFEST_MALFORMED,
            severity=ObjectiveDriftSeverity.ERROR,
            node_id=None,
            target=None,
            message="objective-manifest block is malformed: " + "; ".join(snapshot.manifest_errors),
            repairable=False,
        )
        return DriftReport(conditions=(malformed,))

    if snapshot.manifest is None:
        absent = DriftCondition(
            code=DriftCode.MANIFEST_ABSENT,
            severity=ObjectiveDriftSeverity.INFO,
            node_id=None,
            target=None,
            message="no objective-manifest block in the overview — "
            "run `perk objective doctor --fix` to backfill it from the current node-issues",
            repairable=True,
        )
        return DriftReport(conditions=(absent,))

    ctx = _build_context(snapshot, snapshot.manifest)
    conditions = [
        DriftCondition(
            code=spec.code,
            severity=spec.severity,
            node_id=finding.node_id,
            target=finding.target,
            message=finding.message,
            repairable=spec.repairable,
        )
        for spec in _CHECKS
        for finding in spec.find(ctx)
    ]
    return DriftReport(conditions=tuple(conditions))
