"""Exact YAML mapping/id-sequence path SourceAdapter."""

from dataclasses import dataclass

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

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
    "syntax-error": "The YAML source is not syntactically valid.",
    "unsupported-selector": "The selector is not supported by the YAML adapter.",
    "unsupported-source-shape": "The YAML source shape cannot be focused safely.",
    "selector-not-found": "The selector does not resolve in the current YAML source.",
    "selector-ambiguous": "The selector resolves more than once in the current YAML source.",
}


@dataclass(frozen=True, slots=True)
class _YamlProblem:
    reason: RangeFailure
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class _YamlDocument:
    node: Node | None
    syntax_problem: _YamlProblem | None
    shape_problem: _YamlProblem | None


def _location(node: Node) -> tuple[int, int]:
    return node.start_mark.line + 1, node.start_mark.column + 1


def _problem(reason: RangeFailure, node: Node | None = None) -> _YamlProblem:
    if node is None:
        return _YamlProblem(reason=reason)
    line, column = _location(node)
    return _YamlProblem(reason=reason, line=line, column=column)


def _is_string_scalar(node: Node) -> bool:
    return isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:str"


def _first_merge(node: Node | None) -> Node | None:
    if isinstance(node, MappingNode):
        for key, value in node.value:
            if isinstance(key, ScalarNode) and key.tag == "tag:yaml.org,2002:merge":
                return key
            nested = _first_merge(value)
            if nested is not None:
                return nested
    elif isinstance(node, SequenceNode):
        for item in node.value:
            nested = _first_merge(item)
            if nested is not None:
                return nested
    return None


def _parse(text: str) -> _YamlDocument:
    try:
        documents = tuple(yaml.compose_all(text, Loader=yaml.SafeLoader))
        alias = next(
            (
                event
                for event in yaml.parse(text, Loader=yaml.SafeLoader)
                if isinstance(event, AliasEvent)
            ),
            None,
        )
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        return _YamlDocument(
            node=None,
            syntax_problem=_YamlProblem(
                reason="invalid-source",
                line=None if mark is None else mark.line + 1,
                column=None if mark is None else mark.column + 1,
            ),
            shape_problem=None,
        )
    if len(documents) != 1 or documents[0] is None:
        node = documents[1] if len(documents) > 1 else None
        return _YamlDocument(
            node=None,
            syntax_problem=None,
            shape_problem=_problem("unsupported-source-shape", node),
        )
    if alias is not None:
        return _YamlDocument(
            node=documents[0],
            syntax_problem=None,
            shape_problem=_YamlProblem(
                reason="unsupported-source-shape",
                line=alias.start_mark.line + 1,
                column=alias.start_mark.column + 1,
            ),
        )
    merge = _first_merge(documents[0])
    return _YamlDocument(
        node=documents[0],
        syntax_problem=None,
        shape_problem=None if merge is None else _problem("unsupported-source-shape", merge),
    )


def _selector_segments(selector: str) -> tuple[str, ...] | None:
    segments = tuple(selector.split("."))
    if (
        not selector
        or any(not segment for segment in segments)
        or any(segment.isdecimal() for segment in segments)
        or any(any(character in segment for character in "*\\[]") for segment in segments)
    ):
        return None
    return segments


def _mapping_step(node: MappingNode, segment: str) -> Node | _YamlProblem:
    matches: list[tuple[ScalarNode, Node]] = []
    for key, value in node.value:
        if not _is_string_scalar(key):
            return _problem("unsupported-source-shape", key)
        if key.value == segment:
            matches.append((key, value))
    if not matches:
        return _problem("selector-not-found")
    if len(matches) > 1:
        return _problem("selector-ambiguous", matches[1][0])
    return matches[0][1]


def _sequence_step(node: SequenceNode, segment: str) -> Node | _YamlProblem:
    matches: list[tuple[ScalarNode, MappingNode]] = []
    for item in node.value:
        if not isinstance(item, MappingNode):
            return _problem("unsupported-source-shape", item)
        ids: list[tuple[ScalarNode, Node]] = []
        for key, value in item.value:
            if not _is_string_scalar(key):
                return _problem("unsupported-source-shape", key)
            if key.value == "id":
                ids.append((key, value))
        if len(ids) > 1:
            return _problem("selector-ambiguous", ids[1][0])
        if not ids:
            continue
        _id_key, id_value = ids[0]
        if not _is_string_scalar(id_value):
            return _problem("unsupported-source-shape", id_value)
        if id_value.value == segment:
            assert isinstance(id_value, ScalarNode)
            matches.append((id_value, item))
    if not matches:
        return _problem("selector-not-found")
    if len(matches) > 1:
        return _problem("selector-ambiguous", matches[1][0])
    return matches[0][1]


def _resolve(document: _YamlDocument, selector: str) -> SourceRange | _YamlProblem:
    if document.syntax_problem is not None:
        return document.syntax_problem
    segments = _selector_segments(selector)
    if segments is None:
        return _problem("unsupported-selector")
    if document.shape_problem is not None:
        return document.shape_problem
    assert document.node is not None
    current = document.node
    for segment in segments:
        if isinstance(current, MappingNode):
            next_node = _mapping_step(current, segment)
        elif isinstance(current, SequenceNode):
            next_node = _sequence_step(current, segment)
        else:
            return _problem("unsupported-source-shape", current)
        if isinstance(next_node, _YamlProblem):
            return next_node
        current = next_node
    return SourceRange(start=current.start_mark.index, end=current.end_mark.index)


def _unresolved(problem: _YamlProblem, selector: str) -> UnresolvedRange:
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


class YamlSourceAdapter(SourceAdapter):
    """Exact dot paths through mappings and id-keyed sequences."""

    def resolve_range(self, text: str, selector: str) -> RangeResolution:
        result = _resolve(_parse(text), selector)
        if isinstance(result, SourceRange):
            return ResolvedRange(status="resolved", source_range=result)
        return _unresolved(result, selector)

    def validate(self, text: str, selectors: tuple[str, ...]) -> tuple[SourceDiagnostic, ...]:
        document = _parse(text)
        if document.syntax_problem is not None:
            first_selector = selectors[0] if selectors else ""
            return (_unresolved(document.syntax_problem, first_selector).diagnostic,)
        diagnostics: list[SourceDiagnostic] = []
        for selector in selectors:
            result = _resolve(document, selector)
            if isinstance(result, SourceRange):
                continue
            diagnostics.append(_unresolved(result, selector).diagnostic)
        return tuple(diagnostics)

    def affected_check_hints(self, unit: RoutedUnit) -> tuple[CheckHintId, ...]:
        return ("prose-map", "learned-docs")
