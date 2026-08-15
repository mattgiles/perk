"""Server-side catalog search: a query-independent index over the immutable snapshot.

The searched corpus is closed (PRD §4 exactly): capability labels, shape labels,
unit ids, source paths, fragment labels, tool names, and concern labels. The index is
built once per app over the immutable :class:`CatalogSnapshot`; query-dependent match
metadata lives on :class:`SearchHit`, never on the index type. Result order is index
order — deterministic, no relevance ranking.
"""

from dataclasses import dataclass
from typing import Literal

from perk_dev.prose_map.models import Audience, Capability, ProseKind, ProseRole, RoutedUnit
from perk_dev.prose_review.catalog import CapabilityNode, CatalogSnapshot

type SearchEntryKind = Literal["capability", "session-shape", "unit", "fragment", "concern"]
type MatchField = Literal[
    "capability-label",
    "shape-label",
    "unit-id",
    "source-path",
    "tool-name",
    "fragment-label",
    "concern-label",
]

_TOOL_PREFIX = "typescript-tool:"

# Uniform cap on served hits; `total` always reports the full match count.
_HIT_CAP = 100


@dataclass(frozen=True, slots=True)
class SearchEntry:
    """One searchable entity with its query-independent searched fields."""

    kind: SearchEntryKind
    entity_id: str
    label: str
    fields: tuple[tuple[MatchField, str], ...]
    breadcrumb: tuple[Capability, ...]
    unit: RoutedUnit | None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One matching entry plus its matched field names (in the entry's field order).

    ``matched`` is ``()`` for a filter-only browse: an empty trimmed query matches no
    field, it matches the entry as a whole.
    """

    entry: SearchEntry
    matched: tuple[MatchField, ...]


@dataclass(frozen=True, slots=True)
class SearchResults:
    """The full match count plus the capped hits, in index order."""

    total: int
    hits: tuple[SearchHit, ...]


def _capability_entries(snapshot: CatalogSnapshot) -> list[SearchEntry]:
    entries: list[SearchEntry] = []

    def visit(node: CapabilityNode) -> None:
        capability = node.capability
        entries.append(
            SearchEntry(
                kind="capability",
                entity_id=capability.id,
                label=capability.label,
                fields=(("capability-label", capability.label),),
                breadcrumb=node.breadcrumb,
                unit=None,
            )
        )
        for child in node.children:
            visit(child)

    for root in snapshot.capability_tree:
        visit(root)
    return entries


def build_search_index(snapshot: CatalogSnapshot) -> tuple[SearchEntry, ...]:
    """Build the fixed-order index: capability → session-shape → unit → fragment → concern."""
    entries = _capability_entries(snapshot)
    for shape in snapshot.session_shapes:
        entries.append(
            SearchEntry(
                kind="session-shape",
                entity_id=shape.id,
                label=shape.label,
                fields=(("shape-label", shape.label),),
                breadcrumb=snapshot.capability_breadcrumb(shape.capability),
                unit=None,
            )
        )
    for unit in snapshot.units:
        candidate = unit.candidate
        fields: list[tuple[MatchField, str]] = [
            ("unit-id", candidate.id),
            ("source-path", candidate.path),
        ]
        if candidate.kind == "typescript-tool":
            fields.append(("tool-name", candidate.id.removeprefix(_TOOL_PREFIX)))
        entries.append(
            SearchEntry(
                kind="unit",
                # A unit's display label is its id: Candidate has no separate label.
                entity_id=candidate.id,
                label=candidate.id,
                fields=tuple(fields),
                breadcrumb=snapshot.capability_breadcrumb(unit.capability),
                unit=unit,
            )
        )
    for routed in snapshot.fragments:
        entries.append(
            SearchEntry(
                kind="fragment",
                entity_id=routed.fragment.id,
                label=routed.fragment.label,
                fields=(("fragment-label", routed.fragment.label),),
                breadcrumb=snapshot.capability_breadcrumb(routed.unit.capability),
                unit=routed.unit,
            )
        )
    for view in snapshot.concerns:
        canonical = view.members[0].unit
        entries.append(
            SearchEntry(
                kind="concern",
                entity_id=view.concern.id,
                label=view.concern.label,
                fields=(("concern-label", view.concern.label),),
                breadcrumb=snapshot.capability_breadcrumb(canonical.capability),
                unit=canonical,
            )
        )
    return tuple(entries)


def _passes_filters(
    entry: SearchEntry,
    *,
    audience: Audience | None,
    role: ProseRole | None,
    kind: ProseKind | None,
) -> bool:
    if audience is None and role is None and kind is None:
        return True
    # Filters are unit-attribute filters: only unit and fragment entries carry the
    # filtered attributes (a fragment inherits its owning unit's). Capability, shape,
    # and concern entries have no audience/role/kind — pretending otherwise would be
    # a hidden semantic, so an active filter excludes them outright.
    if entry.kind not in ("unit", "fragment") or entry.unit is None:
        return False
    unit = entry.unit
    # Exact authored-value equality: "shipped" does not fold in "both".
    if audience is not None and unit.audience != audience:
        return False
    if role is not None and unit.role != role:
        return False
    return not (kind is not None and unit.candidate.kind != kind)


def search(
    index: tuple[SearchEntry, ...],
    query: str,
    *,
    audience: Audience | None = None,
    role: ProseRole | None = None,
    kind: ProseKind | None = None,
) -> SearchResults:
    """Case-insensitive substring search over the index, filtered then capped."""
    needle = query.strip().lower()
    hits: list[SearchHit] = []
    total = 0
    for entry in index:
        if not _passes_filters(entry, audience=audience, role=role, kind=kind):
            continue
        if needle:
            matched = tuple(name for name, value in entry.fields if needle in value.lower())
            if not matched:
                continue
        else:
            matched = ()
        total += 1
        if len(hits) < _HIT_CAP:
            hits.append(SearchHit(entry=entry, matched=matched))
    return SearchResults(total=total, hits=tuple(hits))
