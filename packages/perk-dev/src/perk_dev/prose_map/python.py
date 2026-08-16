"""Shared pure-AST language for supported module-level Python symbols."""

import ast

type PythonSymbol = ast.FunctionDef | ast.AsyncFunctionDef | ast.Assign | ast.AnnAssign


def python_symbols(module: ast.Module) -> tuple[PythonSymbol, ...]:
    """Return supported module-body symbols in source order without walking nested scopes."""
    return tuple(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign))
    )


def python_symbol_name(node: PythonSymbol) -> str | None:
    """Return the discovery-visible name for one supported module-body node."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.Assign):
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        return names[0] if len(names) == 1 else None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None
