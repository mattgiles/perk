"""`perk-dev changelog-commits` regression tests.

Covers the pure helpers (marker/release/PR/truncation), the git-backed `gather` (marker discovery,
`--since` override, release fallback, error surfaces, lockfile filtering), and the CLI envelope.
"""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev import changelog
from perk_dev.cli import cli

from perk.substrate import git


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


@pytest.fixture(scope="session")
def changelog_repo_factory(tmp_path_factory, git_repo_factory):
    template = git_repo_factory(tmp_path_factory.mktemp("changelog-repo-template"))
    base = _sha(template)

    (template / "a.txt").write_text("a\n", encoding="utf-8")
    _git(template, "add", ".")
    _git(template, "commit", "-qm", "add a (#101)")
    c1 = _sha(template)

    (template / "b.txt").write_text("b\n", encoding="utf-8")
    _git(template, "add", ".")
    _git(template, "commit", "-qm", "add b (#102)")
    c2 = _sha(template)

    def build(
        destination: Path, *, changelog_text: str | None = None
    ) -> tuple[Path, str, list[str]]:
        shutil.copytree(template, destination, dirs_exist_ok=True, symlinks=True)
        if changelog_text is not None:
            (destination / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
        return destination, base, [c1, c2]

    return build


def _changelog_repo(
    factory: Callable[..., tuple[Path, str, list[str]]],
    tmp_path: Path,
    *,
    changelog_text: str | None = None,
):
    """A repo with a base commit + two commits carrying `(#N)` subjects.

    Returns (root, base_sha, [c1_sha, c2_sha]). Writes the requested current `CHANGELOG.md`
    after copying the committed history.
    """
    return factory(tmp_path, changelog_text=changelog_text)


def test_gather_marker_discovery(tmp_path, changelog_repo_factory):
    root, base, _ = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n"
    )
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


def test_gather_flag_override(tmp_path, changelog_repo_factory):
    root, _base, (c1, _c2) = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n"
    )
    result = changelog.gather(root, since_flag=c1)
    assert result.since_source == "flag"
    assert result.since_commit == c1
    # Range starts after c1 -> only "add b".
    assert [c.subject for c in result.commits] == ["add b (#102)"]


def test_gather_release_fallback(tmp_path, changelog_repo_factory):
    root, base, _ = _changelog_repo(
        changelog_repo_factory,
        tmp_path,
        changelog_text="# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-01-01\n",
    )
    _git(root, "tag", "v1.2.3", base)
    result = changelog.gather(root, since_flag=None)
    assert result.since_source == "release-fallback"
    assert result.since_commit == base


def test_gather_marker_unresolvable(tmp_path, changelog_repo_factory):
    root, _base, _ = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n<!-- As of 0000000 -->\n"
    )
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag=None)
    assert exc.value.error_type == "marker_unresolvable"


def test_gather_changelog_not_found(tmp_path, changelog_repo_factory):
    root, _base, _ = _changelog_repo(changelog_repo_factory, tmp_path)  # no CHANGELOG.md written
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag=None)
    assert exc.value.error_type == "changelog_not_found"


def test_gather_release_tag_unresolvable(tmp_path, changelog_repo_factory):
    # A release header without its `v<version>` tag: the release-fallback ref cannot resolve.
    root, _base, _ = _changelog_repo(
        changelog_repo_factory,
        tmp_path,
        changelog_text="# Changelog\n\n## [Unreleased]\n\n## [9.9.9] - 2026-01-01\n",
    )
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag=None)
    assert exc.value.error_type == "release_tag_unresolvable"


def test_gather_since_unresolvable(tmp_path, changelog_repo_factory):
    root, _base, _ = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n"
    )
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag="no-such-ref")
    assert exc.value.error_type == "since_unresolvable"


def test_gather_no_since_reference(tmp_path, changelog_repo_factory):
    # CHANGELOG.md exists but has neither an `<!-- As of … -->` marker nor a release header.
    root, _base, _ = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n\n## [Unreleased]\n"
    )
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag=None)
    assert exc.value.error_type == "no_since_reference"


def test_gather_changelog_not_utf8(tmp_path, changelog_repo_factory):
    root, _base, _ = _changelog_repo(changelog_repo_factory, tmp_path)  # no CHANGELOG.md committed
    (root / "CHANGELOG.md").write_bytes(b"\xff\xfe")
    with pytest.raises(changelog.ChangelogError) as exc:
        changelog.gather(root, since_flag=None)
    assert exc.value.error_type == "changelog_not_utf8"


def test_gather_filters_lockfiles(tmp_path, changelog_repo_factory):
    root, _base, _ = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n"
    )
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


def test_cli_json(tmp_path, monkeypatch, changelog_repo_factory):
    root, _base, (c1, _c2) = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n"
    )
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["changelog-commits", "--since", c1, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert len(payload["since_commit"]) == 40
    assert len(payload["head_commit"]) == 40
    assert payload["since_source"] == "flag"
    assert payload["commits"][0]["pr"] == 102


def test_cli_default_summary(tmp_path, monkeypatch, changelog_repo_factory):
    root, _base, (c1, _c2) = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n"
    )
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


def test_cli_changelog_not_found(tmp_path, monkeypatch, changelog_repo_factory):
    root, _base, _ = _changelog_repo(changelog_repo_factory, tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["changelog-commits", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["error_type"] == "changelog_not_found"


def test_cli_git_error(tmp_path, monkeypatch, changelog_repo_factory):
    # cli.py resolves `changelog.gather` at call time, so the module-object patch takes effect.
    root, _base, _ = _changelog_repo(
        changelog_repo_factory, tmp_path, changelog_text="# Changelog\n"
    )
    monkeypatch.chdir(root)

    def raiser(*args, **kwargs):
        raise git.GitError("boom")

    monkeypatch.setattr(changelog, "gather", raiser)
    result = CliRunner().invoke(cli, ["changelog-commits", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "git_error"
    assert payload["message"] == "boom"


def test_cli_non_json_failure_rendering(tmp_path, monkeypatch, changelog_repo_factory):
    # CliRunner is non-tty, so `click.style` colors are stripped — assert plain substrings.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["changelog-commits"])
    assert result.exit_code == 2, result.output
    assert "Error: not inside a git repository" in result.stderr

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    root, _base, _ = _changelog_repo(changelog_repo_factory, repo_dir)  # no CHANGELOG.md
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["changelog-commits"])
    assert result.exit_code == 1, result.output
    assert "Error: " in result.stderr
    assert "CHANGELOG.md not found" in result.stderr
