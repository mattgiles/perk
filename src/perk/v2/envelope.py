"""The strict wire models of the v2 door envelope (contracts.md §8.77).

The TypeScript host prints exactly one envelope per call (``extension/pi/v2/door/envelope.ts``);
these models are its Python twin. JSON keys are camelCase (the alias generator) and fields are
snake_case. Every model is strict and closed: an unknown key, a wrong type, a missing explicit
``null`` or a broken outcome↔verb pairing fails validation, and ``parse_envelope`` translates any
failure into ``EnvelopeError``. The committed goldens under ``extension/pi/v2/door/golden/`` pin
the shape both planes agree on.

There is no domain dataclass behind these models: the door's only consumers — the human renderer
and the exit-code map — read the frozen validated model directly.
"""

import json
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic.alias_generators import to_camel

from perk.boundary import StrictInputModel, StrTuple, format_validation_error

type Verb = Literal["start", "run", "status", "reply", "cancel"]
type WaitReason = Literal[
    "pending_decision",
    "unmet_prerequisite",
    "assignment_incomplete",
    "repair_required",
    "parked",
    "blocked",
    "sleeping",
    "cancelled",
    "completed",
]
# Every wait reason but the two terminal states, which are snapshot states of their own.
type WaitingReason = Literal[
    "pending_decision",
    "unmet_prerequisite",
    "assignment_incomplete",
    "repair_required",
    "parked",
    "blocked",
    "sleeping",
]
type RefusalReason = Literal[
    "invalid_input",
    "unknown_decision",
    "stale_subject",
    "superseded",
    "cancelled",
    "duplicate_conflict",
    "invalid_report",
    "snapshot_tampered",
    "already_started",
]
type RepairCause = Literal[
    "instructions_unrenderable", "capability_missing", "snapshot_tampered", "duplicate_conflict"
]
type SubmissionStatus = Literal["queued", "placed", "done", "unanswered"]
type MismatchField = Literal[
    "recordVersion",
    "definitions",
    "policyVersion",
    "durableVersion",
    "chordVersion",
    "workspace",
    "executionKind",
    "manifest_missing",
]

_OBSERVING_VERBS: frozenset[str] = frozenset({"start", "run", "reply"})


def _list_to_tuple(value: object) -> object:
    """JSON arrays arrive as lists; list→tuple is the one allowlisted container coercion under
    strict (mirrors ``boundary.StrTuple``)."""
    return tuple(value) if isinstance(value, list) else value


type _Epoch = Annotated[int, Field(ge=1)]
type _Count = Annotated[int, Field(ge=0)]


class _Wire(StrictInputModel):
    """Strict, frozen, closed — with camelCase JSON keys over snake_case fields."""

    model_config = ConfigDict(alias_generator=to_camel)


# ── endings ─────────────────────────────────────────────────────────────────────────────────────


class AcceptedEnding(_Wire):
    end: Literal["accepted"]
    outcome_id: str


class IncompleteEnding(_Wire):
    end: Literal["incomplete"]
    submission: SubmissionStatus
    reason: str | None
    refusal: RefusalReason | None


class RepairEnding(_Wire):
    end: Literal["repair"]
    cause: RepairCause
    detail: str


type AttemptEnding = Annotated[
    AcceptedEnding | IncompleteEnding | RepairEnding, Field(discriminator="end")
]


# ── the view snapshot ───────────────────────────────────────────────────────────────────────────


class _ObservationView(_Wire):
    seq: _Epoch
    repo: str
    ref: str
    commit: str
    tree: str
    manifest_digest: str
    observed_at: _Count
    age_ms: _Count


class _AttemptView(_Wire):
    attempt_id: str
    ordinal: Annotated[int, Field(ge=1)]
    outcome_id: str | None
    ending: AttemptEnding | None


class _AssignmentView(_Wire):
    assignment_id: str
    role: str
    subject_digest: str
    current: bool
    accepted_outcome_id: str | None
    attempts: Annotated[tuple[_AttemptView, ...], BeforeValidator(_list_to_tuple)]


