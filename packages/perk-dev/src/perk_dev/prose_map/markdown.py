"""Pure Markdown fragment discovery and exact range resolution."""

import re
from dataclasses import dataclass
from typing import Literal

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode

from perk_dev.prose_map.models import Fragment

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_HEADING_SELECTOR_RE = re.compile(r"^heading:[a-z0-9-]+(?:/[a-z0-9-]+)*(?:~[2-9][0-9]*)?$")

type MarkdownFailure = Literal[
    "invalid-source",
    "unsupported-selector",
    "unsupported-source-shape",
    "selector-not-found",
    "selector-ambiguous",
]


@dataclass(frozen=True, slots=True)
class MarkdownRange:
    """A half-open range in Python Unicode-code-point indexes."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class MarkdownProblem:
    """A parser/resolver failure independent of the SourceAdapter contract."""

    reason: MarkdownFailure
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    content_end: int
    end: int
    content: str


@dataclass(frozen=True, slots=True)
class _Heading:
    selector: str
    label: str
    line: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Alias:
    start: int
    end: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class _Frontmatter:
    raw: str
    raw_start: int
    node: Node | None
    value: object
    aliases: tuple[_Alias, ...]
    problem: MarkdownProblem | None


class MarkdownDiscoveryError(Exception):
    """A Markdown document cannot support stable fragment discovery."""


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    """One parsed document reused by discovery, resolution, and batch validation."""

    text: str
    fragments: tuple[Fragment, ...]
    body_start: int
    headings: tuple[_Heading, ...]
    frontmatter: _Frontmatter | None

    def resolve(self, selector: str) -> MarkdownRange | MarkdownProblem:
        """Resolve one selector against the current text."""
        syntax_problem = self._syntax_problem()
        if syntax_problem is not None:
            return syntax_problem
        if selector == "file-body":
            body = next(
                (fragment for fragment in self.fragments if fragment.selector == "file-body"),
                None,
            )
            if body is None:
                return MarkdownProblem("selector-not-found")
            return MarkdownRange(self.body_start, len(self.text))
        if selector == "frontmatter.description":
            return self._resolve_description()
        if _HEADING_SELECTOR_RE.fullmatch(selector) is not None:
            matches = [heading for heading in self.headings if heading.selector == selector]
            if not matches:
                return MarkdownProblem("selector-not-found")
            if len(matches) > 1:
                return MarkdownProblem("selector-ambiguous", line=matches[1].line, column=1)
            return MarkdownRange(matches[0].start, matches[0].end)
        return MarkdownProblem("unsupported-selector")

    def validate(self, selectors: tuple[str, ...]) -> tuple[MarkdownProblem, ...]:
        """Return one problem per failing selector, or one document syntax problem."""
        syntax_problem = self._syntax_problem()
        if syntax_problem is not None:
            return (syntax_problem,)
        return tuple(
            result
            for selector in selectors
            if isinstance((result := self.resolve(selector)), MarkdownProblem)
        )

    def _syntax_problem(self) -> MarkdownProblem | None:
        if self.frontmatter is None or self.frontmatter.problem is None:
            return None
        if self.frontmatter.problem.reason == "invalid-source":
            return self.frontmatter.problem
        return None

    def _resolve_description(self) -> MarkdownRange | MarkdownProblem:
        frontmatter = self.frontmatter
        if frontmatter is None:
            return MarkdownProblem("selector-not-found")
        if frontmatter.problem is not None:
            return frontmatter.problem
        if not isinstance(frontmatter.node, MappingNode):
            if frontmatter.node is None:
                return MarkdownProblem("unsupported-source-shape")
            line, column = self._frontmatter_location(frontmatter.node)
            return MarkdownProblem(
                "unsupported-source-shape",
                line=line,
                column=column,
            )

        matches: list[tuple[ScalarNode, Node, _Alias | None]] = []
        for index, (key, value) in enumerate(frontmatter.node.value):
            if not _is_string_scalar(key):
                continue
            if key.value != "description":
                continue
            next_start = (
                frontmatter.node.value[index + 1][0].start_mark.index
                if index + 1 < len(frontmatter.node.value)
                else len(frontmatter.raw)
            )
            alias = next(
                (
                    candidate
                    for candidate in frontmatter.aliases
                    if key.end_mark.index <= candidate.start < next_start
                ),
                None,
            )
            matches.append((key, value, alias))
        if not matches:
            return MarkdownProblem("selector-not-found")
        if len(matches) > 1:
            key = matches[1][0]
            line, column = self._frontmatter_location(key)
            return MarkdownProblem(
                "selector-ambiguous",
                line=line,
                column=column,
            )

        _key, value, alias = matches[0]
        line, column = (
            (alias.line, alias.column) if alias is not None else self._frontmatter_location(value)
        )
        if alias is not None or not _is_string_scalar(value):
            return MarkdownProblem(
                "unsupported-source-shape",
                line=line,
                column=column,
            )
        if not isinstance(frontmatter.value, dict):
            return MarkdownProblem("unsupported-source-shape")
        effective = next(
            (candidate for key, candidate in frontmatter.value.items() if key == "description"),
            None,
        )
        if not isinstance(effective, str):
            return MarkdownProblem(
                "unsupported-source-shape",
                line=line,
                column=column,
            )
        if not effective.strip():
            return MarkdownProblem("selector-not-found")
        return MarkdownRange(
            frontmatter.raw_start + value.start_mark.index,
            frontmatter.raw_start + value.end_mark.index,
        )

    def _frontmatter_location(self, node: Node) -> tuple[int, int]:
        assert self.frontmatter is not None
        assert node.start_mark is not None
        lines_before = self.text[: self.frontmatter.raw_start].count("\n")
        return (
            lines_before + node.start_mark.line + 1,
            node.start_mark.column + 1,
        )


def _lines(text: str) -> tuple[_Line, ...]:
    lines: list[_Line] = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        if raw.endswith("\r\n"):
            content = raw[:-2]
        elif raw.endswith(("\n", "\r")):
            content = raw[:-1]
        else:
            content = raw
        content_end = offset + len(content)
        end = offset + len(raw)
        lines.append(_Line(start=offset, content_end=content_end, end=end, content=content))
        offset = end
    if not text or offset < len(text):
        content = text[offset:]
        lines.append(_Line(start=offset, content_end=len(text), end=len(text), content=content))
    return tuple(lines)


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-") or "section"


def _is_string_scalar(node: Node) -> bool:
    return isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:str"


def _problem_from_yaml(exc: yaml.MarkedYAMLError, *, line_offset: int) -> MarkdownProblem:
    mark = exc.problem_mark
    return MarkdownProblem(
        "invalid-source",
        line=None if mark is None else mark.line + line_offset + 1,
        column=None if mark is None else mark.column + 1,
    )


def _parse_frontmatter(raw: str, raw_start: int) -> _Frontmatter:
    try:
        documents = tuple(yaml.compose_all(raw, Loader=yaml.SafeLoader))
        aliases = tuple(
            _Alias(
                start=event.start_mark.index,
                end=event.end_mark.index,
                line=event.start_mark.line + 2,
                column=event.start_mark.column + 1,
            )
            for event in yaml.parse(raw, Loader=yaml.SafeLoader)
            if isinstance(event, AliasEvent)
        )
    except yaml.MarkedYAMLError as exc:
        return _Frontmatter(
            raw=raw,
            raw_start=raw_start,
            node=None,
            value=None,
            aliases=(),
            problem=_problem_from_yaml(exc, line_offset=1),
        )
    if len(documents) > 1:
        node = documents[1]
        return _Frontmatter(
            raw=raw,
            raw_start=raw_start,
            node=None,
            value=None,
            aliases=aliases,
            problem=MarkdownProblem(
                "unsupported-source-shape",
                line=None if node is None else node.start_mark.line + 2,
                column=None if node is None else node.start_mark.column + 1,
            ),
        )
    try:
        value = yaml.safe_load(raw)
    except yaml.MarkedYAMLError as exc:
        return _Frontmatter(
            raw=raw,
            raw_start=raw_start,
            node=None,
            value=None,
            aliases=aliases,
            problem=_problem_from_yaml(exc, line_offset=1),
        )
    return _Frontmatter(
        raw=raw,
        raw_start=raw_start,
        node=documents[0] if documents else None,
        value=value,
        aliases=aliases,
        problem=None,
    )


def parse_markdown(text: str) -> MarkdownDocument:
    """Parse supplied text without file I/O, preserving exact source indexes."""
    lines = _lines(text)
    frontmatter: _Frontmatter | None = None
    body_start = 0
    if lines and lines[0].content == "---":
        closing = next(
            (line for line in lines[1:] if line.content == "---"),
            None,
        )
        if closing is not None:
            raw_start = lines[0].end
            frontmatter = _parse_frontmatter(text[raw_start : closing.start], raw_start)
            body_start = closing.end

    headings: list[_Heading] = []
    heading_lines: list[tuple[_Line, int, str, str]] = []
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        if line.start < body_start:
            continue
        match = _HEADING_RE.match(line.content)
        if match is None:
            continue
        level = len(match.group(1))
        label = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, _slug(label)))
        base = "/".join(part for _, part in stack)
        seen[base] = seen.get(base, 0) + 1
        suffix = "" if seen[base] == 1 else f"~{seen[base]}"
        selector = f"heading:{base}{suffix}"
        heading_lines.append((line, number, label, selector))
    for index, (line, number, label, selector) in enumerate(heading_lines):
        end = heading_lines[index + 1][0].start if index + 1 < len(heading_lines) else len(text)
        headings.append(
            _Heading(selector=selector, label=label, line=number, start=line.end, end=end)
        )

    fragments: list[Fragment] = []
    if frontmatter is not None and frontmatter.problem is None:
        value = frontmatter.value
        if isinstance(value, dict):
            description = next(
                (candidate for key, candidate in value.items() if key == "description"),
                None,
            )
            if isinstance(description, str) and description.strip():
                fragments.append(
                    Fragment(
                        id="frontmatter:description",
                        label="Discovery description",
                        selector="frontmatter.description",
                    )
                )
    fragments.extend(
        Fragment(
            id=f"section:{heading.selector.removeprefix('heading:')}",
            label=heading.label,
            selector=heading.selector,
        )
        for heading in headings
    )
    if not fragments:
        fragments.append(Fragment(id="body", label="Document body", selector="file-body"))
    return MarkdownDocument(
        text=text,
        fragments=tuple(fragments),
        body_start=body_start,
        headings=tuple(headings),
        frontmatter=frontmatter,
    )


def discover_markdown_fragments(text: str) -> tuple[Fragment, ...]:
    """Return stable discovery fragments, refusing malformed/multi-document frontmatter."""
    document = parse_markdown(text)
    if document.frontmatter is not None and document.frontmatter.problem is not None:
        problem = document.frontmatter.problem
        location = (
            "" if problem.line is None else f" at line {problem.line}, column {problem.column or 1}"
        )
        raise MarkdownDiscoveryError(f"Markdown frontmatter is {problem.reason}{location}")
    return document.fragments
