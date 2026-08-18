"""Exact module-level Python symbol SourceAdapter."""

import ast
import io
import keyword
import token
import tokenize
from dataclasses import dataclass
from typing import Literal

from perk_dev.prose_map.models import RoutedUnit
from perk_dev.prose_map.python import PythonSymbolCandidate, python_symbol_name, python_symbols
from perk_dev.prose_review.source_adapter.contract import (
    CheckHintId,
    RangeResolution,
    ResolvedRange,
    SourceAdapter,
    SourceDiagnostic,
    SourceDiagnosticCode,
    SourceExtraction,
    SourceRange,
    UnresolvedRange,
)

type _PythonFailure = Literal[
    "invalid-source",
    "unsupported-selector",
    "selector-not-found",
    "selector-ambiguous",
]

_FILENAME = "<prose-review-source>"
_DIAGNOSTIC_CODES: dict[_PythonFailure, SourceDiagnosticCode] = {
    "invalid-source": "syntax-error",
    "unsupported-selector": "unsupported-selector",
    "selector-not-found": "selector-not-found",
    "selector-ambiguous": "selector-ambiguous",
}
_DIAGNOSTIC_MESSAGES: dict[SourceDiagnosticCode, str] = {
    "syntax-error": "The Python source is not syntactically valid.",
    "unsupported-selector": "The selector is not supported by the Python adapter.",
    "selector-not-found": "The selector does not resolve in the current Python source.",
    "selector-ambiguous": "The selector resolves more than once in the current Python source.",
}


@dataclass(frozen=True, slots=True)
class _PythonProblem:
    reason: _PythonFailure
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class _PythonDocument:
    module: ast.Module | None
    tokens: tuple[tokenize.TokenInfo, ...]
    line_starts: tuple[int, ...]
    syntax_problem: _PythonProblem | None


def _line_starts(text: str) -> tuple[int, ...]:
    return (0, *(index + 1 for index, character in enumerate(text) if character == "\n"))


def _syntax_error_problem(exc: SyntaxError) -> _PythonProblem:
    line = exc.lineno if exc.lineno is not None and exc.lineno >= 1 else None
    column = exc.offset if exc.offset is not None and exc.offset >= 1 else None
    return _PythonProblem(reason="invalid-source", line=line, column=column)


def _token_error_problem(exc: tokenize.TokenError) -> _PythonProblem:
    if len(exc.args) < 2:
        return _PythonProblem(reason="invalid-source")
    location = exc.args[1]
    if (
        not isinstance(location, tuple)
        or len(location) != 2
        or not isinstance(location[0], int)
        or not isinstance(location[1], int)
    ):
        return _PythonProblem(reason="invalid-source")
    line = location[0] if location[0] >= 1 else None
    column = location[1] + 1 if location[1] >= 0 else None
    return _PythonProblem(reason="invalid-source", line=line, column=column)


