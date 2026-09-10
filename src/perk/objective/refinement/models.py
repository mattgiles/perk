"""Objective-node refinement — the frozen domain types (contracts.md §8.67).

A **refinement** is a dated, reviewed, advisory elaboration of one existing roadmap node,
persisted as a single marked comment on the node's carrier (the Linear node-issue; on GitHub the
objective issue itself). It is content only: never a plan, a claim, a node status, a readiness
signal, or a freshness proof.

This module is the pure type leaf: frozen dataclasses plus the typed error, with **no**
Pydantic, Click, concrete-backend, or I/O dependency. It imports the existing ``NodeStatus``,
``EngagementComment``, and the issue-contract ``MarkedCommentExpectation`` rather than
duplicating them; the wire format and the validators live in :mod:`perk.objective.refinement.codec`,
the backend-facing flow in :mod:`perk.objective.refinement.service`.
"""

from dataclasses import dataclass
from enum import StrEnum

from perk.backends.engagement import EngagementComment
from perk.backends.issue_backend import MarkedCommentExpectation
from perk.objective._models import NodeStatus

# The node statuses a refinement may be AUTHORED against (reads are unrestricted). A node with a
# plan (backlink or plan metadata) is never eligible even in these statuses.
REFINABLE_STATUSES: frozenset[NodeStatus] = frozenset({NodeStatus.PENDING, NodeStatus.BLOCKED})


class RefinementErrorCode(StrEnum):
    """The refinement service's complete error vocabulary (the mapping table in §8.67)."""

    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_BACKEND = "unsupported_backend"
    OBJECTIVE_NOT_FOUND = "objective_not_found"
    NODE_NOT_FOUND = "node_not_found"
    NODE_INELIGIBLE = "node_ineligible"
    NO_UNREFINED_NODE = "no_unrefined_node"
    MALFORMED_TARGET = "malformed_target"
    AMBIGUOUS_TARGET = "ambiguous_target"
    MALFORMED_REFINEMENT = "malformed_refinement"
    AMBIGUOUS_REFINEMENT = "ambiguous_refinement"
    STALE_SOURCE = "stale_source"
    STALE_REFINEMENT = "stale_refinement"
    BACKEND_ERROR = "backend_error"
    WRITE_UNVERIFIED = "write_unverified"


class RefinementError(Exception):
    """A refinement read/selection/save refused or failed, with a typed ``code``.

    ``comment_ids`` names the carrier comments the outcome rests on (duplicates, the stale or
    malformed record); ``write_attempted`` is True only when a mutation attempt was made before
    the error (the caller must read back rather than blindly retry). Original causes are
    chained, never relabelled.
    """

    def __init__(
        self,
        code: RefinementErrorCode,
        message: str,
        *,
        comment_ids: tuple[str, ...] = (),
        write_attempted: bool = False,
    ) -> None:
        self.code = code
        self.comment_ids = comment_ids
        self.write_attempted = write_attempted
        super().__init__(message)


@dataclass(frozen=True)
class RefinementIdentity:
    """The stable target identity a refinement is bound to. ``carrier_id`` is the carrier's
    stable backend id (the Linear node-issue UUID; on GitHub the objective issue's normalized
    number string, shared by every node of the objective) — its human identifier/URL are
    addressing data kept OUT of the identity hash. Every field is a nonblank string."""

    backend: str
    objective_id: str
    objective_run_id: str
    node_id: str
    carrier_id: str


@dataclass(frozen=True)
class RefinementSource:
    """The node content a refinement was authored against — the fenced source (hashed into
    ``source_digest``). Statuses, backlinks, timestamps, display URLs, objective prose, and
    sibling progress are deliberately excluded. Dependency tuples are unique and sorted by
    ``node_sort_key``; ``depends_on`` preserves null (unspecified/unrecoverable) vs empty where
    the backend can observe it, ``effective_depends_on`` is the graph-inferred resolution."""

    description: str
    slug: str | None
    comment: str | None
    depends_on: tuple[str, ...] | None
    effective_depends_on: tuple[str, ...]
    issue_description: str


