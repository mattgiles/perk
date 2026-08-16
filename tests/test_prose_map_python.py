"""Shared Python symbol-language coverage for prose discovery and source adapters."""

import ast
from pathlib import Path

import pytest
from perk_dev.prose_map import discovery
from perk_dev.prose_map.python import python_symbol_name, python_symbols


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


def test_invalid_python_is_translated_at_the_discovery_boundary(tmp_path: Path) -> None:
    source = tmp_path / "src/perk/invalid.py"
    source.parent.mkdir(parents=True)
    source.write_text("def broken(:\n", encoding="utf-8")

    with pytest.raises(
        discovery.DiscoveryError,
        match=r"Python prose discovery could not parse .*invalid\.py",
    ):
        discovery._python_candidates(tmp_path)
