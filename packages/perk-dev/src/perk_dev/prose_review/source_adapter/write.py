"""Safe whole-buffer persistence for admitted catalog-mapped source families."""

import hashlib
import os
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk_dev.prose_map.models import RoutedUnit
from perk_dev.prose_review.catalog import CatalogSnapshot, LineageView
from perk_dev.prose_review.checks import CHECK_COMMANDS
from perk_dev.prose_review.source_adapter.contract import (
    CheckHintId,
    SourceAdapter,
    SourceDiagnostic,
    WholeFileSource,
)
from perk_dev.prose_review.source_adapter.read import _newline_style, source_adapter_for
from perk_dev.prose_review.source_adapter.typescript import TypeScriptAdapterUnavailable

type SourceRefusalReason = Literal[
    "unsupported-family",
    "unsafe-path",
    "unsafe-lineage",
    "source-unavailable",
    "write-failed",
    "catalog-stale",
]
CONFLICT_DETAIL = "Source changed on disk. The workbench did not overwrite it."
CATALOG_STALE_DETAIL = (
    "The file was saved, but the catalog could not be refreshed. Further saves are disabled. "
    "Copy any remaining edits, repair or revert the saved source outside the workbench if the "
    "catalog is invalid, then relaunch."
)

_REFUSAL_DETAILS: dict[SourceRefusalReason, str] = {
    "unsupported-family": "Save support has not landed for this source family.",
    "unsafe-path": "The catalog source path is not safe to write.",
    "unsafe-lineage": "Generated source files cannot be saved from the workbench.",
    "source-unavailable": "The canonical source is unavailable.",
    "write-failed": "The source could not be saved safely.",
    "catalog-stale": CATALOG_STALE_DETAIL,
}


@dataclass(frozen=True, slots=True)
class SuggestedCheck:
    """One named post-save check handoff, displayed with its allowlisted command.

    Saves never auto-run anything: execution exists only via the explicit
    allowlisted CheckRunner on user action, and the display string is sourced from
    the same :data:`~perk_dev.prose_review.checks.CHECK_COMMANDS` table the runner
    executes — display and execution can never drift.
    """

    id: CheckHintId
    command: str


@dataclass(frozen=True, slots=True)
class SourceSaved:
    status: Literal["saved"]
    source: WholeFileSource
    materialized: tuple[LineageView, ...]
    checks: tuple[SuggestedCheck, ...]
    catalog_refreshed: bool
    refresh_detail: str | None

    def __post_init__(self) -> None:
        if self.catalog_refreshed != (self.refresh_detail is None):
            raise ValueError("catalog refresh detail must identify only a failed refresh")


