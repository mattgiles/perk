"""Private TypeScript compiler-helper SourceAdapter."""

import json
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, RootModel, ValidationError, model_validator

from perk.boundary import StrictInputModel
from perk.substrate.proc import ProcFailure, run_checked
from perk_dev.prose_map.models import RoutedUnit
from perk_dev.prose_review.source_adapter.contract import (
    CheckHintId,
    RangeResolution,
    ResolvedRange,
    SourceAdapter,
    SourceDiagnostic,
    SourceExtraction,
    SourceRange,
    UnresolvedRange,
)

type _UnresolvedReason = Literal[
    "unsupported-selector",
    "unsupported-source-shape",
    "selector-not-found",
    "selector-ambiguous",
]

_HELPER_RELATIVE = Path("tools/prose-map/selector.ts")
_HELPER_TIMEOUT_SECONDS = 5
_DIAGNOSTIC_MESSAGES: dict[str, str] = {
    "syntax-error": "The TypeScript source is not syntactically valid.",
    "unsupported-selector": "The selector is not supported by the TypeScript adapter.",
    "unsupported-source-shape": (
        "The TypeScript selector resolves to a source shape that is not safely editable."
    ),
    "selector-not-found": "The selector does not resolve in the current TypeScript source.",
    "selector-ambiguous": (
        "The selector resolves more than once in the current TypeScript source."
    ),
}


class TypeScriptAdapterUnavailable(Exception):
    """The compiler helper could not run or returned a corrupt protocol response."""


class _ResolvedResultInput(StrictInputModel):
    selector: str
    status: Literal["resolved"]
    start: int
    end: int


class _UnresolvedResultInput(StrictInputModel):
    selector: str
    status: Literal["unresolved"]
    reason: _UnresolvedReason
    line: int | None
    column: int | None

    @model_validator(mode="after")
    def validate_reason_location(self) -> Self:
        has_location = self.line is not None and self.column is not None
        split_location = (self.line is None) != (self.column is None)
        if split_location:
            raise ValueError("selector result location must be wholly present or absent")
        expects_location = self.reason in ("unsupported-source-shape", "selector-ambiguous")
        if has_location != expects_location:
            raise ValueError("selector result location does not match its reason")
        if has_location and (self.line < 1 or self.column < 1):
            raise ValueError("selector result location must be positive")
        return self


type _ResultInput = Annotated[
    _ResolvedResultInput | _UnresolvedResultInput,
    Field(discriminator="status"),
]


class _InvalidSourceResponseInput(StrictInputModel):
    version: Literal[1]
    status: Literal["invalid-source"]
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class _OkResponseInput(StrictInputModel):
    version: Literal[1]
    status: Literal["ok"]
    results: list[_ResultInput]


type _ResponseInput = Annotated[
    _InvalidSourceResponseInput | _OkResponseInput,
    Field(discriminator="status"),
]


class _ResponseEnvelope(RootModel[_ResponseInput]):
    model_config = ConfigDict(strict=True)


@dataclass(frozen=True, slots=True)
class _HelperInvalidSource:
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class _HelperResolved:
    selector: str
    source_range: SourceRange


@dataclass(frozen=True, slots=True)
class _HelperUnresolved:
    selector: str
    reason: _UnresolvedReason
    line: int | None
    column: int | None


type _HelperResult = _HelperResolved | _HelperUnresolved
type _HelperResponse = _HelperInvalidSource | tuple[_HelperResult, ...]


def _line_content_lengths(text: str) -> tuple[int, ...]:
    lengths: list[int] = []
    line_start = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\r":
            lengths.append(index - line_start)
            index += 2 if index + 1 < len(text) and text[index + 1] == "\n" else 1
            line_start = index
            continue
        if character in ("\n", "\u2028", "\u2029"):
            lengths.append(index - line_start)
            index += 1
            line_start = index
            continue
        index += 1
    lengths.append(len(text) - line_start)
    return tuple(lengths)


def _validate_location(text: str, line: int, column: int) -> None:
    line_lengths = _line_content_lengths(text)
    if line < 1 or line > len(line_lengths):
        raise ValueError("helper location names a nonexistent line")
    content_length = line_lengths[line - 1]
    if column < 1 or column > content_length + 1:
        raise ValueError("helper location column is outside the logical line")


def _syntax_diagnostic(line: int, column: int) -> SourceDiagnostic:
    return SourceDiagnostic(
        code="syntax-error",
        message=_DIAGNOSTIC_MESSAGES["syntax-error"],
        selector=None,
        line=line,
        column=column,
    )


