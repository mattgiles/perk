"""`perk-dev changelog-check` regression tests.

Covers the pure structural linter (`changelog.check` over a temp `CHANGELOG.md`), the CLI envelope
(the six named cases plus not-a-repo/registration), and a baseline guard asserting the shipped root
`CHANGELOG.md` passes — that guard runs inside `just test` (pytest), so GitHub Actions CI keeps the
normalized changelog valid on every PR even though the standalone `just changelog-check` recipe is
local-only.
"""

import json
from pathlib import Path

from click.testing import CliRunner
from perk_dev import changelog
from perk_dev.cli import cli

_REPO_ROOT = Path(__file__).resolve().parent.parent

# A well-formed changelog: marker inside [Unreleased], a single-line unreleased bullet with a token,
# a released section with a token-free bullet, and only pinned categories.
_GOOD = """\
# Changelog

## [Unreleased]

<!-- As of fa6b115 -->

### Added

- add a shiny thing (abc1234)

### Changed

### Fixed

## [1.0.1] - 2026-06-24

### Added

- did a released thing with no token
"""


def _codes(result: changelog.ChangelogCheck) -> set[str]:
    return {f.code for f in result.findings}


def _write(root: Path, text: str) -> None:
    (root / "CHANGELOG.md").write_text(text, encoding="utf-8")


# --- pure check: happy path ---------------------------------------------------------


def test_well_formed_has_no_findings(tmp_path):
    _write(tmp_path, _GOOD)
    result = changelog.check(tmp_path)
    assert not result.has_errors()
    assert result.findings == ()


# --- pure check: error rules --------------------------------------------------------


def test_no_unreleased(tmp_path):
    _write(tmp_path, "# Changelog\n\n## [1.0.0] - 2026-01-01\n")
    result = changelog.check(tmp_path)
    assert "no_unreleased" in _codes(result)
    assert result.has_errors()


def test_duplicate_unreleased(tmp_path):
    _write(tmp_path, "# Changelog\n\n## [Unreleased]\n\n## [Unreleased]\n")
    result = changelog.check(tmp_path)
    assert "duplicate_unreleased" in _codes(result)


def test_bad_release_header(tmp_path):
    _write(tmp_path, "# Changelog\n\n## [Unreleased]\n\n## [1.0] - nope\n")
    result = changelog.check(tmp_path)
    assert "bad_release_header" in _codes(result)


def test_bad_marker_hash(tmp_path):
    _write(tmp_path, "# Changelog\n\n## [Unreleased]\n<!-- As of zzz -->\n")
    result = changelog.check(tmp_path)
    assert "bad_marker_hash" in _codes(result)


def test_duplicate_marker(tmp_path):
    _write(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n<!-- As of abc1234 -->\n<!-- As of def5678 -->\n",
    )
    result = changelog.check(tmp_path)
    assert "duplicate_marker" in _codes(result)


def test_marker_outside_unreleased(tmp_path):
    _write(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n<!-- As of abc1234 -->\n",
    )
    result = changelog.check(tmp_path)
    assert "marker_outside_unreleased" in _codes(result)


def test_unknown_category(tmp_path):
    _write(tmp_path, "# Changelog\n\n## [Unreleased]\n\n### Frobnicated\n")
    result = changelog.check(tmp_path)
    assert "unknown_category" in _codes(result)


def test_unreleased_missing_hash(tmp_path):
    _write(tmp_path, "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- no token here\n")
    result = changelog.check(tmp_path)
    assert "unreleased_missing_hash" in _codes(result)


def test_released_has_hash(tmp_path):
    _write(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n- released (abc1234)\n",
    )
    result = changelog.check(tmp_path)
    assert "released_has_hash" in _codes(result)


# --- pure check: warnings (exit 0, not has_errors) ----------------------------------


def test_missing_marker_is_a_warning(tmp_path):
    _write(tmp_path, "# Changelog\n\n## [Unreleased]\n\n### Added\n")
    result = changelog.check(tmp_path)
    warnings = {f.code for f in result.findings if f.severity == "warning"}
    assert "missing_marker" in warnings
    assert not result.has_errors()


