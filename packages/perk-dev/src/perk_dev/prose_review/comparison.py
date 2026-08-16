"""Pure whole-unit comparison projection over an immutable catalog snapshot."""

from dataclasses import dataclass
from typing import Literal

from perk_dev.prose_map.models import Capability, RoutedUnit, SessionShape
from perk_dev.prose_review.catalog import AssemblyLayerView, AssemblyView, CatalogSnapshot

type ComparisonRelation = Literal[
    "delivery-sibling",
    "adjacent-layer",
    "alias-consumer",
    "concern-relative",
    "capability-parent-child",
]
type PlacementLocator = tuple[str, str | None, str | None, int | None]
type AdjacentDirection = Literal["previous", "next"]

_GROUP_LABELS: dict[ComparisonRelation, str] = {
    "delivery-sibling": "Delivery siblings",
    "adjacent-layer": "Adjacent assembly layers",
    "alias-consumer": "Alias consumers",
    "concern-relative": "Concern relatives",
    "capability-parent-child": "Capability parent / child",
}


@dataclass(frozen=True, slots=True)
class ComparisonPlacement:
    """One canonical source identity in canonical or assembly placement context."""

    unit: RoutedUnit
    breadcrumb: tuple[Capability, ...]
    shape: SessionShape | None
    assembly: str | None
    position: int | None
    label: str

    def __post_init__(self) -> None:
        if not self.breadcrumb or not self.label.strip():
            raise ValueError("comparison placements require a breadcrumb and label")
        canonical = self.shape is None and self.assembly is None and self.position is None
        assembly_placement = (
            self.assembly is not None and self.position is not None and self.position > 0
        )
        if not canonical and not assembly_placement:
            raise ValueError("incoherent comparison placement")

    def locator(self) -> PlacementLocator:
        return (
            self.unit.candidate.id,
            None if self.shape is None else self.shape.id,
            self.assembly,
            self.position,
        )


@dataclass(frozen=True, slots=True)
class ComparisonChoice:
    """One server-authored comparison target and its explanatory copy."""

    label: str
    detail: str
    target: ComparisonPlacement

    def __post_init__(self) -> None:
        if not self.label.strip() or not self.detail.strip():
            raise ValueError("comparison choices require labels and details")


@dataclass(frozen=True, slots=True)
class ComparisonGroup:
    """A non-empty, ordered family of comparison choices."""

    relation: ComparisonRelation
    label: str
    choices: tuple[ComparisonChoice, ...]

    def __post_init__(self) -> None:
        if not self.label.strip() or not self.choices:
            raise ValueError("comparison groups require a label and choices")


@dataclass(frozen=True, slots=True)
class ComparisonOptions:
    """The resolved origin and every graph-backed whole-unit comparison choice."""

    origin: ComparisonPlacement
    groups: tuple[ComparisonGroup, ...]


def _layer_label(layer: AssemblyLayerView) -> str:
    if layer.layer.label is not None and layer.layer.label.strip():
        return layer.layer.label
    if layer.unit is None:
        raise ValueError("a boundary has no comparison placement label")
    return layer.unit.candidate.id


def _canonical_placement(snapshot: CatalogSnapshot, unit: RoutedUnit) -> ComparisonPlacement:
    return ComparisonPlacement(
        unit=unit,
        breadcrumb=snapshot.capability_breadcrumb(unit.capability),
        shape=None,
        assembly=None,
        position=None,
        label=unit.candidate.id,
    )


def _assembly_placement(
    snapshot: CatalogSnapshot,
    assembly: AssemblyView,
    layer: AssemblyLayerView,
    shape: SessionShape | None,
) -> ComparisonPlacement:
    if layer.unit is None:
        raise ValueError("a boundary is not a comparison placement")
    return ComparisonPlacement(
        unit=layer.unit,
        breadcrumb=snapshot.capability_breadcrumb(
            layer.unit.capability if shape is None else shape.capability
        ),
        shape=shape,
        assembly=assembly.assembly.id,
        position=layer.position,
        label=_layer_label(layer),
    )