def _unresolved(result: _HelperUnresolved) -> UnresolvedRange:
    return UnresolvedRange(
        status="unresolved",
        reason=result.reason,
        diagnostic=SourceDiagnostic(
            code=result.reason,
            message=_DIAGNOSTIC_MESSAGES[result.reason],
            selector=result.selector,
            line=result.line,
            column=result.column,
        ),
    )


class TypeScriptSourceAdapter(SourceAdapter):
    """Resolve TypeScript prose through one app-scoped, fail-fast helper slot."""

    def __init__(self, helper_root: Path) -> None:
        self._helper_root = helper_root.resolve()
        self._helper = self._helper_root / _HELPER_RELATIVE
        self._slot = threading.BoundedSemaphore(1)

    def _invoke(self, text: str, selectors: tuple[str, ...]) -> _HelperResponse:
        if not self._slot.acquire(blocking=False):
            raise TypeScriptAdapterUnavailable("the TypeScript selector helper is busy")
        try:
            with tempfile.TemporaryDirectory(prefix="perk-typescript-selector-") as directory:
                request_path = Path(directory) / "request.json"
                request_path.write_text(
                    json.dumps(
                        {"version": 1, "source": text, "selectors": selectors},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                stdout = run_checked(
                    ["node", str(self._helper), str(request_path)],
                    cwd=self._helper_root,
                    timeout=_HELPER_TIMEOUT_SECONDS,
                )
                response = _ResponseEnvelope.model_validate_json(stdout).root
                if isinstance(response, _InvalidSourceResponseInput):
                    _validate_location(text, response.line, response.column)
                    return _HelperInvalidSource(line=response.line, column=response.column)
                if len(response.results) != len(selectors):
                    raise ValueError("helper result count does not match the selector request")
                results: list[_HelperResult] = []
                for expected, current in zip(selectors, response.results, strict=True):
                    if current.selector != expected:
                        raise ValueError("helper result selector does not match its request")
                    if isinstance(current, _ResolvedResultInput):
                        if (
                            current.start < 0
                            or current.start >= current.end
                            or current.end > len(text)
                        ):
                            raise ValueError("helper returned an invalid source range")
                        results.append(
                            _HelperResolved(
                                selector=current.selector,
                                source_range=SourceRange(start=current.start, end=current.end),
                            )
                        )
                        continue
                    if current.line is not None and current.column is not None:
                        _validate_location(text, current.line, current.column)
                    results.append(
                        _HelperUnresolved(
                            selector=current.selector,
                            reason=current.reason,
                            line=current.line,
                            column=current.column,
                        )
                    )
                return tuple(results)
        except (OSError, UnicodeError, ValidationError, ValueError, ProcFailure) as exc:
            raise TypeScriptAdapterUnavailable(
                "the TypeScript selector helper is unavailable"
            ) from exc
        finally:
            self._slot.release()

    def _resolve_many(
        self,
        text: str,
        selectors: tuple[str, ...],
    ) -> tuple[RangeResolution, ...]:
        """Invoke the helper exactly once and map its ordered results to resolutions.

        A helper-level invalid-source response fans out to one document-level
        unresolved resolution per selector without reparsing;
        :class:`TypeScriptAdapterUnavailable` still escapes as the operational
        typed exception.
        """
        response = self._invoke(text, selectors)
        if isinstance(response, _HelperInvalidSource):
            return tuple(
                UnresolvedRange(
                    status="unresolved",
                    reason="invalid-source",
                    diagnostic=_syntax_diagnostic(response.line, response.column),
                )
                for _ in selectors
            )
        return tuple(
            ResolvedRange(status="resolved", source_range=result.source_range)
            if isinstance(result, _HelperResolved)
            else _unresolved(result)
            for result in response
        )

    def resolve_range(self, text: str, selector: str) -> RangeResolution:
        return self._resolve_many(text, (selector,))[0]

    def extract_many(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceExtraction, ...]:
        return tuple(
            self._to_extraction(text, resolution)
            for resolution in self._resolve_many(text, selectors)
        )

    def validate(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceDiagnostic, ...]:
        response = self._invoke(text, selectors)
        if isinstance(response, _HelperInvalidSource):
            return (_syntax_diagnostic(response.line, response.column),)
        return tuple(
            _unresolved(result).diagnostic
            for result in response
            if isinstance(result, _HelperUnresolved)
        )

    def affected_check_hints(self, unit: RoutedUnit) -> tuple[CheckHintId, ...]:
        return ("prose-map",)
