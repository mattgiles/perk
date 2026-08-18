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
# `perk.substrate.proc.run_captured` is the ONE captured primitive (every captured facade
# translates its ProcFailure); the other three are the inherited-stdio streaming idiom,
# which is a different shape and keeps its own literals.
_SANCTIONED_SUBPROCESS_WRAPPERS = {
    ("proc", "run_captured"),
    ("proc", "run_interactive"),
    ("run_worker", "_spawn_worker"),
    ("materialize", "run_worktree_setup"),
    ("shared", "run_skills"),
    # The prose-review GitReader's one bytes-mode captured spawn (app-owned, the
    # checks-`_spawn` precedent): porcelain `-z` pathname bytes and diff content
    # bytes are undecodable in `proc.run_captured`'s strict text mode.
    ("git", "_run_captured_bytes"),
}

# The one sanctioned `subprocess.Popen` site: the prose-review CheckRunner's streaming
# spawn (app-owned; `perk.substrate.proc` stays blocking-and-capture). Every Popen must
# pass explicit `cwd=` and `start_new_session=` (the killable-process-group discipline).
_SANCTIONED_POPEN_SITES = {
    ("checks", "_spawn"),
}


def _subprocess_call_sites(
    tree: ast.Module,
    attribute: str,
) -> list[tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef | None]]:
    """Every `subprocess.<attribute>(...)` call paired with its nearest enclosing function."""
    sites: list[tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef | None]] = []

    def walk(node: ast.AST, func: ast.FunctionDef | ast.AsyncFunctionDef | None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func = node
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attribute
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
    scan_roots = (
        REPO_ROOT / "src" / "perk",
        # The two deliberate perk-dev exceptions are the CheckRunner's Popen `_spawn`
        # (sanctioned below) and the GitReader's bytes-mode `_run_captured_bytes`
        # (sanctioned above); no other perk-dev subprocess literal is permitted.
        REPO_ROOT / "packages" / "perk-dev" / "src" / "perk_dev",
    )
    for path in sorted(p for root in scan_roots for p in root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(REPO_ROOT)
        for call, func in _subprocess_call_sites(tree, "run"):
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
        for call, func in _subprocess_call_sites(tree, "Popen"):
            where = f"{rel}:{func.name if func else '<module>'} (line {call.lineno})"
            if func is None or (path.stem, func.name) not in _SANCTIONED_POPEN_SITES:
                offenders.append(
                    f"{where}: subprocess.Popen outside the sanctioned streaming spawn — "
                    "sanction it here deliberately or use a captured wrapper"
                )
            keywords = {kw.arg for kw in call.keywords}
            for required in ("cwd", "start_new_session"):
                if required not in keywords:
                    offenders.append(f"{where}: subprocess.Popen missing explicit `{required}=`")
    assert not offenders, "\n".join(offenders)
