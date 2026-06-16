"""Pure-engine tests for perk/objective_drift.py (offline; no network, no fake Linear).

One case per `DriftCode` covering both the report-only and repairable classifications, plus the
`MANIFEST_MALFORMED`/`MANIFEST_ABSENT` early-returns and the cycle manifest-enrichment.
"""

from perk import objective as o
from perk.objective_drift import (
    DriftCode,
    ObservedNode,
    ObservedSnapshot,
    Severity,
    detect_drift,
)

N = o.NodeStatus


def _manifest(nodes: list[o.ObjectiveNode], phases: dict[str, str]) -> o.Manifest:
    return o.Manifest(schema_version="1", nodes=tuple(nodes), phase_names=phases)


def _node(
    node_id: str,
    description: str,
    *,
    depends_on: tuple[str, ...] = (),
    slug: str | None = None,
) -> o.ObjectiveNode:
    return o.ObjectiveNode(
        id=node_id, description=description, status=N.PENDING, depends_on=depends_on, slug=slug
    )


def _obs(
    node_id: str | None,
    identifier: str,
    *,
    status: N | None = N.PENDING,
    milestone_name: str | None = "Phase 1",
    has_plan_header: bool = False,
    depends_on_observed: tuple[str, ...] = (),
    unknown_blockers: tuple[str, ...] = (),
    block_valid: bool = True,
) -> ObservedNode:
    return ObservedNode(
        node_id=node_id,
        identifier=identifier,
        status=status,
        milestone_name=milestone_name,
        has_plan_header=has_plan_header,
        depends_on_observed=depends_on_observed,
        unknown_blockers=unknown_blockers,
        block_valid=block_valid,
    )


def _snapshot(
    *,
    manifest: o.Manifest | None,
    manifest_errors: tuple[str, ...] = (),
    nodes: tuple[ObservedNode, ...] = (),
    milestone_names: tuple[str, ...] = ("Phase 1",),
    header_ok: bool = True,
    reconcilable_ok: bool = True,
) -> ObservedSnapshot:
    return ObservedSnapshot(
        manifest=manifest,
        manifest_errors=manifest_errors,
        nodes=nodes,
        milestone_names=milestone_names,
        header_ok=header_ok,
        reconcilable_ok=reconcilable_ok,
    )


def _codes(report) -> list[DriftCode]:
    return [c.code for c in report.conditions]


def _only(report, code: DriftCode):
    matches = [c for c in report.conditions if c.code == code]
    assert len(matches) == 1, f"expected exactly one {code}, got {_codes(report)}"
    return matches[0]


# --- early returns ----------------------------------------------------------------------------


def test_manifest_malformed_halts_immediately():
    snap = _snapshot(
        manifest=None,
        manifest_errors=("bad schema",),
        nodes=(_obs("1.1", "ENG-1"),),
        milestone_names=("nope",),
        header_ok=False,
    )
    report = detect_drift(snap)
    assert _codes(report) == [DriftCode.MANIFEST_MALFORMED]
    cond = report.conditions[0]
    assert cond.severity is Severity.ERROR and cond.repairable is False


def test_manifest_absent_is_a_single_repairable_info():
    snap = _snapshot(manifest=None, nodes=(_obs("1.1", "ENG-1"),))
    report = detect_drift(snap)
    cond = _only(report, DriftCode.MANIFEST_ABSENT)
    assert cond.severity is Severity.INFO and cond.repairable is True
    assert _codes(report) == [DriftCode.MANIFEST_ABSENT]


def test_clean_objective_reports_nothing():
    manifest = _manifest([_node("1.1", "Alpha")], {"1": "Phase 1"})
    snap = _snapshot(manifest=manifest, nodes=(_obs("1.1", "ENG-1"),))
    assert detect_drift(snap).conditions == ()


# --- the catalog ------------------------------------------------------------------------------


def test_overview_marker_damage():
    manifest = _manifest([_node("1.1", "Alpha")], {"1": "Phase 1"})
    snap = _snapshot(
        manifest=manifest, nodes=(_obs("1.1", "ENG-1"),), header_ok=False, reconcilable_ok=False
    )
    cond = _only(detect_drift(snap), DriftCode.OVERVIEW_MARKER_DAMAGE)
    assert cond.severity is Severity.ERROR and cond.repairable is False
    assert "objective-header" in cond.message and "Reconcilable" in cond.message


def test_missing_node_issue_is_repairable():
    manifest = _manifest([_node("1.1", "Alpha"), _node("1.2", "Beta")], {"1": "Phase 1"})
    snap = _snapshot(manifest=manifest, nodes=(_obs("1.1", "ENG-1"),))
    cond = _only(detect_drift(snap), DriftCode.MISSING_NODE_ISSUE)
    assert cond.node_id == "1.2" and cond.severity is Severity.ERROR and cond.repairable is True


