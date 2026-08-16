"""Focused coverage for the shared Markdown discovery/range parser."""

import pytest
from perk_dev.prose_map.markdown import (
    MarkdownDiscoveryError,
    MarkdownProblem,
    MarkdownRange,
    discover_markdown_fragments,
    parse_markdown,
)


def _focus(text: str, selector: str) -> str:
    result = parse_markdown(text).resolve(selector)
    assert isinstance(result, MarkdownRange)
    return text[result.start : result.end]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_frontmatter_delimiters_stay_outside_plain_description_and_body(newline: str) -> None:
    text = newline.join(("---", "description: Plain text", "---", "Body", ""))
    document = parse_markdown(text)
    assert [fragment.selector for fragment in document.fragments] == ["frontmatter.description"]
    assert _focus(text, "frontmatter.description") == "Plain text"
    assert document.body_start == text.index("Body")


@pytest.mark.parametrize(
    ("authored", "focused"),
    [
        ("plain text", "plain text"),
        ('"quoted text"', '"quoted text"'),
        ("|\n  block text\n  second", "|\n  block text\n  second\n"),
    ],
)
def test_description_focus_is_the_exact_lexical_yaml_scalar(authored: str, focused: str) -> None:
    text = f"---\ndescription: {authored}\n---\nBody\n"
    assert _focus(text, "frontmatter.description") == focused


@pytest.mark.parametrize(
    ("frontmatter", "expected", "reason"),
    [
        ("title: only", ["file-body"], "selector-not-found"),
        ('description: ""', ["file-body"], "selector-not-found"),
        ("description: []", ["file-body"], "unsupported-source-shape"),
        ("- description", ["file-body"], "unsupported-source-shape"),
    ],
)
def test_description_discovery_and_resolution_state_table(
    frontmatter: str, expected: list[str], reason: str
) -> None:
    text = f"---\n{frontmatter}\n---\nBody\n"
    document = parse_markdown(text)
    assert [fragment.selector for fragment in document.fragments] == expected
    result = document.resolve("frontmatter.description")
    assert isinstance(result, MarkdownProblem)
    assert result.reason == reason


def test_duplicate_description_preserves_last_value_discovery_but_refuses_resolution() -> None:
    text = "---\ndescription: first\ndescription: second\n---\nBody\n"
    document = parse_markdown(text)
    assert [fragment.selector for fragment in document.fragments] == ["frontmatter.description"]
    result = document.resolve("frontmatter.description")
    assert isinstance(result, MarkdownProblem)
    assert result.reason == "selector-ambiguous"
    assert (result.line, result.column) == (3, 1)


def test_alias_description_is_discovered_but_never_editable() -> None:
    text = "---\nbase: &copy reusable\ndescription: *copy\n---\nBody\n"
    document = parse_markdown(text)
    assert [fragment.selector for fragment in document.fragments] == ["frontmatter.description"]
    result = document.resolve("frontmatter.description")
    assert isinstance(result, MarkdownProblem)
    assert result.reason == "unsupported-source-shape"


def test_body_only_range_starts_after_valid_frontmatter() -> None:
    text = "---\ntitle: Context\n---\nBody only\n"
    document = parse_markdown(text)
    assert [fragment.selector for fragment in document.fragments] == ["file-body"]
    assert _focus(text, "file-body") == "Body only\n"


def test_nested_duplicate_headings_focus_only_the_immediate_section_body() -> None:
    text = "# One\nbody\n## Two\nnested\n# One\n"
    document = parse_markdown(text)
    assert [fragment.selector for fragment in document.fragments] == [
        "heading:one",
        "heading:one/two",
        "heading:one~2",
    ]
    assert _focus(text, "heading:one") == "body\n"
    assert _focus(text, "heading:one/two") == "nested\n"
    assert _focus(text, "heading:one~2") == ""


def test_unknown_markdown_selector_grammar_and_drift_are_distinct() -> None:
    document = parse_markdown("# Known\nbody\n")
    assert document.resolve("heading:missing") == MarkdownProblem("selector-not-found")
    assert document.resolve("heading:*") == MarkdownProblem("unsupported-selector")
    assert document.resolve("frontmatter.title") == MarkdownProblem("unsupported-selector")


def test_malformed_frontmatter_short_circuits_batch_validation_and_discovery() -> None:
    text = "---\ndescription: [broken\n---\n# Heading\nbody\n"
    document = parse_markdown(text)
    problems = document.validate(("heading:heading", "frontmatter.description"))
    assert len(problems) == 1
    assert problems[0].reason == "invalid-source"
    assert problems[0].line is not None
    with pytest.raises(MarkdownDiscoveryError, match="invalid-source"):
        discover_markdown_fragments(text)
