"""`perk-dev release-tag` regression tests.

Covers the derived-name annotated tag creation, the already-at-HEAD no-op, the
`tag_conflict` refusal (an existing tag elsewhere — never silently no-op, never retag),
`--dry-run` (validates identically, writes nothing), `--push` against a bare origin, and
the refusal surfaces (`bad_version`, `no_remote`, `not_a_repo`).
"""

import subprocess

import pytest
from click.testing import CliRunner
from perk_dev import release
from perk_dev.cli import cli


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _sha(cwd, ref: str = "HEAD") -> str:
    return _git(cwd, "rev-parse", ref).strip()


def _tag_repo(tmp_path, *, version: str = "1.2.3"):
    root = tmp_path
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "perk tests")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


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


def _tag_names(root) -> set[str]:
    return set(_git(root, "tag", "--list").split())


# --- create / no-op / conflict ------------------------------------------------------


def test_creates_annotated_tag_at_head(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-tag"])
    assert result.exit_code == 0, result.output
    assert "created annotated tag v1.2.3" in result.stderr
    # Annotated: the tag ref names a tag OBJECT, not the commit directly.
    assert _git(root, "cat-file", "-t", "v1.2.3").strip() == "tag"
    assert _sha(root, "v1.2.3^{commit}") == _sha(root)


def test_rerun_noops_with_exit_0(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path)
    monkeypatch.chdir(root)
    runner = CliRunner()
    assert runner.invoke(cli, ["release-tag"]).exit_code == 0
    result = runner.invoke(cli, ["release-tag"])
    assert result.exit_code == 0, result.output
    assert "already at HEAD" in result.stderr


def test_tag_at_older_commit_is_conflict(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path)
    _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    _add_commit(root, "later")
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-tag"])
    assert result.exit_code == 1, result.output
    assert "refusing to retag" in result.stderr


def test_plan_conflict_names_both_commits(tmp_path):
    root = _tag_repo(tmp_path)
    old = _sha(root)
    _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    head = _add_commit(root, "later")
    with pytest.raises(release.ReleaseError) as exc:
        release.plan_release_tag(root)
    assert exc.value.error_type == "tag_conflict"
    assert old[:7] in exc.value.message and head[:7] in exc.value.message


# --- dry-run ------------------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-tag", "--dry-run", "--push"])
    assert result.exit_code == 0, result.output
    assert "would create annotated tag v1.2.3" in result.stderr
    assert "would push v1.2.3 to origin" in result.stderr
    assert _tag_names(root) == set()  # nothing written


def test_dry_run_still_fails_on_conflict(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path)
    _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    _add_commit(root, "later")
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-tag", "--dry-run"])
    assert result.exit_code == 1, result.output
    assert "refusing to retag" in result.stderr


# --- push ---------------------------------------------------------------------------


def test_push_lands_tag_in_origin_and_repush_noops(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path)
    bare = _add_bare_origin(root, tmp_path)
    monkeypatch.chdir(root)
    runner = CliRunner()
    result = runner.invoke(cli, ["release-tag", "--push"])
    assert result.exit_code == 0, result.output
    assert _git(bare, "rev-parse", "v1.2.3^{commit}").strip() == _sha(root)
    # Re-run: the tag no-ops locally AND the identical-tag re-push is a git no-op.
    result = runner.invoke(cli, ["release-tag", "--push"])
    assert result.exit_code == 0, result.output
    assert "already at HEAD" in result.stderr


def test_push_without_remote_fails(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-tag", "--push"])
    assert result.exit_code == 1, result.output
    assert "no `origin` remote" in result.stderr
    # The local tag WAS created before the push gate fired.
    assert _tag_names(root) == {"v1.2.3"}


# --- refusals -----------------------------------------------------------------------


def test_prerelease_version_refuses(tmp_path, monkeypatch):
    root = _tag_repo(tmp_path, version="1.2.3.dev1")
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["release-tag"])
    assert result.exit_code == 1, result.output
    assert "not a plain X.Y.Z version" in result.stderr
    assert _tag_names(root) == set()


def test_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["release-tag"])
    assert result.exit_code == 2, result.output


def test_release_tag_is_registered():
    assert "release-tag" in cli.commands
    # Structurally no tag-name argument: free-form names are refused by shape.
    params = {p.name for p in cli.commands["release-tag"].params}
    assert params == {"push", "dry_run"}
