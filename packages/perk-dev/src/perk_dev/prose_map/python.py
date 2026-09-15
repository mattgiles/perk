"""Shared pure-AST candidate language for module-level Python symbols.

Also home to the ONE Python-symbol admission rule (:func:`is_python_symbol_name`) and the
``symbol:<name>`` selector parser (:func:`python_symbol_selector_name`): discovery emits
``symbol:<name>`` for every name :func:`python_symbol_name` yields, and the prose-review adapter
admits a raw selector through the parser — both sides read the same predicate, so the adapter
admits exactly the catalog's language.
"""

import ast
import keyword
import unicodedata

type PythonSymbolCandidate = ast.FunctionDef | ast.AsyncFunctionDef | ast.Assign | ast.AnnAssign


def is_python_symbol_name(name: str) -> bool:
    """The one admission rule: a non-keyword identifier that is NFKC-stable.

    Python NFKC-normalizes identifiers, so ``ast`` hands back normalized names (a fullwidth
    ``for`` — ``U+FF46 U+FF4F U+FF52`` — arrives as the hard keyword ``for``); the node side is
    therefore always NFKC-stable, and a selector remainder must be too — a non-normalized
    spelling is one discovery can never emit and the adapter could never match, so it is
    refused rather than canonicalized. ``str.isidentifier`` refuses empty, whitespace, dotted
    and slashed remainders; ``keyword.iskeyword`` refuses hard keywords (soft keywords
    ``match`` / ``case`` / ``type`` stay admitted).
    """
    return (
        name.isidentifier()
        and not keyword.iskeyword(name)
        and unicodedata.normalize("NFKC", name) == name
    )


def python_symbols(module: ast.Module) -> tuple[PythonSymbolCandidate, ...]:
    """Return module-body candidates in order; ``python_symbol_name`` decides support."""
    return tuple(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign))
    )


def python_symbol_name(node: PythonSymbolCandidate) -> str | None:
    """Return the discovery-visible name for one module-body candidate, or ``None`` when the
    shape is unsupported or the name fails :func:`is_python_symbol_name`."""
    name: str | None = None
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = node.name
    elif isinstance(node, ast.Assign):
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        name = names[0] if len(names) == 1 else None
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        name = node.target.id
    if name is None or not is_python_symbol_name(name):
        return None
    return name


def python_symbol_selector_name(selector: str) -> str | None:
    """Parse a raw ``symbol:<name>`` selector into its admitted name, or ``None`` when the
    selector is not one discovery could have emitted (wrong prefix, or a remainder that fails
    :func:`is_python_symbol_name`)."""
    if not selector.startswith("symbol:"):
        return None
    name = selector.removeprefix("symbol:")
    if not is_python_symbol_name(name):
        return None
    return name
