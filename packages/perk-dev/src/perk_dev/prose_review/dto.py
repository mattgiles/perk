"""The Prose Review Workbench serialization edge: catalog snapshot → wire DTOs.

Every response body is an ``OutputModel`` built here via ``from_domain`` — the HTTP
layer hands domain values to these constructors but never serializes a domain object
directly. Declaration order is the JSON key order, so the field order below is
deliberate.
"""

from collections.abc import Callable
from typing import Annotated, Literal, Self

from pydantic import Field

from perk.boundary import OutputModel
from perk_dev.prose_map.models import (
    Audience,
    BoundaryKind,
    Capability,
    DeliveryMode,
    Fragment,
    ProseKind,
    ProseRole,
    RoutedUnit,
    Scenario,
    SessionShape,
)
from perk_dev.prose_review.assembly import (
    AssemblyLayerFailureReason,
    AssemblyLayerProblem,
    BoundaryOwner,
    FailedAssemblyLayer,
    LayerPresence,
    LayerPresentation,
    OwnedContentKind,
    PresentationControl,
    RenderedAssembly,
    RenderedBoundaryLayer,
    RenderedContentPart,
    RenderedOwnedLayer,
    ResolvedPresentation,
)
from perk_dev.prose_review.catalog import (
    AssemblyConsumer,
    AssemblyLayerView,
    AssemblyView,
    CapabilityNode,
    CatalogQueryError,
    CatalogSnapshot,
    ConcernMember,
    ConcernView,
    LineageView,
    UnitAlias,
)
from perk_dev.prose_review.checks import CheckId, CheckRunSnapshot, CheckRunStatus
from perk_dev.prose_review.comparison import (
    ComparisonChoice,
    ComparisonGroup,
    ComparisonOptions,
    ComparisonPlacement,
    ComparisonRelation,
)
from perk_dev.prose_review.git import (
    GitDiffResult,
    GitDiffUnavailable,
    GitFileEntry,
    GitFileState,
    GitStatusResult,
    GitStatusUnavailable,
    GitUnavailableReason,
)
from perk_dev.prose_review.search import MatchField, SearchEntryKind, SearchHit, SearchResults
from perk_dev.prose_review.source_adapter import (
    CheckHintId,
    FocusedSource,
    LoadedSource,
    NewlineStyle,
    ReadOnlyReason,
    SourceConflict,
    SourceDiagnostic,
    SourceDiagnosticCode,
    SourceRefusalReason,
    SourceRefused,
    SourceSaved,
    SourceSaveResult,
    SourceValidationFailed,
    SuggestedCheck,
    WholeFileSource,
)


class CapabilityOut(OutputModel):
    """One capability as served over the wire (id + label only)."""

    id: str
    label: str

    @classmethod
    def from_domain(cls, capability: Capability) -> Self:
        return cls(id=capability.id, label=capability.label)


class CatalogSummaryOut(OutputModel):
    """The round-trip proof DTO: catalog counts + fixed-order top-level capabilities."""

    units: int
    fragments: int
    session_shapes: int
    assemblies: int
    scenarios: int
    concerns: int
    lineage_rules: int
    capabilities: tuple[CapabilityOut, ...]

    @classmethod
    def from_domain(cls, snapshot: CatalogSnapshot) -> Self:
        return cls(
            units=len(snapshot.units),
            fragments=len(snapshot.fragments),
            session_shapes=len(snapshot.session_shapes),
            assemblies=len(snapshot.assemblies),
            scenarios=len(snapshot.scenarios),
            concerns=len(snapshot.concerns),
            lineage_rules=len(snapshot.lineage),
            capabilities=tuple(
                CapabilityOut.from_domain(node.capability) for node in snapshot.capability_tree
            ),
        )


class UnitRefOut(OutputModel):
    """One routed unit as referenced from the capability tree."""

    id: str
    kind: ProseKind
    path: str

    @classmethod
    def from_domain(cls, unit: RoutedUnit) -> Self:
        return cls(id=unit.candidate.id, kind=unit.candidate.kind, path=unit.candidate.path)


class FragmentRefOut(OutputModel):
    """One logical fragment reference nested under its owning tree unit."""

    id: str
    label: str

    @classmethod
    def from_domain(cls, fragment: Fragment) -> Self:
        return cls(id=fragment.id, label=fragment.label)