def test_bad_bullet_indent_is_a_warning(tmp_path):
    _write(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n<!-- As of abc1234 -->\n\n### Added\n\n"
        "- top (abc1234)\n   - odd indent\n",
    )
    result = changelog.check(tmp_path)
    findings = {(f.code, f.severity) for f in result.findings}
    assert ("bad_bullet_indent", "warning") in findings
    assert not result.has_errors()


# --- pure check: nested/multi-line exemptions ---------------------------------------


def test_nested_bullet_exempt_from_token_rule(tmp_path):
    _write(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n<!-- As of abc1234 -->\n\n### Added\n\n"
        "- top-level entry (abc1234)\n  - a nested sub-bullet with no token\n",
    )
    result = changelog.check(tmp_path)
    assert "unreleased_missing_hash" not in _codes(result)
    assert not result.has_errors()


def test_released_multiline_prose_bullet_ok(tmp_path):
    _write(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n\n"
        "- a released bullet whose prose wraps across\n  continuation lines with no token\n",
    )
    result = changelog.check(tmp_path)
    assert "released_has_hash" not in _codes(result)
    assert not result.has_errors()


# --- CLI ----------------------------------------------------------------------------


def test_cli_missing_changelog(tmp_path, monkeypatch):
    # tmp_path is a directory but not a git repo; make it one so repo_root resolves.
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["changelog-check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "changelog_not_found"


def _cli_repo(tmp_path, monkeypatch, text):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _write(tmp_path, text)
    monkeypatch.chdir(tmp_path)


def test_cli_missing_marker_fallback(tmp_path, monkeypatch):
    _cli_repo(tmp_path, monkeypatch, "# Changelog\n\n## [Unreleased]\n\n### Added\n")
    result = CliRunner().invoke(cli, ["changelog-check", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert any(f["code"] == "missing_marker" for f in payload["findings"])


def test_cli_bad_marker_commit(tmp_path, monkeypatch):
    _cli_repo(tmp_path, monkeypatch, "# Changelog\n\n## [Unreleased]\n<!-- As of zzz -->\n")
    result = CliRunner().invoke(cli, ["changelog-check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert any(f["code"] == "bad_marker_hash" for f in payload["findings"])


def test_cli_bad_version_header(tmp_path, monkeypatch):
    _cli_repo(tmp_path, monkeypatch, "# Changelog\n\n## [Unreleased]\n\n## [1.0] - nope\n")
    result = CliRunner().invoke(cli, ["changelog-check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert any(f["code"] == "bad_release_header" for f in payload["findings"])


def test_cli_unreleased_without_hash(tmp_path, monkeypatch):
    _cli_repo(
        tmp_path, monkeypatch, "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- no token here\n"
    )
    result = CliRunner().invoke(cli, ["changelog-check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert any(f["code"] == "unreleased_missing_hash" for f in payload["findings"])


def test_cli_released_with_hash(tmp_path, monkeypatch):
    _cli_repo(
        tmp_path,
        monkeypatch,
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n- released (abc1234)\n",
    )
    result = CliRunner().invoke(cli, ["changelog-check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert any(f["code"] == "released_has_hash" for f in payload["findings"])


def test_cli_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["changelog-check", "--json"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "not_a_repo"


def test_cli_clean_ok(tmp_path, monkeypatch):
    _cli_repo(tmp_path, monkeypatch, _GOOD)
    result = CliRunner().invoke(cli, ["changelog-check"])
    assert result.exit_code == 0, result.output
    assert "CHANGELOG.md OK" in result.stderr


def test_changelog_check_is_registered():
    assert "changelog-check" in cli.commands


# --- baseline guard: the shipped CHANGELOG.md is structurally valid -----------------


def test_shipped_changelog_passes():
    result = changelog.check(_REPO_ROOT)
    assert not result.has_errors(), [f.code for f in result.findings if f.severity == "error"]
