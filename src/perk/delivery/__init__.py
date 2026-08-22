"""The compact public delivery façade.

The canonical surface is the repository-scoped :class:`Delivery` status, Prepare, Transfer,
Publish, Sync, Recover (operation conclusion plus the cancellation-metadata repair), and Land
(the incremental plan variant plus the atomic objective variant) families over three nominal
aggregate authorities — exactly the twenty-one names below. Every operation module is internal:
pure train projection, layer context/core, capability rows, production adapters, the
journal/persistence machinery, landing readiness and the landing mutation, and post-merge
finalization are module-path concerns only.
"""

from perk.delivery.facade import (
    Delivery,
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    LandRequest,
    LandResult,
    PrepareRequest,
    PrepareResult,
    PublishRequest,
    PublishResult,
    ReadyStampError,
    RecoverRequest,
    RecoverResult,
    StatusRequest,
    StatusResult,
    SyncRequest,
    SyncResult,
    TransferRequest,
    TransferResult,
)
from perk.delivery.observe import resolve_delivery

__all__ = [
    "Delivery",
    "DeliveryError",
    "DeliveryGit",
    "DeliveryGitHub",
    "DeliveryPersistence",
    "LandRequest",
    "LandResult",
    "PrepareRequest",
    "PrepareResult",
    "PublishRequest",
    "PublishResult",
    "ReadyStampError",
    "RecoverRequest",
    "RecoverResult",
    "StatusRequest",
    "StatusResult",
    "SyncRequest",
    "SyncResult",
    "TransferRequest",
    "TransferResult",
    "resolve_delivery",
]
