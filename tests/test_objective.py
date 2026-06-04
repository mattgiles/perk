"""Pure-mechanics tests for perk/objective.py (no network, no Click)."""

from perk import objective as o
from perk.plan import render_metadata_block

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


def test_next_node_first_unblocked_pending():
    # 1.1 done -> 1.2 pending unblocked is next.
    graph = o.build_graph(_nodes())
    nxt = graph.next_node()
    assert nxt is not None and nxt.id == "1.2"


def test_next_node_blocked_by_unfinished_dep():
    nodes = [
        o.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS),
        o.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
    ]
    graph = o.build_graph(nodes)
    # 1.2 depends on 1.1 (sequential) which is not terminal -> blocked -> no next.
    assert graph.next_node() is None


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


# --- P2.T11: nodes_for_pr + reconcilable splice + render_body_comment markers --------------


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
