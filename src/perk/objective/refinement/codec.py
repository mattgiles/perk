"""Objective-node refinement — the wire format, digests, and validators (contracts.md §8.67).

The stored record is ONE marked comment whose exact shape is::

    <!-- perk:objective-refinement:v1:<target-key> -->

    # Objective node refinement (advisory)

    ```json
    {<canonical header JSON>}
    ```

    <markdown>

``<target-key>`` is the SHA-256 (lowercase hex, no prefix) of the canonical JSON of the
five-field :class:`RefinementIdentity`; the header mapping is exactly
``{schema_version, identity, source, source_digest, provenance}`` (it never duplicates the
Markdown). The Markdown tail has no closing delimiter, so nested fences, pipes, and trailing
content survive verbatim. The shared Linear backend transcodes the whole rendered body as it
does every comment (the HTML marker becomes its inline-code form; the JSON line is ASCII-only
and newline-free, so the transcoder's line splitting cannot damage it).

Parse discipline: a comment whose first physical line is not a refinement-family marker is
unrelated (``None``); a family-marked comment MUST be well-formed (marker key, envelope, exact
schema version, canonical scalar spellings, digest, key↔identity agreement, nonblank Markdown) —
malformed records fail loud, never disappear. Well-formed FOREIGN-identity records are ignored
by target discovery, never rebound. Two exact target records are ambiguous even when equal,
and that ambiguity is decided from the marker headers before any payload is parsed.

Pydantic appears only as the lenient stored-parse models (``LenientParseModel``, unknown header
keys ignored); the domain stays frozen dataclasses, and one content validator serves both the
stored read (``malformed_refinement``) and caller-supplied save input (``invalid_input``).
"""

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import field_validator

from perk.backends.engagement import EngagementComment
from perk.backends.issue_backend import (
    body_digest,
    first_line,
    is_canonical_digest,
    scan_marked_comments,
)
from perk.boundary import LenientParseModel, ValidationError
from perk.objective.graph import node_sort_key
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementDocument,
    RefinementError,
    RefinementErrorCode,
    RefinementIdentity,
    RefinementProvenance,
    RefinementSaveRequest,
    RefinementSource,
    RefinementTarget,
    SavedRefinement,
)

SCHEMA_VERSION = "1"

# The marker family. The HTML form is what perk renders; the inline-code form is the Linear
# transcoder's rewrite of it (derived here by the same rule, never imported — the import
# direction is `backends.linear → objective`, never back).
MARKER_FAMILY = "perk:objective-refinement:v1"
_HTML_MARKER_TEMPLATE = "<!-- " + MARKER_FAMILY + ":{key} -->"
_INLINE_MARKER_TEMPLATE = "`" + MARKER_FAMILY + ":{key}`"
_TITLE_LINE = "# Objective node refinement (advisory)"
_HEADER_PREAMBLE = "\n\n" + _TITLE_LINE + "\n\n```json\n"
_HEADER_CLOSE = "\n```\n\n"

