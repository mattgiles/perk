"""Tooling lockstep regression tests.

Promotes the `prek.toml` <-> `pyproject.toml` ruff-version lockstep assertion
formerly carried by `scripts/verify-p1-t6.sh` + `verify-p2-t3.sh` into pytest.
Pure file parsing — no `prek`/`ruff` binary dependency, so it always runs in CI.
"""

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ruff_floor() -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["dependency-groups"]["dev"]
    floors = [d for d in dev if d.replace(" ", "").startswith("ruff>=")]
    assert len(floors) == 1, dev
    return floors[0].split(">=", 1)[1].strip()


def _prek_ruff_repo() -> dict:
    prek = tomllib.loads((REPO_ROOT / "prek.toml").read_text(encoding="utf-8"))
    matches = [r for r in prek["repos"] if "ruff-pre-commit" in r["repo"]]
    assert len(matches) == 1, prek["repos"]
    return matches[0]


def test_prek_ruff_rev_matches_pyproject_floor():
    repo = _prek_ruff_repo()
    rev = repo["rev"].lstrip("v")
    assert rev == _ruff_floor()

    hook_ids = {h["id"] for h in repo["hooks"]}
    assert {"ruff-check", "ruff-format"} <= hook_ids, hook_ids


# The dignified-python §1.9 subprocess discipline (docs/design/dignified-convergence.md):
# every `subprocess.run(...)` lives inside one of these sanctioned wrapper functions
# (module stem, function name), and passes explicit `check=` and `timeout=` keywords.
_SANCTIONED_SUBPROCESS_WRAPPERS = {
    ("git", "_run"),
    ("git", "_run_capture"),
    ("_exec", "_run"),
    ("env", "_node_version"),
    ("init", "sync_skills"),
    ("doctor", "_fix_extension_deps"),
    ("run_worker", "_spawn_worker"),
}


def _subprocess_run_sites(
    tree: ast.Module,
) -> list[tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef | None]]:
    """Every `subprocess.run(...)` call paired with its nearest enclosing function (or None)."""
    sites: list[tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef | None]] = []

    def walk(node: ast.AST, func: ast.FunctionDef | ast.AsyncFunctionDef | None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func = node
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
        ):
            sites.append((node, func))
        for child in ast.iter_child_nodes(node):
            walk(child, func)

    walk(tree, None)
    return sites


def test_subprocess_run_only_in_sanctioned_wrappers_with_check_and_timeout():
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "perk").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(REPO_ROOT)
        for call, func in _subprocess_run_sites(tree):
            where = f"{rel}:{func.name if func else '<module>'} (line {call.lineno})"
            if func is None or (path.stem, func.name) not in _SANCTIONED_SUBPROCESS_WRAPPERS:
                offenders.append(
                    f"{where}: subprocess.run outside the sanctioned wrapper set — route it "
                    "through an existing wrapper or sanction it here deliberately"
                )
            keywords = {kw.arg for kw in call.keywords}
            for required in ("check", "timeout"):
                if required not in keywords:
                    offenders.append(f"{where}: subprocess.run missing explicit `{required}=`")
    assert not offenders, "\n".join(offenders)
