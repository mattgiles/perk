"""The objective-storage tier contract.

This module is the backend-neutral objective-storage tier: the ``ObjectiveStore`` `Protocol`, its
backend-neutral result dataclasses, and the one backend-neutral error type. The objective tier is
distinct from the issue-tracking tier — the two are conceptually distinct populations even when one
backend happens to store both as issues — so an objective may be a GitHub issue **or** a Linear
**Project** (``github/objective_store.py`` and ``linear/project_store.py`` are the two concrete
stores).

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
from enum import StrEnum
from typing import Literal, Protocol

from perk import objective
from perk.backends.engagement import (
    AgentSessionRead,
    DescriptionEdit,
    EngagementComment,
    NodeEngagement,
)
from perk.backends.issue_backend import GistSummary
from perk.objective.drift import DriftCode, DriftCondition, DriftReport


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
class AdoptableSourceIssue:
    """One pre-existing project issue read verbatim for in-place objective adoption (§8.30).

    ``title``/``body`` are untrusted human DATA. ``id`` is the backend-owned opaque id (a Linear
    issue UUID); ``identifier`` is the human ref (``ENG-N``). Empty on GitHub (single-issue
    objectives have no child issues).
    """

    id: str
    identifier: str
    url: str
    title: str
    body: str


@dataclass(frozen=True)
class AdoptableObjectiveSource:
    """A pre-existing human source read verbatim for in-place objective adoption (§8.30).

    A Linear **Project** (and its issues) or a GitHub **issue**. ``prose`` is the overview/body
    (untrusted human DATA); ``issues`` are the project's existing issues (empty on GitHub). ``id``
    is opaque (a project UUID or a GitHub issue number stringified). The objective-tier twin of
    ``IssueBackend.AdoptableIssue``.
    """

    id: str
    url: str
    title: str
    prose: str
    issues: tuple[AdoptableSourceIssue, ...] = ()


@dataclass(frozen=True)
class NativeCancellation:
    """One roadmap node observed natively canceled at the backend (a human Linear cancel).

    ``persisted_status`` is the node's PERSISTED attachment status — perk's own durable record,
    which the native cancellation overrides only as an effective *read* projection (the node
    reads back ``SKIPPED``); the attachment itself is untouched by the read. Backends without
    a native workflow-state surface (GitHub; the dormant issue-backed Linear store) never emit
    one.
    """

    node_id: str
    persisted_status: objective.NodeStatus


class CancellationRepairOutcome(StrEnum):
    """The conditional native-cancellation metadata write's outcome vocabulary (§8.54).

    ``APPLIED`` = the compare-and-write landed; ``ALREADY_CONVERGED`` = the attachment already
    carries the new status (no write); ``STALE`` = a fresh-read predicate failed (the world
    moved) — skipped/not-applied, never an abort.
    """

    APPLIED = "applied"
    ALREADY_CONVERGED = "already_converged"
    STALE = "stale"


@dataclass(frozen=True)
class ObjectiveState:
    """An objective's observable state: header + roadmap nodes (``perk objective show``).

    Backend-neutral: ``id`` is opaque (an issue number or a Project id stringified) and ``header``
    is an opaque backend-owned mapping. ``native_cancellations`` is the backend-observation
    provenance for nodes whose native workflow state is canceled (their ``nodes`` entry reads
    back with effective ``SKIPPED`` status while the persisted attachment status rides here);
    default-empty — no provenance means existing behavior. ``state`` is the objective entity's
    lifecycle read: ``"closed"`` when the backing entity is retired (a closed GitHub issue; a
    completed/canceled Linear Project; the retired issue-backed sentinel), else ``"open"`` —
    close transitions gate on it so a re-run reports a real transition, never an
    idempotent-write guess (defaulted ``"open"``: the additive read).
    """

    id: str
    url: str
    title: str
    header: dict[str, object]
    nodes: tuple[objective.ObjectiveNode, ...]
    native_cancellations: tuple[NativeCancellation, ...] = ()
    state: Literal["open", "closed"] = "open"


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
    """The result of a ``repair_objective_drift`` pass.

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

    def read_objective_source(self, *, source_id: str) -> AdoptableObjectiveSource | None:
        """Read *any* pre-existing source (a Linear **Project** / a GitHub **issue**) verbatim for
        in-place adoption (§8.30) — the objective-tier twin of ``IssueBackend.read_issue``.

        Returns the source's prose + existing issues as untrusted human DATA (``issues`` empty on
        GitHub). ``None`` when the source is genuinely absent; **raises** ``ObjectiveStoreError`` on
        an infra failure. The source is returned even when closed/completed — the OPEN/not-an-
        objective refusals live in the ``objective author --from`` cold door, not here. A store with
        no project-source surface (the dormant issue-backed Linear store) returns ``None``.
        """
        ...

    def adopt_source_as_objective(
        self,
        *,
        source_id: str,
        title: str,
        prose: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode],
        adopt_map: dict[str, str],
        dry_run: bool = False,
    ) -> ObjectiveRef | None:
        """Stamp perk's objective metadata **additively** into a pre-existing source IN PLACE
        (§8.30), never minting a second project/issue.

        ``prose`` is the MODEL-authored Reconcilable prose; the source's ORIGINAL overview/body is
        archived verbatim into an ``Adopted-from`` Immutable note appended below the Reconcilable
        markers (``objective.render_adopted_overview_note``). ``roadmap_nodes`` is the authored
        roadmap; ``adopt_map`` (node id → existing source-issue id) maps a node to an EXISTING
        project issue — a mapped node stamps the ``objective-node`` block into that issue (title +
        human body verbatim) + attaches it to its phase milestone + reuses it as the roadmap node;
        unmapped nodes mint a fresh node-issue. ``adopt_map`` is ignored on GitHub (no children).

        Returns the source's ``ObjectiveRef`` (``existed=True`` on idempotent re-save via
        ``run_id``, else ``existed=False``). Returns **``None``** for a store that does NOT support
        in-place adoption (the dormant issue-backed Linear store) — the unambiguous "doesn't adopt"
        signal (mirrors ``save_node_plan → None``). ``dry_run`` returns ``None`` (resolving the
        source needs a network read; the cold door's ``--dry-run`` is offline). An empty
        ``roadmap_nodes`` raises (the storage backstop). The additive stamp is idempotent: a re-save
        finds the now-perk objective via ``run_id`` and returns ``existed=True`` (never re-archiving
        / double-stamping).
        """
        ...

    def supersede_objective(
        self,
        *,
        old_objective_id: str,
        title: str,
        prose: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode],
        carry_map: dict[str, str],
        delivery: objective.DeliveryPolicy | None = None,
        delivery_lineage: str | None = None,
        close_predecessor: bool = True,
        dry_run: bool = False,
    ) -> ObjectiveRef | None:
        """Re-author an objective as a **net-new** objective that supersedes and closes the old one
        (the objective analog of ``plan replan`` — but close-old/create-new, not an in-place upsert,
        because ``create_objective`` is find-then-return idempotent on ``run_id``, not an upsert).

        Creates a net-new objective from ``title``/``prose``/``roadmap_nodes`` (idempotent on
        ``run_id`` — find-then-return ``existed=True``), stamps ``supersedes=<old_objective_id>``
        into the new header, then **closes** ``old_objective_id`` (stamping
        ``superseded_by=<new id>`` into its header) and posts a best-effort status update.
        **Create-new-first, close-old-last; the close + the old-side stamp are fail-open** (a
        failure there never fails the create — mirrors the fail-open bookkeeping posture in
        ``create_objective``'s ``post_status_update``).

        ``carry_map`` (new-roadmap-node-id → existing source-node-**issue** id) maps a carried
        roadmap node to an existing node-issue to **move** into the new objective (Linear project
        store only — preserving identity / open PRs / discussion); it is ignored where the store has
        no node-issues (GitHub re-authors the carried nodes as fresh rows). Dropped (un-carried)
        still-open node-issues on the old objective are Canceled (Linear project store).

        Returns the new objective's ``ObjectiveRef`` (``existed=True`` on idempotent re-save via
        ``run_id``, else ``existed=False``). Returns **``None``** for a store that does NOT support
        superseding (the dormant issue-backed Linear store) — the unambiguous "doesn't support it"
        signal (mirrors ``adopt_source_as_objective → None``). ``dry_run`` returns ``None``
        (resolving the old objective needs a network read; the cold door's ``--dry-run`` is
        offline). An empty ``roadmap_nodes`` raises (the storage backstop).

        ``delivery``/``delivery_lineage`` are the reviewed delivery choice + train identity
        (§8.45), composed into the NEW objective's initial header atomically — the cold door
        owns the copy-or-mint lineage decision; the store persists what it is given. ``None``
        keeps the header byte-identical (the §8.42 absence rule).

        ``close_predecessor=False`` is the transfer protocol's deferred-close arm (§8.53):
        create + carried moves/fresh nodes only — no ``superseded_by`` stamp, no close, no
        dropped-node cancels (those move to :meth:`finalize_supersession`, called only after
        the successor projection verifies) — and the found-by-``run_id`` arm is **convergent**
        instead of an early return: the store verifies and completes any interrupted
        subordinate creation writes (GitHub: marker-discover/reuse of an already-posted
        objective-body comment + the ``objective_comment_id`` backfill; Linear: the manifest
        attachment, overview callout, milestones, each carried move re-applied idempotently,
        attachment-less fresh node-issues recovered by their atomic create-time fingerprint,
        dependency relations). The ``close_predecessor=True`` found-arm keeps
        today's early return byte-unchanged.
        """
        ...

    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool:
        """The extracted close side of the supersede model (§8.53's deferred close): stamp
        ``superseded_by=<new>`` into the old objective's header, retire the old objective
        (GitHub: close the issue; Linear project store: Cancel every dropped still-open
        node-issue — carried node-issues have already been moved out — then mark the project
        complete), and post a best-effort status update.

        **Raising** (unlike the fail-open close inside ``supersede_objective(close_predecessor
        =True)``, which wraps this method fail-open) and **idempotent**: an already-present
        ``superseded_by`` stamp skips the re-stamp; an already closed/canceled/completed old
        objective is success. Returns ``True`` on (idempotent) success; **``False``** for a
        store that does not support superseding (the dormant issue-backed Linear store — the
        no-op-family signal mirroring ``supersede_objective → None``). Raises
        ``ObjectiveStoreError`` on an infra failure.
        """
        ...

    def create_objective(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode] | None = None,
        delivery: objective.DeliveryPolicy | None = None,
        delivery_lineage: str | None = None,
        dry_run: bool = False,
    ) -> ObjectiveRef:
        """Create the objective (the two-step create): compose + post the objective (header +
        roadmap blocks), post the objective-body comment (rendered table + prose), then backfill
        the comment id into the header. ``body`` is the authored objective prose; the roadmap comes
        from ``roadmap_nodes`` when given (the structured path), else is parsed from ``body``.
        ``base`` is the objective's target branch, persisted into the ``objective-header``
        block; ``None`` leaves it unset (node plans fall through to ``[workflow] base`` → default).
        Idempotent on ``run_id`` (find-then-return, ``existed=True``). A dry run returns
        ``ObjectiveRef(id="0", url="(dry-run)", existed=False)`` without touching the backend. An
        empty roadmap raises (the storage backstop: no surface may store a node-less objective).
        ``delivery``/``delivery_lineage`` (§8.45) compose into the initial header atomically —
        ``None`` keeps the header byte-identical (the §8.42 absence rule)."""
        ...

    def create_gist_source(
        self, *, title: str, prose: str, run_id: str, dry_run: bool = False
    ) -> ObjectiveRef | None:
        """Create an objective-scoped gist as a project-tier source (contracts.md §8.41).

        In the no-op-return family: returns **``None``** for a store with no project surface
        (the GitHub store and the dormant issue-backed Linear store) — the CLI falls back to the
        issue tier. The Linear project store creates a deliberately light **project** (name =
        ``title``; overview = an inline-code ``gist-header`` block + the transcoded prose — no
        milestones, no node-issues, no metadata sentinel; the overview block IS the identity).
        Idempotent on ``run_id`` (a projects-scan find-then-return, ``existed=True``).
        ``dry_run`` returns ``None`` (falls through to the issue-tier dry-run compose preview).
        Raises ``ObjectiveStoreError`` on an infra failure.
        """
        ...

    def list_gist_sources(self) -> tuple[GistSummary, ...]:
        """Every project-tier gist (the ``perk gist list`` project arm), with the stored ``scope``
        and the ``adopted`` detection (an ``objective-header`` block in the same overview — an
        adopted gist project has been re-authored in place as an objective). ``()`` for a store
        with no project surface. Raises on an infra/query failure (never masks it as empty)."""
        ...

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        """Read an objective's state (header + roadmap nodes). None when absent; raises on an infra
        failure."""
        ...

    def journal_carrier_id(self, *, objective_id: str) -> str | None:
        """Resolve the **issue-tier id** of the objective's operation-journal carrier (§8.43) —
        the issue whose comments physically carry the append-only stack-operation journal.

        Each store returns the thing its model appends to: ``GitHubObjectiveStore`` → the
        objective issue itself (``objective_id``); the dormant issue-backed Linear store → the
        objective issue (``objective_id``); ``LinearProjectObjectiveStore`` → the Project
        metadata sentinel issue's **identifier**. The returned id MUST be usable with the
        matching ``IssueBackend``'s comment ops (``read_comments`` / ``add_issue_comment``).

        ``None`` when the objective is genuinely absent; **raises** ``ObjectiveStoreError`` when
        the objective exists but is broken as a perk objective (a Linear project with no
        metadata sentinel — mirroring the broken-sentinel raise) and on an infra failure (never
        masks an error as None).
        """
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

        ``header_fields`` is the already-composed
        ``plan.render_plan_header_fields(plan.PlanHeader(...))`` dict (the blessed emission
        path; the store is handed data, not asked to know ``plan-save``'s schema beyond
        rendering it).

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

    def reopen_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Converge the objective's own entity back to open — the mirror of ``close_objective``,
        serving the reopen-on-incomplete invariant (a non-terminal ``add_objective_node`` makes
        the roadmap incomplete again, so the objective must be live; contracts §8.20).

        Converge-to-open, not a toggle: returns ``True`` iff a reopen write actually happened;
        ``False`` when the objective is already open (or in any state a reopen must not touch —
        Linear ``canceled`` is a human cancel, not perk's to undo) or on a ``dry_run`` (no write).
        Each store reopens the thing it actually stores: ``GitHubObjectiveStore`` re-opens the
        issue (PATCH ``state=open``); ``LinearProjectObjectiveStore`` moves a ``completed``
        Project back to ``started``; the issue-backed ``LinearObjectiveStore`` moves a
        ``completed``-type issue state back to the team's ``started`` state. Raises
        ``ObjectiveStoreError`` on an infra failure. The superseded-lineage exemption is the
        CALLER's guard (backend-neutral, at the door — a store never inspects ``superseded_by``).
        """
        ...

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        """Post a human-readable status update to the objective's native update surface.

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
        project state.

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
        stopping at the first failed Linear write (fail-loud).

        ``dry_run`` plans the repairs (the would-apply set) without any write. Only
        ``LinearProjectObjectiveStore`` carries real behavior; the other stores return an empty
        ``RepairResult`` (no divergence surface). Raises ``ObjectiveStoreError`` when the objective
        is absent / on an infra failure (never on a repairable drift write, which is recorded in
        ``failed`` + ``aborted``)."""
        ...

    # --- human-engagement reads ---
    #
    # The objective-tier twin of the ``IssueBackend`` read contract — same untrusted-DATA +
    # distinguishable-author discipline, keyed on ``objective_id``. Stores without a surface ship a
    # clean empty/no-op impl; the project-backed store carries honest project-level reads.

    def read_comments(self, *, objective_id: str) -> tuple[EngagementComment, ...]:
        """Read an objective's comments with author identity + edit flag. Oldest-first. Raises
        ``ObjectiveStoreError`` on an infra failure; empty yields ``()``."""
        ...

    def read_description_edits(self, *, objective_id: str) -> tuple[DescriptionEdit, ...]:
        """Read an objective's description/body edit events. ``diff`` is best-effort and may be
        ``None``. Raises on an infra failure; no edits yields ``()``."""
        ...

    def read_agent_session(self, *, objective_id: str) -> AgentSessionRead:
        """Read the objective's agent-session activities + the derived stop indicator. A store with
        no agent-session surface returns the empty ``AgentSessionRead``; **raises** on an
        infra/auth failure."""
        ...

    def read_node_engagement(self, *, objective_id: str, node_id: str) -> NodeEngagement:
        """Read a single roadmap node-issue's pre-planning human engagement.

        The **node-keyed** read (the other reads above are keyed on the whole objective/issue): the
        node-issue's comments + description edits, with distinguishable authorship, bundled as a
        :class:`NodeEngagement`. Agent-session reads are excluded (a pre-planning node-issue has no
        perk agent session). Returns the empty ``EMPTY_NODE_ENGAGEMENT`` for a store with
        no per-node-issue surface (GitHub single-issue objectives; the dormant issue-backed Linear
        store) or a node-issue that cannot be resolved; **raises** ``ObjectiveStoreError`` on an
        infra/auth failure (never masks infra as empty)."""
        ...
