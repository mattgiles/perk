"""Packaging / publish-surface regression tests.

These promote the cross-plane packaging assertions formerly carried by the
`scripts/verify-*.sh` hard gates into the standard pytest suite:

- version lockstep across the version SSOT (`pyproject.toml` `[project] version`), the npm
  `package.json`, and the runtime-derived Python `perk.__version__`,
- the built **wheel** bundles `perk/_shared/{README,registry,contracts}` and
  `perk/_data/CHANGELOG.md`,
- the **npm tarball** ships `shared/` and `extension/index.ts` while excluding the dev-only
  `extension/testing/` + `*.test.ts` (skills are delivered by the external `skills` CLI from the
  git repo — they are no longer in the `pi` manifest or the npm tarball),
- the skill source quality (each `skills/*/SKILL.md` has frontmatter that parses and
  validates — Pi's loader rejects a skill whose YAML doesn't parse), with the `pi` manifest
  and `files` list asserted to *not* carry skills.

Build/pack tests skip cleanly when `uv`/`npm` are absent so the suite stays
CI-robust; in CI both toolchains are present so they actually run.
"""

import json
import shutil
import subprocess
import tarfile
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


def test_no_runtime_dependencies():
    # The extension must load from a bare git clone (no `npm install`): pi resolves its imports
    # through a fixed host-alias set plus `node_modules` walking, so a runtime npm dependency would
    # be unresolvable. The render seam's former lone runtime dep (`nunjucks`) is now vendored
    # (`extension/substrate/miniJinja.ts`); `package.json` must therefore carry no runtime
    # `dependencies` (key absent or empty). The companion source-scan
    # `extension/bareImportGuard.test.ts` proves no shipped source imports a bare npm package.
    deps = _package_json().get("dependencies", {})
    assert deps == {}, f"extension must have zero runtime dependencies, found: {deps}"


def test_npm_pin_lockstep():
    # Beyond the `__version__` lockstep, both perk-owned `@mgiles/perk` install pins must track the
    # file SSOT (`pyproject.toml` version): the `perk init` *wired* pin (`_perk_npm_entry()` written
    # into `.pi/settings.json`) and the *npm-install* pin (`_pinned_spec()` to `npm install`).
    from perk.convergence.init.extension_install import _pinned_spec
    from perk.convergence.init.settings import NPM_PACKAGE, _perk_npm_entry

    ssot = _pyproject_version()
    assert _perk_npm_entry() == f"npm:@mgiles/perk@{ssot}"
    assert _pinned_spec() == f"@mgiles/perk@{ssot}"
    # The install spec's package name is exactly the wired entry's name minus the `npm:` protocol.
    assert _pinned_spec().rsplit("@", 1)[0] == NPM_PACKAGE.removeprefix("npm:")


def test_pi_toolchain_pin_lockstep():
    # The pinned pi SDK (`@earendil-works/pi-coding-agent`) resolves its own nested pi-ai; a
    # top-level pi-ai pin that diverges from it puts test code and the session runtime in two
    # different pi-ai module instances (separate api registries — see
    # docs/learned/pi/headless-session-drive.md). Both devDeps must be exact versions (no range
    # prefix, so `npm ci` cannot drift them apart) and equal to each other.
    dev_deps = _package_json()["devDependencies"]
    sdk = dev_deps["@earendil-works/pi-coding-agent"]
    pi_ai = dev_deps["@earendil-works/pi-ai"]
    for name, pin in (("pi-coding-agent", sdk), ("pi-ai", pi_ai)):
        assert pin[0].isdigit(), f"@earendil-works/{name} must be an exact version, got {pin!r}"
    assert sdk == pi_ai, f"pi toolchain pins diverged: pi-coding-agent {sdk} != pi-ai {pi_ai}"


