"""Pure-mechanics tests for perk/objective.py (no network, no Click)."""

from typing import cast

from perk import objective as o
from perk.plan import find_metadata_block, render_metadata_block

N = o.NodeStatus


def _block(nodes: list[o.ObjectiveNode]) -> str:
    return render_metadata_block(o.OBJECTIVE_ROADMAP_KEY, o.render_roadmap_block(nodes))


def _nodes() -> list[o.ObjectiveNode]:
    return [
        o.ObjectiveNode(id="1.1", description="Alpha", status=N.DONE),
        o.ObjectiveNode(id="1.2", description="Beta", status=N.PENDING),
        o.ObjectiveNode(id="2.1", description="Gamma", status=N.PENDING),
    ]


def test_roadmap_render_parse_roundtrip():
    nodes = _nodes()
    parsed, errors = o.parse_roadmap_nodes(_block(nodes))
    assert errors == []
    assert [n.id for n in parsed] == ["1.1", "1.2", "2.1"]
    assert parsed[0].status is N.DONE and parsed[1].status is N.PENDING


def test_parse_three_cases_no_block_valid_invalid():
    # No block at all -> roadmap-free objective, no error.
    assert o.parse_roadmap_nodes("just prose, no block") == ([], [])
    # Valid block.
    nodes, errors = o.parse_roadmap_nodes(_block(_nodes()))
    assert errors == [] and len(nodes) == 3
    # Block present but invalid (bad status) -> ([], [error]).
    bad = render_metadata_block(
        o.OBJECTIVE_ROADMAP_KEY,
        {"schema_version": "1", "nodes": [{"id": "1.1", "description": "x", "status": "nope"}]},
    )
    nodes, errors = o.parse_roadmap_nodes(bad)
    assert nodes == [] and errors and "status" in errors[0]


def test_parse_structured_roadmap_list_and_mapping_and_invalid():
    # Bare list of nodes -> wrapped with the current schema + validated. `status` is OPTIONAL on the
    # structured path (defaults to pending); id + description are the only required fields.
    nodes, errors = o.parse_structured_roadmap(
        [{"id": "1.1", "description": "a"}, {"id": "1.2", "description": "b", "status": "done"}]
    )
    assert errors == []
    assert [n.id for n in nodes] == ["1.1", "1.2"]
    assert nodes[0].status is N.PENDING and nodes[1].status is N.DONE
    # A node missing `description` (a required field) is rejected.
    bad, berrors = o.parse_structured_roadmap([{"id": "1.1"}])
    assert bad == [] and berrors
    # None / empty -> roadmap-free.
    assert o.parse_structured_roadmap(None) == ([], [])
    assert o.parse_structured_roadmap([]) == ([], [])
    # A full {schema_version, nodes} mapping is accepted as-is.
    nodes2, errors2 = o.parse_structured_roadmap(
        {"schema_version": "1", "nodes": [{"id": "1.1", "description": "a", "status": "pending"}]}
    )
    assert errors2 == [] and [n.id for n in nodes2] == ["1.1"]
    # A non-list/non-mapping is rejected.
    nodes3, errors3 = o.parse_structured_roadmap("oops")
    assert nodes3 == [] and errors3


def test_parse_rejects_wrong_schema_version():
    block = render_metadata_block(
        o.OBJECTIVE_ROADMAP_KEY,
        {"schema_version": "2", "nodes": []},
    )
    nodes, errors = o.parse_roadmap_nodes(block)
    assert nodes == [] and errors and "schema_version" in errors[0]


def test_derive_phase_from_id_prefix():
    assert o.derive_phase("1.2") == (1, "")
    assert o.derive_phase("2A.1") == (2, "A")
    assert o.derive_phase("3") == (1, "")  # no dot -> phase 1


