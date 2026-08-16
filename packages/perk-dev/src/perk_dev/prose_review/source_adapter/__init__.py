"""Public SourceAdapter facade; internal implementations live in sibling modules."""

from perk_dev.prose_review.source_adapter.contract import (
    CheckHintId,
    FocusedSource,
    RangeFailure,
    RangeResolution,
    ReadOnlyReason,
    ResolvedRange,
    SourceAdapter,
    SourceDiagnostic,
    SourceDiagnosticCode,
    SourceExtraction,
    SourceRange,
    SourceReadFailure,
    UnresolvedRange,
    WholeFileSource,
)
from perk_dev.prose_review.source_adapter.read import (
    SourceReadError,
    read_source,
    read_unit_file,
    read_whole_file,
    source_adapter_for,
)

__all__ = [
    "CheckHintId",
    "FocusedSource",
    "RangeFailure",
    "RangeResolution",
    "ReadOnlyReason",
    "ResolvedRange",
    "SourceAdapter",
    "SourceDiagnostic",
    "SourceDiagnosticCode",
    "SourceExtraction",
    "SourceRange",
    "SourceReadError",
    "SourceReadFailure",
    "UnresolvedRange",
    "WholeFileSource",
    "read_source",
    "read_unit_file",
    "read_whole_file",
    "source_adapter_for",
]
