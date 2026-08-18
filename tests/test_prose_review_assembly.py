"""AssemblyRenderer: assembly-wide, toggle-independent, sibling-preserving composition."""

import inspect
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import get_args

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import (
    Assembly,
    AssemblyLayer,
    BoundaryKind,
    Candidate,
    Capability,
    Catalog,
    Fragment,
    ProseKind,
    ProseMap,
    ProseRole,
    RoutedUnit,
    Scenario,
)
from perk_dev.prose_review import assembly as assembly_module
from perk_dev.prose_review.assembly import (
    BOUNDARY_OWNERS,
    FAILURE_DETAILS,
    PRESENCE_VARIES_LABEL,
    AssemblyRenderer,
    AssemblyRenderError,
    FailedAssemblyLayer,
    PresentationOverrides,
    RenderedBoundaryLayer,
    RenderedOwnedLayer,
    WorkspaceBuffer,
)
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.source_adapter import typescript as typescript_adapter_module
from perk_dev.prose_review.source_adapter.typescript import TypeScriptSourceAdapter

from perk import prompts as prompts_module
from perk.substrate.proc import ProcFailure

ROOT = Path(__file__).parents[1]

PROMPT_ID = "markdown:prompts/synthetic/preview.md"
PROMPT_PATH = "prompts/synthetic/preview.md"
SKILL_ID = "markdown:skills/synthetic/SKILL.md"
SKILL_PATH = "skills/synthetic/SKILL.md"
AMBIENT_ID = "markdown:docs/synthetic/ambient.md"
AMBIENT_PATH = "docs/synthetic/ambient.md"
PYTHON_ID = "managed:synthetic-scaffold"
PYTHON_PATH = "pkg/synthetic_module.py"
TYPESCRIPT_ID = "typescript-tool:demo"
TYPESCRIPT_PATH = "ext/syntheticTool.ts"
UNSUPPORTED_ID = "python-symbol:pkg/native_module.pyx"
UNSUPPORTED_PATH = "pkg/native_module.pyx"

PROMPT_TEXT = (
    '{{ marker }} canonical {% if provider == "github" %}github{% else %}elsewhere{% endif %}\n'
)
SKILL_TEXT = "# Skill\n{{ not_a_template }}{% endfor %}{# raw #}\n"
AMBIENT_TEXT = "ambient notes\n"
PYTHON_TEXT = (
    'alpha = "first value"\n\n\ndef beta():\n    raise AssertionError("executed")\n\n\nbeta()\n'
)
TYPESCRIPT_TEXT = (
    'pi.registerTool({ name: "demo", description: "direct" + suffix, '
    "promptSnippet: `hello ${name}` });\n"
)

PYTHON_FRAGMENTS = (
    Fragment(id="alpha", label="Alpha", selector="symbol:alpha"),
    Fragment(id="beta", label="Beta", selector="symbol:beta"),
)
TYPESCRIPT_FRAGMENTS = (
    Fragment(id="description", label="Description", selector="tool:demo.description"),
    Fragment(id="snippet", label="Snippet", selector="tool:demo.promptSnippet"),
)


def _routed(
    unit_id: str,
    kind: ProseKind,
    path: str,
    role: ProseRole,
    fragments: tuple[Fragment, ...] = (),
) -> RoutedUnit:
    return RoutedUnit(
        candidate=Candidate(
            id=unit_id, kind=kind, path=path, selector=unit_id, fragments=fragments
        ),
        capability="cap",
        audience="both",
        role=role,
    )


