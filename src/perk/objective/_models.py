"""Objective data leaf — module constants + markers, status enum/sets, the core dataclasses,
and the marker helpers.

The type leaf of the ``perk/objective/`` package (no intra-package imports; mirrors the
``doctor`` package's ``data.py`` leaf precedent). Holds the storage-block keys/markers, the
:class:`NodeStatus` enum + its category sets, the :class:`DeliveryPolicy` enum + the
delivery-train bounds, the :class:`ObjectiveNode` / :class:`ObjectiveHeader` /
:class:`PlanSelection` / :class:`DependencyGraph` dataclasses, and the dual-encoding marker
helpers (``_inline_marker`` / ``_find_marker_pair`` / ``_has_block``).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field

from perk.boundary import LenientParseModel, StrictInputModel, StrTuple
from perk.plan import has_metadata_block

OBJECTIVE_LABEL = "perk:objective"
OBJECTIVE_LABEL_COLOR = "5319e7"  # indigo (distinct from plan green / learn purple)
OBJECTIVE_LABEL_DESCRIPTION = "perk objective issue"

# The roadmap node-issue label (project-backed Linear store): node-issues are discovered by
# project membership + the `objective-node` block, but the label makes them human-filterable in
# Linear (additive; never load-bearing for discovery).
OBJECTIVE_NODE_LABEL = "perk:objective-node"
OBJECTIVE_NODE_LABEL_COLOR = "5319e7"  # indigo, matching the objective label
OBJECTIVE_NODE_LABEL_DESCRIPTION = "A perk objective roadmap node (managed by perk)."

OBJECTIVE_HEADER_KEY = "objective-header"
OBJECTIVE_ROADMAP_KEY = "objective-roadmap"
# The project-overview drift baseline: an authoritative manifest of the intended
# roadmap's STRUCTURAL identity (id/slug/description/depends_on per node + a pinned phase-name map),
# persisted beside `objective-header`. Status/pr are deliberately excluded — they are live/observed
# state, never part of the manifest, which is what makes recreation safe (it copies a persisted
# fact, never invents live state). Only the project-backed Linear store carries a divergence
# surface; GitHub's roadmap block is its own atomic manifest (its drift report is trivially empty).
OBJECTIVE_MANIFEST_KEY = "objective-manifest"
OBJECTIVE_BODY_KEY = "objective-body"
# The per-node-issue metadata block key (project-backed store): each node-issue carries an
# `objective-node` block (the node's id/status/description) so a project-backed objective derives
# its roadmap live from node-issue membership, not from a stored roadmap table.
OBJECTIVE_NODE_KEY = "objective-node"

# perk starts its OWN objective schema at 1.
OBJECTIVE_SCHEMA_VERSION = "1"

# The strict authoring bounds on a stacked delivery train's NON-SKIPPED nodes
# (contracts.md §8.42). A one-node stacked objective is rejected at authoring — save it as a
# standalone plan instead; a train may later shrink below the minimum via skips (the dynamic
# singleton), which is a lifecycle fact, not an authoring shape.
DELIVERY_TRAIN_MIN_LAYERS = 2
DELIVERY_TRAIN_MAX_LAYERS = 100

# The valid `objective-header` field names (LBYL on the staged-population schema, mirroring
# plan.PLAN_HEADER_FIELDS). `status` is the objective-level rollup, stored explicitly.
OBJECTIVE_HEADER_FIELDS = frozenset(
    {
        "run_id",
        "created",
        "objective_comment_id",
        "status",
        "base",
        "adopted_from",
        "supersedes",
        "superseded_by",
        # Stacked-delivery policy + train identity (contracts.md §8.42): rendered only when set
        # (fresh incremental objectives stay byte-identical); merge-writable on all stores.
        "delivery",
        "delivery_lineage",
    }
)

# The human-readable rendered-table markers spliced into the `objective-body` comment.
ROADMAP_TABLE_MARKER_START = "<!-- perk:roadmap-table -->"
ROADMAP_TABLE_MARKER_END = "<!-- /perk:roadmap-table -->"

# The Reconcilable-prose markers. The objective-body comment is three section types:
# Mechanical (the marker-bounded roadmap table, re-rendered from frontmatter), Reconcilable (the
# prose inside THESE markers — the only region post-merge reconciliation rewrites), and Immutable
# (anything below the closing marker — historical notes, never touched). The Reconcilable region is
# structurally Immutable-safe: `replace_reconcilable_section` can only rewrite between the markers.
OBJECTIVE_RECONCILABLE_MARKER_START = "<!-- perk:objective-reconcilable -->"
OBJECTIVE_RECONCILABLE_MARKER_END = "<!-- /perk:objective-reconcilable -->"

# The Linear-safe inline-code rewrite of a perk HTML-comment marker.
# Derived locally by the same rule as the Linear backend's `to_linear_markdown` transcoder
# (`<!-- perk:x -->` → `` `perk:x` ``) — NOT imported from it: the import direction is
# `backends.linear → objective`, never back.
_INLINE_MARKER_RE = re.compile(r"^<!--\s*(/?perk:.+?)\s*-->$")


def _inline_marker(html_marker: str) -> str:
    match = _INLINE_MARKER_RE.match(html_marker)
    if match is None:  # pragma: no cover - module-constant inputs only
        raise ValueError(f"not a perk HTML-comment marker: {html_marker!r}")
    return f"`{match.group(1)}`"


def _find_marker_pair(
    text: str, start_marker: str, end_marker: str
) -> tuple[int, int, str, str] | None:
    """Locate a marker-bounded region in either encoding (form-preservation).

    ``start_marker``/``end_marker`` are the canonical HTML forms; the HTML scan runs first (the
    unchanged GitHub path), then the Linear-safe inline-code forms derived by the same rewrite
    rule as ``to_linear_markdown``. Returns ``(start, end, found_start, found_end)`` — the index
    of the open marker, the index of the close marker, and the **concrete marker strings found**
    (so callers re-emit whichever form was present) — or ``None`` when absent/unclosed.
    """
    for open_form, close_form in (
        (start_marker, end_marker),
        (_inline_marker(start_marker), _inline_marker(end_marker)),
    ):
        start = text.find(open_form)
        if start == -1:
            continue
        end = text.find(close_form, start)
        if end == -1:
            return None
        return start, end, open_form, close_form
    return None


class DeliveryPolicy(StrEnum):
    """An objective's delivery policy (contracts.md §8.42).

    Storage rule: **absence** of the objective-header ``delivery`` field ⇒ incremental; the only
    value ever serialized is the literal ``"stacked"``. ``"incremental"`` is tolerated on read
    (see :func:`perk.objective.parse.delivery_policy`) but never written.
    """

    INCREMENTAL = "incremental"
    STACKED = "stacked"


class NodeStatus(StrEnum):
    """A roadmap node's explicit status (open #3: never inferred from a PR column)."""

    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


