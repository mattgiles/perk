"""Frozen SourceAdapter domain values and the internal adapter interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from perk_dev.prose_map.models import Fragment, ProseKind, RoutedUnit

type RangeFailure = Literal[
    "unsupported-selector",
    "unsupported-source-shape",
    "selector-not-found",
    "selector-ambiguous",
    "invalid-source",
]
type SourceDiagnosticCode = Literal[
    "syntax-error",
    "unsupported-selector",
    "unsupported-source-shape",
    "selector-not-found",
    "selector-ambiguous",
]
type CheckHintId = Literal["prose-map", "learned-docs"]
type SourceReadFailure = Literal["unknown_unit", "unknown_fragment", "not_found", "not_text"]
type ReadOnlyReason = Literal[
    "whole-unit",
    "unsupported-family",
    "unsupported-selector",
    "unsupported-source-shape",
    "selector-not-found",
    "selector-ambiguous",
    "invalid-source",
]


@dataclass(frozen=True, slots=True)
class SourceRange:
    """A validated half-open range in Python Unicode-code-point indexes."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("source range must satisfy 0 <= start <= end")


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    """One closed adapter diagnostic with an optional one-based location."""

    code: SourceDiagnosticCode
    message: str
    selector: str | None
    line: int | None
    column: int | None

    def __post_init__(self) -> None:
        if self.line is not None and self.line < 1:
            raise ValueError("diagnostic locations are one-based")
        if self.column is not None and self.column < 1:
            raise ValueError("diagnostic locations are one-based")
        if self.code == "syntax-error" and self.selector is not None:
            raise ValueError("syntax diagnostics are document-level")
        if self.code != "syntax-error" and self.selector is None:
            raise ValueError("selector diagnostics must identify their selector")


@dataclass(frozen=True, slots=True)
class ResolvedRange:
    status: Literal["resolved"]
    source_range: SourceRange


@dataclass(frozen=True, slots=True)
class UnresolvedRange:
    status: Literal["unresolved"]
    reason: RangeFailure
    diagnostic: SourceDiagnostic


type RangeResolution = ResolvedRange | UnresolvedRange


@dataclass(frozen=True, slots=True)
class SourceExtraction:
    before: str
    focus: str
    after: str
    resolution: RangeResolution


@dataclass(frozen=True, slots=True)
class WholeFileSource:
    """One canonical unit's whole source file, decoded as text."""

    unit_id: str
    path: str
    kind: ProseKind
    text: str


@dataclass(frozen=True, slots=True)
class FocusedSource:
    """One whole-unit or fragment-focused source read."""

    unit_id: str
    path: str
    kind: ProseKind
    fragment: Fragment | None
    before: str
    focus: str
    after: str
    editable: bool
    read_only_reason: ReadOnlyReason | None

    def __post_init__(self) -> None:
        if self.editable:
            if self.fragment is None or self.read_only_reason is not None:
                raise ValueError("editable source requires a fragment and no read-only reason")
        elif self.read_only_reason is None:
            raise ValueError("non-editable source requires a read-only reason")


class SourceAdapter(ABC):
    """Internal structured-text read adapter with future-save validation hooks."""

    @abstractmethod
    def resolve_range(self, text: str, selector: str) -> RangeResolution:
        """Resolve exactly one selector against supplied text."""

    def extract(self, text: str, selector: str) -> SourceExtraction:
        """Extract one focus range, or return the canonical whole-text fallback."""
        resolution = self.resolve_range(text, selector)
        if isinstance(resolution, UnresolvedRange):
            return SourceExtraction(before="", focus=text, after="", resolution=resolution)
        source_range = resolution.source_range
        if source_range.end > len(text):
            raise ValueError("resolved source range exceeds supplied text")
        return SourceExtraction(
            before=text[: source_range.start],
            focus=text[source_range.start : source_range.end],
            after=text[source_range.end :],
            resolution=resolution,
        )

    def validate(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceDiagnostic, ...]:
        """Validate syntax and exact re-resolution in selector input order."""
        diagnostics: list[SourceDiagnostic] = []
        for selector in selectors:
            result = self.resolve_range(text, selector)
            if isinstance(result, ResolvedRange):
                continue
            if result.diagnostic.code == "syntax-error":
                return (result.diagnostic,)
            diagnostics.append(result.diagnostic)
        return tuple(diagnostics)

    @abstractmethod
    def affected_check_hints(self, unit: RoutedUnit) -> tuple[CheckHintId, ...]:
        """Return semantic check ids affected by a future replacement."""
