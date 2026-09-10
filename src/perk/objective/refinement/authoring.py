"""Objective-node refinement — the authoring boundary (contracts.md §8.67).

The Phase-1 leaf (`models`/`codec`/`service`) knows how to read, select, and save ONE
refinement. This module is the layer the public doors stand on: it PREPARES the grounding
context an authoring session works from, SERIALIZES that context into the one fixed transfer
artifact both planes share, and CONVERTS a returned working draft back into the frozen save
request the service accepts. It never launches, never touches Pi, never writes a comment itself.

Byte ownership (the transport contract): **Python is the sole context serializer**.
:func:`serialize_context` builds the explicit JSON-shaped mapping from validated fields and
spells it with the codec's canonical JSON (sorted keys recursively, ``(",", ":")`` separators,
``ensure_ascii=True``) plus exactly one trailing LF. The whole string — final LF included — is
``context_json``; its handoff digest is ``sha256:<lowercase hex>`` over exactly those UTF-8
bytes. The TypeScript plane validates that digest, decodes the string strictly for use, and
writes the UNCHANGED raw string as the session artifact; at save time this module parses the
transferred artifact strictly without reserializing or trimming anything. The draft artifact is
serialized by TypeScript alone (``schema_version``, ``run_id``, ``context_digest``, ``markdown``
in that order, compact ``JSON.stringify`` + LF) and parsed here without touching the Markdown.

Trust posture: every parse goes through ``StrictInputModel`` boundary models (unknown fields,
coercions, and malformed scalars refuse) and then the codec's content validators — a context
that fails any rule is ``refinement_context_invalid``, never a partial success. The stored
comment parser (lenient, ``LenientParseModel``) is deliberately NOT reused here.

Provenance is a **capture-time observation**, not a code-freshness gate (§8.67): HEAD plus a
dirty flag plus the UTC capture time, taken once at the start of the authoring pass and preserved
verbatim through every rewrite and save. It neither identifies uncommitted bytes nor detects
later checkout changes.
"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from perk import plan
from perk.backends import resolve
from perk.backends.engagement import render_node_engagement
from perk.backends.issue_backend import MarkedCommentExpectation, is_canonical_digest
from perk.backends.objective_store import ObjectiveStore, ObjectiveStoreError
from perk.boundary import StrictInputModel, StrTuple, ValidationError
from perk.objective._models import NodeStatus
from perk.objective.refinement import codec, service
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementDocument,
    RefinementError,
    RefinementErrorCode,
    RefinementIdentity,
    RefinementProvenance,
    RefinementRead,
    RefinementSaveRequest,
    RefinementSource,
    RefinementTarget,
    SavedRefinement,
)
from perk.state import cache
from perk.substrate import git
from perk.substrate.git import GitError

# The transfer artifacts' schema version (an integer, like the TS draft artifacts' — distinct
# from the stored comment header's string ``"1"``).
ARTIFACT_SCHEMA_VERSION = 1

# The two fixed session-data artifact names (contracts.md §8.67). The context is written by the
# cold door into run scratch under this SAME name and imported by the interior as a session
# artifact under it; the draft is written only by the interior.
CONTEXT_ARTIFACT = "objective-refinement-context.json"
DRAFT_ARTIFACT = "objective-refinement-draft.json"

# The registry stage the refinement doors act on.
REFINE_STAGE_ID = "objective-refine"

_DIGEST_PREFIX = "sha256:"


class AuthoringErrorCode(StrEnum):
    """The authoring boundary's own error vocabulary (the service's codes pass through)."""

    CONTEXT_MISSING = "refinement_context_missing"
    CONTEXT_INVALID = "refinement_context_invalid"
    DRAFT_MISSING = "refinement_draft_missing"
    DRAFT_INVALID = "refinement_draft_invalid"
    BINDING_MISMATCH = "refinement_binding_mismatch"


class RefinementAuthoringError(Exception):
    """A context/draft transfer refused, with a typed ``code``. Never wraps a service error —
    those propagate as :class:`RefinementError` unchanged."""

    def __init__(self, code: AuthoringErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


# ------------------------------------------------------------------ the frozen context types


@dataclass(frozen=True)
class RefinementObjective:
    """The objective's addressing facts for the session (never part of any identity hash)."""

    id: str
    title: str
    url: str


@dataclass(frozen=True)
class PriorRefinement:
    """The FULL prior refinement on the selected target (re-refinement evidence): its complete
    Markdown, the source digest it was authored against, its original provenance, and the
    backend's observed last-write time — never the bounded human preview."""

    markdown: str
    source_digest: str
    provenance: RefinementProvenance
    saved_at: str


