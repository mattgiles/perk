"""The issue-tracking tier contract.

perk's GitHub gateway (the ``perk/github/`` package) fuses four tiers: issue tracking
(plan/learn/objective issues, marked comments, labels), PRs, CI/workflow, and auth. Only the
**issue-tracking tier** is backend-selectable (GitHub Issues today; Linear later) — PRs, CI, and
auth stay in ``perk/github/`` for **all** backends (PRs are GitHub-universal even under a Linear
issue backend). This module is that tier's contract: the ``IssueBackend`` `Protocol`, the
backend-neutral result dataclasses, and the one backend-neutral error type. The issue-tracking
tier is backend-selectable behind this contract: the GitHub backend lives behind it today and the
``[issues]`` config table drives a config-driven resolver (``perk/backends/resolve.py``).

Contract disciplines (every concrete backend MUST honor these):

- **Constructor-bound repo context.** Methods take no ``repo_root``; a backend instance is
  constructed for exactly one repo (GitHub carries ``repo_root`` as the ``gh`` cwd; Linear —
  workspace-scoped, not repo-scoped — carries team/API-key config bound at construction).
- **String ids at the boundary.** Every issue/comment id crossing this boundary is a ``str``
  (GitHub's ints stringified; Linear's ids are natively strings).
- **Normalized state vocabulary.** ``PlanState.state`` is the literal ``"OPEN" | "CLOSED"``
  (GitHub's casing kept as the canonical values). Backends with richer native states map them
  (e.g. Linear backlog/todo/in_progress → ``"OPEN"``; done/canceled → ``"CLOSED"``).
  Symmetrically, "close" operations move an issue to the backend's terminal/done state, and the
  ``find_*`` finders match **open** issues only.
- **Error discipline.** Mutations raise ``IssueBackendError``; lookups return ``... | None`` for
  not-found and **raise** on an infra failure — never mask an error as None. Concrete backends
  map their native errors (``GitHubError``, Linear HTTP errors) into ``IssueBackendError`` at
  their boundary.
- **Backend-owned header values.** The ``header`` dicts are opaque ``dict[str, object]``;
  header-embedded comment ids (e.g. ``objective_comment_id``) are backend-owned values a caller
  must never interpret.
"""

from dataclasses import dataclass
from typing import Protocol

from perk import plan
from perk.backends.engagement import (
    AgentSessionRead,
    DescriptionEdit,
    EngagementComment,
)
from perk.github import PullRequest


class IssueBackendError(Exception):
    """An issue-backend operation failed (infra/query/mutation).

    Backend-neutral: concrete backends map their native errors (``GitHubError``, Linear HTTP
    errors) into this at the boundary.
    """


@dataclass(frozen=True)
class Label:
    """A label ensured to exist. ``created`` is False when it already existed (idempotent)."""

    name: str
    created: bool


@dataclass(frozen=True)
class IssueRef:
    """A reference to an issue (plan/learn/objective). ``existed`` is True when returned by
    idempotent dedup (found, not freshly created)."""

    id: str
    url: str
    existed: bool


@dataclass(frozen=True)
class CommentResult:
    """An issue comment. ``posted`` is False only for a dry run."""

    posted: bool


@dataclass(frozen=True)
class PlanUpdate:
    """The result of an in-place ``update_plan_issue`` upsert (re-save path).

    ``body_updated`` is True when the existing plan-body comment was patched; False when no such
    comment was found and a fresh one was posted instead (legacy fallback) or on a dry run.
    """

    issue_id: str
    body_updated: bool
    title_updated: bool
    dry_run: bool


@dataclass(frozen=True)
class PlanHeaderUpdate:
    """The result of a staged ``plan-header`` field write."""

    fields_updated: tuple[str, ...]
    dry_run: bool