# The terminal statuses (a dependency is "satisfied" only when terminal).
TERMINAL: frozenset[NodeStatus] = frozenset({NodeStatus.DONE, NodeStatus.SKIPPED})

# Lifecycle categories for factory selection (the resumable-lease model). `planning` is a
# resumable CLAIM (re-selectable until a plan is committed); `in_progress` is a COMMITTED plan (a
# plan was saved and the node↔plan backlink set atomically by `plan-save`). A `planning` node IS
# plannable, but only while it carries no `pr` backlink (see `plannable_nodes`) — and implicit
# selection takes it only as a FALLBACK when no unblocked `pending` node exists (a claim may be
# live in another session; see `next_plannable`).
PLANNABLE: frozenset[NodeStatus] = frozenset({NodeStatus.PENDING, NodeStatus.PLANNING})
IN_FLIGHT: frozenset[NodeStatus] = frozenset({NodeStatus.PLANNING, NodeStatus.IN_PROGRESS})

_VALID_STATUS_VALUES = frozenset(s.value for s in NodeStatus)


class ObjectiveNodeEntry(LenientParseModel):
    """Tolerant parse shape for one stored/structured roadmap node.

    Lenient base: unknown keys dropped (extra="ignore", replacing the old `_tolerate`
    sibling-key collapse — e.g. the structured-roadmap `adopt_issue` key, consumed separately
    by parse_adopt_mapping); `status` value-looks-up the NodeStatus StrEnum natively; a
    `depends_on` YAML list coerces to a tuple natively. Required id/description/status; absent
    optionals default to None.
    """

    id: str
    description: str
    status: NodeStatus
    pr: str | None = None
    depends_on: tuple[str, ...] | None = None
    slug: str | None = None
    comment: str | None = None

    def to_domain(self) -> "ObjectiveNode":
        return ObjectiveNode(
            id=self.id,
            description=self.description,
            status=self.status,
            pr=self.pr,
            depends_on=self.depends_on,
            slug=self.slug,
            comment=self.comment,
        )