@dataclass(frozen=True)
class RefinementContext:
    """One grounding pass: the selected target as read, the guarded-save expectation that read
    established, the capture-time provenance, the objective's addressing facts, the full prior
    record (or ``None``), the bounded rendered node engagement, and the visible warnings."""

    run_id: str
    target: RefinementTarget
    expected: MarkedCommentExpectation
    provenance: RefinementProvenance
    objective: RefinementObjective
    prior: PriorRefinement | None
    engagement: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RefinementDraft:
    """The interior's working draft as transferred back: bound to one run and one exact
    context digest; the Markdown is the model's only contribution."""

    run_id: str
    context_digest: str
    markdown: str


@dataclass(frozen=True)
class PreparedContext:
    """A prepared context together with its exact serialized bytes and their digest — the
    triple every door hands on, so nothing downstream serializes the context a second time."""

    context: RefinementContext
    context_json: str
    context_digest: str


# ------------------------------------------------------------------ serialization


def _identity_mapping(identity: RefinementIdentity) -> dict[str, object]:
    return {
        "backend": identity.backend,
        "objective_id": identity.objective_id,
        "objective_run_id": identity.objective_run_id,
        "node_id": identity.node_id,
        "carrier_id": identity.carrier_id,
    }


def _source_mapping(source: RefinementSource) -> dict[str, object]:
    return {
        "description": source.description,
        "slug": source.slug,
        "comment": source.comment,
        "depends_on": None if source.depends_on is None else list(source.depends_on),
        "effective_depends_on": list(source.effective_depends_on),
        "issue_description": source.issue_description,
    }


def _provenance_mapping(provenance: RefinementProvenance) -> dict[str, object]:
    return {
        "authoring_run_id": provenance.authoring_run_id,
        "authored_at": provenance.authored_at,
        "code_basis": {
            "head_sha": provenance.code_basis.head_sha,
            "dirty": provenance.code_basis.dirty,
            "captured_at": provenance.code_basis.captured_at,
        },
    }


def _target_mapping(target: RefinementTarget) -> dict[str, object]:
    return {
        "identity": _identity_mapping(target.identity),
        "source": _source_mapping(target.source),
        "source_digest": target.source_digest,
        "carrier_identifier": target.carrier_identifier,
        "carrier_url": target.carrier_url,
        "status": target.status.value,
        "plan_ref": target.plan_ref,
        "has_plan_metadata": target.has_plan_metadata,
    }


def context_mapping(context: RefinementContext) -> dict[str, object]:
    """The explicit JSON-shaped mapping of a context (tuples → lists, required nulls retained).
    Exactly the fields §8.67 fixes for ``objective-refinement-context.json``."""
    prior = context.prior
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "run_id": context.run_id,
        "target": _target_mapping(context.target),
        "expected": {
            "comment_id": context.expected.comment_id,
            "body_digest": context.expected.body_digest,
        },
        "provenance": _provenance_mapping(context.provenance),
        "objective": {
            "id": context.objective.id,
            "title": context.objective.title,
            "url": context.objective.url,
        },
        "prior": None
        if prior is None
        else {
            "markdown": prior.markdown,
            "source_digest": prior.source_digest,
            "provenance": _provenance_mapping(prior.provenance),
            "saved_at": prior.saved_at,
        },
        "engagement": context.engagement,
        "warnings": list(context.warnings),
    }


def serialize_context(context: RefinementContext) -> str:
    """The ONE context serialization: the codec's canonical JSON of :func:`context_mapping` plus
    exactly one trailing LF. The whole returned string is the transferred artifact."""
    return codec.canonical_json(context_mapping(context)) + "\n"


def artifact_digest(text: str) -> str:
    """``sha256:<lowercase hex>`` over the exact UTF-8 bytes of ``text`` — the session-data digest
    convention (prefixed), distinct from the codec's bare-hex remote digests."""
    return _DIGEST_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_artifact_digest(value: str) -> bool:
    """True for exactly ``sha256:`` + 64 lowercase hex chars."""
    return (
        value.startswith(_DIGEST_PREFIX)
        and len(value) == len(_DIGEST_PREFIX) + 64
        and is_canonical_digest(value[len(_DIGEST_PREFIX) :])
    )