# A family marker as a whole first line, in either encoding. The key group is captured raw and
# validated separately (a malformed key in a marked comment is corruption, never a parse miss).
_FAMILY_HTML_RE = re.compile(r"^<!-- " + re.escape(MARKER_FAMILY) + r":([^\s>]*) -->$")
_FAMILY_INLINE_RE = re.compile(r"^`" + re.escape(MARKER_FAMILY) + r":([^`\s]*)`$")
# The lenient ownership predicate's first-line shapes: tolerant whitespace + an optional
# trailing CR, so a damaged owned record is still recognized as NOT a plan.
_FAMILY_LENIENT_RE = re.compile(
    r"^(?:<!--\s*"
    + re.escape(MARKER_FAMILY)
    + r":\S*\s*-->|`"
    + re.escape(MARKER_FAMILY)
    + r":[^`]*`)\r?$"
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEAD_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# ------------------------------------------------------------------ canonical scalars


def canonical_json(mapping: dict[str, object]) -> str:
    """The one canonical JSON spelling every digest hashes: sorted keys, no whitespace,
    ASCII-only escapes."""
    return json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_canonical_timestamp(value: str) -> bool:
    """True for exactly ``YYYY-MM-DDTHH:MM:SSZ`` naming a valid UTC calendar time (whole
    seconds; no fractional part, no numeric offset, no lenient field widths)."""
    if _TIMESTAMP_RE.match(value) is None:
        return False
    try:
        datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def format_timestamp(moment: datetime) -> str:
    """Spell an AWARE datetime as the canonical UTC timestamp (converted to UTC, microseconds
    discarded). A naive datetime is refused — its zone is unknown, so its spelling would lie."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("refinement timestamps require an aware datetime")
    return moment.astimezone(UTC).replace(microsecond=0).strftime(_TIMESTAMP_FORMAT)


def _identity_mapping(identity: RefinementIdentity) -> dict[str, object]:
    return {
        "backend": identity.backend,
        "objective_id": identity.objective_id,
        "objective_run_id": identity.objective_run_id,
        "node_id": identity.node_id,
        "carrier_id": identity.carrier_id,
    }


def _source_mapping(source: RefinementSource) -> dict[str, object]:
    # Explicit field mapping only: tuples become JSON arrays, nullable fields serialize as null.
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


def target_key(identity: RefinementIdentity) -> str:
    """The marker key: SHA-256 hex of the canonical JSON of the five identity fields."""
    return _sha256_hex(canonical_json(_identity_mapping(identity)))


def source_digest(source: RefinementSource) -> str:
    """The source fence digest: SHA-256 hex of the canonical JSON of the six source fields."""
    return _sha256_hex(canonical_json(_source_mapping(source)))


def html_marker(key: str) -> str:
    """The canonical HTML-comment marker perk renders for ``key``."""
    return _HTML_MARKER_TEMPLATE.format(key=key)


def inline_marker(key: str) -> str:
    """The Linear inline-code encoding of the marker for ``key`` (the transcoder's rewrite)."""
    return _INLINE_MARKER_TEMPLATE.format(key=key)


def marker_forms(key: str) -> tuple[str, str]:
    """Both accepted encodings of the exact ownership marker for ``key``."""
    return (html_marker(key), inline_marker(key))


# ------------------------------------------------------------------ content validation


def _nonblank(value: str, label: str, findings: list[str]) -> None:
    if not value.strip():
        findings.append(f"{label} is blank")


def _dependency_findings(deps: tuple[str, ...], label: str, findings: list[str]) -> None:
    for dep in deps:
        if not dep.strip():
            findings.append(f"{label} contains a blank node id")
            return
    if len(set(deps)) != len(deps):
        findings.append(f"{label} contains duplicate node ids")
    elif list(deps) != sorted(deps, key=node_sort_key):
        findings.append(f"{label} is not in natural node order")


def identity_findings(identity: RefinementIdentity) -> list[str]:
    findings: list[str] = []
    _nonblank(identity.backend, "identity.backend", findings)
    _nonblank(identity.objective_id, "identity.objective_id", findings)
    _nonblank(identity.objective_run_id, "identity.objective_run_id", findings)
    _nonblank(identity.node_id, "identity.node_id", findings)
    _nonblank(identity.carrier_id, "identity.carrier_id", findings)
    return findings


def source_findings(source: RefinementSource) -> list[str]:
    findings: list[str] = []
    if source.depends_on is not None:
        _dependency_findings(source.depends_on, "source.depends_on", findings)
    _dependency_findings(source.effective_depends_on, "source.effective_depends_on", findings)
    return findings


def provenance_findings(provenance: RefinementProvenance) -> list[str]:
    findings: list[str] = []
    _nonblank(provenance.authoring_run_id, "provenance.authoring_run_id", findings)
    if not is_canonical_timestamp(provenance.authored_at):
        findings.append("provenance.authored_at is not a canonical UTC timestamp")
    basis = provenance.code_basis
    if _HEAD_SHA_RE.match(basis.head_sha) is None:
        findings.append("provenance.code_basis.head_sha is not a full lowercase 40-hex commit id")
    if not is_canonical_timestamp(basis.captured_at):
        findings.append("provenance.code_basis.captured_at is not a canonical UTC timestamp")
    return findings


def document_findings(document: RefinementDocument) -> list[str]:
    """The content findings for a document (empty ⇒ valid). The one rule set behind both the
    stored-read validator and the save-input validator."""
    findings = identity_findings(document.identity)
    findings += source_findings(document.source)
    if not is_canonical_digest(document.source_digest):
        findings.append("source_digest is not a canonical 64-char lowercase hex digest")
    elif document.source_digest != source_digest(document.source):
        findings.append("source_digest does not match the source")
    findings += provenance_findings(document.provenance)
    if not document.markdown.strip():
        findings.append("markdown is blank")
    return findings


def validate_save_request(request: RefinementSaveRequest) -> None:
    """Refuse caller-supplied save input that breaks the content rules (``invalid_input``)."""
    findings = document_findings(request.document)
    problem = request.expected.validation_problem()
    if problem is not None:
        findings.append(problem)
    if findings:
        raise RefinementError(
            RefinementErrorCode.INVALID_INPUT,
            "invalid refinement save request: " + "; ".join(findings),
        )


def document_for_target(
    target: RefinementTarget, *, markdown: str, provenance: RefinementProvenance
) -> RefinementDocument:
    """Compose the document for a target: identity/source/digest come from the target as read,
    the Markdown and provenance from the authoring context. Content rules are checked at save."""
    return RefinementDocument(
        identity=target.identity,
        source=target.source,
        source_digest=target.source_digest,
        provenance=provenance,
        markdown=markdown,
    )


# ------------------------------------------------------------------ render


def render_refinement(document: RefinementDocument) -> str:
    """Render the exact comment envelope: marker, blank line, title, blank line, the fenced
    canonical header JSON, blank line, the Markdown verbatim (no added final newline)."""
    header: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "identity": _identity_mapping(document.identity),
        "source": _source_mapping(document.source),
        "source_digest": document.source_digest,
        "provenance": _provenance_mapping(document.provenance),
    }
    return (
        html_marker(target_key(document.identity))
        + _HEADER_PREAMBLE
        + canonical_json(header)
        + _HEADER_CLOSE
        + document.markdown
    )


# ------------------------------------------------------------------ parse


class _StoredIdentity(LenientParseModel):
    backend: str
    objective_id: str
    objective_run_id: str
    node_id: str
    carrier_id: str


class _StoredSource(LenientParseModel):
    description: str
    slug: str | None
    comment: str | None
    depends_on: tuple[str, ...] | None
    effective_depends_on: tuple[str, ...]
    issue_description: str


class _StoredCodeBasis(LenientParseModel):
    head_sha: str
    dirty: bool
    captured_at: str

    @field_validator("dirty", mode="before")
    @classmethod
    def _dirty_is_a_real_bool(cls, value: object) -> object:
        # A stored read never normalizes a non-boolean spelling (`1`, `"true"`) into validity.
        if not isinstance(value, bool):
            raise ValueError("dirty must be a JSON boolean")
        return value


class _StoredProvenance(LenientParseModel):
    authoring_run_id: str
    authored_at: str
    code_basis: _StoredCodeBasis


class _StoredHeader(LenientParseModel):
    """The stored header's lenient parse shape: every named field REQUIRED (a missing identity
    or provenance field is never defaulted into validity); unknown keys ignored."""

    schema_version: str
    identity: _StoredIdentity
    source: _StoredSource
    source_digest: str
    provenance: _StoredProvenance

    def to_domain(self, markdown: str) -> RefinementDocument:
        return RefinementDocument(
            identity=RefinementIdentity(
                backend=self.identity.backend,
                objective_id=self.identity.objective_id,
                objective_run_id=self.identity.objective_run_id,
                node_id=self.identity.node_id,
                carrier_id=self.identity.carrier_id,
            ),
            source=RefinementSource(
                description=self.source.description,
                slug=self.source.slug,
                comment=self.source.comment,
                depends_on=self.source.depends_on,
                effective_depends_on=self.source.effective_depends_on,
                issue_description=self.source.issue_description,
            ),
            source_digest=self.source_digest,
            provenance=RefinementProvenance(
                authoring_run_id=self.provenance.authoring_run_id,
                authored_at=self.provenance.authored_at,
                code_basis=RefinementCodeBasis(
                    head_sha=self.provenance.code_basis.head_sha,
                    dirty=self.provenance.code_basis.dirty,
                    captured_at=self.provenance.code_basis.captured_at,
                ),
            ),
            markdown=markdown,
        )


def family_marker_key(line: str) -> str | None:
    """The raw key of a refinement-family marker occupying ``line`` exactly (HTML or inline
    form), else ``None``. The key is NOT validated here."""
    for pattern in (_FAMILY_HTML_RE, _FAMILY_INLINE_RE):
        match = pattern.match(line)
        if match is not None:
            return match.group(1)
    return None


def is_refinement_comment(body: str) -> bool:
    """Ownership-only predicate for plan-comment exclusion: True when the first physical line is
    a refinement-family marker (either encoding), regardless of whether the rest is valid. A
    damaged owned record must never be read or overwritten as a plan; a marker mentioned later
    in a real plan does not change the plan's kind."""
    return _FAMILY_LENIENT_RE.match(first_line(body)) is not None


def _malformed(message: str, comment: EngagementComment) -> RefinementError:
    return RefinementError(
        RefinementErrorCode.MALFORMED_REFINEMENT,
        f"malformed refinement comment {comment.id}: {message}",
        comment_ids=(comment.id,),
    )


def parse_refinement_comment(comment: EngagementComment) -> SavedRefinement | None:
    """Decode one stored comment. ``None`` for an unrelated comment (no family marker on the
    first physical line). A family-marked comment must be well-formed end to end; every
    defect raises ``RefinementError(malformed_refinement)``. Parses BEFORE any trimming; the
    body digest is over the exact stored bytes."""
    body = comment.body
    key = family_marker_key(first_line(body))
    if key is None:
        return None
    if _HEX64_RE.match(key) is None:
        raise _malformed("marker key is not a 64-char lowercase hex digest", comment)
    if sum(body.count(form) for form in marker_forms(key)) != 1:
        raise _malformed("ownership marker is repeated", comment)
    rest = body[len(first_line(body)) :]
    if not rest.startswith(_HEADER_PREAMBLE):
        raise _malformed("envelope title/header fence is missing", comment)
    header_start = len(_HEADER_PREAMBLE)
    header_end = rest.find("\n", header_start)
    if header_end == -1 or not rest.startswith(_HEADER_CLOSE, header_end):
        raise _malformed("header fence is not closed", comment)
    header_text = rest[header_start:header_end]
    markdown = rest[header_end + len(_HEADER_CLOSE) :]
    try:
        raw = json.loads(header_text)
    except json.JSONDecodeError as exc:
        raise _malformed(f"header is not valid JSON ({exc.msg})", comment) from exc
    if not isinstance(raw, dict):
        raise _malformed("header is not a JSON object", comment)
    try:
        header = _StoredHeader.model_validate(raw)
    except ValidationError as exc:
        raise _malformed(f"header fields invalid ({exc.error_count()} error(s))", comment) from exc
    if header.schema_version != SCHEMA_VERSION:
        raise _malformed(f"unknown schema_version {header.schema_version!r}", comment)
    document = header.to_domain(markdown)
    findings = document_findings(document)
    if findings:
        raise _malformed("; ".join(findings), comment)
    if target_key(document.identity) != key:
        raise _malformed("marker key does not match the header identity", comment)
    return SavedRefinement(document=document, comment=comment, body_digest=body_digest(body))


def find_target_refinement(
    comments: Sequence[EngagementComment], identity: RefinementIdentity
) -> SavedRefinement | None:
    """Target discovery over a carrier's complete comment list: the unique valid record owned by
    ``identity``'s exact marker, or ``None`` for genuine absence.

    Precedence: two or more exact target records → ``ambiguous_refinement`` (decided from the
    marker headers, before any payload parse; equal duplicates included); a misplaced/repeated
    target marker, or a family-marked comment whose key cannot be read → ``malformed_refinement``;
    then the unique candidate's payload must decode to this exact identity. Well-formed foreign
    keys are ignored. Never deletes or rebinds anything.
    """
    key = target_key(identity)
    scan = scan_marked_comments(comments, forms=marker_forms(key))
    if len(scan.owned) > 1:
        raise RefinementError(
            RefinementErrorCode.AMBIGUOUS_REFINEMENT,
            f"{len(scan.owned)} refinement comments claim node {identity.node_id!r}",
            comment_ids=tuple(comment.id for comment in scan.owned),
        )
    if scan.malformed:
        raise RefinementError(
            RefinementErrorCode.MALFORMED_REFINEMENT,
            "refinement marker misplaced or repeated in comment(s) "
            + ", ".join(comment.id for comment in scan.malformed),
            comment_ids=tuple(comment.id for comment in scan.malformed),
        )
    owned_ids = {comment.id for comment in scan.owned}
    for comment in comments:
        if comment.id in owned_ids:
            continue
        other_key = family_marker_key(first_line(comment.body))
        if other_key is not None and _HEX64_RE.match(other_key) is None:
            raise _malformed("marker key is not a 64-char lowercase hex digest", comment)
    if not scan.owned:
        return None
    candidate = scan.owned[0]
    saved = parse_refinement_comment(candidate)
    if saved is None or saved.document.identity != identity:
        raise _malformed("record identity does not match the target", candidate)
    return saved
