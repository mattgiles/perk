"""The objective-storage tier contract (Objective #548, Node 2.1).

perk's objective storage is, today, fused into the issue-tracking tier: an objective is a GitHub
issue, and the ``IssueBackend`` `Protocol` carries the objective methods alongside the plan/learn
issue methods. Objective #548 splits the **objective-storage tier** back out into its own
backend-neutral contract so a later node can make a Linear **Project** a canonical objective (not
just an issue) — the issue tier and the objective tier are conceptually distinct populations even
when one backend happens to store both as issues.

This module is that tier's contract: the ``ObjectiveStore`` `Protocol`, its backend-neutral result
dataclasses, and the one backend-neutral error type. It is deliberately **dormant** in Node 2.1 —
no extraction, no consumers — mirroring exactly how ``issue_backend.py`` shipped the
``IssueBackend`` contract dormant in Objective #252, Node 1.1 (Node 1.2 then extracted the GitHub
backend behind it).
Node 2.2 will extract ``GitHubObjectiveStore`` + ``resolve_objective_store``, remove the objective
methods from ``IssueBackend``, and rewire every consumer — atomically, the only point at which that
removal is CI-green.

Contract disciplines (every concrete store MUST honor these):

- **Constructor-bound repo context.** Methods take no ``repo_root``; a store instance is constructed
  for exactly one repo (GitHub carries ``repo_root`` as the ``gh`` cwd; Linear — workspace-scoped —
  carries team/API-key config bound at construction).
- **String ids at the boundary.** Every objective/comment id crossing this boundary is a ``str``
  (GitHub's issue numbers stringified; a Linear Project id is natively a string).
- **Backend-owned opaque header values.** The ``header`` dict is opaque ``dict[str, object]``;
  header-embedded values (e.g. the objective-body comment id) are backend-owned and a caller must
  never interpret them.
- **Error discipline.** Mutations raise ``ObjectiveStoreError``; lookups return ``... | None`` for
  not-found and **raise** on an infra failure — never mask an error as None. Concrete stores map
  their native errors (``GitHubError``, Linear HTTP errors) into ``ObjectiveStoreError`` at their
  boundary.

Backend-neutral naming: the methods drop the issue-tier's ``_issue`` suffix
(``find_objective``/``create_objective``) and use ``objective_id`` everywhere (vs the issue tier's
``issue_id``), because the stored thing is an objective — a GitHub issue **or** a Linear Project.
"""

from dataclasses import dataclass
from typing import Protocol

from perk import objective


class ObjectiveStoreError(Exception):
    """An objective-store operation failed (infra/query/mutation).

    Backend-neutral: concrete stores map their native errors (``GitHubError``, Linear HTTP errors)
    into this at the boundary.
    """


@dataclass(frozen=True)
class ObjectiveRef:
    """A backend-neutral reference to an objective (a GitHub issue number **or** a Linear Project
    id, opaque). ``existed`` is True when returned by idempotent dedup (found, not freshly
    created)."""

    id: str
    url: str
    existed: bool


@dataclass(frozen=True)
class ObjectiveState:
    """An objective's observable state: header + roadmap nodes (``perk objective show``).

    Backend-neutral: ``id`` is opaque (an issue number or a Project id stringified) and ``header``
    is an opaque backend-owned mapping.
    """

    id: str
    url: str
    title: str
    header: dict[str, object]
    nodes: tuple[objective.ObjectiveNode, ...]


@dataclass(frozen=True)
class ObjectiveHeaderUpdate:
    """The result of a staged ``objective-header`` field write."""

    fields_updated: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class ObjectiveNodeUpdate:
    """The result of an ``update_objective_node`` write (roadmap + body comment re-rendered)."""

    objective_id: str
    node_id: str
    comment_updated: bool
    dry_run: bool


@dataclass(frozen=True)
class ObjectiveBodyUpdate:
    """The result of an ``update_objective_body`` write (the Reconcilable prose splice).

    ``comment_id`` is the backend-owned id of the objective-body comment (string at the boundary),
    or None on a path that never resolved one.
    """

    objective_id: str
    comment_id: str | None
    updated: bool
    dry_run: bool


class ObjectiveStore(Protocol):
    """The objective-storage tier contract (one instance per repo; see the module docstring).

    All parameters are keyword-only. Mutations raise ``ObjectiveStoreError``; lookups return
    ``... | None`` for not-found and raise on an infra failure. ``dry_run`` mutations validate +
    compose only — no backend writes.
    """

    # The store's id in the objective-backend vocabulary (e.g. "github"). Contract discipline:
    # stamped **verbatim** into `cache.plan-ref.provider`, so "the backend that wrote the objective
    # is the backend that gets stamped" is structurally true at every stamp site (mirrors
    # IssueBackend.backend_id).
    backend_id: str

    def find_objective(self, *, run_id: str) -> ObjectiveRef | None:
        """Find the **open** objective whose objective-header ``run_id`` matches. None for no
        match; raises on an infra failure (never masks the error as None)."""
        ...

    def create_objective(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
        roadmap_nodes: list[objective.ObjectiveNode] | None = None,
        dry_run: bool = False,
    ) -> ObjectiveRef:
        """Create the objective (the two-step create): compose + post the objective (header +
        roadmap blocks), post the objective-body comment (rendered table + prose), then backfill
        the comment id into the header. ``body`` is the authored objective prose; the roadmap comes
        from ``roadmap_nodes`` when given (the structured path), else is parsed from ``body``.
        Idempotent on ``run_id`` (find-then-return, ``existed=True``). A dry run returns
        ``ObjectiveRef(id="0", url="(dry-run)", existed=False)`` without touching the backend. An
        empty roadmap raises (the storage backstop: no surface may store a node-less objective)."""
        ...

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        """Read an objective's state (header + roadmap nodes). None when absent; raises on an infra
        failure."""
        ...

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> ObjectiveHeaderUpdate:
        """Merge ``fields`` into the objective-header block and write it back. Rejects keys outside
        ``objective.OBJECTIVE_HEADER_FIELDS`` (LBYL). A dry run validates + composes only."""
        ...

    def update_objective_node(
        self,
        *,
        objective_id: str,
        node_id: str,
        status: objective.NodeStatus | None = None,
        pr: str | None = None,
        description: str | None = None,
        dry_run: bool = False,
    ) -> ObjectiveNodeUpdate:
        """Update one roadmap node (explicit-status-only): re-render the roadmap block
        (authoritative) AND best-effort re-render the table in the objective-body comment (the
        roadmap block is the source of truth). Raises when the node is not found or the roadmap is
        invalid."""
        ...

    def update_objective_body(
        self, *, objective_id: str, prose: str, dry_run: bool = False
    ) -> ObjectiveBodyUpdate:
        """Splice ``prose`` into the Reconcilable region of the objective-body comment (the
        Mechanical table block and any Immutable notes are untouched). Raises when the objective has
        no body comment or the comment lacks the Reconcilable region. A dry run composes only."""
        ...