class TreeUnitOut(OutputModel):
    """One tree unit with its authored logical fragments in catalog order."""

    id: str
    kind: ProseKind
    path: str
    fragments: tuple[FragmentRefOut, ...]

    @classmethod
    def from_domain(cls, unit: RoutedUnit) -> Self:
        return cls(
            id=unit.candidate.id,
            kind=unit.candidate.kind,
            path=unit.candidate.path,
            fragments=tuple(
                FragmentRefOut.from_domain(fragment) for fragment in unit.candidate.fragments
            ),
        )


class AssemblyLayerOut(OutputModel):
    """One ordered assembly layer: a routed unit or an ownership boundary."""

    position: int
    optional: bool
    label: str | None
    unit: TreeUnitOut | None
    boundary: BoundaryKind | None

    @classmethod
    def from_domain(cls, layer: AssemblyLayerView) -> Self:
        return cls(
            position=layer.position,
            optional=layer.layer.optional,
            label=layer.layer.label,
            unit=None if layer.unit is None else TreeUnitOut.from_domain(layer.unit),
            boundary=layer.layer.boundary,
        )


class SessionShapeOut(OutputModel):
    """One session shape with its assembly expanded to ordered layers."""

    id: str
    label: str
    delivery: DeliveryMode
    assembly: str
    layers: tuple[AssemblyLayerOut, ...]

    @classmethod
    def from_domain(cls, snapshot: CatalogSnapshot, shape: SessionShape) -> Self:
        assembly = snapshot.get_assembly(shape.assembly)
        if assembly is None:
            raise CatalogQueryError(
                f"session shape {shape.id} references unknown assembly: {shape.assembly}"
            )
        return cls(
            id=shape.id,
            label=shape.label,
            delivery=shape.delivery,
            assembly=shape.assembly,
            layers=tuple(AssemblyLayerOut.from_domain(layer) for layer in assembly.layers),
        )


class CapabilityNodeOut(OutputModel):
    """One capability tree node with its direct units, shapes, and children."""

    id: str
    label: str
    units: tuple[TreeUnitOut, ...]
    session_shapes: tuple[SessionShapeOut, ...]
    children: tuple["CapabilityNodeOut", ...]

    @classmethod
    def from_domain(cls, snapshot: CatalogSnapshot, node: CapabilityNode) -> Self:
        return cls(
            id=node.capability.id,
            label=node.capability.label,
            units=tuple(TreeUnitOut.from_domain(unit) for unit in node.units),
            session_shapes=tuple(
                SessionShapeOut.from_domain(snapshot, shape) for shape in node.session_shapes
            ),
            children=tuple(cls.from_domain(snapshot, child) for child in node.children),
        )


# Deterministic resolution of the quoted self-reference (harmless if pydantic
# already resolved it).
CapabilityNodeOut.model_rebuild()


class CapabilityTreeOut(OutputModel):
    """The whole capability tree in fixed top-level order."""

    capabilities: tuple[CapabilityNodeOut, ...]

    @classmethod
    def from_domain(cls, snapshot: CatalogSnapshot) -> Self:
        return cls(
            capabilities=tuple(
                CapabilityNodeOut.from_domain(snapshot, node) for node in snapshot.capability_tree
            )
        )


class SourceFileOut(OutputModel):
    """Immutable canonical-file metadata retained by the browser workspace."""

    path: str
    mode: int = Field(ge=0, le=0o7777)
    newline_style: NewlineStyle
    load_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_domain(cls, source: WholeFileSource) -> Self:
        return cls(
            path=source.path,
            mode=source.mode,
            newline_style=source.newline_style,
            load_hash=source.load_hash,
        )


class SavedSourceOut(OutputModel):
    """Identity-bearing source metadata returned only after a successful save."""

    unit: str
    kind: ProseKind
    file: SourceFileOut

    @classmethod
    def from_domain(cls, source: WholeFileSource) -> Self:
        return cls(
            unit=source.unit_id,
            kind=source.kind,
            file=SourceFileOut.from_domain(source),
        )


class SourceDiagnosticOut(OutputModel):
    """One closed validation diagnostic from the selected source adapter."""

    code: SourceDiagnosticCode
    message: str
    selector: str | None
    line: int | None
    column: int | None

    @classmethod
    def from_domain(cls, diagnostic: SourceDiagnostic) -> Self:
        return cls(
            code=diagnostic.code,
            message=diagnostic.message,
            selector=diagnostic.selector,
            line=diagnostic.line,
            column=diagnostic.column,
        )