class StructuredRoadmapNode(StrictInputModel):
    """Strict machine-input shape for one ``objective create --roadmap`` / ``objective_save`` node.

    Mirrors the TS ``ROADMAP_PARAM_SCHEMA`` (``additionalProperties: false``): unknown keys fail
    loudly. ``status`` and ``depends_on`` are the only intentionally-coercing fields under the
    otherwise-strict model (a raw enum value / a list of strings).
    """

    id: str
    description: str
    # value-based StrEnum lookup must stay permissive under the otherwise-strict model.
    status: NodeStatus = Field(default=NodeStatus.PENDING, strict=False)
    slug: str | None = None
    pr: str | None = None
    depends_on: StrTuple | None = None  # named list->tuple coercion allowlist
    comment: str | None = None
    # Declared so extra="forbid" does NOT reject it; dropped here and read separately by
    # parse_adopt_mapping (kept off the pristine ObjectiveNode).
    adopt_issue: str | None = None

    def to_domain(self) -> "ObjectiveNode":
        return ObjectiveNode(
            id=self.id,
            description=self.description,
            status=self.status,
            pr=self.pr,
            depends_on=self.depends_on,
            slug=self.slug,
            comment=self.comment,
        )


@dataclass(frozen=True)
class ObjectiveNode:
    """A single node in an objective roadmap.

    ``depends_on`` is ``None`` (unspecified → infer sequential deps) vs ``()`` (explicitly no
    deps). ``pr`` is ``None`` or ``"#456"``. ``slug``/``comment`` are optional.
    """

    id: str
    description: str
    status: NodeStatus
    pr: str | None = None
    depends_on: tuple[str, ...] | None = None
    slug: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class ObjectiveHeader:
    """Compact, queryable objective metadata stored in the issue *body* (the
    ``objective-header`` block). ``status`` is the objective-level rollup, stored explicitly
    (never inferred from PR state). ``objective_comment_id`` is backfilled in the two-step
    create (it is unknown until the body comment is posted).

    Field DECLARATION ORDER is load-bearing for serialization: ``render_header_block`` emits the
    8 base keys in this order (nulls included) to keep the stored ``objective-header`` block
    byte-identical, and appends the conditional delivery pair (``delivery`` /
    ``delivery_lineage``) **only when set** — absence preserves the existing storage shape
    (contracts.md §8.42)."""

    run_id: str
    created: str  # ISO-8601 UTC (see plan.now_iso)
    # Backend-owned opaque value: GitHub stores its numeric comment id, Linear its string UUID.
    objective_comment_id: int | str | None = None
    status: str = "active"
    # The objective's target branch; inherited by every node plan. `None` ⇒ no override
    # (node plans fall through to `[workflow] base` → the GitHub default branch).
    base: str | None = None
    # In-place objective adoption (§8.30): the source ref this objective was adopted from
    # (a Linear project UUID — projects have no human identifier — or a GitHub issue ref `"#<n>"`).
    # Self-referential by construction (adoption stamps perk's metadata INTO the same source); its
    # **presence** is the canonical "this objective was adopted; the `Adopted-from` Immutable note
    # holds the original human content" signal. `None` for a normally-authored objective.
    adopted_from: str | None = None
    # Objective re-authoring lineage (the supersede model): `supersedes` on a NEW objective points
    # back at the OLD objective it re-authored and closed; `superseded_by` is stamped onto the OLD
    # objective pointing forward at its successor. A GitHub ref (`"#<n>"`) or a Linear project UUID,
    # opaque at this tier. Both `None` for a normally-authored objective. Bidirectional by
    # construction (create-new-first, close-old-last, fail-open on the close).
    supersedes: str | None = None
    superseded_by: str | None = None
    # The objective delivery policy (contracts.md §8.42). `None` ⇒ incremental (never stored);
    # the only stored value is `"stacked"` (typed `str` like `status`, with `DeliveryPolicy` as
    # the domain vocabulary).
    delivery: str | None = None
    # The stable delivery-train identity across superseding objectives (a ULID string; minted at
    # stacked authoring, copied by replan). Present iff the lineage exists (stacked only).
    delivery_lineage: str | None = None


def _has_block(text: str, key: str) -> bool:
    # Dual-encoding presence check (HTML or inline-code) — a Linear-stored roadmap block must
    # discriminate absent (valid roadmap-free) from present-but-malformed, same as GitHub's.
    return has_metadata_block(text, key)


