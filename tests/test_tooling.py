"""Tooling lockstep regression tests.

Promotes the `prek.toml` <-> `pyproject.toml` ruff-version lockstep assertion
formerly carried by `scripts/verify-p1-t6.sh` + `verify-p2-t3.sh` into pytest.
Pure file parsing — no `prek`/`ruff` binary dependency, so it always runs in CI.
"""

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
