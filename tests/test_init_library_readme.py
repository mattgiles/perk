"""The committed ``docs/library/README.md`` convergence (``perk init`` / ``perk doctor --fix``).

Converged only when ``docs/library/`` already exists in the invocation checkout; byte-exact,
idempotent, repaired on drift, refused through a symlinked library.
"""

from pathlib import Path

import pytest

from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import LIBRARY_README, converge_library_readme, run_init


def test_absent_directory_converges_to_nothing(tmp_path):
    assert converge_library_readme(tmp_path, apply=True) == []
    assert not (tmp_path / "docs").exists()


def test_present_directory_gets_the_exact_readme_and_is_idempotent(tmp_path):
    library = tmp_path / "docs" / "library"
    library.mkdir(parents=True)
    assert converge_library_readme(tmp_path, apply=False) == ["docs/library/README.md: created"]
    assert not (library / "README.md").exists()  # a dry run writes nothing
    assert converge_library_readme(tmp_path, apply=True) == ["docs/library/README.md: created"]
    assert (library / "README.md").read_bytes() == LIBRARY_README.encode("utf-8")
    assert converge_library_readme(tmp_path, apply=True) == []


def test_hand_edited_readme_is_restored(tmp_path):
    library = tmp_path / "docs" / "library"
    library.mkdir(parents=True)
    (library / "README.md").write_text("# mine\n", encoding="utf-8")
    assert converge_library_readme(tmp_path, apply=True) == ["docs/library/README.md: updated"]
    assert (library / "README.md").read_text(encoding="utf-8") == LIBRARY_README


def test_symlinked_library_is_refused(tmp_path, tmp_path_factory):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "library").symlink_to(
        tmp_path_factory.mktemp("elsewhere"), target_is_directory=True
    )
    with pytest.raises(UserFacingCliError) as excinfo:
        converge_library_readme(tmp_path, apply=True)
    assert excinfo.value.error_type == "library_symlink"


def test_symlinked_readme_leaf_is_refused_and_its_target_untouched(tmp_path):
    library = tmp_path / "docs" / "library"
    library.mkdir(parents=True)
    root_readme = tmp_path / "README.md"
    root_readme.write_text("ROOT README\n", encoding="utf-8")
    (library / "README.md").symlink_to(Path("..") / ".." / "README.md")
    for apply in (False, True):
        with pytest.raises(UserFacingCliError) as excinfo:
            converge_library_readme(tmp_path, apply=apply)
        assert excinfo.value.error_type == "library_symlink"
    assert root_readme.read_text(encoding="utf-8") == "ROOT README\n"


def test_non_regular_readme_is_refused(tmp_path):
    library = tmp_path / "docs" / "library"
    (library / "README.md").mkdir(parents=True)
    with pytest.raises(UserFacingCliError) as excinfo:
        converge_library_readme(tmp_path, apply=True)
    assert excinfo.value.error_type == "library_symlink"


def test_symlinked_docs_ancestor(tmp_path, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("docs-elsewhere")
    (tmp_path / "docs").symlink_to(elsewhere, target_is_directory=True)
    # No library behind the redirect: nothing to converge, never a surprise failure.
    assert converge_library_readme(tmp_path, apply=True) == []
    (elsewhere / "library").mkdir()
    with pytest.raises(UserFacingCliError) as excinfo:
        converge_library_readme(tmp_path, apply=True)
    assert excinfo.value.error_type == "library_symlink"
    assert not (elsewhere / "library" / "README.md").exists()


def test_readme_names_the_library_model():
    assert LIBRARY_README.startswith("# The perk library\n")
    for fragment in (
        "documentation/<slug>/",
        "source-code/<host>/<org>/<repo>/",
        "perk librarian record --publish",
        "catalog.json",
        "perk librarian list",
        "untrusted data",
        "Managed by `perk init` / `perk doctor --fix`.",
    ):
        assert fragment in LIBRARY_README


def test_run_init_twice_converges(git_repo):
    (git_repo / "docs" / "library").mkdir(parents=True)
    first = run_init(git_repo, verify=False)
    assert first.ok
    assert "docs/library/README.md: created" in first.changes
    second = run_init(git_repo, verify=False)
    assert second.ok
    assert second.changes == []
