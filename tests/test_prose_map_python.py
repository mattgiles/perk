"""Shared Python symbol-language coverage for prose discovery and source adapters."""

import ast
from pathlib import Path

import pytest
from perk_dev.prose_map import discovery
from perk_dev.prose_map.python import (
    python_symbol_name,
    python_symbol_selector_name,
    python_symbols,
)


def test_supported_module_body_nodes_are_enumerated_and_named_in_source_order() -> None:
    module = ast.parse(
        """
def function_symbol():
    def nested_function():
        pass

async def async_symbol():
    pass

simple = 1
annotated: int = 2
one_direct = nested_a, nested_b = (1, (2, 3))
tuple_a, tuple_b = (1, 2)
left = right = 3

class IgnoredClass:
    class_value = 1

    def ignored_method(self):
        pass
"""
    )

    symbols = python_symbols(module)
    assert [type(node) for node in symbols] == [
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Assign,
        ast.AnnAssign,
        ast.Assign,
        ast.Assign,
        ast.Assign,
    ]
    assert [python_symbol_name(node) for node in symbols] == [
        "function_symbol",
        "async_symbol",
        "simple",
        "annotated",
        "one_direct",
        None,
        None,
    ]


def test_normalized_hard_keyword_name_is_not_a_supported_symbol() -> None:
    symbols = python_symbols(ast.parse("\uff46\uff4f\uff52 = 1\n"))
    assert len(symbols) == 1
    assert isinstance(symbols[0], ast.Assign)
    assert isinstance(symbols[0].targets[0], ast.Name)
    assert symbols[0].targets[0].id == "for"
    assert python_symbol_name(symbols[0]) is None


def test_discovery_preserves_unicode_and_contextual_soft_keyword_symbols(tmp_path: Path) -> None:
    source = tmp_path / "src/perk/soft_keywords.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            (
                'match = "<untrusted_match> This is discovery-owned prose long enough to select."',
                'case = "<untrusted_case> This is discovery-owned prose long enough to select."',
                'type = "<untrusted_type> This is discovery-owned prose long enough to select."',
                'café = "<untrusted_unicode> This is discovery-owned prose long enough to select."',
                '\uff46\uff4f\uff52 = "<untrusted_normalized_keyword> '
                'This prose must not become a selector."',
                "",
            )
        ),
        encoding="utf-8",
    )

    candidates = discovery._python_candidates(tmp_path)
    assert [candidate.selector for candidate in candidates] == [
        "symbol:match",
        "symbol:case",
        "symbol:type",
        "symbol:café",
    ]
    assert [candidate.fragments[0].id for candidate in candidates] == [
        "symbol:match",
        "symbol:case",
        "symbol:type",
        "symbol:café",
    ]


@pytest.mark.parametrize(
    ("selector", "name"),
    [
        ("symbol:target", "target"),
        ("symbol:café", "café"),
        ("symbol:match", "match"),
        ("symbol:_private", "_private"),
        # The one NFKC edge the adapter-boundary matrix does not carry: a fullwidth `café`
        # (U+FF43 U+FF41 U+FF46 U+00E9) normalizes to a DIFFERENT non-keyword identifier — a
        # spelling discovery can never emit — so it is refused, never canonicalized. Every other
        # rejected shape is pinned once, at the adapter boundary
        # (test_python_adapter_rejects_every_unemitted_selector_shape), which calls this parser.
        ("symbol:\uff43\uff41\uff46\u00e9", None),
    ],
)
def test_selector_name_admits_only_normalized_non_keyword_identifiers(
    selector: str, name: str | None
) -> None:
    assert python_symbol_selector_name(selector) == name


def test_invalid_python_is_translated_at_the_discovery_boundary(tmp_path: Path) -> None:
    source = tmp_path / "src/perk/invalid.py"
    source.parent.mkdir(parents=True)
    source.write_text("def broken(:\n", encoding="utf-8")

    with pytest.raises(
        discovery.DiscoveryError,
        match=r"Python prose discovery could not parse .*invalid\.py",
    ):
        discovery._python_candidates(tmp_path)