class SuggestedCheckOut(OutputModel):
    """One named post-save check handoff with its allowlisted display command.

    Never auto-run by a save: execution happens only through the explicit
    CheckRunner endpoints on user action, against the same allowlist table this
    command string is rendered from.
    """

    id: CheckHintId
    command: str

    @classmethod
    def from_domain(cls, check: SuggestedCheck) -> Self:
        return cls(id=check.id, command=check.command)


class SourceViewOut(OutputModel):
    """One metadata-free whole-unit or fragment projection."""

    unit: str
    fragment: FragmentRefOut | None
    kind: ProseKind
    before: str
    focus: str
    after: str
    editable: bool
    read_only_reason: ReadOnlyReason | None

    @classmethod
    def from_domain(cls, source: FocusedSource) -> Self:
        return cls(
            unit=source.unit_id,
            fragment=(
                None if source.fragment is None else FragmentRefOut.from_domain(source.fragment)
            ),
            kind=source.kind,
            before=source.before,
            focus=source.focus,
            after=source.after,
            editable=source.editable,
            read_only_reason=source.read_only_reason,
        )


class UnitSourceOut(OutputModel):
    """One canonical file load and its requested nested projection."""

    file: SourceFileOut
    view: SourceViewOut

    @classmethod
    def from_domain(cls, source: LoadedSource) -> Self:
        return cls(
            file=SourceFileOut.from_domain(source.file),
            view=SourceViewOut.from_domain(source.view),
        )


class ShapeRefOut(OutputModel):
    """One session shape referenced as a delivery sibling (no layer expansion)."""

    id: str
    label: str
    delivery: DeliveryMode

    @classmethod
    def from_domain(cls, shape: SessionShape) -> Self:
        return cls(id=shape.id, label=shape.label, delivery=shape.delivery)


class ConsumerOut(OutputModel):
    """One canonical assembly-layer reference to the inspected unit."""

    assembly: str
    position: int
    label: str | None
    optional: bool

    @classmethod
    def from_domain(cls, consumer: AssemblyConsumer) -> Self:
        return cls(
            assembly=consumer.assembly.assembly.id,
            position=consumer.layer.position,
            label=consumer.layer.layer.label,
            optional=consumer.layer.layer.optional,
        )


class ConsumingShapeOut(OutputModel):
    """One session shape consuming the inspected unit, with its delivery siblings."""

    id: str
    label: str
    delivery: DeliveryMode
    breadcrumb: tuple[CapabilityOut, ...]
    siblings: tuple[ShapeRefOut, ...]

    @classmethod
    def from_domain(cls, snapshot: CatalogSnapshot, alias: UnitAlias) -> Self:
        shape = alias.session_shape
        return cls(
            id=shape.id,
            label=shape.label,
            delivery=shape.delivery,
            breadcrumb=tuple(
                CapabilityOut.from_domain(capability) for capability in alias.capability_breadcrumb
            ),
            siblings=tuple(
                ShapeRefOut.from_domain(sibling) for sibling in snapshot.delivery_siblings(shape.id)
            ),
        )


class ConcernMemberOut(OutputModel):
    """One other member of a concern the inspected unit belongs to."""

    unit: UnitRefOut
    relation: str | None
    canonical: bool

    @classmethod
    def from_domain(cls, member: ConcernMember) -> Self:
        return cls(
            unit=UnitRefOut.from_domain(member.unit),
            relation=member.relation,
            canonical=member.canonical,
        )


class ConcernOut(OutputModel):
    """One concern from the inspected unit's standpoint: its standing + the relatives."""

    id: str
    label: str
    summary: str
    canonical: bool
    relation: str | None
    members: tuple[ConcernMemberOut, ...]

    @classmethod
    def from_domain(cls, view: ConcernView, unit_id: str) -> Self:
        selected = next(member for member in view.members if member.unit.candidate.id == unit_id)
        return cls(
            id=view.concern.id,
            label=view.concern.label,
            summary=view.concern.summary,
            canonical=selected.canonical,
            relation=selected.relation,
            members=tuple(
                ConcernMemberOut.from_domain(member)
                for member in view.members
                if member.unit.candidate.id != unit_id
            ),
        )


