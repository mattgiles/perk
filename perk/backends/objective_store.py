"""The objective-storage tier contract (Objective #548, Node 2.1).

perk's objective storage is, today, fused into the issue-tracking tier: an objective is a GitHub
issue, and the ``IssueBackend`` `Protocol` carries the objective methods alongside the plan/learn
issue methods. Objective #548 splits the **objective-storage tier** back out into its own
backend-neutral contract so a later node can make a Linear **Project** a canonical objective (not
just an issue) - the issue tier and the objective tier are conceptually distinct populations even
when one backend happens to store both as issues.

This module is that tier's contract: the ``ObjectiveStore`` `Protocol`, its backend-neutral result
dataclasses, and the one backend-neutral error type. It is deliberately **dormant** in Node 2.1 -
no extraction, no consumers - mirroring exactly how ``issue_backend.py`` shipped the
``IssueBackend`` contract dormant in Objective #252, Node 1.1 (Node 1.2 then extracted the GitHub
backend behind it).
Node 2.2 will extract ``GitHubObjectiveStore`` + ``resolve_objective_store``, remove the objective
methods from ``IssueBackend``, and rewire every consumer - atomically, the only point at which that
removal is CI-green.

Contract disciplines (every concrete store MUST honor these):

- **Constructor-bound repo context.** Methods take no ``repo_root``; a store instance is constructed
  for exactly one repo (GitHub carries ``repo_root`` as the ``gh`` cwd; Linear - workspace-scoped -
  carries team/API-key config bound at construction).
- **String ids at the boundary.** Every objective/comment id crossing this boundary is a ``str``
  (GitHub's issue numbers stringified; a Linear Project id is natively a string).
- **Backend-owned opaque header values.** The ``header`` dict is opaque ``dict[str, object]``;
  header-embedded values (e.g. the objective-body comment id) are backend-owned and a caller must
  never interpret them.
- **Error discipline.** Mutations raise ``ObjectiveStoreError``; lookups return ``... | None`` for
  not-found and **raise** on an infra failure - never mask an error as None. Concrete stores map
  their native errors (``GitHubError``, Linear HTTP errors) into ``ObjectiveStoreError`` at their
  boundary.

Backend-neutral naming: the methods drop the issue-tier's ``_issue`` suffix
(``find_objective``/``create_objective``) and use ``objective_id`` everywhere (vs the issue tier's
``issue_id``), because the stored thing is an objective - a GitHub issue **or** a Linear Project.
"""

from dataclasses import dataclass
from typing import Protocol

from perk import objective
from perk.objective_drift import DriftCode, DriftCondition, DriftReport


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
class ObjectiveNodeAdd:
    """The result of an ``add_objective_node`` write (a new roadmap node inserted)."""

    objective_id: str
    node_id: str  # the auto-assigned <phase>.<n>
    comment_updated: bool
    dry_run: bool


@dataclass(frozen=True)
class RepairAction:
    """One repair the ``--fix`` path applied (or would apply / failed at), identified by its drift
    ``code`` and the affected ``node_id`` (``None`` for objective-scoped repairs). ``error`` carries
    the write-failure message on the **failed** action (``None`` for applied / would-apply ones)."""

    code: DriftCode
    node_id: str | None
    error: str | None = None