def test_duplicate_node_ids_report_only():
    manifest = _manifest([_node("1.1", "Alpha")], {"1": "Phase 1"})
    snap = _snapshot(manifest=manifest, nodes=(_obs("1.1", "ENG-1"), _obs("1.1", "ENG-9")))
    cond = _only(detect_drift(snap), DriftCode.DUPLICATE_NODE_IDS)
    assert cond.node_id == "1.1" and cond.repairable is False
    assert "ENG-1" in (cond.target or "") and "ENG-9" in (cond.target or "")


def test_missing_node_status_block_report_only():
    manifest = _manifest([_node("1.1", "Alpha")], {"1": "Phase 1"})
    snap = _snapshot(
        manifest=manifest,
        nodes=(_obs("1.1", "ENG-1", status=None, block_valid=False),),
    )
    cond = _only(detect_drift(snap), DriftCode.MISSING_NODE_STATUS_BLOCK)
    assert cond.severity is Severity.WARNING and cond.repairable is False
    assert cond.target == "ENG-1"


def test_blocking_relation_cycle_is_manifest_enriched():
    # manifest: 1.1 -> 1.2 (sequential). Observed adds the human edge 1.2 -> 1.1 -> a cycle.
    manifest = _manifest(
        [_node("1.1", "Alpha"), _node("1.2", "Beta", depends_on=("1.1",))], {"1": "Phase 1"}
    )
    snap = _snapshot(
        manifest=manifest,
        nodes=(
            _obs("1.1", "ENG-1", depends_on_observed=("1.2",)),
            _obs("1.2", "ENG-2", depends_on_observed=("1.1",)),
        ),
    )
    cond = _only(detect_drift(snap), DriftCode.BLOCKING_RELATION_CYCLE)
    assert cond.severity is Severity.ERROR and cond.repairable is False
    # the human-added edge 1.2->1.1 is named; the manifest edge 1.1->1.2 is not
    assert "1.2→1.1" in cond.message


def test_unknown_blocker_reference_is_disclosure_info():
    manifest = _manifest([_node("1.1", "Alpha")], {"1": "Phase 1"})
    snap = _snapshot(manifest=manifest, nodes=(_obs("1.1", "ENG-1", unknown_blockers=("OPS-42",)),))
    cond = _only(detect_drift(snap), DriftCode.UNKNOWN_BLOCKER_REFERENCE)
    assert cond.severity is Severity.INFO and cond.repairable is False
    assert cond.target == "OPS-42"


def test_dependency_missing_in_linear_is_repairable():
    manifest = _manifest(
        [_node("1.1", "Alpha"), _node("1.2", "Beta", depends_on=("1.1",))], {"1": "Phase 1"}
    )
    snap = _snapshot(
        manifest=manifest,
        nodes=(_obs("1.1", "ENG-1"), _obs("1.2", "ENG-2", depends_on_observed=())),
    )
    cond = _only(detect_drift(snap), DriftCode.DEPENDENCY_MISSING_IN_LINEAR)
    assert cond.node_id == "1.2" and cond.target == "1.1"
    assert cond.severity is Severity.WARNING and cond.repairable is True


def test_dependency_extra_in_linear_report_only():
    manifest = _manifest([_node("1.1", "Alpha"), _node("1.2", "Beta")], {"1": "Phase 1"})
    snap = _snapshot(
        manifest=manifest,
        nodes=(_obs("1.1", "ENG-1"), _obs("1.2", "ENG-2", depends_on_observed=("1.1",))),
    )
    cond = _only(detect_drift(snap), DriftCode.DEPENDENCY_EXTRA_IN_LINEAR)
    assert cond.node_id == "1.2" and cond.target == "1.1"
    assert cond.severity is Severity.INFO and cond.repairable is False


def test_deleted_phase_milestone_is_repairable():
    manifest = _manifest([_node("1.1", "Alpha")], {"1": "Phase 1: Foundations"})
    snap = _snapshot(
        manifest=manifest,
        nodes=(_obs("1.1", "ENG-1", milestone_name=None),),
        milestone_names=(),
    )
    cond = _only(detect_drift(snap), DriftCode.DELETED_PHASE_MILESTONE)
    assert cond.target == "Phase 1: Foundations"
    assert cond.severity is Severity.ERROR and cond.repairable is True


def test_renamed_phase_milestone_report_only():
    manifest = _manifest([_node("1.1", "Alpha")], {"1": "Phase 1"})
    # the pinned "Phase 1" survives (no DELETED), but an extra/renamed milestone is present
    snap = _snapshot(
        manifest=manifest,
        nodes=(_obs("1.1", "ENG-1"),),
        milestone_names=("Phase 1", "Phase 1 (renamed)"),
    )
    cond = _only(detect_drift(snap), DriftCode.RENAMED_PHASE_MILESTONE)
    assert cond.target == "Phase 1 (renamed)"
    assert cond.severity is Severity.WARNING and cond.repairable is False
