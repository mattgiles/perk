"""Packaging / publish-surface regression tests.

These promote the cross-plane packaging assertions formerly carried by the
`scripts/verify-*.sh` hard gates into the standard pytest suite:

- version lockstep between the npm `package.json` and the Python `perk.__version__`,
- the built **wheel** bundles `perk/_shared/{README,registry,contracts}`,
- the **npm tarball** ships `shared/`, `extension/index.ts`, and `skills/` while
  excluding the dev-only `extension/testing/` + `*.test.ts`,
- the skills publish surface (each `skills/*/` has a `SKILL.md`, declared in `package.json`).

Build/pack tests skip cleanly when `uv`/`npm` are absent so the suite stays
CI-robust; in CI both toolchains are present so they actually run.
"""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from perk import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]


def _package_json() -> dict:
    return json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))


def test_version_lockstep():
    # The npm package.json version and the Python single-source version must match.
    assert _package_json()["version"] == __version__


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_wheel_bundles_shared(tmp_path):
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())
    expected = {
        "perk/_shared/README.md",
        "perk/_shared/registry.yaml",
        "perk/_shared/contracts.md",
    }
    assert expected <= names, expected - names


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm not on PATH")
def test_npm_pack_lists_shipped_and_excludes_dev():
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    data = json.loads(result.stdout)
    paths = {f["path"] for f in data[0]["files"]}

    # Shipped surface.
    assert "extension/index.ts" in paths
    assert "shared/registry.yaml" in paths
    assert "shared/contracts.md" in paths
    assert "shared/README.md" in paths
    assert any(p.startswith("skills/") for p in paths), paths

    # Dev-only surface must be excluded.
    assert not any(p.startswith("extension/testing/") for p in paths), paths
    assert not any(p.endswith(".test.ts") for p in paths), paths


def test_skills_shipped():
    skills_dir = REPO_ROOT / "skills"
    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    assert skill_dirs, "expected at least one skill"
    for d in skill_dirs:
        assert (d / "SKILL.md").is_file(), f"{d.name} missing SKILL.md"

    pkg = _package_json()
    assert pkg["pi"]["skills"] == ["./skills"]
    assert "skills/" in pkg["files"]