@dataclass(frozen=True)
class RefinementCodeBasis:
    """The code checkpoint the refinement was authored on: dated provenance, not a freshness
    gate. ``head_sha`` is a full 40-hex commit id; ``captured_at`` a canonical UTC timestamp."""

    head_sha: str
    dirty: bool
    captured_at: str


@dataclass(frozen=True)
class RefinementProvenance:
    """Who/when/on-what authored the refinement. Preserved verbatim across retries — a save
    never regenerates it. Provenance never proves human approval."""

    authoring_run_id: str
    authored_at: str
    code_basis: RefinementCodeBasis


@dataclass(frozen=True)
class RefinementDocument:
    """One complete refinement: identity + fenced source + digest + provenance + the advisory
    Markdown body. ``source_digest`` MUST equal ``codec.source_digest(source)``."""

    identity: RefinementIdentity
    source: RefinementSource
    source_digest: str
    provenance: RefinementProvenance
    markdown: str


@dataclass(frozen=True)
class RefinementTarget:
    """One roadmap node as observed by the store's refinement read: its identity, current
    source (+ digest), carrier addressing, and the eligibility inputs. Every node of a supported
    objective appears here regardless of status — eligibility is a derived property."""

    identity: RefinementIdentity
    source: RefinementSource
    source_digest: str
    carrier_identifier: str
    carrier_url: str
    status: NodeStatus
    plan_ref: str | None
    has_plan_metadata: bool

    @property
    def eligible(self) -> bool:
        """Authoring eligibility: pending/blocked, no plan backlink, no plan metadata. Reads
        are never gated on this."""
        return (
            self.status in REFINABLE_STATUSES
            and self.plan_ref is None
            and self.has_plan_metadata is False
        )


@dataclass(frozen=True)
class RefinementObjectiveSnapshot:
    """The store's refinement read of one supported objective. An empty ``targets`` tuple is a
    supported objective with no nodes (never "unsupported"); a missing/non-perk objective is
    the read's ``None``, not a snapshot."""

    backend: str
    objective_id: str
    objective_run_id: str
    objective_url: str
    targets: tuple[RefinementTarget, ...]


@dataclass(frozen=True)
class SavedRefinement:
    """A refinement as actually observed on its carrier: the decoded document, the observed
    comment (native id/body/author/timestamps), and the digest of the exact stored body."""

    document: RefinementDocument
    comment: EngagementComment
    body_digest: str

    @property
    def saved_at(self) -> str:
        """The backend's own last-write timestamp (``edited_at`` when set, else ``created_at``)
        — an observed native string, never canonicalized or hashed."""
        return (
            self.comment.edited_at
            if self.comment.edited_at is not None
            else self.comment.created_at
        )


@dataclass(frozen=True)
class RefinementRead:
    """The result of reading (or selecting) one target: the current target plus its valid saved
    record, or ``None`` for genuine absence. Staleness never makes a record absent."""

    target: RefinementTarget
    saved: SavedRefinement | None

    @property
    def source_changed(self) -> bool:
        """Advisory: the saved record was authored against a different source than the target
        now carries. False when nothing is saved."""
        if self.saved is None:
            return False
        return self.saved.document.source_digest != self.target.source_digest

    @property
    def expected(self) -> MarkedCommentExpectation:
        """The guarded-save expectation this read establishes: absence, or the exact observed
        comment id + stored-body digest."""
        if self.saved is None:
            return MarkedCommentExpectation(comment_id=None, body_digest=None)
        return MarkedCommentExpectation(
            comment_id=self.saved.comment.id, body_digest=self.saved.body_digest
        )


@dataclass(frozen=True)
class RefinementSaveRequest:
    """A save: the complete document plus the caller's retained expectation (from the read that
    grounded the authoring). The expectation is never refreshed implicitly."""

    document: RefinementDocument
    expected: MarkedCommentExpectation