@dataclass(frozen=True, slots=True)
class SourceValidationFailed:
    status: Literal["validation-failed"]
    diagnostics: tuple[SourceDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class SourceConflict:
    status: Literal["conflict"]
    detail: str


@dataclass(frozen=True, slots=True)
class SourceRefused:
    status: Literal["refused"]
    reason: SourceRefusalReason
    detail: str


type SourceSaveResult = SourceSaved | SourceValidationFailed | SourceConflict | SourceRefused


@dataclass(frozen=True, slots=True)
class _TargetSample:
    path: Path
    content: bytes
    mode: int
    load_hash: str


class _TargetRefusal(Exception):
    def __init__(self, reason: Literal["unsafe-path", "source-unavailable"]) -> None:
        super().__init__(reason)
        self.reason = reason


def _refused(reason: SourceRefusalReason) -> SourceRefused:
    return SourceRefused(status="refused", reason=reason, detail=_REFUSAL_DETAILS[reason])


def _conflict() -> SourceConflict:
    return SourceConflict(status="conflict", detail=CONFLICT_DETAIL)


def _mapped_write_set(
    snapshot: CatalogSnapshot,
    requested: RoutedUnit,
    *,
    typescript_adapter: SourceAdapter | None = None,
) -> tuple[tuple[RoutedUnit, ...], SourceAdapter] | None:
    mapped = snapshot.units_for_path(requested.candidate.path)
    if not mapped or requested not in mapped:
        return None
    adapters = tuple(
        source_adapter_for(unit, typescript_adapter=typescript_adapter) for unit in mapped
    )
    shared = adapters[0]
    if shared is None or any(adapter is not shared for adapter in adapters):
        return None
    return mapped, shared


def _catalog_path(repo_resolved: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or not relative.parts:
        raise _TargetRefusal("unsafe-path")
    if any(part in ("", ".", "..") for part in relative.parts):
        raise _TargetRefusal("unsafe-path")

    candidate = repo_resolved
    for index, part in enumerate(relative.parts):
        candidate /= part
        try:
            entry_stat = candidate.lstat()
        except OSError as exc:
            raise _TargetRefusal("source-unavailable") from exc
        if stat.S_ISLNK(entry_stat.st_mode):
            raise _TargetRefusal("unsafe-path")
        if index < len(relative.parts) - 1:
            if not stat.S_ISDIR(entry_stat.st_mode):
                raise _TargetRefusal("unsafe-path")
        elif not stat.S_ISREG(entry_stat.st_mode):
            raise _TargetRefusal("source-unavailable")

    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise _TargetRefusal("source-unavailable") from exc
    if not resolved.is_relative_to(repo_resolved):
        raise _TargetRefusal("unsafe-path")
    return resolved


def _sample_target(repo_resolved: Path, relative_text: str) -> _TargetSample:
    candidate = _catalog_path(repo_resolved, relative_text)
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise _TargetRefusal("source-unavailable") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise _TargetRefusal("source-unavailable")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        content = b"".join(chunks)
        return _TargetSample(
            path=candidate,
            content=content,
            mode=stat.S_IMODE(file_stat.st_mode),
            load_hash=hashlib.sha256(content).hexdigest(),
        )
    except OSError as exc:
        raise _TargetRefusal("source-unavailable") from exc
    finally:
        os.close(descriptor)


def _selectors(mapped: tuple[RoutedUnit, ...]) -> tuple[str, ...]:
    return tuple(fragment.selector for unit in mapped for fragment in unit.candidate.fragments)


def _lineage_handoff(
    snapshot: CatalogSnapshot, mapped: tuple[RoutedUnit, ...]
) -> tuple[bool, tuple[LineageView, ...]]:
    materialized: list[LineageView] = []
    seen: set[str] = set()
    generated = False
    for unit in mapped:
        for view in snapshot.lineage_for_unit(unit.candidate.id):
            if view.lineage.relationship == "generated-from":
                generated = True
            elif view.lineage.relationship == "materializes-to" and view.lineage.id not in seen:
                seen.add(view.lineage.id)
                materialized.append(view)
    return generated, tuple(materialized)


def _suggested_checks(
    adapter: SourceAdapter, mapped: tuple[RoutedUnit, ...]
) -> tuple[SuggestedCheck, ...]:
    checks: list[SuggestedCheck] = []
    seen: set[CheckHintId] = set()
    for unit in mapped:
        for check_id in adapter.affected_check_hints(unit):
            if check_id in seen:
                continue
            seen.add(check_id)
            checks.append(SuggestedCheck(id=check_id, command=CHECK_COMMANDS[check_id].command))
    return tuple(checks)


def _cleanup_temp(descriptor: int | None, path: Path | None) -> None:
    if descriptor is not None:
        with suppress(OSError):
            os.close(descriptor)
    if path is not None:
        with suppress(OSError):
            path.unlink(missing_ok=True)


def _failure_result(
    repo_resolved: Path,
    relative_text: str,
    expected_hash: str,
) -> SourceSaveResult:
    try:
        sample = _sample_target(repo_resolved, relative_text)
    except _TargetRefusal as exc:
        return _refused(exc.reason)
    if sample.load_hash != expected_hash:
        return _conflict()
    return _refused("write-failed")


def save_source(
    snapshot: CatalogSnapshot,
    repo_root: Path,
    unit_id: str,
    load_hash: str,
    text: str,
    *,
    typescript_adapter: SourceAdapter | None = None,
) -> SourceSaveResult:
    """Conditionally replace one admitted catalog source with the reviewed full buffer."""
    unit = snapshot.get_unit(unit_id)
    if unit is None:
        return _refused("unsupported-family")
    dispatch = _mapped_write_set(
        snapshot,
        unit,
        typescript_adapter=typescript_adapter,
    )
    if dispatch is None:
        return _refused("unsupported-family")
    mapped, adapter = dispatch

    generated, materialized = _lineage_handoff(snapshot, mapped)
    if generated:
        return _refused("unsafe-lineage")

    try:
        repo_resolved = repo_root.resolve(strict=True)
    except OSError:
        return _refused("unsafe-path")
    try:
        early = _sample_target(repo_resolved, unit.candidate.path)
    except _TargetRefusal as exc:
        return _refused(exc.reason)
    try:
        early.content.decode("utf-8")
    except UnicodeDecodeError:
        return _refused("source-unavailable")
    if early.load_hash != load_hash:
        return _conflict()

    try:
        diagnostics = adapter.validate(text, _selectors(mapped))
    except TypeScriptAdapterUnavailable:
        return _failure_result(repo_resolved, unit.candidate.path, load_hash)
    if diagnostics:
        return SourceValidationFailed(status="validation-failed", diagnostics=diagnostics)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        return _failure_result(repo_resolved, unit.candidate.path, load_hash)

    checks = _suggested_checks(adapter, mapped)
    saved_hash = hashlib.sha256(encoded).hexdigest()
    temp_descriptor: int | None = None
    temp_path: Path | None = None
    final_mode: int | None = None
    try:
        temp_descriptor, raw_temp_path = tempfile.mkstemp(
            prefix=f".{early.path.name}.",
            suffix=".tmp",
            dir=early.path.parent,
        )
        temp_path = Path(raw_temp_path)
        stream = os.fdopen(temp_descriptor, "wb", closefd=False)
        try:
            stream.write(encoded)
            stream.flush()
        finally:
            stream.close()

        late = _sample_target(repo_resolved, unit.candidate.path)
        if late.load_hash != load_hash:
            _cleanup_temp(temp_descriptor, temp_path)
            return _conflict()
        final_mode = late.mode
        os.fchmod(temp_descriptor, final_mode)
        os.close(temp_descriptor)
        temp_descriptor = None
        os.replace(temp_path, late.path)  # noqa: PTH105 - required atomic replacement primitive
        temp_path = None
    except _TargetRefusal as exc:
        _cleanup_temp(temp_descriptor, temp_path)
        return _refused(exc.reason)
    except (OSError, ValueError):
        _cleanup_temp(temp_descriptor, temp_path)
        return _failure_result(repo_resolved, unit.candidate.path, load_hash)

    assert final_mode is not None
    return SourceSaved(
        status="saved",
        source=WholeFileSource(
            unit_id=unit.candidate.id,
            path=unit.candidate.path,
            kind=unit.candidate.kind,
            content=encoded,
            mode=final_mode,
            newline_style=_newline_style(encoded),
            load_hash=saved_hash,
        ),
        materialized=materialized,
        checks=checks,
        catalog_refreshed=True,
        refresh_detail=None,
    )