def _parse(text: str) -> _PythonDocument:
    starts = _line_starts(text)
    try:
        module = ast.parse(text, filename=_FILENAME)
        _ = compile(module, _FILENAME, "exec")
    except SyntaxError as exc:
        return _PythonDocument(
            module=None,
            tokens=(),
            line_starts=starts,
            syntax_problem=_syntax_error_problem(exc),
        )
    except UnicodeEncodeError:
        return _PythonDocument(
            module=None,
            tokens=(),
            line_starts=starts,
            syntax_problem=_PythonProblem(reason="invalid-source"),
        )
    try:
        tokens = tuple(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError as exc:
        return _PythonDocument(
            module=None,
            tokens=(),
            line_starts=starts,
            syntax_problem=_token_error_problem(exc),
        )
    except SyntaxError as exc:
        return _PythonDocument(
            module=None,
            tokens=(),
            line_starts=starts,
            syntax_problem=_syntax_error_problem(exc),
        )
    return _PythonDocument(
        module=module,
        tokens=tokens,
        line_starts=starts,
        syntax_problem=None,
    )


def _line_slice(text: str, starts: tuple[int, ...], line: int) -> tuple[int, str] | None:
    if line < 1 or line > len(starts):
        return None
    start = starts[line - 1]
    end = starts[line] if line < len(starts) else len(text)
    return start, text[start:end]


def _ast_index(
    text: str,
    starts: tuple[int, ...],
    line: int,
    byte_column: int,
) -> int | None:
    line_slice = _line_slice(text, starts, line)
    if line_slice is None or byte_column < 0:
        return None
    line_start, line_text = line_slice
    encoded = line_text.encode("utf-8")
    if byte_column > len(encoded):
        return None
    try:
        prefix = encoded[:byte_column].decode("utf-8")
    except UnicodeDecodeError:
        return None
    return line_start + len(prefix)


def _token_index(
    text: str,
    starts: tuple[int, ...],
    line: int,
    column: int,
) -> int | None:
    line_slice = _line_slice(text, starts, line)
    if line_slice is None or column < 0:
        return None
    line_start, line_text = line_slice
    if column > len(line_text):
        return None
    return line_start + column


def _node_start(text: str, document: _PythonDocument, node: ast.stmt) -> int | None:
    return _ast_index(text, document.line_starts, node.lineno, node.col_offset)


def _node_end(text: str, document: _PythonDocument, node: ast.stmt) -> int | None:
    if node.end_lineno is None or node.end_col_offset is None:
        return None
    return _ast_index(text, document.line_starts, node.end_lineno, node.end_col_offset)


def _node_location(
    text: str,
    document: _PythonDocument,
    node: PythonSymbolCandidate,
) -> tuple[int, int] | None:
    start = _node_start(text, document, node)
    line_slice = _line_slice(text, document.line_starts, node.lineno)
    if start is None or line_slice is None:
        return None
    line_start, _line_text = line_slice
    return node.lineno, start - line_start + 1


def _previous_node_end(
    text: str,
    document: _PythonDocument,
    node: PythonSymbolCandidate,
) -> int | None:
    assert document.module is not None
    index = next(
        (index for index, candidate in enumerate(document.module.body) if candidate is node),
        None,
    )
    if index is None:
        return None
    if index == 0:
        return 0
    return _node_end(text, document, document.module.body[index - 1])


def _definition_token_index(
    text: str,
    document: _PythonDocument,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[int, int] | None:
    node_start = _node_start(text, document, node)
    line_slice = _line_slice(text, document.line_starts, node.lineno)
    if node_start is None or line_slice is None:
        return None
    line_start, _line_text = line_slice
    expected_column = node_start - line_start
    expected_name = "async" if isinstance(node, ast.AsyncFunctionDef) else "def"
    token_index = next(
        (
            index
            for index, current in enumerate(document.tokens)
            if current.type == token.NAME
            and current.string == expected_name
            and current.start == (node.lineno, expected_column)
        ),
        None,
    )
    if token_index is None:
        return None
    return token_index, expected_column


def _decorated_start(
    text: str,
    document: _PythonDocument,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> int | None:
    definition = _definition_token_index(text, document, node)
    previous_end = _previous_node_end(text, document, node)
    if definition is None or previous_end is None:
        return None
    definition_index, indentation_column = definition
    depth = 0
    logical_line_start = True
    markers: list[tokenize.TokenInfo] = []
    for current in document.tokens[:definition_index]:
        if current.type == token.NEWLINE:
            logical_line_start = True
            continue
        if current.type in (tokenize.COMMENT, token.NL, token.INDENT, token.DEDENT):
            continue
        if current.type != token.OP:
            logical_line_start = False
            continue
        if current.string in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif (
            current.string == "@"
            and logical_line_start
            and depth == 0
            and current.start[1] == indentation_column
        ):
            marker_index = _token_index(
                text,
                document.line_starts,
                current.start[0],
                current.start[1],
            )
            if marker_index is None:
                return None
            if marker_index >= previous_end:
                markers.append(current)
        elif current.string in "([{":
            depth += 1
        logical_line_start = False
    if depth != 0 or len(markers) != len(node.decorator_list):
        return None
    first = markers[0]
    return _token_index(text, document.line_starts, first.start[0], first.start[1])


def _source_range(
    text: str,
    document: _PythonDocument,
    node: PythonSymbolCandidate,
) -> SourceRange | None:
    end = _node_end(text, document, node)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
        start = _decorated_start(text, document, node)
    else:
        start = _node_start(text, document, node)
    if start is None or end is None or end < start:
        return None
    return SourceRange(start=start, end=end)


def _selector_name(selector: str) -> str | None:
    if not selector.startswith("symbol:"):
        return None
    name = selector.removeprefix("symbol:")
    if not name or not name.isidentifier() or keyword.iskeyword(name):
        return None
    return name


def _resolve(document: _PythonDocument, text: str, selector: str) -> SourceRange | _PythonProblem:
    if document.syntax_problem is not None:
        return document.syntax_problem
    name = _selector_name(selector)
    if name is None:
        return _PythonProblem(reason="unsupported-selector")
    assert document.module is not None
    matches = [node for node in python_symbols(document.module) if python_symbol_name(node) == name]
    if not matches:
        return _PythonProblem(reason="selector-not-found")
    if len(matches) > 1:
        location = _node_location(text, document, matches[1])
        if location is None:
            return _PythonProblem(reason="invalid-source")
        return _PythonProblem(
            reason="selector-ambiguous",
            line=location[0],
            column=location[1],
        )
    source_range = _source_range(text, document, matches[0])
    if source_range is None:
        return _PythonProblem(reason="invalid-source")
    return source_range


def _unresolved(problem: _PythonProblem, selector: str) -> UnresolvedRange:
    code = _DIAGNOSTIC_CODES[problem.reason]
    return UnresolvedRange(
        status="unresolved",
        reason=problem.reason,
        diagnostic=SourceDiagnostic(
            code=code,
            message=_DIAGNOSTIC_MESSAGES[code],
            selector=None if code == "syntax-error" else selector,
            line=problem.line,
            column=problem.column,
        ),
    )


class PythonSourceAdapter(SourceAdapter):
    """Exact named-symbol resolver for discovery-supported Python module nodes."""

    def _resolve_many(
        self,
        text: str,
        selectors: tuple[str, ...],
    ) -> tuple[RangeResolution, ...]:
        """Parse/compiler-validate/tokenize once, then resolve every selector in order."""
        document = _parse(text)
        resolutions: list[RangeResolution] = []
        for selector in selectors:
            result = _resolve(document, text, selector)
            if isinstance(result, SourceRange):
                resolutions.append(ResolvedRange(status="resolved", source_range=result))
            else:
                resolutions.append(_unresolved(result, selector))
        return tuple(resolutions)

    def resolve_range(self, text: str, selector: str) -> RangeResolution:
        return self._resolve_many(text, (selector,))[0]

    def extract_many(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceExtraction, ...]:
        return tuple(
            self._to_extraction(text, resolution)
            for resolution in self._resolve_many(text, selectors)
        )

    def validate(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceDiagnostic, ...]:
        document = _parse(text)
        if document.syntax_problem is not None:
            return (_unresolved(document.syntax_problem, "").diagnostic,)
        diagnostics: list[SourceDiagnostic] = []
        for selector in selectors:
            result = _resolve(document, text, selector)
            if isinstance(result, SourceRange):
                continue
            unresolved = _unresolved(result, selector)
            if unresolved.diagnostic.code == "syntax-error":
                return (unresolved.diagnostic,)
            diagnostics.append(unresolved.diagnostic)
        return tuple(diagnostics)

    def affected_check_hints(self, unit: RoutedUnit) -> tuple[CheckHintId, ...]:
        return ("prose-map", "worker-prompt-pins", "ruff", "ty")