def test_update_node_preserve_clear_set_pr():
    nodes = _nodes()
    # set pr, preserve status
    updated = o.update_node(nodes, "1.2", pr="#7")
    assert updated is not None
    n = next(x for x in updated if x.id == "1.2")
    assert n.pr == "#7" and n.status is N.PENDING  # status NOT inferred from pr (open #3)
    # preserve pr (pr=None)
    again = o.update_node(updated, "1.2", description="Beta2")
    assert again is not None
    n = next(x for x in again if x.id == "1.2")
    assert n.pr == "#7" and n.description == "Beta2"
    # clear pr (pr="")
    cleared = o.update_node(again, "1.2", pr="")
    assert cleared is not None
    n = next(x for x in cleared if x.id == "1.2")
    assert n.pr is None


def test_update_node_status_explicit_only():
    nodes = _nodes()
    updated = o.update_node(nodes, "1.2", status=N.IN_PROGRESS, pr="#9")
    assert updated is not None
    n = next(x for x in updated if x.id == "1.2")
    assert n.status is N.IN_PROGRESS and n.pr == "#9"


def test_update_node_missing_returns_none():
    assert o.update_node(_nodes(), "9.9", status=N.DONE) is None


def test_add_node_assigns_next_id_in_phase():
    nodes = _nodes()
    result = o.add_node(nodes, phase=1, description="Delta")
    assert result is not None
    updated, new_id = result
    assert new_id == "1.3"
    # inserted after the phase-1 nodes, before 2.1
    ids = [n.id for n in updated]
    assert ids == ["1.1", "1.2", "1.3", "2.1"]
    assert next(n for n in updated if n.id == "1.3").slug == "delta"


def test_add_node_new_phase_appends_at_end():
    # A phase with no existing nodes appends at the end (supports a brand-new trailing phase).
    result = o.add_node(_nodes(), phase=3, description="Omega")
    assert result is not None
    updated, new_id = result
    assert new_id == "3.1"
    assert [n.id for n in updated] == ["1.1", "1.2", "2.1", "3.1"]


def test_add_node_optional_fields_round_trip_through_render_parse():
    result = o.add_node(
        _nodes(),
        phase=2,
        description="Delta work",
        depends_on=("1.1", "2.1"),
        slug="delta-work",
        comment="emerged during reconcile",
    )
    assert result is not None
    updated, new_id = result
    assert new_id == "2.2"
    parsed, errors = o.parse_roadmap_nodes(_block(updated))
    assert errors == []
    node = next(n for n in parsed if n.id == "2.2")
    assert node.depends_on == ("1.1", "2.1")
    assert node.slug == "delta-work"
    assert node.comment == "emerged during reconcile"


def test_add_node_non_numeric_suffix_ignored_for_max():
    # Non-numeric suffixes in the phase don't bump the max (the new id is the next integer).
    nodes = [
        o.ObjectiveNode(id="1.1", description="Alpha", status=N.DONE),
        o.ObjectiveNode(id="1.x", description="NonNumeric", status=N.PENDING),
    ]
    result = o.add_node(nodes, phase=1, description="Delta")
    assert result is not None
    _updated, new_id = result
    assert new_id == "1.2"


def test_build_graph_sequential_inference():
    nodes = _nodes()  # no explicit depends_on
    graph = o.build_graph(nodes)
    by_id = {n.id: n for n in graph.nodes}
    assert by_id["1.1"].depends_on == ()
    assert by_id["1.2"].depends_on == ("1.1",)
    assert by_id["2.1"].depends_on == ("1.2",)  # first of phase 2 -> last of phase 1


def test_build_graph_explicit_depends_on():
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.DONE, depends_on=()),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=("1.1",)),
        o.ObjectiveNode(id="1.3", description="C", status=N.PENDING, depends_on=("9.9",)),
    ]
    graph = o.build_graph(nodes)
    by_id = {n.id: n for n in graph.nodes}
    assert by_id["1.3"].depends_on == ("9.9",)


def test_next_plannable_first_unblocked_pending():
    # 1.1 done -> 1.2 pending unblocked is next.
    graph = o.build_graph(_nodes())
    nxt = graph.next_plannable()
    assert nxt is not None and nxt.id == "1.2"


def test_next_plannable_blocked_by_unfinished_dep():
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
    ]
    graph = o.build_graph(nodes)
    # 1.2 depends on 1.1 (sequential) which is not terminal -> blocked -> no next.
    assert graph.next_plannable() is None


