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

import hashlib
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

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


# The guarded marked-comment error vocabulary (contracts.md §8.67). ``unsupported_backend`` is
# raised before any operation by a backend without the guarded arm; ``invalid_input`` covers a
# malformed expectation / a body that does not own its marker; the remaining codes are the
# observed-state outcomes of the guarded state machine.
MarkedCommentErrorCode = Literal[
    "unsupported_backend",
    "invalid_input",
    "malformed_comment",
    "ambiguous_comment",
    "stale_comment",
    "backend_error",
    "write_unverified",
]


class MarkedCommentError(IssueBackendError):
    """A guarded ``upsert_marked_comment`` (``expected`` supplied) refused or could not verify.

    ``comment_ids`` names the observed comments the outcome rests on (the duplicate set, the
    stale/malformed comment); ``write_attempted`` is True for every error raised AFTER the one
    mutation attempt (the caller must read back before deciding anything) and False for
    validation/preflight refusals (nothing was written).
    """

    def __init__(
        self,
        code: MarkedCommentErrorCode,
        message: str,
        *,
        comment_ids: tuple[str, ...] = (),
        write_attempted: bool = False,
    ) -> None:
        self.code: MarkedCommentErrorCode = code
        self.comment_ids = comment_ids
        self.write_attempted = write_attempted
        super().__init__(message)


