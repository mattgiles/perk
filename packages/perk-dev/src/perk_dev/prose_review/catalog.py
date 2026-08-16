"""Immutable query snapshot over the validated living prose catalog."""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from types import MappingProxyType
from typing import Self

from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import (
    Assembly,
    AssemblyLayer,
    Capability,
    Catalog,
    Concern,
    Fragment,
    Lineage,
    RoutedUnit,
    Scenario,
    SessionShape,
)

_TOP_LEVEL_CAPABILITY_ORDER = (
    "foundation",
    "intent",
    "planning",
    "delivery",
    "review",
    "knowledge",
    "extension",
)


class CatalogQueryError(Exception):
    """A validated prose catalog cannot support an unambiguous query snapshot."""


@dataclass(frozen=True, slots=True)
class RoutedFragment:
    """A logical fragment resolved to its canonical routed unit."""

    unit: RoutedUnit
    fragment: Fragment


@dataclass(frozen=True, slots=True)
class CapabilityNode:
    """One capability tree node with its direct units and session shapes."""

    capability: Capability
    breadcrumb: tuple[Capability, ...]
    units: tuple[RoutedUnit, ...]
    session_shapes: tuple[SessionShape, ...]
    children: tuple["CapabilityNode", ...]


@dataclass(frozen=True, slots=True)
class AssemblyLayerView:
    """One authored assembly layer with a one-based position and resolved unit."""

    position: int
    layer: AssemblyLayer
    unit: RoutedUnit | None


@dataclass(frozen=True, slots=True)
class AssemblyView:
    """An assembly with ordered layers, consuming shapes, and authored scenarios."""

    assembly: Assembly
    layers: tuple[AssemblyLayerView, ...]
    session_shapes: tuple[SessionShape, ...]
    scenarios: tuple[Scenario, ...]


@dataclass(frozen=True, slots=True)
class AssemblyConsumer:
    """One canonical assembly-layer reference to a routed unit."""

    assembly: AssemblyView
    layer: AssemblyLayerView


@dataclass(frozen=True, slots=True)
class UnitAlias:
    """One shape-expanded tree appearance of a canonical routed unit."""

    session_shape: SessionShape
    capability_breadcrumb: tuple[Capability, ...]
    assembly: AssemblyView
    layer: AssemblyLayerView


@dataclass(frozen=True, slots=True)
class ConcernMember:
    """A resolved member of a concern, canonical first then authored relatives."""

    unit: RoutedUnit
    relation: str | None
    canonical: bool


@dataclass(frozen=True, slots=True)
class ConcernView:
    """A concern with every referenced unit resolved."""

    concern: Concern
    members: tuple[ConcernMember, ...]


@dataclass(frozen=True, slots=True)
class ConcernRelative:
    """Another unit related to the selected unit through a concern."""

    concern: Concern
    member: ConcernMember


@dataclass(frozen=True, slots=True)
class LineageView:
    """An authored lineage rule with its routed source units resolved."""

    lineage: Lineage
    sources: tuple[RoutedUnit, ...]


@dataclass(frozen=True, slots=True)
class _SnapshotIndexes:
    capabilities: Mapping[str, Capability]
    capability_children: Mapping[str, tuple[Capability, ...]]
    capability_breadcrumbs: Mapping[str, tuple[Capability, ...]]
    units: Mapping[str, RoutedUnit]
    units_by_capability: Mapping[str, tuple[RoutedUnit, ...]]
    fragments: Mapping[tuple[str, str], RoutedFragment]
    fragments_by_unit: Mapping[str, tuple[RoutedFragment, ...]]
    session_shapes: Mapping[str, SessionShape]
    shapes_by_capability: Mapping[str, tuple[SessionShape, ...]]
    delivery_siblings: Mapping[str, tuple[SessionShape, ...]]
    assemblies: Mapping[str, AssemblyView]
    scenarios: Mapping[str, Scenario]
    scenarios_by_assembly: Mapping[str, tuple[Scenario, ...]]
    consumers_by_unit: Mapping[str, tuple[AssemblyConsumer, ...]]
    aliases_by_unit: Mapping[str, tuple[UnitAlias, ...]]
    concerns: Mapping[str, ConcernView]
    concerns_by_unit: Mapping[str, tuple[ConcernView, ...]]
    concern_relatives: Mapping[str, tuple[ConcernRelative, ...]]
    lineage: Mapping[str, LineageView]
    lineage_by_unit: Mapping[str, tuple[LineageView, ...]]


