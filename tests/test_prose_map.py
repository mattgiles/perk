import json
import keyword
from dataclasses import replace
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev.prose_map import catalog as catalog_module
from perk_dev.prose_map import cli as prose_cli
from perk_dev.prose_map import discovery as prose_discovery
from perk_dev.prose_map.catalog import (
    GRAPH_PATH,
    RENDERED_PATH,
    BuildResult,
    ProseMapError,
    build,
    build_catalog,
    load_graph,
    validate_graph,
    validate_scenario_fixtures,
    validate_tool_field_governance,
)
from perk_dev.prose_map.models import (
    Assembly,
    AssemblyLayer,
    Candidate,
    Capability,
    DiscoveryResult,
    Finding,
    OpaqueToolFieldIssue,
    ProseMap,
    Scenario,
    SessionShape,
    UnclassifiedToolFieldIssue,
)

ROOT = Path(__file__).parents[1]
_TEMPLATE_UNIT = "markdown:prompts/top.md"


def _fixture_graph(
    *,
    variables: dict[str, str] | None,
    referenced: bool = True,
) -> ProseMap:
    shapes = (
        (
            SessionShape(
                id="preview",
                capability="fixture",
                label="Fixture preview",
                delivery="warm",
                trigger="/preview",
                assembly="fixture",
            ),
        )
        if referenced
        else ()
    )
    scenarios = (
        (
            Scenario(
                id="fixture-scenario",
                assembly="fixture",
                label="Fixture scenario",
                variables=tuple(sorted(variables.items())),
                include_ambient=True,
                include_tools=True,
            ),
        )
        if variables is not None
        else ()
    )
    return ProseMap(
        capabilities=(),
        routes=(),
        exclusions=(),
        session_shapes=shapes,
        assemblies=(
            Assembly(
                id="fixture",
                layers=(
                    AssemblyLayer(
                        unit=_TEMPLATE_UNIT,
                        boundary=None,
                        label="Top-level prompt",
                        optional=False,
                    ),
                ),
            ),
        ),
        scenarios=scenarios,
        concerns=(),
        lineage=(),
    )


def _fixture_candidate() -> Candidate:
    return Candidate(
        id=_TEMPLATE_UNIT,
        kind="markdown",
        path="prompts/top.md",
        selector="whole-file",
        fragments=(),
    )


def _write_prompt(root: Path, name: str, source: str) -> None:
    path = root / "prompts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _write_scanner_script(root: Path) -> None:
    path = root / "tools/prose-map/catalog.ts"
    path.parent.mkdir(parents=True)
    path.write_text("// scanner fixture\n", encoding="utf-8")


@pytest.fixture(scope="module")
def built() -> BuildResult:
    return build(ROOT)


def test_typescript_field_issues_cross_the_strict_subprocess_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_scanner_script(tmp_path)
    payload = {
        "candidates": [],
        "governed_tools": ["alpha", "beta", "gamma"],
        "tool_field_issues": [
            {
                "kind": "unclassified",
                "field": "promptEpilogue",
                "reason": "unclassified-field",
                "tool": "alpha",
                "path": "extension/a.ts",
                "selector": "tool:alpha.promptEpilogue",
            },
            {
                "kind": "opaque",
                "field": None,
                "reason": "spread-assignment",
                "tool": "beta",
                "path": "extension/b.ts",
                "selector": "tool:beta/member:2",
            },
            {
                "kind": "opaque",
                "field": None,
                "reason": "dynamic-computed-property",
                "tool": "gamma",
                "path": "extension/c.ts",
                "selector": "tool:gamma/member:3",
            },
        ],
    }
    monkeypatch.setattr(
        prose_discovery,
        "run_checked",
        lambda *_args, **_kwargs: json.dumps(payload),
    )

    assert prose_discovery._typescript_candidates(tmp_path) == DiscoveryResult(
        candidates=(),
        governed_tools=("alpha", "beta", "gamma"),
        tool_field_issues=(
            UnclassifiedToolFieldIssue(
                kind="unclassified",
                field="promptEpilogue",
                reason="unclassified-field",
                tool="alpha",
                path="extension/a.ts",
                selector="tool:alpha.promptEpilogue",
            ),
            OpaqueToolFieldIssue(
                kind="opaque",
                field=None,
                reason="spread-assignment",
                tool="beta",
                path="extension/b.ts",
                selector="tool:beta/member:2",
            ),
            OpaqueToolFieldIssue(
                kind="opaque",
                field=None,
                reason="dynamic-computed-property",
                tool="gamma",
                path="extension/c.ts",
                selector="tool:gamma/member:3",
            ),
        ),
    )


