"""Shared pure-AST candidate language for module-level Python symbols."""

import ast
import keyword

type PythonSymbolCandidate = ast.FunctionDef | ast.AsyncFunctionDef | ast.Assign | ast.AnnAssign


def python_symbols(module: ast.Module) -> tuple[PythonSymbolCandidate, ...]:
    """Return module-body candidates in order; ``python_symbol_name`` decides support."""
    return tuple(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign))
    )


def python_symbol_name(node: PythonSymbolCandidate) -> str | None:
    """Return the discovery-visible non-keyword name for one module-body candidate."""
    name: str | None = None
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = node.name
    elif isinstance(node, ast.Assign):
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        name = names[0] if len(names) == 1 else None
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        name = node.target.id
    if name is None or keyword.iskeyword(name):
        return None
    return name
