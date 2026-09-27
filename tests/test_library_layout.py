"""The library layout: main-checkout resolution, the slug grammar and the kind-shaped entry path
rule (contracts.md §8.75(a)/(b))."""

import subprocess
from pathlib import Path

import pytest

from perk.library import layout
from perk.library.errors import LibraryError
from perk.substrate import paths


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60)


def test_library_dir_is_pure_construction(tmp_path):
    assert paths.library_dir(tmp_path) == tmp_path / "docs" / "library"
    assert paths.LIBRARY_REL == "docs/library"


def test_library_root_resolves_the_main_checkout_from_a_linked_worktree(git_repo):
    linked = git_repo / ".worktrees" / "lib-wt"
    _git(git_repo, "worktree", "add", "-q", "-b", "lib-wt", str(linked))
    main_root = layout.library_root(git_repo)
    assert main_root.resolve() == (git_repo / "docs" / "library").resolve()
    assert layout.library_root(linked).resolve() == main_root.resolve()
    from_linked = layout.LibraryLayout.for_repo(linked)
    assert from_linked.root.resolve() == main_root.resolve()
    assert from_linked.documentation == from_linked.root / "documentation"
    assert from_linked.source_code == from_linked.root / "source-code"
    assert from_linked.staging == from_linked.root / ".staging"
    assert from_linked.catalog_path == from_linked.root / "catalog.json"
    assert from_linked.readme_path == from_linked.root / "README.md"
    assert from_linked.content_roots == (from_linked.documentation, from_linked.source_code)
    assert from_linked.docs_entry_dir("pi") == from_linked.documentation / "pi"
    assert from_linked.relative(from_linked.docs_entry_dir("pi")) == "documentation/pi"


def test_library_root_falls_back_outside_a_repo(tmp_path):
    assert layout.library_root(tmp_path) == tmp_path / "docs" / "library"


@pytest.mark.parametrize("slug", ["pi", "dbt-duckdb", "a.b", "a_b", "0x", "a" * 64])
def test_validate_slug_accepts(slug):
    assert layout.validate_slug(slug) == slug


@pytest.mark.parametrize("slug", ["Pi", "-x", "a/b", "a..b", ".hidden", "a" * 65, "", "a b"])
def test_validate_slug_rejects(slug):
    with pytest.raises(LibraryError) as excinfo:
        layout.validate_slug(slug)
    assert excinfo.value.error_type == "invalid_slug"


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("docs", "documentation/pi"),
        ("docs", "documentation/dbt-duckdb"),
        ("source", "source-code/github.com/org/repo"),
        ("source", "source-code/gitlab.example.com/Org_1/repo.js"),
    ],
)
def test_entry_path_shape_accepts(kind, path):
    assert layout.entry_path_shape(kind, path)


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("docs", "documentation"),
        ("docs", "documentation/"),
        ("docs", "documentation/a/b"),
        ("docs", "documentation/Pi"),
        ("docs", "documentation/a..b"),
        ("source", "source-code/github.com/org"),
        ("source", "source-code/github.com/org/repo/extra"),
        ("docs", "../x"),
        ("docs", "/abs"),
        ("docs", "documentation/./pi"),
        ("docs", "documentation\\pi"),
        ("docs", "source-code/github.com/org/repo"),
        ("source", "documentation/pi"),
        ("source", "source-code/github.com/../repo"),
        ("docs", ""),
    ],
)
def test_entry_path_shape_rejects(kind, path):
    assert not layout.entry_path_shape(kind, path)
