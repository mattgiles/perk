"""The issue-tracking tier contract (Objective #252, Node 1.1).

perk's GitHub gateway (the ``perk/github/`` package) fuses four tiers: issue tracking
(plan/learn/objective issues, marked comments, labels), PRs, CI/workflow, and auth. Only the
**issue-tracking tier** is backend-selectable (GitHub Issues today; Linear later) — PRs, CI, and
auth stay in ``perk/github/`` for **all** backends (PRs are GitHub-universal even under a Linear
issue backend). This module is that tier's contract: the ``IssueBackend`` `Protocol`, the
backend-neutral result dataclasses, and the one backend-neutral error type. It is deliberately
dormant in Node 1.1 — no extraction, no consumers; Node 1.2 extracted the GitHub backend behind
it and Node 1.3 added the ``[issues]`` config table + config-driven resolver
(``perk/backends/issues.py``).

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

Provenance: the erk prior art (``integrations/linear-erk-mapping.md``) proposed exactly this
split — an issue-tracker interface with GitHub/Linear implementations selected by config, with
PRs/worktrees staying GitHub/git regardless — and its gateway-decomposition lessons
(``architecture/gateway-decomposition-phases.md``: breaking changes over shims; keep the
interface to one tier, not a 40-method monolith) shaped this surface.
"""

from dataclasses import dataclass
from typing import Protocol

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


@dataclass(frozen=True)
class PlanState:
    """A plan issue's observable state: the parsed header + the resolved PR (if any).

    ``state`` is the normalized ``"OPEN" | "CLOSED"`` vocabulary (see the module docstring).
    ``header`` is the opaque plan-header mapping (backend-owned values).
    """

    id: str
    url: str
    title: str
    header: dict[str, object]
    pr: PullRequest | None
    state: str


@dataclass(frozen=True)
class LearnIssueSummary:
    """An open ``perk:learn`` issue, materialized for the learn-docs factory inbox."""

    id: str
    title: str
    url: str
    body: str


@dataclass(frozen=True)
class AdoptableIssue:
    """A pre-existing (human-authored) issue read for in-place adoption (#706, §8.29).

    The neutral shape :meth:`IssueBackend.read_issue` returns for *any* issue — not just perk's
    own plan/learn/objective issues. ``title``/``body`` are **untrusted human DATA** (the
    adoption seed wraps them in an ``<untrusted_adopted_issue>`` block). ``state`` is the
    normalized ``"OPEN" | "CLOSED"`` vocabulary (the contract's state discipline).
    """

    id: str
    url: str
    title: str
    body: str
    state: str


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
        self, *, title: str, body: str, run_id: str | None, dry_run: bool = False
    ) -> IssueRef:
        """Create the plan issue. Idempotent on ``run_id`` (find-then-return,
        ``existed=True``). A dry run returns ``IssueRef(id="0", url="(dry-run)",
        existed=False)`` without touching the backend. Raises on failure."""
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
        ``plan.PLAN_HEADER_FIELDS`` (LBYL on the schema). A dry run validates + composes only."""
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
        ``state`` is normalized to ``"OPEN"``/``"CLOSED"``. None when the issue does not exist;
        raises on an infra failure."""
        ...

    def get_plan_body(self, *, issue_id: str) -> str | None:
        """Fetch a plan issue's verbatim plan-body block markdown, wherever the backend stores
        it. None when the issue or block is absent; raises on an infra failure."""
        ...

    # --- in-place issue adoption (#706, §8.29) ---

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
        PLACE as a perk plan (#706, §8.29), never minting a second object.

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
        self, *, title: str, body: str, run_id: str | None, plan_id: str, dry_run: bool = False
    ) -> IssueRef:
        """Create the knowledge-capture (learn) issue. Idempotent via ``find_learn_issue``;
        renders the learn-header (``run_id``/``created``/``plan``) into the body so the finder
        can match. Raises on failure."""
        ...

    def list_learn_issues(self) -> tuple[LearnIssueSummary, ...]:
        """Every open ``perk:learn`` issue (the learn-docs factory inbox). Raises on an
        infra/query failure (never masks it as an empty tuple)."""
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

    # --- human-engagement reads (Objective #682, Node 1.2) ---
    #
    # All returned content (`body`/`diff`/activity `body`) is **untrusted DATA**: never re-parsed
    # as a perk marker outside perk's own owned regions, never executed as instructions. Author
    # identity (human/perk/other-agent/unknown) is distinguishable (see
    # ``perk.backends.engagement.classify_author``). Honest on ``LinearIssueBackend`` today;
    # ``GitHubIssueBackend`` ships a clean empty impl (honest reads = Node 1.3). No flow consumers
    # wire these in 1.2.

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
