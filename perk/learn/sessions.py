"""Cross-run session-pointer resolution (`contracts.md` §8.35).

Resolve a landed plan's planning + implementation Pi session pointers from a **different**
session (later, or another worktree) **without heuristic search**:

    plan_id
      → resolve_issue_backend(repo_root).get_plan(...).header
      → {run_id (planning), impl_run_ids (implementation)}
      → main checkout (main_worktree_root(repo_root) or repo_root)
      → read each run's session-pointers record → per-role found/missing

Missing/GC'd pointers degrade to a ``missing`` status, never a guess. ``ResolvedSessions`` is a
frozen domain object; its ``OutputModel`` serialization is a later concern (there is no ``--json``
surface here, so it is intentionally absent). ``ambiguous`` is reserved for the future source-level
manifest and is unused here — this resolver yields only ``found``/``missing``.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk.backends import resolve
from perk.state.session_pointers import (
    SessionPointer,
    SessionPointers,
    read_session_pointers,
)
from perk.substrate.git import main_worktree_root

ResolutionStatus = Literal["found", "missing"]


@dataclass(frozen=True)
class SessionResolution:
    """A single session-slot resolution: ``found`` with a pointer, or ``missing`` with none."""

    status: ResolutionStatus
    pointer: SessionPointer | None = None


@dataclass(frozen=True)
class ImplementationRun:
    """One implementation run (one ``impl_run_ids`` entry) and its two capture-site slots."""

    run_id: str
    main: SessionResolution
    worker: SessionResolution


@dataclass(frozen=True)
class ResolvedSessions:
    """The cross-run resolution of a plan's planning + implementation session pointers.

    ``implementation`` carries one :class:`ImplementationRun` per ``impl_run_ids`` entry (header
    order); ``()`` when the plan was never submitted (empty linkage).
    """

    plan_id: str
    planning_run_id: str | None
    planning_main: SessionResolution
    planning_worker: SessionResolution
    implementation: tuple[ImplementationRun, ...]


_MISSING = SessionResolution(status="missing", pointer=None)


def _resolve_slot(pointer: SessionPointer | None) -> SessionResolution:
    """A present pointer is ``found``; a null slot (or absent record) is ``missing``."""
    if pointer is None:
        return _MISSING
    return SessionResolution(status="found", pointer=pointer)


def resolve_plan_sessions(repo_root: Path, plan_id: str) -> ResolvedSessions:
    """Resolve ``plan_id``'s planning + implementation session pointers cross-run.

    Every degrade path yields ``missing`` (never raises for a missing plan/header/run_id/record):
    a plan that doesn't exist, a header lacking ``run_id``/``impl_run_ids``, a GC'd or absent
    record file, or a null slot all surface as ``missing`` for the affected role.
    """
    main = main_worktree_root(repo_root) or repo_root
    backend = resolve.resolve_issue_backend(repo_root)
    state = backend.get_plan(issue_id=plan_id)
    header: dict[str, object] = state.header if state is not None else {}

    planning_run_id = _header_str(header.get("run_id"))
    planning_record = _record_for(main, planning_run_id)
    planning_main = _resolve_slot(planning_record.planning.main if planning_record else None)
    planning_worker = _resolve_slot(planning_record.planning.worker if planning_record else None)

    impl_runs: list[ImplementationRun] = []
    for impl_run_id in _header_str_list(header.get("impl_run_ids")):
        record = _record_for(main, impl_run_id)
        impl_runs.append(
            ImplementationRun(
                run_id=impl_run_id,
                main=_resolve_slot(record.implementation.main if record else None),
                worker=_resolve_slot(record.implementation.worker if record else None),
            )
        )

    return ResolvedSessions(
        plan_id=plan_id,
        planning_run_id=planning_run_id,
        planning_main=planning_main,
        planning_worker=planning_worker,
        implementation=tuple(impl_runs),
    )


def _record_for(main: Path, run_id: str | None) -> SessionPointers | None:
    """Read a run's session-pointers record under the main checkout; ``None`` without a run_id."""
    if not run_id:
        return None
    return read_session_pointers(main, run_id)


def _header_str(value: object) -> str | None:
    """A non-empty string header value, else ``None`` (the header is backend-owned/untrusted)."""
    return value if isinstance(value, str) and value else None


def _header_str_list(value: object) -> list[str]:
    """The string entries of a list-valued header field; ``[]`` for anything else."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
