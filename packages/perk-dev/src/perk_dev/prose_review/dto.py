"""The Prose Review Workbench serialization edge: catalog snapshot → wire DTOs.

The HTTP layer never touches domain objects — every response body is an
``OutputModel`` built here via ``from_domain``. Declaration order is the JSON key
order, so the field order below is deliberate.
"""

from typing import Self

from perk.boundary import OutputModel
from perk_dev.prose_map.models import (
    BoundaryKind,
    Capability,
    DeliveryMode,
    ProseKind,
    RoutedUnit,
    SessionShape,
)
from perk_dev.prose_review.catalog import (
    AssemblyLayerView,
    CapabilityNode,
    CatalogQueryError,
    CatalogSnapshot,
)
from perk_dev.prose_review.source_adapter import WholeFileSource


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


class AssemblyLayerOut(OutputModel):
    """One ordered assembly layer: a routed unit or an ownership boundary."""

    position: int
    optional: bool
    label: str | None
    unit: UnitRefOut | None
    boundary: BoundaryKind | None

    @classmethod
    def from_domain(cls, layer: AssemblyLayerView) -> Self:
        return cls(
            position=layer.position,
            optional=layer.layer.optional,
            label=layer.layer.label,
            unit=None if layer.unit is None else UnitRefOut.from_domain(layer.unit),
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
    units: tuple[UnitRefOut, ...]
    session_shapes: tuple[SessionShapeOut, ...]
    children: tuple["CapabilityNodeOut", ...]

    @classmethod
    def from_domain(cls, snapshot: CatalogSnapshot, node: CapabilityNode) -> Self:
        return cls(
            id=node.capability.id,
            label=node.capability.label,
            units=tuple(UnitRefOut.from_domain(unit) for unit in node.units),
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
    """One unit's whole source file as served over the wire."""

    unit: str
    path: str
    kind: ProseKind
    content: str

    @classmethod
    def from_domain(cls, source: WholeFileSource) -> Self:
        return cls(unit=source.unit_id, path=source.path, kind=source.kind, content=source.text)