class LineageOut(OutputModel):
    """One authored lineage rule matching the inspected unit, labeled as authored."""

    id: str
    relationship: str
    targets: tuple[str, ...]

    @classmethod
    def from_domain(cls, view: LineageView) -> Self:
        return cls(
            id=view.lineage.id,
            relationship=view.lineage.relationship,
            targets=view.lineage.targets,
        )


class SourceSavedOut(OutputModel):
    status: Literal["saved"]
    source: SavedSourceOut
    materialized: tuple[LineageOut, ...]
    checks: tuple[SuggestedCheckOut, ...]
    catalog_refreshed: bool
    refresh_detail: str | None

    @classmethod
    def from_domain(cls, result: SourceSaved) -> Self:
        return cls(
            status=result.status,
            source=SavedSourceOut.from_domain(result.source),
            materialized=tuple(LineageOut.from_domain(view) for view in result.materialized),
            checks=tuple(SuggestedCheckOut.from_domain(check) for check in result.checks),
            catalog_refreshed=result.catalog_refreshed,
            refresh_detail=result.refresh_detail,
        )


class SourceValidationFailedOut(OutputModel):
    status: Literal["validation-failed"]
    diagnostics: tuple[SourceDiagnosticOut, ...]

    @classmethod
    def from_domain(cls, result: SourceValidationFailed) -> Self:
        return cls(
            status=result.status,
            diagnostics=tuple(
                SourceDiagnosticOut.from_domain(diagnostic) for diagnostic in result.diagnostics
            ),
        )


class SourceConflictOut(OutputModel):
    status: Literal["conflict"]
    detail: str

    @classmethod
    def from_domain(cls, result: SourceConflict) -> Self:
        return cls(status=result.status, detail=result.detail)


class SourceRefusedOut(OutputModel):
    status: Literal["refused"]
    reason: SourceRefusalReason
    detail: str

    @classmethod
    def from_domain(cls, result: SourceRefused) -> Self:
        return cls(status=result.status, reason=result.reason, detail=result.detail)


type SourceSaveOut = (
    SourceSavedOut | SourceValidationFailedOut | SourceConflictOut | SourceRefusedOut
)


def source_save_out(result: SourceSaveResult) -> SourceSaveOut:
    """Map one closed save result to its tagged output boundary."""
    if isinstance(result, SourceSaved):
        return SourceSavedOut.from_domain(result)
    if isinstance(result, SourceValidationFailed):
        return SourceValidationFailedOut.from_domain(result)
    if isinstance(result, SourceConflict):
        return SourceConflictOut.from_domain(result)
    return SourceRefusedOut.from_domain(result)


class CheckRunOut(OutputModel):
    """One check-run snapshot serialized from the requested offset (offset polling)."""

    run: str
    check: CheckId
    label: str
    command: str
    status: CheckRunStatus
    exit_code: int | None
    output: str
    next_offset: int
    truncated: bool

    @classmethod
    def from_domain(cls, snapshot: CheckRunSnapshot, offset: int) -> Self:
        # Offsets are Python str indexes over the monotone append-only capture;
        # clamping to the captured length keeps every requested slice total.
        clamped = min(max(offset, 0), len(snapshot.output))
        return cls(
            run=snapshot.run_id,
            check=snapshot.check,
            label=snapshot.label,
            command=snapshot.command,
            status=snapshot.status,
            exit_code=snapshot.exit_code,
            output=snapshot.output[clamped:],
            next_offset=len(snapshot.output),
            truncated=snapshot.truncated,
        )


class LatestCheckOut(OutputModel):
    """The reconciliation read: the most recent run (offset 0, full output) or null."""

    run: CheckRunOut | None

    @classmethod
    def from_domain(cls, snapshot: CheckRunSnapshot | None) -> Self:
        return cls(run=None if snapshot is None else CheckRunOut.from_domain(snapshot, 0))


class GitFileStatusOut(OutputModel):
    """One catalog-mapped path with its folded working-tree state."""

    path: str
    state: GitFileState

    @classmethod
    def from_domain(cls, entry: GitFileEntry) -> Self:
        return cls(path=entry.path, state=entry.state)


