"""`perk-dev changelog-commits` regression tests.

Covers the pure helpers (marker/release/PR/truncation), the git-backed `gather` (marker discovery,
`--since` override, release fallback, error surfaces, lockfile filtering), and the CLI envelope.
"""

import json
import subprocess

import pytest
from click.testing import CliRunner
from perk_dev import changelog
from perk_dev.cli import cli


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _sha(cwd, ref: str = "HEAD") -> str:
    return _git(cwd, "rev-parse", ref).strip()


# --- pure helpers -------------------------------------------------------------------


def test_find_marker():
    assert changelog.find_marker("nope\n<!-- As of abc1234 -->\nmore") == "abc1234"
    assert changelog.find_marker("<!-- As of abc1234 -->  \n") == "abc1234"  # trailing ws tolerated
    assert changelog.find_marker("## [Unreleased]\nno marker here") is None


def test_latest_release_version():
    text = "## [Unreleased]\n\n## [1.2.3] - 2026-01-01\n\n## [1.0.0] - 2025-01-01\n"
    assert changelog.latest_release_version(text) == "1.2.3"
    assert changelog.latest_release_version("## [Unreleased]\nonly\n") is None


def test_extract_pr():
    assert changelog.extract_pr("add a thing (#1060)") == 1060
    assert changelog.extract_pr("Consolidate learnings #1049/#1048 … (#1055)") == 1055
    assert changelog.extract_pr("Perk init") is None
    assert changelog.extract_pr("Merge pull request #42 from x") == 42


def test_truncate_body():
    assert changelog.truncate_body("  short  ") == "short"
    long = "x" * 600
    out = changelog.truncate_body(long)
    assert len(out) == 501 and out.endswith("…")
    assert out[:500] == "x" * 500


# --- git-backed gather --------------------------------------------------------------


def _changelog_repo(tmp_path, *, changelog_text=None):
    """A repo with a base commit + two commits carrying `(#N)` subjects.

    Returns (root, base_sha, [c1_sha, c2_sha]). Writes `CHANGELOG.md` (committed on the base)
    when `changelog_text` is given.
    """
    root = tmp_path
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "perk tests")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    if changelog_text is not None:
        (root / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    base = _sha(root)

    (root / "a.txt").write_text("a\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "add a (#101)")
    c1 = _sha(root)

    (root / "b.txt").write_text("b\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "add b (#102)")
    c2 = _sha(root)
    return root, base, [c1, c2]


def test_gather_marker_discovery(tmp_path):
    root, base, _ = _changelog_repo(tmp_path, changelog_text="# Changelog\n")
    # The base SHA isn't known until the repo is built; write the marker now.
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [Unreleased]\n<!-- As of {base} -->\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "set marker")

    result = changelog.gather(root, since_flag=None)
    assert result.since_source == "marker"
    assert result.since_commit == base
    # Commits after base: the marker-set commit, add b, add a (newest first).
    subjects = [c.subject for c in result.commits]
    assert "add b (#102)" in subjects and "add a (#101)" in subjects


def test_gather_flag_override(tmp_path):
    root, _base, (c1, _c2) = _changelog_repo(tmp_path, changelog_text="# Changelog\n")
    result = changelog.gather(root, since_flag=c1)
    assert result.since_source == "flag"
    assert result.since_commit == c1
    # Range starts after c1 -> only "add b".
    assert [c.subject for c in result.commits] == ["add b (#102)"]


def test_gather_release_fallback(tmp_path):
    root, base, _ = _changelog_repo(
        tmp_path,
        changelog_text="# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-01-01\n",
    )
    _git(root, "tag", "v1.2.3", base)
    result = changelog.gather(root, since_flag=None)
    assert result.since_source == "release-fallback"
    assert result.since_commit == base


def test_gather_marker_unresolvable(tmp_path):
    root, _base, _ = _changelog_repo(
        tmp_path, changelog_text="# Changelog\n<!-- As of 0000000 -->\n"
    )
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag=None)
    assert exc.value.error_type == "marker_unresolvable"


def test_gather_changelog_not_found(tmp_path):
    root, _base, _ = _changelog_repo(tmp_path)  # no CHANGELOG.md written
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag=None)
    assert exc.value.error_type == "changelog_not_found"


def test_gather_filters_lockfiles(tmp_path):
    root, _base, _ = _changelog_repo(tmp_path, changelog_text="# Changelog\n")
    (root / "uv.lock").write_text("lock\n", encoding="utf-8")
    (root / "src.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "touch lock + src (#103)")
    head = _sha(root)

    result = changelog.gather(root, since_flag=head + "~1")
    rec = next(c for c in result.commits if c.hash == head)
    assert "uv.lock" not in rec.files
    assert "src.py" in rec.files


# --- CLI ----------------------------------------------------------------------------


def test_cli_json(tmp_path, monkeypatch):
    root, _base, (c1, _c2) = _changelog_repo(tmp_path, changelog_text="# Changelog\n")
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["changelog-commits", "--since", c1, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert len(payload["since_commit"]) == 40
    assert len(payload["head_commit"]) == 40
    assert payload["since_source"] == "flag"
    assert payload["commits"][0]["pr"] == 102


def test_cli_default_summary(tmp_path, monkeypatch):
    root, _base, (c1, _c2) = _changelog_repo(tmp_path, changelog_text="# Changelog\n")
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["changelog-commits", "--since", c1])
    assert result.exit_code == 0, result.output
    assert "(HEAD)" in result.stderr
    assert result.stdout == ""


def test_cli_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["changelog-commits", "--json"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "not_a_repo"


def test_cli_changelog_not_found(tmp_path, monkeypatch):
    root, _base, _ = _changelog_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["changelog-commits", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["error_type"] == "changelog_not_found"
