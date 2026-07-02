"""`perk-dev bump-version` regression tests.

Covers the pure version math (`parse_version`/`resolve_target`), the pure roll transform
(`roll_unreleased`/`extract_roll_preview` on inline changelog strings + the committed text
golden), the CLI refusal surfaces, the no-subprocess `--dry-run` guarantee, and — when `uv` and
`npm` are on PATH — the temp-repo integration path (delegated writes + the duplicate-header
refusal on re-run). Repo lockstep stays pinned by `tests/test_packaging.py`, not here.
"""

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from _golden import TEXT_GOLDEN_DIR, assert_text_golden
from click.testing import CliRunner
from perk_dev import bump, changelog
from perk_dev.cli import cli

_CHANGELOG_DIR = TEXT_GOLDEN_DIR / "changelog"


def _fixture(name: str) -> str:
    return (_CHANGELOG_DIR / name).read_text(encoding="utf-8")


# --- version parsing + bump math ------------------------------------------------------


def test_parse_version_accepts_plain():
    assert bump.parse_version("1.2.3") == (1, 2, 3)
    assert bump.parse_version("0.10.200") == (0, 10, 200)


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "1.2.3rc1", "1.2.3.4", "", "one.two.three"])
def test_parse_version_rejects_non_xyz(bad):
    with pytest.raises(bump.BumpError) as excinfo:
        bump.parse_version(bad)
    assert excinfo.value.error_type == "bad_version"


def test_resolve_target_bump_components():
    assert bump.resolve_target("1.2.3", explicit=None, bump="patch") == "1.2.4"
    assert bump.resolve_target("1.2.9", explicit=None, bump="minor") == "1.3.0"
    assert bump.resolve_target("1.2.3", explicit=None, bump="major") == "2.0.0"


def test_resolve_target_explicit():
    assert bump.resolve_target("1.2.3", explicit="1.10.0", bump=None) == "1.10.0"


@pytest.mark.parametrize("target", ["1.2.3", "1.2.2", "0.9.9"])
def test_resolve_target_not_greater(target):
    with pytest.raises(bump.BumpError) as excinfo:
        bump.resolve_target("1.2.3", explicit=target, bump=None)
    assert excinfo.value.error_type == "not_greater"


# --- roll_unreleased ------------------------------------------------------------------

_ROLLABLE = """\
# Changelog

## [Unreleased]

<!-- As of 1111111 -->

### Added

- a new thing (1234567)
  - a nested detail (fedcba9)

### Changed

### Fixed

- a fix (0a1b2c3)

## [1.0.1] - 2026-06-24

### Added

- a released entry with no token
"""


def _roll(text: str = _ROLLABLE, version: str = "1.1.0") -> changelog.RolledChangelog:
    return changelog.roll_unreleased(text, version=version, date="2026-07-01", head_short="abc1234")


def test_roll_strips_tokens_from_top_level_bullets():
    rolled = _roll()
    assert "- a new thing\n" in rolled.text
    assert "- a fix\n" in rolled.text
    assert "(1234567)" not in rolled.text
    assert "(0a1b2c3)" not in rolled.text
    assert rolled.entries == 2


def test_roll_leaves_nested_bullets_untouched():
    assert "  - a nested detail (fedcba9)" in _roll().text


def test_roll_replaces_marker():
    rolled = _roll()
    assert "<!-- As of 1111111 -->" not in rolled.text
    assert rolled.text.count("<!-- As of ") == 1
    assert "## [Unreleased]\n\n<!-- As of abc1234 -->\n\n## [1.1.0] - 2026-07-01" in rolled.text


def test_roll_drops_empty_category_segments():
    rolled = _roll()
    assert "### Changed" not in rolled.text
    assert "### Added" in rolled.text and "### Fixed" in rolled.text


def test_roll_leaves_remainder_untouched():
    rolled = _roll()
    remainder = _ROLLABLE[_ROLLABLE.index("## [1.0.1]") :]
    assert rolled.text.endswith(remainder)
    preamble = "# Changelog\n\n"
    assert rolled.text.startswith(preamble)


def test_roll_duplicate_release_header_refused():
    with pytest.raises(changelog.ChangelogError) as excinfo:
        _roll(version="1.0.1")
    assert excinfo.value.error_type == "duplicate_release_header"


def test_roll_no_unreleased():
    with pytest.raises(changelog.ChangelogError) as excinfo:
        _roll("# Changelog\n\n## [1.0.0] - 2026-01-01\n")
    assert excinfo.value.error_type == "no_unreleased"


def test_roll_nothing_to_release():
    scaffold = (
        "# Changelog\n\n## [Unreleased]\n\n<!-- As of 1111111 -->\n\n### Added\n\n### Fixed\n"
    )
    with pytest.raises(changelog.ChangelogError) as excinfo:
        _roll(scaffold)
    assert excinfo.value.error_type == "nothing_to_release"


# --- goldens --------------------------------------------------------------------------


def test_golden_roll():
    rolled = _roll(_fixture("roll.input.md"))
    assert rolled.entries == 4
    assert_text_golden("changelog/roll.expected", rolled.text, suffix=".md")


def test_rolled_changelog_is_check_clean(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(_roll().text, encoding="utf-8")
    assert not changelog.check(tmp_path).has_errors()


def test_extract_roll_preview_spans_both_sections():
    preview = changelog.extract_roll_preview(_fixture("roll.expected.md"), "1.1.0")
    assert preview.startswith("## [Unreleased]\n")
    assert "## [1.1.0] - 2026-07-01" in preview
    assert "## [1.0.1]" not in preview
    assert preview.endswith("- A bug fix\n")


# --- CLI refusals ---------------------------------------------------------------------


def _git(cwd, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=30)


def _bump_repo(tmp_path, monkeypatch, *, version: str = "1.2.3", commit: bool = True) -> Path:
    """A minimal repo for the plan/refusal paths: pyproject SSOT + a rollable CHANGELOG."""
    root = tmp_path
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "perk tests")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(_ROLLABLE, encoding="utf-8")
    if commit:
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")
    monkeypatch.chdir(root)
    return root