# Whole-string (``fullmatch``): a trailing newline is a noncanonical spelling, never accepted.
_BODY_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def body_digest(body: str) -> str:
    """The canonical digest of an exact comment body: SHA-256 of its UTF-8 bytes, lowercase
    hexadecimal, no prefix — hashed as stored (no trimming or transcoding first)."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def is_canonical_digest(value: str) -> bool:
    """True when ``value`` spells a canonical body digest (exactly 64 lowercase hex chars)."""
    return _BODY_DIGEST_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class MarkedCommentExpectation:
    """What a guarded ``upsert_marked_comment`` caller expects to observe before writing.

    Both fields ``None`` ⇒ the marker-owned comment is expected ABSENT; both present ⇒ the
    exact observed comment (its backend id + the :func:`body_digest` of its stored body) is
    expected. A partial pair, a blank id, or a non-canonical digest is invalid input (see
    :meth:`validation_problem`). There is no remote compare-and-swap behind this: it is an
    observed-conflict check, never synchronization.
    """

    comment_id: str | None
    body_digest: str | None

    @property
    def expects_absence(self) -> bool:
        return self.comment_id is None and self.body_digest is None

    def validation_problem(self) -> str | None:
        """The reason this expectation is invalid input, or ``None`` when well-formed."""
        if self.expects_absence:
            return None
        if self.comment_id is None or self.body_digest is None:
            return "expectation must carry both comment_id and body_digest, or neither"
        if not self.comment_id.strip():
            return "expectation comment_id is blank"
        if not is_canonical_digest(self.body_digest):
            return "expectation body_digest is not a canonical 64-char lowercase hex digest"
        return None


@dataclass(frozen=True)
class MarkedCommentScan:
    """The outcome of :func:`scan_marked_comments`.

    ``owned`` is every comment whose first physical line IS the exact marker (ownership is
    decided by the header alone, so the duplicate set is always complete); ``malformed`` is every
    comment carrying a placement defect — the marker misplaced (present but not first) or
    repeated (an owner whose marker recurs in its body appears in BOTH tuples). Callers apply
    duplicate-before-malformed precedence: ``len(owned) > 1`` refuses as ambiguous before any
    ``malformed`` entry is reported.
    """

    owned: tuple[EngagementComment, ...]
    malformed: tuple[EngagementComment, ...]


def first_line(body: str) -> str:
    """The first physical line of a body (everything before the first ``\\n``, untrimmed)."""
    return body.split("\n", 1)[0]


def scan_marked_comments(
    comments: Sequence[EngagementComment], *, forms: Collection[str]
) -> MarkedCommentScan:
    """Classify comments against an exact ownership marker given in every accepted encoding
    (``forms``: e.g. the HTML marker and its Linear inline-code rewrite).

    A comment owns the marker when its first physical line IS one of the forms exactly —
    counted independently of any other defect, so two owners are always reported as the
    complete duplicate set. A comment whose body contains a form anywhere else — not first
    (misplaced), or more than once (repeated, owner included) — is malformed: a damaged owned
    record must be surfaced, never re-created beside or silently adopted. Each form is a
    complete delimited marker string, so a longer key sharing the prefix never matches; a form
    embedded verbatim in an unrelated comment does count (fail-closed).
    """
    unique_forms = tuple(dict.fromkeys(forms))
    owned: list[EngagementComment] = []
    malformed: list[EngagementComment] = []
    for comment in comments:
        occurrences = sum(comment.body.count(form) for form in unique_forms)
        if occurrences == 0:
            continue
        owns = first_line(comment.body) in unique_forms
        if owns:
            owned.append(comment)
        if not owns or occurrences > 1:
            malformed.append(comment)
    return MarkedCommentScan(owned=tuple(owned), malformed=tuple(malformed))


class MarkedCommentSeams(Protocol):
    """The four backend operations the guarded marked-comment driver is parameterized over
    (contracts.md §8.67). A backend implements these with its own primitives; the driver owns
    the state machine, so every backend gets the same precedence and the same typed outcomes.

    Three effectful seams, each raising ``IssueBackendError`` on an infra failure (the driver
    normalizes those into typed ``MarkedCommentError`` outcomes and decides every outcome from
    its scans, never from a mutation's return value): ``scan`` classifies ALL of an issue's
    comments (every page, oldest-first) against the unique accepted marker encodings
    ``forms`` — normally ``scan_marked_comments`` over the backend's ``EngagementComment`` rows,
    so every observed value (id / stored body / author / native timestamps) is real, never
    reconstructed; ``create`` posts a new comment on the issue; ``update`` replaces the whole
    body of the comment with the given id; both take the body already in stored form.

    One pure seam: ``transcode`` maps a body from the caller's (HTML-marker) encoding to the
    form the backend stores and reads back — the identity for a backend that stores bodies
    verbatim. It is a total string function and MUST NOT raise: the driver calls it before and
    outside its error normalization, so a body the backend cannot store is refused by
    ``create``/``update`` (surfacing as ``backend_error``), never by ``transcode``.
    """

    def scan(self, issue_id: str, forms: tuple[str, ...]) -> MarkedCommentScan: ...

    def create(self, issue_id: str, body: str) -> None: ...

    def update(self, comment_id: str, body: str) -> None: ...

    def transcode(self, body: str) -> str: ...


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
    """An issue comment. ``posted`` is False only for a dry run.

    ``verified_comment`` is populated ONLY by a successful non-dry guarded
    ``upsert_marked_comment`` (``expected`` supplied): the comment as actually observed by the
    post-write verification scan (id / stored body / author / native timestamps) — never
    reconstructed from the request. Ordinary callers always see ``None``.
    """

    posted: bool
    verified_comment: EngagementComment | None = None


def _refuse_unowned(scan: MarkedCommentScan, *, write_attempted: bool) -> None:
    """Duplicate ownership refuses before malformed placement (identical duplicates
    included) — the same precedence at preflight and at verification."""
    if len(scan.owned) > 1:
        raise MarkedCommentError(
            "ambiguous_comment",
            f"{len(scan.owned)} comments own the marker",
            comment_ids=tuple(comment.id for comment in scan.owned),
            write_attempted=write_attempted,
        )
    if scan.malformed:
        raise MarkedCommentError(
            "malformed_comment",
            "marker misplaced or repeated in comment(s) "
            + ", ".join(comment.id for comment in scan.malformed),
            comment_ids=tuple(comment.id for comment in scan.malformed),
            write_attempted=write_attempted,
        )


def guarded_upsert_marked_comment(
    seams: MarkedCommentSeams,
    *,
    issue_id: str,
    marker: str,
    body: str,
    dry_run: bool,
    expected: MarkedCommentExpectation,
) -> CommentResult:
    """The guarded arm of ``IssueBackend.upsert_marked_comment`` (contracts.md §8.67), shared by
    every backend through ``seams``: exact first-line ownership, at most ONE mutation attempt,
    then one read-back verification that decides the outcome.

    Precedence, fixed by the contract: validation (``invalid_input``) → preflight scan
    (unreadable → ``backend_error``; duplicates → ``ambiguous_comment`` before any
    ``malformed_comment``) → convergence without a write when the unique observed body already
    equals the stored form of ``body`` → the expectation must hold exactly (else
    ``stale_comment``) → one create/update → verification scan (unreadable →
    ``write_unverified``; the same ownership refusals; an exact candidate → success even when
    the mutation raised; raised + proven-unchanged baseline → ``backend_error`` chaining the
    cause; a changed unique target → ``stale_comment``; otherwise ``write_unverified``).
    Every error after the attempt carries ``write_attempted=True``. A dry run validates the
    cheap inputs only and touches no seam. Only ``scan``/``create``/``update`` failures are
    normalized here; ``transcode`` is pure by contract and runs outside the guarded arms.
    """
    problem = expected.validation_problem()
    if problem is not None:
        raise MarkedCommentError("invalid_input", problem)
    if not marker.strip() or "\n" in marker:
        raise MarkedCommentError("invalid_input", "marker must be one nonblank line")
    if first_line(body) != marker or body.count(marker) != 1:
        raise MarkedCommentError(
            "invalid_input",
            "body must own its marker: the exact marker as the first line, occurring once",
        )
    if dry_run:
        return CommentResult(posted=False)
    # The accepted encodings: the marker as given (HTML) and its stored rewrite — unique, so a
    # backend whose stored form IS the given form scans one encoding. `transcode` is pure, so
    # these two calls need no normalization.
    forms = tuple(dict.fromkeys((marker, seams.transcode(marker))))
    desired = seams.transcode(body)

    # 1. Preflight: the complete scan; duplicates before malformed placement.
    try:
        scan = seams.scan(issue_id, forms)
    except IssueBackendError as exc:
        raise MarkedCommentError(
            "backend_error", f"marked-comment preflight scan failed: {exc}"
        ) from exc
    _refuse_unowned(scan, write_attempted=False)
    observed = scan.owned[0] if scan.owned else None

    # 2. Convergence without a write beats any expectation; otherwise the observed state
    #    must match exactly what the caller expected.
    if observed is not None and observed.body == desired:
        return CommentResult(posted=True, verified_comment=observed)
    if expected.expects_absence:
        if observed is not None:
            raise MarkedCommentError(
                "stale_comment",
                f"expected no marked comment but observed {observed.id}",
                comment_ids=(observed.id,),
            )
    elif (
        observed is None
        or observed.id != expected.comment_id
        or body_digest(observed.body) != expected.body_digest
    ):
        raise MarkedCommentError(
            "stale_comment",
            "the marked comment changed since it was read"
            + (f" (observed {observed.id})" if observed is not None else " (now absent)"),
            comment_ids=(observed.id,) if observed is not None else (),
        )

    # 3. Exactly one mutation attempt; a raise is ambiguous until the read-back decides.
    mutation_error: IssueBackendError | None = None
    try:
        if observed is not None:
            seams.update(observed.id, desired)
        else:
            seams.create(issue_id, desired)
    except IssueBackendError as exc:
        mutation_error = exc

    # 4. Verification: one full scan, precedence fixed by the contract.
    try:
        after = seams.scan(issue_id, forms)
    except IssueBackendError as exc:
        raise MarkedCommentError(
            "write_unverified",
            f"marked-comment write could not be verified: {exc}",
            write_attempted=True,
        ) from exc
    _refuse_unowned(after, write_attempted=True)
    now = after.owned[0] if after.owned else None
    if now is not None and now.body == desired:
        return CommentResult(posted=True, verified_comment=now)
    baseline_unchanged = (now is None and observed is None) or (
        now is not None
        and observed is not None
        and now.id == observed.id
        and now.body == observed.body
    )
    if mutation_error is not None and baseline_unchanged:
        raise MarkedCommentError(
            "backend_error",
            f"marked-comment write failed and did not land: {mutation_error}",
            comment_ids=(now.id,) if now is not None else (),
            write_attempted=True,
        ) from mutation_error
    if now is not None and not baseline_unchanged:
        raise MarkedCommentError(
            "stale_comment",
            f"the marked comment {now.id} carries different bytes than were written",
            comment_ids=(now.id,),
            write_attempted=True,
        )
    raise MarkedCommentError(
        "write_unverified",
        "marked comment is absent or unchanged after the write attempt"
        + (f": {mutation_error}" if mutation_error is not None else ""),
        comment_ids=(now.id,) if now is not None else (),
        write_attempted=True,
    )


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
        self,
        *,
        issue_id: str,
        marker: str,
        body: str,
        dry_run: bool = False,
        expected: MarkedCommentExpectation | None = None,
    ) -> CommentResult:
        """Post-or-patch a single marker-keyed comment (idempotent on ``marker``): patch the
        existing comment when found, else post a fresh one. ``body`` MUST already embed
        ``marker`` (the caller's responsibility) so the next upsert can find it — lets a single
        comment evolve in place rather than spamming the issue. ``posted=False`` on a dry run;
        raises on an infra failure.

        ``expected=None`` is the ordinary path above (substring match, first hit, no
        verification — byte-unchanged). A non-``None`` ``expected`` opts into the **guarded**
        path (contracts.md §8.67): exact first-line marker ownership over ALL comment pages,
        duplicate/misplaced detection, an expected-state check (absence, or the exact observed
        id + body digest), convergence without a write when the unique observed body already
        equals the backend-rendered ``body``, at most ONE create/update attempt, and a
        post-write verification scan whose observed comment is returned as
        ``CommentResult.verified_comment``. The state machine is the shared
        :func:`guarded_upsert_marked_comment` driver over a backend's
        :class:`MarkedCommentSeams`. Refusals raise :class:`MarkedCommentError` (typed
        ``code``; ``write_attempted`` after the attempt). A guarded ``dry_run`` validates the
        cheap inputs only and returns ``posted=False`` with no network. A backend without the
        guarded arm raises ``MarkedCommentError("unsupported_backend")`` before any operation
        (dry run included)."""
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