@pytest.fixture(scope="session")
def built_distributions(tmp_path_factory):
    """Build the wheel and sdist together once for the grouped packaging tests.

    The consumers share an `@pytest.mark.xdist_group("wheel_build")`, so under
    `-n auto --dist loadgroup` they land on one worker and reuse this build.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH")
    out_dir = tmp_path_factory.mktemp("distribution_build")
    # `--package perk` pins the build to the perk workspace member so the never-published
    # `perk-dev` member is never built (both distributions are unambiguously perk's).
    subprocess.run(
        ["uv", "build", "--package", "perk", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    wheels = list(out_dir.glob("*.whl"))
    sdists = list(out_dir.glob("*.tar.gz"))
    assert len(wheels) == 1, wheels
    assert len(sdists) == 1, sdists
    return wheels[0], sdists[0]


@pytest.fixture(scope="session")
def built_wheel(built_distributions):
    wheel, _sdist = built_distributions
    return wheel


@pytest.fixture(scope="session")
def built_sdist(built_distributions):
    _wheel, sdist = built_distributions
    return sdist


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
        # The boundary-model JSON Schema snapshots bundle into the wheel under the
        # `perk/_shared/schemas/` subdir (representative file proves the subdir ships).
        "perk/_shared/schemas/contracts/registry.schema.json",
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
def test_wheel_bundles_changelog(built_wheel):
    # The changelog is bundled into the wheel as `perk/_data` package data so the Python CLI can
    # display release notes at runtime. Wheel bundling is the whole delivery — npm shipping of the
    # changelog is deliberately deferred.
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    assert "perk/_data/CHANGELOG.md" in names, names


@pytest.mark.xdist_group("wheel_build")
def test_sdist_includes_changelog(built_sdist):
    # Hatchling errors (`Forced include not found`) when building the wheel from an sdist that is
    # missing a force-include source, so the sdist must carry the changelog at its root (the same
    # lockstep that keeps `shared`/`agents`/`prompts` in the sdist `only-include`).
    with tarfile.open(built_sdist) as tf:
        names = tf.getnames()
    assert f"perk-{_pyproject_version()}/CHANGELOG.md" in names, names


@pytest.mark.xdist_group("wheel_build")
def test_wheel_bundles_hunk_feedback_extension(built_wheel):
    # The bundled Hunk feedback publisher (contracts §8.58) ships as the single file
    # `perk/_hunk/perkFeedback.ts` so `perk plan watch` can pass an absolute `--extension`
    # path from the installed artifact. Its tests must NOT ride along.
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    assert "perk/_hunk/perkFeedback.ts" in names, names
    assert not any(n.startswith("perk/_hunk/") and n.endswith(".test.ts") for n in names), names


@pytest.mark.xdist_group("wheel_build")
def test_sdist_includes_hunk_feedback_extension(built_sdist):
    # Same lockstep as the changelog: a wheel built FROM the sdist must be able to satisfy the
    # `extension/hunkFeedback/perkFeedback.ts` force-include.
    with tarfile.open(built_sdist) as tf:
        names = tf.getnames()
    assert f"perk-{_pyproject_version()}/extension/hunkFeedback/perkFeedback.ts" in names, names


@pytest.mark.xdist_group("wheel_build")
def test_wheel_excludes_perk_dev(built_wheel):
    # The never-published `perk-dev` workspace member must never leak into perk's published wheel.
    with zipfile.ZipFile(built_wheel) as zf:
        names = zf.namelist()
    offenders = [n for n in names if "perk_dev" in n or "perk-dev" in n]
    assert not offenders, offenders


@pytest.mark.xdist_group("wheel_build")
def test_sdist_excludes_perk_dev(built_sdist):
    # The never-published `perk-dev` member (and the whole `packages/` tree) must never leak into
    # perk's published sdist; the sdist `only-include` excludes `packages/`.
    with tarfile.open(built_sdist) as tf:
        names = tf.getnames()
    offenders = [n for n in names if "perk_dev" in n or "perk-dev" in n or "/packages/" in n]
    assert not offenders, offenders


def test_build_pins_and_all_packages_flag_present():
    # The `perk-dev` never-published guarantee and the shared-venv dev-member resolution are
    # PROSE/comment-enforced, not otherwise test-enforced: reverting a pin or the sync flag would
    # only fail via a downstream symptom (a leaked member, or a `perk_dev` import error). This
    # guard names the reverted line directly. See docs/learned/workflow/distribution.md and
    # docs/learned/toolchain/uv-workspace-src-layout.md.
    build_sites = {
        "justfile": REPO_ROOT / "justfile",
        "release.yml": REPO_ROOT / ".github/workflows/release.yml",
        "release-checklist.md": REPO_ROOT / "docs/release-checklist.md",
    }
    for label, path in build_sites.items():
        assert "uv build --package perk" in path.read_text(encoding="utf-8"), (
            f"{label} must pin `uv build --package perk` so the dev-only member never leaks"
        )
    sync_sites = {
        "justfile": REPO_ROOT / "justfile",
        "ci.yml": REPO_ROOT / ".github/workflows/ci.yml",
    }
    for label, path in sync_sites.items():
        assert "uv sync --all-packages" in path.read_text(encoding="utf-8"), (
            f"{label} must use `uv sync --all-packages` so the dev-only member resolves in the venv"
        )


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
        "perk/_agents/learn-analyst.md",
        "perk/_agents/adversarial-reviewer.md",
        "perk/_agents/review-angle-selector.md",
        "perk/_agents/draft-reviewer.md",
        "perk/_agents/harvest-analyst.md",
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
    assert "shared/schemas/contracts/registry.schema.json" in paths
    assert "prompts/README.md" in paths

    # Dev-only surface must be excluded.
    assert not any(p.startswith("extension/testing/") for p in paths), paths
    assert not any(p.endswith(".test.ts") for p in paths), paths
    # Agent defs are delivered by the Python plane only — never via the npm tarball.
    assert not any(p.startswith("agents/") for p in paths), paths
    # The docs tree (the Starlight site workspace and canonical docs alike) never ships.
    assert not any(p.startswith("docs/") for p in paths), paths

    # `perk-dev release-build`'s pure checker must agree with the real pack output on every
    # run, so its expected/forbidden sets cannot silently drift from this test's asserts.
    from perk_dev.build import verify_tarball_files

    verify_tarball_files(paths)


def test_docs_site_publish_isolation():
    # The docs-site workspace is dev-only tooling: private, zero runtime deps, exact-pinned.
    # Two pin classes share the literal below — either way, any drift fails here:
    # - The shell/font pins (@astrojs/*, astro, @fontsource*) are design-bound by
    #   docs/design/docs-site-bridge-spike.md + docs/design/docs-site-visual-blueprint.md;
    #   moving one requires an explicit objective reconciliation (the records' shared rule).
    # - axe-core/jsdom are dev-only, plan-selected accessibility tooling (the static a11y gate
    #   in docs/site/checks/a11y.test.mjs) under the objective's "accessibility-test tool
    #   selection may remain plan-time" allowance — still exact-pinned. jsdom stays on 29.x:
    #   30.x's engines floor (^22.22.2 || …) exceeds the repo's documented effective dev floor
    #   (>=22.19.0, docs/site/README.md) under the root .npmrc's engine-strict=true.
    site = json.loads((REPO_ROOT / "docs/site/package.json").read_text(encoding="utf-8"))
    assert site["private"] is True
    assert "dependencies" not in site, site.get("dependencies")
    assert site["devDependencies"] == {
        "@astrojs/markdown-remark": "7.2.2",
        "@astrojs/starlight": "0.41.7",
        "@fontsource-variable/inter": "5.3.0",
        "@fontsource/ibm-plex-mono": "5.3.0",
        "astro": "7.2.1",
        "axe-core": "4.13.0",
        "jsdom": "29.1.1",
    }

    root = _package_json()
    assert root["workspaces"] == ["docs/site", "tools/prose-review"]
    assert not any(entry.startswith("docs") for entry in root["files"]), root["files"]

    # The prose-review workspace shares the same dev-only isolation posture: private, zero
    # runtime deps, exact-pinned toolchain (docs/design/prose-review-stack.md).
    workbench = json.loads(
        (REPO_ROOT / "tools/prose-review/package.json").read_text(encoding="utf-8")
    )
    assert workbench["private"] is True
    assert "dependencies" not in workbench, workbench.get("dependencies")
    assert workbench["devDependencies"] == {
        "@types/react": "19.2.18",
        "@types/react-dom": "19.2.4",
        "@vitejs/plugin-react": "6.0.5",
        "react": "19.2.8",
        "react-dom": "19.2.8",
        "vite": "8.2.1",
    }
    assert not any(entry.startswith("tools") for entry in root["files"]), root["files"]


@pytest.mark.xdist_group("wheel_build")
def test_wheel_and_sdist_exclude_docs_site(built_wheel, built_sdist):
    # Belt-and-suspenders: the wheel/sdist `packages`/`only-include` already exclude `docs/`
    # structurally; this names the docs-site workspace directly so a packaging change that
    # widens the include surface cannot silently ship it.
    with zipfile.ZipFile(built_wheel) as zf:
        wheel_names = zf.namelist()
    with tarfile.open(built_sdist) as tf:
        sdist_names = tf.getnames()
    offenders = [n for n in wheel_names + sdist_names if "docs/site" in n]
    assert not offenders, offenders


def test_skills_shipped():
    # Every shipped skill's frontmatter must parse and validate — Pi's loader rejects a skill
    # whose YAML frontmatter doesn't parse (e.g. an embedded `: ` in an unquoted plain scalar),
    # so a malformed SKILL.md ships a skill that never loads.
    from perk.convergence.init.repo_skills import parse_skill_frontmatter, validate_skill

    skills_dir = REPO_ROOT / "skills"
    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    assert skill_dirs, "expected at least one skill"
    for d in skill_dirs:
        assert (d / "SKILL.md").is_file(), f"{d.name} missing SKILL.md"
        frontmatter, reason = parse_skill_frontmatter((d / "SKILL.md").read_text(encoding="utf-8"))
        assert reason is None, f"{d.name}: {reason}"
        _, reason = validate_skill(d.name, frontmatter)
        assert reason is None, f"{d.name}: {reason}"

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