def test_next_plannable_resumes_orphaned_planning_claim():
    # A `planning` head node with no pr is a resumable claim. With 1.2 sequentially blocked
    # behind it, the claim is the only plannable node -> the fallback resumes it (self-healing).
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.PLANNING, pr=None),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
    ]
    graph = o.build_graph(nodes)
    nxt = graph.next_plannable()
    assert nxt is not None and nxt.id == "1.1"
    assert [n.id for n in graph.plannable_nodes()] == ["1.1"]  # 1.2 blocked behind 1.1
    assert [n.id for n in graph.resumable_claims()] == ["1.1"]
    assert graph.in_flight_nodes() == []


def test_next_plannable_prefers_pending_over_live_claim():
    # Pending-first: a possibly-live claim (1.1) is skipped while an independent unblocked
    # pending node (1.2) exists -> parallel objective-plan launches take distinct nodes.
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.PLANNING, pr=None, depends_on=()),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=()),
    ]
    graph = o.build_graph(nodes)
    nxt = graph.next_plannable()
    assert nxt is not None and nxt.id == "1.2"
    assert [n.id for n in graph.plannable_nodes()] == ["1.1", "1.2"]  # both stay plannable
    assert [n.id for n in graph.resumable_claims()] == ["1.1"]
    sel = graph.classify_for_planning()
    assert sel.kind == "plannable" and sel.node is not None and sel.node.id == "1.2"


def test_planning_with_pr_is_in_flight_not_plannable():
    # A `planning` node that already carries a pr backlink is in-flight, not resumable.
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.PLANNING, pr="#9"),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
    ]
    graph = o.build_graph(nodes)
    assert graph.next_plannable() is None  # 1.1 in-flight, 1.2 blocked behind it
    assert [n.id for n in graph.in_flight_nodes()] == ["1.1"]
    assert graph.plannable_nodes() == []
    assert graph.resumable_claims() == []  # a claim WITH a pr is not a resumable claim


def test_classify_for_planning_kinds():
    # plannable: a pending unblocked head.
    plannable = o.build_graph(_nodes()).classify_for_planning()
    assert plannable.kind == "plannable" and plannable.node is not None
    # complete: all terminal.
    done = [
        o.ObjectiveNode(id="1.1", description="A", status=N.DONE),
        o.ObjectiveNode(id="1.2", description="B", status=N.SKIPPED),
    ]
    assert o.build_graph(done).classify_for_planning().kind == "complete"
    # in_flight: head in_progress blocks the rest, nothing plannable.
    in_flight = o.build_graph(
        [
            o.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS),
            o.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
        ]
    ).classify_for_planning()
    assert in_flight.kind == "in_flight" and in_flight.node is not None
    assert in_flight.node.id == "1.1"
    # blocked: head explicitly blocked, nothing in-flight, nothing plannable.
    blocked = o.build_graph(
        [
            o.ObjectiveNode(id="1.1", description="A", status=N.BLOCKED),
            o.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
        ]
    ).classify_for_planning()
    assert blocked.kind == "blocked" and blocked.node is None


def test_is_complete_and_summary():
    done = [
        o.ObjectiveNode(id="1.1", description="A", status=N.DONE),
        o.ObjectiveNode(id="1.2", description="B", status=N.SKIPPED),
    ]
    assert o.build_graph(done).is_complete() is True
    assert o.build_graph(_nodes()).is_complete() is False
    s = o.summary(_nodes())
    assert s["total"] == 3 and s["done"] == 1 and s["pending"] == 2


def test_render_table_and_rerender():
    nodes = _nodes()
    comment = o.render_body_comment(nodes, prose="Some prose.")
    assert (
        o.ROADMAP_TABLE_MARKER_START in comment and "Alpha" in comment and "Some prose." in comment
    )
    # mutate then rerender the marker-bounded table
    updated = o.update_node(nodes, "1.2", status=N.DONE)
    assert updated is not None
    rerendered = o.rerender_body_table(comment, updated)
    assert rerendered is not None
    assert "Some prose." in rerendered  # prose preserved
    # the 1.2 row now shows done
    line = next(ln for ln in rerendered.splitlines() if ln.startswith("| 1.2 "))
    assert "done" in line


