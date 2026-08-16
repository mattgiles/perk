"""Contained source reads, adapter dispatch, and fragment-focused orchestration.

On the workbench serving path this package is the only reader of canonical source
content. Catalog discovery legitimately reads mapped files once while building the
immutable snapshot; built frontend assets belong to the separate contained-read
family in ``prose_review.web``.
"""

import hashlib
import os
import stat
from pathlib import Path

from perk_dev.prose_map.models import Fragment, RoutedUnit
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.source_adapter.contract import (
    FocusedSource,
    LoadedSource,
    NewlineStyle,
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


def _newline_style(content: bytes) -> NewlineStyle:
    without_crlf = content.replace(b"\r\n", b"")
    present = (
        ("crlf" if b"\r\n" in content else None),
        ("lf" if b"\n" in without_crlf else None),
        ("cr" if b"\r" in without_crlf else None),
    )
    styles = tuple(style for style in present if style is not None)
    if not styles:
        return "none"
    if len(styles) == 1:
        return styles[0]
    return "mixed"


def read_unit_file(repo_root: Path, unit: RoutedUnit) -> WholeFileSource:
    """Read a routed unit's whole source file, contained under ``repo_root``."""
    if Path(unit.candidate.path).is_absolute():
        raise SourceReadError("not_found")
    try:
        repo_resolved = repo_root.resolve()
        candidate = (repo_resolved / unit.candidate.path).resolve()
        if not candidate.is_relative_to(repo_resolved):
            raise SourceReadError("not_found")
        with candidate.open("rb") as stream:
            file_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise SourceReadError("not_found")
            raw = stream.read()
            mode = stat.S_IMODE(file_stat.st_mode)
    except (OSError, ValueError) as exc:
        raise SourceReadError("not_found") from exc
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceReadError("not_text") from exc
    return WholeFileSource(
        unit_id=unit.candidate.id,
        path=unit.candidate.path,
        kind=unit.candidate.kind,
        content=raw,
        mode=mode,
        newline_style=_newline_style(raw),
        load_hash=hashlib.sha256(raw).hexdigest(),
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
    unit: RoutedUnit,
    text: str,
    *,
    fragment: Fragment | None,
    reason: ReadOnlyReason,
) -> FocusedSource:
    return FocusedSource(
        unit_id=unit.candidate.id,
        kind=unit.candidate.kind,
        fragment=fragment,
        before="",
        focus=text,
        after="",
        editable=False,
        read_only_reason=reason,
    )


def project_source(
    snapshot: CatalogSnapshot,
    unit_id: str,
    fragment_id: str | None,
    text: str,
    *,
    typescript_adapter: SourceAdapter | None = None,
) -> FocusedSource:
    """Project one catalog target over supplied text without a canonical read."""
    unit = snapshot.get_unit(unit_id)
    if unit is None:
        raise SourceReadError("unknown_unit")
    routed_fragment = None
    if fragment_id is not None:
        routed_fragment = snapshot.get_fragment(unit_id, fragment_id)
        if routed_fragment is None:
            raise SourceReadError("unknown_fragment")
    if routed_fragment is None:
        return _read_only(unit, text, fragment=None, reason="whole-unit")

    fragment = routed_fragment.fragment
    adapter = source_adapter_for(unit, typescript_adapter=typescript_adapter)
    if adapter is None:
        return _read_only(unit, text, fragment=fragment, reason="unsupported-family")
    try:
        extraction = adapter.extract(text, fragment.selector)
    except TypeScriptAdapterUnavailable:
        if adapter is not typescript_adapter:
            raise
        return _read_only(unit, text, fragment=fragment, reason="adapter-unavailable")
    if isinstance(extraction.resolution, UnresolvedRange):
        return _read_only(unit, text, fragment=fragment, reason=extraction.resolution.reason)
    return FocusedSource(
        unit_id=unit.candidate.id,
        kind=unit.candidate.kind,
        fragment=fragment,
        before=extraction.before,
        focus=extraction.focus,
        after=extraction.after,
        editable=True,
        read_only_reason=None,
    )


def read_source(
    snapshot: CatalogSnapshot,
    repo_root: Path,
    unit_id: str,
    fragment_id: str | None = None,
    *,
    typescript_adapter: SourceAdapter | None = None,
) -> LoadedSource:
    """Load one canonical file and project the requested target over its text."""
    unit = snapshot.get_unit(unit_id)
    if unit is None:
        raise SourceReadError("unknown_unit")
    if fragment_id is not None and snapshot.get_fragment(unit_id, fragment_id) is None:
        raise SourceReadError("unknown_fragment")
    whole = read_unit_file(repo_root, unit)
    view = project_source(
        snapshot,
        unit_id,
        fragment_id,
        whole.text,
        typescript_adapter=typescript_adapter,
    )
    return LoadedSource(file=whole, view=view)
