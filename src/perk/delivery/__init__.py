"""The deep delivery module — stacked-delivery train persistence (contracts.md §8.43).

The **train-persistence seam** of the stacked-delivery architecture: the pure operation-journal
layer (:mod:`perk.delivery.journal` — marker grammar, strict records, canonical byte identity,
the fail-closed fold) and the backend-aligned persistence adapter
(:mod:`perk.delivery.persistence` — succession-folding reads, gated read-back appends, the typed
train-state writers). Later delivery nodes add the ``DeliveryTrain`` projection beside these.

Import direction: ``perk.delivery`` imports the ``perk.backends.*`` contracts one-directionally;
nothing in ``perk/backends/`` or ``perk/github/`` imports ``perk.delivery``.
"""

from perk.delivery.journal import (
    JOURNAL_EVENT_MAX_CHARS,
    JOURNAL_SCHEMA_VERSION,
    EventRole,
    JournalCorruptionError,
    JournalEvent,
    JournalFold,
    JournalRecordTooLarge,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
    canonical_payload,
    ensure_event_size,
    fold_events,
    mint_operation_id,
    parse_journal_comment,
    render_event,
)
from perk.delivery.persistence import (
    AppendResult,
    JournalAppendAmbiguous,
    TrainPersistence,
    TrainPersistenceError,
    UnresolvedOperationError,
    resolve_train_persistence,
)

__all__ = [
    "JOURNAL_EVENT_MAX_CHARS",
    "JOURNAL_SCHEMA_VERSION",
    "AppendResult",
    "EventRole",
    "JournalAppendAmbiguous",
    "JournalCorruptionError",
    "JournalEvent",
    "JournalFold",
    "JournalRecordTooLarge",
    "OperationKind",
    "OperationState",
    "OutcomeRecord",
    "PreparedRecord",
    "TrainPersistence",
    "TrainPersistenceError",
    "UnresolvedOperationError",
    "canonical_payload",
    "ensure_event_size",
    "fold_events",
    "mint_operation_id",
    "parse_journal_comment",
    "render_event",
    "resolve_train_persistence",
]