def prepared(context: RefinementContext) -> PreparedContext:
    """Serialize once and digest those exact bytes."""
    context_json = serialize_context(context)
    return PreparedContext(
        context=context, context_json=context_json, context_digest=artifact_digest(context_json)
    )


# ------------------------------------------------------------------ strict parse boundary


class _IdentityIn(StrictInputModel):
    backend: str
    objective_id: str
    objective_run_id: str
    node_id: str
    carrier_id: str


class _SourceIn(StrictInputModel):
    description: str
    slug: str | None
    comment: str | None
    depends_on: StrTuple | None
    effective_depends_on: StrTuple
    issue_description: str


class _CodeBasisIn(StrictInputModel):
    head_sha: str
    dirty: bool
    captured_at: str


class _ProvenanceIn(StrictInputModel):
    authoring_run_id: str
    authored_at: str
    code_basis: _CodeBasisIn

    def to_domain(self) -> RefinementProvenance:
        return RefinementProvenance(
            authoring_run_id=self.authoring_run_id,
            authored_at=self.authored_at,
            code_basis=RefinementCodeBasis(
                head_sha=self.code_basis.head_sha,
                dirty=self.code_basis.dirty,
                captured_at=self.code_basis.captured_at,
            ),
        )


class _TargetIn(StrictInputModel):
    identity: _IdentityIn
    source: _SourceIn
    source_digest: str
    carrier_identifier: str
    carrier_url: str
    status: str
    plan_ref: str | None
    has_plan_metadata: bool


class _ExpectedIn(StrictInputModel):
    comment_id: str | None
    body_digest: str | None


class _ObjectiveIn(StrictInputModel):
    id: str
    title: str
    url: str


class _PriorIn(StrictInputModel):
    markdown: str
    source_digest: str
    provenance: _ProvenanceIn
    saved_at: str


class _ContextIn(StrictInputModel):
    schema_version: int
    run_id: str
    target: _TargetIn
    expected: _ExpectedIn
    provenance: _ProvenanceIn
    objective: _ObjectiveIn
    prior: _PriorIn | None
    engagement: str
    warnings: StrTuple


class _DraftIn(StrictInputModel):
    schema_version: int
    run_id: str
    context_digest: str
    markdown: str


def _load_json_object(text: str, what: str, code: AuthoringErrorCode) -> dict[str, object]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RefinementAuthoringError(code, f"{what} is not valid JSON ({exc.msg})") from exc
    if not isinstance(raw, dict):
        raise RefinementAuthoringError(code, f"{what} is not a JSON object")
    return raw


def _target_findings(target: RefinementTarget) -> list[str]:
    findings = codec.identity_findings(target.identity)
    findings += codec.source_findings(target.source)
    if not is_canonical_digest(target.source_digest):
        findings.append("target.source_digest is not a canonical 64-char lowercase hex digest")
    elif target.source_digest != codec.source_digest(target.source):
        findings.append("target.source_digest does not match the target source")
    if not target.carrier_identifier.strip():
        findings.append("target.carrier_identifier is blank")
    return findings


