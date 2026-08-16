"""Markdown SourceAdapter backed by the shared prose-map parser."""

from perk_dev.prose_map.markdown import (
    MarkdownDocument,
    MarkdownProblem,
    MarkdownRange,
    parse_markdown,
)
from perk_dev.prose_map.models import RoutedUnit
from perk_dev.prose_review.source_adapter.contract import (
    CheckHintId,
    RangeFailure,
    RangeResolution,
    ResolvedRange,
    SourceAdapter,
    SourceDiagnostic,
    SourceDiagnosticCode,
    SourceRange,
    UnresolvedRange,
)

_DIAGNOSTIC_CODES: dict[RangeFailure, SourceDiagnosticCode] = {
    "invalid-source": "syntax-error",
    "unsupported-selector": "unsupported-selector",
    "unsupported-source-shape": "unsupported-source-shape",
    "selector-not-found": "selector-not-found",
    "selector-ambiguous": "selector-ambiguous",
}
_DIAGNOSTIC_MESSAGES: dict[SourceDiagnosticCode, str] = {
    "syntax-error": "The Markdown frontmatter is not valid YAML.",
    "unsupported-selector": "The selector is not supported by the Markdown adapter.",
    "unsupported-source-shape": "The Markdown source shape cannot be focused safely.",
    "selector-not-found": "The selector does not resolve in the current Markdown source.",
    "selector-ambiguous": "The selector resolves more than once in the current Markdown source.",
}


def _unresolved(problem: MarkdownProblem, selector: str) -> UnresolvedRange:
    reason: RangeFailure = problem.reason
    code = _DIAGNOSTIC_CODES[reason]
    return UnresolvedRange(
        status="unresolved",
        reason=reason,
        diagnostic=SourceDiagnostic(
            code=code,
            message=_DIAGNOSTIC_MESSAGES[code],
            selector=None if code == "syntax-error" else selector,
            line=problem.line,
            column=problem.column,
        ),
    )


def _resolve(document: MarkdownDocument, selector: str) -> RangeResolution:
    result = document.resolve(selector)
    if isinstance(result, MarkdownRange):
        return ResolvedRange(
            status="resolved",
            source_range=SourceRange(start=result.start, end=result.end),
        )
    return _unresolved(result, selector)


class MarkdownSourceAdapter(SourceAdapter):
    """Exact Markdown body, heading-body, and frontmatter-description resolver."""

    def resolve_range(self, text: str, selector: str) -> RangeResolution:
        return _resolve(parse_markdown(text), selector)

    def validate(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceDiagnostic, ...]:
        document = parse_markdown(text)
        syntax_problems = document.validate(())
        if syntax_problems:
            return (_unresolved(syntax_problems[0], "").diagnostic,)
        diagnostics: list[SourceDiagnostic] = []
        for selector in selectors:
            result = _resolve(document, selector)
            if isinstance(result, ResolvedRange):
                continue
            if result.diagnostic.code == "syntax-error":
                return (result.diagnostic,)
            diagnostics.append(result.diagnostic)
        return tuple(diagnostics)

    def affected_check_hints(self, unit: RoutedUnit) -> tuple[CheckHintId, ...]:
        return ("prose-map",)
