"""perk's ``learn`` evidence-bundle subsystem (`contracts.md` §8.35).

Cross-run resolution of a landed plan's session-grounded evidence. Today this is the
session-pointer resolver (:mod:`perk.learn.sessions`) plus the session-export seam
(:mod:`perk.learn.export`), which materializes a resolved pointer's session JSONL as a faithful
current-branch byte copy; the bundle manifest CLI + render are future consumers built on top of
them.
"""

from perk.learn.evidence import (
    DocEntry,
    EvidenceBundle,
    EvidenceSource,
    SourceStatus,
    gather_evidence,
    scan_existing_docs,
)
from perk.learn.export import (
    ExportStatus,
    SessionExport,
    export_session_jsonl,
)
from perk.learn.sessions import (
    ImplementationRun,
    ResolvedSessions,
    SessionResolution,
    resolve_plan_sessions,
)

__all__ = [
    "DocEntry",
    "EvidenceBundle",
    "EvidenceSource",
    "ExportStatus",
    "ImplementationRun",
    "ResolvedSessions",
    "SessionExport",
    "SessionResolution",
    "SourceStatus",
    "export_session_jsonl",
    "gather_evidence",
    "resolve_plan_sessions",
    "scan_existing_docs",
]