def parse_context(text: str) -> RefinementContext:
    """Strictly decode transferred context bytes into the frozen context. Every defect —
    malformed JSON, unknown/missing fields, coercible-but-wrong scalar types, an unknown schema
    version, an unknown node status, a digest that does not match its source, an invalid
    expectation or provenance — is ``refinement_context_invalid``. Never trims anything."""
    code = AuthoringErrorCode.CONTEXT_INVALID
    raw = _load_json_object(text, "refinement context", code)
    try:
        parsed = _ContextIn.model_validate(raw)
    except ValidationError as exc:
        raise RefinementAuthoringError(
            code, f"refinement context fields invalid ({exc.error_count()} error(s))"
        ) from exc
    if parsed.schema_version != ARTIFACT_SCHEMA_VERSION:
        raise RefinementAuthoringError(
            code, f"refinement context has unknown schema_version {parsed.schema_version!r}"
        )
    try:
        status = NodeStatus(parsed.target.status)
    except ValueError as exc:
        raise RefinementAuthoringError(
            code, f"refinement context target status {parsed.target.status!r} is unknown"
        ) from exc
    target = RefinementTarget(
        identity=RefinementIdentity(
            backend=parsed.target.identity.backend,
            objective_id=parsed.target.identity.objective_id,
            objective_run_id=parsed.target.identity.objective_run_id,
            node_id=parsed.target.identity.node_id,
            carrier_id=parsed.target.identity.carrier_id,
        ),
        source=RefinementSource(
            description=parsed.target.source.description,
            slug=parsed.target.source.slug,
            comment=parsed.target.source.comment,
            depends_on=parsed.target.source.depends_on,
            effective_depends_on=parsed.target.source.effective_depends_on,
            issue_description=parsed.target.source.issue_description,
        ),
        source_digest=parsed.target.source_digest,
        carrier_identifier=parsed.target.carrier_identifier,
        carrier_url=parsed.target.carrier_url,
        status=status,
        plan_ref=parsed.target.plan_ref,
        has_plan_metadata=parsed.target.has_plan_metadata,
    )
    expected = MarkedCommentExpectation(
        comment_id=parsed.expected.comment_id, body_digest=parsed.expected.body_digest
    )
    provenance = parsed.provenance.to_domain()
    findings = _target_findings(target)
    findings += codec.provenance_findings(provenance)
    if not parsed.run_id.strip():
        findings.append("run_id is blank")
    if not parsed.objective.id.strip():
        findings.append("objective.id is blank")
    problem = expected.validation_problem()
    if problem is not None:
        findings.append(problem)
    prior: PriorRefinement | None = None
    if parsed.prior is not None:
        prior_provenance = parsed.prior.provenance.to_domain()
        findings += [f"prior.{f}" for f in codec.provenance_findings(prior_provenance)]
        if not is_canonical_digest(parsed.prior.source_digest):
            findings.append("prior.source_digest is not a canonical 64-char lowercase hex digest")
        if not parsed.prior.markdown.strip():
            findings.append("prior.markdown is blank")
        prior = PriorRefinement(
            markdown=parsed.prior.markdown,
            source_digest=parsed.prior.source_digest,
            provenance=prior_provenance,
            saved_at=parsed.prior.saved_at,
        )
    if findings:
        raise RefinementAuthoringError(code, "refinement context invalid: " + "; ".join(findings))
    return RefinementContext(
        run_id=parsed.run_id,
        target=target,
        expected=expected,
        provenance=provenance,
        objective=RefinementObjective(
            id=parsed.objective.id, title=parsed.objective.title, url=parsed.objective.url
        ),
        prior=prior,
        engagement=parsed.engagement,
        warnings=parsed.warnings,
    )


def parse_draft(text: str) -> RefinementDraft:
    """Strictly decode transferred draft bytes. The Markdown field is kept byte-exact (nonblank
    is tested with ``strip()``, the value is never trimmed)."""
    code = AuthoringErrorCode.DRAFT_INVALID
    raw = _load_json_object(text, "refinement draft", code)
    try:
        parsed = _DraftIn.model_validate(raw)
    except ValidationError as exc:
        raise RefinementAuthoringError(
            code, f"refinement draft fields invalid ({exc.error_count()} error(s))"
        ) from exc
    if parsed.schema_version != ARTIFACT_SCHEMA_VERSION:
        raise RefinementAuthoringError(
            code, f"refinement draft has unknown schema_version {parsed.schema_version!r}"
        )
    findings: list[str] = []
    if not parsed.run_id.strip():
        findings.append("run_id is blank")
    if not is_artifact_digest(parsed.context_digest):
        findings.append("context_digest is not a sha256:<64 lowercase hex> digest")
    if not parsed.markdown.strip():
        findings.append("markdown is blank")
    if findings:
        raise RefinementAuthoringError(code, "refinement draft invalid: " + "; ".join(findings))
    return RefinementDraft(
        run_id=parsed.run_id, context_digest=parsed.context_digest, markdown=parsed.markdown
    )


# ------------------------------------------------------------------ run-id / path safety


def is_safe_run_id(run_id: str) -> bool:
    """Whether a run id selects exactly one child of the shared runs directory (the TS
    ``isSafeRunId`` twin): non-empty, not ``.``/``..``, free of separators and NUL."""
    return (
        run_id != ""
        and run_id not in (".", "..")
        and "/" not in run_id
        and "\\" not in run_id
        and "\0" not in run_id
    )


