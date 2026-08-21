"""The delivery operation journal — grammar, records, and the pure fold (contracts.md §8.43).

The **operation journal** is the append-only logical record of stack operations (publish / sync /
adopt / transfer / land) plus the one **non-operation event kind**, the ready stamp (the durable
per-layer handoff fact, contracts.md §8.43) — each physically carried as one strict, marked,
schema-versioned comment per event on the objective's journal carrier (GitHub: the objective
issue's comments; Linear: the Project metadata sentinel issue's comments). This module is the
journal's **pure** layer: the marker grammars, the frozen record dataclasses + their strict edge
models, the canonical serialization (the byte-identity key), and the fail-closed event fold. No
I/O, no backend imports — it imports ``perk.boundary``, ``yaml``, ``ulid``, and stdlib only; the
adapter that reads/writes carriers lives in :mod:`perk.delivery.persistence`.

Fail-closed disciplines (mirroring §8.42's fail-closed ``delivery_policy`` classifier):

- A comment with neither the ``perk:stack-operation-event`` nor the ``perk:stack-ready-stamp``
  marker text is unrelated untrusted DATA (ignored, never parsed). A comment carrying a marker
  text is perk's own region and MUST parse strictly under exactly ONE grammar — the routing
  dispatcher :func:`parse_carrier_comment` gives the operation marker precedence — and a
  malformed / edited / tampered perk-marked event raises :class:`JournalCorruptionError`,
  never a silent skip.
- Byte-identity for idempotency is **canonical-serialization equality**: two events are "the
  same" iff their re-rendered canonical payloads are byte-equal — which makes GitHub (HTML
  marker) and Linear (transcoded inline-code marker) events comparable, because the logical key
  and strict payload are identical across backends.
- ``accepted`` is structurally gated to ``operation_kind == land`` (the async-merge UUID is the
  only sanctioned non-reconstructable handle); the gate widens only at an explicit schema
  revision.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import yaml
from pydantic import ValidationInfo, field_validator
from ulid import ULID

from perk.boundary import (
    OutputModel,
    StrictInputModel,
    StrTuple,
    translate_validation_errors,
)

JOURNAL_SCHEMA_VERSION = "1"

# One backend-neutral size cap validated before every append (margin under GitHub's 65,536-char
# issue-comment limit; Linear's limit is undocumented — this is the conservative shared cap).
# Oversize is a typed refusal (`JournalRecordTooLarge`), never a truncated write.
JOURNAL_EVENT_MAX_CHARS = 60_000


class JournalCorruptionError(Exception):
    """A perk-marked journal event is present but corrupt (malformed / conflicting / edited /
    orphaned). Fail-closed: corruption always raises, never silently folds or skips."""


class JournalRecordTooLarge(Exception):
    """A rendered journal event exceeds :data:`JOURNAL_EVENT_MAX_CHARS` — a typed refusal,
    never a truncated write."""


class OperationKind(StrEnum):
    """The bounded stack-operation vocabulary (the journal never becomes a general workflow
    engine)."""

    PUBLISH = "publish"
    SYNC = "sync"
    ADOPT = "adopt"
    TRANSFER = "transfer"
    LAND = "land"


class EventRole(StrEnum):
    """The bounded event-role vocabulary: one ``prepared`` record per operation, then minimal
    outcomes (``accepted`` only for land's async-merge handle; ``completed``/``abandoned``
    terminal)."""

    PREPARED = "prepared"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


# The terminal outcome roles: an operation lacking one is unresolved (an `accepted`-only land is
# still unresolved).
_TERMINAL_ROLES = frozenset({EventRole.COMPLETED, EventRole.ABANDONED})
_ROLE_VALUES = frozenset(role.value for role in EventRole)


def mint_operation_id() -> str:
    """Mint a fresh operation id (a new ULID) — time-sortable, collision-free."""
    return str(ULID())


def _require_ulid(value: str, *, what: str) -> str:
    """Validate ``value`` as a canonical ULID (wrapped to ``ValueError``, the dataclass /
    edge-model shared check)."""
    try:
        ULID.from_str(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{what} is not a ULID: {value!r}") from exc
    return value


# ----------------------------------------------------------------- marker grammar

# The canonical marker (the architecture's deterministic operation/event identity). The HTML form
# is what perk renders; the inline-code form is what Linear's existing marker transcoder
# (`to_linear_markdown`) produces — perk never renders it directly, but the parser accepts both
# encodings (mirroring perk.plan's dual-encoding discipline).
_MARKER_TEXT = "perk:stack-operation-event"
_HTML_MARKER_RE = re.compile(
    r"^<!--\s*perk:stack-operation-event:([^:\s]+):([^:\s]+?)\s*-->$",
)
_INLINE_MARKER_RE = re.compile(r"^`perk:stack-operation-event:([^:`\s]+):([^:`\s]+)`$")

# The ready stamp's own disjoint marker (contracts.md §8.43): pre-stamp readers skip stamp
# comments as unrelated DATA (no operation-marker substring), so mixed-version machines never
# see corruption where a new event kind merely exists. Four colon-free key segments:
# objective_id : plan_id : node_id : head_sha.
_STAMP_MARKER_TEXT = "perk:stack-ready-stamp"
_STAMP_HTML_MARKER_RE = re.compile(
    r"^<!--\s*perk:stack-ready-stamp:([^:\s]+):([^:\s]+):([^:\s]+):([^:\s]+?)\s*-->$",
)
_STAMP_INLINE_MARKER_RE = re.compile(
    r"^`perk:stack-ready-stamp:([^:`\s]+):([^:`\s]+):([^:`\s]+):([^:`\s]+)`$",
)

_HEAD_SHA_RE = re.compile(r"[0-9a-f]{40}")

# The marker-safe segment allowlist: every real segment shape fits (numeric GitHub ids, Linear
# identifiers like ENG-123, ULID lineages, `<phase>.<n>` node ids), while everything that could
# break either marker encoding is excluded by construction — the colon (the operation marker's
# separator: the reverse-collision guarantee), whitespace/backticks (the inline-code encoding),
# and `<`/`>`/`!` (an embedded `-->` would terminate the HTML comment early and mangle the
# Linear transcode). A non-conforming id is a typed refusal at construction and parse — loud,
# never a silently mangled marker (contracts.md §8.43).
_STAMP_SEGMENT_RE = re.compile(r"[A-Za-z0-9._-]+")


def _require_stamp_segment(value: str, *, what: str) -> str:
    """Validate one stamp payload field (one implementation, both edges): nonblank, no leading
    ``#`` (ids are canonical-bare at construction and parse — exact equality everywhere, no
    normalization branch in the fold), and drawn from the marker-safe allowlist
    (:data:`_STAMP_SEGMENT_RE`)."""
    if not value:
        raise ValueError(f"{what} must be nonblank")
    if value.startswith("#"):
        raise ValueError(f"{what} must be canonical-bare (no leading '#'): {value!r}")
    if _STAMP_SEGMENT_RE.fullmatch(value) is None:
        raise ValueError(
            f"{what} is not a marker-safe segment (allowed: letters, digits, '.', '_', '-'): "
            f"{value!r}"
        )
    return value


def _require_head_sha(value: str) -> str:
    """Validate a stamp's ``head_sha`` as EXACTLY the full 40-hex lowercase object id
    (``fullmatch`` — a ``$``-anchored match would admit a trailing newline; the verified
    checkpoint form — an abbreviation or ref would be re-pinnable, violating immutability)."""
    if _HEAD_SHA_RE.fullmatch(value) is None:
        raise ValueError(f"head_sha is not a 40-hex lowercase object id: {value!r}")
    return value


def render_marker(operation_id: str, role: EventRole) -> str:
    """The canonical HTML marker line for one event."""
    return f"<!-- {_MARKER_TEXT}:{operation_id}:{role.value} -->"


# ----------------------------------------------------------------- records (frozen domain)


@dataclass(frozen=True)
class PreparedRecord:
    """The immutable ``prepared`` record — appended and positively read back immediately before
    an operation's first remote effect.

    ``before``/``after`` are kind-specific exact/expected observations; their exact contents are
    owned by the operation nodes — here they stay opaque validated mappings (the envelope only).
    ``affected_plans`` is the ordered plan-id list.
    """

    operation_id: str
    operation_kind: OperationKind
    delivery_lineage: str
    objective_id: str
    run_id: str
    created: str
    affected_plans: tuple[str, ...]
    before: Mapping[str, object]
    after: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_ulid(self.operation_id, what="operation_id")


@dataclass(frozen=True)
class OutcomeRecord:
    """A later event referring to a prepared operation: ``accepted`` (land's async-merge handle
    only), ``completed`` (every postcondition verified), or ``abandoned`` (every effect proven
    at its before state). ``observed`` is the verified result / proof, an opaque validated
    mapping."""

    operation_id: str
    role: EventRole
    created: str
    observed: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_ulid(self.operation_id, what="operation_id")
        if self.role not in (EventRole.ACCEPTED, EventRole.COMPLETED, EventRole.ABANDONED):
            raise ValueError(f"an outcome record's role cannot be {self.role.value!r}")


type JournalRecord = PreparedRecord | OutcomeRecord


# ----------------------------------------------------------------- edge models (strict parse)


class PreparedRecordModel(StrictInputModel):
    """The strict parse shape of a ``prepared`` payload (``extra="forbid"``; ``schema_version``
    must be the literal ``"1"``; unknown kinds reject; ``operation_id`` must be a ULID)."""

    schema_version: Literal["1"]
    event: Literal["prepared"]
    operation_id: str
    operation_kind: Literal["publish", "sync", "adopt", "transfer", "land"]
    delivery_lineage: str
    objective_id: str
    run_id: str
    created: str
    affected_plans: StrTuple
    before: dict[str, object]
    after: dict[str, object]

    @field_validator("operation_id")
    @classmethod
    def _ulid(cls, value: str) -> str:
        return _require_ulid(value, what="operation_id")

    def to_domain(self) -> PreparedRecord:
        return PreparedRecord(
            operation_id=self.operation_id,
            operation_kind=OperationKind(self.operation_kind),
            delivery_lineage=self.delivery_lineage,
            objective_id=self.objective_id,
            run_id=self.run_id,
            created=self.created,
            affected_plans=self.affected_plans,
            before=self.before,
            after=self.after,
        )


class OutcomeRecordModel(StrictInputModel):
    """The strict parse shape of an ``accepted``/``completed``/``abandoned`` payload (same
    fail-closed rules as :class:`PreparedRecordModel`; ``event`` is the role discriminator)."""

    schema_version: Literal["1"]
    event: Literal["accepted", "completed", "abandoned"]
    operation_id: str
    created: str
    observed: dict[str, object]

    @field_validator("operation_id")
    @classmethod
    def _ulid(cls, value: str) -> str:
        return _require_ulid(value, what="operation_id")

    def to_domain(self) -> OutcomeRecord:
        return OutcomeRecord(
            operation_id=self.operation_id,
            role=EventRole(self.event),
            created=self.created,
            observed=self.observed,
        )


# ----------------------------------------------------------------- edge models (serialize-only)


class PreparedRecordOut(OutputModel):
    """Serialize-only snapshot of a :class:`PreparedRecord`. Field declaration order is
    load-bearing — it matches the architecture's record example and fixes the canonical
    serialization bytes."""

    schema_version: str
    event: str
    operation_id: str
    operation_kind: str
    delivery_lineage: str
    objective_id: str
    run_id: str
    created: str
    affected_plans: tuple[str, ...]
    before: dict[str, object]
    after: dict[str, object]

    @classmethod
    def from_domain(cls, record: PreparedRecord) -> "PreparedRecordOut":
        return cls(
            schema_version=JOURNAL_SCHEMA_VERSION,
            event=EventRole.PREPARED.value,
            operation_id=record.operation_id,
            operation_kind=record.operation_kind.value,
            delivery_lineage=record.delivery_lineage,
            objective_id=record.objective_id,
            run_id=record.run_id,
            created=record.created,
            affected_plans=record.affected_plans,
            before=dict(record.before),
            after=dict(record.after),
        )


class OutcomeRecordOut(OutputModel):
    """Serialize-only snapshot of an :class:`OutcomeRecord` (declaration order load-bearing,
    matching the architecture's outcome example)."""

    schema_version: str
    event: str
    operation_id: str
    created: str
    observed: dict[str, object]

    @classmethod
    def from_domain(cls, record: OutcomeRecord) -> "OutcomeRecordOut":
        return cls(
            schema_version=JOURNAL_SCHEMA_VERSION,
            event=record.role.value,
            operation_id=record.operation_id,
            created=record.created,
            observed=dict(record.observed),
        )


# ----------------------------------------------------------------- rendering


def record_role(record: JournalRecord) -> EventRole:
    """The event role a record carries (``prepared`` for a :class:`PreparedRecord`)."""
    return EventRole.PREPARED if isinstance(record, PreparedRecord) else record.role


def canonical_payload(record: JournalRecord) -> str:
    """The canonical serialization of a record — the byte-identity key (decision: two events are
    "the same" iff these bytes are equal, across both marker encodings)."""
    out: PreparedRecordOut | OutcomeRecordOut = (
        PreparedRecordOut.from_domain(record)
        if isinstance(record, PreparedRecord)
        else OutcomeRecordOut.from_domain(record)
    )
    return yaml.safe_dump(out.model_dump(mode="json"), sort_keys=False)


def render_event(record: JournalRecord) -> str:
    """Render one journal event's comment body: the canonical HTML marker line, a blank line,
    then one ``yaml`` fence carrying the canonical payload. No ``<details>`` wrapper — nothing
    for the Linear transcoder to touch except the marker rewrite."""
    marker = render_marker(record.operation_id, record_role(record))
    return f"{marker}\n\n```yaml\n{canonical_payload(record)}```"


def ensure_event_size(body: str) -> None:
    """Refuse an oversize rendered event (:data:`JOURNAL_EVENT_MAX_CHARS`) — typed, never
    truncated."""
    if len(body) > JOURNAL_EVENT_MAX_CHARS:
        raise JournalRecordTooLarge(
            f"rendered journal event is {len(body)} chars "
            f"(cap {JOURNAL_EVENT_MAX_CHARS}); refusing to append"
        )


# ----------------------------------------------------------------- the ready stamp


@dataclass(frozen=True)
class ReadyStampRecord:
    """The immutable ready-stamp record (contracts.md §8.43): the durable human handoff fact,
    bound to the exact published head it was made at.

    Pure fact — no timestamp, no run id: the deterministic canonical bytes ARE the idempotence
    contract (a same-head re-stamp re-derives byte-identical bytes); temporal ordering comes
    from the carrier comment's ``(created_at, comment_id)``. Every id is canonical-bare (a
    leading ``#`` is rejected at construction and parse), so fold scoping uses exact equality.
    """

    objective_id: str
    delivery_lineage: str
    plan_id: str
    node_id: str
    head_sha: str

    def __post_init__(self) -> None:
        _require_stamp_segment(self.objective_id, what="objective_id")
        _require_stamp_segment(self.delivery_lineage, what="delivery_lineage")
        _require_stamp_segment(self.plan_id, what="plan_id")
        _require_stamp_segment(self.node_id, what="node_id")
        _require_head_sha(self.head_sha)


def stamp_key(record: ReadyStampRecord) -> str:
    """The deterministic 4-segment event key (the marker's key segments, colon-joined)."""
    return f"{record.objective_id}:{record.plan_id}:{record.node_id}:{record.head_sha}"


class ReadyStampModel(StrictInputModel):
    """The strict parse shape of a ready-stamp payload (``extra="forbid"``; ``schema_version``
    must be the literal ``"1"``; ids canonical-bare; ``head_sha`` 40-hex lowercase)."""

    schema_version: Literal["1"]
    event: Literal["ready_stamp"]
    objective_id: str
    delivery_lineage: str
    plan_id: str
    node_id: str
    head_sha: str

    @field_validator("objective_id", "delivery_lineage", "plan_id", "node_id")
    @classmethod
    def _segment(cls, value: str, info: ValidationInfo) -> str:
        return _require_stamp_segment(value, what=str(info.field_name))

    @field_validator("head_sha")
    @classmethod
    def _sha(cls, value: str) -> str:
        return _require_head_sha(value)

    def to_domain(self) -> ReadyStampRecord:
        return ReadyStampRecord(
            objective_id=self.objective_id,
            delivery_lineage=self.delivery_lineage,
            plan_id=self.plan_id,
            node_id=self.node_id,
            head_sha=self.head_sha,
        )


class ReadyStampOut(OutputModel):
    """Serialize-only snapshot of a :class:`ReadyStampRecord` (declaration order load-bearing —
    it fixes the canonical serialization bytes, contracts.md §8.43)."""

    schema_version: str
    event: str
    objective_id: str
    delivery_lineage: str
    plan_id: str
    node_id: str
    head_sha: str

    @classmethod
    def from_domain(cls, record: ReadyStampRecord) -> "ReadyStampOut":
        return cls(
            schema_version=JOURNAL_SCHEMA_VERSION,
            event="ready_stamp",
            objective_id=record.objective_id,
            delivery_lineage=record.delivery_lineage,
            plan_id=record.plan_id,
            node_id=record.node_id,
            head_sha=record.head_sha,
        )


def canonical_stamp_payload(record: ReadyStampRecord) -> str:
    """The canonical serialization of a ready stamp — the byte-identity key (a separate
    function from :func:`canonical_payload`, keeping the operation union closed)."""
    return yaml.safe_dump(
        ReadyStampOut.from_domain(record).model_dump(mode="json"), sort_keys=False
    )


def render_stamp_marker(record: ReadyStampRecord) -> str:
    """The canonical HTML marker line for one ready stamp."""
    return f"<!-- {_STAMP_MARKER_TEXT}:{stamp_key(record)} -->"


def render_stamp_event(record: ReadyStampRecord) -> str:
    """Render one ready-stamp comment body — the :func:`render_event` shape (marker line,
    blank line, one ``yaml`` fence; nothing for the Linear transcoder to touch but the
    marker)."""
    return f"{render_stamp_marker(record)}\n\n```yaml\n{canonical_stamp_payload(record)}```"


# ----------------------------------------------------------------- parsing


@dataclass(frozen=True)
class JournalEvent:
    """One parsed journal event: the strict record plus its physical-comment identity.

    ``canonical_payload`` is the re-rendered canonical serialization (the byte-identity key).
    ``carrier_objective_id`` is the objective whose carrier holds the comment — stamped by the
    persistence adapter (the parser does not know the carrier), defaulting to ``""`` until
    stamped.
    """

    record: JournalRecord
    role: EventRole
    operation_id: str
    canonical_payload: str
    comment_id: str
    created_at: str
    carrier_objective_id: str = ""


def parse_journal_comment(
    body: str,
    *,
    comment_id: str,
    created_at: str,
    edited_at: str | None,
    carrier: str | None = None,
) -> JournalEvent | None:
    """Parse one carrier comment into a :class:`JournalEvent`.

    Returns ``None`` when the body carries no ``perk:stack-operation-event`` marker text in
    either encoding (an unrelated comment — human or other perk machinery — ignored as untrusted
    DATA). Marker detection is substring-based like every perk marker, so ANY body carrying the
    marker text (even quoted inside a code block) is treated as a journal region and must parse
    strictly — the fail-closed pin. Raises :class:`JournalCorruptionError` when the marker text
    is present but the event is detectably edited, malformed, or tampered — with ``carrier``
    (the carrier issue-tier id, when the caller knows it) named alongside the comment id so a
    succession fold's corruption points at the corrupt physical carrier.
    """
    if _MARKER_TEXT not in body:
        return None
    where = f"journal comment {comment_id}"
    if carrier is not None:
        where += f" on carrier {carrier}"
    if body.count(_MARKER_TEXT) > 1:
        raise JournalCorruptionError(f"{where}: carries more than one event marker")
    if edited_at is not None:
        raise JournalCorruptionError(
            f"{where}: journal event was edited at {edited_at} (perk never edits an event)"
        )
    lines = body.strip().splitlines()
    first = lines[0].rstrip() if lines else ""
    match = _HTML_MARKER_RE.match(first) or _INLINE_MARKER_RE.match(first)
    if match is None:
        raise JournalCorruptionError(
            f"{where}: marker text present but the body does not start with a well-formed "
            "stack-operation-event marker line"
        )
    marker_operation_id, marker_role = match.group(1), match.group(2)
    if marker_role not in _ROLE_VALUES:
        raise JournalCorruptionError(f"{where}: unknown event role {marker_role!r} in marker")
    role = EventRole(marker_role)
    payload_text = _extract_single_yaml_fence(lines[1:], where=where)
    try:
        raw = yaml.safe_load(payload_text)
    except yaml.YAMLError as exc:
        raise JournalCorruptionError(f"{where}: payload is not parseable YAML ({exc})") from exc
    if not isinstance(raw, dict):
        raise JournalCorruptionError(f"{where}: payload is not a YAML mapping")
    model_cls: type[PreparedRecordModel] | type[OutcomeRecordModel] = (
        PreparedRecordModel if role is EventRole.PREPARED else OutcomeRecordModel
    )
    with translate_validation_errors(JournalCorruptionError, source=where):
        parsed = model_cls.model_validate(raw)
    record = parsed.to_domain()
    if record.operation_id != marker_operation_id or record_role(record) is not role:
        raise JournalCorruptionError(
            f"{where}: marker identity {marker_operation_id}:{role.value} disagrees with the "
            f"payload's {record.operation_id}:{record_role(record).value} (tampering)"
        )
    return JournalEvent(
        record=record,
        role=role,
        operation_id=record.operation_id,
        canonical_payload=canonical_payload(record),
        comment_id=comment_id,
        created_at=created_at,
    )


def _extract_single_yaml_fence(rest: list[str], *, where: str) -> str:
    """The payload text of the body's single ``yaml`` fence — strict shape: optional blank
    lines, exactly one ```` ```yaml ```` fence, optional trailing blank lines, nothing else."""
    i = 0
    while i < len(rest) and rest[i].strip() == "":
        i += 1
    if i >= len(rest) or rest[i].rstrip() != "```yaml":
        raise JournalCorruptionError(f"{where}: body is not exactly marker + one yaml fence")
    payload_lines: list[str] = []
    j = i + 1
    # rstrip-only close match: nested payload content inside the fence is always indented by
    # safe_dump, so a column-0 ``` line is unambiguous (an indented ``` never terminates).
    while j < len(rest) and rest[j].rstrip() != "```":
        payload_lines.append(rest[j])
        j += 1
    if j >= len(rest):
        raise JournalCorruptionError(f"{where}: yaml fence is unterminated")
    for line in rest[j + 1 :]:
        if line.strip():
            raise JournalCorruptionError(
                f"{where}: body carries text outside the marker + yaml fence"
            )
    return "\n".join(payload_lines) + "\n" if payload_lines else ""


@dataclass(frozen=True)
class ReadyStampEvent:
    """One parsed ready-stamp event: the strict record plus its physical-comment identity.

    ``key`` is the marker's deterministic 4-segment key; ``canonical_payload`` the re-rendered
    canonical serialization (the byte-identity key). No carrier field: nothing routes or folds
    by a stamp's carrier — scoping is the record's own objective identity (contracts.md §8.43).
    """

    record: ReadyStampRecord
    key: str
    canonical_payload: str
    comment_id: str
    created_at: str


def parse_stamp_comment(
    body: str,
    *,
    comment_id: str,
    created_at: str,
    edited_at: str | None,
    carrier: str | None = None,
) -> ReadyStampEvent | None:
    """Parse one carrier comment into a :class:`ReadyStampEvent`.

    Returns ``None`` when the body carries no ``perk:stack-ready-stamp`` marker text in either
    encoding; fail-closed otherwise, mirroring :func:`parse_journal_comment` arm for arm — a
    present-but-malformed / edited / tampered stamp raises :class:`JournalCorruptionError`.
    Callers routing whole carriers go through :func:`parse_carrier_comment` (one grammar per
    comment, operation-marker precedence); this parser assumes the body is a stamp region.
    """
    if _STAMP_MARKER_TEXT not in body:
        return None
    where = f"ready-stamp comment {comment_id}"
    if carrier is not None:
        where += f" on carrier {carrier}"
    if body.count(_STAMP_MARKER_TEXT) > 1:
        raise JournalCorruptionError(f"{where}: carries more than one ready-stamp marker")
    if edited_at is not None:
        raise JournalCorruptionError(
            f"{where}: ready stamp was edited at {edited_at} (perk never edits an event)"
        )
    lines = body.strip().splitlines()
    first = lines[0].rstrip() if lines else ""
    match = _STAMP_HTML_MARKER_RE.match(first) or _STAMP_INLINE_MARKER_RE.match(first)
    if match is None:
        raise JournalCorruptionError(
            f"{where}: marker text present but the body does not start with a well-formed "
            "stack-ready-stamp marker line"
        )
    payload_text = _extract_single_yaml_fence(lines[1:], where=where)
    try:
        raw = yaml.safe_load(payload_text)
    except yaml.YAMLError as exc:
        raise JournalCorruptionError(f"{where}: payload is not parseable YAML ({exc})") from exc
    if not isinstance(raw, dict):
        raise JournalCorruptionError(f"{where}: payload is not a YAML mapping")
    with translate_validation_errors(JournalCorruptionError, source=where):
        parsed = ReadyStampModel.model_validate(raw)
    record = parsed.to_domain()
    marker_key = ":".join(match.groups())
    if stamp_key(record) != marker_key:
        raise JournalCorruptionError(
            f"{where}: marker identity {marker_key} disagrees with the payload's "
            f"{stamp_key(record)} (tampering)"
        )
    return ReadyStampEvent(
        record=record,
        key=marker_key,
        canonical_payload=canonical_stamp_payload(record),
        comment_id=comment_id,
        created_at=created_at,
    )


def parse_carrier_comment(
    body: str,
    *,
    comment_id: str,
    created_at: str,
    edited_at: str | None,
    carrier: str | None = None,
) -> JournalEvent | ReadyStampEvent | None:
    """Route one carrier comment through exactly ONE grammar (contracts.md §8.43).

    Operation-marker precedence: a body carrying the operation marker text parses under the
    operation grammar — whatever it returns or raises stands — so an operation whose opaque
    ``before``/``after`` payload merely *mentions* the stamp text (e.g. journaled user-authored
    prose) parses cleanly as an operation, never as a malformed stamp. Only a body with no
    operation marker text and the stamp marker text parses under the stamp grammar (the reverse
    collision is structurally impossible: every stamp payload field is a marker-safe allowlisted
    segment or 40-hex, so a rendered stamp body can never contain the colon-carrying operation
    marker text). Neither text → unrelated untrusted DATA (``None``).
    """
    if _MARKER_TEXT in body:
        return parse_journal_comment(
            body,
            comment_id=comment_id,
            created_at=created_at,
            edited_at=edited_at,
            carrier=carrier,
        )
    return parse_stamp_comment(
        body,
        comment_id=comment_id,
        created_at=created_at,
        edited_at=edited_at,
        carrier=carrier,
    )


# ----------------------------------------------------------------- fold (pure)


@dataclass(frozen=True)
class OperationState:
    """One operation's folded state: its prepared event, the optional ``accepted`` handle
    (land only), and the optional terminal outcome."""

    operation_id: str
    kind: OperationKind
    prepared: JournalEvent
    accepted: JournalEvent | None
    outcome: JournalEvent | None

    @property
    def resolved(self) -> bool:
        """True when a terminal outcome (completed/abandoned) is present. An ``accepted``-only
        operation is still unresolved."""
        return self.outcome is not None

    @property
    def terminal_role(self) -> EventRole | None:
        """The terminal role (``completed``/``abandoned``) or ``None`` while unresolved."""
        return None if self.outcome is None else self.outcome.role


@dataclass(frozen=True)
class JournalFold:
    """The pure fold over a lineage's journal events.

    ``events`` is the post-dedupe event sequence ordered by ``(created_at, comment_id)``;
    ``operations`` maps ``operation_id`` → folded state (insertion = fold order);
    ``unresolved`` are the operations lacking a terminal outcome; ``delivery_lineage`` is the
    fold's lineage (the expected lineage when given, else the single lineage the events carry);
    ``stamps`` is the post-dedupe ready-stamp sequence ordered by ``(created_at, comment_id)``
    — append-only history across the succession chain, projected per objective identity through
    :meth:`latest_ready_stamp`.
    """

    events: tuple[JournalEvent, ...]
    operations: Mapping[str, OperationState]
    unresolved: tuple[OperationState, ...] = ()
    delivery_lineage: str | None = None
    stamps: tuple[ReadyStampEvent, ...] = ()

    def latest_ready_stamp(self, *, objective_id: str, plan_id: str) -> ReadyStampEvent | None:
        """The latest stamp whose record names EXACTLY this objective identity + plan
        (contracts.md §8.43's fold scoping: stamps bind to the objective identity they were
        made under — a predecessor's stamp never projects for a successor). Exact equality:
        ids are canonical-bare by construction, so no normalization branch exists here."""
        for stamp in reversed(self.stamps):
            record = stamp.record
            if record.objective_id == objective_id and record.plan_id == plan_id:
                return stamp
        return None


def fold_events(
    events: Iterable[JournalEvent],
    *,
    expected_lineage: str | None,
    stamps: Iterable[ReadyStampEvent] = (),
) -> JournalFold:
    """Fold parsed journal events into per-operation state — fail-closed.

    Rules: a duplicate ``(operation_id, role)`` key with a byte-identical canonical payload
    dedupes (first occurrence wins — the idempotency contract); a differing payload is a
    conflicting duplicate (corruption); two prepared events for one operation on different
    carriers is corruption; an outcome/accepted with no prepared event anywhere in the fold is
    corruption (out-of-band deletion of the prepared record is the likely cause — authorized
    deletion IS corruption); both terminal outcomes for one operation is corruption; ``accepted``
    on a non-``land`` operation is corruption; a prepared record whose lineage differs from
    ``expected_lineage`` (when given) is foreign and never silently folds.

    Ready stamps fold by the same disciplines: sorted ``(created_at, comment_id)``, deduped by
    key (byte-identical first-wins; a differing payload under one key is corruption), and
    lineage-validated against the fold's **effective** lineage — the supplied
    ``expected_lineage``, or, when ``None``, the lineage the operation-record inference
    resolves (stamps never *contribute* to the inference). Only a fold that ends with no
    lineage at all folds stamps unverifiable, as parsed.
    """
    ordered = sorted(events, key=lambda e: (e.created_at, e.comment_id))
    deduped: list[JournalEvent] = []
    by_key: dict[tuple[str, EventRole], JournalEvent] = {}
    for event in ordered:
        key = (event.operation_id, event.role)
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = event
            deduped.append(event)
            continue
        if prior.canonical_payload != event.canonical_payload:
            raise JournalCorruptionError(
                f"conflicting duplicate {event.operation_id}:{event.role.value} events "
                f"(comments {prior.comment_id} and {event.comment_id} carry differing payloads)"
            )
        if (
            event.role is EventRole.PREPARED
            and prior.carrier_objective_id != event.carrier_objective_id
        ):
            raise JournalCorruptionError(
                f"operation {event.operation_id} has prepared events on two carriers "
                f"({prior.carrier_objective_id!r} and {event.carrier_objective_id!r})"
            )
        # Byte-identical duplicate: idempotent — first occurrence wins.

    prepared_by_op: dict[str, JournalEvent] = {}
    accepted_by_op: dict[str, JournalEvent] = {}
    outcomes_by_op: dict[str, list[JournalEvent]] = {}
    for event in deduped:
        if event.role is EventRole.PREPARED:
            prepared_by_op[event.operation_id] = event
        elif event.role is EventRole.ACCEPTED:
            accepted_by_op[event.operation_id] = event
        else:
            outcomes_by_op.setdefault(event.operation_id, []).append(event)

    for operation_id in {*accepted_by_op, *outcomes_by_op}:
        if operation_id not in prepared_by_op:
            raise JournalCorruptionError(
                f"operation {operation_id} has outcome events but no prepared event anywhere in "
                "the fold — likely out-of-band deletion of the prepared record (authorized "
                "deletion is corruption)"
            )

    operations: dict[str, OperationState] = {}
    lineages: set[str] = set()
    for operation_id, prep in prepared_by_op.items():
        record = prep.record
        if not isinstance(record, PreparedRecord):  # unreachable by construction; fail closed
            raise JournalCorruptionError(
                f"prepared event {operation_id} does not carry a prepared record"
            )
        if expected_lineage is not None and record.delivery_lineage != expected_lineage:
            raise JournalCorruptionError(
                f"operation {operation_id} carries foreign delivery_lineage "
                f"{record.delivery_lineage!r} (expected {expected_lineage!r}) — a foreign-lineage "
                "event never silently folds"
            )
        lineages.add(record.delivery_lineage)
        accepted = accepted_by_op.get(operation_id)
        if accepted is not None and record.operation_kind is not OperationKind.LAND:
            raise JournalCorruptionError(
                f"operation {operation_id} ({record.operation_kind.value}) carries an accepted "
                "event — accepted is gated to land (the async-merge handle)"
            )
        outcomes = outcomes_by_op.get(operation_id, [])
        if len(outcomes) > 1:
            roles = ", ".join(o.role.value for o in outcomes)
            raise JournalCorruptionError(
                f"operation {operation_id} carries more than one terminal outcome ({roles})"
            )
        operations[operation_id] = OperationState(
            operation_id=operation_id,
            kind=record.operation_kind,
            prepared=prep,
            accepted=accepted,
            outcome=outcomes[0] if outcomes else None,
        )

    if expected_lineage is None and len(lineages) > 1:
        raise JournalCorruptionError(
            "journal folds events from more than one delivery lineage: "
            + ", ".join(sorted(lineages))
        )
    delivery_lineage = (
        expected_lineage
        if expected_lineage is not None
        else (next(iter(lineages)) if lineages else None)
    )

    deduped_stamps: list[ReadyStampEvent] = []
    stamps_by_key: dict[str, ReadyStampEvent] = {}
    for stamp in sorted(stamps, key=lambda s: (s.created_at, s.comment_id)):
        prior = stamps_by_key.get(stamp.key)
        if prior is None:
            stamps_by_key[stamp.key] = stamp
            deduped_stamps.append(stamp)
            continue
        if prior.canonical_payload != stamp.canonical_payload:
            raise JournalCorruptionError(
                f"conflicting duplicate ready-stamp {stamp.key} events (comments "
                f"{prior.comment_id} and {stamp.comment_id} carry differing payloads)"
            )
        # Byte-identical duplicate: idempotent — first occurrence wins.
    if delivery_lineage is not None:
        for stamp in deduped_stamps:
            if stamp.record.delivery_lineage != delivery_lineage:
                raise JournalCorruptionError(
                    f"ready-stamp {stamp.key} carries foreign delivery_lineage "
                    f"{stamp.record.delivery_lineage!r} (expected {delivery_lineage!r}) — a "
                    "foreign-lineage stamp never silently folds"
                )

    unresolved = tuple(op for op in operations.values() if not op.resolved)
    return JournalFold(
        events=tuple(deduped),
        operations=operations,
        unresolved=unresolved,
        delivery_lineage=delivery_lineage,
        stamps=tuple(deduped_stamps),
    )