# The Immutable archive-note marker (§8.30): the source's ORIGINAL overview/body, preserved
# verbatim below the closing Reconcilable marker (Immutable by construction). A perk HTML-comment
# marker so it round-trips through `to_linear_markdown` (→ inline-code) on the Linear path and is
# recognizable/idempotent.
ADOPTED_OVERVIEW_MARKER = "<!-- perk:adopted-original (verbatim — do not edit) -->"


@dataclass(frozen=True)
class PlanSelection:
    """The classified planning state of an objective (drives the factory's honest reporting).

    ``kind`` is one of ``"plannable"`` (a resumable node is ready), ``"in_flight"`` (a plan is in
    flight — implement it, don't re-plan), ``"blocked"`` (every remaining node is blocked by an
    unfinished dependency), or ``"complete"`` (every node is terminal). ``node`` is the relevant
    node for ``plannable``/``in_flight``, else ``None``.
    """

    kind: str
    node: ObjectiveNode | None


@dataclass(frozen=True)
class DependencyGraph:
    """A DAG of objective nodes with resolved (never-``None``) dependency edges."""

    nodes: tuple[ObjectiveNode, ...]

    def _node_map(self) -> dict[str, ObjectiveNode]:
        return {node.id: node for node in self.nodes}

    def unblocked_nodes(self) -> list[ObjectiveNode]:
        """Nodes whose dependencies are all terminal (``done``/``skipped``)."""
        node_map = self._node_map()
        result: list[ObjectiveNode] = []
        for node in self.nodes:
            deps = node.depends_on or ()
            if all(node_map[dep].status in TERMINAL for dep in deps if dep in node_map):
                result.append(node)
        return result

    def pending_unblocked_nodes(self) -> list[ObjectiveNode]:
        """All unblocked ``pending`` nodes, in position order."""
        return [n for n in self.unblocked_nodes() if n.status == NodeStatus.PENDING]

    def plannable_nodes(self) -> list[ObjectiveNode]:
        """All unblocked, resumable/plannable nodes in position order.

        A node is plannable when it is ``pending``, or a ``planning`` **claim with no saved plan**
        (``pr is None``). A ``planning`` node that already carries a ``pr`` backlink is treated as
        in-flight (a committed plan), not resumable.
        """
        return [
            n
            for n in self.unblocked_nodes()
            if n.status == NodeStatus.PENDING or (n.status == NodeStatus.PLANNING and n.pr is None)
        ]

    def resumable_claims(self) -> list[ObjectiveNode]:
        """All unblocked ``planning`` claims with no saved plan (``pr is None``), in position
        order — the "live or abandoned claim" set the surfaces report."""
        return [n for n in self.plannable_nodes() if n.status == NodeStatus.PLANNING]

    def next_plannable(self) -> ObjectiveNode | None:
        """The next node implicit selection should take: **pending-first, claims as fallback**.

        The first unblocked ``pending`` node by position; if none exists, the first resumable
        ``planning`` claim by position; else ``None``. Pending-first makes parallel
        ``objective-plan`` launches safe: a claim cannot be distinguished from a session actively
        planning in another terminal, so implicit selection never steals/duplicates a possibly-live
        claim while safe pending work exists — while an abandoned claim still self-heals once it is
        the only plannable thing left (and is always resumable explicitly via ``--node``).
        """
        pending = self.pending_unblocked_nodes()
        if pending:
            return pending[0]
        claims = self.resumable_claims()
        return claims[0] if claims else None

    def in_flight_nodes(self) -> list[ObjectiveNode]:
        """Nodes with a committed/in-flight plan, in position order.

        ``in_progress`` (a committed plan), or a ``planning`` node that already carries a ``pr``
        backlink (a saved-but-not-yet-advanced edge case).
        """
        return [
            n
            for n in self.nodes
            if n.status == NodeStatus.IN_PROGRESS
            or (n.status == NodeStatus.PLANNING and n.pr is not None)
        ]

    def classify_for_planning(self) -> PlanSelection:
        """Classify the objective's planning state (drives honest factory reporting).

        Order: a plannable node wins (pending-first, resumable claims as fallback — see
        :meth:`next_plannable`); else complete; else an in-flight node; else blocked.
        """
        node = self.next_plannable()
        if node is not None:
            return PlanSelection(kind="plannable", node=node)
        if self.is_complete():
            return PlanSelection(kind="complete", node=None)
        in_flight = self.in_flight_nodes()
        if in_flight:
            return PlanSelection(kind="in_flight", node=in_flight[0])
        return PlanSelection(kind="blocked", node=None)

    def is_complete(self) -> bool:
        """True when every node is terminal."""
        return all(node.status in TERMINAL for node in self.nodes)