class GitStatusOut(OutputModel):
    """The always-200 working-tree status envelope, partitioned by catalog membership.

    Construction enforces the exact tagged combinations the frontend parsers pin:
    available ⇒ ``reason is None``; unavailable ⇒ ``entries == ()`` and
    ``other_change_count == 0``. ``is_catalog_path`` is the handler's captured-
    generation membership predicate — non-catalog and anonymous undecodable records
    are only ever counted, never listed.
    """

    status: Literal["available", "unavailable"]
    reason: GitUnavailableReason | None
    entries: tuple[GitFileStatusOut, ...]
    other_change_count: int

    @classmethod
    def from_domain(cls, result: GitStatusResult, is_catalog_path: Callable[[str], bool]) -> Self:
        if isinstance(result, GitStatusUnavailable):
            return cls(status="unavailable", reason=result.reason, entries=(), other_change_count=0)
        mapped = sorted(
            (entry for entry in result.entries if is_catalog_path(entry.path)),
            key=lambda entry: entry.path,
        )
        other = result.other_paths + sum(
            1 for entry in result.entries if not is_catalog_path(entry.path)
        )
        return cls(
            status="available",
            reason=None,
            entries=tuple(GitFileStatusOut.from_domain(entry) for entry in mapped),
            other_change_count=other,
        )


class GitDiffOut(OutputModel):
    """The always-200 per-file diff envelope.

    Construction enforces: available ⇒ ``reason is None`` and ``diff`` is a string
    (possibly empty); unavailable ⇒ ``diff is None`` and ``truncated is False``.
    """

    status: Literal["available", "unavailable"]
    reason: GitUnavailableReason | None
    diff: str | None
    truncated: bool

    @classmethod
    def from_domain(cls, result: GitDiffResult) -> Self:
        if isinstance(result, GitDiffUnavailable):
            return cls(status="unavailable", reason=result.reason, diff=None, truncated=False)
        return cls(status="available", reason=None, diff=result.diff, truncated=result.truncated)


class UnitInspectOut(OutputModel):
    """The relationship inspector payload for one canonical routed unit."""

    id: str
    kind: ProseKind
    path: str
    selector: str
    audience: Audience
    role: ProseRole
    breadcrumb: tuple[CapabilityOut, ...]
    capability_children: tuple[CapabilityOut, ...]
    consumers: tuple[ConsumerOut, ...]
    shapes: tuple[ConsumingShapeOut, ...]
    concerns: tuple[ConcernOut, ...]
    lineage: tuple[LineageOut, ...]

    @classmethod
    def from_domain(cls, snapshot: CatalogSnapshot, unit: RoutedUnit) -> Self:
        unit_id = unit.candidate.id
        # A unit appearing in several layers of one assembly yields several aliases
        # per consuming shape; the inspector shows one entry per shape (first alias
        # wins — the breadcrumb is identical across duplicates).
        aliases: dict[str, UnitAlias] = {}
        for alias in snapshot.aliases_for_unit(unit_id):
            aliases.setdefault(alias.session_shape.id, alias)
        return cls(
            id=unit_id,
            kind=unit.candidate.kind,
            path=unit.candidate.path,
            selector=unit.candidate.selector,
            audience=unit.audience,
            role=unit.role,
            breadcrumb=tuple(
                CapabilityOut.from_domain(capability)
                for capability in snapshot.capability_breadcrumb(unit.capability)
            ),
            capability_children=tuple(
                CapabilityOut.from_domain(capability)
                for capability in snapshot.capability_children(unit.capability)
            ),
            consumers=tuple(
                ConsumerOut.from_domain(consumer)
                for consumer in snapshot.consumers_for_unit(unit_id)
            ),
            shapes=tuple(
                ConsumingShapeOut.from_domain(snapshot, alias) for alias in aliases.values()
            ),
            concerns=tuple(
                ConcernOut.from_domain(view, unit_id)
                for view in snapshot.concerns_for_unit(unit_id)
            ),
            lineage=tuple(
                LineageOut.from_domain(view) for view in snapshot.lineage_for_unit(unit_id)
            ),
        )


class ComparisonPlacementOut(OutputModel):
    """One whole-unit source identity plus its comparison relation context."""

    unit: UnitRefOut
    breadcrumb: tuple[CapabilityOut, ...]
    shape: ShapeRefOut | None
    assembly: str | None
    position: int | None
    label: str

    @classmethod
    def from_domain(cls, placement: ComparisonPlacement) -> Self:
        return cls(
            unit=UnitRefOut.from_domain(placement.unit),
            breadcrumb=tuple(
                CapabilityOut.from_domain(capability) for capability in placement.breadcrumb
            ),
            shape=(None if placement.shape is None else ShapeRefOut.from_domain(placement.shape)),
            assembly=placement.assembly,
            position=placement.position,
            label=placement.label,
        )


