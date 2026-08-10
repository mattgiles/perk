"""Neutral filesystem primitives shared across the substrate's consumers.

A tiny leaf (stdlib only) so modules that must not import :mod:`perk.state.cache` — e.g. the
delivery plane, whose package ``__init__`` ``state.cache`` itself imports — can still use the
atomic-write seam. ``perk.state.cache`` re-exports :func:`atomic_write_text` from here, so its
existing call sites are unchanged.
"""

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically replace ``path`` with ``content`` (the exterior atomic-write seam).

    Writes a temp file in the same directory (``tempfile.mkstemp`` — same filesystem, so the
    ``os.replace`` is an atomic rename) then swaps it into place; a concurrent reader sees
    either the old bytes or the new bytes, never a torn mix. On any failure the temp file is
    best-effort unlinked and the error re-raised. Failure modes are ``OSError`` for the
    filesystem arms — but even the default UTF-8 encoding raises ``UnicodeEncodeError`` for
    unencodable text (e.g. lone surrogates), and a caller-supplied ``encoding`` can
    additionally surface ``LookupError`` — callers catching only ``OSError`` must not assume
    it covers everything; cleanup covers all of these arms.

    Precondition: ``path.parent`` must exist (the same contract as ``Path.write_text``; every
    call site ``mkdir``s first). Deliberately no ``fsync`` (crash durability is out of scope —
    the target is inter-process tearing of regenerable, gitignored workflow state) and no chmod
    (mkstemp's 0600 is fine for same-user gitignored state) — this is a workflow-scoped writer,
    not a general-purpose one.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
        tmp.replace(path)
    except BaseException:
        # Cleanup-and-re-raise on ANY failure (incl. codec/encoding errors and interrupts) —
        # the broad catch exists only so no failure mode can leave temp residue; the original
        # exception always propagates unchanged.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