def _placement_description(placement: ComparisonPlacement) -> str:
    if placement.shape is not None:
        return (
            f"{placement.shape.label} · {placement.assembly} #{placement.position} · "
            f"{placement.label}"
        )
    if placement.assembly is not None:
        return f"{placement.assembly} #{placement.position} · {placement.label}"
    return placement.unit.candidate.id


def _anchors_for_unit(snapshot: CatalogSnapshot, unit_id: str) -> tuple[ComparisonPlacement, ...]:
    aliases = snapshot.aliases_for_unit(unit_id)
    anchors: list[ComparisonPlacement] = []
    for consumer in snapshot.consumers_for_unit(unit_id):
        matching_aliases = tuple(
            alias
            for alias in aliases
            if alias.assembly.assembly.id == consumer.assembly.assembly.id
            and alias.layer.position == consumer.layer.position
        )
        if matching_aliases:
            anchors.extend(
                _assembly_placement(
                    snapshot,
                    alias.assembly,
                    alias.layer,
                    alias.session_shape,
                )
                for alias in matching_aliases
            )
        else:
            anchors.append(_assembly_placement(snapshot, consumer.assembly, consumer.layer, None))
    return tuple(anchors)


def _group(relation: ComparisonRelation, choices: list[ComparisonChoice]) -> ComparisonGroup | None:
    if not choices:
        return None
    return ComparisonGroup(
        relation=relation,
        label=_GROUP_LABELS[relation],
        choices=tuple(choices),
    )


def _delivery_choices(
    snapshot: CatalogSnapshot, anchors: tuple[ComparisonPlacement, ...]
) -> list[ComparisonChoice]:
    choices: list[ComparisonChoice] = []
    seen: set[PlacementLocator] = set()
    for anchor in anchors:
        if anchor.shape is None or anchor.position is None:
            continue
        for sibling in snapshot.delivery_siblings(anchor.shape.id):
            assembly = snapshot.get_assembly(sibling.assembly)
            if assembly is None or anchor.position > len(assembly.layers):
                continue
            layer = assembly.layers[anchor.position - 1]
            if layer.unit is None:
                continue
            target = _assembly_placement(snapshot, assembly, layer, sibling)
            if target.locator() in seen:
                continue
            seen.add(target.locator())
            choices.append(
                ComparisonChoice(
                    label=sibling.label,
                    detail=f"{target.assembly} #{target.position} · {target.label}",
                    target=target,
                )
            )
    return choices


def _adjacent_choices(
    snapshot: CatalogSnapshot, anchors: tuple[ComparisonPlacement, ...]
) -> list[ComparisonChoice]:
    choices: list[ComparisonChoice] = []
    seen: set[tuple[PlacementLocator, AdjacentDirection, PlacementLocator]] = set()
    for origin in anchors:
        if origin.assembly is None or origin.position is None:
            continue
        assembly = snapshot.get_assembly(origin.assembly)
        if assembly is None:
            continue
        neighbors: tuple[tuple[AdjacentDirection, int, str], ...] = (
            ("previous", origin.position - 1, "Previous layer"),
            ("next", origin.position + 1, "Next layer"),
        )
        for direction, position, prefix in neighbors:
            if position < 1 or position > len(assembly.layers):
                continue
            layer = assembly.layers[position - 1]
            if layer.unit is None:
                continue
            target = _assembly_placement(snapshot, assembly, layer, origin.shape)
            key = (origin.locator(), direction, target.locator())
            if key in seen:
                continue
            seen.add(key)
            choices.append(
                ComparisonChoice(
                    label=f"{prefix} · {target.label}",
                    detail=(
                        f"From {_placement_description(origin)} to {_placement_description(target)}"
                    ),
                    target=target,
                )
            )
    return choices


def _alias_choices(
    snapshot: CatalogSnapshot,
    unit_id: str,
    origin: ComparisonPlacement,
) -> list[ComparisonChoice]:
    choices: list[ComparisonChoice] = []
    seen: set[PlacementLocator] = set()
    for target in _anchors_for_unit(snapshot, unit_id):
        locator = target.locator()
        if locator == origin.locator() or locator in seen:
            continue
        seen.add(locator)
        choices.append(
            ComparisonChoice(
                label=target.label,
                detail=_placement_description(target),
                target=target,
            )
        )
    return choices