def test_typescript_field_issue_discriminants_fail_strict_boundary_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_scanner_script(tmp_path)
    payload = {
        "candidates": [],
        "governed_tools": ["alpha"],
        "tool_field_issues": [
            {
                "kind": "opaque",
                "field": "promptEpilogue",
                "reason": "unclassified-field",
                "tool": "alpha",
                "path": "extension/a.ts",
                "selector": "tool:alpha.promptEpilogue",
            }
        ],
    }
    monkeypatch.setattr(
        prose_discovery,
        "run_checked",
        lambda *_args, **_kwargs: json.dumps(payload),
    )

    with pytest.raises(prose_discovery.DiscoveryError, match="returned invalid JSON"):
        prose_discovery._typescript_candidates(tmp_path)


def test_tool_field_governance_findings_have_exact_contract_messages() -> None:
    issues = (
        UnclassifiedToolFieldIssue(
            kind="unclassified",
            field="promptEpilogue",
            reason="unclassified-field",
            tool="alpha",
            path="extension/a.ts",
            selector="tool:alpha.promptEpilogue",
        ),
        OpaqueToolFieldIssue(
            kind="opaque",
            field=None,
            reason="spread-assignment",
            tool="beta",
            path="extension/b.ts",
            selector="tool:beta/member:2",
        ),
        OpaqueToolFieldIssue(
            kind="opaque",
            field=None,
            reason="dynamic-computed-property",
            tool="gamma",
            path="extension/c.ts",
            selector="tool:gamma/member:3",
        ),
    )

    assert validate_tool_field_governance(issues) == [
        Finding(
            code="unclassified-tool-field",
            message=(
                "governed tool alpha has unclassified registered-tool field promptEpilogue at "
                "extension/a.ts (tool:alpha.promptEpilogue); add a model-facing collector or a "
                "reasoned non-prose policy entry"
            ),
        ),
        Finding(
            code="opaque-tool-contract",
            message=(
                "governed tool beta has opaque registered-tool member at extension/b.ts "
                "(tool:beta/member:2): spread-assignment; replace it with statically named fields"
            ),
        ),
        Finding(
            code="opaque-tool-contract",
            message=(
                "governed tool gamma has opaque registered-tool member at extension/c.ts "
                "(tool:gamma/member:3): dynamic-computed-property; replace it with statically "
                "named fields"
            ),
        ),
    ]


def test_repository_prose_map_is_complete_and_current(built: BuildResult) -> None:
    assert built.catalog.findings == ()
    assert len(built.catalog.units) > 150
    assert len(built.catalog.governed_tools) == 37
    assert (ROOT / RENDERED_PATH).read_text(encoding="utf-8") == built.rendered


def test_build_catalog_includes_converted_tool_field_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovered = prose_discovery.discover(ROOT)
    issue = UnclassifiedToolFieldIssue(
        kind="unclassified",
        field="promptEpilogue",
        reason="unclassified-field",
        tool="plan_review",
        path="extension/doors/planTools.ts",
        selector="tool:plan_review.promptEpilogue",
    )
    injected = replace(
        discovered,
        tool_field_issues=(*discovered.tool_field_issues, issue),
    )
    monkeypatch.setattr(catalog_module, "discover", lambda _root: injected)

    assert build_catalog(ROOT).findings == (
        Finding(
            code="unclassified-tool-field",
            message=(
                "governed tool plan_review has unclassified registered-tool field promptEpilogue "
                "at extension/doors/planTools.ts (tool:plan_review.promptEpilogue); add a "
                "model-facing collector or a reasoned non-prose policy entry"
            ),
        ),
    )


def test_zero_fragment_governed_tool_reports_opaque_and_missing_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovered = prose_discovery.discover(ROOT)
    tool = "objective_stack_status"
    candidate_id = f"typescript-tool:{tool}"
    candidates = tuple(
        candidate for candidate in discovered.candidates if candidate.id != candidate_id
    )
    assert len(candidates) == len(discovered.candidates) - 1
    issue = OpaqueToolFieldIssue(
        kind="opaque",
        field=None,
        reason="spread-assignment",
        tool=tool,
        path="extension/doors/objectiveStackTools.ts",
        selector=f"tool:{tool}/member:1",
    )
    injected = replace(
        discovered,
        candidates=candidates,
        tool_field_issues=(*discovered.tool_field_issues, issue),
    )
    monkeypatch.setattr(catalog_module, "discover", lambda _root: injected)

    assert build_catalog(ROOT).findings == (
        Finding(
            code="missing-tool-contract",
            message=f"PERK_TOOLS tool has no discovered contract: {tool}",
        ),
        Finding(
            code="opaque-tool-contract",
            message=(
                f"governed tool {tool} has opaque registered-tool member at "
                f"extension/doors/objectiveStackTools.ts (tool:{tool}/member:1): "
                "spread-assignment; replace it with statically named fields"
            ),
        ),
    )


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

    python_backed = [
        unit.candidate
        for unit in built.catalog.units
        if unit.candidate.kind == "python-symbol"
        or (unit.candidate.kind == "managed-prose" and Path(unit.candidate.path).suffix == ".py")
    ]
    assert {candidate.id for candidate in python_backed if candidate.kind == "managed-prose"} == {
        "managed:downstream-agents",
        "managed:skill-scaffold",
    }
    for candidate in python_backed:
        assert candidate.selector.startswith("symbol:")
        name = candidate.selector.removeprefix("symbol:")
        assert name.isidentifier()
        assert not keyword.iskeyword(name)
        assert candidate.fragments
        assert all(fragment.selector == candidate.selector for fragment in candidate.fragments)


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