class _DecisionView(_Wire):
    decision_id: str
    subject_digest: str
    allowed_actions: StrTuple
    actor: str


class _CancellationView(_Wire):
    reason: str


class _Diagnostics(_Wire):
    runnable: bool
    blocked: _Count
    parked: _Count
    sleeping: _Count


class ViewSnapshot(_Wire):
    """The status snapshot of a consistent view: its state, the latest observation, every
    assignment, the open decision, the cancellation and the live diagnostics."""

    state: Literal["running", "waiting", "completed", "cancelled"]
    wait_reason: WaitingReason | None
    observation: _ObservationView | None
    assignments: Annotated[tuple[_AssignmentView, ...], BeforeValidator(_list_to_tuple)]
    decision: _DecisionView | None
    cancellation: _CancellationView | None
    diagnostics: _Diagnostics

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.wait_reason is None) == (self.state == "waiting"):
            raise ValueError("wait_reason is set exactly when state is waiting")
        if self.state == "cancelled" and self.cancellation is None:
            raise ValueError("a cancelled snapshot carries its cancellation")
        if self.wait_reason == "pending_decision" and self.decision is None:
            raise ValueError("a pending_decision snapshot carries its decision")
        return self


class MarkerSnapshot(_Wire):
    """The snapshot of an outcome that saw no consistent view."""

    state: Literal["incompatible", "uncertain"]


# ── receipt, refusal, mismatch, error ───────────────────────────────────────────────────────────


class _ContinuationView(_Wire):
    op_id: str
    task_id: _Count


class _ReceiptView(_Wire):
    op_id: str
    kind: Literal["reply", "cancellation"]
    continuation: _ContinuationView | None

    @model_validator(mode="after")
    def _continuation_iff_reply(self) -> Self:
        if (self.kind == "reply") != (self.continuation is not None):
            raise ValueError("a reply receipt carries its continuation, a cancellation none")
        return self


class _RefusalView(_Wire):
    reason: RefusalReason
    detail: str


class _MismatchView(_Wire):
    field: MismatchField
    expected: JsonValue
    found: JsonValue


class _ErrorView(_Wire):
    message: str


# ── the seven envelope variants ─────────────────────────────────────────────────────────────────


def _require_receipt_for(verb: str, receipt: _ReceiptView | None) -> None:
    """The receipt is the verb's own: a reply's on ``reply``, a cancellation's on ``cancel``,
    none otherwise."""
    expected = {"reply": "reply", "cancel": "cancellation"}.get(verb)
    if expected is None:
        if receipt is not None:
            raise ValueError(f"a {verb} envelope carries no receipt")
        return
    if receipt is None:
        raise ValueError(f"a {verb} envelope carries its receipt")
    if receipt.kind != expected:
        raise ValueError(f"a {verb} envelope carries a {expected} receipt, not {receipt.kind}")


class OkEnvelope(_Wire):
    envelope: Literal[1]
    outcome: Literal["ok"]
    verb: Verb
    execution_id: str
    epoch: _Epoch
    status: ViewSnapshot
    receipt: _ReceiptView | None
    refusal: None
    mismatch: None
    error: None

    @model_validator(mode="after")
    def _paired(self) -> Self:
        _require_receipt_for(self.verb, self.receipt)
        if self.verb != "status":
            if self.status.state == "running":
                raise ValueError(f"a quiescent {self.verb} is never running")
            if self.status.wait_reason == "pending_decision":
                raise ValueError(f"a {self.verb} waiting on a decision is pending_decision")
        return self