def _concern_choices(snapshot: CatalogSnapshot, unit_id: str) -> list[ComparisonChoice]:
    choices: list[ComparisonChoice] = []
    seen: set[tuple[str, str]] = set()
    for relative in snapshot.concern_relatives(unit_id):
        target_id = relative.member.unit.candidate.id
        key = (relative.concern.id, target_id)
        if key in seen:
            continue
        seen.add(key)
        if relative.member.canonical:
            standing = "canonical"
        elif relative.member.relation is not None and relative.member.relation.strip():
            standing = relative.member.relation
        else:
            standing = "related"
        choices.append(
            ComparisonChoice(
                label=target_id,
                detail=f"{relative.concern.label} · {standing}",
                target=_canonical_placement(snapshot, relative.member.unit),
            )
        )
    return choices


def _capability_subtree_units(
    snapshot: CatalogSnapshot, capability: Capability
) -> tuple[RoutedUnit, ...]:
    units = list(snapshot.units_for_capability(capability.id))
    for child in snapshot.capability_children(capability.id):
        units.extend(_capability_subtree_units(snapshot, child))
    return tuple(units)


def _capability_choices(
    snapshot: CatalogSnapshot, origin_unit: RoutedUnit
) -> list[ComparisonChoice]:
    choices: list[ComparisonChoice] = []
    seen: set[tuple[str, str, str]] = set()
    anchors: list[tuple[Literal["parent", "child"], Capability]] = []
    parent = snapshot.capability_parent(origin_unit.capability)
    if parent is not None:
        anchors.append(("parent", parent))
    anchors.extend(
        ("child", child) for child in snapshot.capability_children(origin_unit.capability)
    )
    for relationship, capability in anchors:
        for target_unit in _capability_subtree_units(snapshot, capability):
            target_id = target_unit.candidate.id
            if target_id == origin_unit.candidate.id:
                continue
            key = (relationship, capability.id, target_id)
            if key in seen:
                continue
            seen.add(key)
            prefix = "Parent capability" if relationship == "parent" else "Child capability"
            choices.append(
                ComparisonChoice(
                    label=target_id,
                    detail=f"{prefix} · {capability.label}",
                    target=_canonical_placement(snapshot, target_unit),
                )
            )
    return choices


def comparison_options(
    snapshot: CatalogSnapshot,
    unit_id: str,
    *,
    shape_id: str | None = None,
    position: int | None = None,
) -> ComparisonOptions | None:
    """Resolve one coherent subject and project its graph-backed comparison choices."""
    unit = snapshot.get_unit(unit_id)
    if unit is None or (shape_id is None) != (position is None):
        return None

    if shape_id is None:
        origin = _canonical_placement(snapshot, unit)
        anchors = _anchors_for_unit(snapshot, unit_id)
    else:
        if position is None or position < 1:
            return None
        shape = snapshot.get_session_shape(shape_id)
        if shape is None:
            return None
        assembly = snapshot.get_assembly(shape.assembly)
        if assembly is None or position > len(assembly.layers):
            return None
        layer = assembly.layers[position - 1]
        if layer.unit is None or layer.unit.candidate.id != unit_id:
            return None
        origin = _assembly_placement(snapshot, assembly, layer, shape)
        anchors = (origin,)

    groups: list[ComparisonGroup] = []
    candidates: tuple[tuple[ComparisonRelation, list[ComparisonChoice]], ...] = (
        ("delivery-sibling", _delivery_choices(snapshot, anchors)),
        ("adjacent-layer", _adjacent_choices(snapshot, anchors)),
        ("alias-consumer", _alias_choices(snapshot, unit_id, origin)),
        ("concern-relative", _concern_choices(snapshot, unit_id)),
        ("capability-parent-child", _capability_choices(snapshot, unit)),
    )
    for relation, choices in candidates:
        group = _group(relation, choices)
        if group is not None:
            groups.append(group)
    return ComparisonOptions(origin=origin, groups=tuple(groups))