def test_scenario_validation_requires_fixture_for_previewable_assembly(
    tmp_path: Path,
) -> None:
    _write_prompt(tmp_path, "top.md", "No variables.\n")

    assert validate_scenario_fixtures(
        tmp_path,
        _fixture_graph(variables=None),
        (_fixture_candidate(),),
    ) == [
        Finding(
            code="missing-assembly-scenario",
            message="previewable assembly fixture has no scenario",
        )
    ]


def test_scenario_validation_ignores_unreferenced_assembly(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "top.md", "No variables.\n")

    assert (
        validate_scenario_fixtures(
            tmp_path,
            _fixture_graph(variables=None, referenced=False),
            (_fixture_candidate(),),
        )
        == []
    )


def test_scenario_validation_collects_conditional_and_included_variables(
    tmp_path: Path,
) -> None:
    _write_prompt(
        tmp_path,
        "top.md",
        "{% if enabled %}{{ primary }}{% else %}{{ fallback }}{% endif %}\n"
        '{% include "shared/part.md" %}\n',
    )
    _write_prompt(tmp_path, "shared/part.md", "{{ included }}\n")

    assert validate_scenario_fixtures(
        tmp_path,
        _fixture_graph(variables={"enabled": "yes", "primary": "shown"}),
        (_fixture_candidate(),),
    ) == [
        Finding(
            code="missing-scenario-variable",
            message=(
                "scenario fixture-scenario is missing variables for "
                f"{_TEMPLATE_UNIT}: fallback, included"
            ),
        )
    ]


def test_scenario_validation_groups_and_sorts_missing_variables(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "top.md", "{{ zed }} {{ alpha }} {{ middle }}\n")

    assert validate_scenario_fixtures(
        tmp_path,
        _fixture_graph(variables={}),
        (_fixture_candidate(),),
    ) == [
        Finding(
            code="missing-scenario-variable",
            message=(
                "scenario fixture-scenario is missing variables for "
                f"{_TEMPLATE_UNIT}: alpha, middle, zed"
            ),
        )
    ]


def test_scenario_validation_accepts_extra_adapter_variable(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "top.md", "{{ required }}\n")

    assert (
        validate_scenario_fixtures(
            tmp_path,
            _fixture_graph(variables={"provider": "github", "required": "value"}),
            (_fixture_candidate(),),
        )
        == []
    )


def test_scenario_validation_raises_contextual_error_for_malformed_template(
    tmp_path: Path,
) -> None:
    _write_prompt(tmp_path, "top.md", "{% if broken %}\n")

    with pytest.raises(
        ProseMapError,
        match=r"markdown:prompts/top\.md \(top\.md\)",
    ) as raised:
        validate_scenario_fixtures(
            tmp_path,
            _fixture_graph(variables={"broken": "yes"}),
            (_fixture_candidate(),),
        )

    assert raised.value.__cause__ is not None


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


def test_cli_check_reports_unclassified_tool_field_as_invalid(
    built: BuildResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    finding = Finding(
        code="unclassified-tool-field",
        message=(
            "governed tool plan_review has unclassified registered-tool field promptEpilogue at "
            "extension/doors/planTools.ts (tool:plan_review.promptEpilogue); add a model-facing "
            "collector or a reasoned non-prose policy entry"
        ),
    )
    invalid = replace(built, catalog=replace(built.catalog, findings=(finding,)))
    monkeypatch.setattr(prose_cli, "_root", lambda: ROOT)
    monkeypatch.setattr(prose_cli, "build", lambda _root: invalid)

    result = CliRunner().invoke(prose_cli.prose_map, ["check", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "success": False,
        "error_type": "prose_map_invalid",
        "changed": False,
        "rendered_path": str(ROOT / RENDERED_PATH),
        "findings": [
            {
                "code": finding.code,
                "message": finding.message,
            }
        ],
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