def _freeze[K, V](values: dict[K, V]) -> Mapping[K, V]:
    return MappingProxyType(values)


def _freeze_groups[K, V](values: Mapping[K, list[V]]) -> Mapping[K, tuple[V, ...]]:
    return MappingProxyType({key: tuple(items) for key, items in values.items()})


def _required[T](values: Mapping[str, T], key: str, owner: str) -> T:
    value = values.get(key)
    if value is None:
        raise CatalogQueryError(f"{owner} references unrouted unit or unknown id: {key}")
    return value


def _require_clean(catalog: Catalog) -> None:
    if not catalog.findings:
        return
    details = "; ".join(f"{finding.code}: {finding.message}" for finding in catalog.findings)
    raise CatalogQueryError(f"prose catalog has validation findings: {details}")


def _capability_structure(
    catalog: Catalog,
) -> tuple[
    tuple[Capability, ...],
    Mapping[str, Capability],
    Mapping[str, tuple[Capability, ...]],
    Mapping[str, tuple[Capability, ...]],
]:
    capabilities = {capability.id: capability for capability in catalog.graph.capabilities}
    children: defaultdict[str | None, list[Capability]] = defaultdict(list)
    for capability in catalog.graph.capabilities:
        children[capability.parent].append(capability)

    root_rank = {
        capability_id: index for index, capability_id in enumerate(_TOP_LEVEL_CAPABILITY_ORDER)
    }
    authored_rank = {
        capability.id: index for index, capability in enumerate(catalog.graph.capabilities)
    }
    roots = tuple(
        sorted(
            children[None],
            key=lambda capability: (
                root_rank.get(capability.id, len(root_rank)),
                authored_rank[capability.id],
            ),
        )
    )

    breadcrumbs: dict[str, tuple[Capability, ...]] = {}

    def visit(capability: Capability, ancestors: tuple[Capability, ...]) -> None:
        if capability.id in breadcrumbs:
            raise CatalogQueryError(f"capability hierarchy repeats or cycles at {capability.id}")
        breadcrumb = (*ancestors, capability)
        breadcrumbs[capability.id] = breadcrumb
        for child in children[capability.id]:
            visit(child, breadcrumb)

    for root in roots:
        visit(root, ())
    if len(breadcrumbs) != len(capabilities):
        missing = sorted(set(capabilities) - set(breadcrumbs))
        raise CatalogQueryError(
            f"capability hierarchy has no rooted path for: {', '.join(missing)}"
        )

    frozen_children = {
        capability_id: tuple(children[capability_id]) for capability_id in capabilities
    }
    return (
        roots,
        _freeze(capabilities),
        _freeze(frozen_children),
        _freeze(breadcrumbs),
    )


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """A load-once, immutable view of every workbench catalog query."""

    capability_tree: tuple[CapabilityNode, ...]
    units: tuple[RoutedUnit, ...]
    fragments: tuple[RoutedFragment, ...]
    session_shapes: tuple[SessionShape, ...]
    assemblies: tuple[AssemblyView, ...]
    scenarios: tuple[Scenario, ...]
    concerns: tuple[ConcernView, ...]
    lineage: tuple[LineageView, ...]
    _indexes: _SnapshotIndexes = field(repr=False)

    @classmethod
    def from_catalog(cls, catalog: Catalog) -> Self:
        """Build an immutable query snapshot from one clean prose-map catalog."""
        _require_clean(catalog)
        roots, capabilities, capability_children, breadcrumbs = _capability_structure(catalog)

        units = {unit.candidate.id: unit for unit in catalog.units}
        units_by_capability_mutable: defaultdict[str, list[RoutedUnit]] = defaultdict(list)
        for unit in catalog.units:
            units_by_capability_mutable[unit.capability].append(unit)
        units_by_capability = _freeze_groups(units_by_capability_mutable)

        fragments: list[RoutedFragment] = []
        fragments_by_id: dict[tuple[str, str], RoutedFragment] = {}
        fragments_by_unit_mutable: defaultdict[str, list[RoutedFragment]] = defaultdict(list)
        for unit in catalog.units:
            for fragment in unit.candidate.fragments:
                routed = RoutedFragment(unit=unit, fragment=fragment)
                key = (unit.candidate.id, fragment.id)
                if key in fragments_by_id:
                    raise CatalogQueryError(
                        f"unit {unit.candidate.id} has duplicate fragment id: {fragment.id}"
                    )
                fragments.append(routed)
                fragments_by_id[key] = routed
                fragments_by_unit_mutable[unit.candidate.id].append(routed)

        session_shapes = {shape.id: shape for shape in catalog.graph.session_shapes}
        shapes_by_capability_mutable: defaultdict[str, list[SessionShape]] = defaultdict(list)
        shapes_by_family: defaultdict[tuple[str, str], list[SessionShape]] = defaultdict(list)
        for shape in catalog.graph.session_shapes:
            shapes_by_capability_mutable[shape.capability].append(shape)
            shapes_by_family[(shape.capability, shape.assembly)].append(shape)
        shapes_by_capability = _freeze_groups(shapes_by_capability_mutable)

        delivery_siblings = {
            shape.id: tuple(
                sibling
                for sibling in shapes_by_family[(shape.capability, shape.assembly)]
                if sibling.id != shape.id
            )
            for shape in catalog.graph.session_shapes
        }

        scenarios = {scenario.id: scenario for scenario in catalog.graph.scenarios}
        scenarios_by_assembly_mutable: defaultdict[str, list[Scenario]] = defaultdict(list)
        for scenario in catalog.graph.scenarios:
            scenarios_by_assembly_mutable[scenario.assembly].append(scenario)
        scenarios_by_assembly = _freeze_groups(scenarios_by_assembly_mutable)

        assembly_views: list[AssemblyView] = []
        assemblies: dict[str, AssemblyView] = {}
        shapes_by_assembly: defaultdict[str, list[SessionShape]] = defaultdict(list)
        for shape in catalog.graph.session_shapes:
            shapes_by_assembly[shape.assembly].append(shape)
        for assembly in catalog.graph.assemblies:
            layers: list[AssemblyLayerView] = []
            for position, layer in enumerate(assembly.layers, start=1):
                unit = None
                if layer.unit is not None:
                    unit = _required(units, layer.unit, f"assembly {assembly.id}")
                layers.append(AssemblyLayerView(position=position, layer=layer, unit=unit))
            view = AssemblyView(
                assembly=assembly,
                layers=tuple(layers),
                session_shapes=tuple(shapes_by_assembly[assembly.id]),
                scenarios=scenarios_by_assembly.get(assembly.id, ()),
            )
            assembly_views.append(view)
            assemblies[assembly.id] = view

        consumers_by_unit_mutable: defaultdict[str, list[AssemblyConsumer]] = defaultdict(list)
        for assembly in assembly_views:
            for layer in assembly.layers:
                if layer.unit is None:
                    continue
                consumers_by_unit_mutable[layer.unit.candidate.id].append(
                    AssemblyConsumer(assembly=assembly, layer=layer)
                )

        aliases_by_unit_mutable: defaultdict[str, list[UnitAlias]] = defaultdict(list)
        for shape in catalog.graph.session_shapes:
            assembly = _required(assemblies, shape.assembly, f"session shape {shape.id}")
            breadcrumb = _required(breadcrumbs, shape.capability, f"session shape {shape.id}")
            for layer in assembly.layers:
                if layer.unit is None:
                    continue
                aliases_by_unit_mutable[layer.unit.candidate.id].append(
                    UnitAlias(
                        session_shape=shape,
                        capability_breadcrumb=breadcrumb,
                        assembly=assembly,
                        layer=layer,
                    )
                )

        concern_views: list[ConcernView] = []
        concerns: dict[str, ConcernView] = {}
        concerns_by_unit_mutable: defaultdict[str, list[ConcernView]] = defaultdict(list)
        concern_relatives_mutable: defaultdict[str, list[ConcernRelative]] = defaultdict(list)
        for concern in catalog.graph.concerns:
            members = [
                ConcernMember(
                    unit=_required(units, concern.canonical_unit, f"concern {concern.id}"),
                    relation=None,
                    canonical=True,
                )
            ]
            members.extend(
                ConcernMember(
                    unit=_required(units, related.unit, f"concern {concern.id}"),
                    relation=related.relation,
                    canonical=False,
                )
                for related in concern.related
            )
            view = ConcernView(concern=concern, members=tuple(members))
            concern_views.append(view)
            concerns[concern.id] = view
            for selected in view.members:
                unit_id = selected.unit.candidate.id
                concerns_by_unit_mutable[unit_id].append(view)
                concern_relatives_mutable[unit_id].extend(
                    ConcernRelative(concern=concern, member=member)
                    for member in view.members
                    if member.unit.candidate.id != unit_id
                )

        lineage_views: list[LineageView] = []
        lineage: dict[str, LineageView] = {}
        lineage_by_unit_mutable: defaultdict[str, list[LineageView]] = defaultdict(list)
        for rule in catalog.graph.lineage:
            sources = tuple(
                unit for unit in catalog.units if fnmatchcase(unit.candidate.id, rule.source)
            )
            view = LineageView(lineage=rule, sources=sources)
            lineage_views.append(view)
            lineage[rule.id] = view
            for unit in sources:
                lineage_by_unit_mutable[unit.candidate.id].append(view)

        def capability_node(capability: Capability) -> CapabilityNode:
            return CapabilityNode(
                capability=capability,
                breadcrumb=_required(breadcrumbs, capability.id, "capability tree"),
                units=units_by_capability.get(capability.id, ()),
                session_shapes=shapes_by_capability.get(capability.id, ()),
                children=tuple(
                    capability_node(child) for child in capability_children.get(capability.id, ())
                ),
            )

        indexes = _SnapshotIndexes(
            capabilities=capabilities,
            capability_children=capability_children,
            capability_breadcrumbs=breadcrumbs,
            units=_freeze(units),
            units_by_capability=units_by_capability,
            fragments=_freeze(fragments_by_id),
            fragments_by_unit=_freeze_groups(fragments_by_unit_mutable),
            session_shapes=_freeze(session_shapes),
            shapes_by_capability=shapes_by_capability,
            delivery_siblings=_freeze(delivery_siblings),
            assemblies=_freeze(assemblies),
            scenarios=_freeze(scenarios),
            scenarios_by_assembly=scenarios_by_assembly,
            consumers_by_unit=_freeze_groups(consumers_by_unit_mutable),
            aliases_by_unit=_freeze_groups(aliases_by_unit_mutable),
            concerns=_freeze(concerns),
            concerns_by_unit=_freeze_groups(concerns_by_unit_mutable),
            concern_relatives=_freeze_groups(concern_relatives_mutable),
            lineage=_freeze(lineage),
            lineage_by_unit=_freeze_groups(lineage_by_unit_mutable),
        )
        return cls(
            capability_tree=tuple(capability_node(root) for root in roots),
            units=catalog.units,
            fragments=tuple(fragments),
            session_shapes=catalog.graph.session_shapes,
            assemblies=tuple(assembly_views),
            scenarios=catalog.graph.scenarios,
            concerns=tuple(concern_views),
            lineage=tuple(lineage_views),
            _indexes=indexes,
        )

    def get_capability(self, capability_id: str) -> Capability | None:
        return self._indexes.capabilities.get(capability_id)

    def capability_parent(self, capability_id: str) -> Capability | None:
        capability = self.get_capability(capability_id)
        if capability is None or capability.parent is None:
            return None
        return self.get_capability(capability.parent)

    def capability_children(self, capability_id: str) -> tuple[Capability, ...]:
        return self._indexes.capability_children.get(capability_id, ())

    def capability_breadcrumb(self, capability_id: str) -> tuple[Capability, ...]:
        return self._indexes.capability_breadcrumbs.get(capability_id, ())

    def units_for_capability(self, capability_id: str) -> tuple[RoutedUnit, ...]:
        return self._indexes.units_by_capability.get(capability_id, ())

    def units_for_path(self, path: str) -> tuple[RoutedUnit, ...]:
        """Return mapped units for ``path`` in catalog order."""
        return tuple(unit for unit in self.units if unit.candidate.path == path)

    def get_unit(self, unit_id: str) -> RoutedUnit | None:
        return self._indexes.units.get(unit_id)

    def fragments_for_unit(self, unit_id: str) -> tuple[RoutedFragment, ...]:
        return self._indexes.fragments_by_unit.get(unit_id, ())

    def get_fragment(self, unit_id: str, fragment_id: str) -> RoutedFragment | None:
        return self._indexes.fragments.get((unit_id, fragment_id))

    def get_session_shape(self, shape_id: str) -> SessionShape | None:
        return self._indexes.session_shapes.get(shape_id)

    def session_shapes_for_capability(self, capability_id: str) -> tuple[SessionShape, ...]:
        return self._indexes.shapes_by_capability.get(capability_id, ())

    def delivery_siblings(self, shape_id: str) -> tuple[SessionShape, ...]:
        """Return variants sharing the selected shape's capability and assembly."""
        return self._indexes.delivery_siblings.get(shape_id, ())

    def get_assembly(self, assembly_id: str) -> AssemblyView | None:
        return self._indexes.assemblies.get(assembly_id)

    def get_scenario(self, scenario_id: str) -> Scenario | None:
        return self._indexes.scenarios.get(scenario_id)

    def scenarios_for_assembly(self, assembly_id: str) -> tuple[Scenario, ...]:
        return self._indexes.scenarios_by_assembly.get(assembly_id, ())

    def consumers_for_unit(self, unit_id: str) -> tuple[AssemblyConsumer, ...]:
        """Return canonical assembly-layer references without shape expansion."""
        return self._indexes.consumers_by_unit.get(unit_id, ())

    def aliases_for_unit(self, unit_id: str) -> tuple[UnitAlias, ...]:
        """Return one tree alias per consuming session shape and assembly layer."""
        return self._indexes.aliases_by_unit.get(unit_id, ())

    def get_concern(self, concern_id: str) -> ConcernView | None:
        return self._indexes.concerns.get(concern_id)

    def concerns_for_unit(self, unit_id: str) -> tuple[ConcernView, ...]:
        return self._indexes.concerns_by_unit.get(unit_id, ())

    def concern_relatives(self, unit_id: str) -> tuple[ConcernRelative, ...]:
        return self._indexes.concern_relatives.get(unit_id, ())

    def get_lineage(self, lineage_id: str) -> LineageView | None:
        return self._indexes.lineage.get(lineage_id)

    def lineage_for_unit(self, unit_id: str) -> tuple[LineageView, ...]:
        return self._indexes.lineage_by_unit.get(unit_id, ())


def load_catalog(root: Path) -> CatalogSnapshot:
    """Discover and build once, then serve every query from immutable memory."""
    return CatalogSnapshot.from_catalog(build_catalog(root))
