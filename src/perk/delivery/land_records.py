"""The strict read-side parse models for the LAND journal payloads (contracts.md §8.56).

The kind-owned ``before``/``after``/``observed`` mappings the landing operation writes are
decoded here for every read-side consumer — recover's classification, the train projection's
landed-layer coverage join, the finalization-convergence pass, and the reconcile-evidence
assembler. Follows transfer's ``StrictInputModel`` extra-forbid discipline: journal events are
mutable backend state, so a perk-marked payload MUST parse strictly — junk raises
:class:`~perk.delivery.journal.JournalCorruptionError`, never a lenient re-interpretation.
Each caller owns its own fail-closed mapping of that raise (recover → a ``mixed`` row; train
coverage → the ``journal_corruption`` blocker; the convergence pass → a loud skipped-layer
note).

A pure **leaf** module (journal + boundary + stdlib only) so both :mod:`perk.delivery.train`
and :mod:`perk.delivery.landing` can consume it without an import cycle. This module is the
ONE canonical import path for the read models — consumers import ``land_records`` directly,
never a re-export.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BeforeValidator

from perk.boundary import StrictInputModel, translate_validation_errors
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalFold,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
)

# ----------------------------------------------------------------- frozen domain shapes


@dataclass(frozen=True)
class LandPreparedLayer:
    """One recorded land-plan layer (the prepared ``before.layers`` row)."""

    node_id: str
    plan_id: str
    pr_number: int
    base_sha: str
    head_sha: str


@dataclass(frozen=True)
class LandPreparedBefore:
    """The prepared ``before`` payload — exactly the ``LandPlan`` evidence plus the base."""

    mode: Literal["stack_merge_async", "singleton_squash"]
    merge_method: Literal["squash"]
    base: str
    top_pr_number: int
    top_head_sha: str
    layers: tuple[LandPreparedLayer, ...]


@dataclass(frozen=True)
class LandPreparedAfter:
    """The prepared ``after`` payload."""

    merged_pr_numbers: tuple[int, ...]
    base: str


@dataclass(frozen=True)
class LandPrepared:
    """One decoded LAND prepared record (both payload halves)."""

    before: LandPreparedBefore
    after: LandPreparedAfter


@dataclass(frozen=True)
class LandAcceptedObserved:
    """The ``accepted`` handle payload (the verified async-merge options)."""

    uuid: str
    merge_method: str
    merge_action: str
    expected_head_sha: str
    http_status: int


@dataclass(frozen=True)
class LandCompletedLayer:
    """One verified-merged layer row of a ``completed`` payload."""

    pr_number: int
    merge_commit_sha: str


@dataclass(frozen=True)
class LandRemainderPr:
    """One re-observed layer-PR row (the abandon proof / the breach remainder proof)."""

    pr_number: int
    state: str
    head_sha: str


@dataclass(frozen=True)
class LandCompletedObserved:
    """The ``completed`` payload. ``reported_sha`` is required-but-nullable. The additive
    breach fields default so every pre-existing record decodes: ``external_prefix`` marks a
    recorded degraded-atomicity breach (the payload's ``layers`` cover ONLY the externally
    merged contiguous prefix) and ``remainder`` carries the observed OPEN-at-recorded-head
    rows as the acceptance proof."""

    layers: tuple[LandCompletedLayer, ...]
    reported_sha: str | None
    final_base_sha: str
    external_prefix: bool = False
    remainder: tuple[LandRemainderPr, ...] = ()


@dataclass(frozen=True)
class LandAbandonedObserved:
    """The ``abandoned`` payload (reason + bounded detail + the all-before reobservation)."""

    reason: Literal[
        "submit_404", "submit_failed", "submit_rejected", "poll_failed", "recovered_before_state"
    ]
    detail: str
    reobserved: tuple[LandRemainderPr, ...]


# ----------------------------------------------------------------- strict edge models


def _seq_to_tuple(value: object) -> object:
    """The journal read-back materializes YAML sequences as lists; list→tuple is the one
    allowlisted container coercion under strict (mirrors ``boundary.StrTuple``)."""
    return tuple(value) if isinstance(value, list) else value


type _Rows[T] = Annotated[tuple[T, ...], BeforeValidator(_seq_to_tuple)]


class _LandPreparedLayerModel(StrictInputModel):
    node_id: str
    plan_id: str
    pr_number: int
    base_sha: str
    head_sha: str

    def to_domain(self) -> LandPreparedLayer:
        return LandPreparedLayer(
            node_id=self.node_id,
            plan_id=self.plan_id,
            pr_number=self.pr_number,
            base_sha=self.base_sha,
            head_sha=self.head_sha,
        )


class _LandPreparedBeforeModel(StrictInputModel):
    mode: Literal["stack_merge_async", "singleton_squash"]
    merge_method: Literal["squash"]
    base: str
    top_pr_number: int
    top_head_sha: str
    layers: _Rows[_LandPreparedLayerModel]

    def to_domain(self) -> LandPreparedBefore:
        return LandPreparedBefore(
            mode=self.mode,
            merge_method=self.merge_method,
            base=self.base,
            top_pr_number=self.top_pr_number,
            top_head_sha=self.top_head_sha,
            layers=tuple(layer.to_domain() for layer in self.layers),
        )


class _LandPreparedAfterModel(StrictInputModel):
    merged_pr_numbers: _Rows[int]
    base: str

    def to_domain(self) -> LandPreparedAfter:
        return LandPreparedAfter(merged_pr_numbers=self.merged_pr_numbers, base=self.base)


class _LandAcceptedObservedModel(StrictInputModel):
    uuid: str
    merge_method: str
    merge_action: str
    expected_head_sha: str
    http_status: int

    def to_domain(self) -> LandAcceptedObserved:
        return LandAcceptedObserved(
            uuid=self.uuid,
            merge_method=self.merge_method,
            merge_action=self.merge_action,
            expected_head_sha=self.expected_head_sha,
            http_status=self.http_status,
        )


class _LandCompletedLayerModel(StrictInputModel):
    pr_number: int
    merge_commit_sha: str

    def to_domain(self) -> LandCompletedLayer:
        return LandCompletedLayer(pr_number=self.pr_number, merge_commit_sha=self.merge_commit_sha)


class _LandRemainderPrModel(StrictInputModel):
    pr_number: int
    state: str
    head_sha: str

    def to_domain(self) -> LandRemainderPr:
        return LandRemainderPr(pr_number=self.pr_number, state=self.state, head_sha=self.head_sha)


class _LandCompletedObservedModel(StrictInputModel):
    layers: _Rows[_LandCompletedLayerModel]
    reported_sha: str | None  # required-but-nullable
    final_base_sha: str
    external_prefix: bool = False
    remainder: _Rows[_LandRemainderPrModel] = ()

    def to_domain(self) -> LandCompletedObserved:
        return LandCompletedObserved(
            layers=tuple(layer.to_domain() for layer in self.layers),
            reported_sha=self.reported_sha,
            final_base_sha=self.final_base_sha,
            external_prefix=self.external_prefix,
            remainder=tuple(row.to_domain() for row in self.remainder),
        )


class _LandAbandonedObservedModel(StrictInputModel):
    reason: Literal[
        "submit_404", "submit_failed", "submit_rejected", "poll_failed", "recovered_before_state"
    ]
    detail: str
    reobserved: _Rows[_LandRemainderPrModel]

    def to_domain(self) -> LandAbandonedObserved:
        return LandAbandonedObserved(
            reason=self.reason,
            detail=self.detail,
            reobserved=tuple(row.to_domain() for row in self.reobserved),
        )


# ----------------------------------------------------------------- decode functions


def decode_land_prepared(record: PreparedRecord) -> LandPrepared:
    """Strict-decode a LAND prepared record's ``before``/``after`` payloads. Any mismatch —
    wrong kind, missing/extra/mistyped fields — raises ``JournalCorruptionError`` (fail
    closed; the caller maps the raise per its own posture)."""
    if record.operation_kind is not OperationKind.LAND:
        raise JournalCorruptionError(
            f"operation {record.operation_id} is {record.operation_kind.value}, not land"
        )
    where = f"land payload of operation {record.operation_id}"
    with translate_validation_errors(JournalCorruptionError, source=where):
        before = _LandPreparedBeforeModel.model_validate(dict(record.before))
        after = _LandPreparedAfterModel.model_validate(dict(record.after))
    return LandPrepared(before=before.to_domain(), after=after.to_domain())


def decode_land_accepted(
    observed: Mapping[str, object], *, operation_id: str
) -> LandAcceptedObserved:
    """Strict-decode an ``accepted`` handle payload (junk raises, fail closed)."""
    where = f"land accepted payload of operation {operation_id}"
    with translate_validation_errors(JournalCorruptionError, source=where):
        return _LandAcceptedObservedModel.model_validate(dict(observed)).to_domain()


def decode_land_completed(
    observed: Mapping[str, object], *, operation_id: str
) -> LandCompletedObserved:
    """Strict-decode a ``completed`` payload — pre-breach records decode too (the breach
    fields are optional-with-default). Junk raises, fail closed."""
    where = f"land completed payload of operation {operation_id}"
    with translate_validation_errors(JournalCorruptionError, source=where):
        return _LandCompletedObservedModel.model_validate(dict(observed)).to_domain()


def decode_land_abandoned(
    observed: Mapping[str, object], *, operation_id: str
) -> LandAbandonedObserved:
    """Strict-decode an ``abandoned`` payload (junk raises, fail closed)."""
    where = f"land abandoned payload of operation {operation_id}"
    with translate_validation_errors(JournalCorruptionError, source=where):
        return _LandAbandonedObservedModel.model_validate(dict(observed)).to_domain()


# ----------------------------------------------------------------- the prepared⋈completed join


@dataclass(frozen=True)
class JoinedLandLayer:
    """One completed layer row joined to its own operation's prepared layer by
    ``pr_number`` — the shared journal-coverage unit (contracts.md §8.44/§8.56):
    identity + recorded diff bounds from the prepared side, the merge commit from the
    completed side."""

    node_id: str
    plan_id: str
    pr_number: int
    base_sha: str
    head_sha: str
    merge_commit_sha: str


@dataclass(frozen=True)
class CompletedLandJoin:
    """One completed LAND operation's decoded prepared⋈completed join, in fold order
    (delivery order by construction — breach prefix records first, remainder after)."""

    operation_id: str
    completed: LandCompletedObserved
    layers: tuple[JoinedLandLayer, ...]


@dataclass(frozen=True)
class LandJoinFailure:
    """One completed LAND operation that could not decode/join — it contributes NO layers
    (fail closed, whole-operation). Callers map this to their own posture: train → the
    ``journal_corruption`` blocker; evidence assembly → a PARTIAL note; the convergence
    pass → a loud skip note."""

    operation_id: str
    error: str


def join_completed_land_operations(
    fold: JournalFold,
) -> tuple[tuple[CompletedLandJoin, ...], tuple[LandJoinFailure, ...]]:
    """The ONE prepared⋈completed join over a fold's completed LAND operations — the
    load-bearing definition of journal coverage, shared by the train coverage map, the
    reconcile-evidence assembler, and recover's finalization-convergence pass. Pure. Any
    decode failure or unjoined completed row fails that WHOLE operation into the failure
    list (never a partial join)."""
    joins: list[CompletedLandJoin] = []
    failures: list[LandJoinFailure] = []
    for op in fold.operations.values():
        if op.kind is not OperationKind.LAND or op.terminal_role is not EventRole.COMPLETED:
            continue
        prepared_record = op.prepared.record
        outcome = op.outcome.record if op.outcome is not None else None
        try:
            if not isinstance(prepared_record, PreparedRecord) or not isinstance(
                outcome, OutcomeRecord
            ):  # unreachable by fold construction; fail closed
                raise JournalCorruptionError(
                    f"operation {op.operation_id} folds without prepared/outcome records"
                )
            prepared = decode_land_prepared(prepared_record)
            completed = decode_land_completed(outcome.observed, operation_id=op.operation_id)
            prepared_by_pr = {layer.pr_number: layer for layer in prepared.before.layers}
            layers: list[JoinedLandLayer] = []
            for row in completed.layers:
                joined = prepared_by_pr.get(row.pr_number)
                if joined is None:
                    raise JournalCorruptionError(
                        f"operation {op.operation_id}: completed layer PR #{row.pr_number} "
                        "joins no prepared layer"
                    )
                layers.append(
                    JoinedLandLayer(
                        node_id=joined.node_id,
                        plan_id=joined.plan_id,
                        pr_number=joined.pr_number,
                        base_sha=joined.base_sha,
                        head_sha=joined.head_sha,
                        merge_commit_sha=row.merge_commit_sha,
                    )
                )
        except JournalCorruptionError as exc:
            failures.append(LandJoinFailure(operation_id=op.operation_id, error=str(exc)))
            continue
        joins.append(
            CompletedLandJoin(
                operation_id=op.operation_id, completed=completed, layers=tuple(layers)
            )
        )
    return tuple(joins), tuple(failures)