def test_render_table_depends_on_column():
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.PENDING, depends_on=()),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=("1.1",)),
    ]
    table = o.render_roadmap_table(nodes)
    assert "Depends On" in table


def test_objective_header_to_data():
    header = o.ObjectiveHeader(run_id="01RID", created="t", objective_comment_id=5, status="active")
    data = header.to_data()
    assert (
        data["run_id"] == "01RID"
        and data["objective_comment_id"] == 5
        and data["status"] == "active"
    )
    assert data["base"] is None  # absent by default


def test_objective_header_base_round_trips():
    header = o.ObjectiveHeader(run_id="01RID", created="t", base="develop")
    data = header.to_data()
    assert data["base"] == "develop"
    rendered = render_metadata_block(o.OBJECTIVE_HEADER_KEY, data)
    parsed = find_metadata_block(rendered, o.OBJECTIVE_HEADER_KEY)
    assert parsed is not None and parsed["base"] == "develop"
    assert "base" in o.OBJECTIVE_HEADER_FIELDS


# --- adopted_from provenance + parse_adopt_mapping + archive note -----------


def test_objective_header_adopted_from_round_trips():
    header = o.ObjectiveHeader(run_id="01RID", created="t", adopted_from="uuid-xyz")
    data = header.to_data()
    assert data["adopted_from"] == "uuid-xyz"
    rendered = render_metadata_block(o.OBJECTIVE_HEADER_KEY, data)
    parsed = find_metadata_block(rendered, o.OBJECTIVE_HEADER_KEY)
    assert parsed is not None and parsed["adopted_from"] == "uuid-xyz"
    assert "adopted_from" in o.OBJECTIVE_HEADER_FIELDS


def test_objective_header_adopted_from_absent_by_default():
    data = o.ObjectiveHeader(run_id="01RID", created="t").to_data()
    assert data["adopted_from"] is None


def test_parse_adopt_mapping_bare_list_and_nodes_shape():
    bare = [
        {"id": "1.1", "description": "A", "adopt_issue": "ENG-1"},
        {"id": "1.2", "description": "B"},
        {"id": "1.3", "description": "C", "adopt_issue": "  "},
    ]
    assert o.parse_adopt_mapping(bare) == {"1.1": "ENG-1"}
    wrapped = {"schema_version": "1", "nodes": bare}
    assert o.parse_adopt_mapping(wrapped) == {"1.1": "ENG-1"}


def test_parse_adopt_mapping_strips_and_skips():
    nodes = [
        {"id": "2.1", "description": "A", "adopt_issue": " ENG-9 "},
        "not-a-dict",
        {"description": "missing id", "adopt_issue": "ENG-2"},
        {"id": "2.2", "description": "B", "adopt_issue": 42},
    ]
    assert o.parse_adopt_mapping(nodes) == {"2.1": "ENG-9"}


def test_parse_adopt_mapping_non_collection_returns_empty():
    assert o.parse_adopt_mapping(None) == {}
    assert o.parse_adopt_mapping("x") == {}
    assert o.parse_adopt_mapping(123) == {}


def test_render_adopted_overview_note_empty_when_blank():
    assert o.render_adopted_overview_note("") == ""
    assert o.render_adopted_overview_note("   \n  ") == ""


def test_render_adopted_overview_note_marker_and_verbatim():
    note = o.render_adopted_overview_note("Original human overview.\n\nSecond paragraph.")
    assert note.startswith(o.ADOPTED_OVERVIEW_MARKER)
    assert "Original human overview." in note
    assert "Second paragraph." in note
    # Idempotent shape: re-rendering the same input yields identical bytes.
    assert note == o.render_adopted_overview_note("Original human overview.\n\nSecond paragraph.")


# --- nodes_for_pr + reconcilable splice + render_body_comment markers --------------