class PendingDecisionEnvelope(_Wire):
    envelope: Literal[1]
    outcome: Literal["pending_decision"]
    verb: Verb
    execution_id: str
    epoch: _Epoch
    status: ViewSnapshot
    receipt: _ReceiptView | None
    refusal: None
    mismatch: None
    error: None

    @model_validator(mode="after")
    def _paired(self) -> Self:
        if self.verb not in _OBSERVING_VERBS:
            raise ValueError(f"pending_decision is never a {self.verb} outcome")
        if self.status.state != "waiting" or self.status.wait_reason != "pending_decision":
            raise ValueError("a pending_decision envelope's snapshot waits on its decision")
        _require_receipt_for(self.verb, self.receipt)
        return self


class OwnerBusyEnvelope(_Wire):
    envelope: Literal[1]
    outcome: Literal["owner_busy"]
    verb: Verb
    execution_id: str
    epoch: _Epoch
    status: None
    receipt: None
    refusal: None
    mismatch: None
    error: None


class IncompatibleEnvelope(_Wire):
    envelope: Literal[1]
    outcome: Literal["incompatible"]
    verb: Verb
    execution_id: str
    epoch: _Epoch | None
    status: MarkerSnapshot
    receipt: None
    refusal: None
    mismatch: _MismatchView
    error: None

    @model_validator(mode="after")
    def _marker(self) -> Self:
        if self.status.state != "incompatible":
            raise ValueError("an incompatible envelope carries the incompatible marker")
        return self


class ObservationFailedEnvelope(_Wire):
    envelope: Literal[1]
    outcome: Literal["observation_failed"]
    verb: Verb
    execution_id: str
    epoch: _Epoch
    status: None
    receipt: None
    refusal: None
    mismatch: None
    error: _ErrorView

    @model_validator(mode="after")
    def _paired(self) -> Self:
        if self.verb not in _OBSERVING_VERBS:
            raise ValueError(f"{self.verb} never observes")
        return self


class RefusedEnvelope(_Wire):
    envelope: Literal[1]
    outcome: Literal["refused"]
    verb: Verb
    execution_id: str
    epoch: _Epoch
    status: None
    receipt: None
    refusal: _RefusalView
    mismatch: None
    error: None

    @model_validator(mode="after")
    def _paired(self) -> Self:
        if self.verb == "status":
            raise ValueError("status is never refused")
        return self


class UncertainEnvelope(_Wire):
    envelope: Literal[1]
    outcome: Literal["uncertain"]
    verb: Verb
    execution_id: str
    epoch: _Epoch
    status: MarkerSnapshot
    receipt: None
    refusal: None
    mismatch: None
    error: _ErrorView

    @model_validator(mode="after")
    def _marker(self) -> Self:
        if self.status.state != "uncertain":
            raise ValueError("an uncertain envelope carries the uncertain marker")
        return self


type Envelope = Annotated[
    OkEnvelope
    | PendingDecisionEnvelope
    | OwnerBusyEnvelope
    | IncompatibleEnvelope
    | ObservationFailedEnvelope
    | RefusedEnvelope
    | UncertainEnvelope,
    Field(discriminator="outcome"),
]

_ENVELOPE: TypeAdapter[Envelope] = TypeAdapter(Envelope)


class EnvelopeError(Exception):
    """The host's stdout is not one valid envelope for the requested verb and execution."""


def parse_envelope(stdout: str, *, verb: Verb, execution_id: str) -> Envelope:
    """Validate the host's stdout as the envelope of ``verb`` over ``execution_id``.

    Raises ``EnvelopeError`` for non-JSON, a non-object, any model violation, or an envelope
    naming another verb or execution.
    """
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise EnvelopeError(f"v2 envelope: not JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise EnvelopeError("v2 envelope: not a JSON object")
    try:
        envelope = _ENVELOPE.validate_python(raw)
    except ValidationError as exc:
        raise EnvelopeError(format_validation_error(exc, source="v2 envelope")) from exc
    if envelope.verb != verb:
        raise EnvelopeError(f"v2 envelope: verb {envelope.verb!r}, not the requested {verb!r}")
    if envelope.execution_id != execution_id:
        raise EnvelopeError(
            f"v2 envelope: execution {envelope.execution_id!r}, not the requested {execution_id!r}"
        )
    return envelope
