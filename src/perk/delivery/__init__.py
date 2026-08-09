"""The deep delivery module — stacked-delivery train persistence + the read path
(contracts.md §8.43/§8.44).

The stacked-delivery architecture's deep module: the pure operation-journal layer
(:mod:`perk.delivery.journal` — marker grammar, strict records, canonical byte identity, the
fail-closed fold), the backend-aligned persistence adapter (:mod:`perk.delivery.persistence` —
succession-folding reads, gated read-back appends, the typed train-state writers), the
immutable ``DeliveryTrain`` projection (:mod:`perk.delivery.train` — pure reconstruction over
narrow probe Protocols, blockers-vs-information classification), and its production wiring
(:mod:`perk.delivery.observe` — the Git/GitHub probes + ``resolve_train_reads``), and the
stacked-authoring capability preflight (:mod:`perk.delivery.capability` — the §8.45
composed capability checks the ``objective create`` cold door runs before a stacked save).

Import direction: ``perk.delivery`` imports the ``perk.backends.*`` contracts one-directionally
(and only :mod:`perk.delivery.observe` + :mod:`perk.delivery.capability` touch
``perk.substrate.git`` / ``perk.github``); nothing in ``perk/backends/`` or ``perk/github/``
imports ``perk.delivery``.
"""

from perk.delivery.capability import (
    CapabilityCheck,
    CapabilityReport,
    preflight_stacked_authoring,
)
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
from perk.delivery.observe import (
    GatewayGitHubProbe,
    RepoGitProbe,
    TrainReads,
    resolve_train_reads,
)
from perk.delivery.persistence import (
    AppendResult,
    JournalAppendAmbiguous,
    TrainPersistence,
    TrainPersistenceError,
    UnresolvedOperationError,
    resolve_train_persistence,
)
from perk.delivery.train import (
    NO_TRAIN_INCREMENTAL_REASON,
    DeliveryTrain,
    FindingKind,
    GitHubProbe,
    GitProbe,
    JournalReader,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    NoDeliveryTrain,
    ObjectiveReader,
    PlanReader,
    PrFactsView,
    StackEntryView,
    StackView,
    TrainFinding,
    TrainLayer,
    TrainReconstructionError,
    TrainStatus,
    UnresolvedOperationFacts,
    WorktreeFacts,
    reconstruct_train,
)

__all__ = [
    "JOURNAL_EVENT_MAX_CHARS",
    "JOURNAL_SCHEMA_VERSION",
    "NO_TRAIN_INCREMENTAL_REASON",
    "AppendResult",
    "CapabilityCheck",
    "CapabilityReport",
    "DeliveryTrain",
    "EventRole",
    "FindingKind",
    "GatewayGitHubProbe",
    "GitHubProbe",
    "GitProbe",
    "JournalAppendAmbiguous",
    "JournalCorruptionError",
    "JournalEvent",
    "JournalFold",
    "JournalReader",
    "JournalRecordTooLarge",
    "LayerFinalization",
    "LayerGit",
    "LayerIntent",
    "LayerMembership",
    "LayerPr",
    "LayerPublication",
    "LayerWriter",
    "NoDeliveryTrain",
    "ObjectiveReader",
    "OperationKind",
    "OperationState",
    "OutcomeRecord",
    "PlanReader",
    "PrFactsView",
    "PreparedRecord",
    "RepoGitProbe",
    "StackEntryView",
    "StackView",
    "TrainFinding",
    "TrainLayer",
    "TrainPersistence",
    "TrainPersistenceError",
    "TrainReads",
    "TrainReconstructionError",
    "TrainStatus",
    "UnresolvedOperationError",
    "UnresolvedOperationFacts",
    "WorktreeFacts",
    "canonical_payload",
    "ensure_event_size",
    "fold_events",
    "mint_operation_id",
    "parse_journal_comment",
    "preflight_stacked_authoring",
    "reconstruct_train",
    "render_event",
    "resolve_train_persistence",
    "resolve_train_reads",
]
