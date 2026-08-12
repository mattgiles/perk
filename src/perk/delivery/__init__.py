"""The deep delivery module — stacked-delivery train persistence + the read path
(contracts.md §8.43/§8.44).

The stacked-delivery architecture's deep module: the pure operation-journal layer
(:mod:`perk.delivery.journal` — marker grammar, strict records, canonical byte identity, the
fail-closed fold), the backend-aligned persistence adapter (:mod:`perk.delivery.persistence` —
succession-folding reads, gated read-back appends, the typed train-state writers), the
immutable ``DeliveryTrain`` projection (:mod:`perk.delivery.train` — pure reconstruction over
narrow probe Protocols, blockers-vs-information classification), and its production wiring
(:mod:`perk.delivery.observe` — the Git/GitHub probes + ``resolve_train_reads``), the
stacked-authoring capability preflight (:mod:`perk.delivery.capability` — the §8.45
composed capability checks the ``objective create`` cold door runs before a stacked save),
the layer publication operation (:mod:`perk.delivery.publish` — the §8.47 exact-lease
publish `/submit` routes a stacked plan through), and the idempotent post-merge land
finalization (:mod:`perk.delivery.finalize` — the four durable bookkeeping effects
`perk pr land` performs per merged plan, reusable per stacked layer; reconstructed inputs
only, never the worktree cache).

Import direction: ``perk.delivery`` imports the ``perk.backends.*`` contracts one-directionally
(and only :mod:`perk.delivery.observe`, :mod:`perk.delivery.capability`,
:mod:`perk.delivery.layer`, :mod:`perk.delivery.publish`, :mod:`perk.delivery.continuation`,
:mod:`perk.delivery.sync`, and :mod:`perk.delivery.finalize` touch ``perk.substrate`` /
``perk.github``); nothing in ``perk/backends/`` or ``perk/github/`` imports ``perk.delivery``,
and nothing here imports ``perk.state`` or the Linear agent module (``state/cache.py`` imports
:mod:`perk.delivery.layer` at module scope — the atomic-write seam is reached through
``perk.substrate.fs`` instead; the agent activity emission is a worktree-session-scoped caller
concern, kept out of :mod:`perk.delivery.finalize`).
"""

from perk.delivery.capability import (
    CapabilityCheck,
    CapabilityReport,
    preflight_stacked_authoring,
    probe_atomic_push_urls,
)
from perk.delivery.continuation import (
    ContinuationLayer,
    ContinuationManifest,
    PendingContinuation,
    continuations_dir,
    manifest_path,
    pending_continuation,
    write_manifest,
)
from perk.delivery.finalize import (
    LandedPlan,
    LandFinalization,
    LearnConsumeUpdate,
    ObjectiveLandUpdate,
    finalize_landed_plan,
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
from perk.delivery.layer import (
    LayerContext,
    LayerContextOut,
    LayerError,
    PreparedLayerStart,
    derive_layer_context,
    prepare_layer_start,
    require_ready_layer,
    require_reviewable_layer,
)
from perk.delivery.observe import (
    GatewayGitHubProbe,
    RepoGitProbe,
    TrainReads,
    reconstruct_repo_train,
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
from perk.delivery.publish import (
    DeliveryOperationFacts,
    LayerBodyFacts,
    PublicationError,
    PublicationResult,
    TrainRowFacts,
    publish_layer,
)
from perk.delivery.sync import (
    ClaimedLayer,
    RemoteWriterProbe,
    SyncCascade,
    SyncedLayer,
    SyncError,
    SyncResult,
    WriterObservationError,
    derive_claimed_prefix,
    synchronize_train,
)
from perk.delivery.train import (
    NO_TRAIN_INCREMENTAL_REASON,
    STRUCTURAL_BLOCKER_CODES,
    BaseHeadObservation,
    BuildReadiness,
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
    "STRUCTURAL_BLOCKER_CODES",
    "AppendResult",
    "BaseHeadObservation",
    "BuildReadiness",
    "CapabilityCheck",
    "CapabilityReport",
    "ClaimedLayer",
    "ContinuationLayer",
    "ContinuationManifest",
    "DeliveryOperationFacts",
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
    "LandFinalization",
    "LandedPlan",
    "LayerBodyFacts",
    "LayerContext",
    "LayerContextOut",
    "LayerError",
    "LayerFinalization",
    "LayerGit",
    "LayerIntent",
    "LayerMembership",
    "LayerPr",
    "LayerPublication",
    "LayerWriter",
    "LearnConsumeUpdate",
    "NoDeliveryTrain",
    "ObjectiveLandUpdate",
    "ObjectiveReader",
    "OperationKind",
    "OperationState",
    "OutcomeRecord",
    "PendingContinuation",
    "PlanReader",
    "PrFactsView",
    "PreparedLayerStart",
    "PreparedRecord",
    "PublicationError",
    "PublicationResult",
    "RemoteWriterProbe",
    "RepoGitProbe",
    "StackEntryView",
    "StackView",
    "SyncCascade",
    "SyncError",
    "SyncResult",
    "SyncedLayer",
    "TrainFinding",
    "TrainLayer",
    "TrainPersistence",
    "TrainPersistenceError",
    "TrainReads",
    "TrainReconstructionError",
    "TrainRowFacts",
    "TrainStatus",
    "UnresolvedOperationError",
    "UnresolvedOperationFacts",
    "WorktreeFacts",
    "WriterObservationError",
    "canonical_payload",
    "continuations_dir",
    "derive_claimed_prefix",
    "derive_layer_context",
    "ensure_event_size",
    "finalize_landed_plan",
    "fold_events",
    "manifest_path",
    "mint_operation_id",
    "parse_journal_comment",
    "pending_continuation",
    "preflight_stacked_authoring",
    "prepare_layer_start",
    "probe_atomic_push_urls",
    "publish_layer",
    "reconstruct_repo_train",
    "reconstruct_train",
    "render_event",
    "require_ready_layer",
    "require_reviewable_layer",
    "resolve_train_persistence",
    "resolve_train_reads",
    "synchronize_train",
    "write_manifest",
]
