"""Frozen SourceAdapter domain values and the internal adapter interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from perk_dev.prose_map.models import Fragment, ProseKind, RoutedUnit

type NewlineStyle = Literal["none", "lf", "crlf", "cr", "mixed"]
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
    "adapter-unavailable",
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
    """One canonical loaded-file snapshot with untouched byte authority."""

    unit_id: str
    path: str
    kind: ProseKind
    content: bytes
    mode: int
    newline_style: NewlineStyle
    load_hash: str

    def __post_init__(self) -> None:
        if self.mode < 0 or self.mode > 0o7777:
            raise ValueError("source mode must contain only POSIX permission bits")
        if len(self.load_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.load_hash
        ):
            raise ValueError("source load hash must be lowercase SHA-256 hex")

    @property
    def text(self) -> str:
        """Strictly decode the immutable canonical bytes."""
        return self.content.decode("utf-8")


@dataclass(frozen=True, slots=True)
class FocusedSource:
    """One whole-unit or fragment projection over supplied text."""

    unit_id: str
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


@dataclass(frozen=True, slots=True)
class LoadedSource:
    """One canonical file load paired with its requested source projection."""

    file: WholeFileSource
    view: FocusedSource

    def __post_init__(self) -> None:
        if self.file.unit_id != self.view.unit_id or self.file.kind != self.view.kind:
            raise ValueError("loaded source file and view identities must match")
        if self.view.before + self.view.focus + self.view.after != self.file.text:
            raise ValueError("loaded source view must reconstruct the canonical file")


class SourceAdapter(ABC):
    """Internal structured-text read adapter with future-save validation hooks."""

    @abstractmethod
    def resolve_range(self, text: str, selector: str) -> RangeResolution:
        """Resolve exactly one selector against supplied text."""

    def _to_extraction(self, text: str, resolution: RangeResolution) -> SourceExtraction:
        """Slice one validated resolution, or return the canonical whole-text fallback.

        The single slicing/range-check authority: concrete adapters map their native
        results to :class:`RangeResolution` values and never duplicate this conversion.
        """
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

    def extract(self, text: str, selector: str) -> SourceExtraction:
        """Extract one focus range, or return the canonical whole-text fallback."""
        return self._to_extraction(text, self.resolve_range(text, selector))

    def extract_many(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceExtraction, ...]:
        """Extract one ordered result per selector: exact cardinality, `extract` semantics.

        The default delegates to :meth:`extract` per selector; adapters with a batch
        optimization (one parse, one helper invocation) override this while keeping the
        same range validation and whole-text fallback semantics.
        """
        return tuple(self.extract(text, selector) for selector in selectors)

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