def test_cli_registered():
    assert "bump-version" in cli.commands


def test_cli_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["bump-version", "1.3.0"])
    assert result.exit_code == 2, result.output


def test_cli_neither_version_nor_bump(tmp_path, monkeypatch):
    _bump_repo(tmp_path, monkeypatch, commit=False)
    result = CliRunner().invoke(cli, ["bump-version"])
    assert result.exit_code == 1, result.output
    assert "exactly one" in result.stderr


def test_cli_both_version_and_bump(tmp_path, monkeypatch):
    _bump_repo(tmp_path, monkeypatch, commit=False)
    result = CliRunner().invoke(cli, ["bump-version", "1.3.0", "--bump", "patch"])
    assert result.exit_code == 1, result.output
    assert "exactly one" in result.stderr


def test_cli_bad_version(tmp_path, monkeypatch):
    _bump_repo(tmp_path, monkeypatch, commit=False)
    result = CliRunner().invoke(cli, ["bump-version", "v1.3.0"])
    assert result.exit_code == 1, result.output
    assert "X.Y.Z" in result.stderr


def test_cli_not_greater(tmp_path, monkeypatch):
    _bump_repo(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["bump-version", "1.2.3"])
    assert result.exit_code == 1, result.output
    assert "not greater" in result.stderr


def test_cli_nothing_to_release(tmp_path, monkeypatch):
    root = _bump_repo(tmp_path, monkeypatch)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n<!-- As of 1111111 -->\n", encoding="utf-8"
    )
    result = CliRunner().invoke(cli, ["bump-version", "1.3.0"])
    assert result.exit_code == 1, result.output
    assert "no entries" in result.stderr


def test_cli_dry_run_no_writes_no_subprocesses(tmp_path, monkeypatch):
    root = _bump_repo(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(bump, "_run", lambda args, **kwargs: calls.append(args))
    result = CliRunner().invoke(cli, ["bump-version", "1.3.0", "--dry-run"])
    assert result.exit_code == 0, result.output
    # stdout carries the preview region: the fresh [Unreleased] through the new release section.
    assert result.stdout.startswith("## [Unreleased]\n")
    assert "## [1.3.0] - " in result.stdout
    assert "- a new thing\n" in result.stdout
    assert "## [1.0.1]" not in result.stdout
    assert "bump 1.2.3 \u2192 1.3.0" in result.stderr
    assert "(2 entries)" in result.stderr
    assert "dry run" in result.stderr
    # Nothing written, nothing spawned.
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == _ROLLABLE
    assert "1.2.3" in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert calls == []


def test_cli_marker_behind_head_warns(tmp_path, monkeypatch):
    root = _bump_repo(tmp_path, monkeypatch)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    (root / "later.txt").write_text("later\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "later")
    (root / "CHANGELOG.md").write_text(
        _ROLLABLE.replace("<!-- As of 1111111 -->", f"<!-- As of {base[:7]} -->"),
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli, ["bump-version", "1.3.0", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "marker is behind HEAD" in result.stderr


# --- temp-repo integration (delegated writes) -----------------------------------------

_PACKAGE_LOCK = {
    "name": "demo",
    "version": "1.2.3",
    "lockfileVersion": 3,
    "requires": True,
    "packages": {"": {"name": "demo", "version": "1.2.3"}},
}


@pytest.mark.skipif(
    shutil.which("uv") is None or shutil.which("npm") is None,
    reason="requires uv and npm on PATH",
)
def test_cli_bump_integration(tmp_path, monkeypatch):
    root = _bump_repo(tmp_path, monkeypatch)
    (root / "package.json").write_text(
        json.dumps({"name": "demo", "version": "1.2.3"}), encoding="utf-8"
    )
    (root / "package-lock.json").write_text(json.dumps(_PACKAGE_LOCK, indent=2), encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "npm files")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()

    result = CliRunner().invoke(cli, ["bump-version", "1.3.0"])
    assert result.exit_code == 0, result.output
    assert "pyproject.toml + uv.lock \u2192 1.3.0" in result.stderr
    assert "package.json + package-lock.json \u2192 1.3.0" in result.stderr
    assert f"marker now {head[:7]}" in result.stderr

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == "1.3.0"
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    demo = next(p for p in lock["package"] if p["name"] == "demo")
    assert demo["version"] == "1.3.0"
    package_json = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert package_json["version"] == "1.3.0"
    package_lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    assert package_lock["version"] == "1.3.0"
    assert package_lock["packages"][""]["version"] == "1.3.0"

    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.3.0] - " in text
    assert "(1234567)" not in text and "(0a1b2c3)" not in text  # released section token-free
    assert f"## [Unreleased]\n\n<!-- As of {head[:7]} -->" in text
    assert text.count("<!-- As of ") == 1
    assert not changelog.check(root).has_errors()

    # Re-run: the duplicate-header refusal fires pre-flight — exit 1, no file changes.
    files = ("pyproject.toml", "uv.lock", "package.json", "package-lock.json", "CHANGELOG.md")
    before = {name: (root / name).read_text(encoding="utf-8") for name in files}
    rerun = CliRunner().invoke(cli, ["bump-version", "1.3.0"])
    assert rerun.exit_code == 1, rerun.output
    assert "already has" in rerun.stderr
    for name, content in before.items():
        assert (root / name).read_text(encoding="utf-8") == content
