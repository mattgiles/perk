"""`perk-dev release-check` regression tests.

Covers the offline `release.check_release` composition (changelog lint + version lockstep +
tag agreement + the `--for-publish` clean-tree gate), the CLI envelope (exit 1 iff error
findings; warnings alone exit 0), and a baseline guard asserting the real repo passes — so
CI keeps the shipped release state valid on every PR.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner
from perk_dev import changelog, release
from perk_dev.cli import cli

from perk import __version__ as perk_version

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _sha(cwd, ref: str = "HEAD") -> str:
    return _git(cwd, "rev-parse", ref).strip()


# A changelog-check-clean CHANGELOG: marker inside [Unreleased], tokened unreleased bullets.
_CHANGELOG = """\
# Changelog

## [Unreleased]

<!-- As of fa6b115 -->

### Added

- add a shiny thing (abc1234)

## [1.0.0] - 2026-06-01

### Added

- a released thing with no token
"""


def _check_repo(tmp_path, *, version: str = perk_version):
    """A one-commit repo whose surfaces agree at ``version`` and whose CHANGELOG is clean.

    Defaults to the installed perk version so the ``runtime_stale`` warning stays silent —
    the all-green baseline; tests that want the warning pass a divergent ``version``.
    """
    root = tmp_path
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "perk tests")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "package.json").write_text(
        json.dumps({"name": "demo", "version": version}), encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def _add_commit(root, name: str) -> str:
    (root / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", name)
    return _sha(root)


def _codes(result: release.ReleaseCheck) -> set[str]:
    return {f.code for f in result.findings}


# --- check_release ------------------------------------------------------------------


def test_all_green(tmp_path):
    result = release.check_release(_check_repo(tmp_path), for_publish=False)
    assert result.findings == ()
    assert not result.has_errors()


def test_version_mismatch_divergent(tmp_path):
    root = _check_repo(tmp_path)
    (root / "package.json").write_text(
        json.dumps({"name": "demo", "version": "9.9.9"}), encoding="utf-8"
    )
    result = release.check_release(root, for_publish=False)
    finding = next(f for f in result.findings if f.code == "version_mismatch")
    assert finding.severity == "error"
    assert result.has_errors()


def test_version_mismatch_missing_package_json(tmp_path):
    root = _check_repo(tmp_path)
    (root / "package.json").unlink()
    result = release.check_release(root, for_publish=False)
    finding = next(f for f in result.findings if f.code == "version_mismatch")
    assert "missing" in finding.message


def test_runtime_stale_is_warning_only(tmp_path):
    root = _check_repo(tmp_path, version="0.0.1")
    # package.json agrees with pyproject; only the installed perk version diverges.
    result = release.check_release(root, for_publish=False)
    assert _codes(result) == {"runtime_stale"}
    assert not result.has_errors()  # a warning alone: exit stays 0


def test_agreeing_v_tag_at_head_passes(tmp_path):
    root = _check_repo(tmp_path)
    _git(root, "tag", "-a", f"v{perk_version}", "-m", "release")
    result = release.check_release(root, for_publish=False)
    assert result.findings == ()


def test_disagreeing_v_tag_at_head_is_error(tmp_path):
    root = _check_repo(tmp_path)
    _git(root, "tag", "-a", "v9.9.9", "-m", "wrong")
    result = release.check_release(root, for_publish=False)
    finding = next(f for f in result.findings if f.code == "tag_disagreement")
    assert finding.severity == "error"
    assert "v9.9.9" in finding.message


def test_tag_not_at_head_is_warning(tmp_path):
    root = _check_repo(tmp_path)
    _git(root, "tag", "-a", f"v{perk_version}", "-m", "release")
    _add_commit(root, "later")
    result = release.check_release(root, for_publish=False)
    finding = next(f for f in result.findings if f.code == "tag_not_at_head")
    assert finding.severity == "warning"
    assert not result.has_errors()


def test_dirty_tree_only_under_for_publish(tmp_path):
    root = _check_repo(tmp_path)
    (root / "scratch.txt").write_text("wip\n", encoding="utf-8")
    assert "dirty_tree" not in _codes(release.check_release(root, for_publish=False))
    result = release.check_release(root, for_publish=True)
    finding = next(f for f in result.findings if f.code == "dirty_tree")
    assert finding.severity == "error"


def test_changelog_structural_error_propagates(tmp_path):
    root = _check_repo(tmp_path)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n<!-- As of fa6b115 -->\n\n- bullet without token\n",
        encoding="utf-8",
    )
    result = release.check_release(root, for_publish=False)
    assert "unreleased_missing_hash" in _codes(result)
    assert result.has_errors()


# --- CLI ----------------------------------------------------------------------------


def test_cli_green_exit_0(tmp_path, monkeypatch):
    monkeypatch.chdir(_check_repo(tmp_path))
    result = CliRunner().invoke(cli, ["release-check"])
    assert result.exit_code == 0, result.output
    assert "release-check OK" in result.stderr


def test_cli_errors_exit_1(tmp_path, monkeypatch):
    root = _check_repo(tmp_path)
    (root / "package.json").unlink()
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-check"])
    assert result.exit_code == 1, result.output
    assert "version_mismatch" in result.stderr
    assert "release-check OK" not in result.stderr


def test_cli_json_envelope(tmp_path, monkeypatch):
    root = _check_repo(tmp_path)
    _git(root, "tag", "-a", "v9.9.9", "-m", "wrong")
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error_type"] == "check_failed"
    codes = {f["code"] for f in payload["findings"]}
    assert "tag_disagreement" in codes


def test_cli_missing_changelog_is_hard_failure(tmp_path, monkeypatch):
    root = _check_repo(tmp_path)
    (root / "CHANGELOG.md").unlink()
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error_type"] == "changelog_not_found"


def test_cli_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["release-check", "--json"])
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_release_check_is_registered():
    assert "release-check" in cli.commands


# --- baseline guard: the real repo passes release-check -----------------------------


def test_real_repo_has_no_error_findings():
    result = release.check_release(REPO_ROOT, for_publish=False)
    assert not result.has_errors(), [f for f in result.findings if f.severity == "error"]


def test_reuses_changelog_finding_vocabulary():
    # ReleaseCheck reuses changelog.Finding — one findings vocabulary across both checkers.
    assert release.ReleaseCheck(()).findings == ()
    f = changelog.Finding("error", "version_mismatch", None, "x")
    assert release.ReleaseCheck((f,)).has_errors()
