"""The run-cache session-pointer record (`contracts.md` §8.35).

The cross-run carrier that lets a landed plan identify its planning + implementation Pi session
files from a **different** session without heuristic search. Each run writes only its OWN record,
keyed by ``run_id``, under the **shared main checkout** (the writer resolves
``main_worktree_root(cwd) or cwd``), so a linked-worktree run and a later resolver agree on one
location.

Beside the four class/site evidence slots the record carries ``sessions`` — the run's
resumable-conversation index (one-to-many: a replan reuses the run id), written by the TS
``recordRunSession`` at ``session_start`` and read by ``perk resume RUN_ID``; each entry's ``at``
is Pi's ``toISOString()`` form (``YYYY-MM-DDTHH:mm:ss.sssZ``), validated at this read edge.

Pure cache-tier I/O over an explicit ``root`` — no workflow semantics, no network. The TS twin
(the capture side) is ``extension/substrate/sessionPointers.ts``; both planes read/write the same
``session-pointers.json`` (the cross-plane contract is the *file*). Follows the boundary-model
discipline (§8.34 / :mod:`perk.boundary`): a :class:`LenientParseModel` read edge → frozen
``@dataclass`` domain object. LBYL: absence is a normal, branchable ``None``.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import field_validator

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.state.cache import CacheError, atomic_write_text, run_scratch_dir
from perk.substrate.output import user_output

SESSION_POINTERS_FILE = "session-pointers.json"

# The admissible form of a run-session entry's `at`: JavaScript's `Date.prototype.toISOString()`
# output (fixed width, UTC, millisecond precision) — so lexical ordering is chronological by
# construction. Anything else marks the record corrupt at the read edge.
_AT_FORM = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", re.ASCII)


@dataclass(frozen=True)
class SessionPointer:
    """One captured session pointer (a ``main`` or ``worker`` slot of a class).

    ``pi_session_id`` is the session-file basename (matching the ``perk:workflow-state`` stamp);
    ``session_file`` is the absolute path known at capture (informational); ``parent_pi_session_id``
    preserves fork/replacement provenance (the inherited parent session, else ``None``).
    """

    pi_session_id: str
    session_file: str
    at: str  # ISO-8601 UTC
    parent_pi_session_id: str | None = None


@dataclass(frozen=True)
class SessionClassPointers:
    """The two capture sites of one session class (``main`` = interior, ``worker`` = headless)."""

    main: SessionPointer | None = None
    worker: SessionPointer | None = None


@dataclass(frozen=True)
class RunSessionEntry:
    """One resumable conversation of a run (an entry of the record's ``sessions`` list).

    ``pi_session_id`` is the session file's basename; ``session_file`` its absolute path; ``cwd``
    the session's working directory at start (where ``perk resume RUN_ID`` chdirs before
    ``pi --session``); ``at`` the FIRST-capture time in Pi's ``toISOString()`` form
    (``YYYY-MM-DDTHH:mm:ss.sssZ``) — provenance an in-place update never refreshes.
    """

    pi_session_id: str
    session_file: str
    cwd: str
    at: str


@dataclass(frozen=True)
class SessionPointers:
    """A run's full session-pointer record (``session-pointers.json``).

    Self-keyed by ``run_id``: a planning run fills only ``planning.*``; an implement run fills
    only ``implementation.*``. The four slots are always present (``None`` when unset) so a TS
    read-modify-write merges trivially. ``sessions`` is the run's resumable-conversation index
    (a legacy record without the key reads as ``()``).
    """

    run_id: str
    planning: SessionClassPointers = SessionClassPointers()
    implementation: SessionClassPointers = SessionClassPointers()
    sessions: tuple[RunSessionEntry, ...] = ()


class SessionPointerModel(LenientParseModel):
    """The JSON parse boundary for :class:`SessionPointer`."""

    pi_session_id: str
    session_file: str
    at: str
    parent_pi_session_id: str | None = None

    def to_domain(self) -> SessionPointer:
        return SessionPointer(
            pi_session_id=self.pi_session_id,
            session_file=self.session_file,
            at=self.at,
            parent_pi_session_id=self.parent_pi_session_id,
        )


class SessionClassPointersModel(LenientParseModel):
    """The JSON parse boundary for :class:`SessionClassPointers`."""

    main: SessionPointerModel | None = None
    worker: SessionPointerModel | None = None

    def to_domain(self) -> SessionClassPointers:
        return SessionClassPointers(
            main=self.main.to_domain() if self.main is not None else None,
            worker=self.worker.to_domain() if self.worker is not None else None,
        )


class RunSessionEntryModel(LenientParseModel):
    """The JSON parse boundary for :class:`RunSessionEntry`.

    ``at`` must be the ``toISOString()`` form (:data:`_AT_FORM`) — a format check at the
    boundary, so the selector's lexical newest-wins ordering is chronological by construction; a
    non-conforming value fails validation and the whole record degrades as corrupt.
    """

    pi_session_id: str
    session_file: str
    cwd: str
    at: str

    @field_validator("at", mode="after")
    @classmethod
    def _at_is_iso_string_form(cls, value: str) -> str:
        if _AT_FORM.fullmatch(value) is None:
            raise ValueError(
                f"at={value!r} is not the YYYY-MM-DDTHH:mm:ss.sssZ form Pi's toISOString() emits"
            )
        return value

    def to_domain(self) -> RunSessionEntry:
        return RunSessionEntry(
            pi_session_id=self.pi_session_id,
            session_file=self.session_file,
            cwd=self.cwd,
            at=self.at,
        )


class SessionPointersModel(LenientParseModel):
    """The JSON parse boundary for :class:`SessionPointers` (the on-disk record shape)."""

    run_id: str
    planning: SessionClassPointersModel = SessionClassPointersModel()
    implementation: SessionClassPointersModel = SessionClassPointersModel()
    sessions: tuple[RunSessionEntryModel, ...] = ()

    def to_domain(self) -> SessionPointers:
        return SessionPointers(
            run_id=self.run_id,
            planning=self.planning.to_domain(),
            implementation=self.implementation.to_domain(),
            sessions=tuple(e.to_domain() for e in self.sessions),
        )


def session_pointers_path(root: Path, run_id: str) -> Path:
    """The session-pointers record path for a run (under its scratch dir)."""
    return run_scratch_dir(root, run_id) / SESSION_POINTERS_FILE


def read_session_pointers(root: Path, run_id: str) -> SessionPointers | None:
    """Read + validate a run's session-pointers record, or ``None`` when it is absent/unusable.

    **Never raises** (the cross-run resolver and the ``perk resume RUN_ID`` selector depend on
    it): absence is the normal ``None``, and a corrupt/unreadable record is loud-but-non-fatal — it
    warns to stderr and degrades to ``None`` (→ a ``missing`` resolution, never a guess), mirroring
    ``list_dispatch_records`` and the lenient TS twin ``readSessionPointers``. Every corruption
    class is one boundary: the DECODE stage (invalid UTF-8 — e.g. a torn write — raises
    ``UnicodeDecodeError``, a ``ValueError`` that is NOT a ``JSONDecodeError``), the parse stage
    (bad JSON), the schema stage (a malformed ``sessions[].at``, a missing field →
    ``CacheError``), and the OS.
    """
    path = session_pointers_path(root, run_id)
    if not path.is_file():
        return None
    try:
        with translate_validation_errors(CacheError, source=str(path)):
            return SessionPointersModel.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            ).to_domain()
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, CacheError) as exc:
        user_output(f"warning: skipping unreadable session-pointers record {path}: {exc}")
        return None


def write_session_pointers(root: Path, run_id: str, record: SessionPointers) -> Path:
    """Write a run's session-pointers record (creating the run dir); return its path.

    ``run_id`` is authoritative (it overrides ``record.run_id``), mirroring ``write_dispatch``.
    The capture side is the TS twin; this writer exists for symmetry + Python-side tests/fixtures.
    Key order, indent and trailing newline match the TS ``serialize`` — byte-identical for ASCII
    content only (``json.dumps`` escapes non-ASCII as ``\\uXXXX`` where ``JSON.stringify`` emits
    it raw; the cross-plane contract is the schema, and both readers parse either form).
    """
    directory = run_scratch_dir(root, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SESSION_POINTERS_FILE

    def _slot(p: SessionPointer | None) -> dict[str, object] | None:
        if p is None:
            return None
        return {
            "pi_session_id": p.pi_session_id,
            "session_file": p.session_file,
            "parent_pi_session_id": p.parent_pi_session_id,
            "at": p.at,
        }

    def _entry(e: RunSessionEntry) -> dict[str, object]:
        return {
            "pi_session_id": e.pi_session_id,
            "session_file": e.session_file,
            "cwd": e.cwd,
            "at": e.at,
        }

    payload = {
        "run_id": run_id,
        "planning": {
            "main": _slot(record.planning.main),
            "worker": _slot(record.planning.worker),
        },
        "implementation": {
            "main": _slot(record.implementation.main),
            "worker": _slot(record.implementation.worker),
        },
        "sessions": [_entry(e) for e in record.sessions],
    }
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
    return path