def test_nodes_for_pr_matches_canonical_forms():
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.DONE, pr="#6"),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING, pr="7"),
        o.ObjectiveNode(id="1.3", description="C", status=N.PENDING, pr=None),
    ]
    assert [n.id for n in o.nodes_for_pr(nodes, "#6")] == ["1.1"]
    assert [n.id for n in o.nodes_for_pr(nodes, 6)] == ["1.1"]
    assert [n.id for n in o.nodes_for_pr(nodes, "6")] == ["1.1"]
    # node stored "7" matches "#7"/7
    assert [n.id for n in o.nodes_for_pr(nodes, "#7")] == ["1.2"]
    assert o.nodes_for_pr(nodes, "999") == []


def test_render_body_comment_emits_reconcilable_markers():
    nodes = _nodes()
    empty = o.render_body_comment(nodes)
    assert o.OBJECTIVE_RECONCILABLE_MARKER_START in empty
    assert o.OBJECTIVE_RECONCILABLE_MARKER_END in empty
    full = o.render_body_comment(nodes, prose="Some prose here.")
    assert "Some prose here." in full
    # prose sits inside the reconcilable markers
    start = full.index(o.OBJECTIVE_RECONCILABLE_MARKER_START)
    end = full.index(o.OBJECTIVE_RECONCILABLE_MARKER_END)
    assert start < full.index("Some prose here.") < end


def test_replace_reconcilable_section_splices_and_preserves():
    comment = o.render_body_comment(_nodes(), prose="Old prose.")
    # append an Immutable note below the closing marker
    comment = comment + "\n## Immutable history\nnever touch this\n"
    out = o.replace_reconcilable_section(comment, "New prose.")
    assert out is not None
    assert "New prose." in out and "Old prose." not in out
    # the Mechanical table block above is preserved
    assert o.ROADMAP_TABLE_MARKER_START in out
    assert "| 1.1 |" in out
    # the Immutable note below is preserved
    assert "never touch this" in out


def test_replace_reconcilable_section_none_when_markers_absent():
    assert o.replace_reconcilable_section("no markers here", "x") is None


# --- dual-encoding marker awareness --------------------------------


def test_replace_reconcilable_section_preserves_inline_code_form():
    from perk.backends.linear import to_linear_markdown

    comment = to_linear_markdown(o.render_body_comment(_nodes(), prose="Old prose."))
    comment = comment + "\n## Immutable history\nnever touch this\n"
    assert "<!--" not in comment  # the transcode dropped every HTML marker
    out = o.replace_reconcilable_section(comment, "New prose.")
    assert out is not None
    assert "New prose." in out and "Old prose." not in out
    assert "never touch this" in out
    # form preservation: the inline-code sentinels stay; no HTML form is reintroduced
    assert "`perk:objective-reconcilable`" in out and "`/perk:objective-reconcilable`" in out
    assert "<!--" not in out


def test_rerender_body_table_preserves_inline_code_form():
    from perk.backends.linear import to_linear_markdown

    nodes = _nodes()
    comment = to_linear_markdown(o.render_body_comment(nodes, prose="Some prose."))
    updated = o.update_node(nodes, "1.2", status=N.DONE)
    assert updated is not None
    out = o.rerender_body_table(comment, updated)
    assert out is not None
    assert "Some prose." in out
    line = next(ln for ln in out.splitlines() if ln.startswith("| 1.2 "))
    assert "done" in line
    assert "`perk:roadmap-table`" in out and "`/perk:roadmap-table`" in out
    assert "<!--" not in out


def test_html_form_behavior_unchanged_by_dual_encoding():
    # The HTML scan runs first: a comment carrying BOTH forms (pathological) splices the HTML one.
    comment = o.render_body_comment(_nodes(), prose="HTML prose.")
    out = o.replace_reconcilable_section(comment, "Spliced.")
    assert out is not None
    assert o.OBJECTIVE_RECONCILABLE_MARKER_START in out
    assert o.OBJECTIVE_RECONCILABLE_MARKER_END in out


def test_parse_roadmap_nodes_inline_code_block():
    nodes = _nodes()
    body = render_metadata_block(
        o.OBJECTIVE_ROADMAP_KEY, o.render_roadmap_block(nodes), style="inline-code"
    )
    parsed, errors = o.parse_roadmap_nodes(body)
    assert errors == []
    assert [n.id for n in parsed] == ["1.1", "1.2", "2.1"]


