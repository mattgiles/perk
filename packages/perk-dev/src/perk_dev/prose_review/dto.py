"""The Prose Review Workbench serialization edge: catalog snapshot → wire DTOs.

The HTTP layer never touches domain objects — every response body is an
``OutputModel`` built here via ``from_domain``. Declaration order is the JSON key
order, so the field order below is deliberate.
"""

from typing import Self

from perk.boundary import OutputModel
from perk_dev.prose_map.models import Capability
from perk_dev.prose_review.catalog import CatalogSnapshot


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
