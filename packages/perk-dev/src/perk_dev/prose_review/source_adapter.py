"""The Prose Review Workbench's seeded whole-file source adapter.

The exclusivity invariant: on the workbench's serving path — everything after the
snapshot is built, i.e. every per-request read of canonical source content — this
module is the only reader. Catalog *discovery* (``build_catalog(root)`` via
``perk_dev.prose_map.discovery``) legitimately reads mapped sources once at load
time to build the map; that is the catalog module's load-time contract, not a
serving-path read. (``web.read_contained`` reads only built ``dist/`` assets,
which are not canonical sources.)

Every read is root-bound (resolved containment under the repository root) and
text-only (strict UTF-8 decode; no newline translation). Catalog membership is
:func:`read_whole_file`'s check — it refuses unit ids the snapshot does not know;
:func:`read_unit_file` trusts its caller to supply a routed catalog member. This
is the minimal whole-file seed — node 2.2 grows this module into the full adapter
contract (adapter families, fragment-level reads) and converts it to a package.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk_dev.prose_map.models import ProseKind, RoutedUnit
from perk_dev.prose_review.catalog import CatalogSnapshot

type SourceReadFailure = Literal["unknown_unit", "not_found", "not_text"]


class SourceReadError(Exception):
    """A canonical source read was refused or failed, with a closed reason."""

    def __init__(self, reason: SourceReadFailure) -> None:
        super().__init__(reason)
        self.reason: SourceReadFailure = reason


@dataclass(frozen=True)
class WholeFileSource:
    """One canonical unit's whole source file, decoded as text."""

    unit_id: str
    path: str
    kind: ProseKind
    text: str


def read_unit_file(repo_root: Path, unit: RoutedUnit) -> WholeFileSource:
    """Read a routed unit's whole source file, contained under ``repo_root``.

    An absolute candidate path is rejected lexically first: a ``pathlib`` join
    would silently discard the root, so even an in-root absolute path must never
    reach the containment check. The resolution/stat block then mirrors
    ``web.read_contained``'s posture inside one failure boundary — an OS-invalid
    path (embedded NUL → ``ValueError``), a symlink loop, or a read race
    (``OSError``) degrades to ``not_found``; an in-root symlink that resolves
    inside the root is allowed. The strict UTF-8 decode sits OUTSIDE that boundary
    (``UnicodeDecodeError`` is a ``ValueError`` subclass and must map to
    ``not_text``, never be swallowed by the ``not_found`` arm).
    """
    if Path(unit.candidate.path).is_absolute():
        raise SourceReadError("not_found")
    try:
        repo_resolved = repo_root.resolve()
        candidate = (repo_resolved / unit.candidate.path).resolve()
        if not candidate.is_relative_to(repo_resolved):
            raise SourceReadError("not_found")
        if not candidate.is_file():
            raise SourceReadError("not_found")
        raw = candidate.read_bytes()
    except (OSError, ValueError) as exc:
        raise SourceReadError("not_found") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceReadError("not_text") from exc
    return WholeFileSource(
        unit_id=unit.candidate.id,
        path=unit.candidate.path,
        kind=unit.candidate.kind,
        text=text,
    )


def read_whole_file(snapshot: CatalogSnapshot, repo_root: Path, unit_id: str) -> WholeFileSource:
    """Read one catalog unit's whole source file (the membership-checked entry point)."""
    unit = snapshot.get_unit(unit_id)
    if unit is None:
        raise SourceReadError("unknown_unit")
    return read_unit_file(repo_root, unit)
