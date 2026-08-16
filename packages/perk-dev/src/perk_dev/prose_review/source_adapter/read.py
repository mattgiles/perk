"""Contained source reads, adapter dispatch, and fragment-focused orchestration.

On the workbench serving path this package is the only reader of canonical source
content. Catalog discovery legitimately reads mapped files once while building the
immutable snapshot; built frontend assets belong to the separate contained-read
family in ``prose_review.web``.
"""

from pathlib import Path

from perk_dev.prose_map.models import Fragment, RoutedUnit
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.source_adapter.contract import (
    FocusedSource,
    ReadOnlyReason,
    SourceAdapter,
    SourceReadFailure,
    UnresolvedRange,
    WholeFileSource,
)
from perk_dev.prose_review.source_adapter.markdown import MarkdownSourceAdapter
from perk_dev.prose_review.source_adapter.python import PythonSourceAdapter
from perk_dev.prose_review.source_adapter.typescript import TypeScriptAdapterUnavailable
from perk_dev.prose_review.source_adapter.yaml import YamlSourceAdapter


class SourceReadError(Exception):
    """A canonical source read was refused or failed, with a closed reason."""

    def __init__(self, reason: SourceReadFailure) -> None:
        super().__init__(reason)
        self.reason: SourceReadFailure = reason


_MARKDOWN_ADAPTER = MarkdownSourceAdapter()
_PYTHON_ADAPTER = PythonSourceAdapter()
_YAML_ADAPTER = YamlSourceAdapter()


def read_unit_file(repo_root: Path, unit: RoutedUnit) -> WholeFileSource:
    """Read a routed unit's whole source file, contained under ``repo_root``."""
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
    """Read one catalog unit's whole source file after membership validation."""
    unit = snapshot.get_unit(unit_id)
    if unit is None:
        raise SourceReadError("unknown_unit")
    return read_unit_file(repo_root, unit)


def source_adapter_for(
    unit: RoutedUnit,
    *,
    typescript_adapter: SourceAdapter | None = None,
) -> SourceAdapter | None:
    """Dispatch by both routed kind and concrete source suffix."""
    suffix = Path(unit.candidate.path).suffix.lower()
    if unit.candidate.kind in ("markdown", "managed-prose") and suffix == ".md":
        return _MARKDOWN_ADAPTER
    if unit.candidate.kind == "ambient-routing" and suffix in (".yaml", ".yml"):
        return _YAML_ADAPTER
    if unit.candidate.kind in ("python-symbol", "managed-prose") and suffix == ".py":
        return _PYTHON_ADAPTER
    if (
        unit.candidate.kind in ("typescript-tool", "typescript-model-call", "typescript-symbol")
        and suffix == ".ts"
    ):
        return typescript_adapter
    return None


def _read_only(
    whole: WholeFileSource,
    *,
    fragment: Fragment | None,
    reason: ReadOnlyReason,
) -> FocusedSource:
    return FocusedSource(
        unit_id=whole.unit_id,
        path=whole.path,
        kind=whole.kind,
        fragment=fragment,
        before="",
        focus=whole.text,
        after="",
        editable=False,
        read_only_reason=reason,
    )


def read_source(
    snapshot: CatalogSnapshot,
    repo_root: Path,
    unit_id: str,
    fragment_id: str | None = None,
    *,
    typescript_adapter: SourceAdapter | None = None,
) -> FocusedSource:
    """Read one whole unit or exact composite fragment target."""
    unit = snapshot.get_unit(unit_id)
    if unit is None:
        raise SourceReadError("unknown_unit")
    routed_fragment = None
    if fragment_id is not None:
        routed_fragment = snapshot.get_fragment(unit_id, fragment_id)
        if routed_fragment is None:
            raise SourceReadError("unknown_fragment")

    whole = read_unit_file(repo_root, unit)
    if routed_fragment is None:
        return _read_only(whole, fragment=None, reason="whole-unit")

    fragment = routed_fragment.fragment
    adapter = source_adapter_for(unit, typescript_adapter=typescript_adapter)
    if adapter is None:
        return _read_only(whole, fragment=fragment, reason="unsupported-family")
    try:
        extraction = adapter.extract(whole.text, fragment.selector)
    except TypeScriptAdapterUnavailable:
        if adapter is not typescript_adapter:
            raise
        return _read_only(whole, fragment=fragment, reason="adapter-unavailable")
    if isinstance(extraction.resolution, UnresolvedRange):
        return _read_only(whole, fragment=fragment, reason=extraction.resolution.reason)
    return FocusedSource(
        unit_id=whole.unit_id,
        path=whole.path,
        kind=whole.kind,
        fragment=fragment,
        before=extraction.before,
        focus=extraction.focus,
        after=extraction.after,
        editable=True,
        read_only_reason=None,
    )
