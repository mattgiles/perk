"""Packaging / publish-surface regression tests.

These promote the cross-plane packaging assertions formerly carried by the
`scripts/verify-*.sh` hard gates into the standard pytest suite:

- version lockstep across the version SSOT (`pyproject.toml` `[project] version`), the npm
  `package.json`, and the runtime-derived Python `perk.__version__`,
- the built **wheel** bundles `perk/_shared/{README,registry,contracts}`,
- the **npm tarball** ships `shared/` and `extension/index.ts` while excluding the dev-only
  `extension/testing/` + `*.test.ts` (skills are delivered by the external `skills` CLI from the
  git repo — they are no longer in the `pi` manifest or the npm tarball),
- the skill source quality (each `skills/*/` has a `SKILL.md`), with the `pi` manifest and
  `files` list asserted to *not* carry skills.

Build/pack tests skip cleanly when `uv`/`npm` are absent so the suite stays
CI-robust; in CI both toolchains are present so they actually run.
"""

import json
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from perk import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]


def _package_json() -> dict:
    return json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_version_lockstep():
    # `pyproject.toml` `[project] version` is the SSOT (bumped via `uv version`). The npm
    # `package.json` mirrors it (install-independent file-literal lockstep), and the runtime
    # `perk.__version__` must derive to the same value in the `uv sync`'d test env.
    ssot = _pyproject_version()
    assert _package_json()["version"] == ssot
    assert __version__ == ssot


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory):
    """Build the wheel exactly once per session and share it across the wheel-bundle tests.

    The two `test_wheel_bundles_*` tests share an `@pytest.mark.xdist_group("wheel_build")`,
    so under `-n auto --dist loadgroup` they land on a single worker and reuse this one build
    instead of each running their own `uv build --wheel`.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH")
    out_dir = tmp_path_factory.mktemp("wheel_build")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


@pytest.mark.xdist_group("wheel_build")
def test_wheel_bundles_shared(built_wheel):
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    expected = {
        "perk/_shared/README.md",
        "perk/_shared/registry.yaml",
        "perk/_shared/bindings.yaml",
        "perk/_shared/providers.yaml",
        "perk/_shared/contracts.md",
        "perk/_shared/contracts-history.md",
    }
    assert expected <= names, expected - names


@pytest.mark.xdist_group("wheel_build")
def test_wheel_bundles_prompts(built_wheel):
    # The canonical cross-plane prompt templates are bundled into the wheel as `perk/_prompts`
    # (force-include), mirroring `perk/_shared`. The README is the durable bundling probe.
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    assert "perk/_prompts/README.md" in names, names


@pytest.mark.xdist_group("wheel_build")
def test_wheel_bundles_agents(built_wheel):
    # perk's subagent defs are bundled into the wheel as `perk/_agents` (force-include) so
    # `perk init` can materialize them into consumer `.pi/agents/perk/` dirs.
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    expected = {
        "perk/_agents/pr-reviewer.md",
        "perk/_agents/review-classifier.md",
        "perk/_agents/objective-explorer.md",
        "perk/_agents/conflict-resolver.md",
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
    assert "shared/bindings.yaml" in paths
    assert "shared/providers.yaml" in paths
    assert "shared/contracts.md" in paths
    assert "shared/contracts-history.md" in paths
    assert "shared/README.md" in paths
    assert "prompts/README.md" in paths

    # Dev-only surface must be excluded.
    assert not any(p.startswith("extension/testing/") for p in paths), paths
    assert not any(p.endswith(".test.ts") for p in paths), paths
    # Agent defs are delivered by the Python plane only — never via the npm tarball.
    assert not any(p.startswith("agents/") for p in paths), paths


def test_skills_shipped():
    skills_dir = REPO_ROOT / "skills"
    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    assert skill_dirs, "expected at least one skill"
    for d in skill_dirs:
        assert (d / "SKILL.md").is_file(), f"{d.name} missing SKILL.md"

    pkg = _package_json()
    # Skills are delivered by the `skills` CLI from the git repo, not by the Pi package or the
    # npm tarball: the `pi` manifest must not declare skills and the tarball must not ship them.
    assert "skills" not in pkg.get("pi", {})
    assert "skills/" not in pkg["files"]


def test_perk_skills_matches_skills_dir():
    # The `PERK_SKILLS` SSOT (drives the manifest fragment + post-sync presence check) must match
    # the on-disk `skills/` directory listing exactly, in both directions: a skill dir without a
    # tuple entry would silently not be delivered; a tuple entry without a dir would fail delivery.
    from perk.convergence.init import PERK_SKILLS

    skills_dir = REPO_ROOT / "skills"
    on_disk = {d.name for d in skills_dir.iterdir() if d.is_dir()}
    assert on_disk == set(PERK_SKILLS), f"PERK_SKILLS {set(PERK_SKILLS)} != skills/ dirs {on_disk}"
