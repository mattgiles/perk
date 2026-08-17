"""Assembly-wide preview composition over one stable catalog/source generation.

:class:`AssemblyRenderer` resolves one validated assembly/scenario pair from an explicit
:class:`~perk_dev.prose_review.catalog.CatalogSnapshot`, applies scenario-default presentation
with nullable caller overrides, validates path-keyed workspace buffers, and returns every
authored layer exactly once in authored order. There is no session-shape parameter and no
layer filtering: a shape is navigation/provenance only, and an ``optional`` layer stays
present with an explicit presence marker. Presentation toggles change only the top-level
:class:`ResolvedPresentation` echo — the per-layer tuple is byte-identical across toggle
values, so clients derive display visibility from ``visibility_control`` plus the resolved
booleans and contradictory wire states are impossible.

Content composition is family-exact and never executes repository code:

- Prompt-root Markdown (``prompt_template_name``) is gated by the frozen-grammar preview scan
  (subset membership, no includes, mapping-only identifiers) before the unchanged production
  ``perk.prompts.render_text`` seam ever compiles it — editable text can never reach Jinja
  with calls/filters/loops/includes or engine-global identifiers, and can never trigger the
  packaged ``prompts_dir()`` include loader.
- Other Markdown is exact raw source, never parsed as Jinja.
- Code-owned layers extract every catalog fragment in order through the existing
  SourceAdapter selector authority (one parse / one helper invocation per layer).
- External boundaries become typed owner/kind placeholders.

Expected source/gate/template/selector failures become one typed
:class:`FailedAssemblyLayer` for only the responsible authored position while every sibling
remains in the result; unexpected invariant failures stay loud. The HTTP caller owns
stabilizing the snapshot and canonical source bytes against saves (the source transaction in
``web.py``); this module stays pure over its inputs plus contained canonical reads.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import TemplateError

from perk.prompts import render_text
from perk_dev.prompt_grammar import scan_template
from perk_dev.prose_map.catalog import prompt_template_name
from perk_dev.prose_map.models import (
    Assembly,
    AssemblyLayer,
    BoundaryKind,
    Fragment,
    RoutedUnit,
    Scenario,
)
from perk_dev.prose_review.catalog import AssemblyLayerView, CatalogSnapshot
from perk_dev.prose_review.source_adapter import (
    RangeFailure,
    SourceExtraction,
    SourceReadError,
    UnresolvedRange,
    read_unit_file,
    source_adapter_for,
)
from perk_dev.prose_review.source_adapter.typescript import (
    TypeScriptAdapterUnavailable,
    TypeScriptSourceAdapter,
)

type BoundaryOwner = Literal["pi", "user", "runtime", "borrowed-package"]
type LayerPresence = Literal["always", "varies"]
type PresentationControl = Literal["ambient", "tools"]
type OwnedContentKind = Literal["rendered-template", "raw-source", "source-fragments"]
type AssemblyLayerFailureReason = (
    RangeFailure
    | Literal[
        "source-unavailable",
        "template-grammar-invalid",
        "template-include-unsupported",
        "template-variable-unknown",
        "template-render-failed",
        "unsupported-family",
        "adapter-unavailable",
    ]
)
type AssemblyRenderErrorReason = Literal[
    "unknown-assembly",
    "unknown-scenario",
    "scenario-assembly-mismatch",
    "duplicate-workspace-path",
    "unknown-workspace-path",
]

# The exact descriptive marker for authored `optional: true` layers: presence varies by
# consuming session shape or runtime state — never a render-time filter.
PRESENCE_VARIES_LABEL = "Presence varies by session shape or runtime."

# The closed BoundaryKind → semantic owner id mapping (placeholders carry owner AND kind).
BOUNDARY_OWNERS: dict[BoundaryKind, BoundaryOwner] = {
    "pi-system": "pi",
    "user-content": "user",
    "runtime-state": "runtime",
    "borrowed-prompt": "borrowed-package",
}

# Exact safe per-layer failure details. No resolved paths, OS errors, adapter diagnostics,
# helper protocol details, or raw exception text ever enter an Assembly result.
FAILURE_DETAILS: dict[AssemblyLayerFailureReason, str] = {
    "source-unavailable": "The canonical source could not be read safely.",
    "template-grammar-invalid": (
        "The prompt template uses syntax outside the supported preview grammar."
    ),
    "template-include-unsupported": "Assembly preview does not support prompt includes.",
    "template-variable-unknown": (
        "The prompt template references a name outside the scenario's variables."
    ),
    "template-render-failed": "The prompt template could not be rendered for this scenario.",
    "unsupported-family": "The source family has no assembly extraction adapter.",
    "adapter-unavailable": "The source adapter could not run safely.",
    "unsupported-selector": "A catalog fragment uses a selector unsupported by its source adapter.",
    "unsupported-source-shape": (
        "A catalog fragment resolves to a source shape that cannot be extracted safely."
    ),
    "selector-not-found": "A catalog fragment no longer resolves in the current source.",
    "selector-ambiguous": "A catalog fragment resolves more than once in the current source.",
    "invalid-source": "The current source is not syntactically valid for its adapter.",
}


@dataclass(frozen=True, slots=True)
class WorkspaceBuffer:
    path: str
    text: str


@dataclass(frozen=True, slots=True)
class PresentationOverrides:
    include_ambient: bool | None
    include_tools: bool | None


@dataclass(frozen=True, slots=True)
class ResolvedPresentation:
    include_ambient: bool
    include_tools: bool


@dataclass(frozen=True, slots=True)
class LayerPresentation:
    position: int
    label: str | None
    presence: LayerPresence
    presence_label: str | None
    visibility_control: PresentationControl | None


@dataclass(frozen=True, slots=True)
class RenderedContentPart:
    fragment: Fragment | None
    text: str


@dataclass(frozen=True, slots=True)
class AssemblyLayerProblem:
    fragment: Fragment | None
    reason: AssemblyLayerFailureReason
    detail: str


@dataclass(frozen=True, slots=True)
class RenderedOwnedLayer:
    presentation: LayerPresentation
    unit: RoutedUnit
    content_kind: OwnedContentKind
    parts: tuple[RenderedContentPart, ...]


@dataclass(frozen=True, slots=True)
class RenderedBoundaryLayer:
    presentation: LayerPresentation
    boundary: BoundaryKind
    owner: BoundaryOwner


@dataclass(frozen=True, slots=True)
class FailedAssemblyLayer:
    presentation: LayerPresentation
    unit: RoutedUnit
    problems: tuple[AssemblyLayerProblem, ...]


@dataclass(frozen=True, slots=True)
class RenderedAssembly:
    assembly: Assembly
    scenario: Scenario
    presentation: ResolvedPresentation
    layers: tuple[RenderedOwnedLayer | RenderedBoundaryLayer | FailedAssemblyLayer, ...]


class AssemblyRenderError(Exception):
    """The whole render request is invalid, with a closed reason (never a layer result)."""

    def __init__(self, reason: AssemblyRenderErrorReason) -> None:
        super().__init__(reason)
        self.reason: AssemblyRenderErrorReason = reason


def _problem(
    fragment: Fragment | None,
    reason: AssemblyLayerFailureReason,
) -> AssemblyLayerProblem:
    return AssemblyLayerProblem(fragment=fragment, reason=reason, detail=FAILURE_DETAILS[reason])


def _layer_presentation(view: AssemblyLayerView) -> LayerPresentation:
    layer: AssemblyLayer = view.layer
    control: PresentationControl | None = None
    if view.unit is not None:
        if view.unit.role == "ambient-discovery":
            control = "ambient"
        elif view.unit.role == "tool-contract":
            control = "tools"
    return LayerPresentation(
        position=view.position,
        label=layer.label,
        presence="varies" if layer.optional else "always",
        presence_label=PRESENCE_VARIES_LABEL if layer.optional else None,
        visibility_control=control,
    )


def _is_raw_markdown(unit: RoutedUnit) -> bool:
    """Markdown outside ``prompts/`` (skills, agent definitions, managed ``.md`` prose)."""
    return (
        unit.candidate.kind in ("markdown", "managed-prose")
        and Path(unit.candidate.path).suffix.lower() == ".md"
    )


class AssemblyRenderer:
    """App-lifetime assembly preview composer over an explicit per-call snapshot.

    Captures only the resolved source root and the already-created app-scoped TypeScript
    SourceAdapter (its helper slot stays a real cross-operation resource bound; the
    concrete type also owns the ``TypeScriptAdapterUnavailable`` contract this renderer
    maps to the typed ``adapter-unavailable`` failure — a broader adapter here could
    misreport a wiring error as a content failure). The renderer accepts no session-shape
    id, request-selected read path, selector, fragment list, adapter, helper root,
    scenario variable override, or executable callback.
    """

    def __init__(self, repo_root: Path, typescript_adapter: TypeScriptSourceAdapter) -> None:
        self._repo_root = repo_root.resolve()
        self._typescript_adapter = typescript_adapter

    def render(
        self,
        snapshot: CatalogSnapshot,
        *,
        assembly_id: str,
        scenario_id: str,
        presentation: PresentationOverrides,
        workspace_buffers: tuple[WorkspaceBuffer, ...],
    ) -> RenderedAssembly:
        """Render every authored layer of one assembly under one selected scenario."""
        view = snapshot.get_assembly(assembly_id)
        if view is None:
            raise AssemblyRenderError("unknown-assembly")
        scenario = snapshot.get_scenario(scenario_id)
        if scenario is None:
            raise AssemblyRenderError("unknown-scenario")
        if scenario.assembly != assembly_id:
            raise AssemblyRenderError("scenario-assembly-mismatch")
        # The request is the browser's complete loaded workspace, so catalog-known paths
        # unrelated to this assembly are valid; duplicates and unknown paths are not.
        buffers: dict[str, str] = {}
        for buffer in workspace_buffers:
            if buffer.path in buffers:
                raise AssemblyRenderError("duplicate-workspace-path")
            if not snapshot.units_for_path(buffer.path):
                raise AssemblyRenderError("unknown-workspace-path")
            buffers[buffer.path] = buffer.text
        resolved = ResolvedPresentation(
            include_ambient=(
                scenario.include_ambient
                if presentation.include_ambient is None
                else presentation.include_ambient
            ),
            include_tools=(
                scenario.include_tools
                if presentation.include_tools is None
                else presentation.include_tools
            ),
        )
        # Request-local workspace-first text resolution: a buffered path (even an empty
        # string) is never reread; canonical reads and read failures are shared per path.
        text_cache: dict[str, str | None] = dict(buffers)
        layers: list[RenderedOwnedLayer | RenderedBoundaryLayer | FailedAssemblyLayer] = []
        for layer_view in view.layers:
            layers.append(self._render_layer(layer_view, scenario, text_cache))
        return RenderedAssembly(
            assembly=view.assembly,
            scenario=scenario,
            presentation=resolved,
            layers=tuple(layers),
        )

    def _render_layer(
        self,
        view: AssemblyLayerView,
        scenario: Scenario,
        text_cache: dict[str, str | None],
    ) -> RenderedOwnedLayer | RenderedBoundaryLayer | FailedAssemblyLayer:
        presentation = _layer_presentation(view)
        boundary = view.layer.boundary
        if boundary is not None:
            return RenderedBoundaryLayer(
                presentation=presentation,
                boundary=boundary,
                owner=BOUNDARY_OWNERS[boundary],
            )
        unit = view.unit
        if unit is None:  # pragma: no cover - a clean catalog authors one unit or boundary
            raise AssertionError("assembly layer carries neither unit nor boundary")
        text = self._layer_text(unit, text_cache)
        if text is None:
            return FailedAssemblyLayer(
                presentation=presentation,
                unit=unit,
                problems=(_problem(None, "source-unavailable"),),
            )
        template_name = prompt_template_name(unit.candidate)
        if template_name is not None:
            return self._render_prompt_layer(presentation, unit, scenario, text)
        if _is_raw_markdown(unit):
            return RenderedOwnedLayer(
                presentation=presentation,
                unit=unit,
                content_kind="raw-source",
                parts=(RenderedContentPart(fragment=None, text=text),),
            )
        return self._render_code_layer(presentation, unit, text)

    def _layer_text(self, unit: RoutedUnit, text_cache: dict[str, str | None]) -> str | None:
        path = unit.candidate.path
        if path in text_cache:
            return text_cache[path]
        try:
            text: str | None = read_unit_file(self._repo_root, unit).text
        except SourceReadError:
            text = None
        text_cache[path] = text
        return text

    def _render_prompt_layer(
        self,
        presentation: LayerPresentation,
        unit: RoutedUnit,
        scenario: Scenario,
        text: str,
    ) -> RenderedOwnedLayer | FailedAssemblyLayer:
        def failed(reason: AssemblyLayerFailureReason) -> FailedAssemblyLayer:
            return FailedAssemblyLayer(
                presentation=presentation,
                unit=unit,
                problems=(_problem(None, reason),),
            )

        scan = scan_template(text)
        if scan.violations:
            return failed("template-grammar-invalid")
        if scan.has_include:
            # Assembly preview supports no include (canonical or workspace): no editable
            # request may trigger the packaged prompts_dir() loader, and no render may
            # combine this renderer's source root with packaged/checkout prompt bytes.
            return failed("template-include-unsupported")
        variables = dict(scenario.variables)
        if scan.identifiers - variables.keys():
            # Mapping-only identifier semantics (the TS mini-jinja twin's namespace):
            # jinja's default Environment globals and the true/false/none literals are
            # unreachable because none appears in an authored scenario mapping.
            return failed("template-variable-unknown")
        try:
            rendered = render_text(text, variables)
        except TemplateError:
            # Reachable through gate-passing structural errors (if/endif imbalance).
            # A TypeError (non-string variable) stays loud: scenario variables are
            # catalog-validated string pairs, so that is a broken internal invariant.
            return failed("template-render-failed")
        return RenderedOwnedLayer(
            presentation=presentation,
            unit=unit,
            content_kind="rendered-template",
            parts=(RenderedContentPart(fragment=None, text=rendered),),
        )

    def _render_code_layer(
        self,
        presentation: LayerPresentation,
        unit: RoutedUnit,
        text: str,
    ) -> RenderedOwnedLayer | FailedAssemblyLayer:
        adapter = source_adapter_for(unit, typescript_adapter=self._typescript_adapter)
        if adapter is None:
            return FailedAssemblyLayer(
                presentation=presentation,
                unit=unit,
                problems=(_problem(None, "unsupported-family"),),
            )
        fragments = unit.candidate.fragments
        selectors = tuple(fragment.selector for fragment in fragments)
        try:
            extractions = adapter.extract_many(text, selectors)
        except TypeScriptAdapterUnavailable:
            return FailedAssemblyLayer(
                presentation=presentation,
                unit=unit,
                problems=(_problem(None, "adapter-unavailable"),),
            )
        problems = _code_problems(fragments, extractions)
        if problems:
            # Code layers are atomic result variants: any unresolved fragment fails the
            # whole authored layer with ordered problems and no partial content.
            return FailedAssemblyLayer(
                presentation=presentation,
                unit=unit,
                problems=problems,
            )
        return RenderedOwnedLayer(
            presentation=presentation,
            unit=unit,
            content_kind="source-fragments",
            parts=tuple(
                RenderedContentPart(fragment=fragment, text=extraction.focus)
                for fragment, extraction in zip(fragments, extractions, strict=True)
            ),
        )


def _code_problems(
    fragments: tuple[Fragment, ...],
    extractions: tuple[SourceExtraction, ...],
) -> tuple[AssemblyLayerProblem, ...]:
    """Ordered per-fragment problems, collapsing document-level invalid-source to one."""
    problems: list[AssemblyLayerProblem] = []
    saw_invalid_source = False
    for fragment, extraction in zip(fragments, extractions, strict=True):
        resolution = extraction.resolution
        if not isinstance(resolution, UnresolvedRange):
            continue
        if resolution.reason == "invalid-source":
            if not saw_invalid_source:
                problems.append(_problem(None, "invalid-source"))
                saw_invalid_source = True
            continue
        problems.append(_problem(fragment, resolution.reason))
    return tuple(problems)
