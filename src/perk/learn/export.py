"""The session JSONL export seam (`contracts.md` §8.35).

Given a resolved session pointer (:class:`perk.state.session_pointers.SessionPointer`), produce a
current-branch JSONL artifact as a faithful **byte copy** of the pointer's captured ``session_file``
— or explicitly report its absence as ``missing``.

The session file IS the JSONL: a Pi session is persisted as an append-only JSONL log (a header line
+ entry lines) under the home agent dir, so it survives worktree deletion and stays a faithful log
on disk. ``/learn`` runs in a later session when the planning + implementation sessions have
finished writing, so reading the on-disk file yields the COMPLETE transcript. We byte-copy rather
than parse-and-reserialize so the artifact preserves the raw log exactly (header ``version``,
compaction/branch-summary entries, abandoned branches, unknown custom entries); parsing/
normalization is a later node's concern.

The stored absolute ``session_file`` is authoritative — the seam never re-derives the path from the
capture cwd (which may be a deleted worktree, and the session dir is cwd-encoded). The export
**degrades to ``missing`` (never raises)**, mirroring ``read_session_pointers``, so it composes with
resolution: a ``found`` resolution whose source file is gone at export time correctly downgrades to
``missing``.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk.state.session_pointers import SessionPointer
from perk.substrate.output import user_output

ExportStatus = Literal["found", "missing"]


@dataclass(frozen=True)
class SessionExport:
    """The outcome of exporting one session's JSONL to a current-branch artifact.

    ``source`` (the copied ``session_file``) and ``artifact`` (the materialized JSONL path) are set
    only when ``found``; both stay ``None`` for ``missing``.
    """

    status: ExportStatus
    source: str | None = None
    artifact: Path | None = None


_MISSING = SessionExport(status="missing")


def export_session_jsonl(pointer: SessionPointer | None, dest: Path) -> SessionExport:
    """Byte-copy ``pointer.session_file`` to ``dest``, or report ``missing`` (never raises).

    ``dest`` is caller-composed (the full target file path): the consumer picks the naming
    convention + destination dir. The copy is faithful (``shutil.copyfile``) so the artifact
    preserves the raw JSONL exactly. Accepts ``SessionPointer | None`` so a consumer can pass a
    resolution's ``.pointer`` directly.

    Degrades to ``missing`` for every absence path: a ``None`` pointer, an empty ``session_file``,
    a source that is not an existing file, or any ``OSError`` during ``mkdir``/copy (warned to
    stderr, loud-but-non-fatal).
    """
    if pointer is None or not pointer.session_file:
        return _MISSING

    source = Path(pointer.session_file)
    if not source.is_file():
        return _MISSING

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    except OSError as exc:
        user_output(f"warning: could not export session JSONL from {source}: {exc}")
        return _MISSING

    return SessionExport(status="found", source=pointer.session_file, artifact=dest)