def test_parse_roadmap_nodes_malformed_inline_block_is_an_error():
    # present-but-malformed in the inline-code encoding -> error (not "valid roadmap-free")
    broken = "`perk:metadata-block:objective-roadmap`\n\n```yaml\nnodes: [\n```"
    parsed, errors = o.parse_roadmap_nodes(broken)
    assert parsed == [] and errors and "malformed" in errors[0]


def test_objective_header_string_comment_id_round_trips():
    header = o.ObjectiveHeader(
        run_id="01RID", created="t", objective_comment_id="comment-uuid-1", status="active"
    )
    data = header.to_data()
    assert data["objective_comment_id"] == "comment-uuid-1"


def test_node_sort_key_orders_naturally():
    ids = ["3.10", "1.1", "2A.1", "3.2", "2.1", "1.2"]
    assert sorted(ids, key=o.node_sort_key) == ["1.1", "1.2", "2.1", "2A.1", "3.2", "3.10"]


def test_node_sort_key_numeric_before_lexical_trailing():
    # an all-digit trailing segment sorts before a non-numeric one within the same phase
    assert o.node_sort_key("3.2") < o.node_sort_key("3.x")
    assert o.node_sort_key("3") == (1, "", 0, 3, "")


def test_render_node_block_required_and_optional_fields():
    node = o.ObjectiveNode(
        id="1.1", description="Alpha", status=N.PENDING, pr="#9", depends_on=("1.0",)
    )
    # pr and depends_on are excluded; slug/comment omitted when None
    assert o.render_node_block(node) == {
        "id": "1.1",
        "status": "pending",
        "description": "Alpha",
    }
    rich = o.ObjectiveNode(id="1.2", description="Beta", status=N.DONE, slug="beta", comment="note")
    assert o.render_node_block(rich) == {
        "id": "1.2",
        "status": "done",
        "description": "Beta",
        "slug": "beta",
        "comment": "note",
    }


# --- the objective-manifest drift baseline ----------------------------------


def _manifest_nodes() -> list[o.ObjectiveNode]:
    return [
        o.ObjectiveNode(id="1.1", description="Alpha", status=N.DONE, slug="alpha"),
        o.ObjectiveNode(
            id="1.2", description="Beta", status=N.PENDING, slug="beta", depends_on=("1.1",)
        ),
        o.ObjectiveNode(id="2A.1", description="Gamma", status=N.IN_PROGRESS, slug="gamma"),
    ]


def test_phase_key_str_derives_from_node_id():
    assert o.phase_key_str("1.2") == "1"
    assert o.phase_key_str("2A.1") == "2A"
    assert o.phase_key_str("3") == "1"


def test_render_manifest_block_excludes_status_and_pr():
    nodes = _manifest_nodes()
    data = o.render_manifest_block(nodes, {"1": "Phase 1: Foundations", "2A": "Phase 2A: Extra"})
    assert data["schema_version"] == "1"
    node_dicts = cast("list[dict[str, object]]", data["nodes"])
    assert node_dicts == [
        {"id": "1.1", "slug": "alpha", "description": "Alpha", "depends_on": []},
        {"id": "1.2", "slug": "beta", "description": "Beta", "depends_on": ["1.1"]},
        {"id": "2A.1", "slug": "gamma", "description": "Gamma", "depends_on": []},
    ]
    # no live state leaks into the manifest
    for nd in node_dicts:
        assert "status" not in nd and "pr" not in nd
    assert data["phases"] == {"1": "Phase 1: Foundations", "2A": "Phase 2A: Extra"}