def _synthetic_snapshot() -> CatalogSnapshot:
    graph = ProseMap(
        capabilities=(Capability(id="cap", label="Cap", summary="Synthetic", parent=None),),
        routes=(),
        exclusions=(),
        session_shapes=(),
        assemblies=(
            Assembly(
                id="synthetic",
                layers=(
                    AssemblyLayer(unit=None, boundary="pi-system", label="Pi", optional=False),
                    AssemblyLayer(unit=PROMPT_ID, boundary=None, label="Prompt", optional=False),
                    AssemblyLayer(unit=SKILL_ID, boundary=None, label="Skill", optional=False),
                    AssemblyLayer(unit=AMBIENT_ID, boundary=None, label="Ambient", optional=True),
                    AssemblyLayer(unit=PYTHON_ID, boundary=None, label="Managed", optional=False),
                    AssemblyLayer(unit=TYPESCRIPT_ID, boundary=None, label="Tool", optional=True),
                    AssemblyLayer(
                        unit=None, boundary="runtime-state", label="Runtime", optional=True
                    ),
                    AssemblyLayer(
                        unit=None, boundary="borrowed-prompt", label="Borrowed", optional=False
                    ),
                    AssemblyLayer(
                        unit=UNSUPPORTED_ID, boundary=None, label="Unsupported", optional=False
                    ),
                    AssemblyLayer(
                        unit=None, boundary="user-content", label="Human", optional=False
                    ),
                ),
            ),
            Assembly(
                id="repeated",
                layers=(
                    AssemblyLayer(unit=PYTHON_ID, boundary=None, label="First", optional=False),
                    AssemblyLayer(unit=PYTHON_ID, boundary=None, label="Second", optional=False),
                ),
            ),
        ),
        scenarios=(
            Scenario(
                id="synthetic-scenario",
                assembly="synthetic",
                label="Synthetic scenario",
                variables=(("marker", "[SYNTH]"), ("provider", "github")),
                include_ambient=True,
                include_tools=False,
            ),
            Scenario(
                id="repeated-scenario",
                assembly="repeated",
                label="Repeated scenario",
                variables=(),
                include_ambient=True,
                include_tools=True,
            ),
        ),
        concerns=(),
        lineage=(),
    )
    units = (
        _routed(PROMPT_ID, "markdown", PROMPT_PATH, "launch"),
        _routed(SKILL_ID, "markdown", SKILL_PATH, "skill-detail"),
        _routed(AMBIENT_ID, "markdown", AMBIENT_PATH, "ambient-discovery"),
        _routed(PYTHON_ID, "managed-prose", PYTHON_PATH, "skill-detail", PYTHON_FRAGMENTS),
        _routed(
            TYPESCRIPT_ID, "typescript-tool", TYPESCRIPT_PATH, "tool-contract", TYPESCRIPT_FRAGMENTS
        ),
        _routed(UNSUPPORTED_ID, "python-symbol", UNSUPPORTED_PATH, "context"),
    )
    catalog = Catalog(graph=graph, units=units, excluded=(), findings=(), governed_tools=())
    return CatalogSnapshot.from_catalog(catalog)


@pytest.fixture(scope="module")
def synthetic_snapshot() -> CatalogSnapshot:
    return _synthetic_snapshot()