def parse_plan_pr(value: object) -> int | None:
    """The shared nullable plan-PR parser at the issue read boundary (§8.54).

    Absent/``None``/blank/``"None"`` means **no claim** → ``None``. A positive integer (or a
    string spelling one, with an optional leading ``#``) resolves the PR number. Anything
    malformed or non-positive resolves **no** number — without changing the raw header value,
    which stays available for ``malformed_plan_header`` classification and cancellation
    evidence. Read-side tolerance only: writers remain strict.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass — never a PR number
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "None":
            return None
        try:
            number = int(text.removeprefix("#"))
        except ValueError:
            return None
        return number if number > 0 else None
    return None


@dataclass(frozen=True)
class PlanState:
    """A plan issue's observable state: the parsed header + the resolved PR (if any).

    ``state`` is the normalized ``"OPEN" | "CLOSED"`` vocabulary (see the module docstring).
    ``header`` is the opaque plan-header mapping (backend-owned values).

    ``has_plan_header``/``has_objective_header`` are presence-only kind evidence computed at the
    backend read boundary (never a payload decode): they distinguish an absent header (not a
    plan) from a present-but-malformed one (a damaged plan) — the two states ``header == {}``
    collapses. Positive identification: no evidence = not a plan (defaults ``False``).
    """

    id: str
    url: str
    title: str
    header: dict[str, object]
    pr: PullRequest | None
    state: str
    # True when the backend's own storage carries the corresponding perk header for this
    # issue — presence-only kind evidence (never a payload decode).
    has_plan_header: bool = False
    has_objective_header: bool = False


@dataclass(frozen=True)
class LearnIssueSummary:
    """An open ``perk:learn`` issue, materialized for the learn-docs factory inbox.

    ``header`` is the typed learn-header read, populated by the backend from wherever it stores
    the header (GitHub parses the body block at list time; Linear decodes the learn attachment).
    ``None`` when absent/malformed (the gather-time default route never bricks on a stray
    header).
    """

    id: str
    title: str
    url: str
    body: str
    header: plan.LearnHeader | None = None


@dataclass(frozen=True)
class PlanSummary:
    """One open plan in the bounded completion/browse read
    (:meth:`IssueBackend.list_plan_completion_candidates`).

    ``id`` is the opaque backend-owned boundary id (a GitHub number stringified; a Linear human
    identifier like ``ENG-123``) — exactly what a user types at a plan-taking command. No URL:
    the completion surface consumes only id + title.
    """

    id: str
    title: str


@dataclass(frozen=True)
class PendingLearnPlan:
    """A closed plan issue whose plan-header ``learn_state`` is ``pending`` (§8.36) —
    landed, /learn not yet run. ``closed_at`` is the backend's close timestamp
    (ISO-8601 string) or ``None`` when unavailable."""

    id: str
    title: str
    url: str
    closed_at: str | None = None


@dataclass(frozen=True)
class GistSummary:
    """A gist — a backend-tracked statement of intent (contracts.md §8.41) — materialized for
    ``perk gist list``.

    ``scope`` is the stored consumption-tier hint (``"plan" | "objective"``; ``None`` when
    absent or unknown — the lenient gist-header read). ``adopted`` is True when the backend's
    own storage carries plan or objective metadata for the same object (in-place adoption
    stamped a ``plan-header``/``objective-header`` beside the ``gist-header``).
    """

    id: str
    title: str
    url: str
    body: str
    scope: str | None = None
    adopted: bool = False


@dataclass(frozen=True)
class AdoptableIssue:
    """A pre-existing (human-authored) issue read for in-place adoption (§8.29).

    The neutral shape :meth:`IssueBackend.read_issue` returns for *any* issue — not just perk's
    own plan/learn/objective issues. ``title``/``body`` are **untrusted human DATA** (the
    adoption seed wraps them in an ``<untrusted_adopted_issue>`` block). ``state`` is the
    normalized ``"OPEN" | "CLOSED"`` vocabulary (the contract's state discipline).
    ``already_plan`` is True when the issue already carries perk's plan metadata (wherever the
    backend stores it) — the adoption refusal's backend-honest presence check.
    ``already_objective`` is its objective-metadata twin (presence-only, tolerant): the
    wrong-kind adoption refusal's evidence (backend-populated for the same reason — on Linear
    the header rides an attachment the body cannot testify to).
    """

    id: str
    url: str
    title: str
    body: str
    state: str
    already_plan: bool = False
    already_objective: bool = False


class IssueBackend(Protocol):
    """The issue-tracking tier contract (one instance per repo; see the module docstring).

    All parameters are keyword-only. Mutations raise ``IssueBackendError``; lookups return
    ``... | None`` for not-found and raise on an infra failure. ``dry_run`` mutations validate +
    compose only — no backend writes.
    """

    # The backend's id in the `[issues] backend` vocabulary (e.g. "github"). Contract discipline:
    # stamped **verbatim** into `cache.plan-ref.provider`, so "the backend that wrote the issue is
    # the backend that gets stamped" is structurally true at every stamp site.
    backend_id: str

    # --- labels ---

    def ensure_label(
        self, name: str, *, color: str, description: str, dry_run: bool = False
    ) -> Label:
        """Idempotent create-if-missing for a label: an already-existing label is success
        (``created=False``). Raises ``IssueBackendError`` on an infra failure."""
        ...

    # --- plan issues ---

    def find_plan_issue(self, *, run_id: str) -> IssueRef | None:
        """Find the **open** plan issue whose plan-header ``run_id`` matches (the idempotency
        finder, scoped to the backend's plan-issue population). None for no match; raises on an
        infra/query failure (never masks the error as None)."""
        ...

    def create_plan_issue(
        self,
        *,
        title: str,
        header_fields: dict[str, object],
        run_id: str | None,
        dry_run: bool = False,
    ) -> IssueRef:
        """Create the plan issue carrying the plan-header ``header_fields``, stored wherever the
        backend keeps its header (GitHub renders the body metadata block; Linear upserts the
        plan attachment on an empty-description issue). Idempotent on ``run_id``
        (find-then-return, ``existed=True``). A dry run returns ``IssueRef(id="0",
        url="(dry-run)", existed=False)`` without touching the backend. Raises on failure."""
        ...

    def update_plan_issue(
        self, *, issue_id: str, title: str, body_comment: str, dry_run: bool = False
    ) -> PlanUpdate:
        """Upsert an existing plan issue in place (the idempotent re-save path): patch the
        plan-body comment with the revised markdown and the issue title from the (possibly
        revised) plan H1. Legacy issues missing the plan-body comment get a fresh comment posted
        (``body_updated=False``) so the plan body is never stranded."""
        ...

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> PlanHeaderUpdate:
        """Merge ``fields`` into the plan-header block and write it back. Rejects keys outside
        ``plan.PLAN_HEADER_FIELDS`` (LBYL on the schema). **Merge-only**: refuses to create a
        plan-header where none exists (plan-header creation is confined to
        :meth:`create_plan_issue`, :meth:`adopt_issue_as_plan` (§8.29), and the Linear node-plan
        unification writer ``save_node_plan``). A dry run validates + composes only — and must
        refuse a would-fail write."""
        ...

    def prepend_plan_callout(
        self, *, issue_id: str, callout: str, command: str, dry_run: bool = False
    ) -> bool:
        """Read the plan issue's current description, idempotently prepend ``callout`` above it
        (via :func:`perk.plan.prepend_callout`, keyed on the literal ``command`` string), and
        write it back. Returns ``True`` when a write occurred, ``False`` when the callout was
        already present (idempotent) or on a ``dry_run``. Raises ``IssueBackendError`` on an
        infra failure."""
        ...

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        """Read a plan issue's observable state (header + PR). The PR is resolved from the
        header's ``pr`` field via the (GitHub-universal) PR tier — legitimate for every backend.
        ``state`` is normalized to ``"OPEN"``/``"CLOSED"``. The ``has_plan_header``/
        ``has_objective_header`` flags are presence-only kind evidence from the backend's own
        storage (body metadata blocks on GitHub, perk attachments on Linear) — never a payload
        decode. None still means the issue does not exist, nothing else; raises on an infra
        failure."""
        ...

    def get_plan_body(self, *, issue_id: str) -> str | None:
        """Fetch a plan issue's verbatim plan-body block markdown, wherever the backend stores
        it. None when the issue or block is absent; raises on an infra failure."""
        ...

    # --- in-place issue adoption (§8.29) ---

    def read_issue(self, *, issue_id: str) -> AdoptableIssue | None:
        """Read *any* issue's raw title + body + normalized state for in-place adoption.

        Unlike :meth:`get_plan` (needs a ``plan-header``) / :meth:`get_plan_body` (needs a
        ``plan-body`` block), this reads a **non-perk** human issue verbatim. ``title``/``body``
        are untrusted human DATA. ``None`` when the issue does not exist; raises
        ``IssueBackendError`` on an infra failure.
        """
        ...

    def adopt_issue_as_plan(
        self,
        *,
        issue_id: str,
        header_fields: dict[str, object],
        plan_markdown: str,
        callout: str,
        command: str,
        dry_run: bool = False,
    ) -> IssueRef:
        """Stamp perk's plan metadata **additively** into a pre-existing issue — adopting it IN
        PLACE as a perk plan (§8.29), never minting a second object.

        The additive stamp (mirrors the node-unification in-place writer): (a) ensure + **add**
        the ``perk:plan`` label to the existing issue (never replaces its labels); (b) stamp the
        ``plan-header`` block additively into the issue **body** (human prose preserved verbatim,
        **title untouched**); (c) idempotently prepend the ``callout`` (keyed on ``command``)
        above the body; (d) upsert the ``plan-body`` comment carrying ``plan_markdown``. Returns
        ``IssueRef(existed=True)``. Idempotent on re-save (header re-rendered in place;
        callout/label idempotent). ``dry_run`` validates + composes only — no backend writes.
        """
        ...

    # --- learn issues ---

    def find_learn_issue(self, *, run_id: str) -> IssueRef | None:
        """Find the **open** learn issue whose learn-header ``run_id`` matches — scoped so it
        never returns the plan issue (which shares the plan's ``run_id``). None for no match;
        raises on an infra failure."""
        ...

    def create_learn_issue(
        self,
        *,
        title: str,
        body: str,
        run_id: str | None,
        plan_id: str,
        decision: str | None = None,
        target: str | None = None,
        dry_run: bool = False,
    ) -> IssueRef:
        """Create the knowledge-capture (learn) issue. Idempotent via ``find_learn_issue``;
        renders the learn-header (``run_id``/``created``/``plan``, plus the optional captured
        ``decision``/``target`` classification — contracts.md §8.35) into the body so the finder
        can match. Raises on failure."""
        ...

    def list_learn_issues(self) -> tuple[LearnIssueSummary, ...]:
        """Every open ``perk:learn`` issue (the learn-docs factory inbox). Raises on an
        infra/query failure (never masks it as an empty tuple)."""
        ...

    def list_plan_completion_candidates(self) -> tuple[PlanSummary, ...]:
        """The **open** plan population as a bounded completion/browse read — never an
        exhaustive census: ONE backend page per underlying query (GitHub: the list endpoint's
        default page, ~30 rows; Linear: a single ``first: 50`` request per query — no cursor
        pagination), sorted newest-created-first **within the fetched page(s)**; membership
        beyond the page is explicitly not promised. Raises on an infra failure (never masks it
        as an empty tuple — the completion callback owns the swallow). Performs no ``io_step``
        narration (stderr output would garble a TAB completion)."""
        ...

    def list_plans_pending_learn(self, *, limit: int = 50) -> tuple[PendingLearnPlan, ...]:
        """The closed plan issues still awaiting /learn: label-scoped to the backend's
        plan population, terminal-state only, filtered to plan-header
        ``learn_state: pending``. ``limit`` bounds the scan to the most recently
        updated closed plans (the pending stamp lands at close time, so pending plans
        sort early). Ordered most-recently-closed first. Raises on an infra/query
        failure (never masks it as an empty tuple)."""
        ...

    # --- gist issues (§8.41) ---

    def find_gist_issue(self, *, run_id: str) -> IssueRef | None:
        """Find the **open** gist issue whose gist-header ``run_id`` matches — label + header-key
        scoped so it never returns a plan/learn issue. None for no match; raises on an infra
        failure."""
        ...

    def create_gist_issue(
        self,
        *,
        title: str,
        body: str,
        run_id: str | None,
        scope: str,
        dry_run: bool = False,
    ) -> IssueRef:
        """Create the gist issue (a rough statement of intent — contracts.md §8.41). Idempotent
        via ``find_gist_issue``; stamps ``scope`` into the gist-header (``run_id``/``created``/
        ``scope``), stored wherever the backend keeps its metadata (GitHub renders the body
        block; Linear upserts the gist attachment). Raises on failure."""
        ...

    def list_gist_issues(self) -> tuple[GistSummary, ...]:
        """Every **open** ``perk:gist`` issue (the ``perk gist list`` backlog view), with the
        stored ``scope`` and the ``adopted`` detection (the backend's own storage carries plan or
        objective metadata for the same object). Raises on an infra/query failure (never masks
        it as an empty tuple)."""
        ...

    def close_and_label_consolidated(self, *, issue_id: str, dry_run: bool = False) -> bool:
        """Mark a consumed learn issue consolidated: add the ``perk:consolidated`` label
        (additively) and move the issue to the backend's terminal/done state. Idempotent:
        re-closing/re-labelling an already-consolidated issue is success. Returns True on
        success; raises on an infra failure."""
        ...

    # --- generic issue ops ---

    def close_issue(self, *, issue_id: str, dry_run: bool = False) -> bool:
        """Move an issue to the backend's terminal/done state. **Fail-loud**: raises
        ``IssueBackendError`` on an infra failure rather than swallowing it. Idempotent:
        re-closing an already-closed issue is success. ``dry_run`` returns False with no side
        effects."""
        ...

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> CommentResult:
        """Post a comment on an issue. Raises on failure."""
        ...

    def find_comment_id_by_marker(self, *, issue_id: str, marker: str) -> str | None:
        """Find the id of the first comment on the issue whose body contains ``marker``. The
        returned id MUST be usable for the backend's comment-update op. None when no comment
        matches; raises on an infra failure."""
        ...

    def upsert_marked_comment(
        self, *, issue_id: str, marker: str, body: str, dry_run: bool = False
    ) -> CommentResult:
        """Post-or-patch a single marker-keyed comment (idempotent on ``marker``): patch the
        existing comment when found, else post a fresh one. ``body`` MUST already embed
        ``marker`` (the caller's responsibility) so the next upsert can find it — lets a single
        comment evolve in place rather than spamming the issue. ``posted=False`` on a dry run;
        raises on an infra failure."""
        ...

    # --- human-engagement reads ---
    #
    # All returned content (`body`/`diff`/activity `body`) is **untrusted DATA**: never re-parsed
    # as a perk marker outside perk's own owned regions, never executed as instructions. Author
    # identity (human/perk/other-agent/unknown) is distinguishable (see
    # ``perk.backends.engagement.classify_author``). Honest on ``LinearIssueBackend``;
    # ``GitHubIssueBackend`` ships a clean empty impl.

    def read_comments(self, *, issue_id: str) -> tuple[EngagementComment, ...]:
        """Read an issue's comments with author identity + edit flag. Oldest-first. Raises
        ``IssueBackendError`` on an infra failure; an empty issue yields ``()``."""
        ...

    def read_description_edits(self, *, issue_id: str) -> tuple[DescriptionEdit, ...]:
        """Read an issue's description/body edit events (who edited, when). ``diff`` is best-effort
        and may be ``None``. Raises on an infra failure; no edits yields ``()``."""
        ...

    def read_agent_session(self, *, issue_id: str) -> AgentSessionRead:
        """Read the issue's agent-session activities + the derived stop indicator. A backend with
        no agent-session surface (or a missing session) returns the empty
        ``AgentSessionRead``; **raises** on an infra/auth failure (never masks it)."""
        ...
