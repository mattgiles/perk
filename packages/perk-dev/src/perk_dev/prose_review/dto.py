"""The Prose Review Workbench serialization edge: catalog snapshot → wire DTOs.

Every response body is an ``OutputModel`` built here via ``from_domain`` — the HTTP
layer hands domain values to these constructors but never serializes a domain object
directly. Declaration order is the JSON key order, so the field order below is
deliberate.
"""

from typing import Self

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
    SessionShape,
)
from perk_dev.prose_review.catalog import (
    AssemblyConsumer,
    AssemblyLayerView,
    CapabilityNode,
    CatalogQueryError,
    CatalogSnapshot,
    ConcernMember,
    ConcernView,
    LineageView,
    UnitAlias,
)
from perk_dev.prose_review.search import MatchField, SearchEntryKind, SearchHit, SearchResults
from perk_dev.prose_review.source_adapter import FocusedSource, ReadOnlyReason


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


class UnitSourceOut(OutputModel):
    """One whole-unit or fragment-focused source read as served over the wire."""

    unit: str
    fragment: FragmentRefOut | None
    path: str
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
            path=source.path,
            kind=source.kind,
            before=source.before,
            focus=source.focus,
            after=source.after,
            editable=source.editable,
            read_only_reason=source.read_only_reason,
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