@pytest.fixture(scope="module")
def real_snapshot() -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(build_catalog(ROOT))


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    for relative, text in (
        (PROMPT_PATH, PROMPT_TEXT),
        (SKILL_PATH, SKILL_TEXT),
        (AMBIENT_PATH, AMBIENT_TEXT),
        (PYTHON_PATH, PYTHON_TEXT),
        (TYPESCRIPT_PATH, TYPESCRIPT_TEXT),
        (UNSUPPORTED_PATH, "native source\n"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


def _renderer(repo_root: Path) -> AssemblyRenderer:
    return AssemblyRenderer(repo_root, TypeScriptSourceAdapter(ROOT))


DEFAULTS = PresentationOverrides(include_ambient=None, include_tools=None)


def _render(
    renderer: AssemblyRenderer,
    snapshot: CatalogSnapshot,
    *,
    assembly_id: str = "synthetic",
    scenario_id: str = "synthetic-scenario",
    presentation: PresentationOverrides = DEFAULTS,
    buffers: tuple[WorkspaceBuffer, ...] = (),
):
    return renderer.render(
        snapshot,
        assembly_id=assembly_id,
        scenario_id=scenario_id,
        presentation=presentation,
        workspace_buffers=buffers,
    )


def test_synthetic_assembly_preserves_every_authored_layer_in_order(
    synthetic_snapshot: CatalogSnapshot, repo: Path
) -> None:
    result = _render(_renderer(repo), synthetic_snapshot)
    assert result.assembly.id == "synthetic"
    assert result.scenario.id == "synthetic-scenario"
    assert [layer.presentation.position for layer in result.layers] == list(range(1, 11))
    assert [layer.presentation.label for layer in result.layers] == [
        "Pi",
        "Prompt",
        "Skill",
        "Ambient",
        "Managed",
        "Tool",
        "Runtime",
        "Borrowed",
        "Unsupported",
        "Human",
    ]

    pi, prompt, skill, ambient, managed, tool, runtime, borrowed, unsupported, human = result.layers
    assert isinstance(pi, RenderedBoundaryLayer)
    assert (pi.boundary, pi.owner) == ("pi-system", "pi")
    assert isinstance(runtime, RenderedBoundaryLayer)
    assert (runtime.boundary, runtime.owner) == ("runtime-state", "runtime")
    assert isinstance(borrowed, RenderedBoundaryLayer)
    assert (borrowed.boundary, borrowed.owner) == ("borrowed-prompt", "borrowed-package")
    assert isinstance(human, RenderedBoundaryLayer)
    assert (human.boundary, human.owner) == ("user-content", "user")

    assert isinstance(prompt, RenderedOwnedLayer)
    assert prompt.content_kind == "rendered-template"
    # trim_blocks consumes the newline after the line-ending `{% endif %}` tag.
    assert [part.text for part in prompt.parts] == ["[SYNTH] canonical github"]
    assert prompt.parts[0].fragment is None

    assert isinstance(skill, RenderedOwnedLayer)
    assert skill.content_kind == "raw-source"
    assert skill.parts == (assembly_module.RenderedContentPart(fragment=None, text=SKILL_TEXT),)

    assert isinstance(ambient, RenderedOwnedLayer)
    assert ambient.content_kind == "raw-source"
    assert ambient.parts[0].text == AMBIENT_TEXT

    assert isinstance(managed, RenderedOwnedLayer)
    assert managed.content_kind == "source-fragments"
    assert [(part.fragment, part.text) for part in managed.parts] == [
        (PYTHON_FRAGMENTS[0], 'alpha = "first value"'),
        (PYTHON_FRAGMENTS[1], 'def beta():\n    raise AssertionError("executed")'),
    ]

    assert isinstance(tool, RenderedOwnedLayer)
    assert tool.content_kind == "source-fragments"
    assert [(part.fragment, part.text) for part in tool.parts] == [
        (TYPESCRIPT_FRAGMENTS[0], '"direct" + suffix'),
        (TYPESCRIPT_FRAGMENTS[1], "`hello ${name}`"),
    ]

    assert isinstance(unsupported, FailedAssemblyLayer)
    assert unsupported.problems == (
        assembly_module.AssemblyLayerProblem(
            fragment=None,
            reason="unsupported-family",
            detail="The source family has no assembly extraction adapter.",
        ),
    )


def test_presence_and_visibility_control_metadata(
    synthetic_snapshot: CatalogSnapshot, repo: Path
) -> None:
    result = _render(_renderer(repo), synthetic_snapshot)
    assert PRESENCE_VARIES_LABEL == "Presence varies by session shape or runtime."
    by_position = {layer.presentation.position: layer.presentation for layer in result.layers}
    for position in (4, 6, 7):
        assert by_position[position].presence == "varies"
        assert by_position[position].presence_label == PRESENCE_VARIES_LABEL
    for position in (1, 2, 3, 5, 8, 9, 10):
        assert by_position[position].presence == "always"
        assert by_position[position].presence_label is None
    assert by_position[4].visibility_control == "ambient"  # ambient-discovery role
    assert by_position[6].visibility_control == "tools"  # tool-contract role
    for position in (1, 2, 3, 5, 7, 8, 9, 10):
        assert by_position[position].visibility_control is None


def test_presentation_overrides_change_only_the_top_level_echo(
    synthetic_snapshot: CatalogSnapshot, repo: Path
) -> None:
    renderer = _renderer(repo)
    defaults = _render(renderer, synthetic_snapshot)
    # Scenario defaults apply when overrides are null.
    assert defaults.presentation == assembly_module.ResolvedPresentation(
        include_ambient=True, include_tools=False
    )
    flipped = _render(
        renderer,
        synthetic_snapshot,
        presentation=PresentationOverrides(include_ambient=False, include_tools=True),
    )
    assert flipped.presentation == assembly_module.ResolvedPresentation(
        include_ambient=False, include_tools=True
    )
    # The per-layer tuple is byte-identical across toggle values: extraction always ran
    # for the ambient- and tools-controlled layers on both renders.
    assert flipped.layers == defaults.layers
    ambient = flipped.layers[3]
    tool = flipped.layers[5]
    assert isinstance(ambient, RenderedOwnedLayer) and ambient.parts[0].text == AMBIENT_TEXT
    assert isinstance(tool, RenderedOwnedLayer) and len(tool.parts) == 2


def test_renderer_accepts_no_session_shape_or_selection_inputs() -> None:
    parameters = inspect.signature(AssemblyRenderer.render).parameters
    assert list(parameters) == [
        "self",
        "snapshot",
        "assembly_id",
        "scenario_id",
        "presentation",
        "workspace_buffers",
    ]
    for name in ("assembly_id", "scenario_id", "presentation", "workspace_buffers"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is inspect.Parameter.empty


def test_workspace_buffers_win_without_canonical_rereads(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_read(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("workspace-covered render attempted a canonical source read")

    monkeypatch.setattr(assembly_module, "read_unit_file", unexpected_read)
    buffers = (
        WorkspaceBuffer(
            path=PROMPT_PATH, text='{% if provider == "linear" %}L{% else %}G{% endif %}'
        ),
        WorkspaceBuffer(path=SKILL_PATH, text=""),  # empty-string content wins by membership
        WorkspaceBuffer(path=AMBIENT_PATH, text="edited ambient\n"),
        WorkspaceBuffer(path=PYTHON_PATH, text='alpha = "edited"\ndef beta():\n    return alpha\n'),
        WorkspaceBuffer(
            path=TYPESCRIPT_PATH,
            text='pi.registerTool({ name: "demo", description: "edited", promptSnippet: "s" });\n',
        ),
        WorkspaceBuffer(path=UNSUPPORTED_PATH, text="edited native\n"),
    )
    result = _render(_renderer(repo), synthetic_snapshot, buffers=buffers)
    prompt, skill, ambient, managed, tool = (
        result.layers[1],
        result.layers[2],
        result.layers[3],
        result.layers[4],
        result.layers[5],
    )
    assert isinstance(prompt, RenderedOwnedLayer) and prompt.parts[0].text == "G"
    assert isinstance(skill, RenderedOwnedLayer) and skill.parts[0].text == ""
    assert isinstance(ambient, RenderedOwnedLayer) and ambient.parts[0].text == "edited ambient\n"
    assert isinstance(managed, RenderedOwnedLayer)
    assert managed.parts[0].text == 'alpha = "edited"'
    assert isinstance(tool, RenderedOwnedLayer) and tool.parts[0].text == '"edited"'
    # Disk bytes are untouched by a buffered render.
    assert (repo / PROMPT_PATH).read_text(encoding="utf-8") == PROMPT_TEXT


def test_repeated_same_path_layers_read_the_canonical_file_at_most_once(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_read = assembly_module.read_unit_file

    def counting_read(repo_root: Path, unit: RoutedUnit) -> object:
        nonlocal calls
        calls += 1
        return real_read(repo_root, unit)

    monkeypatch.setattr(assembly_module, "read_unit_file", counting_read)
    result = _render(
        _renderer(repo),
        synthetic_snapshot,
        assembly_id="repeated",
        scenario_id="repeated-scenario",
    )
    assert calls == 1
    first, second = result.layers
    assert isinstance(first, RenderedOwnedLayer)
    assert isinstance(second, RenderedOwnedLayer)
    assert first.parts == second.parts


def test_missing_canonical_path_fails_each_dependent_position_and_spares_siblings(
    synthetic_snapshot: CatalogSnapshot, repo: Path
) -> None:
    (repo / SKILL_PATH).unlink()
    (repo / PYTHON_PATH).unlink()
    result = _render(_renderer(repo), synthetic_snapshot)
    skill = result.layers[2]
    managed = result.layers[4]
    for failed in (skill, managed):
        assert isinstance(failed, FailedAssemblyLayer)
        assert failed.problems == (
            assembly_module.AssemblyLayerProblem(
                fragment=None,
                reason="source-unavailable",
                detail="The canonical source could not be read safely.",
            ),
        )
    # Unrelated paths continue: prompt, ambient, and TypeScript layers still render.
    assert isinstance(result.layers[1], RenderedOwnedLayer)
    assert isinstance(result.layers[3], RenderedOwnedLayer)
    assert isinstance(result.layers[5], RenderedOwnedLayer)
    repeated = _render(
        _renderer(repo),
        synthetic_snapshot,
        assembly_id="repeated",
        scenario_id="repeated-scenario",
    )
    assert all(isinstance(layer, FailedAssemblyLayer) for layer in repeated.layers)
    assert len(repeated.layers) == 2


@pytest.mark.parametrize(
    "template",
    [
        "{{ user.name }}",
        "{{ x | upper }}",
        "{% for x in y %}{{ x }}{% endfor %}",
        "{# comment #}",
        "{{ call() }}",
        "{% if a\n%}multiline{% endif %}",
        "stray }} closer",
        "{{ unterminated",
    ],
)
def test_out_of_subset_workspace_jinja_fails_before_any_compilation(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
) -> None:
    def unexpected_render(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("out-of-subset text reached the production render seam")

    monkeypatch.setattr(assembly_module, "render_text", unexpected_render)
    result = _render(
        _renderer(repo),
        synthetic_snapshot,
        buffers=(WorkspaceBuffer(path=PROMPT_PATH, text=template),),
    )
    prompt = result.layers[1]
    assert isinstance(prompt, FailedAssemblyLayer)
    assert prompt.problems == (
        assembly_module.AssemblyLayerProblem(
            fragment=None,
            reason="template-grammar-invalid",
            detail="The prompt template uses syntax outside the supported preview grammar.",
        ),
    )
    # Every sibling remains typed and ordered.
    assert len(result.layers) == 10
    assert isinstance(result.layers[2], RenderedOwnedLayer)


@pytest.mark.parametrize("source", ["workspace", "canonical"])
def test_any_include_is_refused_and_the_jinja_loader_is_never_called(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    include_text = '{% include "common/x.md" %}\n{{ marker }}\n'

    def unexpected_loader(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("assembly preview consulted the packaged prompts loader")

    monkeypatch.setattr(prompts_module._loader, "get_source", unexpected_loader)
    buffers: tuple[WorkspaceBuffer, ...] = ()
    if source == "workspace":
        buffers = (WorkspaceBuffer(path=PROMPT_PATH, text=include_text),)
    else:
        (repo / PROMPT_PATH).write_text(include_text, encoding="utf-8")
    result = _render(_renderer(repo), synthetic_snapshot, buffers=buffers)
    prompt = result.layers[1]
    assert isinstance(prompt, FailedAssemblyLayer)
    assert prompt.problems == (
        assembly_module.AssemblyLayerProblem(
            fragment=None,
            reason="template-include-unsupported",
            detail="Assembly preview does not support prompt includes.",
        ),
    )


@pytest.mark.parametrize(
    "template",
    [
        "{{ range }}",
        "{{ cycler }}",
        "{{ lipsum }}",
        "{% if true %}x{% endif %}",
        "{{ unknown_variable }}",
    ],
)
def test_identifiers_outside_the_scenario_mapping_are_refused(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
) -> None:
    def unexpected_render(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("an engine-global identifier reached the production render seam")

    monkeypatch.setattr(assembly_module, "render_text", unexpected_render)
    result = _render(
        _renderer(repo),
        synthetic_snapshot,
        buffers=(WorkspaceBuffer(path=PROMPT_PATH, text=template),),
    )
    prompt = result.layers[1]
    assert isinstance(prompt, FailedAssemblyLayer)
    assert prompt.problems == (
        assembly_module.AssemblyLayerProblem(
            fragment=None,
            reason="template-variable-unknown",
            detail="The prompt template references a name outside the scenario's variables.",
        ),
    )


def test_gate_passing_structural_imbalance_is_a_typed_render_failure(
    synthetic_snapshot: CatalogSnapshot, repo: Path
) -> None:
    result = _render(
        _renderer(repo),
        synthetic_snapshot,
        buffers=(WorkspaceBuffer(path=PROMPT_PATH, text="{% if provider %}unclosed"),),
    )
    prompt = result.layers[1]
    assert isinstance(prompt, FailedAssemblyLayer)
    assert prompt.problems == (
        assembly_module.AssemblyLayerProblem(
            fragment=None,
            reason="template-render-failed",
            detail="The prompt template could not be rendered for this scenario.",
        ),
    )
    assert isinstance(result.layers[2], RenderedOwnedLayer)


def test_skills_remain_exact_raw_source_even_with_jinja_like_text(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered_texts: list[str] = []
    real_render = assembly_module.render_text

    def recording_render(template_text: str, variables: Mapping[str, object]) -> str:
        rendered_texts.append(template_text)
        return real_render(template_text, variables)

    monkeypatch.setattr(assembly_module, "render_text", recording_render)
    hostile = "{% for x in y %}{{ x | upper }}{% endfor %}{# never parsed #}"
    result = _render(
        _renderer(repo),
        synthetic_snapshot,
        buffers=(WorkspaceBuffer(path=SKILL_PATH, text=hostile),),
    )
    skill = result.layers[2]
    assert isinstance(skill, RenderedOwnedLayer)
    assert skill.content_kind == "raw-source"
    assert skill.parts == (assembly_module.RenderedContentPart(fragment=None, text=hostile),)
    # Only the prompt layer's text reached the render seam; raw markdown never did.
    assert rendered_texts == [PROMPT_TEXT]


def test_unresolved_code_fragments_fail_the_whole_layer_with_ordered_problems(
    synthetic_snapshot: CatalogSnapshot, repo: Path
) -> None:
    # Both python selectors miss: two ordered fragment-scoped problems, no partial parts.
    missing_both = 'gamma = "neither symbol"\n'
    result = _render(
        _renderer(repo),
        synthetic_snapshot,
        buffers=(WorkspaceBuffer(path=PYTHON_PATH, text=missing_both),),
    )
    managed = result.layers[4]
    assert isinstance(managed, FailedAssemblyLayer)
    assert [(problem.fragment, problem.reason) for problem in managed.problems] == [
        (PYTHON_FRAGMENTS[0], "selector-not-found"),
        (PYTHON_FRAGMENTS[1], "selector-not-found"),
    ]
    assert all(
        problem.detail == "A catalog fragment no longer resolves in the current source."
        for problem in managed.problems
    )

    # One resolving + one missing TypeScript fragment: single problem, still no parts.
    partial = 'pi.registerTool({ name: "demo", description: "only direct" });\n'
    partial_result = _render(
        _renderer(repo),
        synthetic_snapshot,
        buffers=(WorkspaceBuffer(path=TYPESCRIPT_PATH, text=partial),),
    )
    tool = partial_result.layers[5]
    assert isinstance(tool, FailedAssemblyLayer)
    assert [(problem.fragment, problem.reason) for problem in tool.problems] == [
        (TYPESCRIPT_FRAGMENTS[1], "selector-not-found"),
    ]

    # Siblings remain in both renders.
    assert isinstance(result.layers[5], RenderedOwnedLayer)
    assert isinstance(partial_result.layers[4], RenderedOwnedLayer)


def test_document_invalid_source_collapses_to_one_unit_level_problem(
    synthetic_snapshot: CatalogSnapshot, repo: Path
) -> None:
    result = _render(
        _renderer(repo),
        synthetic_snapshot,
        buffers=(WorkspaceBuffer(path=PYTHON_PATH, text="def broken(:\n"),),
    )
    managed = result.layers[4]
    assert isinstance(managed, FailedAssemblyLayer)
    assert managed.problems == (
        assembly_module.AssemblyLayerProblem(
            fragment=None,
            reason="invalid-source",
            detail="The current source is not syntactically valid for its adapter.",
        ),
    )


def test_helper_unavailability_is_one_unit_level_typed_problem(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(
        _argv: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int,
        env_overlay: Mapping[str, str] | None = None,
    ) -> str:
        del cwd, timeout, env_overlay
        raise ProcFailure("spawn", ("node",))

    monkeypatch.setattr(typescript_adapter_module, "run_checked", fail)
    result = _render(_renderer(repo), synthetic_snapshot)
    tool = result.layers[5]
    assert isinstance(tool, FailedAssemblyLayer)
    assert tool.problems == (
        assembly_module.AssemblyLayerProblem(
            fragment=None,
            reason="adapter-unavailable",
            detail="The source adapter could not run safely.",
        ),
    )
    # Every non-TypeScript sibling still rendered.
    assert isinstance(result.layers[1], RenderedOwnedLayer)
    assert isinstance(result.layers[4], RenderedOwnedLayer)


def test_boundary_owner_mapping_is_exhaustive_and_exact() -> None:
    kinds = get_args(BoundaryKind.__value__)
    assert set(BOUNDARY_OWNERS) == set(kinds)
    assert BOUNDARY_OWNERS == {
        "pi-system": "pi",
        "user-content": "user",
        "runtime-state": "runtime",
        "borrowed-prompt": "borrowed-package",
    }


def test_failure_details_cover_every_reason_with_safe_copy() -> None:
    reasons = {
        "unsupported-selector",
        "unsupported-source-shape",
        "selector-not-found",
        "selector-ambiguous",
        "invalid-source",
        "source-unavailable",
        "template-grammar-invalid",
        "template-include-unsupported",
        "template-variable-unknown",
        "template-render-failed",
        "unsupported-family",
        "adapter-unavailable",
    }
    assert set(FAILURE_DETAILS) == reasons
    assert FAILURE_DETAILS["unsupported-selector"] == (
        "A catalog fragment uses a selector unsupported by its source adapter."
    )
    assert FAILURE_DETAILS["unsupported-source-shape"] == (
        "A catalog fragment resolves to a source shape that cannot be extracted safely."
    )
    assert FAILURE_DETAILS["selector-ambiguous"] == (
        "A catalog fragment resolves more than once in the current source."
    )


@pytest.mark.parametrize(
    ("assembly_id", "scenario_id", "buffers", "reason"),
    [
        ("missing", "synthetic-scenario", (), "unknown-assembly"),
        ("synthetic", "missing", (), "unknown-scenario"),
        ("synthetic", "repeated-scenario", (), "scenario-assembly-mismatch"),
        (
            "synthetic",
            "synthetic-scenario",
            (
                WorkspaceBuffer(path=SKILL_PATH, text="a"),
                WorkspaceBuffer(path=SKILL_PATH, text="b"),
            ),
            "duplicate-workspace-path",
        ),
        (
            "synthetic",
            "synthetic-scenario",
            (WorkspaceBuffer(path="not/in/catalog.md", text="x"),),
            "unknown-workspace-path",
        ),
    ],
)
def test_request_wide_failures_raise_closed_reasons_before_source_reads(
    synthetic_snapshot: CatalogSnapshot,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    assembly_id: str,
    scenario_id: str,
    buffers: tuple[WorkspaceBuffer, ...],
    reason: str,
) -> None:
    def unexpected_read(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("request-wide validation attempted a source read")

    monkeypatch.setattr(assembly_module, "read_unit_file", unexpected_read)
    with pytest.raises(AssemblyRenderError) as excinfo:
        _render(
            _renderer(repo),
            synthetic_snapshot,
            assembly_id=assembly_id,
            scenario_id=scenario_id,
            buffers=buffers,
        )
    assert excinfo.value.reason == reason


def test_real_plan_authoring_renders_all_six_authored_layers(
    real_snapshot: CatalogSnapshot,
) -> None:
    renderer = _renderer(ROOT)
    result = renderer.render(
        real_snapshot,
        assembly_id="plan-authoring",
        scenario_id="plan-github-warm",
        presentation=DEFAULTS,
        workspace_buffers=(),
    )
    assert result.assembly.id == "plan-authoring"
    assert result.scenario.id == "plan-github-warm"
    assert result.presentation == assembly_module.ResolvedPresentation(
        include_ambient=True, include_tools=True
    )
    assert [layer.presentation.position for layer in result.layers] == [1, 2, 3, 4, 5, 6]

    pi, context, skill, draft, review, human = result.layers
    assert isinstance(pi, RenderedBoundaryLayer)
    assert (pi.boundary, pi.owner) == ("pi-system", "pi")
    assert isinstance(human, RenderedBoundaryLayer)
    assert (human.boundary, human.owner) == ("user-content", "user")

    assert isinstance(context, RenderedOwnedLayer)
    assert context.content_kind == "rendered-template"
    assert context.parts[0].text.startswith("[PLAN AUTHORING]\n")
    assert "{{" not in context.parts[0].text

    assert isinstance(skill, RenderedOwnedLayer)
    assert skill.content_kind == "raw-source"
    assert skill.parts[0].text == (ROOT / "skills/perk-plan/SKILL.md").read_text(encoding="utf-8")

    # plan_draft's promptGuidelines is an indirect identifier in the current source: the
    # whole authored layer is one typed failure while every sibling stays rendered.
    assert isinstance(draft, FailedAssemblyLayer)
    assert [
        (problem.reason, problem.fragment and problem.fragment.id) for problem in draft.problems
    ] == [
        ("unsupported-source-shape", "promptGuidelines"),
    ]

    assert isinstance(review, RenderedOwnedLayer)
    assert review.content_kind == "source-fragments"
    review_unit = real_snapshot.get_unit("typescript-tool:plan_review")
    assert review_unit is not None
    assert [part.fragment for part in review.parts] == list(review_unit.candidate.fragments)
    assert len(review.parts) == 8
    review_source = (ROOT / review_unit.candidate.path).read_text(encoding="utf-8")
    for part in review.parts:
        assert part.text
        assert part.text in review_source

    # Presence metadata: the two optional tool layers vary; the rest are always present.
    assert [layer.presentation.presence for layer in result.layers] == [
        "always",
        "always",
        "always",
        "varies",
        "varies",
        "always",
    ]
    assert draft.presentation.presence_label == PRESENCE_VARIES_LABEL
    assert review.presentation.presence_label == PRESENCE_VARIES_LABEL
    assert [layer.presentation.visibility_control for layer in result.layers] == [
        None,
        None,
        None,  # bound skill-detail carries no control (never treated as ambient)
        "tools",
        "tools",
        None,
    ]


def test_real_catalog_adds_no_synthetic_ambient_layer_and_shapes_share_the_assembly(
    real_snapshot: CatalogSnapshot,
) -> None:
    for view in real_snapshot.assemblies:
        for layer in view.layers:
            if layer.unit is not None:
                assert layer.unit.role != "ambient-discovery"
    cold = real_snapshot.get_session_shape("plan.cold")
    warm = real_snapshot.get_session_shape("plan.warm")
    assert cold is not None and warm is not None
    assert cold.assembly == warm.assembly == "plan-authoring"


def test_real_plan_authoring_layers_are_toggle_independent(
    real_snapshot: CatalogSnapshot,
) -> None:
    renderer = _renderer(ROOT)

    def render(presentation: PresentationOverrides):
        return renderer.render(
            real_snapshot,
            assembly_id="plan-authoring",
            scenario_id="plan-linear-cold",
            presentation=presentation,
            workspace_buffers=(),
        )

    defaults = render(DEFAULTS)
    off = render(PresentationOverrides(include_ambient=False, include_tools=False))
    assert off.layers == defaults.layers
    assert off.presentation == assembly_module.ResolvedPresentation(
        include_ambient=False, include_tools=False
    )
