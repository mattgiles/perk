import json
from dataclasses import replace
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev.prose_map import cli as prose_cli
from perk_dev.prose_map.catalog import (
    GRAPH_PATH,
    RENDERED_PATH,
    BuildResult,
    ProseMapError,
    build,
    load_graph,
    validate_graph,
)
from perk_dev.prose_map.models import Capability

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def built() -> BuildResult:
    return build(ROOT)


def test_repository_prose_map_is_complete_and_current(built: BuildResult) -> None:
    assert built.catalog.findings == ()
    assert len(built.catalog.units) > 150
    assert len(built.catalog.governed_tools) == 35
    assert (ROOT / RENDERED_PATH).read_text(encoding="utf-8") == built.rendered


def test_tool_contracts_are_logical_fragments_without_copied_prose(built: BuildResult) -> None:
    plan_review = next(
        unit for unit in built.catalog.units if unit.candidate.id == "typescript-tool:plan_review"
    )
    fragment_ids = {fragment.id for fragment in plan_review.candidate.fragments}
    assert {"description", "promptSnippet", "parameters.properties.plan.description"}.issubset(
        fragment_ids
    )
    assert all("=>" not in fragment.selector for fragment in plan_review.candidate.fragments)


def test_python_owned_prompt_wrappers_are_ast_selected(built: BuildResult) -> None:
    python_units = {
        unit.candidate.id: unit.candidate
        for unit in built.catalog.units
        if unit.candidate.kind == "python-symbol"
    }
    expected = {
        "python-symbol:packages/perk-dev/src/perk_dev/audit/bounding.py:_PREAMBLE",
        "python-symbol:src/perk/backends/engagement.py:render_adopted_engagement",
        "python-symbol:src/perk/backends/engagement.py:render_node_engagement",
        "python-symbol:src/perk/backends/engagement.py:render_objective_engagement",
        "python-symbol:src/perk/backends/engagement.py:render_plan_engagement",
        "python-symbol:src/perk/cli/commands/learn/factory_common.py:render_inbox",
        "python-symbol:src/perk/cli/commands/objective/author_cmd.py:_render_source",
        "python-symbol:src/perk/cli/commands/objective/plan_cmd.py:_layer_context_block",
        "python-symbol:src/perk/cli/commands/objective/replan_cmd.py:_render_existing_objective",
        "python-symbol:src/perk/cli/commands/plan/from_cmd.py:_render_source_issue",
        "python-symbol:src/perk/cli/commands/plan/replan_cmd.py:_render_existing_plan",
        "python-symbol:src/perk/cli/seed_file.py:render_seed_file_scratch",
        "python-symbol:src/perk/learn/normalize.py:_PREAMBLE",
    }
    assert set(python_units) == expected
    assert all(candidate.selector.startswith("symbol:") for candidate in python_units.values())


def test_managed_repo_instructions_select_only_the_development_section(
    built: BuildResult,
) -> None:
    candidate = next(
        unit.candidate for unit in built.catalog.units if unit.candidate.id == "managed:repo-agents"
    )
    assert candidate.selector == "heading:agents/developing-perk"
    assert [fragment.id for fragment in candidate.fragments] == ["section:agents/developing-perk"]


def test_fixture_and_borrowed_sources_are_excluded(built: BuildResult) -> None:
    excluded_ids = {candidate.id for candidate in built.catalog.excluded}
    assert "markdown:prompts/README.md" in excluded_ids
    assert any(
        candidate_id.startswith("markdown:prompts/_fixtures/") for candidate_id in excluded_ids
    )
    assert any("extension/vendor/btw/" in candidate_id for candidate_id in excluded_ids)


def test_graph_boundary_forbids_unknown_fields(tmp_path: Path) -> None:
    graph_path = tmp_path / GRAPH_PATH
    graph_path.parent.mkdir(parents=True)
    graph_path.write_text(
        (ROOT / GRAPH_PATH).read_text(encoding="utf-8") + "\nunknown_field: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ProseMapError, match="Extra inputs are not permitted"):
        load_graph(tmp_path)


def test_semantic_validation_detects_capability_cycle() -> None:
    graph = load_graph(ROOT)
    first = graph.capabilities[0]
    child = Capability(
        id="cycle-child",
        label="Cycle child",
        summary="A deliberately invalid cycle fixture.",
        parent=first.id,
    )
    cyclic_root = replace(first, parent=child.id)
    invalid = replace(graph, capabilities=(cyclic_root, child, *graph.capabilities[1:]))
    findings = validate_graph(invalid)
    assert any(finding.code == "capability-cycle" for finding in findings)


def test_cli_check_reports_clean_catalog(
    built: BuildResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prose_cli, "_root", lambda: ROOT)
    monkeypatch.setattr(prose_cli, "build", lambda _root: built)
    result = CliRunner().invoke(prose_cli.prose_map, ["check", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "success": True,
        "error_type": None,
        "changed": False,
        "rendered_path": str(ROOT / RENDERED_PATH),
        "findings": [],
    }


def test_cli_sync_is_atomic_and_dry_run_does_not_write(
    built: BuildResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered_path = tmp_path / RENDERED_PATH
    rendered_path.parent.mkdir(parents=True)
    rendered_path.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(prose_cli, "_root", lambda: tmp_path)
    monkeypatch.setattr(prose_cli, "build", lambda _root: built)

    dry = CliRunner().invoke(prose_cli.prose_map, ["sync", "--dry-run", "--json"])
    assert dry.exit_code == 1
    assert json.loads(dry.output)["changed"] is True
    assert rendered_path.read_text(encoding="utf-8") == "stale\n"

    synced = CliRunner().invoke(prose_cli.prose_map, ["sync", "--json"])
    assert synced.exit_code == 0
    assert json.loads(synced.output)["success"] is True
    assert rendered_path.read_text(encoding="utf-8") == built.rendered