class ComparisonChoiceOut(OutputModel):
    """One server-labeled whole-unit comparison target."""

    label: str
    detail: str
    target: ComparisonPlacementOut

    @classmethod
    def from_domain(cls, choice: ComparisonChoice) -> Self:
        return cls(
            label=choice.label,
            detail=choice.detail,
            target=ComparisonPlacementOut.from_domain(choice.target),
        )


class ComparisonGroupOut(OutputModel):
    """One non-empty graph relation family in fixed response order."""

    relation: ComparisonRelation
    label: str
    choices: tuple[ComparisonChoiceOut, ...]

    @classmethod
    def from_domain(cls, group: ComparisonGroup) -> Self:
        return cls(
            relation=group.relation,
            label=group.label,
            choices=tuple(ComparisonChoiceOut.from_domain(choice) for choice in group.choices),
        )


class ComparisonOptionsOut(OutputModel):
    """The authoritative comparison origin and its ordered relation groups."""

    origin: ComparisonPlacementOut
    groups: tuple[ComparisonGroupOut, ...]

    @classmethod
    def from_domain(cls, options: ComparisonOptions) -> Self:
        return cls(
            origin=ComparisonPlacementOut.from_domain(options.origin),
            groups=tuple(ComparisonGroupOut.from_domain(group) for group in options.groups),
        )


class SearchResultOut(OutputModel):
    """One search hit: the entity, its breadcrumb, and the matched field names."""

    kind: SearchEntryKind
    id: str
    label: str
    breadcrumb: tuple[CapabilityOut, ...]
    unit: UnitRefOut | None
    matched: tuple[MatchField, ...]

    @classmethod
    def from_domain(cls, hit: SearchHit) -> Self:
        entry = hit.entry
        return cls(
            kind=entry.kind,
            id=entry.entity_id,
            label=entry.label,
            breadcrumb=tuple(
                CapabilityOut.from_domain(capability) for capability in entry.breadcrumb
            ),
            unit=None if entry.unit is None else UnitRefOut.from_domain(entry.unit),
            matched=hit.matched,
        )


class SearchOut(OutputModel):
    """The search response: the full match count plus the capped, ordered results."""

    total: int
    results: tuple[SearchResultOut, ...]

    @classmethod
    def from_domain(cls, results: SearchResults) -> Self:
        return cls(
            total=results.total,
            results=tuple(SearchResultOut.from_domain(hit) for hit in results.hits),
        )


class AssemblyScenarioOut(OutputModel):
    """One authored scenario fixture: label, variables object, presentation defaults."""

    id: str
    label: str
    variables: dict[str, str]
    include_ambient: bool
    include_tools: bool

    @classmethod
    def from_domain(cls, scenario: Scenario) -> Self:
        # A JSON object inserted from the domain's sorted pairs, not an array of pairs.
        return cls(
            id=scenario.id,
            label=scenario.label,
            variables=dict(scenario.variables),
            include_ambient=scenario.include_ambient,
            include_tools=scenario.include_tools,
        )


class AssemblyOptionsOut(OutputModel):
    """One assembly id plus its complete ordered scenario fixtures."""

    assembly: str
    scenarios: tuple[AssemblyScenarioOut, ...]

    @classmethod
    def from_domain(cls, view: AssemblyView) -> Self:
        return cls(
            assembly=view.assembly.id,
            scenarios=tuple(
                AssemblyScenarioOut.from_domain(scenario) for scenario in view.scenarios
            ),
        )


class AssemblyPresentationOut(OutputModel):
    """The resolved top-level presentation booleans (defaults plus overrides)."""

    include_ambient: bool
    include_tools: bool

    @classmethod
    def from_domain(cls, presentation: ResolvedPresentation) -> Self:
        return cls(
            include_ambient=presentation.include_ambient,
            include_tools=presentation.include_tools,
        )


class AssemblyLayerPresentationOut(OutputModel):
    """Common per-layer presentation metadata, nested under every layer variant."""

    position: int
    label: str | None
    presence: LayerPresence
    presence_label: str | None
    visibility_control: PresentationControl | None

    @classmethod
    def from_domain(cls, presentation: LayerPresentation) -> Self:
        return cls(
            position=presentation.position,
            label=presentation.label,
            presence=presentation.presence,
            presence_label=presentation.presence_label,
            visibility_control=presentation.visibility_control,
        )