def context_artifact_path(repo_root: Path, run_id: str) -> Path:
    """The fixed context artifact path inside the run's session-data dir, with the containment
    check (an unsafe run id, or a resolved path escaping the data dir, raises
    ``refinement_context_invalid`` before any read)."""
    if not is_safe_run_id(run_id):
        raise RefinementAuthoringError(
            AuthoringErrorCode.CONTEXT_INVALID, f"run id {run_id!r} is not a safe path component"
        )
    data_dir = cache.session_data_dir(repo_root, run_id)
    path = data_dir / CONTEXT_ARTIFACT
    try:
        resolved_dir = data_dir.resolve(strict=False)
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise RefinementAuthoringError(
            AuthoringErrorCode.CONTEXT_INVALID,
            f"could not resolve the context artifact path: {exc}",
        ) from exc
    if resolved.parent != resolved_dir:
        raise RefinementAuthoringError(
            AuthoringErrorCode.CONTEXT_INVALID,
            "the context artifact path escapes the run's session data dir",
        )
    return path


def _read_utf8(path: Path, missing: AuthoringErrorCode, invalid: AuthoringErrorCode) -> str:
    what = path.name
    if not path.is_file():
        raise RefinementAuthoringError(missing, f"{what} not found at {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RefinementAuthoringError(invalid, f"could not read {what}: {exc}") from exc
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RefinementAuthoringError(invalid, f"{what} is not valid UTF-8") from exc


def load_context_artifact(repo_root: Path, *, run_id: str) -> tuple[RefinementContext, str]:
    """Strictly read the current run's fixed context artifact: the parsed context plus the
    artifact's ``sha256:`` digest over its exact bytes. Absent → ``refinement_context_missing``;
    unreadable/undecodable/malformed → ``refinement_context_invalid``. No other-run fallback."""
    path = context_artifact_path(repo_root, run_id)
    text = _read_utf8(path, AuthoringErrorCode.CONTEXT_MISSING, AuthoringErrorCode.CONTEXT_INVALID)
    context = parse_context(text)
    if context.run_id != run_id:
        raise RefinementAuthoringError(
            AuthoringErrorCode.CONTEXT_INVALID,
            f"context run id {context.run_id!r} does not match the current run {run_id!r}",
        )
    return context, artifact_digest(text)


def load_draft_file(path: Path) -> RefinementDraft:
    """Strictly read a transferred draft file (the ``--draft-file`` input)."""
    text = _read_utf8(path, AuthoringErrorCode.DRAFT_MISSING, AuthoringErrorCode.DRAFT_INVALID)
    return parse_draft(text)


# ------------------------------------------------------------------ preparation


def capture_provenance(repo_root: Path, *, run_id: str) -> RefinementProvenance:
    """Capture the authoring provenance ONCE: HEAD, the dirty flag, and one UTC timestamp that
    serves as both ``authored_at`` (the start of the pass) and ``captured_at``. An unresolvable
    HEAD is a ``GitError`` (the CLI maps it to ``git_error``)."""
    head = git.resolve_commit(repo_root, "HEAD")
    if head is None:
        raise GitError("the repository has no resolvable HEAD commit — commit once before refining")
    dirty = git.is_dirty(repo_root)
    now = plan.now_iso()
    return RefinementProvenance(
        authoring_run_id=run_id,
        authored_at=now,
        code_basis=RefinementCodeBasis(head_sha=head, dirty=dirty, captured_at=now),
    )


def _header_run_id(header: dict[str, object]) -> str | None:
    value = header.get("run_id")
    if isinstance(value, str) and value.strip():
        return value
    return None


@dataclass(frozen=True)
class SelectedTarget:
    """A target selected and identity-bound against fresh adapters, before any provenance is
    captured — the dry-run report's input and the first half of a real preparation."""

    read: RefinementRead
    objective: RefinementObjective
    store: ObjectiveStore

    @property
    def target(self) -> RefinementTarget:
        return self.read.target


def select_bound_target(
    repo_root: Path, *, objective_id: str, node_id: str | None
) -> SelectedTarget:
    """Select the target against FRESH adapters (the caller has already done any sync and
    config reload): resolve store + issue backend, select through the service (explicit node or
    default walk), read the objective's addressing facts through ``get_objective`` and compare
    its identity EXACTLY with the target's (mismatch → ``refinement_binding_mismatch``, never a
    silent rebind). The resolved objective store's own refinement read is the support decision —
    a store without one surfaces as the service's typed ``unsupported_backend``; there is no
    door-side backend allowlist. No `objective show`, no delivery-readiness helper, no claim, no
    write, no clock, no git."""
    store = resolve.resolve_objective_store(repo_root)
    issues = resolve.resolve_issue_backend(repo_root)
    read = service.select_refinement_target(
        store, issues, objective_id=objective_id, node_id=node_id
    )
    target = read.target
    try:
        state = store.get_objective(objective_id=objective_id)
    except ObjectiveStoreError as exc:
        raise RefinementError(RefinementErrorCode.BACKEND_ERROR, str(exc)) from exc
    if state is None:
        raise RefinementError(
            RefinementErrorCode.OBJECTIVE_NOT_FOUND, f"objective {objective_id!r} not found"
        )
    header_run = _header_run_id(state.header)
    if state.id != target.identity.objective_id or header_run != target.identity.objective_run_id:
        raise RefinementAuthoringError(
            AuthoringErrorCode.BINDING_MISMATCH,
            f"objective {objective_id!r} reads as id {state.id!r} / run {header_run!r} but the "
            f"selected target is bound to id {target.identity.objective_id!r} / run "
            f"{target.identity.objective_run_id!r}",
        )
    return SelectedTarget(
        read=read,
        objective=RefinementObjective(id=state.id, title=state.title, url=state.url),
        store=store,
    )


def prepare_refinement_context(
    repo_root: Path, *, objective_id: str, node_id: str | None, run_id: str
) -> RefinementContext:
    """Prepare one grounding pass: :func:`select_bound_target`, then read the node engagement
    fail-soft (a failure is a visible warning + an empty block) and capture provenance once."""
    selected = select_bound_target(repo_root, objective_id=objective_id, node_id=node_id)
    target = selected.target
    warnings: list[str] = []
    engagement = ""
    try:
        ne = selected.store.read_node_engagement(
            objective_id=objective_id, node_id=target.identity.node_id
        )
    except ObjectiveStoreError as exc:
        warnings.append(f"node engagement unavailable ({exc}) — continuing without it")
    else:
        engagement = render_node_engagement(ne) or ""
    provenance = capture_provenance(repo_root, run_id=run_id)
    return RefinementContext(
        run_id=run_id,
        target=target,
        expected=selected.read.expected,
        provenance=provenance,
        objective=selected.objective,
        prior=_prior_of(selected.read.saved),
        engagement=engagement,
        warnings=tuple(warnings),
    )


def _prior_of(saved: SavedRefinement | None) -> PriorRefinement | None:
    if saved is None:
        return None
    return PriorRefinement(
        markdown=saved.document.markdown,
        source_digest=saved.document.source_digest,
        provenance=saved.document.provenance,
        saved_at=saved.saved_at,
    )


# ------------------------------------------------------------------ save conversion


@dataclass(frozen=True)
class RefinementSaveOutcome:
    """The verified save facts every save surface reports."""

    saved: SavedRefinement
    context: RefinementContext


def compose_save_request(
    context: RefinementContext, draft: RefinementDraft, *, context_digest: str
) -> RefinementSaveRequest:
    """Bind a transferred draft to its exact context: matching run ids and the exact context
    digest are required (mismatch → ``refinement_draft_invalid``); the document is composed from
    the context's target + provenance and the draft's byte-exact Markdown, with the context's
    retained expectation. Nothing is reselected or refreshed."""
    if draft.run_id != context.run_id:
        raise RefinementAuthoringError(
            AuthoringErrorCode.DRAFT_INVALID,
            f"draft run id {draft.run_id!r} does not match the context run {context.run_id!r}",
        )
    if draft.context_digest != context_digest:
        raise RefinementAuthoringError(
            AuthoringErrorCode.DRAFT_INVALID,
            "draft context_digest does not match the current context artifact — the context was "
            "re-prepared after this draft was written; rewrite the draft against the new context",
        )
    document: RefinementDocument = codec.document_for_target(
        context.target, markdown=draft.markdown, provenance=context.provenance
    )
    return RefinementSaveRequest(document=document, expected=context.expected)


def save_refinement_draft(
    repo_root: Path, *, run_id: str, draft_file: Path
) -> RefinementSaveOutcome:
    """The complete save conversion behind ``perk objective refinement-save``: strict draft
    read → strict current-run context read → exact binding → the service's guarded save through
    fresh adapters. Every service refusal propagates as ``RefinementError``. A retained context
    bound to a different backend than the resolved store refuses at the service as
    ``invalid_input`` before any read — never a silent save elsewhere."""
    draft = load_draft_file(draft_file)
    context, digest = load_context_artifact(repo_root, run_id=run_id)
    request = compose_save_request(context, draft, context_digest=digest)
    store = resolve.resolve_objective_store(repo_root)
    issues = resolve.resolve_issue_backend(repo_root)
    saved = service.save_node_refinement(store, issues, request=request)
    return RefinementSaveOutcome(saved=saved, context=context)
