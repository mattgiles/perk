"""`perk-dev release-info` regression tests.

Covers the pure `changelog.latest_release` helper, the git-backed `release.gather` (version
surfaces, local tag + best-effort origin probe, latest release header, marker-vs-HEAD, the
degrade-to-nulls posture, error surfaces), and the CLI envelope (report-only: exit 0 even when
the facts are unflattering).
"""

import json
import subprocess

import pytest
from click.testing import CliRunner
from perk_dev import changelog, release
from perk_dev.cli import cli

from perk import __version__ as perk_version


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _sha(cwd, ref: str = "HEAD") -> str:
    return _git(cwd, "rev-parse", ref).strip()


# --- pure helpers -------------------------------------------------------------------


def test_latest_release():
    text = "## [Unreleased]\n\n## [1.2.3] - 2026-01-01\n\n## [1.0.0] - 2025-01-01\n"
    assert changelog.latest_release(text) == ("1.2.3", "2026-01-01")
    assert changelog.latest_release("## [Unreleased]\nonly\n") is None


# --- git-backed gather --------------------------------------------------------------

_CHANGELOG = """# Changelog

## [Unreleased]
<!-- As of {marker} -->

## [1.0.0] - 2026-06-01
"""


def _release_repo(tmp_path, *, version="1.2.3"):
    """A one-commit repo with pyproject SSOT, package.json mirror, and a CHANGELOG.

    The changelog's marker starts unresolvable (`{marker}` literal is replaced by callers via
    `_set_marker`); gather reads files from the worktree, so post-commit rewrites need no commit.
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
    (root / "CHANGELOG.md").write_text(_CHANGELOG.format(marker="0000000"), encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def _set_marker(root, marker: str) -> None:
    (root / "CHANGELOG.md").write_text(_CHANGELOG.format(marker=marker), encoding="utf-8")


def _add_commit(root, name: str) -> str:
    (root / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", name)
    return _sha(root)


def _add_bare_origin(root, tmp_path):
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(root, "remote", "add", "origin", str(bare))
    return bare


def test_gather_happy_path(tmp_path):
    root = _release_repo(tmp_path)
    head = _sha(root)
    _set_marker(root, head[:7])
    _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")

    info = release.gather(root)
    assert info.current_version == "1.2.3"
    assert info.package_json_version == "1.2.3"
    assert info.runtime_version == perk_version
    assert info.tag_name == "v1.2.3"
    assert info.tag_exists is True
    assert info.tag_commit == head and len(info.tag_commit) == 40  # peeled, full SHA
    assert info.tag_at_head is True
    assert info.tag_on_remote is None  # no origin remote: unknowable, not "absent"
    assert info.remote_tag_commit is None
    assert info.latest_release_version == "1.0.0"
    assert info.latest_release_date == "2026-06-01"
    assert info.head_commit == head and len(info.head_commit) == 40
    assert info.marker_hash == head[:7]
    assert info.marker_commit == head
    assert info.marker_at_head is True


def test_gather_tag_missing(tmp_path):
    root = _release_repo(tmp_path)
    info = release.gather(root)
    assert info.tag_exists is False
    assert info.tag_commit is None
    assert info.tag_at_head is False


def test_gather_tag_behind_head(tmp_path):
    root = _release_repo(tmp_path)
    tagged = _sha(root)
    _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    _add_commit(root, "later")
    info = release.gather(root)
    assert info.tag_exists is True
    assert info.tag_commit == tagged
    assert info.tag_at_head is False


def test_gather_tag_on_remote_true(tmp_path):
    root = _release_repo(tmp_path)
    head = _sha(root)
    _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    _add_bare_origin(root, tmp_path)
    _git(root, "push", "-q", "origin", "v1.2.3")
    info = release.gather(root)
    assert info.tag_on_remote is True
    assert info.remote_tag_commit == head  # the peeled commit, not the tag object


def test_gather_tag_on_remote_false(tmp_path):
    root = _release_repo(tmp_path)
    _add_bare_origin(root, tmp_path)
    info = release.gather(root)
    assert info.tag_on_remote is False
    assert info.remote_tag_commit is None


def test_gather_remote_probed_even_without_local_tag(tmp_path):
    # A remote-only tag is a reportable state: the probe does not depend on the local tag.
    root = _release_repo(tmp_path)
    head = _sha(root)
    _git(root, "tag", "v1.2.3")
    _add_bare_origin(root, tmp_path)
    _git(root, "push", "-q", "origin", "v1.2.3")
    _git(root, "tag", "-d", "v1.2.3")
    info = release.gather(root)
    assert info.tag_exists is False
    assert info.tag_on_remote is True
    assert info.remote_tag_commit == head


def test_gather_marker_states(tmp_path):
    root = _release_repo(tmp_path)
    base = _sha(root)

    # Unresolvable hash: marker_hash reported, marker_commit null.
    info = release.gather(root)
    assert info.marker_hash == "0000000"
    assert info.marker_commit is None
    assert info.marker_at_head is False

    # Behind HEAD.
    _set_marker(root, base[:7])
    head = _add_commit(root, "later")
    info = release.gather(root)
    assert info.marker_commit == base
    assert info.marker_at_head is False
    assert info.head_commit == head

    # Missing marker line.
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
    info = release.gather(root)
    assert info.marker_hash is None
    assert info.marker_commit is None
    assert info.marker_at_head is False


def test_gather_missing_changelog(tmp_path):
    root = _release_repo(tmp_path)
    (root / "CHANGELOG.md").unlink()
    info = release.gather(root)
    assert info.latest_release_version is None
    assert info.latest_release_date is None
    assert info.marker_hash is None
    assert info.marker_commit is None
    assert info.marker_at_head is False


def test_gather_no_release_header(tmp_path):
    root = _release_repo(tmp_path)
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
    info = release.gather(root)
    assert info.latest_release_version is None
    assert info.latest_release_date is None


def test_gather_package_json_degrades_to_null(tmp_path):
    root = _release_repo(tmp_path)
    (root / "package.json").unlink()
    assert release.gather(root).package_json_version is None
    (root / "package.json").write_text(json.dumps({"version": 3}), encoding="utf-8")
    assert release.gather(root).package_json_version is None  # non-string: a fact, not an error


def test_gather_pyproject_not_found(tmp_path):
    root = _release_repo(tmp_path)
    (root / "pyproject.toml").unlink()
    with pytest.raises(release.ReleaseError) as exc:
        release.gather(root)
    assert exc.value.error_type == "pyproject_not_found"


def test_gather_bad_pyproject(tmp_path):
    root = _release_repo(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    with pytest.raises(release.ReleaseError) as exc:
        release.gather(root)
    assert exc.value.error_type == "bad_pyproject"
    (root / "pyproject.toml").write_text("not toml [", encoding="utf-8")
    with pytest.raises(release.ReleaseError) as exc:
        release.gather(root)
    assert exc.value.error_type == "bad_pyproject"


def test_gather_head_unresolvable(tmp_path):
    root = tmp_path
    _git(root, "init", "-q")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    with pytest.raises(release.ReleaseError) as exc:
        release.gather(root)
    assert exc.value.error_type == "head_unresolvable"


# --- CLI ----------------------------------------------------------------------------


def test_cli_json_report_only(tmp_path, monkeypatch):
    # Tag missing + stale marker: still exit 0 — release-info reports facts, never judges.
    root = _release_repo(tmp_path)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-info", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["error_type"] is None
    assert payload["current_version"] == "1.2.3"
    assert payload["package_json_version"] == "1.2.3"
    assert payload["runtime_version"] == perk_version
    assert payload["tag_name"] == "v1.2.3"
    assert payload["tag_exists"] is False
    assert payload["tag_on_remote"] is None
    assert payload["latest_release_version"] == "1.0.0"
    assert payload["latest_release_date"] == "2026-06-01"
    assert len(payload["head_commit"]) == 40
    assert payload["marker_hash"] == "0000000"
    assert payload["marker_commit"] is None
    assert payload["marker_at_head"] is False


def test_cli_default_summary(tmp_path, monkeypatch):
    root = _release_repo(tmp_path)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-info"])
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "pyproject 1.2.3" in result.stderr
    assert "tag v1.2.3: missing" in result.stderr
    assert "origin: unknown" in result.stderr
    assert "latest release: 1.0.0 (2026-06-01)" in result.stderr
    assert "marker: 0000000 (unresolvable)" in result.stderr


def test_cli_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["release-info", "--json"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "not_a_repo"