class AssemblyContentPartOut(OutputModel):
    """One ordered content part with optional fragment provenance."""

    fragment: FragmentRefOut | None
    text: str

    @classmethod
    def from_domain(cls, part: RenderedContentPart) -> Self:
        return cls(
            fragment=(None if part.fragment is None else FragmentRefOut.from_domain(part.fragment)),
            text=part.text,
        )


class AssemblyLayerProblemOut(OutputModel):
    """One typed per-layer failure with its fixed safe detail copy."""

    fragment: FragmentRefOut | None
    reason: AssemblyLayerFailureReason
    detail: str

    @classmethod
    def from_domain(cls, problem: AssemblyLayerProblem) -> Self:
        return cls(
            fragment=(
                None if problem.fragment is None else FragmentRefOut.from_domain(problem.fragment)
            ),
            reason=problem.reason,
            detail=problem.detail,
        )


class RenderedOwnedLayerOut(OutputModel):
    """One successfully composed owned layer with its ordered content parts."""

    type: Literal["owned"]
    presentation: AssemblyLayerPresentationOut
    unit: UnitRefOut
    content_kind: OwnedContentKind
    parts: tuple[AssemblyContentPartOut, ...]

    @classmethod
    def from_domain(cls, layer: RenderedOwnedLayer) -> Self:
        return cls(
            type="owned",
            presentation=AssemblyLayerPresentationOut.from_domain(layer.presentation),
            unit=UnitRefOut.from_domain(layer.unit),
            content_kind=layer.content_kind,
            parts=tuple(AssemblyContentPartOut.from_domain(part) for part in layer.parts),
        )


class RenderedBoundaryLayerOut(OutputModel):
    """One external ownership placeholder carrying boundary kind plus owner id."""

    type: Literal["boundary"]
    presentation: AssemblyLayerPresentationOut
    boundary: BoundaryKind
    owner: BoundaryOwner

    @classmethod
    def from_domain(cls, layer: RenderedBoundaryLayer) -> Self:
        return cls(
            type="boundary",
            presentation=AssemblyLayerPresentationOut.from_domain(layer.presentation),
            boundary=layer.boundary,
            owner=layer.owner,
        )


class FailedAssemblyLayerOut(OutputModel):
    """One sibling-preserving typed failure layer with ordered safe problems."""

    type: Literal["failure"]
    presentation: AssemblyLayerPresentationOut
    unit: UnitRefOut
    problems: tuple[AssemblyLayerProblemOut, ...]

    @classmethod
    def from_domain(cls, layer: FailedAssemblyLayer) -> Self:
        return cls(
            type="failure",
            presentation=AssemblyLayerPresentationOut.from_domain(layer.presentation),
            unit=UnitRefOut.from_domain(layer.unit),
            problems=tuple(
                AssemblyLayerProblemOut.from_domain(problem) for problem in layer.problems
            ),
        )


type AssemblyRenderedLayerOut = Annotated[
    RenderedOwnedLayerOut | RenderedBoundaryLayerOut | FailedAssemblyLayerOut,
    Field(discriminator="type"),
]


def _rendered_layer_out(
    layer: RenderedOwnedLayer | RenderedBoundaryLayer | FailedAssemblyLayer,
) -> RenderedOwnedLayerOut | RenderedBoundaryLayerOut | FailedAssemblyLayerOut:
    if isinstance(layer, RenderedOwnedLayer):
        return RenderedOwnedLayerOut.from_domain(layer)
    if isinstance(layer, RenderedBoundaryLayer):
        return RenderedBoundaryLayerOut.from_domain(layer)
    return FailedAssemblyLayerOut.from_domain(layer)


class AssemblyRenderOut(OutputModel):
    """One complete guarded assembly render: every authored layer in authored order."""

    assembly: str
    scenario: AssemblyScenarioOut
    presentation: AssemblyPresentationOut
    layers: tuple[AssemblyRenderedLayerOut, ...]

    @classmethod
    def from_domain(cls, rendered: RenderedAssembly) -> Self:
        return cls(
            assembly=rendered.assembly.id,
            scenario=AssemblyScenarioOut.from_domain(rendered.scenario),
            presentation=AssemblyPresentationOut.from_domain(rendered.presentation),
            layers=tuple(_rendered_layer_out(layer) for layer in rendered.layers),
        )