@dataclass(frozen=True)
class RepairResult:
    """The result of a ``repair_objective_drift`` pass (Node 4.4 / #612).

    Fail-loud: repairs apply in a deterministic order and the **first** failed Linear write stops
    the batch (``aborted=True``, the failing condition in ``failed``); ``applied`` records what
    landed before the abort (durable + idempotent on a re-run). ``remaining`` is the still-present
    drift after the pass (or the would-apply set under ``dry_run``).
    """

    applied: tuple[RepairAction, ...]
    failed: RepairAction | None
    remaining: tuple[DriftCondition, ...]
    aborted: bool
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
    compose only - no backend writes.
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

    def save_node_plan(
        self,
        *,
        objective_id: str,
        node_id: str,
        header_fields: dict[str, object],
        plan_markdown: str,
        dry_run: bool = False,
    ) -> ObjectiveRef | None:
        """Write a plan **into** the objective's node-issue (the node-issue↔plan unification).

        For a store whose model fuses the roadmap node and the plan into a single entity (the
        Linear **Project** store: a roadmap node already *is* a Linear issue), an objective-linked
        ``plan-save`` writes the plan **into that node-issue** rather than minting a second
        ``perk:plan`` issue - the ``plan-header`` block is merged into the node-issue description
        (Linear-safe inline-code), the plan body is upserted as a single node-issue comment, and the
        node-issue's title/``objective-node`` block/prose are untouched (node-issues are discovered
        by project membership + the ``objective-node`` block, never by a ``perk:plan`` label).
        Returns the **node-issue** ``ObjectiveRef`` (``existed=True`` - an in-place write into an
        existing issue).

        ``header_fields`` is the already-composed ``plan.PlanHeader(...).to_data()`` dict (the store
        is handed data, not asked to know ``plan-save``'s schema beyond rendering it).

        **Returns ``None`` for a store that does NOT unify node + plan** - the single, unambiguous
        "doesn't unify" signal (no separate capability flag). ``GitHubObjectiveStore`` and the
        issue-backed ``LinearObjectiveStore`` ``return None`` unconditionally; the caller then falls
        back to the standalone plan-issue path. ``None`` is unambiguous: a unifying store **raises**
        ``ObjectiveStoreError`` when the node is not found (never returns ``None`` for not-found).

        A ``dry_run`` returns ``None`` (resolving the node-issue requires a network read;
        ``plan-save --dry-run`` is offline, so the caller falls back to the offline compose path).
        """
        ...

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Retire the objective's own entity on completion (removes the issue-tier leak).

        Each store closes the thing it actually stores: ``GitHubObjectiveStore`` **closes** the
        GitHub objective issue; the issue-backed ``LinearObjectiveStore`` moves the objective issue
        to its Done state; ``LinearProjectObjectiveStore`` **marks the Linear Project complete**
        (a Project is not an issue - it cannot be "closed" through the issue tier). Returns ``True``
        on a real close; ``dry_run`` returns ``False`` without a write. Raises
        ``ObjectiveStoreError`` on an infra failure.
        """
        ...

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        """Post a human-readable status update to the objective's native update surface (Node 4.3).

        Returns ``True`` when an update was posted, ``False`` for a store with no update surface
        (``GitHubObjectiveStore`` and the issue-backed ``LinearObjectiveStore`` always return
        ``False``) or a ``dry_run``. Only ``LinearProjectObjectiveStore`` posts (a Linear Project
        **Update** via ``projectUpdateCreate``). The method MAY raise ``ObjectiveStoreError`` on an
        infra failure — every call site wraps it **fail-open** (the update is bookkeeping, never
        load-bearing: a Linear failure must never break a merge or a node transition).
        """
        ...

    def add_objective_node(
        self,
        *,
        objective_id: str,
        phase: int,
        description: str,
        status: objective.NodeStatus = objective.NodeStatus.PENDING,
        slug: str | None = None,
        depends_on: tuple[str, ...] | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> ObjectiveNodeAdd:
        """Insert a new node into ``phase`` (auto-assigned ``<phase>.<n>``, appended after that
        phase's last node): re-render the authoritative objective-roadmap block AND best-effort
        re-render the objective-body comment table. Raises ``ObjectiveStoreError`` on an id
        collision / invalid roadmap. A dry run validates + composes only."""
        ...

    def detect_objective_drift(self, *, objective_id: str) -> DriftReport:
        """Detect drift between the persisted ``objective-manifest`` baseline and the observed
        project state (Node 4.4 / #612).

        Only a store with an independently-editable divergence surface carries real behavior: the
        project-backed ``LinearProjectObjectiveStore`` builds the observed snapshot and runs
        ``objective_drift.detect_drift``. ``GitHubObjectiveStore`` and the issue-backed
        ``LinearObjectiveStore`` return an **empty** ``DriftReport()`` (their roadmap is edited
        atomically with the rest of the body — no divergence surface, no drift), mirroring the
        ``save_node_plan → None`` / ``post_status_update → False`` no-op precedent. Raises
        ``ObjectiveStoreError`` when the objective is absent / on an infra failure."""
        ...

    def repair_objective_drift(self, *, objective_id: str, dry_run: bool = False) -> RepairResult:
        """Apply the **safe, unambiguous** (repairable) drift repairs in a deterministic order,
        stopping at the first failed Linear write (fail-loud; Node 4.4 / #612).

        ``dry_run`` plans the repairs (the would-apply set) without any write. Only
        ``LinearProjectObjectiveStore`` carries real behavior; the other stores return an empty
        ``RepairResult`` (no divergence surface). Raises ``ObjectiveStoreError`` when the objective
        is absent / on an infra failure (never on a repairable drift write, which is recorded in
        ``failed`` + ``aborted``)."""
        ...
