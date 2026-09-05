"""Execute the vendored guide's corrected annotation examples on the supported Python runtime."""

import re
import sys
from pathlib import Path

import pytest

from perk.substrate.proc import run_captured

REPO_ROOT = Path(__file__).resolve().parents[1]


def _example(heading: str) -> str:
    guide = REPO_ROOT / "skills" / "dignified-python" / "versions" / "python-3.13.md"
    _, marker, following = guide.read_text(encoding="utf-8").partition(f"\n{heading}\n")
    assert marker, f"missing example section: {heading}"
    preamble, opening, following = following.partition("```python\n")
    assert opening and not re.search(r"^#{1,6} ", preamble, re.MULTILINE), (
        f"missing Python example before the next section: {heading}"
    )
    code, closing, _ = following.partition("\n```")
    assert closing, f"unclosed example in {heading}"
    return code


@pytest.mark.parametrize(
    "heading",
    [
        "### Quoted forward references",
        "### Optional postponed annotations",
        "### Tree Structure with Quoted Forward References",
        "### Python 3.10/3.11",
        "### Python 3.13",
    ],
)
def test_forward_reference_examples(heading, tmp_path):
    # Execute the actual guide, not a parallel copy of its examples. On 3.13 an unprotected
    # self-reference fails during class definition; the string check keeps that protection
    # explicit even when this suite runs on a newer, lazily-evaluating Python.
    code = _example(heading) + (
        '\nassert isinstance(Node.__init__.__annotations__["parent"], str)\nNode(1)\n'
    )
    result = run_captured([sys.executable, "-I", "-c", code], cwd=tmp_path, timeout=10)
    assert result.returncode == 0, result.stderr


def test_generic_self_example(tmp_path):
    code = _example("## Generic Classes with PEP 695 (3.12+)") + (
        "\nassert int_stack.pop() == 43\nassert int_stack.pop() == 42\n"
    )
    result = run_captured([sys.executable, "-I", "-c", code], cwd=tmp_path, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("first,second", [("a", "b"), ("b", "a")])
def test_type_only_circular_import_examples(first, second, tmp_path):
    for name in (first, second):
        (tmp_path / f"{name}.py").write_text(_example(f"#### {name}.py"), encoding="utf-8")
    script = tmp_path / "check_examples.py"
    script.write_text(
        f"import {first}\nimport {second}\n"
        "from typing import get_type_hints\n"
        "assert a.A().method() is None\nassert b.B().method() is None\n"
        # Runtime introspection needs the names omitted by TYPE_CHECKING, as the guide warns.
        'names = {"A": a.A, "B": b.B}\n'
        'assert get_type_hints(a.A.method, globalns=names)["return"] == b.B | None\n'
        'assert get_type_hints(b.B.method, globalns=names)["return"] == a.A | None\n',
        encoding="utf-8",
    )
    result = run_captured([sys.executable, "-E", str(script)], cwd=tmp_path, timeout=10)
    assert result.returncode == 0, result.stderr