def test_manifest_round_trips_through_inline_code_and_prosemirror():
    from perk.backends.linear import to_linear_markdown

    nodes = _manifest_nodes()
    names = {"1": "Phase 1: Foundations", "2A": "Phase 2A: Extra"}
    overview = to_linear_markdown(
        render_metadata_block(
            o.OBJECTIVE_MANIFEST_KEY, o.render_manifest_block(nodes, names), style="inline-code"
        )
    )
    assert "<!--" not in overview  # the transcode dropped every HTML marker
    manifest, errors = o.parse_manifest(overview)
    assert errors == [] and manifest is not None
    assert [n.id for n in manifest.nodes] == ["1.1", "1.2", "2A.1"]
    assert manifest.nodes[1].depends_on == ("1.1",)
    assert manifest.nodes[0].depends_on == ()  # explicit empty edge set
    assert manifest.nodes[2].slug == "gamma"
    assert manifest.phase_names == names
    assert o.phase_key_str(manifest.nodes[2].id) == "2A"


def test_parse_manifest_three_cases_absent_malformed_valid():
    # absent -> (None, []) (a valid backfill target)
    assert o.parse_manifest("just prose, no manifest block") == (None, [])
    # malformed -> (None, [error])
    broken = "`perk:metadata-block:objective-manifest`\n\n```yaml\nnodes: [\n```"
    manifest, errors = o.parse_manifest(broken)
    assert manifest is None and errors and "malformed" in errors[0]
    # invalid (bad phases shape) -> (None, [error])
    bad = render_metadata_block(
        o.OBJECTIVE_MANIFEST_KEY,
        {
            "schema_version": "1",
            "nodes": [{"id": "1.1", "slug": "a", "description": "x", "depends_on": []}],
            "phases": {"1": 5},
        },
    )
    manifest, errors = o.parse_manifest(bad)
    assert manifest is None and errors and "phases" in errors[0]
    # valid
    good = render_metadata_block(
        o.OBJECTIVE_MANIFEST_KEY,
        o.render_manifest_block(_manifest_nodes(), {"1": "Phase 1", "2A": "Phase 2A"}),
    )
    manifest, errors = o.parse_manifest(good)
    assert errors == [] and manifest is not None and len(manifest.nodes) == 3


def test_node_issue_title_slug_vs_truncated_description():
    slugged = o.ObjectiveNode(id="2.1", description="Gamma", status=N.PENDING, slug="gamma")
    assert o.node_issue_title(slugged) == "2.1: gamma"
    short = o.ObjectiveNode(id="2.2", description="short desc", status=N.PENDING)
    assert o.node_issue_title(short) == "2.2: short desc"
    longish = o.ObjectiveNode(id="2.3", description="x" * 50, status=N.PENDING)
    assert o.node_issue_title(longish, max_len=10) == "2.3: " + "x" * 10 + "…"


# --- project-update body composers -------------------------------------------------


def test_objective_created_update_body():
    body = o.objective_created_update_body("Big Objective", node_count=7, phase_count=3)
    assert body == "**Objective created** — Big Objective\n\n7 nodes across 3 phases."


def test_plan_landed_update_body_incomplete():
    body = o.plan_landed_update_body(["1.1", "1.2"], pr="7", complete=False)
    assert body == "**Plan landed** — node(s) 1.1, 1.2 (PR #7) marked done."
    assert "Objective complete." not in body


def test_plan_landed_update_body_complete_and_pr_normalization():
    # `pr` is normalized through canonical_pr: "#7" / 7 / "7" all render as "#7".
    for pr in ("#7", 7, "7"):
        body = o.plan_landed_update_body(["1.3"], pr=pr, complete=True)
        assert body == "**Plan landed** — node(s) 1.3 (PR #7) marked done.\n\nObjective complete."


def test_reconciled_update_body():
    assert o.reconciled_update_body() == (
        "**Roadmap reconciled** — the objective prose was updated against the merged diff."
    )


def test_objective_callout_content_and_routing():
    from perk import plan as _plan

    out = o.objective_callout("ENG-7")
    assert "**Plan the next node:**" in out
    assert "```\nperk objective plan ENG-7\n```" in out
    assert "_Run from the repo root to plan the next actionable node._" in out
    # routes through render_command_callout
    assert out == _plan.render_command_callout(
        "Plan the next node:",
        "perk objective plan ENG-7",
        "Run from the repo root to plan the next actionable node.",
    )
